import os
import re
import math
import time
from datetime import datetime

from aiogram import Router, types, F, Bot
from aiogram.types import FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.database import (
    get_db, get_balance, add_balance, get_user_data, get_global_stats,
    get_transfer_logs, resolve_user_id
)
from handlers.users.statuses import has_active_status

router = Router()
TRANSFERS_PER_PAGE = 10

# ==========================================
# 🔐 СИСТЕМНЫЕ ПЕРЕМЕННЫЕ И ДОСТУПЫ (RBAC)
# ==========================================
ADMIN_ID = int(os.getenv("ADMIN_ID", 1412940726))

# Достаем список модераторов из .env и чистим от пробелов
MODERATORS = [int(i.strip()) for i in os.getenv("MODERATORS", "").split(",") if i.strip()]

def is_moderator(user_id):
    """Проверяет, является ли пользователь Создателем или Модератором"""
    return user_id == ADMIN_ID or user_id in MODERATORS

def fmt(num):
    return f"{int(num):,}".replace(",", " ")

async def get_target_id(message: types.Message):
    """Вспомогательная функция для поиска ID в реплаях или тексте"""
    if message.reply_to_message:
        return message.reply_to_message.from_user.id
    parts = message.text.split()
    if len(parts) > 1:
        return await resolve_user_id(parts[1]) 
    return None

import re

# ==========================================
# 🛠 УМНЫЙ ПАРСЕР СУММ ДЛЯ АДМИНОВ
# ==========================================
def parse_admin_amount(amount_str: str) -> int:
    """Переводит строки типа '100м', '5л', '2т' в целые числа"""
    clean_str = amount_str.lower().replace(" ", "")
    clean_str = clean_str.replace('к', '000').replace('k', '000')
    clean_str = clean_str.replace('м', '000000').replace('m', '000000')
    clean_str = clean_str.replace('л', '000000000').replace('l', '000000000') # лярды / миллиарды
    clean_str = clean_str.replace('т', '000000000000').replace('t', '000000000000') # триллионы
    
    try:
        return int(clean_str)
    except ValueError:
        return 0

# ==========================================
# 💰 ВЫДАТЬ И ЗАБРАТЬ UMBREL / GOLD (БРОНЕБОЙНЫЙ ПАРСЕР)
# ==========================================
@router.message((F.text.lower() == "выдать") | F.text.lower().startswith("выдать "))
async def admin_add_money(message: types.Message):
    user_id = message.from_user.id
    if not is_moderator(user_id):
        return

    # 1. Отрезаем команду
    raw_text = message.text[len("выдать"):].strip()
    
    # 1.5. Проверяем, это выдача голды или обычных денег?
    is_gold = False
    lower_text = raw_text.lower()
    for kw in ["голд", "золото", "gold", "ug"]:
        if lower_text.startswith(kw):
            is_gold = True
            # Отрезаем слово "голд", чтобы парсер дальше искал только ник и сумму
            raw_text = raw_text[len(kw):].strip()
            break

    if not raw_text:
        return await message.reply("⚠️ Укажи сумму. Пример: <code>выдать 1м</code> или <code>выдать голд 5</code>", parse_mode="HTML")

    target_id = None
    target_name = "Тебе"
    amount_str = ""

    # 2. Логика разбора (кому и сколько)
    if message.reply_to_message:
        # Если это реплай, то ВСЁ остальное — это сумма
        target_id = message.reply_to_message.from_user.id
        target_name = message.reply_to_message.from_user.first_name
        amount_str = raw_text
    else:
        # Разбиваем максимум на 2 части, чтобы отделить @юзера/ID от суммы
        parts = raw_text.split(maxsplit=1)
        first_arg = parts[0]

        # Если указан @юзер ИЛИ длинный ID (>=8 цифр) И при этом есть вторая часть (сумма)
        if first_arg.startswith('@') or (first_arg.isdigit() and len(first_arg) >= 8 and len(parts) > 1):
            target_id = await resolve_user_id(first_arg)
            if not target_id: 
                return await message.reply("❌ Игрок не найден.")
            target_name = f"Игроку {first_arg}"
            # Сумма - это всё, что после юзера
            amount_str = parts[1] if len(parts) > 1 else ""
        else:
            # Значит, цель не указана (выдача себе), а ВЕСЬ текст — это просто сумма
            target_id = user_id
            amount_str = raw_text

    # 3. Умный парсинг суммы
    amount = parse_admin_amount(amount_str)
    
    if amount <= 0:
        return await message.reply("⚠️ Некорректная сумма. Там есть недопустимые символы или она равна нулю.")

    # 4. Выдача
    executor = "Архитектор" if user_id == ADMIN_ID else "Модератор"
    
    if is_gold:
        pool = await get_db()
        async with pool.acquire() as db:
            await db.execute("INSERT INTO users (user_id) VALUES ($1) ON CONFLICT DO NOTHING", target_id)
            await db.execute("UPDATE users SET gold_balance = COALESCE(gold_balance, 0) + $1 WHERE user_id = $2", amount, target_id)
            new_bal = await db.fetchval("SELECT gold_balance FROM users WHERE user_id = $1", target_id)
        
        if target_id == user_id:
            await message.reply(f"🛡 {executor}: Начислено <b>{fmt(amount)}</b> Gold Umbrel 🟡.\nТеперь ваш резерв: <b>{fmt(new_bal)}</b> UG", parse_mode="HTML")
        else:
            await message.reply(f"🛡 {executor}: Успешно начислено <b>{fmt(amount)}</b> Gold Umbrel 🟡 пользователю <b>{target_name}</b>.", parse_mode="HTML")
    else:
        await add_balance(target_id, amount)
        if target_id == user_id:
            await message.reply(f"🛡 {executor}: Начислено <b>{fmt(amount)}</b> UMBREL.\nТеперь ваш баланс: <b>{fmt(await get_balance(target_id))}</b>", parse_mode="HTML")
        else:
            await message.reply(f"🛡 {executor}: Успешно начислено <b>{fmt(amount)}</b> UMBREL пользователю <b>{target_name}</b>.", parse_mode="HTML")

    # 🔔 УВЕДОМЛЕНИЕ АРХИТЕКТОРА (Если выдал Модератор)
    if user_id != ADMIN_ID:
        try:
            curr = "Gold Umbrel 🟡" if is_gold else "UMBREL"
            log_msg = (
                f"🚨 <b>ВНИМАНИЕ: ВЫДАЧА СРЕДСТВ</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 Модератор: <a href='tg://user?id={user_id}'>{message.from_user.first_name}</a> (<code>{user_id}</code>)\n"
                f"🎯 Получатель: <a href='tg://user?id={target_id}'>{target_name}</a> (<code>{target_id}</code>)\n"
                f"💰 Сумма: <b>{fmt(amount)} {curr}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
            await message.bot.send_message(ADMIN_ID, log_msg, parse_mode="HTML")
        except:
            pass

@router.message((F.text.lower() == "забрать") | F.text.lower().startswith("забрать "))
async def admin_take_money(message: types.Message):
    user_id = message.from_user.id
    if not is_moderator(user_id):
        return

    raw_text = message.text[len("забрать"):].strip()
    
    is_gold = False
    lower_text = raw_text.lower()
    for kw in ["голд", "золото", "gold", "ug"]:
        if lower_text.startswith(kw):
            is_gold = True
            raw_text = raw_text[len(kw):].strip()
            break

    if not raw_text:
        return await message.reply("⚠️ Укажи сумму. Пример: <code>забрать @юзер 1м</code> или <code>забрать голд @юзер 5</code>", parse_mode="HTML")

    target_id = None
    target_name = "Игрок"
    amount_str = ""

    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        target_name = message.reply_to_message.from_user.first_name
        amount_str = raw_text
    else:
        parts = raw_text.split(maxsplit=1)
        first_arg = parts[0]

        if first_arg.startswith('@') or (first_arg.isdigit() and len(first_arg) >= 8 and len(parts) > 1):
            target_id = await resolve_user_id(first_arg)
            if not target_id: 
                return await message.reply("❌ Игрок не найден.")
            target_name = first_arg
            amount_str = parts[1] if len(parts) > 1 else ""
        else:
            return await message.reply("⚠️ Ответь на сообщение или укажи цель: <code>забрать @юзер 1л</code>", parse_mode="HTML")

    # Умный парсинг суммы
    amount = parse_admin_amount(amount_str)
    
    if amount <= 0: 
        return await message.reply("⚠️ Некорректная сумма. Там есть недопустимые символы или она равна нулю.")

    # 🔥 ЗАЩИТА АРХИТЕКТОРА 🔥
    if target_id == ADMIN_ID and user_id != ADMIN_ID:
        return await message.reply("🤡 Попытка списать средства у Архитектора? Доступ отклонен.")

    if is_gold:
        pool = await get_db()
        async with pool.acquire() as db:
            current_bal = await db.fetchval("SELECT gold_balance FROM users WHERE user_id = $1", target_id) or 0
            if current_bal < amount: amount = current_bal
            if amount <= 0: return await message.reply(f"У <b>{target_name}</b> и так 0 UG.", parse_mode="HTML")
            
            await db.execute("UPDATE users SET gold_balance = gold_balance - $1 WHERE user_id = $2", amount, target_id)
            new_bal = current_bal - amount
            
        await message.reply(f"🔥 <b>Системное изъятие:</b>\nУ пользователя <b>{target_name}</b> изъято <b>{fmt(amount)}</b> Gold Umbrel 🟡.\nЕго остаток: <b>{fmt(new_bal)}</b> UG.", parse_mode="HTML")
    else:
        current_bal = await get_balance(target_id)
        if current_bal < amount: amount = current_bal
        if amount <= 0: return await message.reply(f"У <b>{target_name}</b> и так 0 UMBREL.", parse_mode="HTML")

        await add_balance(target_id, -amount)
        await message.reply(f"🔥 <b>Системное изъятие:</b>\nУ пользователя <b>{target_name}</b> изъято <b>{fmt(amount)}</b> UMBREL.\nЕго остаток: <b>{fmt(await get_balance(target_id))}</b> UMBREL.", parse_mode="HTML")

    # 🔔 УВЕДОМЛЕНИЕ АРХИТЕКТОРА (Если изъял Модератор)
    if user_id != ADMIN_ID:
        try:
            curr = "Gold Umbrel 🟡" if is_gold else "UMBREL"
            log_msg = (
                f"🕵️‍♂️ <b>ВНИМАНИЕ: ИЗЪЯТИЕ СРЕДСТВ</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 Модератор: <a href='tg://user?id={user_id}'>{message.from_user.first_name}</a> (<code>{user_id}</code>)\n"
                f"🎯 Цель: <a href='tg://user?id={target_id}'>{target_name}</a> (<code>{target_id}</code>)\n"
                f"🔥 Изъято: <b>{fmt(amount)} {curr}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
            await message.bot.send_message(ADMIN_ID, log_msg, parse_mode="HTML")
        except:
            pass
            
# ==========================================
# 🏦 БАНК: ИЗЪЯТЬ С ДЕПОЗИТА
# ==========================================
ADMIN_TAKE_DEP_PATTERN = re.compile(r"^-(?:деп|депозит)\s+([@\w]+)?\s*([\d\s]+)$", re.IGNORECASE)

@router.message(F.text.regexp(ADMIN_TAKE_DEP_PATTERN))
async def admin_take_deposit(message: types.Message):
    user_id = message.from_user.id
    if not is_moderator(user_id):
        return

    match = ADMIN_TAKE_DEP_PATTERN.match(message.text.lower())
    target_str = match.group(1)
    amount_str = match.group(2).replace(' ', '')
    
    if not target_str and not message.reply_to_message:
         return await message.reply("⚠️ Чтобы снять с депозита, ответь на сообщение или укажи цель: <code>-депозит @юзер 1000</code>", parse_mode="HTML")

    amount = int(amount_str)
    target_id = None
    target_name = "Игрок"

    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        target_name = message.reply_to_message.from_user.first_name
        if not match.group(2).strip(): 
             amount = int(target_str.replace(' ', '')) 
             target_str = None
             
    elif target_str:
        target_id = await resolve_user_id(target_str)
        if not target_id:
            return await message.reply("❌ Игрок не найден в базе данных.")
        target_name = target_str

    # 🔥 ЗАЩИТА АРХИТЕКТОРА 🔥
    if target_id == ADMIN_ID and user_id != ADMIN_ID:
        return await message.reply("🤡 Счета Архитектора неприкосновенны. Запрос аннулирован.")

    if amount <= 0: return await message.reply("⚠️ Сумма изъятия должна быть больше нуля.")
    if target_id == message.from_user.id: return await message.reply("🤡 Пытаешься ограбить сам себя? Отменено.")

    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            current_dep = await db.fetchval("SELECT amount FROM deposits WHERE user_id = $1 FOR UPDATE", target_id)
            
            if current_dep is None:
                return await message.reply(f"У <b>{target_name}</b> нет открытого вклада в банке.", parse_mode="HTML")
            if current_dep == 0:
                return await message.reply(f"В сейфе у <b>{target_name}</b> и так 0 UMBREL.", parse_mode="HTML")
            
            if current_dep < amount: amount = current_dep
                
            await db.execute("UPDATE deposits SET amount = amount - $1 WHERE user_id = $2", amount, target_id)
            
    await message.reply(
        f"🏦 <b>Банковский арест:</b>\n"
        f"С депозита пользователя <b>{target_name}</b> изъято <b>{fmt(amount)}</b> UMBREL.\n"
        f"Остаток в сейфе: <b>{fmt(current_dep - amount)}</b> UMBREL.",
        parse_mode="HTML"
    )


from core.redis_driver import get_active_game  # 🔥 НЕ ЗАБУДЬ ЭТОТ ИМПОРТ В НАЧАЛО ФАЙЛА

# ==========================================
# 🔎 КОМАНДА: ЧЕК (ПРОФИЛЬ + LIVE АКТИВНОСТЬ)
# ==========================================
@router.message(F.text.lower().startswith("чек") & (~F.text.lower().startswith("чекдолг")) & (~F.text.lower().startswith("чек ферма")) & (~F.text.lower().startswith("чек депозит")))
async def admin_check_info(message: types.Message):
    user_id = message.from_user.id
    if not (user_id == ADMIN_ID or await has_active_status(user_id, 777) or await has_active_status(user_id, 4)):
        return

    target_id = await get_target_id(message)
    if not target_id:
        return await message.reply("⚠️ Ответь на сообщение или укажи ID / @username")

    user_data = await get_user_data(target_id)
    if not user_data:
        return await message.reply("❌ Игрок не найден в базе данных.")

    balance = await get_balance(target_id)
    debt = user_data.get('debt', 0)
    
    # 🔥 Спрашиваем у Redis, во что играет юзер прямо сейчас 🔥
    active_game = await get_active_game(target_id)
    games_text = f" ├ 🎮 <b>{active_game}</b> (в процессе)" if active_game else " └ <i>Нет активных сессий</i>"

    try:
        target_user = await message.bot.get_chat(target_id)
        target_name = target_user.first_name
        username = target_user.username or "нет"
    except:
        target_name = f"Игрок {target_id}"
        username = "нет"
    
    text = f"""
👁 <b>СЕКРЕТНОЕ ДОСЬЕ:</b>
━━━━━━━━━━━━━━━━━━━━
🆔 ID: <code>{target_id}</code>
📛 Имя: <b>{target_name}</b>
🏷 Username: @{username}

💰 <b>ФИНАНСЫ:</b>
━━━━━━━━━━━━━━━━━━━━
💵 UMBREL: <b>{fmt(balance)}</b>
💸 Долг: <b>{fmt(debt)}</b>

🎮 <b>АКТИВНЫЕ ОПЕРАЦИИ (LIVE):</b>
━━━━━━━━━━━━━━━━━━━━
{games_text}
"""
    await message.reply(text, parse_mode="HTML")


# ==========================================
# 🏦 КОМАНДА: ЧЕК ДЕПОЗИТ (FIXED)
# ==========================================
@router.message(F.text.lower().startswith("чек депозит"))
async def admin_check_deposit(message: types.Message):
    user_id = message.from_user.id
    if not (user_id == ADMIN_ID or await has_active_status(user_id, 777) or await has_active_status(user_id, 4)):
        return

    target_id = None
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
    else:
        parts = message.text.split()
        if len(parts) >= 3:
            target_id = await resolve_user_id(parts[-1])

    if not target_id:
        return await message.reply("⚠️ Ответь на сообщение или укажи ID / @username")

    pool = await get_db()
    async with pool.acquire() as db:
        # Получаем данные и сразу преобразуем в обычный словарь для безопасности
        row = await db.fetchrow("SELECT * FROM deposits WHERE user_id = $1", target_id)
        
    if not row:
        return await message.reply("🏦 У этого агента <b>нет открытых депозитов</b>.", parse_mode="HTML")

    # Превращаем запись в словарь, чтобы работали безопасные методы .get()
    dep = dict(row)
    
    # Пытаемся достать проценты (проверяем все возможные имена колонок)
    interest = dep.get('interest') or dep.get('accrued_interest') or dep.get('profit') or 0
    amount = dep.get('amount', 0)
    created_at = dep.get('created_at', 'неизвестно')

    text = f"""
🏦 <b>БАНКОВСКАЯ ВЫПИСКА:</b>
━━━━━━━━━━━━━━━━━━━━
👤 Агент: <code>{target_id}</code>

📈 Тело вклада: <b>{fmt(amount)} ᴜ</b>
➕ Накопленный процент: <b>{fmt(interest)} ᴜ</b>
📅 Дата открытия: <code>{created_at}</code>

💰 <b>ИТОГО К ВЫДАЧЕ: {fmt(amount + interest)} ᴜ</b>
"""
    await message.reply(text, parse_mode="HTML")

# ==========================================
# 👑 СТАТУСЫ (ВЫДАТЬ И ЗАБРАТЬ) - БРОНЕБОЙНАЯ ВЕРСИЯ
# ==========================================
@router.message(F.text.lower().startswith("+статус") & (F.from_user.id == ADMIN_ID))
async def admin_add_status(message: types.Message):
    # Отрезаем саму команду
    parts = message.text.lower().split()[1:]
    
    target_id = None
    
    # 1. ОПРЕДЕЛЯЕМ ЦЕЛЬ (Кому выдаем)
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
    elif len(parts) > 0 and (parts[0].startswith('@') or (parts[0].isdigit() and len(parts[0]) >= 8)):
        # Если первое слово @юзер или длинный ID
        from core.database import resolve_user_id
        target_id = await resolve_user_id(parts[0])
        parts = parts[1:] # Отрезаем цель из списка аргументов, чтобы остались только статусы
    else:
        # Если ни реплая, ни @юзера нет — выдаем самому себе
        target_id = message.from_user.id
        
    if not target_id:
        return await message.reply("❌ Цель не найдена.")

    # 2. СОБИРАЕМ ЧИСЛА (Статусы и сроки)
    numbers = [int(x) for x in parts if x.isdigit()]
    
    days = 7
    statuses_to_give = []
    
    # 3. УМНАЯ ЛОГИКА СРОКА
    if "навсегда" in parts:
        days = 36500
        statuses_to_give = numbers
    elif len(numbers) >= 2:
        days = numbers[-1] # Последняя цифра - срок
        statuses_to_give = numbers[:-1] # Все остальные - статусы
    elif len(numbers) == 1:
        days = 7 # По умолчанию на 7 дней
        statuses_to_give = numbers
    else:
        return await message.reply("❌ Укажи ID статуса. Пример: <code>+статус 777 навсегда</code>", parse_mode="HTML")
        
    if not statuses_to_give:
        return await message.reply("❌ Ошибка. Не найдены ID статусов.")
        
    expire_ts = int(time.time()) + days * 86400
    
    pool = await get_db()
    async with pool.acquire() as db:
        for s_id in statuses_to_give:
            await db.execute(
                "INSERT INTO user_statuses (user_id, status_id, expire_timestamp) "
                "VALUES ($1, $2, $3) "
                "ON CONFLICT(user_id, status_id) "
                "DO UPDATE SET expire_timestamp = GREATEST(user_statuses.expire_timestamp, EXCLUDED.expire_timestamp)", 
                target_id, s_id, expire_ts
            )
            
    time_text = "НАВСЕГДА 💎" if days > 10000 else f"на {days} дней"
    await message.reply(f"✅ Статусы <b>{statuses_to_give}</b> выданы {time_text}.", parse_mode="HTML")

@router.message(F.text.lower().startswith("-статус") & (F.from_user.id == ADMIN_ID))
async def admin_remove_status(message: types.Message):
    parts = message.text.lower().split()[1:]
    
    target_id = None
    
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
    elif len(parts) > 0 and (parts[0].startswith('@') or (parts[0].isdigit() and len(parts[0]) >= 8)):
        from core.database import resolve_user_id
        target_id = await resolve_user_id(parts[0])
        parts = parts[1:]
    else:
        target_id = message.from_user.id
        
    if not target_id: 
        return await message.reply("❌ Ошибка формата! Цель не найдена.")

    statuses_to_remove = [int(x) for x in parts if x.isdigit()]
    
    if not statuses_to_remove:
        return await message.reply("❌ Укажи ID статуса для удаления.")

    pool = await get_db()
    async with pool.acquire() as db:
        for s_id in statuses_to_remove:
            await db.execute("DELETE FROM user_statuses WHERE user_id = $1 AND status_id = $2", target_id, s_id)

    await message.reply(f"🚫 <b>Статусы {statuses_to_remove} аннулированы</b> для <code>{target_id}</code>.", parse_mode="HTML")

# ==========================================
# 🕵️ ШПИОН И ПРОФАЙЛЕР (ГЛАЗ БОГА)
# ==========================================
@router.message(F.text.lower().startswith("шпион"), F.from_user.id == ADMIN_ID)
async def cmd_spy_user(message: types.Message):
    target_id = await get_target_id(message)

    if not target_id:
        return await message.reply(
            "⚠️ Укажи ID, @username или ответь на сообщение подозреваемого.\n"
            "Пример: <code>шпион @elon_ov</code>", 
            parse_mode="HTML"
        )

    pool = await get_db()
    async with pool.acquire() as db:
        rows = await db.fetch("""
            SELECT type, amount 
            FROM audit_log 
            WHERE user_id = $1 AND amount >= 1000000
            ORDER BY id DESC 
            LIMIT 20
        """, target_id)
        
    if not rows:
        return await message.reply(f"🕵️ Логи пусты. Игрок <code>{target_id}</code> чист (или багует по-мелкому).", parse_mode="HTML")
        
    text = f"🕵️ <b>ПОСЛЕДНИЕ КРУПНЫЕ ДОХОДЫ [{target_id}]:</b>\n"
    for r in rows:
        text += f"▪️ Тип: <code>{r['type']}</code> | Сумма: <b>{fmt(r['amount'])} ᴜ</b>\n"
        
    await message.reply(text, parse_mode="HTML")

@router.message(F.text.lower().startswith("проверка на вшивость") & (F.from_user.id == ADMIN_ID))
async def admin_integrity_check(message: types.Message):
    target_id = None
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
    else:
        raw_arg = message.text[len("проверка на вшивость"):].strip()
        if raw_arg: 
            target_id = await resolve_user_id(raw_arg)

    if not target_id:
        return await message.reply("⚠️ Объект не найден. Укажи корректный ID или юзернейм.", parse_mode="HTML")

    status_msg = await message.reply("👁‍🗨 <b>Запрос к ядру профайлинга...</b>", parse_mode="HTML")
    
    try: 
        from core.database import build_security_profile
        report = await build_security_profile(target_id)
        final_text = f"👁‍🗨 <b>ПРОФАЙЛ:</b> <code>{target_id}</code>\n{report}"
        await status_msg.edit_text(final_text, parse_mode="HTML")
    except Exception as e:
        import logging
        logging.exception("Ошибка в нейро-сканере!")
        await status_msg.edit_text(f"❌ <b>Критический сбой анализатора:</b>\n<code>{e}</code>", parse_mode="HTML")

# ==========================================
# 📊 ЛОГИ И СТАТИСТИКА
# ==========================================
@router.message((F.text.lower() == "логи") & (F.from_user.id == ADMIN_ID))
async def send_logs_file(message: types.Message):
    log_file_path = "bot_errors.log"
    if os.path.exists(log_file_path):
        try:
            await message.reply_document(FSInputFile(log_file_path), caption="📋 <b>Бортовой журнал UMBREL</b>")
        except Exception as e:
            await message.reply(f"❌ Ошибка: {e}")
    else:
        await message.reply("❓ Файл логов еще не создан.")

@router.message((F.text.lower().startswith("логи ")) & (F.from_user.id == ADMIN_ID))
async def check_user_logs(message: types.Message):
    target_id = await get_target_id(message)
    if not target_id: return await message.reply("⚠️ Формат: `логи [ID]`")
        
    logs = await get_transfer_logs(target_id, limit=7)
    if not logs: return await message.reply(f"📁 История переводов игрока <code>{target_id}</code> пуста.")
        
    text = f"📑 <b>ПОСЛЕДНИЕ ТРАНЗАКЦИИ:</b> <code>{target_id}</code>\n━━━━━━━━━━━━━━━━━━━━\n"
    for s_id, r_id, amt, ts in logs:
        time_str = datetime.fromtimestamp(ts).strftime('%d.%m %H:%M')
        if s_id == target_id: text += f"🔴 {time_str} | <b>-{fmt(amt)}</b> ᴜ ➡️ <code>{r_id}</code>\n"
        else: text += f"🟢 {time_str} | <b>+{fmt(amt)}</b> ᴜ ⬅️ <code>{s_id}</code>\n"
    await message.reply(text, parse_mode="HTML")

# ==========================================
# 👁‍🗨 КОНСОЛЬ АРХИТЕКТОРА (ГЛОБАЛЬНАЯ СТАТИСТИКА)
# ==========================================
@router.message((F.text.lower() == "админ стата") & (F.from_user.id == ADMIN_ID))
async def admin_global_stats(message: types.Message, bot: Bot):
    wait_msg = await message.reply("⏳ <i>Генерация отчета Архитектора...</i>", parse_mode="HTML")
    s = await get_global_stats()
    if not s: 
        return await wait_msg.edit_text("❌ <b>Сбой систем аналитики.</b>", parse_mode="HTML")
    
    # 🔥 СОБИРАЕМ ID, КОТОРЫЕ НУЖНО СКРЫТЬ ИЗ ТОПОВ 🔥
    # (Предполагается, что MODERATORS импортирован из конфига как список int)
    excluded_ids = [ADMIN_ID]
    if isinstance(MODERATORS, list):
        excluded_ids.extend(MODERATORS)
    
    pool = await get_db()
    async with pool.acquire() as db:
        # Статистика групп
        total_chats = await db.fetchval("SELECT COUNT(DISTINCT chat_id) FROM chat_members WHERE chat_id IS NOT NULL") or 0
        top_chats = await db.fetch("""
            SELECT chat_id, COUNT(user_id) as member_count 
            FROM chat_members 
            WHERE chat_id IS NOT NULL
            GROUP BY chat_id 
            ORDER BY member_count DESC 
            LIMIT 3
        """)

        # 🔥 ИСТИННАЯ МАКРОЭКОНОМИКА (ВЫЧИТАЕМ АДМИНОВ ИЗ ОБОРОТА) 🔥
        totals = await db.fetchrow("""
            SELECT 
                SUM(balance) as real_balance, 
                SUM(debt) as real_debt, 
                SUM(gold_balance) as real_gold
            FROM users 
            WHERE user_id != ALL($1::bigint[])
        """, excluded_ids)
        
        s['total_balance'] = totals['real_balance'] or 0
        s['total_debt'] = totals['real_debt'] or 0
        total_gold = totals['real_gold'] or 0
        
        gold_holders = await db.fetchval("""
            SELECT COUNT(*) FROM users 
            WHERE gold_balance > 0 AND user_id != ALL($1::bigint[])
        """, excluded_ids) or 0
        
        dividend_pool = await db.fetchval("SELECT value_int FROM system_stats WHERE key = 'dividend_pool'") or 0
        
        # Топ 3 держателя Золота (Скрываем админов)
        top_gold = await db.fetch("""
            SELECT user_id, telegram_username, gold_balance 
            FROM users 
            WHERE gold_balance > 0 AND user_id != ALL($1::bigint[])
            ORDER BY gold_balance DESC 
            LIMIT 3
        """, excluded_ids)

        # 🔥 ПЕРЕХВАТЫВАЕМ ТОПЫ ИЗ get_global_stats И ФИЛЬТРУЕМ ИХ 🔥
        top_rich_rows = await db.fetch("""
            SELECT nickname, balance, user_id FROM users 
            WHERE balance > 0 AND user_id != ALL($1::bigint[])
            ORDER BY balance DESC LIMIT 3
        """, excluded_ids)
        s['top_rich'] = [(r['nickname'] or f"Агент {r['user_id']}", r['balance']) for r in top_rich_rows]

        top_debtors_rows = await db.fetch("""
            SELECT nickname, debt, user_id FROM users 
            WHERE debt > 0 AND user_id != ALL($1::bigint[])
            ORDER BY debt DESC LIMIT 3
        """, excluded_ids)
        s['top_debtors'] = [(r['nickname'] or f"Агент {r['user_id']}", r['debt']) for r in top_debtors_rows]

    try:
        star_balance = await bot.get_my_star_balance()
        bot_stars_text = f"<b>{fmt(star_balance.amount)} ⭐️</b>"
    except Exception as e:
        bot_stars_text = "<i>Недоступно (Ошибка API)</i>"

    # Обработка чатов
    chat_list_text = ""
    if top_chats:
        for i, row in enumerate(top_chats, 1):
            chat_id, count = row['chat_id'], row['member_count']
            try:
                chat_info = await bot.get_chat(chat_id)
                chat_title = chat_info.title or f"Чат {chat_id}"
            except Exception:
                chat_title = f"Недоступный узел ({chat_id})"
            chat_list_text += f" ├ {i}. <b>{chat_title}</b>: {count} чел.\n"
    else:
        chat_list_text = " └ <i>Групп нет</i>\n"

    # Обработка списков игроков (уже отфильтрованных)
    rich_list = "\n".join([f" ├ {name}: <b>{fmt(bal)}</b> ᴜ" for name, bal in s['top_rich']]) or " └ <i>Пусто</i>"
    debt_list = "\n".join([f" ├ {name}: <b>{fmt(d)}</b> ᴜ" for name, d in s['top_debtors']]) or " └ <i>Должников нет</i>"
    
    # Форматирование золотого топа
    gold_list = ""
    if top_gold:
        for row in top_gold:
            if row['telegram_username']:
                name = f"@{row['telegram_username']}"
            else:
                name = f"<a href='tg://user?id={row['user_id']}'>Агент {row['user_id']}</a>"
            gold_list += f" ├ {name}: <b>{fmt(row['gold_balance'])}</b> 🟡\n"
    else:
        gold_list = " └ <i>Нет акционеров</i>\n"

    # Генерация интерфейса
    text = (
        f"👁‍🗨 <b>КОНСОЛЬ АРХИТЕКТОРА | UMBRELIANA</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 <b>ДЕМОГРАФИЯ</b>\n"
        f"├ Всего пользователей: <b>{fmt(s['total_users'])}</b>\n"
        f"└ Онлайн 24ч: <b>{fmt(s['active_24h'])}</b>\n\n"
        
        f"🌐 <b>ТОПОЛОГИЯ СЕТИ</b>\n"
        f"├ Активных узлов: <b>{total_chats}</b>\n"
        f"🏆 Топ-3 группы:\n{chat_list_text}\n"
        
        f"💰 <b>БАЗОВАЯ ЭКОНОМИКА (UMBREL)</b>\n"
        f"├ В обороте: <b>{fmt(s['total_balance'])} ᴜ</b>\n"
        f"└ Кредитный долг: <b>{fmt(s['total_debt'])} ᴜ</b>\n\n"

        f"🟡 <b>ЭЛИТНАЯ ЭКОНОМИКА (GOLD)</b>\n"
        f"├ Эмиссия: <b>{fmt(total_gold)} 🟡 UG</b>\n"
        f"├ Акционеров: <b>{fmt(gold_holders)}</b> чел.\n"
        f"└ Общак Синдиката: <b>{fmt(dividend_pool)} ᴜ</b>\n\n"
        
        f"🏭 <b>ПРОМЫШЛЕННОСТЬ</b>\n"
        f"├ Активных ферм: <b>{fmt(s['active_farms'])}</b>\n"
        f"└ GPU в работе: <b>{fmt(s['total_gpus'])} шт.</b>\n\n"
        
        f"⭐️ <b>КАССА TELEGRAM</b>\n"
        f"└ Баланс бота: {bot_stars_text}\n\n"

        f"🏆 <b>ТОП-3 МАГНАТА (UMBREL)</b>\n{rich_list}\n\n"
        f"👑 <b>ТОП-3 СУВЕРЕНА (GOLD)</b>\n{gold_list}\n\n"
        f"💀 <b>ТОП-3 ДОЛЖНИКА</b>\n{debt_list}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    
    await wait_msg.edit_text(text, parse_mode="HTML")

# ==========================================
# 👁‍🗨 ПОЛНАЯ СТАТИСТИКА АДМИНИСТРАТОРА
# ==========================================

@router.message((F.text.lower() == "админ стата полная") & (F.from_user.id == ADMIN_ID))
async def admin_full_stats_menu(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 Экономика", callback_data="fullstat_eco")
    builder.button(text="🎰 Казино", callback_data="fullstat_casino")
    builder.button(text="🏭 Промышленность", callback_data="fullstat_farm")
    builder.button(text="⚙️ Инфраструктура", callback_data="fullstat_infra")
    builder.adjust(2, 2)

    await message.reply(
        "👁‍🗨 <b>ГЛОБАЛЬНАЯ КОНСОЛЬ АРХИТЕКТОРА</b>\n"
        "Выберите модуль для сканирования:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("fullstat_") & (F.from_user.id == ADMIN_ID))
async def process_fullstat_callback(callback: types.CallbackQuery):
    tab = callback.data.split("_")[1]
    text = ""
    
    pool = await get_db()
    async with pool.acquire() as db:
        if tab == "eco":
            excluded_ids = [ADMIN_ID]
            if isinstance(MODERATORS, list):
                excluded_ids.extend(MODERATORS)
            
            p2p_all = await db.fetchval("SELECT SUM(amount) FROM transfers WHERE sender_id != ALL($1::bigint[]) AND receiver_id != ALL($1::bigint[])", excluded_ids) or 0
            day_ago = int(time.time()) - 86400
            p2p_24h = await db.fetchval("SELECT SUM(amount) FROM transfers WHERE timestamp >= $1 AND sender_id != ALL($2::bigint[]) AND receiver_id != ALL($2::bigint[])", day_ago, excluded_ids) or 0
            
            totals = await db.fetchrow("SELECT COALESCE(SUM(balance), 0) as b, COALESCE(SUM(debt), 0) as d, COALESCE(SUM(gold_balance), 0) as g FROM users WHERE user_id != ALL($1::bigint[])", excluded_ids)
            deposits = await db.fetchval("SELECT SUM(amount) FROM deposits WHERE user_id != ALL($1::bigint[])", excluded_ids) or 0
            clans_bal = await db.fetchval("SELECT SUM(balance) FROM clans") or 0
            
            poor = await db.fetchval("SELECT COUNT(*) FROM users WHERE balance < 10000 AND user_id != ALL($1::bigint[])", excluded_ids) or 0
            rich = await db.fetchval("SELECT COUNT(*) FROM users WHERE balance >= 10000000 AND user_id != ALL($1::bigint[])", excluded_ids) or 0
            debtors = await db.fetchval("SELECT COUNT(*) FROM users WHERE debt > 0 AND user_id != ALL($1::bigint[])", excluded_ids) or 0
            
            text = (
                f"💰 <b>МАКРОЭКОНОМИКА СИНДИКАТА</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"💵 <b>Эмиссия и Резервы:</b>\n"
                f"├ На руках (UMBREL): <b>{fmt(totals['b'])} ᴜ</b>\n"
                f"├ Золотой запас (GOLD): <b>{fmt(totals['g'])} 🟡</b>\n"
                f"├ В банке (Вклады): <b>{fmt(deposits)} ᴜ</b>\n"
                f"└ Казна кланов: <b>{fmt(clans_bal)} ᴜ</b>\n\n"
                f"🔄 <b>Движение капитала (P2P):</b>\n"
                f"├ Оборот за 24ч: <b>{fmt(p2p_24h)} ᴜ</b>\n"
                f"└ Оборот за всё время: <b>{fmt(p2p_all)} ᴜ</b>\n\n"
                f"📉 <b>Кредиты и расслоение:</b>\n"
                f"├ Общий долг системы: <b>{fmt(totals['d'])} ᴜ</b>\n"
                f"├ Должников: <b>{fmt(debtors)}</b> чел.\n"
                f"├ Киты (>10М ᴜ): <b>{fmt(rich)}</b> чел.\n"
                f"└ Бедняки (<10К ᴜ): <b>{fmt(poor)}</b> чел.\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )

        elif tab == "casino":
            try:
                total_spins = await db.fetchval("SELECT COUNT(*) FROM roulette_history") or 0
                r_stats = await db.fetchrow("""
                    SELECT 
                        COALESCE(SUM(total_spins), 0) as u_spins, 
                        COALESCE(SUM(total_wins), 0) as u_wins, 
                        COALESCE(MAX(biggest_win), 0) as max_win, 
                        COALESCE(SUM(jackpots_won), 0) as total_jps 
                    FROM user_roulette_stats
                """)
                gh_stats = await db.fetchrow("SELECT COUNT(*) as total_g, COALESCE(SUM(is_win), 0) as total_w FROM user_game_history")
                
                jp1 = await db.fetchval("SELECT amount FROM jackpot LIMIT 1") or 0
                try:
                    jp2 = await db.fetchval("SELECT pool FROM roulette_jackpot LIMIT 1") or 0
                    current_jp = max(jp1, jp2)
                except:
                    current_jp = jp1

                all_games = gh_stats['total_g'] if gh_stats else 0
                all_wins = gh_stats['total_w'] if gh_stats else 0
                global_wr = (all_wins / all_games * 100) if all_games > 0 else 0

                text = (
                    f"🎰 <b>ТЕНЕВОЕ КАЗИНО</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🎲 <b>Глобальная активность:</b>\n"
                    f"├ Сыграно игр (Все режимы): <b>{fmt(all_games)}</b>\n"
                    f"├ Общих побед: <b>{fmt(all_wins)}</b>\n"
                    f"└ Глобальный WinRate: <b>{global_wr:.1f}%</b>\n\n"
                    f"🎯 <b>Статистика Рулетки:</b>\n"
                    f"├ Всего запусков колеса: <b>{fmt(total_spins)}</b>\n"
                    f"├ Сделано ставок: <b>{fmt(r_stats['u_spins'])}</b>\n"
                    f"└ Зашло ставок: <b>{fmt(r_stats['u_wins'])}</b>\n\n"
                    f"💰 <b>Финансы казино:</b>\n"
                    f"├ Текущий Джекпот: <b>{fmt(current_jp)} ᴜ</b>\n"
                    f"├ Сорвано джекпотов: <b>{fmt(r_stats['total_jps'])}</b> раз\n"
                    f"└ Рекордный занос: <b>{fmt(r_stats['max_win'])} ᴜ</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━"
                )
            except Exception as e:
                text = f"🎰 <b>КАЗИНО:</b>\n<i>Нет данных или ошибка БД: {e}</i>"

        elif tab == "farm":
            try:
                f_stats = await db.fetchrow("SELECT COUNT(DISTINCT user_id) as farms, COALESCE(SUM(qty), 0) as gpus, COALESCE(AVG(condition), 0) as avg_cond, COALESCE(SUM(was_repaired), 0) as reps, COALESCE(MAX(multiplier), 0) as max_m FROM gpu_batches WHERE condition > 0")
                avg_cool = await db.fetchval("SELECT AVG(cooling_level) FROM farms") or 1.0
                m_stats = await db.fetchrow("SELECT COUNT(*) as lots, COALESCE(SUM(price), 0) as val, COALESCE(SUM(deposit), 0) as dep FROM market")

                text = (
                    f"🏭 <b>ПРОМЫШЛЕННОСТЬ И РЫНОК</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🖥 <b>Состояние оборудования:</b>\n"
                    f"├ Активных ферм: <b>{fmt(f_stats['farms'])}</b>\n"
                    f"├ GPU в работе: <b>{fmt(f_stats['gpus'])} шт.</b>\n"
                    f"├ Макс. множитель (Топ GPU): <b>{f_stats['max_m']}x</b>\n"
                    f"├ Средний уровень охлада: <b>{avg_cool:.1f} lvl</b>\n"
                    f"├ Средний износ сети: <b>{f_stats['avg_cond']:.1f}%</b>\n"
                    f"└ Восстановлено карт: <b>{fmt(f_stats['reps'])} раз</b>\n\n"
                    f"⚖️ <b>Теневой рынок (Market):</b>\n"
                    f"├ Активных лотов: <b>{fmt(m_stats['lots'])}</b>\n"
                    f"├ Общая стоимость: <b>{fmt(m_stats['val'])} ᴜ</b>\n"
                    f"└ Заморожено в залогах: <b>{fmt(m_stats['dep'])} ᴜ</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━"
                )
            except Exception as e:
                text = f"🏭 <b>ПРОМЫШЛЕННОСТЬ:</b>\n<i>Ошибка БД: {e}</i>"

        elif tab == "infra":
            try:
                db_bytes = await db.fetchval("SELECT pg_database_size(current_database())") or 0
                log_size = os.path.getsize("bot_errors.log") / (1024 * 1024) if os.path.exists("bot_errors.log") else 0
                
                day_ago, month_ago = int(time.time()) - 86400, int(time.time()) - 2592000
                u_stats = await db.fetchrow(
                    "SELECT COUNT(*) as total, "
                    "COUNT(*) FILTER (WHERE last_seen >= $1) as a_24h, "
                    "COUNT(*) FILTER (WHERE last_seen < $2) as dead, "
                    "COUNT(*) FILTER (WHERE ban_until > $3) as banned, "
                    "COUNT(*) FILTER (WHERE clan_id != 0) as in_clan "
                    "FROM users", day_ago, month_ago, int(time.time())
                )
                clans = await db.fetchval("SELECT COUNT(*) FROM clans") or 0
                msg_total = await db.fetchval("SELECT SUM(total_messages) FROM users") or 0

                text = (
                    f"⚙️ <b>ИНФРАСТРУКТУРА И УЗЛЫ</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"💽 <b>Сервер и БД (PostgreSQL):</b>\n"
                    f"├ Размер базы: <b>{db_bytes / (1024*1024):.2f} MB</b>\n"
                    f"└ Логи ошибок: <b>{log_size:.2f} MB</b>\n\n"
                    f"👥 <b>Глубокая демография:</b>\n"
                    f"├ Всего агентов в базе: <b>{fmt(u_stats['total'])}</b>\n"
                    f"├ Живой онлайн (24ч): <b>{fmt(u_stats['a_24h'])}</b>\n"
                    f"├ В составе кланов: <b>{fmt(u_stats['in_clan'])}</b> чел.\n"
                    f"├ Мертвые души (>30 дн): <b>{fmt(u_stats['dead'])}</b>\n"
                    f"└ В карцере (Бан): <b>{fmt(u_stats['banned'])}</b>\n\n"
                    f"📊 <b>Активность:</b>\n"
                    f"├ Зарегистрировано кланов: <b>{fmt(clans)}</b>\n"
                    f"└ Обработано сообщений: <b>{fmt(msg_total)}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━"
                )
            except Exception as e:
                text = f"⚙️ <b>ИНФРАСТРУКТУРА:</b>\n<i>Ошибка БД: {e}</i>"

        elif tab == "menu":
            text = "👁‍🗨 <b>ГЛОБАЛЬНАЯ КОНСОЛЬ АРХИТЕКТОРА</b>\nВыберите модуль для сканирования:"

    builder = InlineKeyboardBuilder()
    if tab == "menu":
        builder.button(text="💰 Экономика", callback_data="fullstat_eco")
        builder.button(text="🎰 Казино", callback_data="fullstat_casino")
        builder.button(text="🏭 Промышленность", callback_data="fullstat_farm")
        builder.button(text="⚙️ Инфраструктура", callback_data="fullstat_infra")
        builder.adjust(2, 2)
    else:
        builder.button(text="🔄 Обновить", callback_data=callback.data)
        builder.button(text="◀️ В меню", callback_data="fullstat_menu")
        builder.adjust(1, 1)

    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    except Exception:
        pass
    await callback.answer()

# ==========================================
# 🧠 ЕДИНОЕ ЯДРО ГЕНЕРАЦИИ СТРАНИЦ ТРАНЗАКЦИЙ
# ==========================================
async def build_transfers_page(bot, page: int, search_id: int = None, search_id_2: int = None, whales_only: bool = False):
    pool = await get_db()
    conditions = []
    args = []
    
    if search_id and search_id_2:
        args.extend([search_id, search_id_2])
        conditions.append(f"((sender_id = $1 AND receiver_id = $2) OR (sender_id = $2 AND receiver_id = $1))")
    elif search_id:
        args.append(search_id)
        conditions.append(f"(sender_id = $1 OR receiver_id = $1)")
        
    if whales_only:
        conditions.append("amount >= 10000000")
        
    where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
    count_query = f"SELECT COUNT(*) FROM transfers{where_clause}"
    
    if search_id and search_id_2:
        sum_query = f"""
            SELECT 
                COALESCE(SUM(CASE WHEN sender_id = $1 THEN amount ELSE 0 END), 0) as s1_to_s2,
                COALESCE(SUM(CASE WHEN sender_id = $2 THEN amount ELSE 0 END), 0) as s2_to_s1
            FROM transfers {where_clause}
        """
    else:
        sum_query = f"SELECT COALESCE(SUM(amount), 0) FROM transfers{where_clause}"
    
    args_with_pagination = args.copy()
    args_with_pagination.append(TRANSFERS_PER_PAGE)
    args_with_pagination.append(page * TRANSFERS_PER_PAGE)
    
    limit_idx = len(args) + 1
    offset_idx = len(args) + 2
    
    data_query = f"""
        SELECT sender_id, receiver_id, amount, timestamp 
        FROM transfers 
        {where_clause} 
        ORDER BY timestamp DESC 
        LIMIT ${limit_idx} OFFSET ${offset_idx}
    """

    async with pool.acquire() as db:
        total_records = await db.fetchval(count_query, *args) or 0
        
        if search_id and search_id_2:
            sums = await db.fetchrow(sum_query, *args)
            vol1_to_2 = sums['s1_to_s2'] if sums else 0
            vol2_to_1 = sums['s2_to_s1'] if sums else 0
            total_volume = vol1_to_2 + vol2_to_1
        else:
            total_volume = await db.fetchval(sum_query, *args) or 0
            
        if total_records == 0 and page == 0:
            if search_id and search_id_2: return f"🕵️ Связи между этими агентами не найдено.", None
            if search_id: return f"🕵️ Транзакций с агентом <code>{search_id}</code> не найдено.", None
            if whales_only: return "🕵️ Теневые киты пока спят.", None
            return "🕵️ Журнал транзакций пуст.", None
            
        logs = await db.fetch(data_query, *args_with_pagination)

    total_pages = max(1, math.ceil(total_records / TRANSFERS_PER_PAGE))
    if page >= total_pages: page = total_pages - 1
    if page < 0: page = 0

    async def get_short_name(u_id):
        try:
            chat = await bot.get_chat(u_id)
            return chat.first_name or f"ID:{u_id}"
        except:
            return f"ID:{u_id}"

    if search_id and search_id_2:
        name1 = await get_short_name(search_id)
        name2 = await get_short_name(search_id_2)
        diff = abs(vol1_to_2 - vol2_to_1)
        if vol1_to_2 > vol2_to_1: leader_text = f"<b>{name1}</b> перевел больше на <b>{fmt(diff)} ᴜ</b>"
        elif vol2_to_1 > vol1_to_2: leader_text = f"<b>{name2}</b> перевел больше на <b>{fmt(diff)} ᴜ</b>"
        else: leader_text = "Равенство (Никто никому не должен)"

        title = (
            f"🤝 <b>СВЯЗЬ АГЕНТОВ:</b>\n"
            f"<code>{search_id}</code> ↔️ <code>{search_id_2}</code>\n"
            f"════════════════════\n"
            f"📊 <b>ФИНАНСОВАЯ СВОДКА:</b>\n"
            f"├ Общий оборот: <b>{fmt(total_volume)} ᴜ</b>\n"
            f"├ {name1} ➡️ {name2}: <b>{fmt(vol1_to_2)} ᴜ</b>\n"
            f"├ {name2} ➡️ {name1}: <b>{fmt(vol2_to_1)} ᴜ</b>\n"
            f"└ ⚖️ Перевес: {leader_text}\n"
        )
        icon = "🔄"
    elif search_id:
        title = f"🔎 <b>ПОИСК ТРАНЗАКЦИЙ (ID: {search_id}):</b>\n💰 Оборот агента: <b>{fmt(total_volume)} ᴜ</b>"
        icon = "💸"
    elif whales_only:
        title = "🐳 <b>ДВИЖЕНИЕ КАПИТАЛА КИТОВ (>10М ᴜ):</b>"
        icon = "💎"
    else:
        title = "🚀 <b>ВСЕ ТРАНЗАКЦИИ СЕТИ:</b>"
        icon = "💸"

    text = f"{title}\nСтр. {page + 1}/{total_pages} (Всего переводов: {total_records})\n════════════════════\n"

    name_cache = {}
    import html
    
    async def get_admin_name(u_id):
        if u_id in name_cache: return name_cache[u_id]
        try:
            chat = await bot.get_chat(u_id)
            name = chat.first_name or ""
            name = name.strip()
            if not name or name == 'ᅠ': name = "Без имени"
            name = html.escape(name)
            name = (name[:12] + '..') if len(name) > 12 else name 
            name_cache[u_id] = f"<code>{u_id}</code> ({name})"
        except:
            name_cache[u_id] = f"<code>{u_id}</code>"
        return name_cache[u_id]

    for row in logs:
        sender_info = await get_admin_name(row['sender_id'])
        receiver_info = await get_admin_name(row['receiver_id'])
        dt_str = datetime.fromtimestamp(row['timestamp']).strftime('%d.%m %H:%M')
        
        text += f"🕒 <code>{dt_str}</code> | {icon} <b>{fmt(row['amount'])} ᴜ</b>\n"
        text += f"└ От: {sender_info}\n"
        text += f"└ К:  {receiver_info}\n\n"

    builder = InlineKeyboardBuilder()
    btns = []
    
    if search_id and search_id_2:
        cb_prefix = f"adm_tr2_{search_id}_{search_id_2}"
        if page > 0: btns.append(types.InlineKeyboardButton(text="◀️ Назад", callback_data=f"{cb_prefix}_{page - 1}"))
        if page < total_pages - 1: btns.append(types.InlineKeyboardButton(text="Вперед ▶️", callback_data=f"{cb_prefix}_{page + 1}"))
    else:
        s_id = search_id if search_id else 0
        w_flag = 1 if whales_only else 0
        if page > 0: btns.append(types.InlineKeyboardButton(text="◀️ Назад", callback_data=f"adm_tr_{page - 1}_{s_id}_{w_flag}"))
        if page < total_pages - 1: btns.append(types.InlineKeyboardButton(text="Вперед ▶️", callback_data=f"adm_tr_{page + 1}_{s_id}_{w_flag}"))

    if btns: builder.row(*btns)

    return text, builder.as_markup() if btns else None

# ==========================================
# 📊 КОМАНДЫ РАДАРОВ (ПЕРЕВОДЫ)
# ==========================================
@router.message((F.text.lower() == "стата переводов") & (F.from_user.id == ADMIN_ID))
async def admin_global_transfer_stats(message: types.Message):
    text, markup = await build_transfers_page(message.bot, 0, search_id=None, whales_only=False)
    await message.reply(text, reply_markup=markup, parse_mode="HTML")

@router.message((F.text.lower().in_(["стата китов", "стата крупных переводов"])) & (F.from_user.id == ADMIN_ID))
async def admin_whale_transfer_stats(message: types.Message):
    text, markup = await build_transfers_page(message.bot, 0, search_id=None, whales_only=True)
    await message.reply(text, reply_markup=markup, parse_mode="HTML")

@router.message(F.text.lower().startswith("поиск перевода") & (F.from_user.id == ADMIN_ID) & (~F.text.lower().startswith("поиск переводов")))
async def admin_search_transfers(message: types.Message):
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        return await message.reply("⚠️ Формат: <code>поиск перевода [ID или @username]</code>", parse_mode="HTML")
        
    target_str = parts[2].strip()
    target_id = int(target_str) if target_str.isdigit() else await resolve_user_id(target_str)
            
    if not target_id:
        return await message.reply(f"❌ Агент <b>{target_str}</b> не найден. Введи точный ID.", parse_mode="HTML")

    text, markup = await build_transfers_page(message.bot, 0, search_id=target_id, whales_only=False)
    await message.reply(text, reply_markup=markup, parse_mode="HTML")

@router.message(F.text.lower().startswith("поиск переводов") & (F.from_user.id == ADMIN_ID))
async def admin_search_dual_transfers(message: types.Message):
    parts = message.text.split()
    if len(parts) < 4:
        return await message.reply("⚠️ Формат: <code>поиск переводов [Агент 1] [Агент 2]</code>", parse_mode="HTML")
        
    target_id_1 = int(parts[2]) if parts[2].isdigit() else await resolve_user_id(parts[2])
    target_id_2 = int(parts[3]) if parts[3].isdigit() else await resolve_user_id(parts[3])

    if not target_id_1 or not target_id_2:
        return await message.reply("❌ Один или оба агента не найдены в базе.", parse_mode="HTML")
    if target_id_1 == target_id_2:
        return await message.reply("⚠️ Указан один и тот же агент дважды.")

    text, markup = await build_transfers_page(message.bot, 0, search_id=target_id_1, search_id_2=target_id_2)
    await message.reply(text, reply_markup=markup, parse_mode="HTML")

@router.callback_query(F.data.startswith("adm_tr2_") & (F.from_user.id == ADMIN_ID))
async def admin_transfers_dual_pagination(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    id1, id2, page = int(parts[2]), int(parts[3]), int(parts[4])
    text, markup = await build_transfers_page(callback.bot, page, search_id=id1, search_id_2=id2)
    try: await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except Exception: pass
    await callback.answer()

@router.callback_query(F.data.startswith("adm_tr_") & (F.from_user.id == ADMIN_ID))
async def callback_admin_transfers_page(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    page = int(parts[2])
    search_id = int(parts[3]) if parts[3] != "0" else None
    whales_only = parts[4] == "1"
    text, markup = await build_transfers_page(callback.message.bot, page, search_id, whales_only)
    try: await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except: pass
    await callback.answer()