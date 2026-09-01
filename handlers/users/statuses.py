import re
import time
import urllib.parse
import json
import logging
import os
from aiogram import Router, F, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.database import get_db, get_balance, add_balance

router = Router()

def fmt(num):
    return f"{int(num):,}".replace(",", " ")

# ==========================================
# 🛡 ФЕЙЛСЕЙФ СИСТЕМА: РЕЗЕРВНАЯ ЛОКАЛИЗАЦИЯ ДЛЯ ОНЛАЙНА
# ==========================================
FALLBACK_STRINGS = {}
try:
    if os.path.exists("locales/ru.json"):
        with open("locales/ru.json", "r", encoding="utf-8") as f:
            FALLBACK_STRINGS = json.load(f)
except Exception as e:
    logging.error(f"Критическая ошибка чтения резервного файла статусов ru.json: {e}")

def local_fallback(key: str, **kwargs) -> str:
    text = FALLBACK_STRINGS.get(key, key)
    if kwargs:
        try: return text.format(**kwargs)
        except: pass
    return text

# ==========================================
# 🗄 ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ДЛЯ СТАТУСОВ
# ==========================================
async def init_statuses_db():
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_statuses (
                user_id BIGINT,
                status_id INTEGER,
                expire_timestamp BIGINT,
                PRIMARY KEY (user_id, status_id)
            )
        """)

# ==========================================
# ⚙️ ФУНКЦИИ ДВИЖКА СТАТУСОВ
# ==========================================
async def has_active_status(user_id: int, status_id: int) -> bool:
    current_time = int(time.time())
    pool = await get_db()
    async with pool.acquire() as db:
        result = await db.fetchval(
            "SELECT 1 FROM user_statuses WHERE user_id = $1 AND status_id = $2 AND expire_timestamp > $3", 
            user_id, status_id, current_time
        )
        return bool(result)

async def is_vip(user_id: int) -> bool:
    return await has_active_status(user_id, 777)

async def get_active_statuses(user_id: int) -> dict:
    current_time = int(time.time())
    active_statuses = {}
    
    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            await db.execute("DELETE FROM user_statuses WHERE expire_timestamp <= $1", current_time)
            rows = await db.fetch(
                "SELECT status_id, expire_timestamp FROM user_statuses WHERE user_id = $1", 
                user_id
            )
            for row in rows:
                active_statuses[row['status_id']] = row['expire_timestamp']
                
    return active_statuses

# ==========================================
# 💠 МУЛЬТИЯЗЫЧНАЯ КОНФИГУРАЦИЯ СТАТУСОВ
# ==========================================
STATUSES = {
    0: {
        "name_key": "status_0_name", 
        "desc_key": "status_0_desc",
        "prices": {"7": 25_000_000, "30": 70_000_000, "навсегда": 150_000_000}
    },
    1: {
        "name_key": "status_1_name", 
        "desc_key": "status_1_desc",
        "prices": {"7": 140_000_000, "30": 500_000_000, "навсегда": 2_800_000_000}
    },
    2: {
        "name_key": "status_2_name", 
        "desc_key": "status_2_desc",
        "prices": {"7": 300_000_000, "30": 650_000_000, "навсегда": 3_500_000_000}
    },
    3: {
        "name_key": "status_3_name", 
        "desc_key": "status_3_desc",
        "prices": {"7": 220_000_000, "30": 380_000_000, "навсегда": 2_100_000_000}
    },
    4: {
        "name_key": "status_4_name", 
        "desc_key": "status_4_desc",
        "prices": {"7": 500_000_000, "30": 1_000_000_000, "навсегда": 5_500_000_000}
    },
    5: {
        "name_key": "status_5_name", 
        "desc_key": "status_5_desc",
        "prices": {"7": 1_500_000_000, "30": 4_000_000_000, "навсегда": 20_000_000_000}
    },
    777: {
        "name_key": "status_777_name",
        "desc_key": "status_777_desc",
        "hidden": True,
        "prices": {}
    }
}

# ==========================================
# 📜 ВЫВОД СПИСКА ДОСТУПНЫХ СТАТУСОВ
# ==========================================
@router.message(F.text.lower().in_(["статусы", "статус", "лицензии", "statuses", "status", "licenses"]))
async def show_statuses_menu(message: types.Message, _ = None):
    if not _: _ = local_fallback
    
    text = _("st_menu_title")
    for s_id, s_data in STATUSES.items():
        if s_data.get("hidden"): continue
        
        text += _("st_menu_row", 
                  s_id=s_id, 
                  name=_(s_data['name_key']), 
                  p7=fmt(s_data['prices']['7']), 
                  p30=fmt(s_data['prices']['30']), 
                  p_perm=fmt(s_data['prices']['навсегда']), 
                  desc=_(s_data['desc_key']))
        
    text += _("st_menu_footer")
    await message.reply(text, parse_mode="HTML")

# ==========================================
# 🛒 ПОКУПКА ОБЫЧНЫХ СТАТУСОВ (ЗА UMBREL)
# ==========================================
# Расширен паттерн под buy status и параметр forever
BUY_STATUS_RE = re.compile(r"^(?:купить\s+статус|buy\s+status)\s+(\d+)\s+(7|30|навсегда|forever)$", re.IGNORECASE)

@router.message(F.text.regexp(BUY_STATUS_RE))
async def process_status_purchase(message: types.Message, _ = None):
    if not _: _ = local_fallback
    user_id = message.from_user.id
    match = BUY_STATUS_RE.match(message.text.lower())
    
    s_id = int(match.group(1))
    duration_str = match.group(2).lower()
    
    # Нормализуем английский параметр под ключи нашего словаря цен
    if duration_str == "forever":
        duration_str = "навсегда"

    if s_id not in STATUSES or STATUSES[s_id].get("hidden"):
        return await message.reply(_("st_err_invalid_id"))

    s_data = STATUSES[s_id]
    price = s_data['prices'][duration_str]
    days_to_add = 36500 if duration_str == "навсегда" else int(duration_str)

    if await get_balance(user_id) < price:
        return await message.reply(_("st_err_no_balance", price=fmt(price)), parse_mode="HTML")

    active_statuses = await get_active_statuses(user_id)
    current_time = int(time.time())

    await add_balance(user_id, -price)

    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            if s_id in active_statuses:
                new_expire = active_statuses[s_id] + (days_to_add * 86400)
                await db.execute("UPDATE user_statuses SET expire_timestamp = $1 WHERE user_id = $2 AND status_id = $3", new_expire, user_id, s_id)
                expire_timestamp = new_expire
            else:
                expire_timestamp = current_time + (days_to_add * 86400)
                await db.execute("INSERT INTO user_statuses (user_id, status_id, expire_timestamp) VALUES ($1, $2, $3)", user_id, s_id, expire_timestamp)

    if days_to_add > 10000:
        expire_text = _("st_perm_text")
    else:
        formatted_date = time.strftime('%d.%m %H:%M', time.localtime(expire_timestamp))
        expire_text = _("st_until_text", date=formatted_date)

    await message.reply(_("st_buy_success", name=_(s_data['name_key']), expire_text=expire_text), parse_mode="HTML")

@router.message(F.text.lower().startswith(("купить статус", "buy status")))
async def fallback_status_purchase(message: types.Message, _ = None):
    if not _: _ = local_fallback
    await message.reply(_("st_buy_fallback"), parse_mode="HTML")

# ==========================================
# 🌟 ЭЛИТНЫЙ ДОНАТ (ИНФОРМАЦИЯ И РЕДИРЕКТ)
# ==========================================
@router.message(F.text.lower().in_(["вип", "vip"]))
async def show_vip_menu(message: types.Message, _ = None):
    if not _: _ = local_fallback
    
    bot_me = await message.bot.get_me()
    encoded_text = urllib.parse.quote("💎 Донат")
    bot_link = f"https://t.me/{bot_me.username}?text={encoded_text}"
    
    kb = InlineKeyboardBuilder()
    kb.button(text=_("st_vip_btn_text"), url=bot_link)
    kb.adjust(1)
    
    await message.reply(
        _("st_vip_desc"), 
        reply_markup=kb.as_markup(), 
        parse_mode="HTML"
    )
    
# ==========================================
# 📋 МОИ СОБЫТИЯ / СТАТУСЫ
# ==========================================
@router.message(F.text.lower().in_(["мои события", "мои статусы", "мой статус", "my events", "my statuses", "my status"]))
async def my_status_menu(message: types.Message, _ = None):
    if not _: _ = local_fallback
    user_id = message.from_user.id
    active_statuses = await get_active_statuses(user_id)

    if not active_statuses:
        return await message.reply(_("st_my_none"), parse_mode="HTML")

    text = _("st_my_title")
    current_time = int(time.time())

    for s_id, expire in active_statuses.items():
        s_data = STATUSES.get(s_id)
        if not s_data: continue

        time_left = expire - current_time
        days = time_left // 86400
        
        if days > 10000:
            text += _("st_my_row_forever", name=_(s_data['name_key']))
        else:
            hours = (time_left % 86400) // 3600
            minutes = (time_left % 3600) // 60
            formatted_date = time.strftime('%d.%m.%Y %H:%M', time.localtime(expire))
            text += _("st_my_row_time", name=_(s_data['name_key']), date=formatted_date, days=days, hours=hours, minutes=minutes)

    await message.reply(text, parse_mode="HTML")

# ==========================================
# 📡 СБОРЩИК VIP-ПОДПИСЧИКОВ (ДЛЯ РЫНКА)
# ==========================================
async def get_vip_market_subscribers() -> list:
    current_time = int(time.time())
    pool = await get_db()
    async with pool.acquire() as db:
        rows = await db.fetch(
            "SELECT DISTINCT user_id FROM user_statuses WHERE status_id IN (2, 777) AND expire_timestamp > $1", 
            current_time
        )
        return [row['user_id'] for row in rows]

# ==========================================
# 🛰 МОДУЛЬ СЛЕЖКИ: ЧЕК СТАТУС (АДМИН / VIP)
# ==========================================
@router.message(F.text.lower().startswith(("чек статус", "check status")))
async def cmd_check_user_status(message: types.Message, _ = None):
    if not _: _ = local_fallback
    user_id = message.from_user.id
    
    if user_id != 1412940726 and not await has_active_status(user_id, 777) and not await has_active_status(user_id, 4):
        return await message.reply(_("st_check_denied"))

    target_id = None
    target_name = "Agent"

    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        target_name = message.reply_to_message.from_user.first_name
    else:
        parts = message.text.split()
        if len(parts) >= 3:
            target_param = parts[2]
            if target_param.isdigit():
                target_id = int(target_param)
                target_name = f"ID: {target_id}"
            elif message.entities:
                for entity in message.entities:
                    if entity.type == "text_mention":
                        target_id = entity.user.id
                        target_name = entity.user.first_name
                        break

    if not target_id:
        return await message.reply(_("st_check_usage"), parse_mode="HTML")

    active_statuses = await get_active_statuses(target_id)

    if not active_statuses:
        return await message.reply(_("st_check_none", name=target_name), parse_mode="HTML")

    text = _("st_check_title", name=target_name)
    current_time = int(time.time())

    for s_id, expire in active_statuses.items():
        s_data = STATUSES.get(s_id)
        if not s_data: continue

        time_left = expire - current_time
        days = time_left // 86400
        
        if days > 10000:
            text += _("st_my_row_forever", name=_(s_data['name_key']))
        else:
            hours = (time_left % 86400) // 3600
            minutes = (time_left % 3600) // 60
            formatted_date = time.strftime('%d.%m.%Y %H:%M', time.localtime(expire))
            text += _("st_my_row_time", name=_(s_data['name_key']), date=formatted_date, days=days, hours=hours, minutes=minutes)

    await message.reply(text, parse_mode="HTML")