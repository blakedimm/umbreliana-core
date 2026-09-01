import time
import random
import asyncio
import json
import logging
import os
from aiogram import Router, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramRetryAfter

from core.database import get_farm, get_balance, add_balance, get_gpu_batches, move_gpu_batch
from handlers.users.quests import process_quest_action
from handlers.events.events_engine import GLOBAL_MODIFIERS

from .config import GPUS, fmt
from .menu import safe_edit_text, shop_cooldowns

router = Router()

# 🔥 ЖЕЛЕЗНЫЙ ФИКС: Локальное определение проверки видеокарт
def is_standard_gpu(gpu_id: str) -> bool:
    return gpu_id.startswith('gpu_') and gpu_id.split('_')[-1].isdigit()

# ==========================================
# 🛡 ДВИЖОК ЛОКАЛИЗАЦИИ ИЗ СЕССИИ И ПАМЯТИ
# ==========================================
LOCALES = {}
for lang in ["ru", "en"]:
    path = f"locales/{lang}.json"
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                LOCALES[lang] = json.load(f)
        except Exception as e:
            logging.error(f"Ошибка загрузки локали {lang} в разгоне: {e}")

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


@router.callback_query(F.data.startswith("farm_overclock_"))
async def btn_overclock_menu(callback: types.CallbackQuery, _ = None):
    owner_id = int(callback.data.split("_")[-1])
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    
    if callback.from_user.id != owner_id: 
        return await callback.answer(_("oc_err_not_owner"), show_alert=True)
    await overclock_menu(callback.message, is_edit=True, user_id=callback.from_user.id, _=_)
    await callback.answer()


@router.message(F.text.lower() == "разгон")
async def overclock_menu(message: types.Message, is_edit=False, user_id=None, _ = None):
    if _ is None:
        _ = await resolve_chat_translator(message.chat.id, _)
        
    if user_id is None: 
        user_id = message.from_user.id
        
    farm_data = await get_farm(user_id)
    owned_gpus = {int(k.split('_')[1]): v for k, v in farm_data.items() if is_standard_gpu(k) and v > 0}
    
    if not owned_gpus:
        msg = _("oc_empty_terminal")
        try:
            if is_edit: 
                return await message.edit_text(msg, reply_markup=InlineKeyboardBuilder().button(text=_("oc_btn_back"), callback_data=f"farm_main_{user_id}").as_markup(), parse_mode="HTML")
            return await message.reply(msg, parse_mode="HTML")
        except: 
            return
        
    text = _("oc_menu_main")
    builder = InlineKeyboardBuilder()
    
    for gpu_id, count in owned_gpus.items():
        gpu_info = GPUS.get(gpu_id)
        if gpu_info:
            builder.button(text=f"{gpu_info['emoji']} {gpu_info['name']} ({count} шт)", callback_data=f"oc_model_{gpu_id}_{user_id}")
            
    builder.button(text=_("oc_btn_back_farm"), callback_data=f"farm_main_{user_id}")
    builder.adjust(1)
    
    try:
        if is_edit: 
            await safe_edit_text(message, text, builder.as_markup())
        else: 
            await message.reply(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    except: 
        pass


@router.callback_query(F.data.startswith("oc_model_"))
async def oc_batch_menu(callback: types.CallbackQuery, _ = None):
    owner_id = int(callback.data.split("_")[-1])
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    
    if callback.from_user.id != owner_id: 
        return await callback.answer(_("oc_err_not_owner"), show_alert=True)

    user_id = callback.from_user.id
    gpu_id_int = int(callback.data.split("_")[2])
    gpu_id = f"gpu_{gpu_id_int}"
    gpu_info = GPUS.get(gpu_id_int)
    
    total_count = (await get_farm(user_id)).get(gpu_id, 0)
    if total_count <= 0: 
        return await callback.answer("❌ Error!", show_alert=True)
        
    batches = await get_gpu_batches(user_id, gpu_id, total_count)
    
    text = _("oc_menu_batch", name=gpu_info['name'])
    builder = InlineKeyboardBuilder()
    
    for batch in batches:
        mult, qty, cond = batch['mult'], batch['qty'], round(batch['cond'], 1)
        status = _("oc_status_elite") if mult >= 1.5 else (_("oc_status_top") if mult > 1.0 else (_("oc_status_defect") if mult < 1.0 else _("oc_status_stock")))
        builder.button(text=f"{status} [x{mult}] — {qty} шт. (❤️ {cond}%)", callback_data=f"oc_qty_{gpu_id_int}_{mult}_{cond}_{user_id}")
        
    builder.button(text=_("oc_btn_back"), callback_data=f"oc_back_main_{user_id}")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("oc_back_main_"))
async def oc_back_main_menu(callback: types.CallbackQuery):
    owner_id = int(callback.data.split("_")[-1])
    _ = await resolve_chat_translator(callback.message.chat.id)
    if callback.from_user.id != owner_id: 
        return await callback.answer(_("oc_err_not_owner"), show_alert=True)
    await overclock_menu(callback.message, is_edit=True, user_id=owner_id, _=_)
    await callback.answer()


@router.callback_query(F.data.startswith("oc_qty_"))
async def oc_qty_menu(callback: types.CallbackQuery, _ = None):
    owner_id = int(callback.data.split("_")[-1])
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    
    if callback.from_user.id != owner_id: 
        return await callback.answer(_("oc_err_not_owner"), show_alert=True)

    user_id = callback.from_user.id
    parts = callback.data.split("_")
    gpu_id_int, mult, cond = int(parts[2]), float(parts[3]), float(parts[4])
    gpu_id = f"gpu_{gpu_id_int}"
    
    total_count = (await get_farm(user_id)).get(gpu_id, 0) 
    batches = await get_gpu_batches(user_id, gpu_id, total_count)
    available_qty = next((b['qty'] for b in batches if b['mult'] == mult and abs(b['cond'] - cond) < 0.2), 0)
    
    if available_qty <= 0: 
        return await callback.answer("❌ Token Expired", show_alert=True)

    text = _("oc_menu_qty", mult=mult, cond=cond, qty=available_qty)
    builder = InlineKeyboardBuilder()
    options = [1, 5, 10, 30, 50, 100]
    for opt in options:
        if opt <= available_qty: 
            builder.button(text=f"{opt} шт.", callback_data=f"oc_type_{gpu_id_int}_{mult}_{cond}_{opt}_{user_id}")
    if available_qty not in options:
        builder.button(text=_("oc_btn_all_pool", qty=available_qty), callback_data=f"oc_type_{gpu_id_int}_{mult}_{cond}_{available_qty}_{user_id}")

    builder.button(text=_("oc_btn_back"), callback_data=f"oc_model_{gpu_id_int}_{user_id}")
    builder.adjust(3) 
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("oc_type_"))
async def oc_type_menu(callback: types.CallbackQuery, _ = None):
    owner_id = int(callback.data.split("_")[-1])
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    
    if callback.from_user.id != owner_id: 
        return await callback.answer(_("oc_err_not_owner"), show_alert=True)

    user_id = callback.from_user.id
    parts = callback.data.split("_")
    gpu_id_int, mult, cond, qty = int(parts[2]), float(parts[3]), float(parts[4]), int(parts[5])
    gpu_info = GPUS.get(gpu_id_int)

    mod_cost = max(15000, int(gpu_info['price'] * 0.02))
    ext_cost = max(35000, int(gpu_info['price'] * 0.06))
    degradation = max(0, (mult - 1.0) * 0.5) 
    mod_chance = max(0.10, 0.80 - degradation)
    ext_chance = max(0.05, 0.40 - degradation)

    text = _("oc_menu_type", 
             name=gpu_info['name'], qty=qty, mult=mult, cond=cond,
             mod_cost=fmt(mod_cost), mod_chance=int(mod_chance * 100),
             ext_cost=fmt(ext_cost), ext_chance=int(ext_chance * 100))

    builder = InlineKeyboardBuilder()
    builder.button(text=_("oc_btn_mod"), callback_data=f"oc_run_{gpu_id_int}_{mult}_{cond}_{qty}_mod_{user_id}")
    builder.button(text=_("oc_btn_ext"), callback_data=f"oc_run_{gpu_id_int}_{mult}_{cond}_{qty}_ext_{user_id}")
    builder.button(text=_("oc_btn_cancel"), callback_data=f"oc_qty_{gpu_id_int}_{mult}_{cond}_{user_id}")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("oc_run_"))
async def process_overclock_run(callback: types.CallbackQuery, _ = None):
    owner_id = int(callback.data.split("_")[-1])
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    
    if callback.from_user.id != owner_id: 
        return await callback.answer(_("oc_err_not_owner"), show_alert=True)

    user_id = callback.from_user.id
    now = time.time()
    if user_id in shop_cooldowns and (now - shop_cooldowns[user_id] < 5.0): 
        return await callback.answer(_("oc_err_cooldown"), show_alert=True)
    shop_cooldowns[user_id] = now

    await callback.answer() 
    try: await callback.message.edit_reply_markup(reply_markup=None)
    except: pass

    parts = callback.data.split("_")
    gpu_id_int, mult, cond, qty, mode = int(parts[2]), float(parts[3]), float(parts[4]), int(parts[5]), parts[6]
    
    gpu_id = f"gpu_{gpu_id_int}"
    gpu_info = GPUS.get(gpu_id_int)
    farm_data = await get_farm(user_id)
    total_count = farm_data.get(gpu_id, 0)
    batches = await get_gpu_batches(user_id, gpu_id, total_count)
    
    target_batch = next((b for b in batches if b['mult'] == mult and abs(b['cond'] - cond) < 0.2), None)
    if not target_batch: 
        return await callback.message.answer(_("oc_err_struct"))
        
    source_cond = target_batch['cond'] 
    degradation = max(0, (mult - 1.0) * 0.5)

    if mode == "mod":
        cost_per_card = max(15000, int(gpu_info['price'] * 0.02))
        chance = max(0.10, 0.80 - degradation)
        reward, penalty = 0.1, 0.1
    else:
        cost_per_card = max(35000, int(gpu_info['price'] * 0.06))
        chance = max(0.05, 0.40 - degradation)
        reward, penalty = 0.3, 0.4

    total_cost = int(cost_per_card * qty * GLOBAL_MODIFIERS.get("oc_cost", 1.0))
    if await get_balance(user_id) < total_cost: 
        return await callback.message.answer(_("oc_err_balance", cost=fmt(total_cost)))
        
    await add_balance(user_id, -total_cost)
    
    is_success = random.random() < (chance + GLOBAL_MODIFIERS.get("oc_chance", 0.0))
    await process_quest_action(user_id, "farm_overclock", qty)
    
    if is_success:
        await process_quest_action(user_id, "farm_overclock_success", qty)
        new_mult = min(3.0, round(mult + reward, 2))
        await move_gpu_batch(user_id, gpu_id, mult, new_mult, qty, source_cond)
        
        if new_mult >= 1.5:
            final_text = _("oc_res_elite", mult=mult, new_mult=new_mult)
        else:
            final_text = _("oc_res_success", mult=mult, new_mult=new_mult)
    else:
        if random.random() < 0.20:
            await move_gpu_batch(user_id, gpu_id, mult, mult, qty, 0.0)
            final_text = _("oc_res_critical")
        else:
            new_mult = round(max(0.5, mult - penalty), 2)
            await move_gpu_batch(user_id, gpu_id, mult, new_mult, qty, source_cond)
            final_text = _("oc_res_fail", mult=mult, new_mult=new_mult)

    stages = [(40, _("oc_anim_stage_1")), (85, _("oc_anim_stage_2"))]
    anim_msg = callback.message
    
    try: await anim_msg.edit_text(_("oc_anim_start", name=gpu_info['name']), parse_mode="HTML")
    except: pass
        
    flood_hit = False
    for percent, stage_text in stages:
        if flood_hit: break 
        await asyncio.sleep(2.0) 
        try: await anim_msg.edit_text(_("oc_anim_loop", name=gpu_info['name'], text=stage_text, percent=percent), parse_mode="HTML")
        except TelegramRetryAfter as e:
            flood_hit = True
            await asyncio.sleep(e.retry_after) 
        except: pass 
            
    if not flood_hit: await asyncio.sleep(1.5) 
        
    builder = InlineKeyboardBuilder()
    builder.button(text=_("oc_btn_return_stand"), callback_data=f"oc_model_{gpu_id_int}_{user_id}")
    
    try: await anim_msg.edit_text(final_text, reply_markup=builder.as_markup(), parse_mode="HTML")
    except:
        try: await callback.message.answer(final_text, reply_markup=builder.as_markup(), parse_mode="HTML")
        except: pass