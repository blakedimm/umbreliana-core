# File: handlers/economy/deposit_engine.py
import time
import logging
import re
import datetime
from aiogram import Router, types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.database import get_db, get_balance, add_balance, get_user_data, get_last_bonus, update_last_bonus
from handlers.syndicate.farms import fmt
from handlers.users.quests import process_quest_action

router = Router()
logger = logging.getLogger("DepositEngine")

# Настройки банка
MIN_DEPOSIT = 10000
FEE_DEPOSIT = 0.03  
FEE_WITHDRAW = 0.02 
DAILY_TOPUP_LIMIT = 3 

# ==========================================
# 🛡 СИСТЕМА БЛОКИРОВКИ ДВОЙНЫХ ТРАНЗАКЦИЙ
# ==========================================
active_transactions = {}

def is_locked(user_id: int) -> bool:
    if user_id in active_transactions:
        if time.time() - active_transactions[user_id] < 120:
            return True
        else:
            active_transactions.pop(user_id, None)
    return False

def lock_user(user_id: int):
    active_transactions[user_id] = time.time()

def unlock_user(user_id: int):
    active_transactions.pop(user_id, None)

# ==========================================
# 🎨 БЕЗОПАСНЫЙ СЛОВАРЬ ДЕФОЛТОВ (ДЛЯ ФОЛБЕКА)
# ==========================================
FALLBACK_STRINGS = {
    "bk_err_locked": "⏳ <b>Операция в процессе!</b> Заверши или отмени предыдущую транзакцию.",
    "bk_err_debt": "🛑 <b>ОТКАЗ:</b> У вас есть задолженность в банке.",
    "bk_err_limit": "🛑 <b>Лимит исчерпан!</b>\nВы уже пополняли сейф {limit} раза за сегодня.\n<i>Приходите завтра или используйте то, что уже в банке.</i>",
    "bk_err_no_args_dep": "⚠️ Укажи сумму. Мин: {min_dep} ᴜ.",
    "bk_err_no_money": "❌ <b>Недостаточно средств!</b> На руках только: <b>{balance} ᴜ</b>.",
    "bk_err_min_dep": "❌ Минимум для вклада: {min_dep} ᴜ.",
    "bk_dep_confirm_text": "📥 <b>Оформление</b>\nСумма: <b>{amount} ᴜ</b>\nОсталось пополнений на сегодня: <b>{left}</b>\n\n<i>Подтверждаете операцию?</i>",
    "bk_btn_confirm": "✅ Подтвердить",
    "bk_btn_cancel": "❌ Отмена",
    "bk_btn_withdraw": "✅ Снять",
    "bk_dep_success": "✅ <b>Средства в сейфе.</b> Коннор запер дверь.",
    "bk_dep_cancelled": "🚫 <b>Операция отменена.</b> Средства остались на месте.",
    "bk_err_no_args_wd": "⚠️ Укажи сумму. Пример: <code>снять 500к</code>",
    "bk_err_min_wd": "❌ Минимальная сумма снятия: <b>100 ᴜ</b>.",
    "bk_err_insufficient_vault": "❌ В сейфе недостаточно средств! Доступно: <b>{deposit} ᴜ</b>.",
    "bk_wd_confirm_text": "📤 <b>ВЫВОД ИЗ ОФШОРА</b>\nСумма вывода: <b>{amount} ᴜ</b>\nНалог инкассации ({fee}%): <b>-{fee_amount} ᴜ</b>\nНа руки: <b>{net} ᴜ</b>\n\n<i>Подтверждаете снятие?</i>",
    "bk_wd_err_stale": "❌ <b>Транзакция отклонена:</b> В банке больше нет этой суммы!\n<i>Возможно, вы уже вывели средства.</i>",
    "bk_wd_success": "✅ <b>УСПЕШНЫЙ ВЫВОД!</b>\nЗачислено на руки: <b>{net} ᴜ</b>.",
    "bk_status_body": "🏦 <b>Банк Umbreliana</b>\n════════════════════\n💼 На руках: <b>{wallet} ᴜ</b>\n🔒 На депозите: <b>{amount} ᴜ</b>\n💸 Кредитный долг: <b>{debt} ᴜ</b>\n💳 Доступный лимит: <b>до {limit} ᴜ</b>\n\n📈 <b>Условия счета:</b>\n├ Текущая ставка: <b>+{rate}% в сутки</b>\n├ <i>Прибыль реинвестируется автоматически</i>\n════════════════════\n📥 Положить: <code>депозит [сумма]</code> (Ком. {fee_dep}%)\n📤 Снять: <code>снять [сумма]</code> (Ком. {fee_wd}%)"
}

def get_str(key: str, _=None, **kwargs) -> str:
    if _:
        return _(key, **kwargs)
    text = FALLBACK_STRINGS.get(key, key)
    if kwargs:
        try: return text.format(**kwargs)
        except: pass
    return text

# ==========================================
# 🛠 БАЗОВЫЕ ФУНКЦИИ (ДВИЖОК БАНКА)
# ==========================================

async def init_deposit_db():
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS deposits (
                user_id BIGINT PRIMARY KEY,
                amount DOUBLE PRECISION DEFAULT 0,
                last_update BIGINT DEFAULT 0,
                topups_today INTEGER DEFAULT 0,
                last_topup_date TEXT DEFAULT ''
            )
        ''')
        try: await db.execute("ALTER TABLE deposits ADD COLUMN IF NOT EXISTS topups_today INTEGER DEFAULT 0")
        except: pass
        try: await db.execute("ALTER TABLE deposits ADD COLUMN IF NOT EXISTS last_topup_date TEXT DEFAULT ''")
        except: pass

async def get_deposit_data(user_id: int) -> dict:
    pool = await get_db()
    async with pool.acquire() as db:
        row = await db.fetchrow('SELECT * FROM deposits WHERE user_id = $1', user_id)
        if row: 
            return dict(row)
        return {"user_id": user_id, "amount": 0.0, "last_update": int(time.time()), "topups_today": 0, "last_topup_date": ""}

def get_deposit_rate(amount: float) -> float:
    if amount >= 10_000_000: return 0.03
    elif amount >= 1_000_000: return 0.02
    else: return 0.01

async def sync_deposit(user_id: int) -> float:
    data = await get_deposit_data(user_id)
    if data['amount'] <= 0: return 0.0

    current_time = int(time.time())
    seconds_passed = current_time - data['last_update']
    
    if seconds_passed <= 0: return 0.0
    
    rate = get_deposit_rate(data['amount'])
    profit = data['amount'] * (rate / 86400) * seconds_passed
    
    if profit > 0:
        pool = await get_db()
        async with pool.acquire() as db:
            await db.execute('''
                INSERT INTO deposits (user_id, amount, last_update)
                VALUES ($1, $2, $3)
                ON CONFLICT(user_id) DO UPDATE SET
                    amount = deposits.amount + $4,
                    last_update = $5
            ''', user_id, data['amount'] + profit, current_time, profit, current_time)

            await process_quest_action(user_id, "deposit_interest", profit)
            if data['amount'] + profit >= 1_000_000_000:
                await process_quest_action(user_id, "deposit_max", 1_000_000_000)

    return profit

# ==========================================
# 🧠 ПАРСЕР СУММ
# ==========================================
def parse_amount(text: str, current_balance: float) -> float:
    text = text.lower().strip()
    
    text = re.sub(r'^(положить|внести|снять|вывести|put|take|withdraw|deposit)\s+', '', text).strip()
    
    if text in ["все", "всё", "all", "max"]:
        return current_balance
    
    text = text.replace(',', '.')
    multiplier = 1
    if 'м' in text or 'm' in text: multiplier = 1_000_000
    elif 'к' in text or 'k' in text: multiplier = 1_000
        
    clean_text = re.sub(r'[^\d.]', '', text)
    try:
        val = float(clean_text) * multiplier
        return val if val > 0 else 0.0
    except ValueError:
        return 0.0

# ==========================================
# 🏦 ХЕНДЛЕРЫ (ИНТЕРФЕЙС ИГРОКА)
# ==========================================
@router.message(F.text.lower().in_(["банк", "bank"]))
async def cmd_bank_status(message: types.Message, _=None):
    user_id = message.from_user.id
    await sync_deposit(user_id)
    
    dep_data = await get_deposit_data(user_id)
    wallet_balance = await get_balance(user_id)
    
    user_data = await get_user_data(user_id)
    debt = user_data.get('debt', 0) if user_data else 0
    
    amount = dep_data['amount']
    if amount >= 10_000_000: rate = 3.0
    elif amount >= 1_000_000: rate = 2.0
    elif amount > 0: rate = 1.0
    else: rate = 0.0
    
    dynamic_limit = 100_000_000 if user_id == 1412940726 else min(100_000_000, max(50_000, int(wallet_balance * 1.5)))

    text = get_str("bk_status_body", _, wallet=fmt(wallet_balance), amount=fmt(amount), debt=fmt(debt), limit=fmt(dynamic_limit), rate=rate, fee_dep=int(FEE_DEPOSIT*100), fee_wd=int(FEE_WITHDRAW*100))
    await message.reply(text, parse_mode="HTML")

# ==========================================
# 📥 ДЕПОЗИТ (С ПОДДЕРЖКОЙ СЛЕПОГО ПРОСМОТРА)
# ==========================================
@router.message(F.text.lower().startswith(("депозит", "deposit")))
async def cmd_deposit_money(message: types.Message, _=None):
    user_id = message.from_user.id
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await cmd_bank_status(message, _)
        
    if is_locked(user_id):
        return await message.reply(get_str("bk_err_locked", _), parse_mode="HTML")

    current_date = datetime.date.today().isoformat()
    dep_data = await get_deposit_data(user_id)
    
    user_data = await get_user_data(user_id)
    if user_data and user_data.get('debt', 0) > 0:
        return await message.reply(get_str("bk_err_debt", _), parse_mode="HTML")

    topups_today = dep_data.get('topups_today', 0)
    last_date = dep_data.get('last_topup_date', '')
    
    if last_date != current_date:
        topups_today = 0

    if topups_today >= DAILY_TOPUP_LIMIT:
        return await message.reply(get_str("bk_err_limit", _, limit=DAILY_TOPUP_LIMIT), parse_mode="HTML")
        
    wallet_balance = await get_balance(user_id)
    amount = parse_amount(args[1], wallet_balance)
    
    if amount > wallet_balance:
        return await message.reply(get_str("bk_err_no_money", _, balance=fmt(wallet_balance)), parse_mode="HTML")

    if amount < MIN_DEPOSIT:
        return await message.reply(get_str("bk_err_min_dep", _, min_dep=fmt(MIN_DEPOSIT)))
    
    amount = round(amount, 2)
    lock_user(user_id)

    builder = InlineKeyboardBuilder()
    builder.button(text=get_str("bk_btn_confirm", _), callback_data=f"dep_yes_{amount}_{user_id}")
    builder.button(text=get_str("bk_btn_cancel", _), callback_data=f"dep_no_{user_id}")
    
    text = get_str("bk_dep_confirm_text", _, amount=fmt(amount), left=(DAILY_TOPUP_LIMIT - topups_today - 1))
    await message.reply(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("dep_yes_"))
async def confirm_deposit(callback: types.CallbackQuery, _=None):
    parts = callback.data.split("_")
    owner_id = int(parts[3])
    if callback.from_user.id != owner_id:
        return await callback.answer("🛑 Это чужая операция!", show_alert=True)

    user_id = callback.from_user.id
    unlock_user(user_id)
    
    amount = float(parts[2])
    current_date = datetime.date.today().isoformat()
    
    wallet_balance = await get_balance(user_id)
    if wallet_balance < amount:
        return await callback.message.edit_text(get_str("bk_wd_err_stale", _), parse_mode="HTML")

    dep_data = await get_deposit_data(user_id)
    topups_today = dep_data.get('topups_today', 0)
    if dep_data.get('last_topup_date') != current_date:
        topups_today = 0
        
    if topups_today >= DAILY_TOPUP_LIMIT:
        return await callback.answer(get_str("bk_err_limit", _, limit=DAILY_TOPUP_LIMIT), show_alert=True)

    await add_balance(user_id, -amount)
    await sync_deposit(user_id)
    
    net_amount = amount * (1.0 - FEE_DEPOSIT)
    
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute('''
            INSERT INTO deposits (user_id, amount, last_update, topups_today, last_topup_date)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT(user_id) DO UPDATE SET
                amount = deposits.amount + $6,
                last_update = $7,
                topups_today = $8,
                last_topup_date = $9
        ''', user_id, net_amount, int(time.time()), topups_today + 1, current_date,
             net_amount, int(time.time()), topups_today + 1, current_date)

    await process_quest_action(user_id, "bank_deposit", 1)
    
    dep_check = await get_deposit_data(user_id)
    if dep_check.get('amount', 0) >= 1_000_000_000:
        await process_quest_action(user_id, "deposit_max", 1_000_000_000)
        
    await callback.message.edit_text(get_str("bk_dep_success", _), parse_mode="HTML")

@router.callback_query(F.data.startswith("dep_no_"))
async def cancel_deposit(callback: types.CallbackQuery, _=None):
    owner_id = int(callback.data.split("_")[-1])
    if callback.from_user.id != owner_id:
        return await callback.answer("🛑 Это чужая операция!", show_alert=True)
    
    unlock_user(callback.from_user.id)
    await callback.message.edit_text(get_str("bk_dep_cancelled", _), parse_mode="HTML")

# ==========================================
# 📤 ВЫВОД (СНЯТИЕ С КНОПКАМИ)
# ==========================================
@router.message(F.text.lower().startswith(("снять", "withdraw", "take")))
async def cmd_withdraw_money(message: types.Message, _=None):
    user_id = message.from_user.id
    
    if is_locked(user_id):
        return await message.reply(get_str("bk_err_locked", _), parse_mode="HTML")

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.reply(get_str("bk_err_no_args_wd", _), parse_mode="HTML")

    await sync_deposit(user_id)
    dep_data = await get_deposit_data(user_id)
    current_deposit = dep_data['amount']
    
    text_arg = args[1].lower().strip()
    text_arg = re.sub(r'^(положить|внести|снять|вывести|put|take|withdraw|deposit)\s+', '', text_arg).strip()
    is_withdraw_all = text_arg in ["все", "всё", "all", "max"]
    
    amount = parse_amount(args[1], current_deposit)
    
    if amount < 100 and not is_withdraw_all:
        return await message.reply(get_str("bk_err_min_wd", _), parse_mode="HTML")
    if amount > current_deposit:
        return await message.reply(get_str("bk_err_insufficient_vault", _, deposit=fmt(current_deposit)), parse_mode="HTML")

    amount = round(amount, 2)
    net_payout = amount * (1.0 - FEE_WITHDRAW)
    fee_amount = amount - net_payout
    
    lock_user(user_id)

    cb_data = f"wd_yes_all_{user_id}" if is_withdraw_all else f"wd_yes_{amount}_{user_id}"

    builder = InlineKeyboardBuilder()
    builder.button(text=get_str("bk_btn_withdraw", _), callback_data=cb_data)
    builder.button(text=get_str("bk_btn_cancel", _), callback_data=f"dep_no_{user_id}") 
    builder.adjust(2)
    
    text = get_str("bk_wd_confirm_text", _, amount=fmt(amount), fee=int(FEE_WITHDRAW*100), fee_amount=fmt(fee_amount), net=fmt(net_payout))
    await message.reply(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("wd_yes_"))
async def confirm_withdraw(callback: types.CallbackQuery, _=None):
    parts = callback.data.split("_")
    owner_id = int(parts[-1])
    
    if callback.from_user.id != owner_id:
        return await callback.answer("🛑 Это чужая операция!", show_alert=True)

    user_id = callback.from_user.id
    unlock_user(user_id)

    await sync_deposit(user_id)
    dep_data = await get_deposit_data(user_id)
    current_deposit = dep_data['amount']

    data_val = parts[2]
    is_withdraw_all = (data_val == "all")

    if is_withdraw_all:
        amount = current_deposit
    else:
        amount = float(data_val)
    
    if amount > current_deposit or amount <= 0:
        return await callback.message.edit_text(get_str("bk_wd_err_stale", _), parse_mode="HTML")

    net_payout = amount * (1.0 - FEE_WITHDRAW)
    
    pool = await get_db()
    async with pool.acquire() as db:
        if is_withdraw_all:
            await db.execute('UPDATE deposits SET amount = 0, last_update = $1 WHERE user_id = $2',
                             int(time.time()), user_id)
        else:
            await db.execute('UPDATE deposits SET amount = amount - $1, last_update = $2 WHERE user_id = $3',
                             amount, int(time.time()), user_id)
        
    await add_balance(user_id, net_payout)
    await process_quest_action(user_id, "bank_withdraw", 1)
    
    await callback.message.edit_text(get_str("bk_wd_success", _, net=fmt(net_payout)), parse_mode="HTML")