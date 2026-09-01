import io
import os
import time
import logging
import asyncio
import random
import json
from datetime import date

from aiogram import Router, F, types
from aiogram.filters import CommandStart, CommandObject, Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, FSInputFile, BufferedInputFile, InputMediaPhoto
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext

from core.database import get_db, get_balance, add_balance, get_last_bonus, get_user_data, resolve_user_id
from handlers.economy.bonus import get_cached_user_data
from handlers.users.statuses import has_active_status, get_active_statuses, STATUSES

# 🔥 Подключаем наш HTML-дизайн движок
from handlers.users.design_generator import generate_html_profile

router = Router()
ADMIN_ID = int(os.getenv("ADMIN_ID", 1412940726))
MODERATORS = [int(i.strip()) for i in os.getenv("MODERATORS", "").split(",") if i.strip()]

def fmt(num):
    return f"{int(num):,}".replace(",", " ")

# ==========================================
# 🛡 ФЕЙЛСЕЙФ СИСТЕМА: РЕЗЕРВНАЯ ЛОКАЛИЗАЦИЯ
# ==========================================
FALLBACK_STRINGS = {}
try:
    if os.path.exists("locales/ru.json"):
        with open("locales/ru.json", "r", encoding="utf-8") as f:
            FALLBACK_STRINGS = json.load(f)
except Exception as e:
    logging.error(f"Критическая ошибка чтения резервного файла ru.json: {e}")

def local_fallback(key: str, **kwargs) -> str:
    text = FALLBACK_STRINGS.get(key, key)
    if kwargs:
        try: return text.format(**kwargs)
        except: pass
    return text

# ==========================================
# 🛑 ЛС-ФИЛЬТРЫ И НАСТРОЙКИ (УЛУЧШЕННЫЙ БЕЛЫЙ СПИСОК КОМАНД)
# ==========================================
EXACT_PM_COMMANDS = {
    "бонус", "баланс", "на счету", "б", "профиль", "ферма", "фарма", "bonus", "balance", "bal", "profile", "farm",
    "собрать", "банк", "📚 инструктаж", "инструктаж", "кланы", "донат", "инвентарь", "тестирование", "collect", "bank", "briefing", "clans", "donate",
    "👤 профиль", "🎁 бонус", "🏭 ферма", "🏦 банк", "👤 profile", "🎁 bonus", "🏭 farm", "🏦 bank",
    "✦ профиль", "✦ profile", "⚡ бонус", "⚡ bonus",
    "империя", "клан", "clan", "clans", "🏴‍☠️ кланы", "🏴‍☠️ clans", "донат", "donate", "💎 донат", "💎 donate",
    "квесты", "задания", "миссии", "📜 квесты", "quests", "missions", "📜 quests",
    "реферал", "рефералы", "🤝 реферал", "referral", "refs", "🤝 referral", "🌐 чаты", "🌐 channels", "🌐 chats", "chats", "channels",
    "титулы", "титул", "магазин титулов", "мои титулы", "мой титул", "titles", "title"
}
PREFIX_PM_COMMANDS = (
    "/start", "топ", "мой долг", "чек", "ник", "top", "debt", "check", "nick",
    "логи", "админ", "п ", "взять в долг", "вернуть", "общий статус", "сектор", "logs", "admin", "borrow", "repay"
)
EXTRA_PM_EXCEPTIONS = {"кто крыса", "инфо ивент", "ивент2", "раунд2", "итог2", "раунд", "итог", "event"}

# ==========================================
# 🛡 УМНЫЙ ОТВЕТ В ЛС
# ==========================================
async def is_garbage_in_pm(message: types.Message, state: FSMContext) -> bool:
    if message.from_user.id == ADMIN_ID: return False 
    if await state.get_state() is not None: return False 
    
    if message.successful_payment is not None: 
        return False
        
    if not message.text: return True
    
    text = message.text.lower().strip()
    if text in EXACT_PM_COMMANDS or text.startswith(PREFIX_PM_COMMANDS) or text in EXTRA_PM_EXCEPTIONS:
        return False 
        
    return True

@router.message(F.chat.type == "private", is_garbage_in_pm)
async def pm_garbage_handler(message: types.Message, _ = None):
    if not _: _ = local_fallback
    responses = [ _("pm_garbage_1"), _("pm_garbage_2") ]
    await message.reply(random.choice(responses), parse_mode="HTML")

# ==========================================
# 4. ГЛАВНОЕ МЕНЮ И СТАРТ
# ==========================================
def get_main_reply_keyboard(user_id: int, _):
    keyboard = [
        [KeyboardButton(text=_("main_kb_profile")), KeyboardButton(text=_("main_kb_bonus"))],
        [KeyboardButton(text=_("main_kb_quests")), KeyboardButton(text=_("main_kb_farm"))], 
        [KeyboardButton(text=_("main_kb_bank")), KeyboardButton(text=_("main_kb_clans"))],
        [KeyboardButton(text=_("main_kb_donate")), KeyboardButton(text=_("main_kb_instruct"))], 
        [KeyboardButton(text=_("main_kb_chats")), KeyboardButton(text=_("main_kb_ref"))]
    ]
    
    if user_id == ADMIN_ID:
        keyboard.insert(0, [KeyboardButton(text=_("main_kb_admin_stats")), KeyboardButton(text=_("main_kb_restart"))])
        
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True, 
        input_field_placeholder=_("main_kb_placeholder") 
    )

@router.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject, _ = None):
    if not _: _ = local_fallback

    if command.args == "exam":
        from handlers.users.rating_system import cmd_exam_start
        return await cmd_exam_start(message)
    
    if command.args and command.args.startswith("ref_"):
        try:
            inviter_id = int(command.args.split("_")[1])
            user_id = message.from_user.id
            if inviter_id != user_id:
                pool = await get_db()
                async with pool.acquire() as db:
                    exists = await db.fetchval("SELECT 1 FROM users WHERE user_id = $1", user_id)
                    if not exists:
                        await add_balance(inviter_id, 50000, is_income=True)
                        await db.execute("UPDATE users SET refs_earned = COALESCE(refs_earned, 0) + 50000 WHERE user_id = $1", inviter_id)
                        try:
                            await message.bot.send_message(
                                inviter_id, 
                                _("ref_new_agent", user_id=user_id, name=message.from_user.first_name), 
                                parse_mode="HTML"
                            )
                        except: pass
                        current_time = int(time.time())
                        await db.execute("""
                            INSERT INTO users (user_id, balance, nickname, first_seen, last_seen, referrer_id)
                            VALUES ($1, $2, $3, $4, $5, $6)
                            ON CONFLICT(user_id) DO NOTHING
                        """, user_id, 25000, message.from_user.first_name, current_time, current_time, inviter_id)
        except Exception as e:
            logging.error(f"Ошибка обработки реферала: {e}")

    user_data = await get_user_data(message.from_user.id)
    if not user_data or not user_data.get('tutorial_passed'):
        tut_kb = InlineKeyboardBuilder()
        tut_kb.row(types.InlineKeyboardButton(text=_("btn_start_tut"), callback_data="tut_start"))
        tut_kb.row(types.InlineKeyboardButton(text=_("btn_skip_tut"), callback_data="tut_skip"))
        return await message.answer(_("welcome_tutorial"), reply_markup=tut_kb.as_markup(), parse_mode="HTML")

    if message.chat.type == "private":
        bot_info = await message.bot.get_me()
        inline_kb = InlineKeyboardBuilder()
        inline_kb.row(types.InlineKeyboardButton(text=_("btn_add_to_group"), url=f"https://t.me/{bot_info.username}?startgroup&admin=change_info+post_messages+edit_messages+delete_messages+restrict_members+invite_users+pin_messages+promote_members+manage_video_chats+manage_topics+manage_chat"))
        inline_kb.row(
            types.InlineKeyboardButton(text=_("btn_user_agreement"), url="https://graph.org/Polzovatelskoe-soglashenie-Umbreliana-04-08"),
            types.InlineKeyboardButton(text=_("btn_privacy_policy"), url="https://graph.org/Politika-konfidencialnosti-Umbreliana-04-08")
        )
        await message.answer(_("welcome_private"), reply_markup=get_main_reply_keyboard(message.from_user.id, _), parse_mode="HTML", disable_web_page_preview=True)
        await message.answer(_("nav_links_title"), reply_markup=inline_kb.as_markup(), parse_mode="HTML")
    else:
        await message.reply(_("welcome_group"))

# ==========================================
# 👤 ПРОФИЛЬ (БУЛЛЕТПРУФ МУЛЬТИЯЗЫЧНЫЕ ФИЛЬТРЫ)
# ==========================================
@router.message(F.text.lower().startswith(("профиль", "profile")) | F.text.lower().in_(["👤 профиль", "👤 profile", "✦ профиль", "✦ profile"]))
async def widget_profile(message: types.Message, _ = None):
    if not _: _ = local_fallback
    target_id, target_name = message.from_user.id, message.from_user.first_name
    args = message.text.split()
    
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        target_name = message.reply_to_message.from_user.first_name
    elif len(args) > 1 and args[0].lower() in ["профиль", "profile"]:
        raw_target = args[1].replace('@', '')
        if raw_target.isdigit():
            target_id, target_name = int(raw_target), f"Agent {raw_target}" 
        else:
            pool = await get_db()
            async with pool.acquire() as db:
                found_id = await db.fetchval("SELECT user_id FROM users WHERE telegram_username ILIKE $1", raw_target)
            if found_id: target_id = found_id
            else: target_id = await resolve_user_id(raw_target)
            if not target_id: return await message.reply(_("player_not_found", target=raw_target), parse_mode="HTML")
            target_name = f"@{raw_target}"

    if target_id == message.bot.id:
        return await message.reply(_("connor_everywhere"))

    balance = await get_balance(target_id)
    fmt_balance = f"{balance:,}".replace(',', ' ')
    
    pool = await get_db()
    async with pool.acquire() as db:
        user_row = await db.fetchrow("SELECT title, clan_id, gold_balance FROM users WHERE user_id = $1", target_id)
        umc_balance = await db.fetchval("SELECT umc_balance FROM farms WHERE user_id = $1", target_id) or 0
        
        if user_row:
            active_title = user_row['title']
            clan_id = user_row['clan_id'] or 0
            gold_bal = user_row['gold_balance'] or 0
        else:
            active_title, clan_id, gold_bal = None, 0, 0
            
        rating = await db.fetchval("SELECT rating_points FROM user_rating WHERE user_id = $1", target_id) or 2500
        
        clan_name = "ОДИНОЧКА"
        if clan_id > 0:
            clan_name = await db.fetchval("SELECT name FROM clans WHERE id = $1", clan_id) or "ОДИНОЧКА"
            
        has_any_title = await db.fetchval("SELECT 1 FROM user_titles WHERE user_id = $1 LIMIT 1", target_id)

    fmt_gold = f"{int(gold_bal):,}".replace(',', ' ')
    fmt_umc = f"{int(umc_balance):,}".replace(',', ' ')
    active_statuses = await get_active_statuses(target_id)
    
    title_text, header_line = _("role_citizen"), _("header_dossier")

    is_creator = (target_id == ADMIN_ID)
    is_mod = (target_id in MODERATORS) 

    final_title_for_img = active_title

    if is_creator:
        final_title_for_img = "CREATOR" if not active_title else active_title
        title_text, header_line, display_name = _("role_creator"), _("header_creator"), f"👑 <code>[CREATOR]</code> <b>{target_name}</b>"
    elif is_mod:
        final_title_for_img = "ADMIN" if not active_title else active_title
        title_text, header_line, display_name = _("role_admin"), _("header_admin"), f"🛡 <code>[ADMIN]</code> <b>{target_name}</b>"
    else:
        if active_statuses:
            highest_status_id = max(active_statuses.keys())
            status_keys = {1: "fm_license_tech", 2: "fm_license_magnate", 3: "fm_license_fortune", 4: "fm_license_architect", 777: "fm_license_sovereign"}
            if highest_status_id in status_keys:
                title_text = _(status_keys[highest_status_id])
            if highest_status_id == 4: header_line = _("header_architect")
            elif highest_status_id == 5 or highest_status_id == 777: header_line = _("header_sovereign")
            
        if active_title:
            display_name = f"<b>[{active_title}]</b> {target_name}"
        else:
            display_name = f"<b>{target_name}</b>"

    licenses_list = []
    licenses_text = _("lic_title_active") if active_statuses else _("lic_title_none")
    
    if active_statuses:
        current_time = int(time.time())
        status_keys = {1: "fm_license_tech", 2: "fm_license_magnate", 3: "fm_license_fortune", 4: "fm_license_architect", 777: "fm_license_sovereign"}
        for s_id, expire in sorted(active_statuses.items()):
            # 🔥 ИСПРАВЛЕНИЕ: Жёстко завязали имена на l10n-ключи, полностью удалив KeyError
            s_name = _(status_keys[s_id]) if s_id in status_keys else _("role_sovere")
            time_left = expire - current_time
            days = time_left // 86400
            
            if days > 10000:
                licenses_list.append(_("lic_forever", name=s_name))
                licenses_text += f" ├ " + _("lic_forever", name=s_name) + "\n"
            else:
                licenses_list.append(_("lic_days", name=s_name, days=days, hours=(time_left % 86400) // 3600))
                licenses_text += f" ├ " + _("lic_days", name=s_name, days=days, hours=(time_left % 86400) // 3600) + "\n"

    footer = _("footer_owner") if (target_id == message.from_user.id) else _("footer_system")

    profile_text = _("profile_text_fallback", header=header_line, name=display_name, user_id=target_id, role=title_text, fiat=fmt_balance, gold=fmt_gold, umc=fmt_umc, licenses=licenses_text, footer=footer)

    profile_kb = InlineKeyboardBuilder()
    profile_kb.button(text=_("btn_my_tasks"), callback_data="quests_menu_daily")
    profile_kb.button(text=_("btn_ref_network"), callback_data="referral_menu")
    profile_kb.adjust(1)
    
    show_html = has_any_title or is_creator or is_mod or (active_statuses and (5 in active_statuses or 777 in active_statuses))

    if show_html:
        short_caption = _("html_caption_success", name=display_name)

        filename = await asyncio.to_thread(
            generate_html_profile, 
            user_id=target_id, 
            username=target_name, 
            title=final_title_for_img, 
            balance=balance, 
            gold_balance=gold_bal, 
            umc_balance=umc_balance,
            rating=rating, 
            clan_name=clan_name, 
            role_header=title_text, 
            licenses=licenses_list
        )
        
        if os.path.exists(filename) and os.path.getsize(filename) > 0:
            with open(filename, "rb") as f:
                photo_bytes = f.read()
                
            photo = BufferedInputFile(photo_bytes, filename=filename)
            os.remove(filename) 
            
            await message.reply_photo(
                photo=photo, 
                caption=short_caption, 
                parse_mode="HTML", 
                reply_markup=profile_kb.as_markup()
            )
        else:
            await message.reply(_("db_error_dossier"))
    else:
        await message.reply(profile_text, parse_mode="HTML", reply_markup=profile_kb.as_markup())
    
# ==========================================
# 🏦 БАНК И СВОДКА ДЕПОЗИТОВ
# ==========================================
@router.message(F.text.lower().in_(["банк", "bank", "🏦 банк", "🏦 bank"]))
async def widget_bank(message: types.Message, _ = None):
    if not _: _ = local_fallback
    user_data = await get_cached_user_data(message.from_user.id)
    debt, ban_until = user_data.get('debt', 0), user_data.get('ban_until', 0)
    current_time = int(time.time())
    builder = InlineKeyboardBuilder()

    if ban_until > current_time:
        status_icon, status_text = "🔴", _("bank_status_frozen")
        info_text = _("bank_info_frozen", hours=(ban_until - current_time) // 3600)
    elif debt > 0:
        status_icon, status_text = "🟡", _("bank_status_debt")
        rem_time = max(0, user_data.get('debt_time', 0) - current_time)
        info_text = _("bank_info_debt", debt=fmt(debt), hours=rem_time // 3600, mins=(rem_time % 3600) // 60)
        builder.row(types.InlineKeyboardButton(text=_("bank_btn_extend"), callback_data="loan_extend"))
    else:
        status_icon, status_text, info_text = "🟢", _("bank_status_ok"), _("bank_info_ok")

    await message.reply(_("bank_title", icon=status_icon, status=status_text, info=info_text), reply_markup=builder.as_markup() if debt > 0 else None)

@router.message(Command("balance"))
@router.message(F.text.lower().strip().in_(["б", "баланс", "счёт", "bal", "balance", "b"]))
async def show_balance(message: types.Message, _ = None):
    if not _: _ = local_fallback
    user_id = message.from_user.id          
    balance = await get_balance(user_id)
    
    pool = await get_db()
    async with pool.acquire() as db:
        gold_balance = await db.fetchval("SELECT gold_balance FROM users WHERE user_id = $1", user_id) or 0
        active_title = await db.fetchval("SELECT title FROM users WHERE user_id = $1", user_id)
        umc_balance = await db.fetchval("SELECT umc_balance FROM farms WHERE user_id = $1", user_id) or 0
        
    fmt_gold = f"{int(gold_balance):,}".replace(',', ' ')
    fmt_umc = f"{int(umc_balance):,}".replace(',', ' ')
    
    vip_badge = ""
    if active_title:
        vip_badge = f" 💎 <b>[{active_title}]</b>"
    elif user_id == ADMIN_ID or user_id in MODERATORS:
        vip_badge = " 🛡 <b>[ADMIN]</b>"
    elif await has_active_status(user_id, 777):
        vip_badge = " 👑 <b>[VIP]</b>"
        
    today, last_claim = str(date.today()), await get_last_bonus(user_id)
    
    builder = InlineKeyboardBuilder()
    if last_claim != today: builder.button(text=_("balance_btn_bonus"), callback_data=f"claim_bonus_inline_{user_id}")
        
    await message.reply(
        _("balance_msg", vip=vip_badge, user_id=user_id, name=message.from_user.first_name, fiat=fmt(balance), shares=fmt_gold, umc=fmt_umc), 
        reply_markup=builder.as_markup() if last_claim != today else None,
        parse_mode="HTML"
    )

# ==========================================
# 🤝 РЕФЕРАЛКА, ПОМОЩЬ, ЧАТЫ И ПОДСКАЗКИ
# ==========================================
@router.message(F.text.lower().in_(["чаты", "channels", "chats", "🌐 чаты", "🌐 channels", "🌐 chats"]))
async def cmd_official_chats(message: types.Message, _ = None):
    if not _: _ = local_fallback
    builder = InlineKeyboardBuilder()
    builder.button(text=_("chats_btn_connect"), url="https://t.me/umbrelianachat")
    await message.reply(_("chats_title"), reply_markup=builder.as_markup(), parse_mode="HTML")

@router.message(Command("help"))
@router.message(F.text.lower().in_(["инструктаж", "briefing", "📚 инструктаж", "📚 briefing"]))
async def cmd_instruction_hub(message: types.Message, _ = None):
    if not _: _ = local_fallback
    
    # 🔥 Динамически вытягиваем ссылку из локализации
    wiki_url = _("instruct_url")
    
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text=_("btn_start_tut"), callback_data="tut_start"))
    kb.row(types.InlineKeyboardButton(text=_("instruct_btn_wiki"), url=wiki_url))
    kb.adjust(1)
    
    await message.answer(_("instruct_title"), reply_markup=kb.as_markup(), parse_mode="HTML")

@router.message(Command("mines"))
async def cmd_mines_hint(message: types.Message, _ = None): 
    if not _: _ = local_fallback
    await message.reply(_("hint_mines"), parse_mode="HTML")

@router.message(Command("bomb"))
async def cmd_bomb_hint(message: types.Message, _ = None): 
    if not _: _ = local_fallback
    await message.reply(_("hint_bomb"), parse_mode="HTML")

@router.message(Command("race"))
async def cmd_race_hint(message: types.Message, _ = None): 
    if not _: _ = local_fallback
    await message.reply(_("hint_race"), parse_mode="HTML")

async def build_referral_menu(user_id: int, bot_instance, _):
    bot_info = await bot_instance.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
    pool = await get_db()
    async with pool.acquire() as db:
        refs_count = await db.fetchval("SELECT COUNT(*) FROM users WHERE referrer_id = $1", user_id) or 0
        total_earned = await db.fetchval("SELECT refs_earned FROM users WHERE user_id = $1", user_id) or 0
    
    text = _("ref_menu_text", count=refs_count, earned=fmt(total_earned), link=ref_link)
    builder = InlineKeyboardBuilder()
    builder.button(text=_("ref_menu_btn_invite"), url=f"https://t.me/share/url?url={ref_link}&text=" + _("ref_menu_invite_text"))
    return text, builder.as_markup()

@router.callback_query(F.data == "referral_menu")
async def callback_referral_menu(callback: types.CallbackQuery, _ = None):
    if not _: _ = local_fallback
    text, markup = await build_referral_menu(callback.from_user.id, callback.bot, _)
    if callback.message.photo:
        try: await callback.message.delete()
        except: pass
        await callback.message.answer(text, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)
    else:
        await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)

@router.message(F.text.lower().in_(["реферал", "рефералы", "🤝 реферал", "🤝 referral", "referral", "refs"]))
async def text_referral_menu(message: types.Message, _ = None):
    if not _: _ = local_fallback
    text, markup = await build_referral_menu(message.from_user.id, message.bot, _)
    await message.reply(text, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)

# ==========================================
# CATALOG: СПИСОК ИГР 
# ==========================================
@router.message(F.text.lower().in_(["игры", "список игр", "казино", "азарт", "каталог", "каталог игр", "games", "games list", "casino"]))
async def show_games_list(message: types.Message, _ = None):
    if not _: _ = local_fallback
    await message.reply(_("games_list_text"), parse_mode="HTML")