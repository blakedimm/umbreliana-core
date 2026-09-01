import random
import asyncio
import time
import json
import logging
import os
import html
from aiogram import Router, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest

# Извлекаем функции из БД
from core.database import get_balance, add_balance, get_farm, update_farm

# Извлекаем конфиги видеокарт и пассивного ядра
from handlers.syndicate.farms import GPUS, sync_farm_passive 
from handlers.users.quests import process_quest_action

router = Router()

active_openings = {}

# Глобальный макрос форматирования чисел
fmt = lambda x: f"{int(x):,}".replace(',', ' ')

# ==========================================
# 🛡 ФЕЙЛСЕЙФ СИСТЕМА: РЕЗЕРВНАЯ ЛОКАЛИЗАЦИЯ
# ==========================================
LOCALES = {}
for lang in ["ru", "en"]:
    path = f"locales/{lang}.json"
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                LOCALES[lang] = json.load(f)
        except Exception as e:
            logging.error(f"Ошибка загрузки локали {lang} в кейсах: {e}")

def get_translator(lang: str):
    target_lang = lang if lang in LOCALES else "ru"
    def translate(key: str, **kwargs) -> str:
        text = LOCALES[target_lang].get(key, LOCALES["ru"].get(key, key))
        if kwargs:
            try: return text.format(**kwargs)
            except: pass
        return text
    return translate

async def resolve_chat_translator(chat_id: int, default__ = None):
    try:
        from core.database import get_db
        pool = await get_db()
        async with pool.acquire() as db:
            chat_lang = await db.fetchval("SELECT lang FROM chats WHERE chat_id = $1", chat_id)
            if chat_lang: return get_translator(chat_lang)
    except: pass
    return default__ if default__ else get_translator("ru")


# ==========================================
# 📦 ОБНОВЛЕННАЯ КОНФИГУРАЦИЯ С ТАБАМИ
# ==========================================
CASES = {
    # --- СТАНДАРТНАЯ ВКЛАДКА (валюта: UMBREL) ---
    1: {"name_key": "case_name_1", "desc_key": "case_desc_1", "price": 30_000, "currency": "umbrel", "tiers": [1]*12 + [2]*5 + [3]*2 + [4]*1},
    2: {"name_key": "case_name_2", "desc_key": "case_desc_2", "price": 75_000, "currency": "umbrel", "tiers": [2]*8 + [3]*7 + [4]*4 + [5]*1},
    3: {"name_key": "case_name_3", "desc_key": "case_desc_3", "price": 250_000, "currency": "umbrel", "tiers": [4]*11 + [5]*6 + [6]*2 + [7]*1},
    4: {"name_key": "case_name_4", "desc_key": "case_desc_4", "price": 750_000, "currency": "umbrel", "tiers": [6]*11 + [7]*6 + [8]*2 + [9]*1},
    5: {"name_key": "case_name_5", "desc_key": "case_desc_5", "price": 2_200_000, "currency": "umbrel", "tiers": [8]*11 + [9]*6 + [10]*2 + [11]*1},
    6: {"name_key": "case_name_6", "desc_key": "case_desc_6", "price": 6_000_000, "currency": "umbrel", "tiers": [10]*11 + [11]*6 + [12]*2 + [13]*1},
    7: {"name_key": "case_name_7", "desc_key": "case_desc_7", "price": 16_000_000, "currency": "umbrel", "tiers": [12]*12 + [13]*5 + [14]*2 + [15]*1},
    8: {"name_key": "case_name_8", "desc_key": "case_desc_8", "price": 55_000_000, "currency": "umbrel", "tiers": [14]*11 + [15]*6 + [16]*2 + [17]*1},
    9: {"name_key": "case_name_9", "desc_key": "case_desc_9", "price": 175_000_000, "currency": "umbrel", "tiers": [16]*30 + [17]*12 + [18]*5 + [19]*2 + [20]*1},
    10: {"name_key": "case_name_10", "desc_key": "case_desc_10", "price": 40_000_000, "currency": "umbrel", "tiers": "ALL"},
    
    # --- 🔥 ПРЕМИУМ ДОВЕСОК: РЕАЛЬНАЯ ВЫГОДА (Строго топовый сегмент GOLD карт!) ---
    101: {"name_key": "case_name_101", "desc_key": "case_desc_101", "price": 500, "currency": "stars", "tiers": [114]*8 + [121]*6 + [115]*4 + [116]*3 + [117]*2 + [119]*1},
    102: {"name_key": "case_name_102", "desc_key": "case_desc_102", "price": 2500, "currency": "stars", "tiers": [115]*10 + [116]*8 + [117]*6 + [118]*4 + [119]*3 + [120]*2}
}


# ==========================================
# 🏠 ХАБ КОНТЕЙНЕРОВ С ТАБАМИ
# ==========================================
@router.message(F.text.lower().in_(["кейсы", "cases", "box", "boxes", "контейнеры"]))
async def cmd_cases_menu(message: types.Message, _ = None):
    _ = await resolve_chat_translator(message.chat.id, _)
    await send_cases_menu(message.from_user.id, message, tab="standard", _=_)


@router.callback_query(F.data.startswith("cases_main_"))
async def callback_cases_main(callback: types.CallbackQuery, _ = None):
    parts = callback.data.split("_")
    user_id = int(parts[-1])
    tab = parts[2] if len(parts) == 4 else "standard"
    
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    if callback.from_user.id != user_id:
        return await callback.answer(_("cs_hands_off"), show_alert=True)
    
    await send_cases_menu(user_id, callback.message, is_edit=True, tab=tab, _=_)
    await callback.answer()


async def send_cases_menu(user_id, message_obj, is_edit=False, tab="standard", _ = None):
    from core.database import get_db
    pool = await get_db()
    async with pool.acquire() as db:
        u_balance = await db.fetchval("SELECT balance FROM users WHERE user_id = $1", user_id) or 0
        g_balance = await db.fetchval("SELECT gold_balance FROM users WHERE user_id = $1", user_id) or 0

    text = _("cs_hub_title")
    text += _("cs_hub_balance_u", balance=fmt(u_balance))
    if tab == "standard":
        text += _("cs_hub_balance_g", balance=fmt(g_balance))
    else:
        text += _("cs_hub_balance_stars")
    text += _("cs_hub_desc")

    builder = InlineKeyboardBuilder()
    
    for case_id, c_data in CASES.items():
        if tab == "standard" and case_id > 100: continue
        if tab == "premium" and case_id <= 100: continue
        
        cur_sign = " ⭐️" if c_data['currency'] == "stars" else " ᴜ"
        btn_text = f"{_(c_data['name_key'])} — {fmt(c_data['price'])}{cur_sign}"
        builder.button(text=btn_text, callback_data=f"case_view_{case_id}_{user_id}")
        
    builder.adjust(1)
    
    if tab == "standard":
        builder.row(types.InlineKeyboardButton(text=_("cs_btn_tab_premium"), callback_data=f"cases_main_premium_{user_id}"))
    else:
        builder.row(types.InlineKeyboardButton(text=_("cs_btn_tab_standard"), callback_data=f"cases_main_standard_{user_id}"))
        
    builder.row(types.InlineKeyboardButton(text=_("cs_btn_back_hub"), callback_data=f"farm_main_{user_id}"))

    if is_edit:
        try: await message_obj.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
        except: pass
    else:
        await message_obj.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


# ==========================================
# 👁 ПРОСМОТР ЛОТА
# ==========================================
@router.callback_query(F.data.startswith("case_view_"))
async def case_view_menu(callback: types.CallbackQuery, _ = None):
    owner_id = int(callback.data.split("_")[-1])
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    if callback.from_user.id != owner_id: return await callback.answer(_("cs_hands_off"), show_alert=True)

    user_id = callback.from_user.id
    case_id = int(callback.data.split("_")[2])
    c_data = CASES.get(case_id)
    
    builder = InlineKeyboardBuilder()
    
    if c_data['currency'] == "stars":
        price_text = _("cs_view_price_stars", price=fmt(c_data['price']))
        balance_text = _("cs_hub_balance_stars")
        
        builder.row(
            types.InlineKeyboardButton(text="x1", callback_data=f"case_open_{case_id}_1_{user_id}"),
            types.InlineKeyboardButton(text="x5", callback_data=f"case_open_{case_id}_5_{user_id}"),
            types.InlineKeyboardButton(text="x10", callback_data=f"case_open_{case_id}_10_{user_id}")
        )
    else:
        from core.database import get_db
        pool = await get_db()
        async with pool.acquire() as db:
            balance = await db.fetchval("SELECT balance FROM users WHERE user_id = $1", user_id) or 0
        
        price_text = _("cs_view_price_u", price=fmt(c_data['price']))
        balance_text = _("cs_hub_balance_u", balance=fmt(balance))
        max_qty = balance // c_data['price'] if c_data['price'] > 0 else 0
        
        builder.row(
            types.InlineKeyboardButton(text="x1", callback_data=f"case_open_{case_id}_1_{user_id}"),
            types.InlineKeyboardButton(text="x5", callback_data=f"case_open_{case_id}_5_{user_id}"),
            types.InlineKeyboardButton(text="x10", callback_data=f"case_open_{case_id}_10_{user_id}")
        )
        if max_qty > 0:
            builder.row(types.InlineKeyboardButton(text=f"🔥 MAX ({max_qty})", callback_data=f"case_open_{case_id}_max_{user_id}"))

    text = _("cs_view_title")
    text += _("cs_view_name", name=_(c_data['name_key']))
    text += price_text
    text += _("cs_view_desc", desc=_(c_data['desc_key']))
    text += balance_text

    back_tab = "premium" if case_id > 100 else "standard"
    builder.row(types.InlineKeyboardButton(text=_("cs_btn_back_list"), callback_data=f"cases_main_{back_tab}_{user_id}"))
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


# ==========================================
# 🎁 ЛОГИКА АКТИВАЦИИ И ВСКРЫТИЯ ПЛОМБ
# ==========================================
@router.callback_query(F.data.startswith("case_open_"))
async def case_open_process(callback: types.CallbackQuery, _ = None):
    owner_id = int(callback.data.split("_")[-1])
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    if callback.from_user.id != owner_id: return await callback.answer(_("cs_hands_off"), show_alert=True)

    parts = callback.data.split("_")
    user_id = callback.from_user.id
    case_id = int(parts[2])
    qty_val = parts[3]
    c_data = CASES.get(case_id)
    
    # 🔥 ЖЕЛЕЗНАЯ ВЕТКА TELEGRAM STARS: Сборка инвойса без возможности падения API
    if c_data['currency'] == "stars":
        await callback.answer()
        qty = int(qty_val) if qty_val.isdigit() else 1
        total_stars = c_data['price'] * qty
        
        title_str = str(_(c_data['name_key']))
        desc_str = str(_(c_data['desc_key']))
        
        # Защита от пустых строк в дескрипшене
        if not desc_str or desc_str.strip() == "":
            desc_str = "Premium Containment Cargo Suite."

        prices = [types.LabeledPrice(label=title_str[:30], amount=total_stars)]
        
        await callback.message.answer_invoice(
            title=title_str[:31],
            description=desc_str[:250],
            payload=f"case_stars:{case_id}:{qty}:{user_id}",
            provider_token="", 
            currency="XTR",
            prices=prices
        )
        return

    # ВЕТКА СТАНДАРТНОЙ ВАЛЮТЫ UMBREL
    from core.database import get_db
    pool = await get_db()
    async with pool.acquire() as db:
        balance = await db.fetchval("SELECT balance FROM users WHERE user_id = $1", user_id) or 0

    if qty_val == "max": qty = balance // c_data['price']
    else: qty = int(qty_val)

    if qty <= 0: return await callback.answer(_("cs_err_no_money"), show_alert=True)

    total_cost = c_data['price'] * qty
    if balance < total_cost:
        return await callback.answer(_("cs_err_no_cash"), show_alert=True)

    await add_balance(user_id, -total_cost)

    try: await callback.message.edit_reply_markup(reply_markup=None)
    except: pass

    await execute_case_drop(callback.message, user_id, case_id, qty, qty_val, _)


# ==========================================
# 🛡 ПРОВЕРКА ПЛАТЕЖЕЙ STARS (PRE-CHECKOUT)
# ==========================================
@router.pre_checkout_query()
async def case_pre_checkout(pre_checkout_query: types.PreCheckoutQuery):
    payload = pre_checkout_query.invoice_payload
    if not payload.startswith("case_stars:"):
        return await pre_checkout_query.answer(ok=False, error_message="Unknown payload session.")
    await pre_checkout_query.answer(ok=True)


# ==========================================
# ✅ УСПЕШНОЕ ЗАЧИСЛЕНИЕ STARS ОТ TELEGRAM
# ==========================================
@router.message(F.successful_payment)
async def case_successful_payment_handler(message: types.Message):
    payment_info = message.successful_payment
    payload = payment_info.invoice_payload
    
    if not payload.startswith("case_stars:"): return
        
    parts = payload.split(":")
    case_id = int(parts[1])
    qty = int(parts[2])
    user_id = int(parts[3])
    
    _ = await resolve_chat_translator(message.chat.id)
    await execute_case_drop(message, user_id, case_id, qty, str(qty), _, os_stars_flag=True)


# ==========================================
# 🧠 ОБЩЕЕ ЯДРО ГЕНЕРАЦИИ ДРОПА И КВЕСТОВ
# ==========================================
async def execute_case_drop(message_obj, user_id, case_id, qty, qty_val, _, os_stars_flag=False):
    c_data = CASES.get(case_id)
    from core.database import get_db
    pool = await get_db()
    
    drops = {} 
    total_drop_value = 0

    for unused_idx in range(qty):
        if c_data["tiers"] == "ALL":
            roll = random.randint(1, 100)
            if roll <= 60: drop_pool = [7, 8, 9, 10]
            elif roll <= 85: drop_pool = [11, 12, 13, 21]
            elif roll <= 95: drop_pool = [14, 15, 16]
            else: drop_pool = [17, 18, 19, 20]
            dropped_tier = random.choice(drop_pool)
        else:
            dropped_tier = random.choice(c_data["tiers"])
        
        drops[dropped_tier] = drops.get(dropped_tier, 0) + 1
        total_drop_value += GPUS[dropped_tier]['price']

    farm_data = await get_farm(user_id)
    await sync_farm_passive(user_id, farm_data)
    
    updates = {'last_collect': int(time.time())}
    for g_id, count in drops.items():
        updates[f"gpu_{g_id}"] = farm_data.get(f"gpu_{g_id}", 0) + count
    
    await update_farm(user_id, **updates)
    
    # Выставляем БИОС-множитель х1.2 для Золотых пачек (ID 101+)
    async with pool.acquire() as db:
        db_batches = await db.fetch("SELECT id, gpu_id, qty, condition, multiplier, was_repaired FROM gpu_batches WHERE user_id = $1 ORDER BY id ASC", user_id)
        for row in db_batches:
            if row['gpu_id'].startswith('gpu_') and row['gpu_id'].split('_')[-1].isdigit():
                gpu_num = int(row['gpu_id'].split('_')[1])
                if gpu_num > 100 and row['multiplier'] == 1.0:
                    await db.execute("UPDATE gpu_batches SET multiplier = 1.2 WHERE id = $1", row['id'])
                    
    await sync_farm_passive(user_id, await get_farm(user_id), force_sync=True)

    await process_quest_action(user_id, "any_game_play", qty)
    await process_quest_action(user_id, "case_open", qty)
    await process_quest_action(user_id, "farm_buy_gpu", qty)
    await process_quest_action(user_id, "farm_total_gpus", qty)

    if qty == 1 and not os_stars_flag:
        stages = [_("cs_anim_1"), _("cs_anim_2"), _("cs_anim_3")]
        for stage in stages:
            try:
                await message_obj.edit_text(_("cs_anim_title", name=_(c_data['name_key'])) + stage, parse_mode="HTML")
                await asyncio.sleep(1.2)
            except: pass
        
        gpu_id = list(drops.keys())[0]
        gpu_info = GPUS[gpu_id]
        
        if c_data['currency'] == "umbrel":
            profit = gpu_info['price'] - c_data['price']
            profit_text = _("cs_profit_up", amt=fmt(profit)) if profit >= 0 else _("cs_profit_down", amt=fmt(abs(profit)))
        else:
            profit_text = _("cs_profit_gold")
            
        res_text = _("cs_res_single", emoji=gpu_info['emoji'], name=gpu_info['name'], profit=profit_text)
    else:
        drop_lines = []
        for g_id, count in drops.items():
            drop_lines.append(f" • {GPUS[g_id]['emoji']} {GPUS[g_id]['name']} x{count}")
        
        if c_data['currency'] == "umbrel":
            total_profit = total_drop_value - (c_data['price'] * qty)
            profit_text = _("cs_profit_up", amt=fmt(total_profit)) if total_profit >= 0 else _("cs_profit_down", amt=fmt(abs(total_profit)))
            cur_sign = "ᴜ"
        else:
            profit_text = _("cs_profit_gold")
            cur_sign = "⭐️"
            
        res_text = _("cs_res_multi_body", 
                     qty=qty, cost=fmt(c_data['price'] * qty), cur=cur_sign, 
                     drops="\n".join(drop_lines), profit=profit_text)

    builder = InlineKeyboardBuilder()
    builder.button(text=_("cs_btn_repeat"), callback_data=f"case_open_{case_id}_{qty_val}_{user_id}")
    
    back_tab = "premium" if case_id > 100 else "standard"
    builder.button(text=_("cs_btn_back_list"), callback_data=f"cases_main_{back_tab}_{user_id}")
    builder.adjust(1)

    if os_stars_flag:
        await message_obj.answer(res_text, reply_markup=builder.as_markup(), parse_mode="HTML")
    else:
        try: await message_obj.edit_text(res_text, reply_markup=builder.as_markup(), parse_mode="HTML")
        except: await message_obj.answer(res_text, reply_markup=builder.as_markup(), parse_mode="HTML")