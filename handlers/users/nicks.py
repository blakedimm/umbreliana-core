import re
import html
import json
import logging
import os
from aiogram import Router, F, types
from core.database import get_db

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
    logging.error(f"Критическая ошибка чтения резервного файла ников ru.json: {e}")

def local_fallback(key: str, **kwargs) -> str:
    text = FALLBACK_STRINGS.get(key, key)
    if kwargs:
        try: return text.format(**kwargs)
        except: pass
    return text

# ==========================================
# 🔍 КОМАНДА: ИНФОРМАЦИЯ О НИКНЕЙМЕ (НОВАЯ)
# ==========================================
@router.message(F.text.lower().strip().in_(["ник", "никнейм", "nick", "nickname"]))
async def cmd_show_nickname_info(message: types.Message, _ = None):
    if not _: _ = local_fallback
    user_id = message.from_user.id
    
    pool = await get_db()
    async with pool.acquire() as db:
        # Тянем актуальный ник из базы данных
        current_nick = await db.fetchval("SELECT nickname FROM users WHERE user_id = $1", user_id)
        
    # Если в базе пусто (первичный запуск), подставляем имя из Telegram
    if not current_nick:
        current_nick = html.escape(message.from_user.first_name) if message.from_user.first_name else _("nick_default_agent", user_id=user_id)
        
    await message.reply(
        _("nick_info_text", nick=current_nick),
        parse_mode="HTML"
    )

# ==========================================
# 🏷 КОМАНДА: СМЕНА НИКНЕЙМА
# ==========================================
@router.message(F.text.lower().startswith(("+ник ", "+имя ", "+никнейм ", "+nick ", "+name ")))
async def cmd_set_nickname(message: types.Message, _ = None):
    if not _: _ = local_fallback
    
    parts = message.text.split(maxsplit=1)
    
    if len(parts) < 2:
        return await message.reply(_("nick_err_empty"), parse_mode="HTML")
        
    new_nick = parts[1].strip()
    
    # 🛡 ВАЛИДАЦИЯ
    if len(new_nick) < 2 or len(new_nick) > 25:
        return await message.reply(_("nick_err_len"), parse_mode="HTML")
        
    if "<" in new_nick or ">" in new_nick or "&" in new_nick:
        return await message.reply(_("nick_err_html"), parse_mode="HTML")
        
    new_nick = re.sub(r'[\r\n\t\u200b\u200e\u200c\u200d]', '', new_nick).strip()
    
    if not new_nick:
        return await message.reply(_("nick_err_spaces"))

    safe_nick = html.escape(new_nick)

    # 💾 СОХРАНЯЕМ В БАЗУ
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            await db.execute("UPDATE users SET nickname = $1 WHERE user_id = $2", safe_nick, message.from_user.id)
            
        await message.reply(
            _("nick_success", nick=safe_nick), 
            parse_mode="HTML"
        )
    except Exception as e:
        logging.error(f"Ошибка при смене ника {message.from_user.id}: {e}")
        await message.reply(_("nick_db_error"))

# Отдельный перехватчик, если ввели просто команду изменения без параметров
@router.message(F.text.lower().in_(["+ник", "+имя", "+никнейм", "+nick", "+name"]))
async def cmd_set_nickname_empty(message: types.Message, _ = None):
    if not _: _ = local_fallback
    await message.reply(_("nick_empty_hint"), parse_mode="HTML")

# ==========================================
# ♻️ КОМАНДА: СБРОС НИКНЕЙМА
# ==========================================
@router.message(F.text.lower().in_(["-ник", "-имя", "-никнейм", "-nick", "-name"]))
async def cmd_reset_nickname(message: types.Message, _ = None):
    if not _: _ = local_fallback
    
    default_name = message.from_user.first_name
    
    if not default_name:
        default_name = _("nick_default_agent", user_id=message.from_user.id)

    safe_name = html.escape(default_name)

    # 💾 ВОЗВРАЩАЕМ В БАЗУ
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            await db.execute("UPDATE users SET nickname = $1 WHERE user_id = $2", safe_name, message.from_user.id)
            
        await message.reply(
            _("nick_reset_success", name=safe_name), 
            parse_mode="HTML"
        )
    except Exception as e:
        logging.error(f"Ошибка при сбросе ника {message.from_user.id}: {e}")
        await message.reply(_("nick_db_error"))