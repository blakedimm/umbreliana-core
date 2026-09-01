# File: handlers/syndicate/farms/menu.py
import os
import io
import asyncio
import time
import random
import json
import logging
import html
from aiogram import Router, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import FSInputFile, InputMediaPhoto, BufferedInputFile

from core.database import get_db, get_balance, get_farm, add_balance, update_farm, change_rating, get_user_data, get_clan
from handlers.users.statuses import get_active_statuses, has_active_status
from handlers.users.quests import process_quest_action

from handlers.users.design_generator import generate_html_farm_dashboard
from handlers.events.events_engine import GLOBAL_MODIFIERS

from .config import COOLING, fmt, get_tax_rate, GPUS, SLOTS_UPGRADES
from .engine import calculate_farm_state, perform_collection, sync_farm_passive, is_standard_gpu

router = Router()
farm_action_locks = set()
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
            logging.error(f"Ошибка загрузки локали {lang} в меню фермы: {e}")

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


async def safe_edit_text(obj, text: str, markup):
    message_obj = obj.message if isinstance(obj, types.CallbackQuery) else obj
    if message_obj.photo:
        try: await message_obj.delete()
        except: pass
        try: await message_obj.answer(text, reply_markup=markup, parse_mode="HTML")
        except: pass
    else:
        try: await message_obj.edit_text(text, reply_markup=markup, parse_mode="HTML")
        except: pass


# ==========================================
# 🏭 ОСНОВНОЙ ДАШБОРД ТЕРМИНАЛА
# ==========================================
async def send_farm_menu(user_id, message_obj, is_edit=False, _ = None):
    if not _: _ = await resolve_chat_translator(message_obj.chat.id, _)
        
    farm_data = await get_farm(user_id)
    await sync_farm_passive(user_id, farm_data)
    farm_data = await get_farm(user_id)
    balance = await get_balance(user_id)
    
    income_ph, pending_profit, is_full, total_heat, cooling_capacity, power_ph, total_watts = await calculate_farm_state(user_id, farm_data)
    
    try: user_name = (await message_obj.bot.get_chat(user_id)).first_name
    except: user_name = _("inv_agent_fallback", user_id=user_id)
    user_mention = f"<a href='tg://user?id={user_id}'>{user_name}</a>"
    
    active_statuses = await get_active_statuses(user_id)
    is_tech, is_magnate, is_architect, is_sovereign = 1 in active_statuses, 2 in active_statuses, 4 in active_statuses, (777 in active_statuses or 5 in active_statuses)
        
    names = []
    if is_tech: names.append(_("fm_license_tech"))
    if is_magnate: names.append(_("fm_license_magnate"))
    if 3 in active_statuses: names.append(_("fm_license_fortune"))
    if is_architect: names.append(_("fm_license_architect"))
    if is_sovereign: names.append(_("fm_license_sovereign"))
        
    tax_percent = int(get_tax_rate(income_ph) * 100)
    if is_magnate and tax_percent > 15:
        tax_percent = 15 
        
    boost = 1.15 if is_architect else 1.0 
    display_income, display_profit = int(income_ph * boost), int(pending_profit * boost)
    cooling_level = farm_data.get('cooling_level', 1)
    
    from handlers.economy.crypto import get_market_state
    current_course, *crypto_trash = await get_market_state()
    
    umc_wallet = int(farm_data.get('umc_balance', 0))
    estimated_u = int(umc_wallet * current_course)
    
    event_str = "Нет"
    if GLOBAL_MODIFIERS.get("end_time", 0) > time.time():
        event_str = GLOBAL_MODIFIERS.get("event_name", "Нет")
    
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute("ALTER TABLE farms ADD COLUMN IF NOT EXISTS render_html BOOLEAN DEFAULT TRUE")
        
        total_cards = await db.fetchval("SELECT SUM(qty) FROM gpu_batches WHERE user_id = $1", user_id) or 0
        active_title = await db.fetchval("SELECT title FROM users WHERE user_id = $1", user_id)
        has_any_title = await db.fetchval("SELECT 1 FROM user_titles WHERE user_id = $1 LIMIT 1", user_id)
        
        render_html = await db.fetchval("SELECT render_html FROM farms WHERE user_id = $1", user_id)
        if render_html is None: 
            render_html = True
    
    heat_status = _("fm_heat_critical") if total_heat > cooling_capacity else (_("fm_heat_elevated") if total_heat > cooling_capacity * 0.8 else _("fm_heat_nominal"))
    status = _("fm_status_overflow") if is_full else (_("fm_status_nominal") if income_ph > 0 else _("fm_status_offline"))

    sep = "✨════════════════════✨" if (active_title or is_sovereign) else "━━━━━━━━━━━━━━━━━━━━"
    if active_title:
        header = _("fm_hdr_custom", name=user_mention, title=active_title)
        balance_style = f"💎 <b>{fmt(balance)} ᴜ</b>"
    elif is_sovereign:
        header = _("fm_hdr_vip", name=user_mention)
        balance_style = f"👑 <b>{fmt(balance)} ᴜ</b>"
    else:
        header = _("fm_hdr_title", name=user_mention)
        balance_style = f"<b>{fmt(balance)} ᴜ</b>"

    licenses_str = f"\n🛡 <b>Clearances: {' + '.join(names)}</b>" if (" Clearances:" in _("fm_raid_alert_text") and names) else (f"\n🛡 <b>Лицензии: {' + '.join(names)}</b>" if names else "")

    if event_str != "Нет":
        prefix_newline = "" if licenses_str else "\n"
        licenses_str += f"{prefix_newline}\n⚠️ <b>ГЛОБАЛЬНОЕ СОБЫТИЕ: {event_str.upper()}</b>"

    text = _("fm_dashboard_body", 
             header=header, sep=sep, status=status, licenses=licenses_str,
             profit=fmt(display_profit), income=fmt(display_income), boost=' 🔥 (+15%)' if boost > 1.0 else '',
             power=fmt(power_ph), tax=tax_percent, wallet=fmt(umc_wallet), course=current_course, est=fmt(estimated_u),
             cards=total_cards, cooling_emoji=COOLING[cooling_level]['emoji'], cooling_name=COOLING[cooling_level]['name'],
             heat=fmt(total_heat), capacity=fmt(cooling_capacity), heat_status=heat_status, balance_style=balance_style)

    builder = InlineKeyboardBuilder()
    if income_ph > 0: 
        btn_collect_text = _("fm_btn_collect_elite") if has_any_title else _("fm_btn_collect_normal")
        builder.row(types.InlineKeyboardButton(text=btn_collect_text, callback_data=f"farm_collect_{user_id}"))
    
    if umc_wallet > 0:
        builder.row(types.InlineKeyboardButton(text=_("fm_btn_trade_umc"), callback_data=f"farm_trade_umc_{user_id}"))

    builder.row(types.InlineKeyboardButton(text=_("fm_btn_inventory"), callback_data=f"farm_my_gpus_{user_id}"))
    
    btn_shop_text = _("fm_btn_shop_vip") if is_sovereign else _("fm_btn_shop_normal")
    shop_callback = f"farm_vip_shop_{user_id}" if is_sovereign else f"farm_shop_{user_id}"
    builder.row(
        types.InlineKeyboardButton(text=btn_shop_text, callback_data=shop_callback),
        types.InlineKeyboardButton(text=_("fm_btn_cooling"), callback_data=f"farm_cooling_{user_id}")
    )
    builder.row(types.InlineKeyboardButton(text=_("fm_btn_racks"), callback_data=f"farm_slots_{user_id}"))
    
    btn_render_text = "🖼 Графика: СЕТЬ" if render_html else "📝 Графика: ТЕКСТ"
    builder.row(types.InlineKeyboardButton(text=btn_render_text, callback_data=f"farm_toggle_ui_{user_id}"))
    builder.row(types.InlineKeyboardButton(text=_("fm_btn_close"), callback_data=f"farm_close_{user_id}"))

    if has_any_title and render_html:
        if is_full:
            html_status_text = f'<span style="color: #ff003c;">{_("img_status_full")}</span>'
        elif income_ph > 0:
            html_status_text = f'<span style="color: #39ff14;">{_("img_status_ok")}</span>'
        else:
            html_status_text = f'<span style="color: #8b92a5;">{_("img_status_off")}</span>'
            
        localized_cooling_name = _(f"cool_name_{cooling_level}")
        if localized_cooling_name == f"cool_name_{cooling_level}":
            localized_cooling_name = COOLING[cooling_level]['name']
        
        filename = await asyncio.to_thread(
            generate_html_farm_dashboard, 
            user_id=user_id, username=user_name, active_title=active_title, balance=balance, 
            income_ph=display_income, heat=total_heat, cooling=cooling_capacity, cards=total_cards, 
            storage_val=display_profit, power_ph=power_ph, tax_percent=tax_percent, 
            cooling_name=localized_cooling_name, farm_status=html_status_text, licenses=names,
            is_boosted=(boost > 1.0), current_event=event_str, _=_
        )

        if os.path.exists(filename) and os.path.getsize(filename) > 0:
            with open(filename, "rb") as f: photo_bytes = f.read()
            photo = BufferedInputFile(photo_bytes, filename=filename)
            os.remove(filename)

            caption_text = _("fm_html_caption", name=user_mention)
            if is_edit:
                try:
                    await message_obj.edit_media(
                        media=InputMediaPhoto(media=photo, caption=caption_text, parse_mode="HTML"), 
                        reply_markup=builder.as_markup()
                    )
                except Exception:
                    try: await message_obj.delete()
                    except: pass
                    await message_obj.answer_photo(photo=photo, caption=caption_text, reply_markup=builder.as_markup(), parse_mode="HTML")
            else:
                await message_obj.answer_photo(photo=photo, caption=caption_text, reply_markup=builder.as_markup(), parse_mode="HTML")
        else:
            await message_obj.answer(_("fm_html_init_error"))
    else:
        if is_edit: await safe_edit_text(message_obj, text, builder.as_markup())
        else: await message_obj.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


# ==========================================
# ⚙️ ОБРАБОТЧИК ДЛЯ ПЕРЕКЛЮЧАТЕЛЯ UI РЕНДЕРА
# ==========================================
@router.callback_query(F.data.startswith("farm_toggle_ui_"))
async def cb_toggle_farm_ui(callback: types.CallbackQuery, _ = None):
    user_id = callback.from_user.id
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    if user_id != int(callback.data.split("_")[-1]): 
        return await callback.answer(_("fm_hands_off"), show_alert=True)
        
    pool = await get_db()
    async with pool.acquire() as db:
        current_state = await db.fetchval("SELECT render_html FROM farms WHERE user_id = $1", user_id)
        if current_state is None: current_state = True
        new_state = not current_state
        await db.execute("UPDATE farms SET render_html = $1 WHERE user_id = $2", new_state, user_id)
        
    await callback.answer("⚙️ Режим интерфейса успешно изменен!")
    await send_farm_menu(user_id, callback.message, is_edit=True, _=_)


# ==========================================
# 📥 СБОР ПРИБЫЛИ
# ==========================================
async def process_farm_collection(user_id: int, first_name: str, _ = None) -> dict:
    if not _: _ = get_translator("ru")
    net_profit, fire, broken, tax, rate, elec_str, emergency_msg, pending_crypto = await perform_collection(user_id, await get_farm(user_id))
    mention = f"<a href='tg://user?id={user_id}'>{first_name}</a>"

    if fire == "POLICE_RAID": return {"status": "raid", "net_profit": net_profit}
    if fire: return {"status": "fire", "text": _("fm_collect_fire_title", name=mention, fire=fire)}
    if net_profit <= 0 and tax <= 0 and not broken: return {"status": "empty", "text": _("fm_collect_empty", name=mention)}

    is_arch, is_sov = await has_active_status(user_id, 4), (await has_active_status(user_id, 777) or await has_active_status(user_id, 5))
    if is_arch and net_profit > 0:
        extra_architect_bonus = int(net_profit * 0.15)
        await update_farm(user_id, umc_balance=float((await get_farm(user_id)).get('umc_balance', 0)) + extra_architect_bonus)
        net_profit += extra_architect_bonus

    total_mined = pending_crypto
    hdr = _("fm_collect_sov_hdr", name=mention) if is_sov else _("fm_collect_normal_hdr", name=mention)
    sep = "✨══════════════════✨" if is_sov else "──────────────────"
    prefix = "👑 " if is_sov else "+"

    if broken:
        wear_footer_text = _("fm_collect_wear_title", sep=sep) + broken.strip()
    else:
        wear_footer_text = _("fm_collect_success_footer")

    # 🔥 ФИКС: Убрали `fmt(elec)` так как elec_str теперь уже отформатированная строка из engine
    receipt = _("fm_collect_receipt",
                hdr=hdr, sep=sep, total=fmt(total_mined), tax_rate=int(rate*100), tax=fmt(tax), elec=elec_str,
                prefix=prefix, net=fmt(net_profit), boost=" 🔥 (+15%)" if is_arch else "",
                emergency=emergency_msg, wear_footer=wear_footer_text)
    
    await process_quest_action(user_id, "farm_collect", 1)
    return {"status": "success", "text": receipt, "broken": bool(broken), "net_profit": net_profit}


# ==========================================
# 📊 МАРШРУТЫ И ОБРАБОТЧИКИ КОМАНД
# ==========================================
@router.message(lambda msg: msg.text and msg.text.lower().strip() in ["ферма", "🏭 ферма", "фарма", "собрать ферму", "farm", "my farm", "🏭 farm"])
async def cmd_farm(message: types.Message, _ = None):
    _ = await resolve_chat_translator(message.chat.id, _)
    user_id = message.from_user.id
    pool = await get_db()
    async with pool.acquire() as db:
        if not await db.fetchval("SELECT 1 FROM users WHERE user_id = $1", user_id): return 
    await send_farm_menu(user_id, message, _=_)


@router.callback_query(F.data.startswith("farm_main_"))
async def callback_farm_main(callback: types.CallbackQuery, _ = None):
    user_id = callback.from_user.id
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    if user_id != int(callback.data.split("_")[-1]): return await callback.answer(_("fm_hands_off"), show_alert=True)
        
    if user_id in farm_action_locks: return await callback.answer(_("fm_loading_hud"), show_alert=False)
        
    farm_action_locks.add(user_id)
    try:
        await callback.answer(_("fm_connecting_alert"))
        await send_farm_menu(user_id, callback.message, is_edit=True, _=_)
    finally:
        if user_id in farm_action_locks: farm_action_locks.remove(user_id)


@router.callback_query(F.data.startswith("farm_close_"))
async def close_farm_menu(callback: types.CallbackQuery, _ = None):
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    if callback.from_user.id != int(callback.data.split("_")[-1]): return await callback.answer(_("fm_hands_off"), show_alert=True)
    try: await callback.message.delete()
    except: await callback.answer(_("fm_minivan_exit_alert"), show_alert=True)


@router.message(F.text.lower().in_(["собрать", "собрать прибыль", "снять прибыль", "сбор", "collect", "extract", "claim"]))
async def text_farm_collect_profit(message: types.Message, _ = None):
    _ = await resolve_chat_translator(message.chat.id, _)
    res = await process_farm_collection(message.from_user.id, message.from_user.first_name, _=_)
    builder = InlineKeyboardBuilder()
    
    if res.get("status") == "raid":
        builder.button(text=_("fm_raid_bribe_btn"), callback_data=f"p_raid_bribe_{res['net_profit']}_{message.from_user.id}")
        builder.button(text=_("fm_raid_risk_btn"), callback_data=f"p_raid_risk_{res['net_profit']}_{message.from_user.id}")
        builder.adjust(1)
        return await message.reply(_("fm_raid_alert_text", profit=fmt(res['net_profit'])), reply_markup=builder.as_markup(), parse_mode="HTML")

    if res.get("net_profit", 0) > 0:
        builder.button(text=_("fm_swap_btn_shadow"), callback_data=f"shadow_swap_{message.from_user.id}")
    builder.adjust(1)
    await message.reply(res["text"], reply_markup=builder.as_markup() if res.get("net_profit", 0) > 0 else None, parse_mode="HTML")


@router.callback_query(F.data.startswith("farm_collect_"))
async def farm_collect_profit(callback: types.CallbackQuery, _ = None):
    user_id = callback.from_user.id
    owner_id = int(callback.data.split("_")[-1])
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    
    if user_id != owner_id: 
        try: return await callback.answer(_("fm_hands_off"), show_alert=True)
        except: return

    if user_id in farm_action_locks:
        try: return await callback.answer(_("fm_bribe_alert_processing"), show_alert=False)
        except: return
        
    farm_action_locks.add(user_id)
    try:
        res = await process_farm_collection(user_id, callback.from_user.first_name, _=_)
        builder = InlineKeyboardBuilder()
        
        if res.get("status") == "raid":
            builder.button(text=_("fm_raid_bribe_btn"), callback_data=f"p_raid_bribe_{res['net_profit']}_{user_id}")
            builder.button(text=_("fm_raid_risk_btn"), callback_data=f"p_raid_risk_{res['net_profit']}_{user_id}")
            builder.adjust(1)
            await callback.message.answer(_("fm_raid_alert_text", profit=fmt(res['net_profit'])), reply_markup=builder.as_markup(), parse_mode="HTML")
            await send_farm_menu(user_id, callback.message, is_edit=True, _=_)
            return
            
        if res.get("net_profit", 0) > 0:
            builder.button(text=_("fm_swap_btn_shadow"), callback_data=f"shadow_swap_{user_id}")
        builder.button(text=_("fm_btn_return_term"), callback_data=f"farm_main_{user_id}")
        builder.adjust(1)

        await callback.message.answer(res["text"], reply_markup=builder.as_markup(), parse_mode="HTML")
        await send_farm_menu(user_id, callback.message, is_edit=True, _=_)
    finally:
        if user_id in farm_action_locks:
            farm_action_locks.remove(user_id)


# ==========================================
# ❄️ МЕНЮ ОХЛАЖДЕНИЯ
# ==========================================
@router.callback_query(F.data.startswith("farm_cooling_"))
async def farm_cooling_menu(callback: types.CallbackQuery, _ = None):
    owner_id = int(callback.data.split("_")[-1])
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    if callback.from_user.id != owner_id: return await callback.answer(_("fm_hands_off"), show_alert=True)

    user_id = callback.from_user.id
    farm_data = await get_farm(user_id)
    current_cooling_level = farm_data.get('cooling_level', 1)
    balance = await get_balance(user_id)

    current_cool_info = COOLING.get(current_cooling_level)
    text = _("fm_cool_title", balance=fmt(balance), emoji=current_cool_info['emoji'], name=current_cool_info['name'], capacity=fmt(current_cool_info['capacity']))

    builder = InlineKeyboardBuilder()
    for level, data in sorted(COOLING.items()):
        if level <= current_cooling_level: continue
        price = data.get('price', 0)
        short_price = f"{price / 1_000_000:.1f}M" if price >= 1_000_000 else f"{price // 1_000}k" if price >= 1000 else str(price)
        builder.button(text=f"[💰 {short_price}] {data['emoji']} {data['name']}", callback_data=f"buy_cool_{level}_{user_id}")

    builder.button(text=_("fm_btn_back"), callback_data=f"farm_main_{user_id}")
    builder.adjust(1)
    await safe_edit_text(callback, text, builder.as_markup())


# ==========================================
# 💳 ПОКУПКА ОХЛАЖДЕНИЯ
# ==========================================
@router.callback_query(F.data.startswith("buy_cool_"))
async def buy_cooling_btn(callback: types.CallbackQuery, _ = None):
    owner_id = int(callback.data.split("_")[-1])
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    if callback.from_user.id != owner_id: return await callback.answer(_("fm_hands_off"), show_alert=True)

    user_id = callback.from_user.id
    target_level = int(callback.data.split("_")[2])
    if target_level not in COOLING: return await callback.answer("❌ Error!", show_alert=True)

    farm_data = await get_farm(user_id)
    current_level = farm_data.get('cooling_level', 1)
    if target_level <= current_level: return await callback.answer(_("fm_cool_err_installed"), show_alert=True)

    price = COOLING[target_level].get('price', 0)
    if await get_balance(user_id) < price: return await callback.answer(_("fm_cool_err_money"), show_alert=True)

    await add_balance(user_id, -price)
    await update_farm(user_id, cooling_level=target_level)
    await callback.answer(_("fm_cool_success_alert", name=COOLING[target_level]['name']), show_alert=True)
    await send_farm_menu(user_id, callback.message, is_edit=True, _=_)


# ==========================================
# 📦 МЕНЮ СТОЕК ОБОРУДОВАНИЯ
# ==========================================
@router.callback_query(F.data.startswith("farm_slots_"))
async def farm_slots_menu(callback: types.CallbackQuery, _ = None):
    owner_id = int(callback.data.split("_")[-1])
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    if callback.from_user.id != owner_id: return await callback.answer(_("fm_hands_off"), show_alert=True)

    user_id = callback.from_user.id
    farm_data = await get_farm(user_id)
    current_slots_level = farm_data.get('slots_level', 1)
    balance = await get_balance(user_id)

    current_slots_info = SLOTS_UPGRADES.get(current_slots_level, SLOTS_UPGRADES[1])
    text = _("fm_racks_title", balance=fmt(balance), emoji=current_slots_info['emoji'], name=current_slots_info['name'], capacity=fmt(current_slots_info['capacity']))
    
    max_level = max(SLOTS_UPGRADES.keys())
    if current_slots_level >= max_level: text += _("fm_racks_max_tier")
    else: text += _("fm_racks_avail_tier")

    builder = InlineKeyboardBuilder()
    for level, data in sorted(SLOTS_UPGRADES.items()):
        if level <= current_slots_level: continue
        price = data.get('price', 0)
        short_price = f"{price / 1_000_000:.1f}M" if price >= 1_000_000 else f"{price // 1_000}k" if price >= 1000 else str(price)
        
        btn_text = f"[💰 {short_price}] {data['emoji']} {data['name']} ({data['capacity']} )"
        builder.button(text=btn_text, callback_data=f"buy_slots_{level}_{user_id}")

    builder.button(text=_("fm_btn_back"), callback_data=f"farm_main_{user_id}")
    builder.adjust(1)
    await safe_edit_text(callback, text, builder.as_markup())


# ==========================================
# 💳 ПОКУПКА СТОЕК ОБОРУДОВАНИЯ
# ==========================================
@router.callback_query(F.data.startswith("buy_slots_"))
async def buy_slots_btn(callback: types.CallbackQuery, _ = None):
    owner_id = int(callback.data.split("_")[-1])
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    if callback.from_user.id != owner_id: return await callback.answer(_("fm_hands_off"), show_alert=True)

    user_id = callback.from_user.id
    target_level = int(callback.data.split("_")[2])
    if target_level not in SLOTS_UPGRADES: return await callback.answer("❌ Error!", show_alert=True)

    farm_data = await get_farm(user_id)
    current_level = farm_data.get('slots_level', 1)
    if target_level <= current_level: return await callback.answer(_("fm_racks_err_installed"), show_alert=True)

    target_slots_info = SLOTS_UPGRADES[target_level]
    price = target_slots_info.get('price', 0)
    if await get_balance(user_id) < price: return await callback.answer(_("fm_racks_err_money"), show_alert=True)

    await add_balance(user_id, -price)
    await update_farm(user_id, slots_level=target_level, max_slots=target_slots_info['capacity'])
    await callback.answer(_("fm_racks_success_alert", name=target_slots_info['name'], capacity=target_slots_info['capacity']), show_alert=True)
    await send_farm_menu(user_id, callback.message, is_edit=True, _=_)


# ==========================================
# 🚨 ОБРАБОТЧИКИ ИСХОДОВ РЕЙДА КИБЕРПОЛИЦИИ
# ==========================================
@router.callback_query(F.data.startswith("p_raid_bribe_"))
async def raid_bribe_choice(callback: types.CallbackQuery, _ = None):
    owner_id = int(callback.data.split("_")[-1])
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    if callback.from_user.id != owner_id: return await callback.answer(_("fm_hands_off"), show_alert=True)
    
    net_profit = int(callback.data.split("_")[3])
    bribe_amount = int(net_profit * 0.25)
    final_profit = net_profit - bribe_amount
    
    await add_balance(owner_id, final_profit, is_income=True)
    await callback.message.edit_text(_("fm_raid_bribe_success", bribe=fmt(bribe_amount), profit=fmt(final_profit)), parse_mode="HTML")
    await callback.answer(_("fm_bribe_alert_taken"))

@router.callback_query(F.data.startswith("p_raid_risk_"))
async def raid_risk_choice(callback: types.CallbackQuery, _ = None):
    owner_id = int(callback.data.split("_")[-1])
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    if callback.from_user.id != owner_id: return await callback.answer(_("fm_hands_off"), show_alert=True)
    
    net_profit = int(callback.data.split("_")[3])
    await callback.answer()
    
    if random.random() < 0.40:
        await add_balance(owner_id, net_profit, is_income=True)
        await callback.message.edit_text(_("fm_raid_risk_success", profit=fmt(net_profit)), parse_mode="HTML")
    else:
        lost_money = int(net_profit * 0.5)
        saved_money = net_profit - lost_money
        await add_balance(owner_id, saved_money, is_income=True)
        
        farm_data = await get_farm(owner_id)
        owned_gpus = [i for i in GPUS if farm_data.get(f'gpu_{i}', 0) > 0]
        burned_msg = ""
        
        if owned_gpus:
            target_gpu = max(owned_gpus, key=lambda x: GPUS[x]['price'])
            gpu_id_str = f'gpu_{target_gpu}'
            
            pool = await get_db()
            async with pool.acquire() as db:
                async with db.transaction():
                    target_batch = await db.fetchrow("SELECT id, qty FROM gpu_batches WHERE user_id = $1 AND gpu_id = $2 AND condition > 0 ORDER BY condition DESC LIMIT 1", owner_id, gpu_id_str)
                    if target_batch:
                        if target_batch['qty'] > 1: await db.execute("UPDATE gpu_batches SET qty = qty - 1 WHERE id = $1", target_batch['id'])
                        else: await db.execute("DELETE FROM gpu_batches WHERE id = $1", target_batch['id'])
            
            await update_farm(owner_id, **{gpu_id_str: farm_data[gpu_id_str] - 1})
            await change_rating(owner_id, -40)
            burned_msg = _("fm_raid_seizure_row", name=GPUS[target_gpu]['name'])

        await callback.message.edit_text(_("fm_raid_risk_fail", lost=fmt(lost_money), saved=fmt(saved_money), burned_msg=burned_msg), parse_mode="HTML")