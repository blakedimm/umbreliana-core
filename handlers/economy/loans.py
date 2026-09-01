import time
import random
import re
import os
import json
import logging
from handlers.users.statuses import has_active_status
from handlers.economy.deposit_engine import get_deposit_data
from aiogram import Router, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from core.database import get_db, get_user_data, update_user, add_balance, get_balance, get_overdue_users, get_all_debtors
from handlers.syndicate.farms import calculate_farm_state, GPUS, COOLING

router = Router()

__all__ = ['router', 'debt_reaper', 'check_transfer_lock']

MAX_LOAN = 100_000_000 

fmt = lambda x: f"{int(x):,}".replace(',', ' ')

# ==========================================
# 🎨 БЕЗОПАСНАЯ ФЕЙЛСЕЙФ СИСТЕМА ЛОКАЛИЗАЦИИ
# ==========================================
FALLBACK_STRINGS = {
    "ln_err_input_format": "📝 Напиши чётко: <code>взять в долг 100м</code>",
    "ln_confirm_err_hack": "❌ Выявлена попытка взлома. Лимит превышен.",
    "ln_confirm_err_double": "❌ Ты уже взял кредит! Кнопка больше не работает.",
    "ln_cancel_success": "❌ <b>Сделка отменена.</b> Коннор сжёг договор.",
    "ln_extend_err_none": "У тебя нет долгов!",
    "ln_extend_alert": "Время куплено! 💸"
}

def get_str(key: str, translator=None, **kwargs) -> str:
    if translator and callable(translator):
        return translator(key, **kwargs)
    text = FALLBACK_STRINGS.get(key, key)
    if kwargs:
        try: return text.format(**kwargs)
        except: pass
    return text

LOCALES = {}
for l in ["ru", "en"]:
    p = f"locales/{l}.json"
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f: LOCALES[l] = json.load(f)
        except Exception as e:
            logging.error(f"Ошибка загрузки локали {l} в кредитах: {e}")

def get_translator(lang: str):
    t_lang = lang if lang in LOCALES else "ru"
    def translate(key: str, **kwargs) -> str:
        text = LOCALES[t_lang].get(key, FALLBACK_STRINGS.get(key, key))
        if kwargs:
            try: return text.format(**kwargs)
            except: pass
        return text
    return translate

async def resolve_chat_translator(chat_id: int, default__ = None):
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            chat_lang = await db.fetchval("SELECT lang FROM chats WHERE chat_id = $1", chat_id)
            if chat_lang: return get_translator(chat_lang)
    except: pass
    return default__ if default__ else get_translator("ru")


def parse_amount(text):
    clean_text = text.lower().replace("взять в долг", "").replace("borrow", "").replace("вернуть", "").replace("repay", "").strip()
    clean_text = clean_text.replace(" ", "")
    val_str = clean_text.replace('к', '000').replace('k', '000').replace('м', '000000').replace('m', '000000')
    
    digits = re.findall(r'\d+', val_str)
    if digits: return int(digits[0])
    return None

# ==========================================
# 🏦 ЗАПРОС КРЕДИТА
# ==========================================
@router.message(F.text.lower().startswith(("взять в долг", "borrow")))
async def request_loan(message: types.Message, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    from handlers.admin import SYSTEM_MODULES
    if not SYSTEM_MODULES.get("банки", True): return message.reply(get_str("ln_sys_disabled", _), parse_mode="HTML")

    amount = parse_amount(message.text)
    user_id = message.from_user.id
    user_data = await get_user_data(user_id) 
    balance = await get_balance(user_id)

    dep_data = await get_deposit_data(user_id)
    deposit_amount = int(dep_data.get('amount', 0)) 
    
    if deposit_amount >= 100: 
        return await message.reply(get_str("ln_err_offshore", _, amount=fmt(deposit_amount)), parse_mode="HTML")
    
    current_time = int(time.time())
    created_at = user_data.get('created_at', 0) 
    
    if created_at > 0 and (current_time - created_at) < 604800:
        days_registered = (current_time - created_at) // 86400
        return await message.reply(get_str("ln_err_young", _, days=days_registered, rem=7 - days_registered), parse_mode="HTML")

    from core.database import get_farm
    farm_data = await get_farm(user_id)
    if not farm_data: return await message.reply(get_str("ln_err_no_farm", _))
        
    income_ph, *unused_farm = await calculate_farm_state(user_id, farm_data)
    MIN_INCOME_REQUIRED = 30_000 
    
    if income_ph < MIN_INCOME_REQUIRED and user_id != 1412940726:
        return await message.reply(get_str("ln_err_low_activity", _, income=fmt(income_ph), required=fmt(MIN_INCOME_REQUIRED)), parse_mode="HTML")

    if not amount or amount <= 0: return await message.reply(get_str("ln_err_input_format", _), parse_mode="HTML")

    dynamic_limit = MAX_LOAN if user_id == 1412940726 else min(MAX_LOAN, max(50_000, int(balance * 1.5)))

    if amount > dynamic_limit:
        return await message.reply(get_str("ln_err_limit_exceeded", _, limit=fmt(dynamic_limit), balance=fmt(balance)), parse_mode="HTML")

    if user_data.get('debt', 0) > 0: return await message.reply(get_str("ln_err_active_debt", _))
    if user_data.get('ban_until', 0) > time.time(): return await message.reply(get_str("ln_err_banned_collectors", _))

    is_lucky = await has_active_status(user_id, 3)
    interest = 1.05 if is_lucky else 1.2 
    return_amount = int(amount * interest)
    
    commission_val = return_amount - amount
    percent_label = "5%" if is_lucky else "20%"
    
    builder = InlineKeyboardBuilder()
    builder.button(text=get_str("ln_btn_sign", _), callback_data=f"loan_confirm_{amount}_{user_id}")
    builder.button(text=get_str("ln_btn_cancel", _), callback_data=f"loan_cancel_{user_id}")
    builder.adjust(1)

    text = get_str("ln_contract_body", _, name=message.from_user.first_name, balance=fmt(balance), limit=fmt(dynamic_limit), amount=fmt(amount), percent=percent_label, commission=fmt(commission_val), return_amount=fmt(return_amount))
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("loan_confirm_"))
async def confirm_loan(callback: types.CallbackQuery, _=None):
    parts = callback.data.split("_")
    try: 
        amount = int(parts[2])
        owner_id = int(parts[3])
    except (ValueError, IndexError): 
        return await callback.answer("Buffer Error.", show_alert=True)

    if callback.from_user.id != owner_id:
        return await callback.answer("🛑 Это чужой кредитный договор!", show_alert=True)

    if not _: _ = await resolve_chat_translator(callback.message.chat.id, _)
    user_id = callback.from_user.id
    balance = await get_balance(user_id)
    dynamic_limit = min(MAX_LOAN, max(50_000, int(balance * 1.5)))
    
    if amount > dynamic_limit or amount <= 0: return await callback.answer(get_str("ln_confirm_err_hack", _), show_alert=True)

    user_data = await get_user_data(user_id)
    if user_data.get('debt', 0) > 0:
        from core.database import change_rating
        await change_rating(user_id, -10)
        return await callback.message.edit_text(get_str("ln_confirm_err_double", _))

    interest = 1.05 if await has_active_status(user_id, 3) else 1.2
    return_amount = int(amount * interest)
    
    deadline = int(time.time()) + 86400 
    await update_user(user_id, debt=return_amount, debt_time=deadline)
    await add_balance(user_id, amount)

    await callback.message.edit_text(get_str("ln_confirm_success", _, amount=fmt(amount), return_amount=fmt(return_amount)), parse_mode="HTML")


@router.callback_query(F.data.startswith("loan_cancel_"))
async def cancel_loan(callback: types.CallbackQuery, _=None):
    owner_id = int(callback.data.split("_")[-1])
    if callback.from_user.id != owner_id:
        return await callback.answer("🛑 Руки на стол! Это не твой договор.", show_alert=True)

    if not _: _ = await resolve_chat_translator(callback.message.chat.id, _)
    await callback.message.edit_text(get_str("ln_cancel_success", _), parse_mode="HTML")

# ==========================================
# 📊 УЗЕЛ КУЛДАУНОВ И МОНИТОРИНГА
# ==========================================
@router.message(F.text.lower().in_(["мой долг", "my debt", "debt"]))
async def debt_info(message: types.Message, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    user_data = await get_user_data(message.from_user.id)
    debt = user_data.get('debt', 0)

    if debt <= 0: return await message.reply(get_str("ln_info_none", _))

    rem = max(0, user_data['debt_time'] - int(time.time()))
    time_str = get_str("ln_info_time_str", _, hours=rem // 3600, minutes=(rem % 3600) // 60) if rem > 0 else get_str("ln_info_timeout", _)

    builder = InlineKeyboardBuilder()
    builder.button(text=get_str("ln_btn_extend", _), callback_data=f"loan_extend_{message.from_user.id}")

    text = get_str("ln_info_body", _, debt=fmt(debt), time=time_str)
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("loan_extend_"))
async def extend_loan(callback: types.CallbackQuery, _=None):
    owner_id = int(callback.data.split("_")[-1])
    if callback.from_user.id != owner_id:
        return await callback.answer("🛑 Это не твой долг!", show_alert=True)

    if not _: _ = await resolve_chat_translator(callback.message.chat.id, _)
    user_id = callback.from_user.id
    user_data = await get_user_data(user_id)
    debt = user_data.get('debt', 0)

    if debt <= 0: return await callback.answer(get_str("ln_extend_err_none", _), show_alert=True)

    penalty_rate = 0.05 if await has_active_status(user_id, 3) else 0.15 
    penalty = int(debt * penalty_rate)
    
    new_debt = debt + penalty
    new_deadline = user_data['debt_time'] + 86400 

    await update_user(user_id, debt=new_debt, debt_time=new_deadline)

    text = get_str("ln_extend_body", _, penalty=fmt(penalty), debt=fmt(new_debt))
    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer(get_str("ln_extend_alert", _))


@router.message(F.text.lower().startswith(("вернуть", "repay")))
async def repay_debt(message: types.Message, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)
    debt = user_data.get('debt', 0)

    if debt <= 0: return await message.reply(get_str("ln_repay_err_none", _))

    text = message.text.lower().strip()
    words = text.split()
    if any(w in words for w in ["все", "всё", "all"]): amount = debt
    else: amount = parse_amount(text)

    if not amount or amount <= 0: return await message.reply(get_str("ln_repay_err_format", _))
    if await get_balance(user_id) < amount: return await message.reply(get_str("ln_repay_err_no_money", _))

    actual_payment = min(amount, debt)
    new_debt = debt - actual_payment
    
    await add_balance(user_id, -actual_payment)
    await update_user(user_id, debt=new_debt, debt_time=(0 if new_debt == 0 else user_data['debt_time']))

    if new_debt == 0:
        from core.database import change_rating
        await change_rating(user_id, 20)
        await message.answer(get_str("ln_repay_success_full", _, payment=fmt(actual_payment)), parse_mode="HTML")
    else:
        await message.answer(get_str("ln_repay_success_partial", _, payment=fmt(actual_payment), rem=fmt(new_debt)), parse_mode="HTML")


async def check_transfer_lock(user_id: int):
    user_data = await get_user_data(user_id)
    return user_data.get('debt', 0) <= 0

# ==========================================
# 📜 ДОСКА ПОЗОРА (РЕЕСТР ДОЛЖНИКОВ)
# ==========================================
@router.message(F.text.lower().in_({"должники", "долги", "debtors", "debts"}))
async def show_debtors_list(message: types.Message, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    debtors = await get_all_debtors()
    if not debtors: return await message.answer(get_str("ln_board_empty", _), parse_mode="HTML")

    text = get_str("ln_board_header", _)
    total_debt = 0
    
    for i, row in enumerate(debtors, 1):
        user_id, nickname, debt = row['user_id'], row['nickname'], row['debt']
        total_debt += debt
        fmt_debt = f"{int(debt):,}".replace(',', ' ')
        display_name = nickname if nickname else f"ID {user_id}"

        num = ["❶", "❷", "❸", "❹", "❺", "❻", "❼", "❽", "❾", "❿"][i-1] if i <= 10 else f"{i}."
        text += f"{num} <b>{display_name}</b> — <code>{fmt_debt}</code> ᴜ\n"

    text += get_str("ln_board_footer", _, total=fmt(total_debt))
    await message.answer(text, parse_mode="HTML")

# ==========================================
# 💀 ПАЛАЧ (ФОНОВЫЙ БЭКГРАУНД КРОН)
# ==========================================
async def debt_reaper(bot):
    try:
        overdue_users = await get_overdue_users()

        for user in overdue_users:
            user_id = user['id']
            current_data = await get_user_data(user_id)
            debt = current_data.get('debt', 0)
            if debt <= 0: continue
                
            balance = await get_balance(user_id)
            
            # 🔥 ЖЕСТКИЙ ПЕРЕХВАТ ЯЗЫКА КЛИЕНТА ДЛЯ КРОН ЗАДАЧИ
            pool = await get_db()
            async with pool.acquire() as db: 
                user_lang = await db.fetchval("SELECT lang FROM users WHERE user_id = $1", user_id) or "ru"
            _user_trans = get_translator(user_lang)

            # --- СЦЕНАРИЙ 1: ДЕНЕГ ХВАТАЕТ ДЛЯ СЕЙВ ТРАНЗАКЦИИ ---
            if balance >= debt:
                await add_balance(user_id, -debt)
                await update_user(user_id, debt=0, debt_time=0)
                try:
                    await bot.send_message(user_id, get_str("ln_reaper_deduct_msg", translator=_user_trans, debt=fmt(debt)), parse_mode="HTML")
                except: pass

            # --- СЦЕНАРИЙ 2: ПЕРЕХВАТ ОФШОРОВ (ДЕДЛОК ФИКС) ---
            else:
                dep_data = await get_deposit_data(user_id)
                deposit_amount = dep_data.get('amount', 0)
                remaining_debt = debt - balance

                if deposit_amount > 0:
                    if deposit_amount >= remaining_debt:
                        penalty = remaining_debt * 1.5 
                        take_from_deposit = min(deposit_amount, penalty)
                        
                        async with pool.acquire() as db:
                            await db.execute('UPDATE deposits SET amount = amount - $1 WHERE user_id = $2', take_from_deposit, user_id)
                        
                        await update_user(user_id, balance=0, debt=0, debt_time=0)
                        from core.database import change_rating
                        await change_rating(user_id, -50)
                        
                        try:
                            await bot.send_message(user_id, get_str("ln_reaper_offshore_hack", translator=_user_trans, amount=fmt(take_from_deposit)), parse_mode="HTML")
                        except: pass
                        continue 
                    
                    else:
                        async with pool.acquire() as db:
                            await db.execute('UPDATE deposits SET amount = 0 WHERE user_id = $1', user_id)

                # --- СЦЕНАРИЙ 3: ДЕНЕГ НЕТ НИГДЕ (ПОЛНАЯ УТИЛИЗАЦИЯ) ---
                ban_days = random.randint(1, 3)
                ban_ts = int(time.time()) + (ban_days * 86400)

                await update_user(user_id, balance=0, debt=0, debt_time=0, ban_until=ban_ts)
                try:
                    from core.database import change_rating
                    await change_rating(user_id, -200)
                except: pass

                try:
                    fmt_bal = f"{balance:,}".replace(',', ' ') if balance > 0 else "0"
                    extra_text = ""
                    if deposit_amount > 0: extra_text = get_str("ln_reaper_extra_deposit", translator=_user_trans, amount=fmt(deposit_amount))
                    elif balance > 0: extra_text = get_str("ln_reaper_extra_balance", translator=_user_trans, amount=fmt_bal)
                    
                    text = get_str("ln_reaper_ban_msg", translator=_user_trans, debt=fmt(debt), extra=extra_text, days=ban_days)
                    await bot.send_message(user_id, text, parse_mode="HTML")
                except: pass

    except Exception as e:
        logging.error(f"Ошибка в работе Палача кредитной системы: {e}")