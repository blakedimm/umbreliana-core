import time
import asyncio
import json
import logging
import os
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.database import get_db, get_balance, add_balance

router = Router()

# ==========================================
# 🛡 ФЕЙЛСЕЙФ СИСТЕМА: РЕЗЕРВНАЯ ЛОКАЛИЗАЦИЯ ДЛЯ ОНЛАЙНА
# ==========================================
FALLBACK_STRINGS = {}
try:
    if os.path.exists("locales/ru.json"):
        with open("locales/ru.json", "r", encoding="utf-8") as f:
            FALLBACK_STRINGS = json.load(f)
except Exception as e:
    logging.error(f"Критическая ошибка чтения резервного файла титулов ru.json: {e}")

def local_fallback(key: str, **kwargs) -> str:
    text = FALLBACK_STRINGS.get(key, key)
    if kwargs:
        try: return text.format(**kwargs)
        except: pass
    return text

# ==========================================
# ⚙️ НАСТРОЙКИ МАГАЗИНА ТИТУЛОВ
# ==========================================
BUY_ALL_PRICE = 8_000_000_000
ARCHITECT_PRICE = 3_000_000_000
ARCHITECT_EMOJI = "🌌"

PRESET_TITLES = {
    "lord": {"name_key": "title_lord_name", "desc_key": "title_lord_desc", "perks_key": "title_lord_perks", "price": 1_000_000_000, "emoji": "👑"},
    "shadow": {"name_key": "title_shadow_name", "desc_key": "title_shadow_desc", "perks_key": "title_shadow_perks", "price": 1_500_000_000, "emoji": "🌑"},
    "monopoly": {"name_key": "title_monopoly_name", "desc_key": "title_monopoly_desc", "perks_key": "title_monopoly_perks", "price": 2_000_000_000, "emoji": "🎩"},
    "cyber": {"name_key": "title_cyber_name", "desc_key": "title_cyber_desc", "perks_key": "title_cyber_perks", "price": 2_500_000_000, "emoji": "👹"}
}

fmt = lambda x: f"{int(x):,}".replace(',', ' ')

class TitleInput(StatesGroup):
    waiting_for_text = State()

# ==========================================
# 🛠 ГЕНЕРАТОР ГЛАВНОГО МЕНЮ МАГАЗИНА
# ==========================================
async def build_shop_menu(user_id, _):
    balance = await get_balance(user_id)
    pool = await get_db()
    async with pool.acquire() as db:
        owned_rows = await db.fetch("SELECT title_id, custom_text FROM user_titles WHERE user_id = $1", user_id)
        owned_ids = {r['title_id']: r['custom_text'] for r in owned_rows}

    text = _("tt_shop_title", balance=fmt(balance))
    kb = InlineKeyboardBuilder()
    
    for t_id, data in PRESET_TITLES.items():
        if t_id in owned_ids:
            kb.button(text=_("tt_btn_bought", emoji=data['emoji'], name=_(data['name_key'])), callback_data="dummy")
        else:
            kb.button(text=f"{data['emoji']} " + _(data['name_key']), callback_data=f"titleinfo_{t_id}")
            
    if "architect" in owned_ids:
        kb.button(text=_("tt_btn_custom_change", name=owned_ids['architect']), callback_data="titleinfo_architect")
    else:
        kb.button(text=f"{ARCHITECT_EMOJI} " + _("title_architect_name_default"), callback_data="titleinfo_architect")
        
    if len(owned_ids) < len(PRESET_TITLES) + 1:
        kb.button(text=_("tt_btn_buy_all"), callback_data="titleinfo_all")
    
    kb.adjust(1)
    return text, kb.as_markup()

# ==========================================
# 🛒 ВХОД В МАГАЗИН
# ==========================================
@router.message(lambda msg: msg.text and msg.text.lower().strip() in ["титулы", "титул", "магазин титулов", "titles", "title", "title shop"])
async def shop_titles_menu(message: types.Message, state: FSMContext, _ = None):
    if not _: _ = local_fallback
    await state.clear()
    text, markup = await build_shop_menu(message.from_user.id, _)
    await message.reply(text, reply_markup=markup, parse_mode="HTML")

# ==========================================
# 📖 КАРТОЧКА ТОВАРА (ОПИСАНИЕ И ПОДТВЕРЖДЕНИЕ)
# ==========================================
@router.callback_query(F.data.startswith("titleinfo_"))
async def show_title_info(callback: types.CallbackQuery, _ = None):
    if not _: _ = local_fallback
    t_id = callback.data.split("_")[1]
    
    if t_id == "all":
        text = _("tt_info_all", price=fmt(BUY_ALL_PRICE))
    elif t_id == "architect":
        text = _("tt_info_preset", emoji=ARCHITECT_EMOJI, name=_("title_architect_name_default"), desc=_("title_architect_desc"), perks=_("title_architect_perks"), price=fmt(ARCHITECT_PRICE))
    elif t_id in PRESET_TITLES:
        data = PRESET_TITLES[t_id]
        text = _("tt_info_preset", emoji=data['emoji'], name=_(data['name_key']), desc=_(data['desc_key']), perks=_(data['perks_key']), price=fmt(data['price']))
    else:
        return await callback.answer(_("tt_err_item"), show_alert=True)

    kb = InlineKeyboardBuilder()
    kb.button(text=_("tt_btn_confirm"), callback_data=f"buytitle_{t_id}")
    kb.button(text=_("tt_btn_back"), callback_data="titles_back")
    kb.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "titles_back")
async def back_to_shop(callback: types.CallbackQuery, _ = None):
    if not _: _ = local_fallback
    text, markup = await build_shop_menu(callback.from_user.id, _)
    await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")

# ==========================================
# 💳 ЛОГИКА ПОКУПКИ (ПОСЛЕ ПОДТВЕРЖДЕНИЯ)
# ==========================================
@router.callback_query(F.data.startswith("buytitle_"))
async def process_buy(callback: types.CallbackQuery, state: FSMContext, _ = None):
    if not _: _ = local_fallback
    t_id = callback.data.split("_")[1]
    user_id = callback.from_user.id
    balance = await get_balance(user_id)
    pool = await get_db()

    if t_id == "all":
        if balance < BUY_ALL_PRICE:
            return await callback.answer(_("tt_buy_err_money"), show_alert=True)
            
        await add_balance(user_id, -BUY_ALL_PRICE)
        async with pool.acquire() as db:
            for preset_id in PRESET_TITLES.keys():
                await db.execute(
                    "INSERT INTO user_titles (user_id, title_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", 
                    user_id, preset_id
                )
        return await callback.message.edit_text(_("tt_buy_all_success"), parse_mode="HTML")

    if t_id == "architect":
        async with pool.acquire() as db:
            has_architect = await db.fetchval("SELECT 1 FROM user_titles WHERE user_id = $1 AND title_id = 'architect'", user_id)
            
        if not has_architect and balance < ARCHITECT_PRICE:
            return await callback.answer(_("tt_buy_err_money"), show_alert=True)
            
        await state.set_state(TitleInput.waiting_for_text)
        action_text = _("tt_custom_action_change") if has_architect else _("tt_custom_action_buy")
        
        return await callback.message.edit_text(
            _("tt_custom_prompt", action=action_text),
            parse_mode="HTML"
        )

    if t_id in PRESET_TITLES:
        price = PRESET_TITLES[t_id]['price']
        if balance < price:
            return await callback.answer(_("tt_buy_err_money"), show_alert=True)
            
        await add_balance(user_id, -price)
        async with pool.acquire() as db:
            await db.execute("INSERT INTO user_titles (user_id, title_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", user_id, t_id)
            
        await callback.message.edit_text(_("tt_buy_preset_success", name=_(PRESET_TITLES[t_id]['name_key'])), parse_mode="HTML")

# ==========================================
# ✍️ ВВОД КАСТОМНОГО НАЗВАНИЯ
# ==========================================
@router.message(TitleInput.waiting_for_text)
async def capture_custom_title(message: types.Message, state: FSMContext, _ = None):
    if not _: _ = local_fallback
    text = message.text.strip()
    
    if text.lower() in ["отмена", "cancel"]:
        await state.clear()
        return await message.reply(_("tt_custom_cancel_msg"))
        
    if len(text) > 20:
        return await message.reply(_("tt_custom_err_len"))
        
    safe_text = text.replace("<", "").replace(">", "")
    user_id = message.from_user.id
    
    pool = await get_db()
    async with pool.acquire() as db:
        is_taken = await db.fetchval(
            "SELECT user_id FROM user_titles WHERE LOWER(custom_text) = $1 AND title_id = 'architect' AND user_id != $2", 
            safe_text.lower(), user_id
        )
        if is_taken:
            return await message.reply(_("tt_custom_err_taken"), parse_mode="HTML")

        has_architect = await db.fetchval("SELECT 1 FROM user_titles WHERE user_id = $1 AND title_id = 'architect'", user_id)
        
        if not has_architect:
            balance = await db.fetchval("SELECT balance FROM users WHERE user_id = $1", user_id)
            if balance < ARCHITECT_PRICE:
                await state.clear()
                return await message.reply(_("tt_custom_err_money_belated"))
            await db.execute("UPDATE users SET balance = balance - $1 WHERE user_id = $2", ARCHITECT_PRICE, user_id)
        
        await db.execute(
            "INSERT INTO user_titles (user_id, title_id, custom_text) VALUES ($1, 'architect', $2) "
            "ON CONFLICT(user_id, title_id) DO UPDATE SET custom_text = EXCLUDED.custom_text", 
            user_id, safe_text
        )
        
    await state.clear()
    await message.reply(_("tt_custom_success", text=safe_text), parse_mode="HTML")

# ==========================================
# 🎒 ИНВЕНТАРЬ (КОМАНДА: МОИ ТИТУЛЫ)
# ==========================================
@router.message(lambda msg: msg.text and msg.text.lower().strip() in ["мои титулы", "мой титул", "my titles", "my title"])
async def my_titles_menu(message: types.Message, _ = None):
    if not _: _ = local_fallback
    user_id = message.from_user.id
    
    pool = await get_db()
    async with pool.acquire() as db:
        active_title = await db.fetchval("SELECT title FROM users WHERE user_id = $1", user_id)
        owned_rows = await db.fetch("SELECT title_id, custom_text FROM user_titles WHERE user_id = $1", user_id)

    if not owned_rows:
        return await message.reply(_("tt_inv_empty"), parse_mode="HTML")

    active_display = active_title if active_title else _("tt_inv_not_equipped")
    text = _("tt_inv_title", active=active_display)

    kb = InlineKeyboardBuilder()
    for row in owned_rows:
        t_id = row['title_id']
        if t_id == 'architect':
            display_name = f"{ARCHITECT_EMOJI} {row['custom_text']}"
        else:
            display_name = f"{PRESET_TITLES[t_id]['emoji']} {_(PRESET_TITLES[t_id]['name_key'])}"
            
        equip_data = f"equip_{t_id}"
        if active_title == display_name:
            display_name = _("tt_inv_equipped_row", name=display_name)
            
        kb.button(text=display_name, callback_data=equip_data)

    if active_title:
        kb.button(text=_("tt_inv_btn_remove"), callback_data="equip_none")

    kb.adjust(1)
    await message.reply(text, reply_markup=kb.as_markup(), parse_mode="HTML")

# ==========================================
# 🔄 НАДЕВАЕМ / СНИМАЕМ ТИТУЛ
# ==========================================
@router.callback_query(F.data.startswith("equip_"))
async def process_equip(callback: types.CallbackQuery, _ = None):
    if not _: _ = local_fallback
    action = callback.data.replace("equip_", "")
    user_id = callback.from_user.id
    
    pool = await get_db()
    new_title = None
    
    if action == "none":
        pass 
    elif action == "architect":
        async with pool.acquire() as db:
            custom_text = await db.fetchval("SELECT custom_text FROM user_titles WHERE user_id = $1 AND title_id = 'architect'", user_id)
            if custom_text:
                new_title = f"{ARCHITECT_EMOJI} {custom_text}"
    elif action in PRESET_TITLES:
        new_title = f"{PRESET_TITLES[action]['emoji']} {_(PRESET_TITLES[action]['name_key'])}"

    async with pool.acquire() as db:
        await db.execute("UPDATE users SET title = $1 WHERE user_id = $2", new_title, user_id)

    status = _("tt_equip_success", name=new_title) if new_title else _("tt_equip_remove")
    await callback.answer("Success!", show_alert=False)
    await callback.message.edit_text(f"✅ {status}", parse_mode="HTML")

# ==========================================
# 🔊 ЭЛИТНОЕ ВЕЩАНИЕ (РУПОР)
# ==========================================
@router.message(lambda msg: msg.text and msg.text.lower().strip().startswith(("вещание", "broadcast")))
async def title_broadcast(message: types.Message, _ = None):
    if not _: _ = local_fallback
    user_id = message.from_user.id
    
    # 🔥 Универсальный сплит команды от тела сообщения для EN/RU
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply(_("tt_bc_err_empty"), parse_mode="HTML")
        
    text_to_broadcast = parts[1].strip()

    if len(text_to_broadcast) > 500:
        return await message.reply(_("tt_bc_err_len"))

    pool = await get_db()
    async with pool.acquire() as db:
        has_architect = await db.fetchval("SELECT custom_text FROM user_titles WHERE user_id = $1 AND title_id = 'architect' LIMIT 1", user_id)
        if not has_architect:
            return await message.reply(_("tt_bc_err_denied"), parse_mode="HTML")

        last_cast = await db.fetchval("SELECT last_broadcast FROM users WHERE user_id = $1", user_id) or 0
        current_time = int(time.time())
        
        if current_time - last_cast < 86400:
            hours_left = 24 - ((current_time - last_cast) // 3600)
            return await message.reply(_("tt_bc_err_cooldown", hours=hours_left), parse_mode="HTML")

        target_chats = await db.fetch("""
            SELECT chat_id FROM chat_members 
            WHERE chat_id IS NOT NULL 
            GROUP BY chat_id HAVING COUNT(user_id) >= 20
        """)

        if not target_chats:
            return await message.reply(_("tt_bc_err_no_chats"))

        await db.execute("UPDATE users SET last_broadcast = $1 WHERE user_id = $2", current_time, user_id)

    success_count = 0
    name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name

    broadcast_msg = _("tt_bc_template", title=has_architect, name=name, text=text_to_broadcast)
    wait_msg = await message.reply(_("tt_bc_connecting"), parse_mode="HTML")
    
    for row in target_chats:
        try:
            await message.bot.send_message(row['chat_id'], broadcast_msg, parse_mode="HTML")
            success_count += 1
            await asyncio.sleep(0.1)
        except Exception:
            pass 

    await wait_msg.edit_text(_("tt_bc_success", count=success_count), parse_mode="HTML")