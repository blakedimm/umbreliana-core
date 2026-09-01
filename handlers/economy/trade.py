import time
import asyncio
import re
import urllib.parse
import os
import json
import logging
from aiogram import Router, F, types, Bot
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from core.database import get_db, get_balance, add_balance, get_farm, update_farm, add_to_dividend_pool
from handlers.syndicate.farms import GPUS, sync_farm_passive

router = Router()
ADMIN_ID = 1412940726 

fmt = lambda x: f"{int(x):,}".replace(',', ' ')

# ==========================================
# 🎨 БЕЗОПАСНАЯ ФЕЙЛСЕЙФ СИСТЕМА ЛОКАЛИЗАЦИИ
# ==========================================
FALLBACK_STRINGS = {
    "tr_err_target_format": "⚠️ Цель нужно указывать по ID или через реплай.",
    "tr_err_not_yours": "Это не для тебя!",
    "tr_alert_started": "Сделка начата!",
    "tr_alert_inactive": "Сделка уже неактивна",
    "tr_alert_cleared": "Твое предложение очищено!",
    "tr_alert_ready": "Ты подтвердил готовность!",
    "tr_alert_edit_resume": "Редактирование возобновлено.",
    "tr_alert_not_participant": "Ты не участвуешь!",
    "tr_alert_no_gpus": "У тебя нет видеокарт!",
    "tr_alert_no_active_gpus": "Нет доступных рабочих карт!",
    "tr_err_money_nan": "❌ Введи корректную сумму числом!",
    "tr_err_umc_nan": "❌ Количество должно быть целым числом!",
    "tr_err_qty_nan": "❌ Напиши корректное число!"
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
            logging.error(f"Ошибка загрузки локали {l} в трейдах: {e}")

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


# ==========================================
# 🧮 НАЛОГОВЫЕ ДВИЖКИ СИНДИКАТА
# ==========================================
async def calculate_trade_tax(user_id: int, amount: int):
    if amount <= 0: return 0, 0, 0, 0
    from handlers.users.statuses import has_active_status
    if await has_active_status(user_id, 5) or await has_active_status(user_id, 777): tax_rate = 0.05
    else:
        if amount < 10_000_000: tax_rate = 0.05
        elif amount < 50_000_000: tax_rate = 0.15
        elif amount < 500_000_000: tax_rate = 0.30
        else: tax_rate = 0.50
        
    tax = int(amount * tax_rate)
    dividend_cut = int(amount * 0.01)
    total_needed = amount + tax
    return tax, total_needed, dividend_cut, tax_rate


async def calculate_crypto_trade_tax(user_id: int, amount: int):
    if amount <= 0: return 0, 0, 0
    from handlers.users.statuses import has_active_status
    if await has_active_status(user_id, 5) or await has_active_status(user_id, 777): tax_rate = 0.05
    else:
        if amount < 1000: tax_rate = 0.05
        elif amount < 10000: tax_rate = 0.15
        elif amount < 100000: tax_rate = 0.30
        else: tax_rate = 0.50
        
    tax = int(amount * tax_rate)
    total_needed = amount + tax
    return tax, total_needed, tax_rate

# ==========================================
# 🗄 ГЛОБАЛЬНАЯ ПАМЯТЬ ТРЕЙДОВ
# ==========================================
ACTIVE_TRADES = {}
USER_TRADES = {} 
PENDING_REQUESTS = {}

class TradeFSM(StatesGroup):
    waiting_for_money = State()
    waiting_for_crypto = State()  
    waiting_for_qty = State()

async def init_trade_db():
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS trade_history (
                id SERIAL PRIMARY KEY,
                chat_id BIGINT,
                trade_summary TEXT,
                timestamp BIGINT
            )
        """)

# ==========================================
# ⏱ АВТООТМЕНА ПО ТАЙМАУТУ
# ==========================================
async def trade_timeout_watchdog(bot: Bot, trade_id: int):
    while True:
        await asyncio.sleep(30) 
        if trade_id not in ACTIVE_TRADES: break 

        trade = ACTIVE_TRADES[trade_id]
        last_active = trade.get('last_active', int(time.time()))
        
        if int(time.time()) - last_active >= 300: 
            ACTIVE_TRADES.pop(trade_id, None)
            u1, u2 = trade['users']
            USER_TRADES.pop(u1, None)
            USER_TRADES.pop(u2, None)
            
            # Тянем язык чата для сброса по кулдауну
            _chat_trans = await resolve_chat_translator(trade['chat_id'])
            try:
                await bot.edit_message_text(
                    get_str("tr_timeout", translator=_chat_trans), 
                    chat_id=trade['chat_id'], 
                    message_id=trade['dashboard_msg_id'], 
                    parse_mode="HTML"
                )
            except Exception: pass
            break

# ==========================================
# 🤝 ШАГ 1: ИНИЦИАЦИЯ В ГРУППЕ
# ==========================================
@router.message(F.text.lower().startswith(("трейд", "trade")))
async def cmd_trade_request(message: types.Message, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    user_id = message.from_user.id
    target_id = None

    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
    else:
        parts = message.text.split()
        if len(parts) > 1:
            raw_target = parts[1].replace('@', '')
            if raw_target.isdigit(): target_id = int(raw_target)
            else: return await message.reply(get_str("tr_err_target_format", _))

    if not target_id: return await message.reply(get_str("tr_err_instruction", _), parse_mode="HTML")
    if target_id == user_id: return await message.reply(get_str("tr_err_self", _))
    if target_id == message.bot.id: return await message.reply(get_str("tr_err_bot", _))

    try:
        member = await message.bot.get_chat_member(message.chat.id, target_id)
        if member.status in ['left', 'kicked', 'restricted']:
            return await message.reply(get_str("tr_err_not_here", _))
    except Exception:
        return await message.reply(get_str("tr_err_not_found", _))

    if user_id in USER_TRADES or target_id in USER_TRADES: return await message.reply(get_str("tr_err_busy", _))

    req_id = f"{user_id}_{target_id}"
    PENDING_REQUESTS[req_id] = message.from_user.first_name

    builder = InlineKeyboardBuilder()
    builder.button(text=get_str("tr_btn_accept", _), callback_data=f"trq_acc_{user_id}_{target_id}")
    builder.button(text=get_str("tr_btn_decline", _), callback_data=f"trq_dec_{user_id}_{target_id}")
    builder.adjust(2)

    target_name = member.user.first_name if 'member' in locals() else str(target_id)
    text_req = get_str("tr_request_body", _, name1=message.from_user.first_name, name2=target_name)
    await message.reply(text_req, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("trq_dec_"))
async def decline_trade_req(callback: types.CallbackQuery, _=None):
    if not _: _ = await resolve_chat_translator(callback.message.chat.id, _)
    parts = callback.data.split("_")
    initiator, target = int(parts[2]), int(parts[3])
    if callback.from_user.id not in [target, initiator]: return await callback.answer(get_str("tr_err_not_Yours", _), show_alert=True)
    await callback.message.edit_text(get_str("tr_declined", _), parse_mode="HTML")


@router.callback_query(F.data.startswith("trq_acc_"))
async def accept_trade_req(callback: types.CallbackQuery, _=None):
    if not _: _ = await resolve_chat_translator(callback.message.chat.id, _)
    parts = callback.data.split("_")
    initiator_id, target_id = int(parts[2]), int(parts[3])
    
    if callback.from_user.id != target_id: return await callback.answer(get_str("tr_err_not_yours", _), show_alert=True)
    if initiator_id in USER_TRADES or target_id in USER_TRADES: return await callback.answer(get_str("tr_err_busy_alert", _), show_alert=True)

    trade_id = int(time.time())
    req_id = f"{initiator_id}_{target_id}"
    initiator_name = PENDING_REQUESTS.get(req_id, "Инициатор")

    ACTIVE_TRADES[trade_id] = {
        "status": "building", 
        "chat_id": callback.message.chat.id,
        "dashboard_msg_id": callback.message.message_id,
        "last_active": int(time.time()), 
        initiator_id: {"name": initiator_name, "money": 0, "umc": 0, "gpus": [], "ready": False, "confirmed": False, "prompt_msg_id": None},
        target_id: {"name": callback.from_user.first_name, "money": 0, "umc": 0, "gpus": [], "ready": False, "confirmed": False, "prompt_msg_id": None},
        "users": [initiator_id, target_id]
    }
    USER_TRADES[initiator_id] = trade_id
    USER_TRADES[target_id] = trade_id

    await update_trade_dashboard(callback.bot, trade_id, _=_)
    asyncio.create_task(trade_timeout_watchdog(callback.bot, trade_id))
    await callback.answer(get_str("tr_alert_started", _))


# ==========================================
# 🖥 ГЛАВНАЯ ПАНЕЛЬ СДЕЛКИ (ОБНОВЛЕНИЕ)
# ==========================================
async def update_trade_dashboard(bot: Bot, trade_id: int, _=None):
    if trade_id not in ACTIVE_TRADES: return
    trade = ACTIVE_TRADES[trade_id]
    if not _: _ = await resolve_chat_translator(trade['chat_id'])
    
    trade['last_active'] = int(time.time()) 
    chat_id, msg_id = trade['chat_id'], trade['dashboard_msg_id']
    u1, u2 = trade['users']
    d1, d2 = trade[u1], trade[u2]

    text = get_str("tr_dash_header", _, id=trade_id)
    
    for uid, d in [(u1, d1), (u2, d2)]:
        text += get_str("tr_dash_user_offers", _, name=d['name'])
        if d['money'] == 0 and d.get('umc', 0) == 0 and not d['gpus']:
            text += get_str("tr_dash_empty", _)
        else:
            if d['money'] > 0: 
                # 🔥 ФИКС РАСПАКОВКИ: Заменили затирочный "_" на "tax_rate"
                tax, total_needed, dividend_cut, tax_rate = await calculate_trade_tax(uid, d['money'])
                text += get_str("tr_dash_money", _, money=fmt(d['money']), tax_percent=int(tax_rate*100), tax=fmt(tax))
            if d.get('umc', 0) > 0:
                # 🔥 ФИКС РАСПАКОВКИ: Заменили затирочный "_" на "c_rate"
                c_tax, total_needed, c_rate = await calculate_crypto_trade_tax(uid, d['umc'])
                text += get_str("tr_dash_umc", _, umc=fmt(d['umc']), tax_percent=int(c_rate*100), tax=fmt(c_tax))
            for g in d['gpus']:
                gpu_info = GPUS[g['gpu_num']]
                text += get_str("tr_dash_gpu", _, emoji=gpu_info['emoji'], name=gpu_info['name'], mult=g['mult'], cond=g['cond'], qty=g['qty'])
        text += "\n"

    text += "════════════════════\n"
    builder = InlineKeyboardBuilder()

    if trade['status'] == "building":
        s1 = get_str("tr_status_ready", _) if d1['ready'] else get_str("tr_status_choosing", _)
        s2 = get_str("tr_status_ready", _) if d2['ready'] else get_str("tr_status_choosing", _)
        text += get_str("tr_status_row", _, name=d1['name'], status=s1) + get_str("tr_status_row", _, name=d2['name'], status=s2)
        
        builder.row(
            types.InlineKeyboardButton(text=get_str("tr_btn_add_money", _), callback_data=f"td_add_money_{trade_id}"),
            types.InlineKeyboardButton(text=get_str("tr_btn_add_umc", _), callback_data=f"td_add_umc_{trade_id}"),
            types.InlineKeyboardButton(text=get_str("tr_btn_add_gpu", _), callback_data=f"td_add_gpu_{trade_id}")
        )
        builder.row(types.InlineKeyboardButton(text=get_str("tr_btn_clear", _), callback_data=f"td_clear_{trade_id}"))
        builder.row(
            types.InlineKeyboardButton(text=get_str("tr_btn_ready", _), callback_data=f"td_ready_{trade_id}"),
            types.InlineKeyboardButton(text=get_str("tr_btn_cancel", _), callback_data=f"td_cancel_{trade_id}")
        )
        builder.adjust(3, 1, 2)

    elif trade['status'] == "confirming":
        s1 = get_str("tr_status_confirmed", _) if d1['confirmed'] else get_str("tr_status_thinking", _)
        s2 = get_str("tr_status_confirmed", _) if d2['confirmed'] else get_str("tr_status_thinking", _)
        text += get_str("tr_confirm_header", _)
        text += get_str("tr_status_row", _, name=d1['name'], status=s1) + get_str("tr_status_row", _, name=d2['name'], status=s2)
        
        builder.row(types.InlineKeyboardButton(text=get_str("tr_btn_execute", _), callback_data=f"td_confirm_{trade_id}"))
        builder.row(types.InlineKeyboardButton(text=get_str("tr_btn_edit", _), callback_data=f"td_unready_{trade_id}"))
        builder.row(types.InlineKeyboardButton(text=get_str("tr_btn_cancel", _), callback_data=f"td_cancel_{trade_id}"))
        builder.adjust(1, 1, 1)

    try: await bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id, reply_markup=builder.as_markup(), parse_mode="HTML")
    except Exception: pass

def reset_trade_readiness(trade):
    trade['status'] = "building"
    u1, u2 = trade['users']
    trade[u1]['ready'] = trade[u2]['ready'] = False
    trade[u1]['confirmed'] = trade[u2]['confirmed'] = False

# ==========================================
# 🕹 КНОПКИ УПРАВЛЕНИЯ ТРЕЙДОМ
# ==========================================
@router.callback_query(F.data.startswith("td_cancel_"))
async def td_cancel(callback: types.CallbackQuery, _=None):
    if not _: _ = await resolve_chat_translator(callback.message.chat.id, _)
    trade_id = int(callback.data.split("_")[2])
    if trade_id not in ACTIVE_TRADES: return await callback.answer(get_str("tr_alert_inactive", _), show_alert=True)
    
    user_id = callback.from_user.id
    trade = ACTIVE_TRADES[trade_id]
    u1, u2 = trade['users']
    if user_id not in [u1, u2]: return await callback.answer(get_str("tr_err_not_yours", _), show_alert=True)

    ACTIVE_TRADES.pop(trade_id, None)
    USER_TRADES.pop(u1, None)
    USER_TRADES.pop(u2, None)
    await callback.message.edit_text(get_str("tr_cancelled_by", _, id=trade_id, name=callback.from_user.first_name), parse_mode="HTML")

@router.callback_query(F.data.startswith("td_clear_"))
async def td_clear(callback: types.CallbackQuery, _=None):
    if not _: _ = await resolve_chat_translator(callback.message.chat.id, _)
    trade_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    if trade_id not in ACTIVE_TRADES or user_id not in ACTIVE_TRADES[trade_id]['users']: return
    
    trade = ACTIVE_TRADES[trade_id]
    trade[user_id]['money'] = 0
    trade[user_id]['umc'] = 0
    trade[user_id]['gpus'] = []
    
    reset_trade_readiness(trade)
    await update_trade_dashboard(callback.bot, trade_id, _=_)
    await callback.answer(get_str("tr_alert_cleared", _))

@router.callback_query(F.data.startswith("td_ready_"))
async def td_ready(callback: types.CallbackQuery, _=None):
    if not _: _ = await resolve_chat_translator(callback.message.chat.id, _)
    trade_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    if trade_id not in ACTIVE_TRADES or user_id not in ACTIVE_TRADES[trade_id]['users']: return
    
    trade = ACTIVE_TRADES[trade_id]
    trade[user_id]['ready'] = True
    
    u1, u2 = trade['users']
    if trade[u1]['ready'] and trade[u2]['ready']: trade['status'] = "confirming"
        
    await update_trade_dashboard(callback.bot, trade_id, _=_)
    await callback.answer(get_str("tr_alert_ready", _))

@router.callback_query(F.data.startswith("td_unready_"))
async def td_unready(callback: types.CallbackQuery, _=None):
    if not _: _ = await resolve_chat_translator(callback.message.chat.id, _)
    trade_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    if trade_id not in ACTIVE_TRADES or user_id not in ACTIVE_TRADES[trade_id]['users']: return
    
    trade = ACTIVE_TRADES[trade_id]
    reset_trade_readiness(trade)
    await update_trade_dashboard(callback.bot, trade_id, _=_)
    await callback.answer(get_str("tr_alert_edit_resume", _))

# ==========================================
# 💰 ДОБАВЛЕНИЕ ДЕНЕГ И КРИПТЫ
# ==========================================
@router.callback_query(F.data.startswith("td_add_money_"))
async def td_add_money(callback: types.CallbackQuery, state: FSMContext, _=None):
    if not _: _ = await resolve_chat_translator(callback.message.chat.id, _)
    trade_id = int(callback.data.split("_")[3])
    user_id = callback.from_user.id
    if trade_id not in ACTIVE_TRADES or user_id not in ACTIVE_TRADES[trade_id]['users']: return await callback.answer(get_str("tr_alert_not_participant", _), show_alert=True)
    
    balance = await get_balance(user_id)
    await state.set_state(TradeFSM.waiting_for_money)
    await state.update_data(trade_id=trade_id)
    
    msg = await callback.message.answer(get_str("tr_prompt_money", _, username=callback.from_user.username, balance=fmt(balance)), parse_mode="HTML")
    ACTIVE_TRADES[trade_id][user_id]['prompt_msg_id'] = msg.message_id
    await callback.answer()


@router.message(TradeFSM.waiting_for_money)
async def process_trade_money(message: types.Message, state: FSMContext, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    data = await state.get_data()
    trade_id, user_id = data.get('trade_id'), message.from_user.id

    prompt_msg_id = ACTIVE_TRADES.get(trade_id, {}).get(user_id, {}).get('prompt_msg_id')
    try: await message.delete()
    except: pass
    if prompt_msg_id:
        try: await message.bot.delete_message(message.chat.id, prompt_msg_id)
        except: pass

    if not trade_id or trade_id not in ACTIVE_TRADES: return await state.clear()
    trade = ACTIVE_TRADES[trade_id]
    if message.text.lower().strip() in ["отмена", "cancel"]: return await state.clear()

    amount_str = message.text.lower().replace('к', '000').replace('k', '000').replace('м', '000000').replace('m', '000000').replace(' ', '')
    if not amount_str.isdigit() or int(amount_str) <= 0:
        msg = await message.answer(get_str("tr_err_money_nan", _))
        await asyncio.sleep(3); await msg.delete()
        return await state.clear()

    amount = int(amount_str)
    # 🔥 ФИКС РАСПАКОВКИ: Убрали заглушку "_"
    tax, total_needed, dividend_cut, tax_rate = await calculate_trade_tax(user_id, amount)

    if await get_balance(user_id) < total_needed:
        msg = await message.answer(get_str("tr_err_money_insufficient", _, percent=int(tax_rate*100), total=fmt(total_needed)), parse_mode="HTML")
        await asyncio.sleep(4); await msg.delete()
        return await state.clear()

    trade[user_id]['money'] = amount
    reset_trade_readiness(trade)
    await state.clear()
    await update_trade_dashboard(message.bot, trade_id, _=_)


@router.callback_query(F.data.startswith("td_add_umc_"))
async def td_add_umc(callback: types.CallbackQuery, state: FSMContext, _=None):
    if not _: _ = await resolve_chat_translator(callback.message.chat.id, _)
    trade_id = int(callback.data.split("_")[3])
    user_id = callback.from_user.id
    if trade_id not in ACTIVE_TRADES or user_id not in ACTIVE_TRADES[trade_id]['users']: return await callback.answer(get_str("tr_alert_not_participant", _), show_alert=True)
    
    farm_data = await get_farm(user_id)
    umc_balance = int(farm_data.get('umc_balance', 0))
    
    await state.set_state(TradeFSM.waiting_for_crypto)
    await state.update_data(trade_id=trade_id)
    
    msg = await callback.message.answer(get_str("tr_prompt_umc", _, username=callback.from_user.username, balance=fmt(umc_balance)), parse_mode="HTML")
    ACTIVE_TRADES[trade_id][user_id]['prompt_msg_id'] = msg.message_id
    await callback.answer()


@router.message(TradeFSM.waiting_for_crypto)
async def process_trade_crypto(message: types.Message, state: FSMContext, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    data = await state.get_data()
    trade_id, user_id = data.get('trade_id'), message.from_user.id

    prompt_msg_id = ACTIVE_TRADES.get(trade_id, {}).get(user_id, {}).get('prompt_msg_id')
    try: await message.delete()
    except: pass
    if prompt_msg_id:
        try: await message.bot.delete_message(message.chat.id, prompt_msg_id)
        except: pass

    if not trade_id or trade_id not in ACTIVE_TRADES: return await state.clear()
    trade = ACTIVE_TRADES[trade_id]
    if message.text.lower().strip() in ["отмена", "cancel"]: return await state.clear()

    amount_str = message.text.lower().replace('к', '000').replace('k', '000').replace('м', '000000').replace('m', '000000').replace(' ', '')
    if not amount_str.isdigit() or int(amount_str) <= 0:
        msg = await message.answer(get_str("tr_err_umc_nan", _))
        await asyncio.sleep(3); await msg.delete()
        return await state.clear()

    amount = int(amount_str)
    # 🔥 ФИКС РАСПАКОВКИ: Убрали заглушку "_"
    c_tax, total_needed, c_rate = await calculate_crypto_trade_tax(user_id, amount)
    farm_data = await get_farm(user_id)

    if int(farm_data.get('umc_balance', 0)) < total_needed:
        msg = await message.answer(get_str("tr_err_umc_insufficient", _, percent=int(c_rate*100), total=fmt(total_needed)), parse_mode="HTML")
        await asyncio.sleep(4); await msg.delete()
        return await state.clear()

    trade[user_id]['umc'] = amount
    reset_trade_readiness(trade)
    await state.clear()
    await update_trade_dashboard(message.bot, trade_id, _=_)

# ==========================================
# 🖥 ДОБАВЛЕНИЕ ВИДЕОКАРТ В ТРЕЙД
# ==========================================
@router.callback_query(F.data.startswith("td_add_gpu_"))
async def td_select_gpu_model(callback: types.CallbackQuery, _=None):
    if not _: _ = await resolve_chat_translator(callback.message.chat.id, _)
    trade_id = int(callback.data.split("_")[3])
    user_id = callback.from_user.id
    if trade_id not in ACTIVE_TRADES or user_id not in ACTIVE_TRADES[trade_id]['users']: return await callback.answer(get_str("tr_alert_not_participant", _), show_alert=True)

    farm_data = await get_farm(user_id)
    builder = InlineKeyboardBuilder()
    has_gpus = False

    for gpu_id, gpu_info in GPUS.items():
        owned = farm_data.get(f'gpu_{gpu_id}', 0)
        if owned > 0:
            has_gpus = True
            builder.button(text=f"{gpu_info['emoji']} {gpu_info['name']} ({owned})", callback_data=f"td_mod_{gpu_id}_{trade_id}")

    if not has_gpus: return await callback.answer(get_str("tr_alert_no_gpus", _), show_alert=True)
    builder.button(text=get_str("tr_btn_close", _), callback_data="td_menu_cancel")
    builder.adjust(1)
    
    msg = await callback.message.answer(get_str("tr_prompt_gpu_model", _, username=callback.from_user.username), reply_markup=builder.as_markup())
    ACTIVE_TRADES[trade_id][user_id]['prompt_msg_id'] = msg.message_id
    await callback.answer()

@router.callback_query(F.data == "td_menu_cancel")
async def td_menu_cancel(callback: types.CallbackQuery):
    try: await callback.message.delete()
    except: pass
    await callback.answer()

@router.callback_query(F.data.startswith("td_mod_"))
async def td_select_gpu_batch(callback: types.CallbackQuery, _=None):
    if not _: _ = await resolve_chat_translator(callback.message.chat.id, _)
    parts = callback.data.split("_")
    gpu_num, trade_id = int(parts[2]), int(parts[3])
    user_id = callback.from_user.id
    gpu_id_str = f"gpu_{gpu_num}"

    pool = await get_db()
    async with pool.acquire() as db:
        batches = await db.fetch("SELECT multiplier, condition, SUM(qty) as total FROM gpu_batches WHERE user_id=$1 AND gpu_id=$2 AND condition > 0 GROUP BY multiplier, condition ORDER BY condition DESC", user_id, gpu_id_str)

    if not batches: return await callback.answer(get_str("tr_alert_no_active_gpus", _), show_alert=True)

    builder = InlineKeyboardBuilder()
    for b in batches:
        mult, cond, qty = b['multiplier'], b['condition'], b['total']
        builder.button(text=f"x{mult} | ❤️ {cond}% | {qty} шт.", callback_data=f"td_bat_{gpu_num}_{mult}_{cond}_{trade_id}")

    builder.button(text=get_str("tr_btn_close", _), callback_data="td_menu_cancel")
    builder.adjust(1)
    
    prompt_text = get_str("tr_prompt_gpu_batch", _, username=callback.from_user.username, name=GPUS[gpu_num]['name'])
    await callback.message.edit_text(prompt_text, reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("td_bat_"))
async def td_ask_qty(callback: types.CallbackQuery, state: FSMContext, _=None):
    if not _: _ = await resolve_chat_translator(callback.message.chat.id, _)
    parts = callback.data.split("_")
    gpu_num, mult, cond, trade_id = int(parts[2]), float(parts[3]), float(parts[4]), int(parts[5])
    
    await state.set_state(TradeFSM.waiting_for_qty)
    await state.update_data(gpu_num=gpu_num, mult=mult, cond=cond, trade_id=trade_id)
    
    prompt_text = get_str("tr_prompt_gpu_qty", _, username=callback.from_user.username, mult=mult, cond=cond)
    await callback.message.edit_text(prompt_text)

@router.message(TradeFSM.waiting_for_qty)
async def td_process_qty(message: types.Message, state: FSMContext, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    data = await state.get_data()
    user_id, trade_id = message.from_user.id, data.get('trade_id')

    prompt_msg_id = ACTIVE_TRADES.get(trade_id, {}).get(user_id, {}).get('prompt_msg_id')
    try: await message.delete()
    except: pass
    if prompt_msg_id:
        try: await message.bot.delete_message(message.chat.id, prompt_msg_id)
        except: pass

    if not trade_id or trade_id not in ACTIVE_TRADES: return await state.clear()
    trade = ACTIVE_TRADES[trade_id]
    if message.text.lower().strip() in ["отмена", "cancel"]: return await state.clear()

    if not message.text.isdigit() or int(message.text) <= 0:
        msg = await message.answer(get_str("tr_err_qty_nan", _))
        await asyncio.sleep(3); await msg.delete()
        return await state.clear()

    qty = int(message.text)
    gpu_num, mult, cond = data['gpu_num'], data['mult'], data['cond']
    gpu_id_str = f"gpu_{gpu_num}"

    pool = await get_db()
    async with pool.acquire() as db:
        available = await db.fetchval("SELECT SUM(qty) FROM gpu_batches WHERE user_id=$1 AND gpu_id=$2 AND multiplier=$3 AND ABS(condition - $4) < 0.1", user_id, gpu_id_str, mult, cond) or 0

    if qty > available:
        msg = await message.answer(get_str("tr_err_qty_insufficient", _, max=available))
        await asyncio.sleep(3); await msg.delete()
        return await state.clear()

    trade_gpus = trade[user_id]['gpus']
    existing = next((g for g in trade_gpus if g['gpu_num'] == gpu_num and g['mult'] == mult and g['cond'] == cond), None)
    
    if existing:
        if existing['qty'] + qty > available: qty = available - existing['qty']
        existing['qty'] += qty
    else:
        trade_gpus.append({'gpu_num': gpu_num, 'mult': mult, 'cond': cond, 'qty': qty})

    reset_trade_readiness(trade)
    await state.clear()
    await update_trade_dashboard(message.bot, trade_id, _=_)

# ==========================================
# ✅ ФИНАЛЬНОЕ ПОДТВЕРЖДЕНИЕ И ЭКЗЕКЬЮШЕН
# ==========================================
@router.callback_query(F.data.startswith("td_confirm_"))
async def td_confirm(callback: types.CallbackQuery, _=None):
    trade_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    if trade_id not in ACTIVE_TRADES or user_id not in ACTIVE_TRADES[trade_id]['users']: return
    
    trade = ACTIVE_TRADES[trade_id]
    trade[user_id]['confirmed'] = True
    await update_trade_dashboard(callback.bot, trade_id, _=_)
    
    u1, u2 = trade['users']
    if trade[u1]['confirmed'] and trade[u2]['confirmed']:
        await finalize_trade(callback.bot, trade_id)


async def finalize_trade(bot: Bot, trade_id: int):
    trade = ACTIVE_TRADES.pop(trade_id, None)
    if not trade: return
    
    chat_id, msg_id = trade['chat_id'], trade['dashboard_msg_id']
    u1_id, u2_id = trade['users']
    
    USER_TRADES.pop(u1_id, None)
    USER_TRADES.pop(u2_id, None)

    data1, data2 = trade[u1_id], trade[u2_id]
    
    # 🔥 ЖЕСТКИЙ ФИКС РАСПАКОВКИ: Никаких затирочных "_"
    tax1, req_m1, div1, tax_rate1 = await calculate_trade_tax(u1_id, data1['money'])
    tax2, req_m2, div2, tax_rate2 = await calculate_trade_tax(u2_id, data2['money'])

    c_tax1, c_req1, c_rate1 = await calculate_crypto_trade_tax(u1_id, data1.get('umc', 0))
    c_tax2, c_req2, c_rate2 = await calculate_crypto_trade_tax(u2_id, data2.get('umc', 0))

    pool = await get_db()
    success = False
    
    try:
        async with pool.acquire() as db:
            async with db.transaction():
                b1 = await db.fetchval("SELECT balance FROM users WHERE user_id = $1 FOR UPDATE", u1_id) or 0
                b2 = await db.fetchval("SELECT balance FROM users WHERE user_id = $1 FOR UPDATE", u2_id) or 0
                
                umc1 = await db.fetchval("SELECT umc_balance FROM farms WHERE user_id = $1 FOR UPDATE", u1_id) or 0.0
                umc2 = await db.fetchval("SELECT umc_balance FROM farms WHERE user_id = $1 FOR UPDATE", u2_id) or 0.0
                
                if b1 < req_m1 or b2 < req_m2: raise ValueError("Недостаточно ᴜ.")
                if umc1 < c_req1 or umc2 < c_req2: raise ValueError("Недостаточно UMC.")

                for g in data1['gpus']:
                    res = await db.fetchval("SELECT SUM(qty) FROM gpu_batches WHERE user_id=$1 AND gpu_id=$2 AND multiplier=$3 AND ABS(condition - $4) < 0.1", 
                                          u1_id, f"gpu_{g['gpu_num']}", g['mult'], g['cond']) or 0
                    if res < g['qty']: raise ValueError("SHORTFALL U1 GPUS")

                for g in data2['gpus']:
                    res = await db.fetchval("SELECT SUM(qty) FROM gpu_batches WHERE user_id=$1 AND gpu_id=$2 AND multiplier=$3 AND ABS(condition - $4) < 0.1", 
                                          u2_id, f"gpu_{g['gpu_num']}", g['mult'], g['cond']) or 0
                    if res < g['qty']: raise ValueError("SHORTFALL U2 GPUS")

                async def transfer_assets(from_user, to_user, gpus_list):
                    for g in gpus_list:
                        gpu_id_str = f"gpu_{g['gpu_num']}"
                        left_to_move = g['qty']
                        
                        batches = await db.fetch(
                            "SELECT id, qty FROM gpu_batches WHERE user_id=$1 AND gpu_id=$2 AND ABS(multiplier - $3) < 0.01 AND ABS(condition - $4) < 0.5 FOR UPDATE", 
                            from_user, gpu_id_str, float(g['mult']), float(g['cond'])
                        )
                        for b in batches:
                            if left_to_move <= 0: break
                            take = min(left_to_move, b['qty'])
                            
                            if take == b['qty']: await db.execute("DELETE FROM gpu_batches WHERE id=$1", b['id'])
                            else: await db.execute("UPDATE gpu_batches SET qty = qty - $1 WHERE id=$2", take, b['id'])
                                
                            await db.execute("INSERT INTO gpu_batches (user_id, gpu_id, multiplier, qty, condition, was_repaired) VALUES ($1, $2, $3, $4, $5, 0)", 
                                             to_user, gpu_id_str, g['mult'], take, g['cond'])
                            
                            await db.execute(f"UPDATE farms SET {gpu_id_str} = GREATEST(0, COALESCE({gpu_id_str}, 0) - $1) WHERE user_id = $2", take, from_user)
                            await db.execute(f"UPDATE farms SET {gpu_id_str} = COALESCE({gpu_id_str}, 0) + $1 WHERE user_id = $2", take, to_user)
                            left_to_move -= take
                            
                        if left_to_move > 0: raise ValueError("FRAGMENTED SEGMENT WEAR")

                if data1['gpus']: await transfer_assets(u1_id, u2_id, data1['gpus'])
                if data2['gpus']: await transfer_assets(u2_id, u1_id, data2['gpus'])

                if data1['money'] > 0:
                    await db.execute("UPDATE users SET balance = balance - $1 WHERE user_id = $2", req_m1, u1_id)
                    await db.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", data1['money'], u2_id)
                if data2['money'] > 0:
                    await db.execute("UPDATE users SET balance = balance - $1 WHERE user_id = $2", req_m2, u2_id)
                    await db.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", data2['money'], u1_id)

                if data1.get('umc', 0) > 0:
                    await db.execute("UPDATE farms SET umc_balance = umc_balance - $1 WHERE user_id = $2", c_req1, u1_id)
                    await db.execute("UPDATE farms SET umc_balance = umc_balance + $1 WHERE user_id = $2", float(data1['umc']), u2_id)
                if data2.get('umc', 0) > 0:
                    await db.execute("UPDATE farms SET umc_balance = umc_balance - $1 WHERE user_id = $2", c_req2, u2_id)
                    await db.execute("UPDATE farms SET umc_balance = umc_balance + $1 WHERE user_id = $2", float(data2['umc']), u1_id)

                success = True
    except Exception as e:
        logging.error(f"Критическая ошибка финализации обмена: {e}")
        success = False

    # Динамический язык для финального чека по языку чата
    _chat_trans = await resolve_chat_translator(chat_id)

    if success:
        farm1 = await get_farm(u1_id); farm2 = await get_farm(u2_id)
        await sync_farm_passive(u1_id, farm1, force_sync=True)
        await sync_farm_passive(u2_id, farm2, force_sync=True) 

        total_dividends = div1 + div2
        if total_dividends > 0: await add_to_dividend_pool(total_dividends)

        def get_transfer_details(data, translator_node):
            parts = []
            if data['money'] > 0: parts.append(f"💰 <b>{fmt(data['money'])} ᴜ</b>")
            if data.get('umc', 0) > 0: parts.append(f"🪙 <b>{fmt(data['umc'])} UMC</b>")
            for g in data['gpus']:
                gpu_info = GPUS.get(g['gpu_num'])
                parts.append(get_str("tr_report_gpu_line", translator_node, qty=g['qty'], name=gpu_info['name'], mult=g['mult']))
            return "\n    ├ ".join(parts) if parts else get_str("tr_report_nothing", translator_node)

        details1 = get_transfer_details(data1, _chat_trans)
        details2 = get_transfer_details(data2, _chat_trans)
        
        final_report = get_str("tr_report_body", translator=_chat_trans, id=trade_id, name1=data1['name'], details1=details1, name2=data2['name'], details2=details2)
        
        async with pool.acquire() as db:
            await db.execute("INSERT INTO trade_history (chat_id, trade_summary, timestamp) VALUES ($1, $2, $3)", chat_id, f"🤝 {data1['name']} ⮂ {data2['name']} (Трейд #{trade_id})", int(time.time()))

        try: await bot.edit_message_text(final_report, chat_id=chat_id, message_id=msg_id, parse_mode="HTML")
        except:
            try: await bot.send_message(chat_id, final_report, parse_mode="HTML")
            except: pass
    else:
        try: await bot.edit_message_text(get_str("tr_report_error", _chat_trans), chat_id=chat_id, message_id=msg_id, parse_mode="HTML")
        except: pass

# ==========================================
# 🛑 ТЕКСТОВАЯ ОТМЕНА И ИСТОРИЯ
# ==========================================
@router.message(F.text.lower().in_(["отменить трейд", "cancel trade"]))
async def cmd_cancel_trade_prompt(message: types.Message, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    user_id = message.from_user.id
    trade_id = USER_TRADES.get(user_id)
    if not trade_id or trade_id not in ACTIVE_TRADES: return await message.reply(get_str("tr_err_no_active", _))
    
    trade = ACTIVE_TRADES[trade_id]
    u1, u2 = trade['users']
    partner_id = u2 if user_id == u1 else u1
    partner_name = trade[partner_id]['name']

    builder = InlineKeyboardBuilder()
    builder.button(text=get_str("tr_btn_break", _), callback_data=f"tc_yes_{trade_id}")
    builder.button(text=get_str("tr_btn_return", _), callback_data=f"tc_no_{trade_id}")
    builder.adjust(2)
    
    prompt_text = get_str("tr_cancel_confirm_prompt", _, name=partner_name)
    await message.reply(prompt_text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("tc_yes_"))
async def cmd_cancel_trade_yes(callback: types.CallbackQuery, _=None):
    if not _: _ = await resolve_chat_translator(callback.message.chat.id, _)
    trade_id = int(callback.data.split("_")[2])
    if trade_id not in ACTIVE_TRADES: return await callback.message.edit_text(get_str("tr_err_not_actual", _), parse_mode="HTML")

    trade = ACTIVE_TRADES.pop(trade_id)
    u1, u2 = trade['users']
    USER_TRADES.pop(u1, None)
    USER_TRADES.pop(u2, None)

    await callback.message.edit_text(get_str("tr_cancel_success_alert", _), parse_mode="HTML")
    try: await callback.bot.edit_message_text(get_str("tr_cancelled_by_player", _), chat_id=trade['chat_id'], message_id=trade['dashboard_msg_id'], parse_mode="HTML")
    except: pass


@router.callback_query(F.data.startswith("tc_no_"))
async def cmd_cancel_trade_no(callback: types.CallbackQuery):
    try: await callback.message.delete()
    except: pass


@router.message(F.text.lower().in_(["история трейдов", "trade history"]))
async def cmd_trade_history_local(message: types.Message, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    chat_id = message.chat.id
    pool = await get_db()
    async with pool.acquire() as db:
        rows = await db.fetch("SELECT trade_summary, timestamp FROM trade_history WHERE chat_id = $1 ORDER BY timestamp DESC LIMIT 10", chat_id)

    if not rows: return await message.reply(get_str("tr_hist_local_empty", _))

    text = get_str("tr_hist_local_header", _)
    for r in rows:
        text += f"🕒 <i>{time.strftime('%d.%m %H:%M', time.localtime(r['timestamp']))}</i>\n{r['trade_summary']}\n\n"
    await message.reply(text, parse_mode="HTML")


@router.message(F.text.lower().in_(["глобальная история трейдов", "глобал трейды", "global trade history", "global trades"]))
async def cmd_trade_history_global(message: types.Message, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    pool = await get_db()
    async with pool.acquire() as db:
        rows = await db.fetch("SELECT trade_summary, timestamp FROM trade_history ORDER BY timestamp DESC LIMIT 15")

    if not rows: return await message.reply(get_str("tr_hist_global_empty", _))

    text = get_str("tr_hist_global_header", _)
    for r in rows:
        text += f"🕒 <i>{time.strftime('%d.%m %H:%M', time.localtime(r['timestamp']))}</i>\n{r['trade_summary']}\n\n"
    await message.reply(text, parse_mode="HTML")