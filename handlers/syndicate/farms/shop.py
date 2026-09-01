# File: handlers/syndicate/shop.py
import time
import re
import random
import json
import logging
import os
from aiogram import Router, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.database import get_db, get_balance, add_balance, get_farm, update_farm, change_rating
from handlers.users.statuses import has_active_status
from handlers.users.quests import process_quest_action
from handlers.events.events_engine import GLOBAL_MODIFIERS

# 🔥 Явный импорт SLOTS_UPGRADES из конфигурации
from .config import GPUS, COOLING, SLOTS_UPGRADES, fmt
from .engine import perform_collection, sync_farm_passive, is_standard_gpu
from .menu import safe_edit_text, send_farm_menu

router = Router()
shop_cooldowns = {}

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
            logging.error(f"Ошибка загрузки локали {lang} в шопе фермы: {e}")

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
        pool = await get_db()
        async with pool.acquire() as db:
            chat_lang = await db.fetchval("SELECT lang FROM chats WHERE chat_id = $1", chat_id)
            if chat_lang: return get_translator(chat_lang)
    except: pass
    return default__ if default__ else get_translator("ru")


# ==========================================
# 🛠 УТИЛИТЫ ФОРМАТИРОВАНИЯ ДЛЯ КНОПОК
# ==========================================
def format_short_price(num: int) -> str:
    if num >= 1_000_000_000: return f"{num / 1_000_000_000:.1f}B"
    if num >= 1_000_000: return f"{num / 1_000_000:.1f}M"
    if num >= 1_000: return f"{num // 1_000}k"
    return str(num)

def get_short_name(full_name: str) -> str:
    clean_name = full_name.replace("Золотая ", "").replace("Золотой ", "").replace("Golden ", "").replace("Gold ", "")
    clean_name = clean_name.replace("NVIDIA ", "").replace("AMD ", "").replace("Intel ", "").replace("ASIC ", "")
    return clean_name.strip()


# ==========================================
# 🛒 ГЛАВНЫЙ МАГАЗИН
# ==========================================
@router.callback_query(F.data.startswith("farm_shop_"))
async def farm_shop_menu(callback: types.CallbackQuery, _ = None):
    owner_id = int(callback.data.split("_")[-1])
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    if callback.from_user.id != owner_id: return await callback.answer(_("shop_hands_off"), show_alert=True)

    user_id = callback.from_user.id
    balance = await get_balance(user_id)
    text = _("shop_title", balance=fmt(balance))
    
    builder = InlineKeyboardBuilder()
    sorted_gpus = sorted([(k, v) for k, v in GPUS.items() if k < 100], key=lambda x: x[1]['price'])
    
    for i, gpu in sorted_gpus:
        current_price = int(gpu['price'] * GLOBAL_MODIFIERS['shop'])
        short_price = format_short_price(current_price)
        short_name = get_short_name(gpu['name'])
        btn_text = f"[💰 {short_price}] {gpu['emoji']} {short_name}"
        builder.button(text=btn_text, callback_data=f"farm_item_{i}_{user_id}")
        
    builder.adjust(1)
    
    builder.row(
        types.InlineKeyboardButton(text=_("shop_btn_cooling"), callback_data=f"farm_cooling_{user_id}"),
        types.InlineKeyboardButton(text=_("shop_btn_racks"), callback_data=f"farm_slots_{user_id}")
    )
    
    if await has_active_status(user_id, 777): 
        builder.row(types.InlineKeyboardButton(text=_("shop_btn_vip"), callback_data=f"farm_vip_shop_{user_id}"))

    builder.row(types.InlineKeyboardButton(text=_("shop_btn_back"), callback_data=f"farm_main_{user_id}"))
    await safe_edit_text(callback, text, builder.as_markup())


@router.message(F.text.lower().in_(["магазин", "магазин вд", "маркет вд", "shop", "market"]))
async def cmd_text_shop_menu(message: types.Message, _ = None):
    _ = await resolve_chat_translator(message.chat.id, _)
    user_id = message.from_user.id
    balance = await get_balance(user_id)
    text = _("shop_title", balance=fmt(balance))
    
    builder = InlineKeyboardBuilder()
    sorted_gpus = sorted([(k, v) for k, v in GPUS.items() if k < 100], key=lambda x: x[1]['price'])
    
    for i, gpu in sorted_gpus:
        current_price = int(gpu['price'] * GLOBAL_MODIFIERS['shop'])
        short_price = format_short_price(current_price)
        short_name = get_short_name(gpu['name'])
        btn_text = f"[💰 {short_price}] {gpu['emoji']} {short_name}"
        builder.button(text=btn_text, callback_data=f"farm_item_{i}_{user_id}")
        
    builder.adjust(1)
    
    builder.row(
        types.InlineKeyboardButton(text=_("shop_btn_cooling"), callback_data=f"farm_cooling_{user_id}"),
        types.InlineKeyboardButton(text=_("shop_btn_racks"), callback_data=f"farm_slots_{user_id}")
    )
    
    if await has_active_status(user_id, 777): 
        builder.row(types.InlineKeyboardButton(text=_("shop_btn_vip"), callback_data=f"farm_vip_shop_{user_id}"))

    builder.row(types.InlineKeyboardButton(text=_("shop_btn_back"), callback_data=f"farm_main_{user_id}"))
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


# ==========================================
# 💎 VIP МАГАЗИН
# ==========================================
@router.callback_query(F.data.startswith("farm_vip_shop_"))
async def farm_vip_shop_menu(callback: types.CallbackQuery, _ = None):
    owner_id = int(callback.data.split("_")[-1])
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    if callback.from_user.id != owner_id: return await callback.answer(_("shop_hands_off"), show_alert=True)

    user_id = callback.from_user.id
    if not await has_active_status(user_id, 777): return await callback.answer(_("shop_sovereign_only"), show_alert=True)

    balance = await get_balance(user_id)
    text = _("shop_vip_title", balance=fmt(balance))

    builder = InlineKeyboardBuilder()
    sorted_gpus = sorted([(k, v) for k, v in GPUS.items() if k > 100], key=lambda x: x[1]['price'])

    for i, gpu in sorted_gpus:
        current_price = int(gpu['price'] * GLOBAL_MODIFIERS['shop'])
        short_price = format_short_price(current_price)
        short_name = get_short_name(gpu['name'])
        btn_text = f"[💰 {short_price}] {gpu['emoji']} {short_name}"
        builder.button(text=btn_text, callback_data=f"farm_item_{i}_{user_id}")

    builder.button(text=_("shop_btn_to_normal"), callback_data=f"farm_shop_{user_id}")
    builder.adjust(1)
    await safe_edit_text(callback, text, builder.as_markup())


# ==========================================
# 🔍 ПРОСМОТР ТОВАРА
# ==========================================
@router.callback_query(F.data.startswith("farm_item_"))
async def show_gpu_item(callback: types.CallbackQuery, _ = None):
    owner_id = int(callback.data.split("_")[-1])
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    if callback.from_user.id != owner_id: return await callback.answer(_("shop_hands_off"), show_alert=True)
    
    gpu_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    if gpu_id > 100 and not await has_active_status(user_id, 777):
        return await callback.answer(_("shop_sovereign_only"), show_alert=True)

    gpu = GPUS.get(gpu_id)
    balance = await get_balance(user_id)
    farm_data = await get_farm(user_id)
    owned = farm_data.get(f'gpu_{gpu_id}', 0)
    
    current_price = int(gpu['price'] * GLOBAL_MODIFIERS['shop'])
    max_qty = balance // current_price if current_price > 0 else 0
    sell_price = int(gpu['price'] * 0.5) 

    text = _("shop_item_details", emoji=gpu['emoji'], name=gpu['name'], price=fmt(gpu['price']), sell_price=fmt(sell_price), income=fmt(gpu['income']), heat=gpu['heat'], owned=owned, balance=fmt(balance))
    
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="1 pcs" if callback.message.text and " procurement" in callback.message.text.lower() else "1 шт", callback_data=f"farm_buy_{gpu_id}_1_{user_id}"),
        types.InlineKeyboardButton(text="5 pcs" if callback.message.text and " procurement" in callback.message.text.lower() else "5 шт", callback_data=f"farm_buy_{gpu_id}_5_{user_id}"),
        types.InlineKeyboardButton(text="10 pcs" if callback.message.text and " procurement" in callback.message.text.lower() else "10 шт", callback_data=f"farm_buy_{gpu_id}_10_{user_id}")
    )
    builder.row(types.InlineKeyboardButton(text=_("shop_btn_buy_max", qty=format_short_price(max_qty)), callback_data=f"farm_buy_{gpu_id}_max_{user_id}")) 
    
    if owned > 0:
        builder.row(
            types.InlineKeyboardButton(text="📉 Sell 1" if callback.message.text and " procurement" in callback.message.text.lower() else "📉 Продать 1", callback_data=f"farm_sell_{gpu_id}_1_{user_id}"),
            types.InlineKeyboardButton(text=_("shop_btn_sell_all", qty=format_short_price(owned)), callback_data=f"farm_sell_{gpu_id}_all_{user_id}")
        )
    
    back_btn_data = f"farm_vip_shop_{user_id}" if gpu_id > 100 else f"farm_shop_{user_id}"
    builder.row(types.InlineKeyboardButton(text=_("shop_btn_back_generic"), callback_data=back_btn_data))
    await safe_edit_text(callback, text, builder.as_markup())


# ==========================================
# 💳 ПОКУПКА ЧЕРЕЗ КНОПКУ (ЗАЩИЩЕННАЯ)
# ==========================================
@router.callback_query(F.data.startswith("farm_buy_"))
async def farm_buy_gpu_btn(callback: types.CallbackQuery, _ = None):
    owner_id = int(callback.data.split("_")[-1])
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    if callback.from_user.id != owner_id: return await callback.answer(_("shop_hands_off"), show_alert=True)

    user_id = callback.from_user.id
    now = time.time()
    if user_id in shop_cooldowns and (now - shop_cooldowns[user_id] < 1.5): return await callback.answer(_("shop_cooldown_processing"), show_alert=True)
    shop_cooldowns[user_id] = now

    parts = callback.data.split("_")
    if "cooling" in callback.data: return

    gpu_id, qty_str = int(parts[2]), parts[3]
    if gpu_id > 100 and not await has_active_status(user_id, 777): return await callback.answer(_("shop_sovereign_only"), show_alert=True)

    gpu = GPUS.get(gpu_id)
    current_price = int(gpu['price'] * GLOBAL_MODIFIERS['shop'])
    
    farm_data = await get_farm(user_id)
    # 🔥 ФИКС: Заменили заглушку "_" на "unused_profit", оберегая транслятор
    unused_profit, fire_message, *unused_collect = await perform_collection(user_id, farm_data)
    if fire_message: await callback.message.answer(fire_message, parse_mode="HTML")
        
    farm_data = await get_farm(user_id)
    max_slots = farm_data.get('max_slots', 30)
    pool = await get_db()
    
    async with pool.acquire() as db:
        balance = await db.fetchval("SELECT balance FROM users WHERE user_id = $1", user_id) or 0
        qty = (balance // current_price) if qty_str == 'max' else int(qty_str)
        
        if qty <= 0: return await callback.answer(_("shop_no_money_alert"), show_alert=True)
        total_price = current_price * qty
        if balance < total_price: return await callback.answer(_("shop_insufficient_alert"), show_alert=True)
            
        total_owned = await db.fetchval("SELECT SUM(qty) FROM gpu_batches WHERE user_id = $1 AND gpu_id LIKE 'gpu_%'", user_id) or 0
        if total_owned + qty > max_slots:
            return await callback.answer(_("shop_no_slots_alert", owned=total_owned, max_slots=max_slots, qty=qty), show_alert=True)

    await add_balance(user_id, -total_price)
    await update_farm(user_id, **{f'gpu_{gpu_id}': farm_data.get(f'gpu_{gpu_id}', 0) + qty})
    await sync_farm_passive(user_id, await get_farm(user_id), force_sync=True)


# ==========================================
# 📉 ПРОДАЖА ЧЕРЕЗ КНОПКУ
# ==========================================
@router.callback_query(F.data.startswith("farm_sell_"))
async def farm_sell_gpu_btn(callback: types.CallbackQuery, _ = None):
    owner_id = int(callback.data.split("_")[-1])
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    if callback.from_user.id != owner_id: return await callback.answer(_("shop_hands_off"), show_alert=True)
    
    user_id = callback.from_user.id
    now = time.time()
    if user_id in shop_cooldowns and (now - shop_cooldowns[user_id] < 1.5): return await callback.answer(_("shop_sell_cooldown"), show_alert=True)
    shop_cooldowns[user_id] = now

    parts = callback.data.split("_")
    gpu_id_int, qty_str = int(parts[2]), parts[3]
    gpu = GPUS.get(gpu_id_int)
    
    farm_data = await get_farm(user_id)
    gpu_id_str = f'gpu_{gpu_id_int}'
    owned = farm_data.get(gpu_id_str, 0)
    
    qty = owned if qty_str == 'all' else int(qty_str)
    if qty > owned or qty <= 0: return await callback.answer(_("shop_sell_qty_error"), show_alert=True)
        
    # 🔥 ФИКС: Заменили заглушку "_" на "unused_profit"
    unused_profit, fire_message, *unused_collect = await perform_collection(user_id, farm_data)
    if fire_message: await callback.message.answer(fire_message, parse_mode="HTML")
        
    farm_data = await get_farm(user_id) 
    owned = farm_data.get(gpu_id_str, 0)
    qty = min(qty, owned) 
    if qty <= 0: return await callback.message.answer(_("shop_sell_burnt"))
            
    avg_condition = 100.0
    pool = await get_db()
    
    async with pool.acquire() as db:
        async with db.transaction():
            rows = await db.fetch("SELECT id, qty, condition FROM gpu_batches WHERE user_id=$1 AND gpu_id=$2 ORDER BY condition ASC", user_id, gpu_id_str)
            collected = 0
            cond_points = 0.0
            
            for r in rows:
                if collected >= qty: break
                take = min(qty - collected, r['qty'])
                cond_points += take * r['condition']
                collected += take
                
                if take == r['qty']: await db.execute("DELETE FROM gpu_batches WHERE id = $1", r['id'])
                else: await db.execute("UPDATE gpu_batches SET qty = qty - $1 WHERE id = $2", take, r['id'])
                    
        if collected > 0: avg_condition = cond_points / collected

    sell_percent = 0.65 if await has_active_status(user_id, 2) else 0.50
    total_revenue = int((gpu['price'] * sell_percent) * (avg_condition / 100.0) * qty)

    await add_balance(user_id, total_revenue, is_income=True)
    await update_farm(user_id, **{gpu_id_str: owned - qty})
    await sync_farm_passive(user_id, await get_farm(user_id), force_sync=True)
    await process_quest_action(user_id, "farm_sell_gpu", qty)
    
    await callback.answer(_("shop_sell_success_alert", qty=qty, revenue=fmt(total_revenue)), show_alert=True)
    await send_farm_menu(user_id, callback.message, is_edit=True, _=_)


# ==========================================
# 💬 ТЕКСТОВЫЕ КОМАНДЫ (ПОКУПКА)
# ==========================================
@router.message(
    lambda msg: msg.text and 
    msg.text.lower().strip().startswith(("купить ", "buy ")) and 
    not msg.text.lower().strip().startswith(("купить статус", "buy status")) and 
    not any(word in msg.text.lower() for word in ["акци", "sh", "share", "stock"])
)
async def text_buy_gpu(message: types.Message, _ = None):
    _ = await resolve_chat_translator(message.chat.id, _)
    user_id = message.from_user.id
    now = time.time()
    if user_id in shop_cooldowns and (now - shop_cooldowns[user_id] < 1.5): return 
    shop_cooldowns[user_id] = now
    
    balance = await get_balance(user_id)
    raw_text = message.text.lower().replace("купить ", "").replace("buy ", "").strip()

    # --- 1. ВЕТКА СТОЕК ---
    if any(word in raw_text for word in ["стойку", "стойка", "каркас", "серверная", "шкаф", "узел", "ангар", "rack", "frame", "shelf", "cabinet"]):
        farm_data = await get_farm(user_id)
        current_level = farm_data.get('slots_level', 1)
        
        target_level = None
        for lvl, data in SLOTS_UPGRADES.items():
            if data['name'].lower() in raw_text or (raw_text.isdigit() and int(raw_text) == lvl):
                target_level = lvl
                break
                
        if not target_level: target_level = current_level + 1

        if target_level not in SLOTS_UPGRADES: return await message.reply(_("shop_rack_not_found"))
        if target_level <= current_level: return await message.reply(_("shop_rack_already_active"))

        target_slots_info = SLOTS_UPGRADES[target_level]
        price = target_slots_info.get('price', 0)
        if balance < price:
            return await message.reply(_("shop_rack_no_money", price=fmt(price), balance=fmt(balance)), parse_mode="HTML")

        await add_balance(user_id, -price)
        await update_farm(user_id, slots_level=target_level, max_slots=target_slots_info['capacity'])
        return await message.reply(_("shop_rack_success", name=target_slots_info['name'], capacity=target_slots_info['capacity']), parse_mode="HTML")

    # --- 2. ВЕТКА ОХЛАЖДЕНИЯ ---
    if any(word in raw_text for word in ["охлаждение", "охлад", "вентилятор", "кондиционер", "вытяжка", "дата-центр", "криокамера", "азот", "ноль", "cooling", "cooler", "fan", "ac", "ventilation", "nitrogen"]):
        farm_data = await get_farm(user_id)
        current_level = farm_data.get('cooling_level', 1)
        
        target_level = None
        for lvl, data in COOLING.items():
            if data['name'].lower() in raw_text or (raw_text.isdigit() and int(raw_text) == lvl):
                target_level = lvl
                break
                
        if not target_level: target_level = current_level + 1

        if target_level not in COOLING: return await message.reply(_("shop_cooling_not_found"))
        if target_level <= current_level: return await message.reply(_("shop_cooling_already_active"))

        price = COOLING[target_level].get('price', 0)
        if balance < price: return await message.reply(_("shop_cooling_no_money", price=fmt(price)), parse_mode="HTML")

        await add_balance(user_id, -price)
        await update_farm(user_id, cooling_level=target_level)
        return await message.reply(_("shop_cooling_success", name=COOLING[target_level]['name']), parse_mode="HTML")

    # --- 3. ВЕТКА ПОДСКАЗКИ ВИДЕОКАРТ ---
    if raw_text in ["видеокарту", "карту", "gpu", "card"]:
        affordable = {k: v for k, v in GPUS.items() if int(v['price'] * GLOBAL_MODIFIERS['shop']) <= balance}
        if not affordable: return await message.reply(_("shop_gpu_cant_afford"))
        best_id = max(affordable, key=lambda k: affordable[k]['price'])
        best_gpu = affordable[best_id]
        match = re.search(r'[a-zA-Z]?\d{2,}', best_gpu['name'])
        suggest_word = match.group(0) if match else best_gpu['name']

        # 🔥 ЖЕЛЕЗНЫЙ ФИКС: Если авто-подборщик выбрал VIP-карту, принудительно пишем "золотая" в подсказку
        if best_id > 100:
            suggest_word = f"золотая {suggest_word}"

        return await message.reply(_("shop_gpu_suggestion", emoji=best_gpu['emoji'], name=best_gpu['name'], price=fmt(best_gpu['price']), word=suggest_word), parse_mode="HTML")

    # --- 4. КЛАССИЧЕСКИЙ ПОИСК И ПОКУПКА GPU ---
    def find_gpu(search_str):
        search_str = search_str.lower().strip()
        is_golden = any(word in search_str for word in ["золот", "gold", "✨", "🌟", "vip"])
        clean_search = search_str
        for word in ["золотая", "золотую", "золотой", "золотые", "✨", "🌟", "vip", "gpu", "видеокарту", "вд", "карту", "golden", "gold", "card"]: 
            clean_search = clean_search.replace(word, "")
        clean_search = clean_search.strip()

        if not clean_search:
            return None, None

        for gid, gpu in GPUS.items():
            if is_golden and gid < 100: continue
            if not is_golden and gid > 100: continue
            model_digits = re.findall(r'\d+', gpu['name'])
            if model_digits and any(d in clean_search for d in model_digits): return gid, gpu

        for gid, gpu in GPUS.items():
            if is_golden and gid < 100: continue
            if not is_golden and gid > 100: continue
            if clean_search in gpu['name'].lower(): return gid, gpu
        return None, None

    parts = raw_text.split()
    target_id, target_gpu = find_gpu(raw_text)
    qty = 1

    if not target_gpu and len(parts) > 1 and parts[-1].isdigit():
        potential_qty = int(parts[-1])
        potential_search = " ".join(parts[:-1]).strip()
        tid, tgpu = find_gpu(potential_search)
        if tgpu:
            target_id = tid
            target_gpu = tgpu
            qty = potential_qty

    if not target_gpu: return await message.reply(_("shop_gpu_not_found"))
    if target_id > 100 and not await has_active_status(user_id, 777): return await message.reply(_("shop_gpu_sov_restricted"))
    if qty <= 0: return await message.reply(_("shop_gpu_qty_above_zero"))

    current_price = int(target_gpu['price'] * target_gpu.get('discount_percent', 1.0) if 'discount_percent' in target_gpu else target_gpu['price'] * GLOBAL_MODIFIERS['shop'])
    total_price = current_price * qty
    
    farm_data = await get_farm(user_id)
    # 🔥 ФИКС: Заменили заглушку "_" на "unused_profit"
    unused_profit, fire_message, *unused_collect = await perform_collection(user_id, farm_data)
    if fire_message: await message.answer(fire_message, parse_mode="HTML")
        
    farm_data = await get_farm(user_id)
    max_slots = farm_data.get('max_slots', 30)
    pool = await get_db()
    
    async with pool.acquire() as db:
        db_balance = await db.fetchval("SELECT balance FROM users WHERE user_id = $1", user_id) or 0
        if db_balance < total_price: return await message.reply(_("shop_gpu_text_no_money", price=fmt(total_price), balance=fmt(db_balance)))
            
        total_owned = await db.fetchval("SELECT SUM(qty) FROM gpu_batches WHERE user_id = $1 AND gpu_id LIKE 'gpu_%'", user_id) or 0
        if total_owned + qty > max_slots: return await message.reply(_("shop_gpu_text_no_slots", owned=total_owned, max_slots=max_slots, qty=qty))

    await add_balance(user_id, -total_price)
    await update_farm(user_id, **{f'gpu_{target_id}': farm_data.get(f'gpu_{target_id}', 0) + qty})
    await sync_farm_passive(user_id, await get_farm(user_id), force_sync=True)
        
    if target_id >= 16: await change_rating(user_id, min(30, 10 * qty))
    elif target_id >= 10: await change_rating(user_id, min(30, 5 * qty))
    elif target_id >= 5: await change_rating(user_id, min(30, 2 * qty))
        
    await process_quest_action(user_id, "farm_buy_gpu", qty)
    await message.reply(_("shop_gpu_text_buy_success", qty=qty, name=target_gpu['name'], price=fmt(total_price)), parse_mode="HTML")


# ==========================================
# 💥 ХЭНДЛЕР: ПРОДАТЬ ВСЕ ВИДЕОКАРТЫ
# ==========================================
@router.message(F.text.lower().in_(["продать все", "продать всё", "sell all"]))
async def cmd_sell_all_gpus(message: types.Message, _ = None):
    _ = await resolve_chat_translator(message.chat.id, _)
    user_id = message.from_user.id
    farm_data = await get_farm(user_id)
    
    # 🔥 ФИКС: Заменили заглушку "_" на "unused_profit"
    unused_profit, fire_message, *unused_collect = await perform_collection(user_id, farm_data)
    if fire_message: await message.answer(fire_message, parse_mode="HTML")
    farm_data = await get_farm(user_id) 
        
    total_revenue = 0
    total_cards_sold = 0
    updates = {}
    sell_percent = 0.65 if await has_active_status(user_id, 2) else 0.50
    
    pool = await get_db()
    async with pool.acquire() as db:
        all_user_batches = await db.fetch("SELECT gpu_id, qty, condition FROM gpu_batches WHERE user_id=$1 AND condition>0", user_id)
        
        batches_by_gpu = {}
        for b in all_user_batches:
            g_id = b['gpu_id']
            if g_id not in batches_by_gpu: batches_by_gpu[g_id] = []
            batches_by_gpu[g_id].append(b)

        for key, qty in farm_data.items():
            if is_standard_gpu(key) and qty > 0:
                gpu_num = int(key.split('_')[1])
                gpu_info = GPUS.get(gpu_num)
                if gpu_info:
                    gpu_batches = batches_by_gpu.get(key, [])
                    if gpu_batches:
                        total_qty_cond = sum(r['qty'] * r['condition'] for r in gpu_batches)
                        total_qty_sum = sum(r['qty'] for r in gpu_batches)
                        avg_cond = total_qty_cond / total_qty_sum if total_qty_sum > 0 else 100.0
                    else: avg_cond = 100.0
                    
                    revenue = int((gpu_info['price'] * sell_percent) * (avg_cond / 100.0) * qty)
                    total_revenue += revenue
                    total_cards_sold += qty
                    updates[key] = 0 

    if total_cards_sold == 0: return await message.reply(_("shop_sell_all_empty"))

    async with pool.acquire() as db:
        await db.execute("DELETE FROM gpu_batches WHERE user_id=$1 AND gpu_id LIKE 'gpu_%' AND condition > 0", user_id)

    await add_balance(user_id, total_revenue, is_income=True)
    updates['last_collect'] = int(time.time())
    await update_farm(user_id, **updates)
    await sync_farm_passive(user_id, await get_farm(user_id), force_sync=True)
    
    await process_quest_action(user_id, "farm_sell_gpu", total_cards_sold)
    await message.reply(_("shop_sell_all_success", qty=total_cards_sold, revenue=fmt(total_revenue)), parse_mode="HTML")


# ==========================================
# ⚙️ ХЭНДЛЕР: ШТУЧНАЯ ПРОДАЖА КАРТ ПО ИМЕНИ
# ==========================================
@router.message(F.text.lower().startswith(("продать ", "sell ")))
async def text_sell_gpu(message: types.Message, _ = None):
    _ = await resolve_chat_translator(message.chat.id, _)
    user_id = message.from_user.id
    now = time.time()
    if user_id in shop_cooldowns and (now - shop_cooldowns[user_id] < 1.5): return
    shop_cooldowns[user_id] = now
    
    text = message.text.lower()
    if text.startswith("продать "): text = text.replace("продать ", "").strip()
    else: text = text.replace("sell ", "").strip()

    def find_gpu(search_str):
        for gid, gpu in GPUS.items():
            if re.search(r'\b' + re.escape(search_str) + r'\b', gpu['name'].lower()): return gid, gpu
        for gid, gpu in GPUS.items():
            if search_str in gpu['name'].lower(): return gid, gpu
        return None, None

    parts = text.split()
    target_id, target_gpu = find_gpu(text)
    qty_str = "1"

    if not target_gpu and len(parts) > 1 and (parts[-1].isdigit() or parts[-1] in ["все", "всё", "all"]):
        qty_str = parts[-1]
        potential_search = " ".join(parts[:-1]).strip()
        tid, tgpu = find_gpu(potential_search)
        if tgpu:
            target_id = tid
            target_gpu = tgpu

    if not target_gpu: return await message.reply(_("shop_sell_text_not_found"))

    farm_data = await get_farm(user_id)
    owned = farm_data.get(f'gpu_{target_id}', 0)

    if owned <= 0: return await message.reply(_("shop_sell_text_not_owned", name=target_gpu['name']), parse_mode="HTML")

    qty = owned if qty_str in ["все", "всё", "all"] else int(qty_str)
    if qty <= 0 or qty > owned: return await message.reply(_("shop_sell_qty_error"))

    # 🔥 ФИКС: Заменили заглушку "_" на "unused_profit"
    unused_profit, fire_message, *unused_collect = await perform_collection(user_id, farm_data)
    if fire_message: await message.answer(fire_message, parse_mode="HTML")
        
    farm_data = await get_farm(user_id)
    owned = farm_data.get(f'gpu_{target_id}', 0)
    qty = min(qty, owned)
    if qty <= 0: return await message.reply(_("shop_sell_burnt"))

    gpu_id_str = f'gpu_{target_id}'  
    avg_condition = 100.0
    pool = await get_db()
    
    async with pool.acquire() as db:
        async with db.transaction():
            rows = await db.fetch("SELECT id, qty, condition FROM gpu_batches WHERE user_id=$1 AND gpu_id=$2 ORDER BY condition ASC", user_id, gpu_id_str)
            collected = 0
            cond_points = 0.0
            for r in rows:
                if collected >= qty: break
                take = min(qty - collected, r['qty'])
                cond_points += take * r['condition']
                collected += take
                
                if take == r['qty']: await db.execute("DELETE FROM gpu_batches WHERE id = $1", r['id'])
                else: await db.execute("UPDATE gpu_batches SET qty = qty - $1 WHERE id = $2", take, r['id'])
            
        if collected > 0: avg_condition = cond_points / collected

    sell_percent = 0.65 if await has_active_status(user_id, 2) else 0.50
    revenue = int((target_gpu['price'] * sell_percent) * (avg_condition / 100.0) * qty)
    
    await add_balance(user_id, revenue, is_income=True)
    await update_farm(user_id, **{f'gpu_{target_id}': owned - qty})
    await sync_farm_passive(user_id, await get_farm(user_id), force_sync=True)
    await process_quest_action(user_id, "farm_sell_gpu", qty)

    await message.reply(_("shop_gpu_text_buy_success", qty=qty, name=target_gpu['name'], price=fmt(revenue)), parse_mode="HTML")