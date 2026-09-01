# File: handlers/syndicate/inventory.py
import time
import random
import json
import logging
import os
import html
from aiogram import Router, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.database import get_db, get_farm, update_farm, get_balance, add_balance
from handlers.users.quests import process_quest_action
from handlers.users.statuses import has_active_status

from .config import GPUS, fmt
from .engine import sync_farm_passive, is_standard_gpu
from .menu import safe_edit_text, farm_action_locks

router = Router()
shop_cooldowns = {}

# ==========================================
# 🛡 ФЕЙЛСЕЙФ СИСТЕМА: РЕЗЕРВНАЯ LОКАЛИЗАЦИЯ
# ==========================================
LOCALES = {}
for lang in ["ru", "en"]:
    path = f"locales/{lang}.json"
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                LOCALES[lang] = json.load(f)
        except Exception as e:
            logging.error(f"Ошибка загрузки локали {lang} в инвентаре: {e}")

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
# 🎒 ТЕКСТОВЫЕ ТРИГГЕРЫ ВХОДА
# ==========================================
@router.message(F.text.lower().in_(["мои видюхи", "мои видеокарты", "инвентарь", "мои карты", "мои вд", "my gpus", "my cards", "inventory"]))
async def cmd_my_gpus(message: types.Message, _ = None):
    _ = await resolve_chat_translator(message.chat.id, _)
    await send_inventory_menu(message.from_user.id, message, is_edit=False, _=_)


@router.callback_query(F.data.startswith("farm_my_gpus_"))
async def callback_my_gpus(callback: types.CallbackQuery, _ = None):
    owner_id = int(callback.data.split("_")[-1])
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    
    if callback.from_user.id != owner_id: 
        return await callback.answer(_("inv_hands_off"), show_alert=True)
    await send_inventory_menu(owner_id, callback.message, is_edit=True, _=_)
    await callback.answer()


# ==========================================
# 📦 ГЕНЕРАТОР ИНВЕНТАРЯ
# ==========================================
async def send_inventory_menu(user_id, message_obj, is_edit=False, _ = None):
    if not _: _ = await resolve_chat_translator(message_obj.chat.id, _)
        
    farm_data = await get_farm(user_id) 
    await sync_farm_passive(user_id, farm_data)
    farm_data = await get_farm(user_id) 

    try: user_name = (await message_obj.bot.get_chat(user_id)).first_name
    except: user_name = _("inv_agent_fallback", user_id=user_id)
    user_mention = f"<a href='tg://user?id={user_id}'>{html.escape(user_name)}</a>"

    pool = await get_db()
    async with pool.acquire() as db:
        all_batches = await db.fetch("SELECT id, gpu_id, multiplier, qty, condition, was_repaired FROM gpu_batches WHERE user_id = $1 AND gpu_id LIKE 'gpu_%'", user_id)

    repairable_count, dead_count, total_gpus_owned = 0, 0, 0
    gpu_batches_map = {}
    
    for b in all_batches:
        g_id = b['gpu_id']
        if g_id not in gpu_batches_map: gpu_batches_map[g_id] = []
        gpu_batches_map[g_id].append(b)
        
        total_gpus_owned += b['qty']
        if b['condition'] <= 0:
            if b['was_repaired'] == 1: dead_count += b['qty']
            else: repairable_count += b['qty']

    await process_quest_action(user_id, "farm_total_gpus", total_gpus_owned, is_absolute=True)

    inventory_lines = []
    builder = InlineKeyboardBuilder()
    has_working_cards = False
    sorted_gpus = sorted(GPUS.items(), key=lambda x: x[1]['price'], reverse=True)

    for i, gpu in sorted_gpus:
        gpu_id_str = f'gpu_{i}'
        batches = gpu_batches_map.get(gpu_id_str, [])
        
        if batches:
            has_working_cards = True
            inventory_lines.append(f"<b>{gpu['emoji']} {gpu['name']}</b>")
            
            saved_qty = broken_qty = 0
            grouped_working = {}
            
            for b in batches:
                hp, repaired_flag, qty, mult = b['condition'], b['was_repaired'], b['qty'], b['multiplier'] or 1.0
                if hp > 0:
                    if repaired_flag == -1 and hp <= 1.0: saved_qty += qty
                    else:
                        key = (round(hp, 1), mult)
                        grouped_working[key] = grouped_working.get(key, 0) + qty
                else:
                    if repaired_flag == 1: pass
                    else: broken_qty += qty
                        
            for (cond_rounded, mult), b_qty in sorted(grouped_working.items(), key=lambda x: x[0], reverse=True):
                if mult >= 1.5: mult_str = _("inv_mult_elite", mult=mult)
                elif mult > 1.0: mult_str = _("inv_mult_overclock", mult=mult)
                elif mult < 1.0: mult_str = _("inv_mult_defect", mult=mult)
                else: mult_str = ""
                    
                hp_emoji = "💚" if cond_rounded >= 80 else ("💛" if cond_rounded >= 40 else "💔")
                inventory_lines.append(f" ├ {b_qty} шт. — {hp_emoji} <b>{cond_rounded:.1f}%</b>{mult_str}")
                
            if saved_qty > 0: inventory_lines.append(f" ├ {saved_qty} шт. — " + _("inv_status_saved"))
            if broken_qty > 0: inventory_lines.append(f" ├ {broken_qty} шт. — " + _("inv_status_broken"))
            if gpu_id_str in gpu_batches_map:
                local_dead = sum(b['qty'] for b in gpu_batches_map[gpu_id_str] if b['condition'] <= 0 and b['was_repaired'] == 1)
                if local_dead > 0: inventory_lines.append(f" ├ {local_dead} шт. — " + _("inv_status_scrap"))
                
            inventory_lines.append(_("inv_pawnshop_text", price=fmt(int(gpu['price']*0.25))))

    max_slots = farm_data.get('max_slots', 30)
    slot_status = _("inv_slot_status", owned=total_gpus_owned, max_slots=max_slots)

    text = _("inv_title", name=user_mention, slot_status=slot_status) + "\n"
    text += "\n".join(inventory_lines) if has_working_cards else _("inv_empty")
    
    if repairable_count > 0: text += _("inv_need_repair", count=repairable_count)
    if dead_count > 0: text += _("inv_burnt_forever", count=dead_count)
            
    if has_working_cards:
        builder.row(types.InlineKeyboardButton(text=_("inv_btn_sell"), callback_data=f"fsell_list_{user_id}"),
                    types.InlineKeyboardButton(text=_("inv_btn_overclock"), callback_data=f"farm_overclock_{user_id}"))
    if repairable_count > 0: 
        builder.row(types.InlineKeyboardButton(text=_("inv_btn_repair_hub", count=repairable_count), callback_data=f"frepair_list_{user_id}"))
    if dead_count > 0: 
        builder.row(types.InlineKeyboardButton(text=_("inv_btn_scrap", count=dead_count), callback_data=f"farm_scrap_{user_id}"))
    builder.row(types.InlineKeyboardButton(text=_("inv_btn_back_farm"), callback_data=f"farm_main_{user_id}"))
    
    if is_edit: await safe_edit_text(message_obj, text, builder.as_markup())
    else: await message_obj.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


# ==========================================
# 📉 ВЫВОД КАТАЛОГА ПРОДАЖ КАРТ С ВЕРСТАКА
# ==========================================
@router.callback_query(F.data.startswith("fsell_list_"))
async def inventory_sell_list(callback: types.CallbackQuery, _ = None):
    owner_id = int(callback.data.split("_")[-1])
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    if callback.from_user.id != owner_id: return await callback.answer(_("inv_hands_off"), show_alert=True)

    user_id = callback.from_user.id
    farm_data = await get_farm(user_id)
    builder = InlineKeyboardBuilder()
    has_cards = False
    
    for gpu_id, gpu_info in GPUS.items():
        owned = farm_data.get(f'gpu_{gpu_id}', 0)
        if owned > 0:
            has_cards = True
            builder.button(text=f"📉 {gpu_info['emoji']} {gpu_info['name']} ({owned} шт)", callback_data=f"farm_item_{gpu_id}_{user_id}")

    if not has_cards: return await callback.answer(_("inv_sell_empty_alert"), show_alert=True)

    builder.button(text=_("inv_btn_back"), callback_data=f"farm_my_gpus_{user_id}")
    builder.adjust(1) 
    await callback.message.edit_text(_("inv_sell_title"), reply_markup=builder.as_markup(), parse_mode="HTML")


# ==========================================
# 🗑 МЕХАНИКА УТИЛИЗАЦИИ ВТИЛЬ-ОГРЫЗКОВ
# ==========================================
@router.callback_query(F.data.startswith("farm_scrap_"))
async def scrap_dead_cards(callback: types.CallbackQuery, _ = None):
    owner_id = int(callback.data.split("_")[-1])
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    if callback.from_user.id != owner_id: return await callback.answer(_("inv_hands_off"), show_alert=True)
    user_id = callback.from_user.id
    
    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            dead_batches = await db.fetch("SELECT gpu_id, SUM(qty) as s_qty FROM gpu_batches WHERE user_id=$1 AND condition <= 0 AND was_repaired = 1 AND gpu_id LIKE 'gpu_%' GROUP BY gpu_id", user_id)
            if not dead_batches: return await callback.answer(_("inv_scrap_empty_alert"), show_alert=True)
            await db.execute("DELETE FROM gpu_batches WHERE user_id=$1 AND condition <= 0 AND was_repaired = 1 AND gpu_id LIKE 'gpu_%'", user_id)

    farm_data = await get_farm(user_id)
    updates = {}
    for row in dead_batches:
        gpu_id_str, qty = row['gpu_id'], row['s_qty']
        updates[gpu_id_str] = max(0, farm_data.get(gpu_id_str, 0) - qty)
        
    if updates: await update_farm(user_id, **updates)
    await callback.answer(_("inv_scrap_success_alert"), show_alert=True)
    await send_inventory_menu(user_id, callback.message, is_edit=True, _=_)


# ==========================================
# 🔧 РЕМОНТНЫЙ ЦЕХ (МЕНЮ)
# ==========================================
@router.callback_query(F.data.startswith("frepair_list_"))
async def frepair_list_menu(callback: types.CallbackQuery, _ = None):
    owner_id = int(callback.data.split("_")[-1])
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    if callback.from_user.id != owner_id: return await callback.answer(_("inv_hands_off"), show_alert=True)

    user_id = callback.from_user.id
    pool = await get_db()
    async with pool.acquire() as db:
        broken_batches = await db.fetch("SELECT gpu_id, SUM(qty) as total_broken FROM gpu_batches WHERE user_id = $1 AND condition <= 0 AND was_repaired = 0 AND gpu_id LIKE 'gpu_%' GROUP BY gpu_id", user_id)

    if not broken_batches: return await callback.answer(_("inv_repair_empty_alert"), show_alert=True)

    text = _("inv_repair_title")
    builder = InlineKeyboardBuilder()

    for batch in broken_batches:
        if not is_standard_gpu(batch['gpu_id']): continue
        gpu_num = int(batch['gpu_id'].split('_')[1])
        gpu_info = GPUS.get(gpu_num)
        broken_qty = batch['total_broken']
        repair_cost = int(gpu_info['price'] * 0.3 * broken_qty)
        
        text += _("inv_repair_row_cost", name=gpu_info['name'], qty=broken_qty, price=fmt(repair_cost))
        builder.button(text=_("inv_btn_repair_model", name=gpu_info['name']), callback_data=f"frepair_qty_{gpu_num}_{user_id}")

    builder.button(text=_("inv_btn_back"), callback_data=f"farm_my_gpus_{user_id}")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")


# ==========================================
# 🔧 СТЕНД ПОДБОРЩИКА ОБЪЕМА РЕМОНТА
# ==========================================
@router.callback_query(F.data.startswith("frepair_qty_"))
async def frepair_qty_menu(callback: types.CallbackQuery, _ = None):
    owner_id = int(callback.data.split("_")[-1])
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    if callback.from_user.id != owner_id: return await callback.answer(_("inv_hands_off"), show_alert=True)

    user_id = callback.from_user.id
    gpu_num = int(callback.data.split("_")[2])
    gpu_id_str = f"gpu_{gpu_num}"
    gpu_info = GPUS.get(gpu_num)

    pool = await get_db()
    async with pool.acquire() as db:
        broken_qty = await db.fetchval("SELECT SUM(qty) FROM gpu_batches WHERE user_id = $1 AND gpu_id = $2 AND condition <= 0 AND was_repaired = 0", user_id, gpu_id_str) or 0

    if broken_qty <= 0: return await callback.answer(_("inv_repair_not_found"), show_alert=True)

    repair_cost_per_card = int(gpu_info['price'] * 0.3)
    text = _("inv_repair_qty_title", name=gpu_info['name'], qty=broken_qty, price=fmt(repair_cost_per_card))

    builder = InlineKeyboardBuilder()
    options = [1, 5, 10, 50]
    for opt in options:
        if opt <= broken_qty: builder.button(text=f"{opt} шт.", callback_data=f"frepair_do_{gpu_num}_{opt}_{user_id}")
    if broken_qty not in options:
        builder.button(text=_("inv_btn_all_pool_short", qty=broken_qty), callback_data=f"frepair_do_{gpu_num}_{broken_qty}_{user_id}")

    builder.button(text=_("inv_btn_back"), callback_data=f"frepair_list_{user_id}")
    builder.adjust(3) 
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")


# ==========================================
# 🔧 ВЫПОЛНЕНИЕ РЕМОНТНЫХ ТРАНЗАКЦИЙ КАЗНЫ
# ==========================================
@router.callback_query(F.data.startswith("frepair_do_"))
async def frepair_execute(callback: types.CallbackQuery, _ = None):
    owner_id = int(callback.data.split("_")[-1])
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    if callback.from_user.id != owner_id: return await callback.answer(_("inv_hands_off"), show_alert=True)

    user_id = callback.from_user.id
    now = time.time()
    if user_id in shop_cooldowns and (now - shop_cooldowns[user_id] < 1.5): return await callback.answer(_("inv_repair_cooldown"), show_alert=True)
    shop_cooldowns[user_id] = now

    parts = callback.data.split("_")
    gpu_num, qty_to_repair = int(parts[2]), int(parts[3]) 

    farm_data = await get_farm(user_id)
    await sync_farm_passive(user_id, farm_data)

    gpu_id_str = f"gpu_{gpu_num}"
    gpu_info = GPUS.get(gpu_num)
    repair_cost = int(gpu_info['price'] * 0.3 * qty_to_repair)

    if await get_balance(user_id) < repair_cost: return await callback.answer(_("inv_repair_no_money", price=fmt(repair_cost)), show_alert=True)

    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            broken_qty = await db.fetchval("SELECT SUM(qty) FROM gpu_batches WHERE user_id = $1 AND gpu_id = $2 AND condition <= 0 AND was_repaired = 0", user_id, gpu_id_str) or 0
            if broken_qty < qty_to_repair: return await callback.answer(_("inv_repair_qty_error"), show_alert=True)
                
            await add_balance(user_id, -repair_cost)
            rows = await db.fetch("SELECT id, qty, multiplier FROM gpu_batches WHERE user_id = $1 AND gpu_id = $2 AND condition <= 0 AND was_repaired = 0 ORDER BY id", user_id, gpu_id_str)
            
            remaining = qty_to_repair
            for r in rows:
                if remaining <= 0: break
                b_id, b_qty, mult = r['id'], r['qty'], r['multiplier']
                take = min(b_qty, remaining)
                
                if take == b_qty:
                    await db.execute("UPDATE gpu_batches SET condition = 100.0, was_repaired = 1 WHERE id = $1", b_id)
                else:
                    await db.execute("UPDATE gpu_batches SET qty = qty - $1 WHERE id = $2", take, b_id)
                    exist_rep = await db.fetchval("SELECT id FROM gpu_batches WHERE user_id = $1 AND gpu_id = $2 AND multiplier = $3 AND condition = 100.0 AND was_repaired = 1", user_id, gpu_id_str, mult)
                    if exist_rep: await db.execute("UPDATE gpu_batches SET qty = qty + $1 WHERE id = $2", take, exist_rep)
                    else: await db.execute("INSERT INTO gpu_batches (user_id, gpu_id, multiplier, qty, condition, was_repaired) VALUES ($1, $2, $3, $4, 100.0, 1)", user_id, gpu_id_str, mult, take)
                remaining -= take

    await process_quest_action(user_id, "farm_repair", qty_to_repair)
    await callback.answer(_("inv_repair_success_alert", qty=qty_to_repair), show_alert=True)
    await send_inventory_menu(user_id, callback.message, is_edit=True, _=_)