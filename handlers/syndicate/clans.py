import re
import time
import random
import json
import os
import logging
import html
from handlers.users import statuses
from datetime import datetime
from aiogram import Router, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder

# 🔥 Подключаем рубильник модулей из админки
from handlers.admin import SYSTEM_MODULES
from handlers.users.quests import process_quest_action

from core.database import (
    get_balance, add_balance, get_user_data, update_user, 
    create_clan, get_clan, get_clan_members, add_clan_balance, 
    update_clan, get_top_clans, resolve_user_id, get_db
)

router = Router()

def fmt(num):
    return f"{int(num):,}".replace(",", " ")

CLAN_PRICE = 5_000_000 # Цена создания клана (5 лямов)

# ==========================================
# 🧬 ДРЕВО ТЕХНОЛОГИЙ СИНДИКАТА
# ==========================================
CLAN_TECH = {
    "income": {
        "max_lvl": 25, 
        "base_price": 50_000_000, 
        "mult": 1.4, 
        "emoji": "📈",
        "db_col": "tech_income",
        "name_key": "tech_name_income",
        "desc_key": "tech_desc_income"
    },
    "cooling": {
        "max_lvl": 10, 
        "base_price": 100_000_000, 
        "mult": 1.8, 
        "emoji": "❄️",
        "db_col": "tech_cooling",
        "name_key": "tech_name_cooling",
        "desc_key": "tech_desc_cooling"
    },
    "tax": {
        "max_lvl": 15, 
        "base_price": 200_000_000, 
        "mult": 1.6, 
        "emoji": "💼",
        "db_col": "tech_tax",
        "name_key": "tech_name_tax",
        "desc_key": "tech_desc_tax"
    },
    "firewall": {
        "max_lvl": 20, 
        "base_price": 100_000_000, 
        "mult": 1.45, 
        "emoji": "🛡",
        "db_col": "firewall_lvl",
        "name_key": "tech_name_firewall",
        "desc_key": "tech_desc_firewall"
    },
    "capacity": {
        "max_lvl": 18, 
        "base_price": 50_000_000, 
        "mult": 1.4, 
        "emoji": "👥",
        "db_col": "tech_capacity",
        "name_key": "tech_name_capacity",
        "desc_key": "tech_desc_capacity"
    }
}

# ==========================================
# 🎨 БЕЗОПАСНЫЙ СЛОВАРЬ ДЕФОЛТОВ (ДЛЯ ФОЛБЕКА)
# ==========================================
FALLBACK_STRINGS = {
    "tech_name_income": "Алгоритм сжатия", "tech_desc_income": "Увеличивает доход всех ферм на 2% за ур.",
    "tech_name_cooling": "Квантовое охлаждение", "tech_desc_cooling": "Снижает нагрев ферм на 5% за ур.",
    "tech_name_tax": "Офшорные юристы", "tech_desc_tax": "Снижает налог на сбор прибыли на 1% за ур.",
    "tech_name_firewall": "Военный Файрвол", "tech_desc_firewall": "Увеличивает защиту общака на 25 млн HP за ур.",
    "tech_name_capacity": "Расширение штата", "tech_desc_capacity": "Увеличивает максимальное количество бойцов в клане на +5 за ур."
}

def get_str(key: str, _=None, **kwargs) -> str:
    if _:
        return _(key, **kwargs)
    text = FALLBACK_STRINGS.get(key, key)
    if kwargs:
        try: return text.format(**kwargs)
        except: pass
    return text

# Внешняя l10n сборка для асинхронных бэкграунд-задач
LOCALES = {}
for l in ["ru", "en"]:
    p = f"locales/{l}.json"
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f: LOCALES[l] = json.load(f)

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

def get_bulk_tech_price(base_price, current_lvl, mult, add_levels):
    total_cost = 0
    for i in range(add_levels): total_cost += int(base_price * (mult ** (current_lvl + i)))
    return total_cost

def get_max_affordable_levels(balance, base_price, current_lvl, max_lvl, mult):
    affordable_levels = 0
    total_cost = 0
    for i in range(max_lvl - current_lvl):
        next_price = int(base_price * (mult ** (current_lvl + i)))
        if total_cost + next_price <= balance:
            total_cost += next_price
            affordable_levels += 1
        else: break
    return affordable_levels, total_cost

# ==========================================
# 🛡 СОЗДАНИЕ КЛАНА
# ==========================================
CREATE_CLAN_PATTERN = re.compile(r"^(?:создать клан|create clan)\s+([a-zA-Zа-яА-Я0-9]{2,5})\s+(.+)$", re.IGNORECASE)

@router.message(F.text.regexp(CREATE_CLAN_PATTERN))
async def cmd_create_clan(message: types.Message, _=None): 
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    if not SYSTEM_MODULES.get("кланы", True): return await message.reply(get_str("cl_sys_disabled", _), parse_mode="HTML")

    user_id = message.from_user.id
    user_data = await get_user_data(user_id)
    
    if user_data.get('clan_id', 0) > 0: return await message.reply(get_str("cl_err_already_in", _), parse_mode="HTML")

    current_balance = await get_balance(user_id)
    if current_balance < CLAN_PRICE:
        return await message.reply(get_str("cl_err_create_no_money", _, price=fmt(CLAN_PRICE), balance=fmt(current_balance)), parse_mode="HTML")

    match = CREATE_CLAN_PATTERN.match(message.text)
    tag = match.group(1).upper()
    name = match.group(2).strip()

    if len(name) > 20: return await message.reply(get_str("cl_err_name_too_long", _))

    pool = await get_db()
    async with pool.acquire() as db:
        exists = await db.fetchval("SELECT 1 FROM clans WHERE name ILIKE $1 OR tag ILIKE $2", name, tag)
        if exists: return await message.reply(get_str("cl_err_duplicate", _), parse_mode="HTML")

    await add_balance(user_id, -CLAN_PRICE)
    clan_id = await create_clan(user_id, tag, name)
    await process_quest_action(user_id, "clan_members", 1)

    await message.reply(get_str("cl_create_success", _, name=name, tag=tag, clan_id=clan_id), parse_mode="HTML")

# ==========================================
# 🏴‍☠️ ДАШБОРД СИНДИКАТА 2.0
# ==========================================
VIEW_CLAN_PATTERN = re.compile(r"^(?:мой клан|клан|синдикат|my clan|clan|syndicate)(?:\s+(.*?))?$", re.IGNORECASE)

@router.message(F.text.regexp(VIEW_CLAN_PATTERN))
async def cmd_view_clan(message: types.Message, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    if not SYSTEM_MODULES.get("кланы", True): return await message.reply(get_str("cl_sys_disabled", _), parse_mode="HTML")

    target_id = message.from_user.id
    is_self = True

    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        is_self = False
    else:
        match = VIEW_CLAN_PATTERN.match(message.text)
        if match and match.group(1):
            resolved_id = await resolve_user_id(match.group(1).strip())
            if resolved_id:
                target_id = resolved_id
                is_self = False
            else: return await message.reply(get_str("cl_err_player_not_found", _))

    user_data = await get_user_data(target_id)
    if not user_data: return await message.reply(get_str("cl_err_player_not_found", _))

    clan_id = user_data.get('clan_id', 0)

    if clan_id == 0:
        if is_self: return await message.reply(get_str("cl_self_lone", _), parse_mode="HTML")
        try:
            target_user = await message.bot.get_chat(target_id)
            target_name = target_user.first_name
        except: target_name = "Agent"
        return await message.reply(get_str("cl_target_lone", _, name=target_name), parse_mode="HTML")

    clan = await get_clan(clan_id)
    members = await get_clan_members(clan_id)
    total_members = len(members)
    
    if clan['owner_id'] == target_id: role = get_str("cl_role_boss", _)
    elif clan.get('deputy_id') == target_id: role = get_str("cl_role_deputy", _)
    else: role = get_str("cl_role_fighter", _)

    role_text = get_str("cl_lbl_role_self", _) if is_self else get_str("cl_lbl_role_target", _)

    tech_str = ""
    for key, tech in CLAN_TECH.items():
        lvl = clan.get(tech['db_col'], 0)
        bars = "■" * lvl + "□" * (tech['max_lvl'] - lvl)
        tech_str += f" ├ {tech['emoji']} {get_str(tech['name_key'], _)} [{lvl}/{tech['max_lvl']}]\n └ <code>[{bars}]</code>\n"

    if not tech_str: tech_str = get_str("cl_tech_not_started", _)

    top_players = ""
    for idx, (uid, nick, bal) in enumerate(members[:3], 1):
        icon = "👑" if uid == clan['owner_id'] else "🔹"
        display_name = nick if nick else f"Игрок {uid}"
        top_players += f"{idx}. {icon} <b>{display_name}</b> — <b>{fmt(bal)} ᴜ</b>\n"

    text = get_str("cl_view_body", _, tag=clan['tag'], name=clan['name'], id=clan['id'], role_lbl=role_text, role=role, members=total_members, balance=fmt(clan['balance']), tech_str=tech_str, top_players=top_players)

    if clan.get('under_attack_by', 0) != 0:
        if is_self: text += get_str("cl_view_siege_alert", _, hp=fmt(clan.get('current_firewall_hp', 0)))
        else: text += get_str("cl_view_siege_public", _, hp=fmt(clan.get('current_firewall_hp', 0)))

    if is_self: text += get_str("cl_view_footer_self", _)
    else: text += get_str("cl_view_footer_enemy", _, id=clan['id'])

    await message.reply(text, parse_mode="HTML")

# ==========================================
# 🧬 ЛАБОРАТОРИЯ (ПРОКАЧКА ТЕХНОЛОГИЙ)
# ==========================================
@router.message(F.text.lower().in_(["лаба", "лаборатория", "технологии", "исследования", "lab", "laboratory", "research"]))
async def cmd_tech_lab(message: types.Message, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    if not SYSTEM_MODULES.get("кланы", True): return
    
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)
    clan_id = user_data.get('clan_id', 0)
    if clan_id == 0: return

    clan = await get_clan(clan_id)
    if user_id not in (clan['owner_id'], clan.get('deputy_id', 0)): return await message.reply(get_str("cl_lab_err_rights", _))

    text = get_str("cl_lab_header", _, balance=fmt(clan['balance']))
    
    for key, tech in CLAN_TECH.items():
        current_lvl = clan.get(tech['db_col'], 0)
        t_name = get_str(tech['name_key'], _)
        if current_lvl >= tech['max_lvl']:
            text += get_str("cl_lab_max_row", _, emoji=tech['emoji'], name=t_name)
        else:
            price = get_bulk_tech_price(tech['base_price'], current_lvl, tech['mult'], 1)
            text += get_str("cl_lab_row", _, emoji=tech['emoji'], name=t_name, lvl=current_lvl, max_lvl=tech['max_lvl'], desc=get_str(tech['desc_key'], _), price=fmt(price))

    text += get_str("cl_lab_footer", _)
    await message.reply(text, parse_mode="HTML")

@router.message(F.text.lower().startswith(("изучить ", "research ")))
async def cmd_research_tech(message: types.Message, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    if not SYSTEM_MODULES.get("кланы", True): return
    
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)
    clan_id = user_data.get('clan_id', 0)
    if clan_id == 0: return
    clan = await get_clan(clan_id)
    
    if user_id not in (clan['owner_id'], clan.get('deputy_id', 0)): return await message.reply(get_str("cl_research_err_rights", _))

    search_str = message.text.lower().replace("изучить ", "").replace("research ", "").strip()
    target_key, target_tech = None, None
    for key, tech in CLAN_TECH.items():
        if search_str in get_str(tech['name_key'], _).lower():
            target_key, target_tech = key, tech
            break

    if not target_tech: return await message.reply(get_str("cl_research_err_not_found", _), parse_mode="HTML")

    current_lvl = clan.get(target_tech['db_col'], 0)
    t_name = get_str(target_tech['name_key'], _)
    if current_lvl >= target_tech['max_lvl']:
        return await message.reply(get_str("cl_research_err_max", _, name=t_name), parse_mode="HTML")

    cost_1 = get_bulk_tech_price(target_tech['base_price'], current_lvl, target_tech['mult'], 1)
    builder = InlineKeyboardBuilder()
    
    if clan['balance'] >= cost_1: builder.button(text=f"+1 Lvl ({fmt(cost_1)} ᴜ)", callback_data=f"techup_{target_key}_1")
    else: builder.button(text=get_str("cl_btn_tech_no_money", _), callback_data="ignore")

    if current_lvl + 5 <= target_tech['max_lvl']:
        cost_5 = get_bulk_tech_price(target_tech['base_price'], current_lvl, target_tech['mult'], 5)
        if clan['balance'] >= cost_5: builder.button(text=f"+5 Lvl ({fmt(cost_5)} ᴜ)", callback_data=f"techup_{target_key}_5")

    max_lvls, max_cost = get_max_affordable_levels(clan['balance'], target_tech['base_price'], current_lvl, target_tech['max_lvl'], target_tech['mult'])
    if max_lvls > 1 and max_lvls != 5:
        builder.button(text=f"MAX: +{max_lvls} Lvl ({fmt(max_cost)} ᴜ)", callback_data=f"techup_{target_key}_max")

    builder.adjust(1)
    text = get_str("cl_research_menu_body", _, name=t_name, lvl=current_lvl, max_lvl=target_tech['max_lvl'], balance=fmt(clan['balance']))
    await message.reply(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("techup_"))
async def process_tech_upgrade(callback: types.CallbackQuery, _=None):
    if not _: _ = await resolve_chat_translator(callback.message.chat.id, _)
    if not SYSTEM_MODULES.get("кланы", True): return await callback.answer("System Maintenance!", show_alert=True)
        
    user_id = callback.from_user.id
    user_data = await get_user_data(user_id)
    clan_id = user_data.get('clan_id', 0)
    if clan_id == 0: return await callback.answer(get_str("cl_upgrade_err_clan", _), show_alert=True)

    data = callback.data.split("_")
    tech_key, amount_str = data[1], data[2]
    target_tech = CLAN_TECH.get(tech_key)
    if not target_tech: return await callback.answer("Upgrade Matrix Error.", show_alert=True)

    clan = await get_clan(clan_id)
    if user_id not in (clan['owner_id'], clan.get('deputy_id', 0)): return await callback.answer(get_str("cl_upgrade_err_rights", _), show_alert=True)

    current_lvl = clan.get(target_tech['db_col'], 0)
    if current_lvl >= target_tech['max_lvl']: return await callback.answer(get_str("cl_upgrade_err_max", _), show_alert=True)

    levels_to_buy, total_cost = 0, 0
    if amount_str == "max":
        levels_to_buy, total_cost = get_max_affordable_levels(clan['balance'], target_tech['base_price'], current_lvl, target_tech['max_lvl'], target_tech['mult'])
    else:
        levels_to_buy = int(amount_str)
        if current_lvl + levels_to_buy > target_tech['max_lvl']: levels_to_buy = target_tech['max_lvl'] - current_lvl
        total_cost = get_bulk_tech_price(target_tech['base_price'], current_lvl, target_tech['mult'], levels_to_buy)

    if levels_to_buy <= 0 or clan['balance'] < total_cost: return await callback.answer(get_str("cl_upgrade_err_no_money", _), show_alert=True)

    new_balance = clan['balance'] - total_cost
    new_lvl = current_lvl + levels_to_buy
    await update_clan(clan_id, balance=new_balance, **{target_tech['db_col']: new_lvl})

    text = get_str("cl_upgrade_success", _, tag=clan['tag'], name=get_str(target_tech['name_key'], _), gained=levels_to_buy, lvl=new_lvl, max_lvl=target_tech['max_lvl'], price=fmt(total_cost))
    await callback.message.edit_text(text, parse_mode="HTML")

# ==========================================
# 👑 ПАНЕЛЬ УПРАВЛЕНИЯ КЛАНОМ (ДЛЯ БОССА)
# ==========================================
@router.message(F.text.lower().in_(["клан панель", "clan panel"]))
async def cmd_clan_panel(message: types.Message, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    if not SYSTEM_MODULES.get("кланы", True): return
    
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)
    clan_id = user_data.get('clan_id', 0)
    if clan_id == 0: return await message.reply(get_str("cl_panel_err_lone", _))

    clan = await get_clan(clan_id)
    if clan['owner_id'] != user_id: return await message.reply(get_str("cl_panel_err_rights", _), parse_mode="HTML")

    text = get_str("cl_panel_body", _, tag=clan['tag'], id=clan['id'])
    await message.reply(text, parse_mode="HTML")

# ==========================================
# 🛡 ВСТУПЛЕНИЕ И ВЫХОД
# ==========================================
@router.message(F.text.lower().startswith(("вступить ", "join ")))
async def cmd_join_clan(message: types.Message, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    if not SYSTEM_MODULES.get("кланы", True): return
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)
    
    if user_data.get('clan_id', 0) > 0: return await message.reply(get_str("cl_join_err_in", _))

    parts = message.text.split()
    if len(parts) < 2 or not parts[-1].isdigit(): return await message.reply(get_str("cl_join_err_args", _), parse_mode="HTML")

    target_clan_id = int(parts[-1])
    clan = await get_clan(target_clan_id)
    if not clan: return await message.reply(get_str("cl_join_err_not_found", _))
    
    members = await get_clan_members(target_clan_id)
    max_members = 10 + (clan.get('tech_capacity', 0) * 5) 

    if len(members) >= max_members:
        return await message.reply(get_str("cl_join_err_max", _, tag=clan['tag'], current=len(members), max=max_members), parse_mode="HTML")

    await update_user(user_id, clan_id=target_clan_id)
    await process_quest_action(clan['owner_id'], "clan_members", 1)
    
    # Пуш-уведомление лидеру на его родном языке
    pool = await get_db()
    async with pool.acquire() as db:
        boss_lang = await db.fetchval("SELECT lang FROM users WHERE user_id = $1", clan['owner_id']) or "ru"
    _boss = get_translator(boss_lang)
    try:
        await message.bot.send_message(clan['owner_id'], get_str("cl_join_ref_alert", _boss, user_id=user_id, name=message.from_user.first_name), parse_mode="HTML")
    except: pass

    await message.reply(get_str("cl_join_success", _, tag=clan['tag'], name=clan['name']), parse_mode="HTML")

@router.message(F.text.lower().in_(["покинуть клан", "leave clan"]))
async def cmd_leave_clan(message: types.Message, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)
    clan_id = user_data.get('clan_id', 0)
    if clan_id == 0: return await message.reply(get_str("cl_leave_err_lone", _))

    clan = await get_clan(clan_id)
    if clan['owner_id'] == user_id: return await message.reply(get_str("cl_leave_err_boss", _), parse_mode="HTML")

    await update_user(user_id, clan_id=0)
    pool = await get_db()
    async with pool.acquire() as db: await db.execute("UPDATE users SET clan_donated = 0 WHERE user_id = $1", user_id)

    await message.reply(get_str("cl_leave_success", _))

# ==========================================
# 💰 ВЗНОС В ОБЩАК
# ==========================================
@router.message(F.text.lower().startswith(("взнос ", "contribute ", "deposit ")))
async def cmd_donate_clan(message: types.Message, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    if not SYSTEM_MODULES.get("кланы", True): return
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)
    clan_id = user_data.get('clan_id', 0)
    if clan_id == 0: return await message.reply(get_str("cl_don_err_lone", _))

    parts = message.text.lower().split()
    amount_str = parts[-1].replace('к', '000').replace('k', '000').replace('m', '000000').replace('м', '000000')
    if not amount_str.isdigit(): return await message.reply(get_str("cl_don_err_invalid", _))

    amount = int(amount_str)
    if amount <= 0: return await message.reply(get_str("cl_don_err_zero", _))
    if await get_balance(user_id) < amount: return await message.reply(get_str("cl_don_err_no_money", _))

    await add_balance(user_id, -amount)
    await add_clan_balance(clan_id, amount)

    pool = await get_db()
    async with pool.acquire() as db: await db.execute("UPDATE users SET clan_donated = clan_donated + $1 WHERE user_id = $2", amount, user_id)
    await process_quest_action(user_id, "clan_contribute", 1)

    await message.reply(get_str("cl_don_success", _, amount=fmt(amount)), parse_mode="HTML")

# ==========================================
# 🏆 ТОП СИНДИКАТОВ СЕРВЕРА
# ==========================================
@router.message(F.text.lower().in_(["топ кланов", "топ кланы", "кланы", "🏴‍☠️ кланы", "top clans", "clans", "🏴‍☠️ clans"]))
async def cmd_top_clans(message: types.Message, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    clans = await get_top_clans(10)
    text = get_str("cl_top_header", _)
    
    if not clans: text += get_str("cl_top_empty", _)
    else:
        medals = ["🥇", "🥈", "🥉"]
        for i, clan in enumerate(clans, 1):
            prefix = medals[i-1] if i <= 3 else f"<b>{i}.</b>"
            text += get_str("cl_top_row", _, prefix=prefix, tag=clan['tag'], name=clan['name'], balance=fmt(clan['balance']))

    text += get_str("cl_top_footer", _)
    builder = InlineKeyboardBuilder()
    builder.button(text=get_str("cl_btn_my_clan", _), callback_data="my_clan_menu")
    builder.adjust(1)
    await message.reply(text, reply_markup=builder.as_markup(), parse_mode="HTML")

# ==========================================
# 🛡 МЕНЮ "МОЙ КЛАН" (ДЛЯ ИНЛАЙН КНОПКИ)
# ==========================================
@router.callback_query(F.data == "my_clan_menu")
async def cb_my_clan_menu(callback: types.CallbackQuery, _=None):
    if not _: _ = await resolve_chat_translator(callback.message.chat.id, _)
    user_id = callback.from_user.id
    user_data = await get_user_data(user_id)
    clan_id = user_data.get('clan_id', 0)
    if clan_id == 0: return await callback.answer(get_str("cl_cb_menu_err_lone", _), show_alert=True)

    clan = await get_clan(clan_id)
    members = await get_clan_members(clan_id)

    if clan['owner_id'] == user_id: role = get_str("cl_role_boss_short", _)
    elif clan.get('deputy_id') == user_id: role = get_str("cl_role_deputy_short", _)
    else: role = get_str("cl_role_fighter_short", _)

    text = get_str("cl_cb_menu_body", _, tag=clan['tag'], name=clan['name'], id=clan['id'], role=role, members=len(members), balance=fmt(clan['balance']))
    builder = InlineKeyboardBuilder()
    builder.button(text=get_str("cl_btn_my_share", _), callback_data="claim_clan_share_cb")
    builder.button(text=get_str("cl_btn_back_top", _), callback_data="back_to_top_clans")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "back_to_top_clans")
async def cb_back_to_top_clans(callback: types.CallbackQuery, _=None):
    if not _: _ = await resolve_chat_translator(callback.message.chat.id, _)
    clans = await get_top_clans(10)
    text = get_str("cl_top_header", _)
    
    if not clans: text += get_str("cl_top_empty", _)
    else:
        medals = ["🥇", "🥈", "🥉"]
        for i, clan in enumerate(clans, 1):
            prefix = medals[i-1] if i <= 3 else f"<b>{i}.</b>"
            text += get_str("cl_top_row", _, prefix=prefix, tag=clan['tag'], name=clan['name'], balance=fmt(clan['balance']))

    text += get_str("cl_top_footer", _)
    builder = InlineKeyboardBuilder()
    builder.button(text=get_str("cl_btn_my_clan", _), callback_data="my_clan_menu")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

# ==========================================
# 💸 СМАРТ-КОНТРАКТ ДИВИДЕНДОВ
# ==========================================
async def process_clan_share_logic(user_id: int, _=None) -> tuple[bool, str]:
    if not _: _ = get_translator("ru")
    user_data = await get_user_data(user_id)
    clan_id = user_data.get('clan_id', 0)
    if clan_id == 0: return False, get_str("cl_share_err_lone", _)

    clan = await get_clan(clan_id)
    if clan['balance'] < 5_000_000: return False, get_str("cl_share_err_empty", _)

    donated = user_data.get('clan_donated', 0)
    if donated <= 0: return False, get_str("cl_share_err_freeloader", _)

    current_time = int(time.time())
    last_payout = user_data.get('last_clan_payout', 0)
    time_passed = current_time - last_payout
    
    if time_passed < 86400: 
        rem_h, rem_m = (86400 - time_passed) // 3600, ((86400 - time_passed) % 3600) // 60
        return False, get_str("cl_share_err_cooldown", _, hours=rem_h, minutes=rem_m)

    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            fresh_clan = await db.fetchrow("SELECT balance FROM clans WHERE id = $1", clan_id)
            members_count = await db.fetchval("SELECT COUNT(user_id) FROM users WHERE clan_id = $1", clan_id) or 1
            total_donated = await db.fetchval("SELECT SUM(clan_donated) FROM users WHERE clan_id = $1", clan_id) or 1
            
            calculated_payout = int(donated * 0.01)
            user_payout = min(calculated_payout, 50_000_000)
            
            tax_msg = ""
            if members_count < 10:
                user_payout = int(user_payout * 0.5)
                tax_msg = get_str("cl_share_tax_msg", _)

            if user_payout > fresh_clan['balance']: user_payout = fresh_clan['balance']
            if user_payout < 100: return False, get_str("cl_share_err_min", _)

            await db.execute("UPDATE clans SET balance = balance - $1 WHERE id = $2", user_payout, clan_id)
            await db.execute("UPDATE users SET balance = balance + $1, last_clan_payout = $2 WHERE user_id = $3", user_payout, current_time, user_id)

    user_share_pct = donated / total_donated
    success_text = get_str("cl_share_success", _, donated=fmt(donated), percent=round(user_share_pct * 100, 2), payout=fmt(user_payout), tax=tax_msg)
    return True, success_text

@router.message(F.text.lower().in_(["доля", "моя доля", "дивиденды", "получить долю", "share", "my share", "dividends"]))
async def cmd_clan_share(message: types.Message, _=None):
    _ = await resolve_chat_translator(message.chat.id, _)
    is_success, text = await process_clan_share_logic(message.from_user.id, _=_)
    await message.reply(text, parse_mode="HTML")

@router.callback_query(F.data == "claim_clan_share_cb")
async def cb_claim_clan_share(callback: types.CallbackQuery, _=None):
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    is_success, text = await process_clan_share_logic(callback.from_user.id, _=_)
    if is_success: await callback.message.edit_text(text, parse_mode="HTML")
    else: await callback.answer(text, show_alert=True)

# ==========================================
# 👥 УПРАВЛЕНИЕ ЗАМЕСТИТЕЛЕМ
# ==========================================
@router.message(F.text.lower().startswith(("+зам ", "+deputy ")))
async def cmd_add_deputy(message: types.Message, _=None):
    _ = await resolve_chat_translator(message.chat.id, _)
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)
    clan_id = user_data.get('clan_id', 0)
    if clan_id == 0: return
    clan = await get_clan(clan_id)

    if clan['owner_id'] != user_id: return await message.reply(get_str("cl_dep_err_rights", _))

    target_id = None
    if message.reply_to_message: target_id = message.reply_to_message.from_user.id
    else:
        parts = message.text.split()
        if len(parts) > 1: target_id = await resolve_user_id(parts[1])

    if not target_id: return await message.reply(get_str("cl_dep_err_args", _), parse_mode="HTML")
    if target_id == user_id: return await message.reply(get_str("cl_dep_err_self", _))

    target_data = await get_user_data(target_id)
    if target_data.get('clan_id') != clan_id: return await message.reply(get_str("cl_dep_err_not_member", _))

    await update_clan(clan_id, deputy_id=target_id)
    try:
        t_user = await message.bot.get_chat(target_id)
        t_name = t_user.first_name
    except: t_name = f"ID:{target_id}"

    await message.reply(get_str("cl_dep_add_success", _, name=t_name), parse_mode="HTML")

@router.message(F.text.lower().in_(["-зам", "-deputy"]))
async def cmd_remove_deputy(message: types.Message, _=None):
    _ = await resolve_chat_translator(message.chat.id, _)
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)
    clan_id = user_data.get('clan_id', 0)
    if clan_id == 0: return
    clan = await get_clan(clan_id)

    if clan['owner_id'] != user_id: return await message.reply(get_str("cl_dep_rem_rights", _))
    if clan.get('deputy_id', 0) == 0: return await message.reply(get_str("cl_dep_rem_err_none", _))

    await update_clan(clan_id, deputy_id=0)
    await message.reply(get_str("cl_dep_rem_success", _))

# ==========================================
# 👑 ПЕРЕДАЧА ВЛАСТИ И ИЗГНАНИЕ
# ==========================================
@router.message(F.text.lower().startswith(("изгнать", "kick")) & (F.reply_to_message))
async def cmd_clan_kick(message: types.Message, _=None):
    _ = await resolve_chat_translator(message.chat.id, _)
    caller_id = message.from_user.id
    caller_data = await get_user_data(caller_id)
    clan_id = caller_data.get('clan_id', 0)
    if clan_id == 0: return
    clan = await get_clan(clan_id)
    
    if caller_id not in (clan['owner_id'], clan.get('deputy_id', 0)): return await message.reply(get_str("cl_kick_err_rights", _))

    target_id = message.reply_to_message.from_user.id
    if target_id == clan['owner_id']: return await message.reply(get_str("cl_kick_err_boss", _))
    if target_id == caller_id: return await message.reply(get_str("cl_kick_err_self", _))

    target_data = await get_user_data(target_id)
    if target_data.get('clan_id') != clan_id: return await message.reply(get_str("cl_kick_err_not_member", _))

    await update_user(target_id, clan_id=0)
    pool = await get_db()
    async with pool.acquire() as db: await db.execute("UPDATE users SET clan_donated = 0 WHERE user_id = $1", target_id)
    if target_id == clan.get('deputy_id', 0): await update_clan(clan_id, deputy_id=0)

    await message.reply(get_str("cl_kick_success", _, name=message.reply_to_message.from_user.first_name), parse_mode="HTML")

@router.message(F.text.lower().startswith(("передать клан", "transfer clan")))
async def cmd_transfer_clan(message: types.Message, _=None):
    _ = await resolve_chat_translator(message.chat.id, _)
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)
    clan_id = user_data.get('clan_id', 0)
    if clan_id == 0: return
    clan = await get_clan(clan_id)

    if clan['owner_id'] != user_id: return await message.reply(get_str("cl_trans_err_rights", _))

    current_time = int(time.time())
    if current_time - clan.get('created_at', current_time) < 86400: return await message.reply(get_str("cl_trans_err_young", _), parse_mode="HTML")

    target_id = None
    if message.reply_to_message: target_id = message.reply_to_message.from_user.id
    else:
        cmd_len = len("передать клан") if message.text.lower().startswith("передать клан") else len("transfer clan")
        raw_arg = message.text[cmd_len:].strip()
        if raw_arg: target_id = await resolve_user_id(raw_arg)

    if not target_id: return await message.reply(get_str("cl_trans_err_args", _), parse_mode="HTML")
    if target_id == user_id: return await message.reply(get_str("cl_trans_err_self", _))

    target_data = await get_user_data(target_id)
    if target_data.get('clan_id') != clan_id: return await message.reply(get_str("cl_trans_err_not_member", _))

    updates = {'owner_id': target_id}
    if clan.get('deputy_id') == target_id: updates['deputy_id'] = 0
    await update_clan(clan_id, **updates)

    try:
        t_user = await message.bot.get_chat(target_id)
        t_name = t_user.first_name
    except: t_name = f"ID:{target_id}"

    await message.reply(get_str("cl_trans_success", _, tag=clan['tag'], name=t_name), parse_mode="HTML")

@router.message(F.text.lower().startswith(("распустить клан", "disband clan")))
async def cmd_disband_clan(message: types.Message, _=None):
    _ = await resolve_chat_translator(message.chat.id, _)
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)
    clan_id = user_data.get('clan_id', 0)
    if clan_id == 0: return await message.reply(get_str("cl_disband_err_rights", _))

    clan = await get_clan(clan_id)
    if clan['owner_id'] != user_id: return await message.reply(get_str("cl_disband_err_rights", _))

    parts = message.text.split()
    if len(parts) < 3 or not parts[-1].isdigit():
        return await message.reply(get_str("cl_disband_prompt", _, id=clan_id), parse_mode="HTML")

    if int(parts[-1]) != clan_id: return await message.reply(get_str("cl_disband_err_id", _))

    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            await db.execute("UPDATE users SET clan_id = 0, clan_donated = 0 WHERE clan_id = $1", clan_id)
            await db.execute("DELETE FROM clans WHERE id = $1", clan_id)

    await message.reply(get_str("cl_disband_success", _, tag=clan['tag']), parse_mode="HTML")

# ==========================================
# 🌐 PvE РЕЙДЫ (СОВМЕСТНЫЕ КОНТРАКТЫ)
# ==========================================
RAID_BOSSES = {
    1: {"name": "База конкурентов", "hp": 2_000_000, "reward": 25_000_000, "cost": 2_000_000, "emoji": "🗄"},
    2: {"name": "Центральный Банк", "hp": 15_000_000, "reward": 200_000_000, "cost": 15_000_000, "emoji": "🏦"},
    3: {"name": "Сервера Пентагона", "hp": 150_000_000, "reward": 2_500_000_000, "cost": 150_000_000, "emoji": "🛡"},
    4: {"name": "ИИ 'Скайнет'", "hp": 1_500_000_000, "reward": 30_000_000_000, "cost": 2_000_000_000, "emoji": "🤖"},
    5: {"name": "Квантовый Архив", "hp": 15_000_000_000, "reward": 400_000_000_000, "cost": 25_000_000_000, "emoji": "🌌"}
}

@router.message(F.text.lower().in_(["контракты", "контракт", "рейды", "contracts", "contract", "raids"]))
async def cmd_raid_contracts(message: types.Message, _=None):
    _ = await resolve_chat_translator(message.chat.id, _)
    if not SYSTEM_MODULES.get("кланы", True): return
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)
    clan_id = user_data.get('clan_id', 0)
    if clan_id == 0: return await message.reply(get_str("cl_raid_err_member", _))

    clan = await get_clan(clan_id)
    if clan.get('raid_id', 0) != 0: return await message.reply(get_str("cl_raid_err_already_active", _), parse_mode="HTML")

    text = get_str("cl_raid_header", _, balance=fmt(clan['balance']))
    for i, boss in RAID_BOSSES.items():
        text += get_str("cl_raid_row", _, id=i, emoji=boss['emoji'], name=boss['name'], hp=fmt(boss['hp']), reward=fmt(boss['reward']), cost=fmt(boss['cost']))

    text += get_str("cl_raid_footer", _)
    await message.reply(text, parse_mode="HTML")

@router.message(F.text.lower().startswith(("начать рейд ", "start raid ")))
async def cmd_start_raid(message: types.Message, _=None):
    _ = await resolve_chat_translator(message.chat.id, _)
    if not SYSTEM_MODULES.get("кланы", True): return
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)
    clan_id = user_data.get('clan_id', 0)
    if clan_id == 0: return
    clan = await get_clan(clan_id)

    if user_id not in (clan['owner_id'], clan.get('deputy_id', 0)): return await message.reply(get_str("cl_raid_start_err_rights", _))
    if clan.get('raid_id', 0) != 0: return await message.reply(get_str("cl_raid_start_err_active", _))

    parts = message.text.split()
    if not parts[-1].isdigit(): return await message.reply(get_str("cl_raid_start_err_args", _))

    raid_id = int(parts[-1])
    if raid_id not in RAID_BOSSES: return await message.reply(get_str("cl_raid_start_err_not_found", _))

    boss = RAID_BOSSES[raid_id]
    if clan['balance'] < boss['cost']: return await message.reply(get_str("cl_raid_start_err_open_money", _, cost=fmt(boss['cost'])), parse_mode="HTML")

    deadline = int(time.time()) + 86400 
    await update_clan(clan_id, balance=clan['balance'] - boss['cost'], raid_id=raid_id, raid_hp=boss['hp'], raid_deadline=deadline)
    await message.reply(get_str("cl_raid_start_success", _, tag=clan['tag'], name=boss['name']), parse_mode="HTML")

    members = await get_clan_members(clan_id)
    pool = await get_db()
    
    # Пушим соклановцев на их языках
    for m in members:
        uid = m[0]
        if uid != user_id:
            async with pool.acquire() as db:
                m_lang = await db.fetchval("SELECT lang FROM users WHERE user_id = $1", uid) or "ru"
            _m = get_translator(m_lang)
            try:
                await message.bot.send_message(chat_id=uid, text=get_str("cl_raid_member_alert", _m, tag=clan['tag'], name=boss['name'], hp=fmt(boss['hp']), reward=fmt(boss['reward'])), parse_mode="HTML")
            except: pass

@router.message(F.text.lower().in_(["рейд", "raid"]))
async def cmd_active_raid(message: types.Message, _=None):
    _ = await resolve_chat_translator(message.chat.id, _)
    if not SYSTEM_MODULES.get("кланы", True): return
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)
    clan_id = user_data.get('clan_id', 0)
    if clan_id == 0: return
    clan = await get_clan(clan_id)

    raid_id = clan.get('raid_id', 0)
    if raid_id == 0: return await message.reply(get_str("cl_raid_active_err_none", _), parse_mode="HTML")

    boss = RAID_BOSSES[raid_id]
    current_hp, max_hp = clan.get('raid_hp', 0), boss['hp']
    time_left = clan.get('raid_deadline', 0) - int(time.time())

    if time_left <= 0:
        await update_clan(clan_id, raid_id=0, raid_hp=0, raid_deadline=0)
        return await message.reply(get_str("cl_raid_active_timeout", _, name=boss['name']), parse_mode="HTML")

    rem_h, rem_m = time_left // 3600, (time_left % 3600) // 60
    hp_percent = max(0.0, current_hp / max_hp)
    filled = int((1.0 - hp_percent) * 10)
    hp_bar = f"[{'■' * filled}{'□' * (10 - filled)}]"

    text = get_str("cl_raid_active_body", _, name=boss['name'], current_hp=fmt(current_hp), max_hp=fmt(max_hp), bar=hp_bar, percent=int((1 - hp_percent) * 100), hours=rem_h, minutes=rem_m)
    await message.reply(text, parse_mode="HTML")

@router.message(F.text.lower().in_(["ддос", "ddos", "атака", "attack"]))
async def cmd_raid_attack(message: types.Message, _=None):
    _ = await resolve_chat_translator(message.chat.id, _)
    if not SYSTEM_MODULES.get("кланы", True): return
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)
    clan_id = user_data.get('clan_id', 0)
    if clan_id == 0: return await message.reply(get_str("cl_atk_err_lone", _))

    clan = await get_clan(clan_id)
    raid_id = clan.get('raid_id', 0)
    if raid_id == 0: return await message.reply(get_str("cl_atk_err_none", _))

    if int(time.time()) > clan.get('raid_deadline', 0):
        await update_clan(clan_id, raid_id=0, raid_hp=0, raid_deadline=0)
        return await message.reply(get_str("cl_atk_err_timeout", _))

    current_time = int(time.time())
    last_attack = user_data.get('last_raid_attack', 0)
    if current_time - last_attack < 14400:
        rem = 14400 - (current_time - last_attack)
        return await message.reply(get_str("cl_atk_err_cooldown", _, hours=rem // 3600, minutes=(rem % 3600) // 60), parse_mode="HTML")

    base_power = await get_hacker_power(user_id)
    damage = int((base_power * (1.0 + (clan.get('tech_income', 0) * 0.02))) * random.uniform(0.8, 1.2))
    if damage < 1000: return await message.reply(get_str("cl_atk_err_weak", _))

    await update_user(user_id, last_raid_attack=current_time)
    current_hp = clan.get('raid_hp', 0)
    new_hp = current_hp - damage
    boss = RAID_BOSSES[raid_id]

    if new_hp <= 0:
        reward = boss['reward']
        pool = await get_db()
        async with pool.acquire() as db:
            async with db.transaction():
                await db.execute("UPDATE clans SET raid_id=0, raid_hp=0, raid_deadline=0, balance=balance+$1 WHERE id=$2", reward, clan_id)
                personal_bonus = int(reward * 0.05)
                await db.execute("UPDATE users SET balance=balance+$1 WHERE user_id=$2", personal_bonus, user_id)
        await message.reply(get_str("cl_atk_success_win", _, name=message.from_user.first_name, boss_name=boss['name'], reward=fmt(reward), bonus=fmt(personal_bonus)), parse_mode="HTML")
    else:
        await update_clan(clan_id, raid_hp=new_hp)
        await message.reply(get_str("cl_atk_success_hit", _, boss_name=boss['name'], damage=fmt(damage), hp=fmt(new_hp)), parse_mode="HTML")

async def get_hacker_power(uid):
    from core.database import get_farm
    try: from handlers.syndicate.farms import GPUS 
    except: pass 
    farm = await get_farm(uid)
    power = 1000  
    for key, count in farm.items():
        if key.startswith('gpu_') and count > 0:
            try: power += GPUS[int(key.split('_')[1])]['income'] * count
            except: pass
    return power

# ==========================================
# 🏰 КИБЕРВОЙНЫ СИНДИКАТОВ 2.0
# ==========================================
WAR_DURATION = 86400  
WAR_LOOT_PERCENT = 0.15 
WAR_COST_BASE = 50_000_000 

def calculate_nodes(target_clan):
    fw_lvl = target_clan.get('firewall_lvl', 0)
    gateway_hp = (fw_lvl + 1) * 50_000_000
    crypto_cost = int(target_clan.get('balance', 0) * 0.05)
    social_clicks = 10 + (fw_lvl * 2)
    return {"gateway_hp": gateway_hp, "gateway_max": gateway_hp, "crypto_cost": crypto_cost, "crypto_paid": 0, "social_clicks": social_clicks, "social_attackers": []}

@router.message(F.text.lower().startswith(("война клану ", "war to clan ")))
async def cmd_declare_clan_war(message: types.Message, _=None):
    _ = await resolve_chat_translator(message.chat.id, _)
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)
    attacker_clan_id = user_data.get('clan_id', 0)
    if attacker_clan_id == 0: return await message.reply(get_str("cl_war_err_lone", _))

    attacker_clan = await get_clan(attacker_clan_id)
    if user_id not in (attacker_clan['owner_id'], attacker_clan.get('deputy_id', 0)): return await message.reply(get_str("cl_war_err_rights", _))
    if int(time.time()) - attacker_clan.get('last_war_attack', 0) < 172800: return await message.reply(get_str("cl_war_err_cooldown", _))

    parts = message.text.split()
    if not parts[-1].isdigit(): return await message.reply(get_str("cl_war_err_args", _), parse_mode="HTML")

    target_clan_id = int(parts[-1])
    if target_clan_id == attacker_clan_id: return await message.reply(get_str("cl_war_err_self", _))

    target_clan = await get_clan(target_clan_id)
    if not target_clan: return await message.reply(get_str("cl_war_err_not_found", _))
    if target_clan['balance'] < 50_000_000: return await message.reply(get_str("cl_war_err_poor", _))
    if target_clan.get('under_attack_by', 0) != 0: return await message.reply(get_str("cl_war_err_already_sieged", _))

    war_cost = int(WAR_COST_BASE * (1 + target_clan.get('firewall_lvl', 0) * 0.1))
    if attacker_clan['balance'] < war_cost: return await message.reply(get_str("cl_war_err_attacker_poor", _, price=fmt(war_cost)))

    nodes_data = calculate_nodes(target_clan)
    now = int(time.time())
    
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute("UPDATE clans SET balance = balance - $1, last_war_attack = $2 WHERE id = $3", war_cost, now, attacker_clan_id)
        await db.execute("UPDATE clans SET under_attack_by = $1, war_deadline = $2, war_nodes = $3::jsonb WHERE id = $4", attacker_clan_id, now + WAR_DURATION, json.dumps(nodes_data), target_clan_id)

    await message.answer(get_str("cl_war_declared_success", _, at_tag=attacker_clan['tag'], tg_tag=target_clan['tag']), parse_mode="HTML")

# ==========================================
# 📊 ИНТЕРФЕЙС ВОЙНЫ (ВОЕНКОМАТ 3.0)
# ==========================================
@router.message(F.text.lower().in_(["военкомат", "осада", "война", "warroom", "siege", "war"]))
async def cmd_war_interface(message: types.Message, _=None):
    _ = await resolve_chat_translator(message.chat.id, _)
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)
    my_clan_id = user_data.get('clan_id', 0)
    if my_clan_id == 0: return

    pool = await get_db()
    async with pool.acquire() as db:
        target_clan = await db.fetchrow("SELECT * FROM clans WHERE under_attack_by = $1", my_clan_id)
        is_attacker = True
        if not target_clan:
            target_clan = await db.fetchrow("SELECT * FROM clans WHERE id = $1 AND under_attack_by != 0", my_clan_id)
            is_attacker = False

    if not target_clan: return await message.reply(get_str("cl_war_err_none", _))

    now = int(time.time())
    if now > target_clan['war_deadline']: return await message.reply(get_str("cl_war_timeout", _))

    time_left = target_clan['war_deadline'] - now
    nodes = json.loads(target_clan['war_nodes'])
    
    gw_status = get_str("cl_war_node_broken", _) if nodes['gateway_hp'] <= 0 else f"🟢 {fmt(nodes['gateway_hp'])} / {fmt(nodes['gateway_max'])} HP"
    cr_status = get_str("cl_war_node_hacked", _) if nodes['crypto_paid'] >= nodes['crypto_cost'] else f"🟡 {fmt(nodes['crypto_paid'])} / {fmt(nodes['crypto_cost'])} ᴜ"
    
    unique_attackers = len(nodes.get('social_attackers', []))
    soc_status = get_str("cl_war_node_captured", _) if unique_attackers >= nodes['social_clicks'] else f"🔵 {unique_attackers} / {nodes['social_clicks']}"

    role = get_str("cl_war_role_attack", _) if is_attacker else get_str("cl_war_role_defense", _)
    text = get_str("cl_war_interface_body", _, role=role, hours=time_left // 3600, minutes=(time_left % 3600) // 60, gw_status=gw_status, cr_status=cr_status, soc_status=soc_status)

    builder = InlineKeyboardBuilder()
    if is_attacker:
        if nodes['gateway_hp'] > 0: builder.button(text=get_str("cl_btn_war_atk_gw", _), callback_data=f"war_atk_gw_{target_clan['id']}")
        if nodes['crypto_paid'] < nodes['crypto_cost']: builder.button(text=get_str("cl_btn_war_atk_cr", _), callback_data=f"war_atk_cr_{target_clan['id']}")
        if unique_attackers < nodes['social_clicks']: builder.button(text=get_str("cl_btn_war_atk_so", _), callback_data=f"war_atk_so_{target_clan['id']}")
    else:
        if nodes['gateway_hp'] > 0: builder.button(text=get_str("cl_btn_war_def_gw", _), callback_data=f"war_def_gw_{target_clan['id']}")
        if nodes['crypto_paid'] < nodes['crypto_cost']: builder.button(text=get_str("cl_btn_war_def_cr", _), callback_data=f"war_def_cr_{target_clan['id']}")
        
    builder.adjust(1)
    await message.reply(text, reply_markup=builder.as_markup(), parse_mode="HTML")

# ==========================================
# ⚔️ ОБРАБОТКА АТАК И ЗАЩИТ
# ==========================================
@router.callback_query(F.data.startswith("war_"))
async def process_war_actions(callback: types.CallbackQuery, _=None):
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    parts = callback.data.split("_")
    action_type, node_type, target_clan_id = parts[1], parts[2], int(parts[3])
    user_id = callback.from_user.id
    
    user_data = await get_user_data(user_id)
    my_clan_id = user_data.get('clan_id', 0)
    if my_clan_id == 0: return await callback.answer("You are not in a clan core!", show_alert=True)

    pool = await get_db()
    async with pool.acquire() as db: target_clan = await db.fetchrow("SELECT * FROM clans WHERE id = $1", target_clan_id)

    if not target_clan or target_clan['under_attack_by'] == 0: return await callback.answer(get_str("cl_war_act_err_none", _), show_alert=True)
    if action_type == "atk" and my_clan_id != target_clan['under_attack_by']: return await callback.answer(get_str("cl_war_act_err_attacker_side", _), show_alert=True)
    if action_type == "def" and my_clan_id != target_clan_id: return await callback.answer(get_str("cl_war_act_err_defender_side", _), show_alert=True)

    now = int(time.time())
    nodes = json.loads(target_clan['war_nodes'])

    if node_type == "gw":
        if now - user_data.get('last_raid_attack', 0) < 3600: return await callback.answer(get_str("cl_war_act_gw_cooldown", _), show_alert=True)
        base_power = await get_hacker_power(user_id)
        if action_type == "atk":
            damage = int(base_power * random.uniform(1.5, 2.5))
            nodes['gateway_hp'] = max(0, nodes['gateway_hp'] - damage)
            msg = f"💥 -{fmt(damage)} HP!"
        else:
            heal = int(base_power * 2.0)
            nodes['gateway_hp'] = min(nodes['gateway_max'], nodes['gateway_hp'] + heal)
            msg = f"🔧 +{fmt(heal)} HP!"
        await update_user(user_id, last_raid_attack=now)

    elif node_type == "cr":
        cost = 1_000_000
        balance = await get_balance(user_id)
        if balance < cost: return await callback.answer(get_str("cl_war_act_cr_no_money", _, price=fmt(cost)), show_alert=True)
        await add_balance(user_id, -cost)
        if action_type == "atk":
            nodes['crypto_paid'] += cost
            msg = f"💸 +{fmt(cost)} ᴜ!"
        else:
            nodes['crypto_cost'] += cost
            msg = f"💰 +{fmt(cost)} ᴜ!"

    elif node_type == "so":
        if action_type == "def": return await callback.answer(get_str("cl_war_act_so_def_err", _), show_alert=True)
        attackers = nodes.get('social_attackers', [])
        if user_id in attackers: return await callback.answer(get_str("cl_war_act_so_already", _), show_alert=True)
        attackers.append(user_id)
        nodes['social_attackers'] = attackers
        msg = get_str("cl_war_act_so_success", _, current=len(attackers), target=nodes['social_clicks'])

    async with pool.acquire() as db: await db.execute("UPDATE clans SET war_nodes = $1::jsonb WHERE id = $2", json.dumps(nodes), target_clan_id)

    if nodes['gateway_hp'] <= 0 and nodes['crypto_paid'] >= nodes['crypto_cost'] and len(nodes.get('social_attackers', [])) >= nodes['social_clicks']:
        await end_war(target_clan_id, attacker_won=True)
        return await callback.message.edit_text(get_str("cl_war_all_nodes_fallen", _), parse_mode="HTML")

    await callback.answer(msg, show_alert=True)
    await cmd_war_interface(callback.message, _=_)

# ==========================================
# 🏁 ЛОГИКА ЗАВЕРШЕНИЯ ВОЙНЫ
# ==========================================
async def end_war(target_clan_id: int, attacker_won: bool):
    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            target_clan = await db.fetchrow("SELECT * FROM clans WHERE id = $1", target_clan_id)
            if not target_clan or target_clan['under_attack_by'] == 0: return
            if attacker_won:
                loot = int(target_clan['balance'] * WAR_LOOT_PERCENT)
                await db.execute("UPDATE clans SET balance = balance - $1 WHERE id = $2", loot, target_clan_id)
                await db.execute("UPDATE clans SET balance = balance + $1 WHERE id = $2", loot, target_clan['under_attack_by'])
            await db.execute("UPDATE clans SET under_attack_by = 0, current_firewall_hp = 0, war_deadline = 0, war_nodes = '{}'::jsonb WHERE id = $1", target_clan_id)

# ==========================================
# 🤝 СИСТЕМА ПЕРЕМИРИЯ И АДМИН-КОНТРОЛЬ
# ==========================================
ACTIVE_TRUCES = {}

@router.message(F.text.lower().in_(["перемирие", "truce"]))
async def cmd_war_truce(message: types.Message, _=None):
    _ = await resolve_chat_translator(message.chat.id, _)
    if not SYSTEM_MODULES.get("кланы", True): return
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)
    my_clan_id = user_data.get('clan_id', 0)
    if my_clan_id == 0: return

    pool = await get_db()
    async with pool.acquire() as db:
        target_clan = await db.fetchrow("SELECT * FROM clans WHERE under_attack_by = $1", my_clan_id)
        is_attacker = True
        if not target_clan:
            target_clan = await db.fetchrow("SELECT * FROM clans WHERE id = $1 AND under_attack_by != 0", my_clan_id)
            is_attacker = False

    if not target_clan: return await message.reply(get_str("cl_truce_err_none", _))

    my_clan = await get_clan(my_clan_id)
    if user_id not in (my_clan['owner_id'], my_clan.get('deputy_id', 0)): return await message.reply(get_str("cl_truce_err_rights", _))

    war_id = target_clan['id']
    enemy_clan_id = target_clan['under_attack_by'] if not is_attacker else target_clan['id']

    if ACTIVE_TRUCES.get(war_id) == enemy_clan_id:
        async with pool.acquire() as db:
            await db.execute("UPDATE clans SET under_attack_by = 0, war_deadline = 0, war_nodes = '{}'::jsonb WHERE id = $1", war_id)
        ACTIVE_TRUCES.pop(war_id, None)
        return await message.reply(get_str("cl_truce_success_signed", _), parse_mode="HTML")
    
    ACTIVE_TRUCES[war_id] = my_clan_id
    await message.reply(get_str("cl_truce_offered_success", _), parse_mode="HTML")

    enemy_clan = await get_clan(enemy_clan_id)
    async with pool.acquire() as db: boss_lang = await db.fetchval("SELECT lang FROM users WHERE user_id = $1", enemy_clan['owner_id']) or "ru"
    _boss = get_translator(boss_lang)
    try:
        await message.bot.send_message(chat_id=enemy_clan['owner_id'], text=get_str("cl_truce_msg_to_enemy_boss", _boss, tag=my_clan['tag']), parse_mode="HTML")
    except: pass

@router.message(F.text.lower().startswith(("завершить войну ", "end war ")) & (F.from_user.id == 1412940726))
async def cmd_admin_end_war(message: types.Message, _=None):
    parts = message.text.split()
    if len(parts) < 3: return await message.reply(get_str("cl_admin_war_err_args", _), parse_mode="HTML")
    try: target_clan_id = int(parts[-1])
    except ValueError: return await message.reply(get_str("cl_admin_war_err_nan", _))

    pool = await get_db()
    async with pool.acquire() as db:
        check = await db.fetchrow("SELECT under_attack_by FROM clans WHERE id = $1", target_clan_id)
        if not check or check['under_attack_by'] == 0: return await message.reply(get_str("cl_admin_war_err_not_sieged", _))
        await db.execute("UPDATE clans SET under_attack_by = 0, war_deadline = 0, war_nodes = '{}'::jsonb WHERE id = $1", target_clan_id)
    
    ACTIVE_TRUCES.pop(target_clan_id, None)
    await message.reply(get_str("cl_admin_war_success", _, id=target_clan_id), parse_mode="HTML")

@router.message(F.text.lower().startswith(("удалить клан ", "delete clan ")) & (F.from_user.id == 1412940726))
async def cmd_admin_delete_clan(message: types.Message, _=None):
    parts = message.text.split()
    if len(parts) < 3 or not parts[-1].isdigit(): return await message.reply(get_str("cl_admin_del_err_args", _), parse_mode="HTML")
    target_clan_id = int(parts[-1])
    
    pool = await get_db()
    async with pool.acquire() as db:
        clan = await db.fetchrow("SELECT * FROM clans WHERE id = $1", target_clan_id)
        if not clan: return await message.reply(get_str("cl_admin_del_err_not_found", _))
        async with db.transaction():
            await db.execute("UPDATE users SET clan_id = 0, clan_donated = 0 WHERE clan_id = $1", target_clan_id)
            await db.execute("UPDATE clans SET under_attack_by = 0, war_deadline = 0, war_nodes = '{}'::jsonb WHERE under_attack_by = $1", target_clan_id)
            await db.execute("DELETE FROM clans WHERE id = $1", target_clan_id)
            
    ACTIVE_TRUCES.pop(target_clan_id, None)
    keys_to_delete = [k for k, v in ACTIVE_TRUCES.items() if v == target_clan_id]
    for k in keys_to_delete: ACTIVE_TRUCES.pop(k, None)
            
    await message.reply(get_str("cl_admin_del_success", _, tag=clan['tag'], name=clan['name']), parse_mode="HTML")

# ==========================================
# 🔪 ДУЭЛИ (Игрок vs Игрок)
# ==========================================
DUEL_COOLDOWN_HOURS = 1  
MIN_DUEL_BALANCE = 50_000 

@router.message(F.text.lower().startswith(("напасть ", "взломать ", "attack ", "hack ")))
async def cmd_internal_war(message: types.Message, _=None):
    _ = await resolve_chat_translator(message.chat.id, _)
    if not SYSTEM_MODULES.get("кланы", True): return
    
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)
    clan_id = user_data.get('clan_id', 0)
    if clan_id == 0: return await message.reply(get_str("cl_duel_err_lone", _))

    target_id = None
    if message.reply_to_message: target_id = message.reply_to_message.from_user.id
    else:
        parts = message.text.split()
        if len(parts) > 1: target_id = await resolve_user_id(parts[1])

    if not target_id: return await message.reply(get_str("cl_duel_err_args", _), parse_mode="HTML")
    if target_id == user_id: return await message.reply(get_str("cl_duel_err_self", _))

    target_data = await get_user_data(target_id)
    if target_data.get('clan_id') != clan_id: return await message.reply(get_str("cl_duel_err_not_same_clan", _))

    clan = await get_clan(clan_id)
    if target_id == clan['owner_id']: return await message.reply(get_str("cl_duel_err_boss_immune", _))
    if await statuses.has_active_status(target_id, 4): return await message.reply(get_str("cl_duel_err_arch_immune", _), parse_mode="HTML")
    if await statuses.has_active_status(target_id, 777): return await message.reply(get_str("cl_duel_err_sov_immune", _), parse_mode="HTML")

    attacker_bal = await get_balance(user_id)
    defender_bal = await get_balance(target_id)

    if attacker_bal < MIN_DUEL_BALANCE: return await message.reply(get_str("cl_duel_err_atk_poor", _, price=fmt(MIN_DUEL_BALANCE)), parse_mode="HTML")
    if defender_bal < MIN_DUEL_BALANCE: return await message.reply(get_str("cl_duel_err_def_poor", _))
    if attacker_bal > defender_bal * 5: return await message.reply(get_str("cl_duel_err_diff_limit", _), parse_mode="HTML")

    current_time = int(time.time())
    time_passed = current_time - user_data.get('last_duel', 0)
    if user_id != ADMIN_ID and time_passed < 3600:
        return await message.reply(get_str("cl_duel_err_cooldown", _, minutes=int((3600 - time_passed) // 60)), parse_mode="HTML")

    await update_user(user_id, last_duel=current_time)
    win_chance = max(0.20, min(0.65, await get_hacker_power(user_id) / (await get_hacker_power(user_id) + await get_hacker_power(target_id))))

    try:
        t_user = await message.bot.get_chat(target_id)
        t_name = t_user.first_name
    except: t_name = "Соклановец"

    roll = random.random()
    if roll < win_chance:
        if random.random() < 0.15: 
            percent = random.uniform(0.20, 0.30)
            loot = int(defender_bal * percent)
            await add_balance(target_id, -loot)
            await add_balance(user_id, loot)
            await message.reply(get_str("cl_duel_res_crit_win", _, name=t_name, chance=int(win_chance * 100), payout=fmt(loot), percent=int(percent*100)), parse_mode="HTML")
        else:
            percent = random.uniform(0.05, 0.15)
            loot = int(defender_bal * percent)
            await add_balance(target_id, -loot)
            await add_balance(user_id, loot)
            await message.reply(get_str("cl_duel_res_normal_win", _, name=t_name, chance=int(win_chance * 100), payout=fmt(loot), percent=int(percent*100)), parse_mode="HTML")
    else:
        if random.random() < 0.15:
            await message.reply(get_str("cl_duel_res_draw", _, name=t_name), parse_mode="HTML")
        elif random.random() < 0.10:
            percent = random.uniform(0.20, 0.30)
            penalty = int(attacker_bal * percent)
            await add_balance(user_id, -penalty)
            await add_balance(target_id, penalty)
            await message.reply(get_str("cl_duel_res_honeypot", _, name=t_name, chance=int(win_chance * 100), penalty=fmt(penalty), percent=int(percent*100)), parse_mode="HTML")
        else:
            percent = random.uniform(0.05, 0.15)
            penalty = int(attacker_bal * percent)
            await add_balance(user_id, -penalty)
            await add_balance(target_id, penalty)
            await message.reply(get_str("cl_duel_res_fail", _, name=t_name, chance=int(win_chance * 100), penalty=fmt(penalty), percent=int(percent*100)), parse_mode="HTML")