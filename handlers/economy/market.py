import time
import re
import random
import asyncio
import os
import json
import logging
from aiogram import Router, F, types
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from core.database import get_db, get_balance, add_balance, get_farm, update_farm
from handlers.syndicate.farms import GPUS, sync_farm_passive, calculate_farm_state
from handlers.users.statuses import has_active_status
from handlers.events.events_engine import GLOBAL_MODIFIERS
from handlers.economy.crypto import get_market_state

router = Router()
ADMIN_ID = 1412940726 

fmt = lambda x: f"{int(x):,}".replace(',', ' ')

# ==========================================
# 🎨 БЕЗОПАСНАЯ ФЕЙЛСЕЙФ СИСТЕМА ЛОКАЛИЗАЦИИ
# ==========================================
FALLBACK_STRINGS = {
    "mk_bulk_err_format": "❌ Ошибка формата. Пример:\n<code>на рынок жц 3060 2, 5060 4</code>",
    "mk_sell_cancelled": "🚫 Продажа отменена.",
    "mk_sell_qty_err_nan": "❌ Напиши количество цифрами (например, 1) или «всё».",
    "mk_sell_qty_err_zero": "❌ Количество должно быть больше нуля!",
    "mk_sell_price_err_nan": "❌ Цена должна быть числом!",
    "mk_edit_err_low": "❌ Цена не может быть ниже 1 000 ─ ᴜ!"
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
            logging.error(f"Ошибка загрузки локали {l} в рынке: {e}")

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


def parse_bulk_query(text):
    items = []
    for part in text.split(','):
        part = part.strip()
        if not part: continue
        sub_parts = part.split()
        if len(sub_parts) == 1:
            qty = 1
            search_str = sub_parts[0].lower()
        else:
            qty_str = sub_parts[-1]
            if qty_str.isdigit():
                qty = int(qty_str)
                search_str = " ".join(sub_parts[:-1]).lower()
            else:
                qty = 1
                search_str = " ".join(sub_parts).lower()
        items.append((search_str, qty))
    return items

def find_gpu_universal(search_str):
    for gid, gpu in GPUS.items():
        if re.search(r'\b' + re.escape(search_str) + r'\b', gpu['name'].lower()): return gid, gpu
    for gid, gpu in GPUS.items():
        if search_str in gpu['name'].lower(): return gid, gpu
    return None, None

def find_gpu(search_str):
    search_str = search_str.lower().strip()
    for gid, gpu in GPUS.items():
        if re.search(r'\b' + re.escape(search_str) + r'\b', gpu['name'].lower()): return gid, gpu
    for gid, gpu in GPUS.items():
        if search_str in gpu['name'].lower(): return gid, gpu
    return None, None


class MarketSell(StatesGroup):
    waiting_for_qty = State()
    waiting_for_price = State()

class MarketEdit(StatesGroup):
    waiting_for_price_change = State()


async def get_market_page(page: int):
    pool = await get_db()
    async with pool.acquire() as db:
        total_lots = await db.fetchval("SELECT COUNT(*) FROM market") or 0
        total_pages = max(1, (total_lots + 9) // 10)
        page = max(1, min(page, total_pages))
        offset = (page - 1) * 10
        lots = await db.fetch("SELECT * FROM market ORDER BY price ASC, id ASC LIMIT 10 OFFSET $1", offset)
    return lots, page, total_pages, total_lots


async def send_market_message(message_or_call, page=1, is_edit=False, _=None):
    user_id = message_or_call.from_user.id
    lots, current_page, total_pages, total_lots = await get_market_page(page)

    if not lots:
        text = get_str("mk_empty_market", translator=_)
        markup = None
    else:
        text = get_str("mk_title", translator=_, total=total_lots)
        for lot in lots:
            gpu_num = int(lot['gpu_id'].split('_')[1])
            gpu = GPUS.get(gpu_num)
            if not gpu: continue
            
            seller = get_str("mk_state_seller", translator=_) if lot['seller_id'] == 0 else f"<code>{lot['seller_id']}</code>"
            cond_val = lot['condition']
            
            if lot['seller_id'] == user_id:
                cond_str = get_str("mk_cond_yours", translator=_, cond=cond_val)
            else:
                if cond_val >= 90: cond_str = get_str("mk_cond_a", translator=_)
                elif cond_val >= 60: cond_str = get_str("mk_cond_b", translator=_)
                elif cond_val >= 30: cond_str = get_str("mk_cond_c", translator=_)
                else: cond_str = get_str("mk_cond_d", translator=_)
            
            text += get_str("mk_lot_row", translator=_, id=lot['id'], seller=seller, emoji=gpu['emoji'], name=gpu['name'], qty=lot['qty'], cond_str=cond_str, price=fmt(lot['price']))

        text += get_str("mk_footer", translator=_)
        buttons = []
        if current_page > 1:
            buttons.append(InlineKeyboardButton(text=get_str("mk_btn_back", translator=_), callback_data=f"market_page_{current_page - 1}_{user_id}"))
        if current_page < total_pages:
            buttons.append(InlineKeyboardButton(text=get_str("mk_btn_forward", translator=_), callback_data=f"market_page_{current_page + 1}_{user_id}"))
        markup = InlineKeyboardMarkup(inline_keyboard=[buttons]) if buttons else None

    if is_edit:
        try: await message_or_call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        except: pass
    else:
        await message_or_call.reply(text, reply_markup=markup, parse_mode="HTML")


@router.message(F.text.lower().in_(["рынок", "барахолка", "маркет", "market", "flea market", "bazaar"]))
async def cmd_market_list(message: types.Message, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    await send_market_message(message, page=1, is_edit=False, _=_)


@router.callback_query(F.data.startswith("market_page_"))
async def callback_market_page(call: types.CallbackQuery, _=None):
    if not _: _ = await resolve_chat_translator(call.message.chat.id, _)
    parts = call.data.split('_')
    page, owner_id = int(parts[2]), int(parts[3])
    if call.from_user.id != owner_id:
        return await call.answer(get_str("mk_alert_menu_foreign", translator=_), show_alert=True)

    await send_market_message(call, page, is_edit=True, _=_)
    try: await call.answer()
    except: pass


# ==========================================
# 🛒 МАССОВЫЙ ЖЦ-ВЫБРОС НА РЫНОК
# ==========================================
@router.message(F.text.lower().startswith(("на рынок жц ", "to market bulk ")))
async def cmd_market_bulk_sell(message: types.Message, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    prefix = "на рынок жц " if message.text.lower().startswith("на рынок жц ") else "to market bulk "
    raw_text = message.text.lower().replace(prefix, "").strip()
    
    parsed_items = parse_bulk_query(raw_text)
    if not parsed_items: return await message.reply(get_str("mk_bulk_err_format", _), parse_mode="HTML")

    user_id = message.from_user.id
    farm_data = await get_farm(user_id)
    balance = await get_balance(user_id)
    
    log_messages, updates, lots_to_insert = [], {}, []
    total_deposit = 0
    shop_mod = GLOBAL_MODIFIERS.get('shop', 1.0)
    
    pool = await get_db()
    async with pool.acquire() as db:
        for search_str, qty in parsed_items:
            gid, gpu = find_gpu_universal(search_str)
            if not gpu:
                log_messages.append(get_str("mk_bulk_row_unrecognized", _, name=search_str))
                continue
                
            if gid > 100:
                log_messages.append(get_str("mk_bulk_row_gold_err", _, name=gpu['name']))
                continue

            gpu_id_str = f'gpu_{gid}'
            owned = farm_data.get(gpu_id_str, 0) - updates.get(gpu_id_str, 0)
            
            if owned < qty:
                log_messages.append(get_str("mk_bulk_row_insufficient", _, name=gpu['name'], owned=owned, qty=qty))
                continue
                
            avg_cond = await db.fetchval("SELECT AVG(condition) FROM gpu_batches WHERE user_id = $1 AND gpu_id = $2 AND condition > 0", user_id, gpu_id_str)
            avg_cond = avg_cond if avg_cond is not None else 100.0
            
            dynamic_gpu_price = int(gpu['price'] * shop_mod)
            suggested_price = int((dynamic_gpu_price * qty) * (avg_cond / 100.0) * 0.8)
            if suggested_price < 1000: suggested_price = 1000
            
            is_magnate = await has_active_status(user_id, 2)
            is_enthusiast = await has_active_status(user_id, 0)

            if is_magnate: deposit = 0
            elif is_enthusiast: deposit = int(suggested_price * 0.03) 
            else: deposit = int(suggested_price * 0.05) 
            
            total_deposit += deposit
            lots_to_insert.append((gid, gpu, qty, suggested_price, avg_cond, deposit))
            updates[gpu_id_str] = farm_data.get(gpu_id_str, 0) - qty
            
    if total_deposit > 0 and balance < total_deposit:
        return await message.reply(get_str("mk_bulk_err_deposit", _, price=fmt(total_deposit)), parse_mode="HTML")

    if not lots_to_insert: return await message.reply(get_str("mk_bulk_err_no_lots", _), parse_mode="HTML")

    await add_balance(user_id, -total_deposit)
    
    async with pool.acquire() as db:
        async with db.transaction():
            for gid, gpu, qty, price, cond, dep in lots_to_insert:
                try:
                    await db.execute("""
                        INSERT INTO market (seller_id, gpu_id, price, qty, condition, created_at, deposit) 
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """, user_id, f"gpu_{gid}", price, qty, round(cond, 1), int(time.time()), dep)
                    log_messages.append(get_str("mk_bulk_row_success", _, emoji=gpu['emoji'], name=gpu['name'], qty=qty, price=fmt(price)))
                except Exception as e:
                    logging.error(f"DB Error: {e}") 
                    log_messages.append(get_str("mk_bulk_row_err_generic", _, name=gpu['name']))

    if updates:
        updates['last_wear_update'] = int(time.time())
        await update_farm(user_id, **updates)
        await sync_farm_passive(user_id, await get_farm(user_id))

    await message.reply(get_str("mk_bulk_success_final", _, log="\n".join(log_messages), deposit=fmt(total_deposit)), parse_mode="HTML")


# ==========================================
# 🏷 ШТУЧНОЕ ВЫСТАВЛЕНИЕ ЛОТА (FSM)
# ==========================================
@router.message(F.text.lower().startswith(("на рынок ", "to market ")))
async def cmd_market_sell_start(message: types.Message, state: FSMContext, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    prefix_len = 9 if message.text.lower().startswith("на рынок ") else 10
    search_term = message.text[prefix_len:].strip()
    if not search_term: return await message.reply(get_str("mk_sell_err_args", _), parse_mode="HTML")

    gpu_num, target_gpu = find_gpu(search_term)
    if not target_gpu: return await message.reply(get_str("mk_sell_err_not_found", _, name=search_term))

    if gpu_num > 100: return await message.reply(get_str("mk_sell_err_gold", _), parse_mode="HTML")

    user_id = message.from_user.id
    gpu_id_str = f"gpu_{gpu_num}"
    farm_data = await get_farm(user_id)
    current_count = farm_data.get(gpu_id_str, 0)

    if current_count <= 0: return await message.reply(get_str("mk_sell_err_not_owned", _, name=target_gpu['name']), parse_mode="HTML")

    await state.update_data(gpu_num=gpu_num, gpu_name=target_gpu['name'], emoji=target_gpu['emoji'], max_qty=current_count)
    await state.set_state(MarketSell.waiting_for_qty)

    await message.reply(get_str("mk_sell_qty_prompt", _, count=current_count, emoji=target_gpu['emoji'], name=target_gpu['name']), parse_mode="HTML")


@router.message(MarketSell.waiting_for_qty)
async def cmd_market_sell_qty(message: types.Message, state: FSMContext, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    text = message.text.lower().strip()
    if text in ["отмена", "cancel", "назад", "back"]:
        await state.clear()
        return await message.reply(get_str("mk_sell_cancelled", _))

    data = await state.get_data()
    max_qty, gpu_num = data['max_qty'], data['gpu_num']

    if text in ["max", "макс", "все", "всё", "all"]: qty = max_qty
    else:
        qty_str = re.sub(r'\D', '', text)
        if not qty_str: return await message.reply(get_str("mk_sell_qty_err_nan", _))
        qty = int(qty_str)

    if qty <= 0: return await message.reply(get_str("mk_sell_qty_err_zero", _))
    if qty > max_qty: return await message.reply(get_str("mk_sell_qty_err_limit", _, max_qty=max_qty))

    user_id = message.from_user.id
    gpu_id_str = f"gpu_{gpu_num}"

    pool = await get_db()
    async with pool.acquire() as db:
        batches = await db.fetch("SELECT qty, condition FROM gpu_batches WHERE user_id=$1 AND gpu_id=$2 AND condition>0 ORDER BY condition ASC", user_id, gpu_id_str)
        left, total_cond = qty, 0.0
        for b in batches:
            if left <= 0: break
            take = min(b['qty'], left)
            total_cond += b['condition'] * take
            left -= take
        avg_condition = total_cond / qty if qty > 0 else 100.0

    await state.update_data(qty=qty, avg_condition=avg_condition)
    await state.set_state(MarketSell.waiting_for_price)

    await message.reply(get_str("mk_sell_price_prompt", _, qty=qty, cond=avg_condition), parse_mode="HTML")


@router.message(MarketSell.waiting_for_price)
async def cmd_market_sell_price(message: types.Message, state: FSMContext, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    if message.text.lower().strip() in ["отмена", "cancel"]:
        await state.clear()
        return await message.reply(get_str("mk_sell_cancelled", _))

    price_str = message.text.lower().replace('к', '000').replace('k', '000').replace('м', '000000').replace('m', '000000').replace(' ', '')
    if not price_str.isdigit(): return await message.reply(get_str("mk_sell_price_err_nan", _))

    price = int(price_str)
    if price < 1000: return await message.reply(get_str("mk_sell_price_err_low", _))

    user_id = message.from_user.id
    is_magnate = await has_active_status(user_id, 2)
    is_enthusiast = await has_active_status(user_id, 0)

    deposit = 0 if is_magnate else (int(price * 0.03) if is_enthusiast else int(price * 0.05))
    if await get_balance(user_id) < deposit:
        return await message.reply(get_str("mk_sell_price_err_deposit", _, deposit=fmt(deposit)))

    data = await state.get_data()
    await state.clear()

    gpu_num, qty, avg_condition = data['gpu_num'], data['qty'], data['avg_condition']
    gpu_id_str = f"gpu_{gpu_num}"

    farm_data = await get_farm(user_id)
    if farm_data.get(gpu_id_str, 0) < qty: return await message.reply(get_str("mk_sell_err_inventory_lost", _))

    await add_balance(user_id, -deposit)
    await update_farm(user_id, **{gpu_id_str: farm_data.get(gpu_id_str, 0) - qty})
    
    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            batches = await db.fetch("SELECT id, qty FROM gpu_batches WHERE user_id=$1 AND gpu_id=$2 AND condition>0 ORDER BY condition ASC", user_id, gpu_id_str)
            left_to_remove = qty
            for batch in batches:
                if left_to_remove <= 0: break
                b_id, b_qty = batch['id'], batch['qty']
                if b_qty <= left_to_remove:
                    await db.execute("DELETE FROM gpu_batches WHERE id = $1", b_id)
                    left_to_remove -= b_qty
                else:
                    await db.execute("UPDATE gpu_batches SET qty = qty - $1 WHERE id = $2", left_to_remove, b_id)
                    left_to_remove = 0
                    
            lot_id = await db.fetchval(
                "INSERT INTO market (seller_id, gpu_id, price, qty, condition, created_at, deposit) VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id", 
                user_id, gpu_id_str, price, qty, avg_condition, int(time.time()), deposit
            )

    await message.reply(get_str("mk_sell_success_final", _, price=fmt(price), deposit=fmt(deposit), id=lot_id), parse_mode="HTML")

    # Рассылка VIP подписчикам на их родных языках
    async def notify_market_vips():
        from handlers.users.statuses import get_vip_market_subscribers
        vips = await get_vip_market_subscribers()
        if not vips: return

        gpu_name = GPUS[gpu_num]['name']
        
        for vip_id in vips:
            if vip_id == user_id: continue 
            async with pool.acquire() as db_loc:
                v_lang = await db_loc.fetchval("SELECT lan FROM users WHERE user_id = $1", vip_id) or "ru"
            _v = get_translator(v_lang)
            
            is_deal = get_str("mk_vip_deal_hot", _v) if price < (GPUS[gpu_num]['price'] * qty * 0.9) else get_str("mk_vip_deal_new", _v)
            text_vip = get_str("mk_vip_notify_text", _v, is_deal=is_deal, name=gpu_name, qty=qty, cond=avg_condition, price=fmt(price))
            
            try:
                await message.bot.send_message(vip_id, text_vip, parse_mode="HTML")
                await asyncio.sleep(0.05)
            except: pass

    asyncio.create_task(notify_market_vips())


# ==========================================
# 🛒 КУПИТЬ ЛОТ
# ==========================================
@router.message(F.text.lower().startswith(("купить лот ", "buy lot ")))
async def cmd_market_buy(message: types.Message, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    parts = message.text.split()
    if len(parts) < 3 or not parts[2].isdigit(): return await message.reply(get_str("mk_buy_err_args", _), parse_mode="HTML")
    
    lot_id, buyer_id = int(parts[2]), message.from_user.id
    pool = await get_db()
    async with pool.acquire() as db: lot = await db.fetchrow("SELECT * FROM market WHERE id = $1", lot_id)

    if not lot: return await message.reply(get_str("mk_buy_err_not_found", _))

    lot_dict = dict(lot)
    seller_id, price, qty, cond, gpu_id_str = lot_dict['seller_id'], lot_dict['price'], lot_dict['qty'], lot_dict['condition'], lot_dict['gpu_id']
    deposit = lot_dict.get('deposit', 0)
    gpu_num = int(gpu_id_str.split('_')[1])

    if buyer_id == seller_id: return await message.reply(get_str("mk_buy_err_self", _))
    if await get_balance(buyer_id) < price: return await message.reply(get_str("mk_buy_err_no_money", _, price=fmt(price)), parse_mode="HTML")

    success = False
    async with pool.acquire() as db:
        async with db.transaction():
            lot_check = await db.fetchrow("SELECT * FROM market WHERE id = $1 FOR UPDATE", lot_id)
            if not lot_check: return await message.reply(get_str("mk_buy_err_intercepted", _))

            await db.execute("DELETE FROM market WHERE id = $1", lot_id)
            await db.execute("INSERT INTO gpu_batches (user_id, gpu_id, multiplier, qty, condition, was_repaired) VALUES ($1, $2, 1.0, $3, $4, 0)", 
                             buyer_id, gpu_id_str, qty, cond)
            success = True

    if not success: return

    await add_balance(buyer_id, -price)
    if seller_id != 0:
        await add_balance(seller_id, price + deposit)
        from core.database import change_rating
        await change_rating(seller_id, 5)
        
        async with pool.acquire() as db:
            s_lang = await db.fetchval("SELECT lang FROM users WHERE user_id = $1", seller_id) or "ru"
        _s = get_translator(s_lang)
        try:
            await message.bot.send_message(seller_id, get_str("mk_buy_seller_notify", _s, qty=qty, name=GPUS[gpu_num]['name'], price=fmt(price), deposit=fmt(deposit)), parse_mode="HTML")
        except: pass

    farm_data = await get_farm(buyer_id)
    await update_farm(buyer_id, **{gpu_id_str: farm_data.get(gpu_id_str, 0) + qty})
    await message.reply(get_str("mk_buy_buyer_success", _, qty=qty, name=GPUS[gpu_num]['name'], price=fmt(price)), parse_mode="HTML")

    if buyer_id != ADMIN_ID:
        buyer_name = message.from_user.first_name
        if message.from_user.username: buyer_name += f" (@{message.from_user.username})"
        
        async with pool.acquire() as db:
            a_lang = await db.fetchval("SELECT lang FROM users WHERE user_id = $1", ADMIN_ID) or "ru"
        _a = get_translator(a_lang)
        
        seller_name = get_str("mk_admin_log_seller_state", _a) if seller_id == 0 else get_str("mk_admin_log_seller_fiat", _a, id=seller_id)
        admin_text = get_str("mk_admin_log_deal", _a, buyer=buyer_name, qty=qty, name=GPUS[gpu_num]['name'], price=fmt(price), seller=seller_name)
        try: await message.bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML")
        except: pass


# ==========================================
# ❌ СНЯТЬ С РЫНКА
# ==========================================
@router.message(F.text.lower().startswith(("с рынка ", "cancel lot ")))
async def cmd_market_remove(message: types.Message, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    parts = message.text.split()
    if len(parts) < 3 or not parts[2].isdigit(): return await message.reply(get_str("mk_remove_err_args", _), parse_mode="HTML")
    
    lot_id, user_id = int(parts[2]), message.from_user.id
    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            lot = await db.fetchrow("SELECT * FROM market WHERE id = $1 FOR UPDATE", lot_id)
            if not lot: return await message.reply(get_str("mk_remove_err_not_found", _))
            if lot['seller_id'] != user_id and user_id != ADMIN_ID: return await message.reply(get_str("mk_remove_err_rights", _))

            deposit = lot['deposit']
            await db.execute("DELETE FROM market WHERE id = $1", lot_id)
            if lot['seller_id'] != 0:
                await db.execute("INSERT INTO gpu_batches (user_id, gpu_id, multiplier, qty, condition, was_repaired) VALUES ($1, $2, 1.0, $3, $4, 0)", 
                                 lot['seller_id'], lot['gpu_id'], lot['qty'], lot['condition'])

    if lot['seller_id'] != 0:
        farm_data = await get_farm(lot['seller_id'])
        await update_farm(lot['seller_id'], **{lot['gpu_id']: farm_data.get(lot['gpu_id'], 0) + lot['qty']})

    burn_str = get_str("mk_remove_burn_text", _, deposit=fmt(deposit)) if deposit > 0 else ""
    await message.reply(get_str("mk_remove_success", _, burn_text=burn_str), parse_mode="HTML")


# ==========================================
# 👑 АДМИН: СОЗДАТЬ И КЛИРИНГ РЫНКА
# ==========================================
@router.message(F.text.lower().startswith("+лот ") & (F.from_user.id == ADMIN_ID))
async def cmd_admin_spawn_lot(message: types.Message, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    parts = message.text.split()
    if len(parts) < 3: return await message.reply(get_str("mk_spawn_err_args", _), parse_mode="HTML")
    
    price_str = parts[-1].lower().replace('к', '000').replace('k', '000').replace('м', '000000').replace('m', '000000')
    if not price_str.isdigit(): return await message.reply(get_str("mk_spawn_err_price", _))
    price = int(price_str)
    
    search_term = " ".join(parts[1:-1])
    gpu_num, target_gpu = find_gpu(search_term)
    if not target_gpu: return await message.reply(get_str("mk_spawn_err_not_found", _, name=search_term))
        
    gpu_id_str = f"gpu_{gpu_num}"
    pool = await get_db()
    async with pool.acquire() as db:
        lot_id = await db.fetchval(
            "INSERT INTO market (seller_id, gpu_id, price, qty, condition, created_at, deposit) VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id", 
            0, gpu_id_str, price, 1, 100.0, int(time.time()), 0
        )
    await message.reply(get_str("mk_spawn_success", _, id=lot_id, price=fmt(price)), parse_mode="HTML")


@router.message(F.text.lower().in_(["очистить рынок", "clear market"]))
async def cmd_admin_clear_market(message: types.Message, _=None):
    if message.from_user.id != ADMIN_ID: return
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    await message.reply(get_str("mk_clear_start", _), parse_mode="HTML")

    player_refunds, vip_deals = [], []
    shop_mod = GLOBAL_MODIFIERS.get('shop', 1.0)

    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            player_lots = await db.fetch("SELECT * FROM market WHERE seller_id != 0")
            for lot in player_lots:
                seller_id, gpu_id, qty, cond = lot['seller_id'], lot['gpu_id'], lot['qty'], lot['condition']
                deposit = lot['deposit'] if lot['deposit'] is not None else 0
                await db.execute("INSERT INTO gpu_batches (user_id, gpu_id, multiplier, qty, condition, was_repaired) VALUES ($1, $2, 1.0, $3, $4, 0)", 
                                 seller_id, gpu_id, qty, cond)
                player_refunds.append((seller_id, gpu_id, qty, deposit))

            await db.execute("DELETE FROM market")
            new_lots_count = random.randint(5, 12)
            gpu_ids = [k for k, v in GPUS.items() if k < 100 and v['price'] <= 100_000_000]
            
            for _count in range(new_lots_count):
                gpu_num = random.choice(gpu_ids)
                gpu_id_str = f"gpu_{gpu_num}"
                gpu_info = GPUS[gpu_num]
                
                qty = random.randint(1, 3)
                random_price_mod = random.uniform(0.85, 1.15)
                price = int(int(gpu_info['price'] * qty * shop_mod) * random_price_mod)
                if price < 1000: price = 1000
                
                await db.execute("INSERT INTO market (seller_id, gpu_id, price, qty, condition, created_at, deposit) VALUES ($1, $2, $3, $4, $5, $6, $7)", 
                                 0, gpu_id_str, price, qty, 100.0, int(time.time()), 0)
                if random_price_mod < 0.9:
                    vip_deals.append(get_str("mk_clear_vip_row", _, qty=qty, name=gpu_info['name'], price=fmt(price)))

    for seller_id, gpu_id, qty, deposit in player_refunds:
        if deposit > 0: await add_balance(seller_id, deposit)
        farm_data = await get_farm(seller_id)
        await update_farm(seller_id, **{gpu_id: farm_data.get(gpu_id, 0) + qty})

    await message.answer(get_str("mk_clear_success", _), parse_mode="HTML")

    if vip_deals:
        from handlers.users.statuses import get_vip_market_subscribers
        async def notify():
            vips = await get_vip_market_subscribers()
            for vid in vips:
                if vid == message.from_user.id: continue
                async with pool.acquire() as db_loc:
                    v_lang = await db_loc.fetchval("SELECT lang FROM users WHERE user_id = $1", vid) or "ru"
                _v = get_translator(v_lang)
                text_vip = get_str("mk_clear_vip_title", _v) + "\n".join(vip_deals)
                try: await message.bot.send_message(vid, text_vip, parse_mode="HTML")
                except: pass
        asyncio.create_task(notify())


# ==========================================
# 📊 ПОКЕДЕКС ВИДЕОКАРТ (ИСПРАВЛЕН СИНТАКСИС)
# ==========================================
@router.message(F.text.lower().startswith(("видеокарта ", "видюха ", "gpu ", "вд ")))
async def cmd_gpu_info(message: types.Message, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2: return await message.reply(get_str("mk_info_err_args", translator=_), parse_mode="HTML")
        
    search_term = parts[1].strip()
    gpu_num, target_gpu = find_gpu(search_term)
    if not target_gpu: return await message.reply(get_str("mk_info_err_not_found", translator=_, name=search_term))

    gpu_id_str = f"gpu_{gpu_num}"
    pool = await get_db()
    async with pool.acquire() as db:
        market_stats = await db.fetchrow("SELECT COUNT(*) as c, SUM(qty) as s, MIN(price) as m FROM market WHERE gpu_id = $1", gpu_id_str)
        lots_count = market_stats['c'] if market_stats and market_stats['c'] else 0
        total_on_market = market_stats['s'] if market_stats and market_stats['s'] else 0
        min_price = market_stats['m'] if market_stats and market_stats['m'] else 0
        global_count = await db.fetchval("SELECT SUM(qty) FROM gpu_batches WHERE gpu_id = $1", gpu_id_str) or 0

    shop_mod = GLOBAL_MODIFIERS.get('shop', 1.0)
    price = int(target_gpu['price'] * shop_mod)
    
    current_course, *unused_crypto = await get_market_state()
    income_in_u = target_gpu.get('income', 0) * current_course
    roi_hours = int(price / income_in_u) if income_in_u > 0 else 0

    def_str = get_str("mk_info_def_row", translator=_, mod=shop_mod) if shop_mod != 1.0 else "\n"
    market_str = get_str("mk_info_market_active", translator=_, count=lots_count, total=total_on_market, price=fmt(min_price)) if lots_count > 0 else get_str("mk_info_market_empty", translator=_)

    # 🔥 ЖЕЛЕЗНЫЙ ФИКС: Обходим зарезервированное слово "global" через распаковку словаря
    text = get_str(
        "mk_info_body", 
        translator=_, 
        emoji=target_gpu['emoji'], 
        name=target_gpu['name'], 
        id=gpu_num, 
        price=fmt(price), 
        def_str=def_str, 
        income=fmt(target_gpu.get('income', 0)), 
        roi=fmt(roi_hours), 
        course=current_course, 
        market_str=market_str, 
        **{"global": fmt(global_count)}
    )
    await message.reply(text, parse_mode="HTML")


# ==========================================
# 🗃 МОИ ЛОТЫ И УПРАВЛЕНИЕ ИМИ
# ==========================================
async def get_my_market_page(user_id: int, page: int):
    pool = await get_db()
    async with pool.acquire() as db:
        total_lots = await db.fetchval("SELECT COUNT(*) FROM market WHERE seller_id = $1", user_id) or 0
        total_pages = max(1, (total_lots + 4) // 5) 
        page = max(1, min(page, total_pages))
        offset = (page - 1) * 5
        lots = await db.fetch("SELECT * FROM market WHERE seller_id = $1 ORDER BY id ASC LIMIT 5 OFFSET $2", user_id, offset)
    return lots, page, total_pages, total_lots


async def send_my_lots_message(message_or_call, user_id, page=1, is_edit=False, _=None):
    lots, current_page, total_pages, total_lots = await get_my_market_page(user_id, page)

    if not lots:
        text = get_str("mk_my_empty", _)
        if is_edit:
            try: await message_or_call.message.edit_text(text)
            except: pass
        else: await message_or_call.reply(text)
        return

    text = get_str("mk_my_title", _, total=total_lots, current=current_page, pages=total_pages)
    builder = InlineKeyboardBuilder()

    for lot in lots:
        gpu_num = int(lot['gpu_id'].split('_')[1])
        gpu = GPUS.get(gpu_num)
        if not gpu: continue

        text += get_str("mk_my_row", _, id=lot['id'], emoji=gpu['emoji'], name=gpu['name'], qty=lot['qty'], cond=lot['condition'], price=fmt(lot['price']))
        builder.row(
            InlineKeyboardButton(text=get_str("mk_btn_inc", _, id=lot['id']), callback_data=f"mylot_inc_{lot['id']}"),
            InlineKeyboardButton(text=get_str("mk_btn_dec", _, id=lot['id']), callback_data=f"mylot_dec_{lot['id']}"),
            InlineKeyboardButton(text=get_str("mk_btn_rem", _, id=lot['id']), callback_data=f"mylot_rem_{lot['id']}")
        )

    nav_buttons = []
    if current_page > 1: nav_buttons.append(InlineKeyboardButton(text=get_str("mk_btn_back", _), callback_data=f"mylots_page_{current_page - 1}_{user_id}"))
    if current_page < total_pages: nav_buttons.append(InlineKeyboardButton(text=get_str("mk_btn_forward", _), callback_data=f"mylots_page_{current_page + 1}_{user_id}"))
    if nav_buttons: builder.row(*nav_buttons)

    if is_edit:
        try: await message_or_call.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
        except: pass
    else:
        await message_or_call.reply(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.message(F.text.lower().in_(["мои лоты", "my lots"]))
async def cmd_my_lots(message: types.Message, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    await send_my_lots_message(message, message.from_user.id, page=1, is_edit=False, _=_)


@router.callback_query(F.data.startswith("mylots_page_"))
async def callback_mylots_page(call: types.CallbackQuery, _=None):
    if not _: _ = await resolve_chat_translator(call.message.chat.id, _)
    parts = call.data.split('_')
    page, owner_id = int(parts[2]), int(parts[3])
    if call.from_user.id != owner_id: return await call.answer(get_str("mk_my_alert_foreign", _), show_alert=True)
    await send_my_lots_message(call, owner_id, page, is_edit=True, _=_)
    try: await call.answer()
    except: pass


@router.callback_query(F.data.startswith("mylot_rem_"))
async def callback_mylot_remove(call: types.CallbackQuery, _=None):
    if not _: _ = await resolve_chat_translator(call.message.chat.id, _)
    lot_id, user_id = int(call.data.split('_')[2]), call.from_user.id
    
    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            lot = await db.fetchrow("SELECT * FROM market WHERE id = $1 AND seller_id = $2 FOR UPDATE", lot_id, user_id)
            if not lot: return await call.answer(get_str("mk_buy_err_not_found", _), show_alert=True)

            deposit = lot['deposit']
            await db.execute("DELETE FROM market WHERE id = $1", lot_id)
            await db.execute("INSERT INTO gpu_batches (user_id, gpu_id, multiplier, qty, condition, was_repaired) VALUES ($1, $2, 1.0, $3, $4, 0)",
                             user_id, lot['gpu_id'], lot['qty'], lot['condition'])

    farm_data = await get_farm(user_id)
    await update_farm(user_id, **{lot['gpu_id']: farm_data.get(lot['gpu_id'], 0) + lot['qty']})

    burn_str = get_str("mk_remove_burn_text", _, deposit=fmt(deposit)) if deposit > 0 else ""
    await call.answer(get_str("mk_remove_success", _ , burn_text=""), show_alert=False)
    await call.message.answer(get_str("mk_remove_success", _, burn_text=burn_str), parse_mode="HTML")
    await send_my_lots_message(call, user_id, page=1, is_edit=True, _=_)


@router.callback_query(F.data.startswith("mylot_inc_") | F.data.startswith("mylot_dec_"))
async def callback_mylot_edit_price(call: types.CallbackQuery, state: FSMContext, _=None):
    if not _: _ = await resolve_chat_translator(call.message.chat.id, _)
    action = "inc" if "inc" in call.data else "dec"
    lot_id, user_id = int(call.data.split('_')[2]), call.from_user.id

    pool = await get_db()
    async with pool.acquire() as db: lot = await db.fetchrow("SELECT * FROM market WHERE id = $1 AND seller_id = $2", lot_id, user_id)
    if not lot: return await call.answer(get_str("mk_buy_err_not_found", _), show_alert=True)

    await state.update_data(lot_id=lot_id, action=action, current_price=lot['price'], deposit=lot.get('deposit', 0))
    await state.set_state(MarketEdit.waiting_for_price_change)

    word = get_str("mk_edit_word_inc", _) if action == "inc" else get_str("mk_edit_word_dec", _)
    text_prompt = get_str("mk_edit_prompt", _, word=word, id=lot_id, price=fmt(lot['price']), word_lower=word.lower())
    await call.message.answer(text_prompt, parse_mode="HTML")
    await call.answer()


@router.message(MarketEdit.waiting_for_price_change)
async def process_market_price_change(message: types.Message, state: FSMContext, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    if message.text.lower().strip() in ["отмена", "cancel"]:
        await state.clear()
        return await message.reply(get_str("mk_sell_cancelled", _))

    amount_str = message.text.lower().replace('к', '000').replace('k', '000').replace('м', '000000').replace('m', '000000').replace(' ', '')
    if not amount_str.isdigit(): return await message.reply(get_str("mk_sell_price_err_nan", _))

    amount = int(amount_str)
    if amount <= 0: return await message.reply(get_str("mk_sell_qty_err_zero", _))

    data = await state.get_data()
    lot_id, action, current_price, old_deposit = data['lot_id'], data['action'], data['current_price'], data['deposit']
    user_id = message.from_user.id

    new_price = current_price + amount if action == "inc" else current_price - amount
    if new_price < 1000: return await message.reply(get_str("mk_edit_err_low", _))

    new_deposit = int(new_price * 0.05)
    deposit_diff = new_deposit - old_deposit

    if deposit_diff > 0:
        if await get_balance(user_id) < deposit_diff:
            return await message.reply(get_str("mk_edit_err_deposit", _, price=fmt(deposit_diff)))
        await add_balance(user_id, -deposit_diff)
    elif deposit_diff < 0:
        await add_balance(user_id, abs(deposit_diff))

    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute("UPDATE market SET price = $1, deposit = $2 WHERE id = $3 AND seller_id = $4", 
                         new_price, new_deposit, lot_id, user_id)

    await state.clear()
    word = get_str("mk_edit_word_success_inc", _) if action == "inc" else get_str("mk_edit_word_success_dec", _)
    dep_msg = get_str("mk_edit_dep_msg_inc", _, price=fmt(deposit_diff)) if deposit_diff > 0 else (get_str("mk_edit_dep_msg_dec", _, price=fmt(abs(deposit_diff))) if deposit_diff < 0 else "")

    await message.reply(get_str("mk_edit_success", _, id=lot_id, word=word, price=fmt(new_price), dep_msg=dep_msg), parse_mode="HTML")
    await send_my_lots_message(message, user_id, page=1, is_edit=False, _=_)


# ==========================================
# 📊 ГЛОБАЛЬНАЯ АНАЛИТИКА РЫНКА
# ==========================================
@router.message(F.text.lower().in_(["инфо рынок", "рынок инфо", "market info", "market analytics"]))
async def cmd_market_global_info(message: types.Message, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    pool = await get_db()
    async with pool.acquire() as db:
        res = await db.fetchrow("SELECT COUNT(*) as c, SUM(qty) as sq, SUM(price) as sp FROM market")
        total_lots = res['c'] or 0
        total_cards = res['sq'] or 0
        total_value = res['sp'] or 0
        
        state_lots = await db.fetchval("SELECT COUNT(*) FROM market WHERE seller_id = 0") or 0
        player_lots = total_lots - state_lots
        
        min_lot = await db.fetchrow("SELECT gpu_id, price FROM market ORDER BY price ASC LIMIT 1")
        max_lot = await db.fetchrow("SELECT gpu_id, price FROM market ORDER BY price DESC LIMIT 1")

    if total_lots == 0: return await message.reply(get_str("mk_analytics_empty", _))

    def get_gpu_name(gpu_id_str):
        try: return f"{GPUS[int(gpu_id_str.split('_')[1])]['emoji']} {GPUS[int(gpu_id_str.split('_')[1])]['name']}"
        except: return "Unknown Engine Unit"

    min_text = f"{get_gpu_name(min_lot['gpu_id'])} (<b>{fmt(min_lot['price'])} ᴜ</b>)" if min_lot else "---"
    max_text = f"{get_gpu_name(max_lot['gpu_id'])} (<b>{fmt(max_lot['price'])} ᴜ</b>)" if max_lot else "---"

    text = get_str("mk_analytics_body", _, total_lots=total_lots, total_cards=total_cards, total_value=fmt(total_value), state_lots=state_lots, player_lots=player_lots, max_text=max_text, min_text=min_text, avg=fmt(total_value/total_cards if total_cards > 0 else 0))
    await message.reply(text, parse_mode="HTML")