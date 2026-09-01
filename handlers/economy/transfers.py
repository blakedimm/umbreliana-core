import re
import time
import asyncio
import json
import logging
import os
from aiogram import Router, types, F

# Импорты ядра
from core.database import get_db, resolve_user_id, add_to_dividend_pool
from handlers.users.quests import process_quest_action
from handlers.economy.loans import check_transfer_lock
from handlers.users.statuses import has_active_status

# Радар китов
from handlers.admin.eye_of_god import log_whale_transaction

router = Router()

# ==========================================
# 🛡 ФЕЙЛСЕЙФ СИСТЕМА: РЕЗЕРВНАЯ ЛОКАЛИЗАЦИЯ ДЛЯ ОНЛАЙНА
# ==========================================
FALLBACK_STRINGS = {}
try:
    if os.path.exists("locales/ru.json"):
        with open("locales/ru.json", "r", encoding="utf-8") as f:
            FALLBACK_STRINGS = json.load(f)
except Exception as e:
    logging.error(f"Критическая ошибка чтения резервного файла транзакций ru.json: {e}")

def local_fallback(key: str, **kwargs) -> str:
    text = FALLBACK_STRINGS.get(key, key)
    if kwargs:
        try: return text.format(**kwargs)
        except: pass
    return text

# ==========================================
# ⚙️ РЕГУЛЯРНЫЕ ВЫРАЖЕНИЯ (ОБНОВЛЕННЫЕ ПАТТЕРНЫ)
# ==========================================

# Обычные переводы (Добавлены: pay, send, transfer, give)
TRANSFER_ID_PATTERN = re.compile(
    r"^(?:п|передать|дать|перевод|перевести|отправить|кинуть|закинуть|переслать|pay|send|transfer|give)\s+([@\w]+)\s+(\d+[kкmм]*)(.*)$", 
    re.IGNORECASE | re.DOTALL
)
TRANSFER_REPLY_PATTERN = re.compile(
    r"^(?:п|передать|дать|перевод|перевести|отправить|кинуть|закинуть|переслать|pay|send|transfer|give)\s+(\d+[kкmм]*)(.*)$", 
    re.IGNORECASE | re.DOTALL
)

# Переводы Акций (Добавлены: sh, shares)
GOLD_TRANSFER_ID_PATTERN = re.compile(
    r"^(?:п|передать|дать|перевод|перевести|отправить|кинуть|закинуть|переслать|pay|send|transfer|give)\s+(?:голд|золото|gold|ug|sh|shares)\s+([@\w]+)\s+(\d+)(.*)$", 
    re.IGNORECASE | re.DOTALL
)
GOLD_TRANSFER_REPLY_PATTERN = re.compile(
    r"^(?:п|передать|дать|перевод|перевести|отправить|кинуть|закинуть|переслать|pay|send|transfer|give)\s+(?:голд|золото|gold|ug|sh|shares)\s+(\d+)(.*)$", 
    re.IGNORECASE | re.DOTALL
)

# Вспомогательная функция для парсинга сумм
def parse_amount(amount_str: str) -> int:
    clean_str = amount_str.lower().replace('к', '000').replace('k', '000').replace('м', '000000').replace('m', '000000')
    try:
        return int(clean_str)
    except ValueError:
        return 0

fmt = lambda x: f"{int(x):,}".replace(',', ' ')


# ==========================================
# 🧠 ЯДРО ЛОГИКИ ПЕРЕВОДОВ (ЕДИНОЕ)
# ==========================================

async def execute_umbrel_transfer(message: types.Message, sender_id: int, target_id: int, target_name: str, amount: int, comment: str, _):
    """Единый движок перевода UMBREL"""
    if amount <= 0:
        return await message.reply(_("tr_amount_low"))
    if sender_id == target_id:
        return await message.reply(_("tr_self"))

    can_transfer = await check_transfer_lock(sender_id)
    if not can_transfer:
        return await message.reply(_("tr_locked"))

    # 🔥 ПРОГРЕССИВНЫЙ НАЛОГ И ОФШОРЫ
    if await has_active_status(sender_id, 5):
        tax = int(amount * 0.05) # 5% фиксированный
        dividend_cut = int(amount * 0.01)
        net_amount = amount - tax
        tax_text = _("tr_tax_offshore", tax=fmt(tax))
    else:
        if amount < 10_000_000: tax_rate = 0.05
        elif amount < 50_000_000: tax_rate = 0.15
        elif amount < 500_000_000: tax_rate = 0.30
        else: tax_rate = 0.50

        tax = int(amount * tax_rate)
        dividend_cut = int(amount * 0.01)
        net_amount = amount - tax
        tax_text = _("tr_tax_standard", tax=fmt(tax), rate=int(tax_rate * 100))

    if net_amount <= 0:
        return await message.reply(_("tr_tax_ate_all"))

    pool = await get_db()
    try:
        async with pool.acquire() as db:
            async with db.transaction():
                current_balance = await db.fetchval("SELECT balance FROM users WHERE user_id = $1 FOR UPDATE", sender_id)
                if current_balance < amount:
                    return await message.reply(_("tr_no_money"))
                
                await db.execute("UPDATE users SET balance = balance - $1 WHERE user_id = $2", amount, sender_id)
                await db.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", net_amount, target_id)
                await db.execute(
                    "INSERT INTO transfers (sender_id, receiver_id, amount, timestamp) VALUES ($1, $2, $3, $4)",
                    sender_id, target_id, amount, int(time.time())
                )
                
                if amount >= 100_000_000:
                    asyncio.create_task(
                        log_whale_transaction(message.bot, sender_id, target_id, amount)
                    )
    except Exception as e:
        print(f"❌ Ошибка транзакции перевода: {e}")
        return await message.reply(_("tr_db_error"))

    if dividend_cut > 0:
        await add_to_dividend_pool(dividend_cut)

    await process_quest_action(sender_id, "transfer_send", amount)        
    await process_quest_action(sender_id, "transfer_send_total", amount)  
    await process_quest_action(target_id, "transfer_receive", 1)          

    comment_text = f"\n💬 <b>Комментарий:</b> {comment.strip()}" if comment.strip() else ""
    
    await message.reply(
        _("tr_success_msg", target_id=target_id, target_name=target_name, comment=comment_text, amount=fmt(amount), tax_text=tax_text, net=fmt(net_amount)),
        parse_mode="HTML"
    )

async def execute_gold_transfer(message: types.Message, sender_id: int, target_id: int, target_name: str, amount: int, _):
    """Единый движок перевода АКЦИЙ (БД: gold_balance)"""
    if amount <= 0:
        return await message.reply(_("tr_gold_amount_low"))
    if sender_id == target_id:
        return await message.reply(_("tr_gold_self"))

    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            sender_gold = await db.fetchval("SELECT gold_balance FROM users WHERE user_id = $1 FOR UPDATE", sender_id) or 0
            if sender_gold < amount:
                return await message.reply(_("tr_gold_no_asset", balance=sender_gold))
            
            await db.execute("INSERT INTO users (user_id) VALUES ($1) ON CONFLICT DO NOTHING", target_id)
            await db.execute("UPDATE users SET gold_balance = COALESCE(gold_balance, 0) - $1 WHERE user_id = $2", amount, sender_id)
            await db.execute("UPDATE users SET gold_balance = COALESCE(gold_balance, 0) + $1 WHERE user_id = $2", amount, target_id)

    await message.reply(
        _("tr_gold_success", amount=amount, target_id=target_id, target_name=target_name),
        parse_mode="HTML"
    )

# ==========================================
# 📖 ИНСТРУКЦИЯ ПО ПЕРЕВОДАМ (HELP COMMAND)
# ==========================================
@router.message(F.text.lower().strip().in_(["перевод", "transfer", "send help", "pay help"]))
async def cmd_transfer_help(message: types.Message, _ = None):
    if not _: _ = local_fallback
    await message.reply(_("tr_help_text"), parse_mode="HTML")

# ==========================================
# 📜 ХЭНДЛЕРЫ: АКЦИОНЕРНЫЕ ПЕРЕВОДЫ (SHARES)
# ==========================================

@router.message(F.text.regexp(GOLD_TRANSFER_ID_PATTERN))
async def gold_transfer_by_id(message: types.Message, _ = None):
    if not _: _ = local_fallback
    match = GOLD_TRANSFER_ID_PATTERN.match(message.text.lower())
    target_str = match.group(1)
    amount = int(match.group(2))

    target_id = await resolve_user_id(target_str)
    if not target_id:
        return await message.reply(_("tr_user_not_found"))

    await execute_gold_transfer(message, message.from_user.id, target_id, target_str, amount, _)

@router.message(F.text.regexp(GOLD_TRANSFER_REPLY_PATTERN))
async def gold_transfer_by_reply(message: types.Message, _ = None):
    if not _: _ = local_fallback
    if not message.reply_to_message:
        return await message.reply(_("tr_gold_reply_hint"))

    if message.reply_to_message.from_user.is_bot:
        return await message.reply(_("tr_bot_no_shares"))

    match = GOLD_TRANSFER_REPLY_PATTERN.match(message.text.lower())
    amount = int(match.group(1))

    target_id = message.reply_to_message.from_user.id
    target_name = message.reply_to_message.from_user.first_name

    await execute_gold_transfer(message, message.from_user.id, target_id, target_name, amount, _)

# ==========================================
# 💸 ХЭНДЛЕРЫ: ОБЫЧНЫЕ ПЕРЕВОДЫ (UMBREL)
# ==========================================

@router.message(F.text.regexp(TRANSFER_ID_PATTERN))
async def transfer_by_id(message: types.Message, _ = None):
    if not _: _ = local_fallback
    match = TRANSFER_ID_PATTERN.match(message.text.lower())
    target_str = match.group(1)
    amount = parse_amount(match.group(2))
    comment = match.group(3)

    target_id = await resolve_user_id(target_str)
    target_name = target_str 
    
    if target_id:
        try:
            member = await message.bot.get_chat_member(message.chat.id, target_id)
            target_name = member.user.first_name
        except:
            return await message.reply(_("tr_user_not_in_chat"))

    if not target_id:
        return await message.reply(_("tr_user_not_found"))

    await execute_umbrel_transfer(message, message.from_user.id, target_id, target_name, amount, comment, _)

@router.message(F.text.regexp(TRANSFER_REPLY_PATTERN))
async def transfer_by_reply(message: types.Message, _ = None):
    if not _: _ = local_fallback
    if not message.reply_to_message:
        return await message.reply(_("tr_reply_hint"))

    if message.reply_to_message.from_user.is_bot:
        return await message.reply(_("tr_bot_no_money"))

    match = TRANSFER_REPLY_PATTERN.match(message.text.lower())
    amount = parse_amount(match.group(1))
    comment = match.group(2)

    target_id = message.reply_to_message.from_user.id
    target_name = message.reply_to_message.from_user.first_name

    await execute_umbrel_transfer(message, message.from_user.id, target_id, target_name, amount, comment, _)