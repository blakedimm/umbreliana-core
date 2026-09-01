import time
import asyncio
import re
from aiogram import BaseMiddleware, types
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core import bot_state 
from core.database import get_db
from core.redis_driver import get_redis
from core.triggers import INTERACTION_TRIGGERS

CHANNEL_ID = -1003768778329 
CHANNEL_URL = "https://t.me/umbreliananews"

activity_buffer = {}

# ==========================================
# 🛑 ГЛОБАЛЬНЫЙ АНТИ-СПАМ V3.0 (Умный фильтр)
# ==========================================
class RateLimitMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if not user or user.is_bot:
            return await handler(event, data)

        if isinstance(event, (Message, CallbackQuery)):
            redis = await get_redis()
            if not redis:
                return await handler(event, data)

            # =======================================================
            # 🧠 1. ИНТЕЛЛЕКТУАЛЬНЫЕ ФИЛЬТРЫ ПРОПУСКА
            # =======================================================
            if isinstance(event, Message):
                # ❌ Игнорируем сервисные сообщения (вступление в группу, пины и т.д.)
                if event.content_type not in ("text", "photo", "video", "document", "audio", "voice"):
                    return await handler(event, data)

                # 🗣 В группах игнорируем обычный трёп, обрабатываем только команды (начинаются с "/")
                is_private = event.chat.type == "private"
                is_command = event.text and event.text.startswith("/")
                
                # Если это не личка и не команда — пусть общаются, анти-спам тут не нужен
                if not is_private and not is_command:
                    return await handler(event, data)

                # 🖼 ЗАЩИТА ОТ АЛЬБОМОВ
                if event.media_group_id:
                    album_key = f"album_lock:{event.media_group_id}"
                    is_first_in_album = await redis.set(album_key, "1", ex=10, nx=True)
                    if not is_first_in_album:
                        return await handler(event, data)

            # =======================================================
            # 🛑 2. ПРОВЕРКА ТОТАЛЬНОГО ИГНОРА
            # =======================================================
            ignore_key = f"user_ignored:{user.id}"
            if await redis.get(ignore_key):
                return 

            # =======================================================
            # 🔒 3. РАЗДЕЛЬНЫЕ ЗАМКИ (Текст отдельно, кнопки отдельно)
            # =======================================================
            # Добавляем префикс, чтобы лок на кнопку не блочил текстовые команды и наоборот
            action_type = "cb" if isinstance(event, CallbackQuery) else "msg"
            lock_key = f"user_lock:{action_type}:{user.id}"
            
            acquired = await redis.set(lock_key, "processing", ex=10, nx=True)
            
            if not acquired:
                # 📈 СИСТЕМА ЭСКАЛАЦИИ СПАМА
                spam_key = f"spam_clicks:{user.id}"
                clicks = await redis.incr(spam_key)
                await redis.expire(spam_key, 5)
                
                show_modal = False
                msg = None

                # Стадии агрессии
                if clicks <= 2:
                    # На 1-2 клика ругаемся ТОЛЬКО на инлайн кнопки (тихим тостом)
                    # На текст молчим, чтобы не засорять чат
                    if isinstance(event, CallbackQuery):
                        msg = "⏳ Процесс обрабатывается, подожди..."
                elif clicks == 3:
                    msg = "🤨 Слыш, тебе русским языком сказано — подожди."
                elif clicks == 4:
                    msg = "🤬 Хватит спамить! Терминал сейчас заклинит от твоих кликов!"
                    show_modal = True
                elif clicks >= 5:
                    msg = "🤬 ДА ТЫ ЗАЕБАЛ! Всё, я ушел на перекур. Минуту меня не трогай."
                    await redis.set(ignore_key, "1", ex=60)
                    await redis.delete(spam_key)
                    show_modal = True

                # Отправляем ответ только если есть что сказать
                if msg:
                    if isinstance(event, CallbackQuery):
                        try: await event.answer(msg, show_alert=show_modal) 
                        except: pass
                    elif isinstance(event, Message):
                        try: await event.reply(f"<b>{msg}</b>", parse_mode="HTML") 
                        except: pass
                
                return  
            
            # =======================================================
            # ✅ 4. ШТАТНОЕ ВЫПОЛНЕНИЕ
            # =======================================================
            try:
                return await handler(event, data)
            finally:
                # Снимаем замок только после выполнения задачи
                await redis.delete(lock_key)
        
        return await handler(event, data)
    
# ==========================================
# 🛑 ЗАЩИТА ПРИ ПЕРЕЗАГРУЗКЕ (SHUTDOWN)
# ==========================================
class ShutdownMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if bot_state.IS_SHUTTING_DOWN:
            message = event.message if hasattr(event, "message") else (event if isinstance(event, Message) else None)
            callback = event.callback_query if hasattr(event, "callback_query") else (event if isinstance(event, CallbackQuery) else None)
            
            if message:
                is_private = message.chat.type == "private"
                is_command = message.text and (message.text.startswith("/") or any(t in message.text.lower() for t in INTERACTION_TRIGGERS))
                
                if is_private or is_command:
                    try: 
                        await message.answer("🛠 <b>Система на техобслуживании.</b>\nПожалуйста, подождите завершения рестарта...", parse_mode="HTML")
                    except: pass
                return 

            elif callback:
                try: 
                    await callback.answer("🛠 Идет рестарт бота...", show_alert=True)
                except: pass
                return 

            return 
            
        return await handler(event, data)


# ==========================================
# 🛑 АНТИ-АБУЗ: БЛОКИРОВКА КАНАЛОВ И АНОНИМОВ
# ==========================================
class AntiChannelMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, types.Message):
            if event.sender_chat:
                text = event.text.lower() if event.text else ""
                first_word = text.split()[0] if text.split() else ""
                
                if text.startswith("/") or first_word in INTERACTION_TRIGGERS or text in INTERACTION_TRIGGERS:
                    try:
                        await event.reply(
                            "🛑 <b>ОТКАЗ СИСТЕМЫ:</b>\n"
                            "Писать от имени каналов или анонимных администраторов запрещено.\n"
                            "<i>Снимите маску и играйте с реального аккаунта!</i>", 
                            parse_mode="HTML"
                        )
                    except: pass
                return 
            
            user = data.get("event_from_user")
            if user and user.id in [136817688, 1087968824, 777000]:
                return
                
        elif isinstance(event, types.CallbackQuery):
            user = data.get("event_from_user")
            if user and user.id in [136817688, 1087968824, 777000]:
                await event.answer("🛑 Анонимным аккаунтам запрещено нажимать кнопки!", show_alert=True)
                return
                
        return await handler(event, data)


# ==========================================
# 🛑 ВЫШИБАЛА, СЛЕДИТ ЗА КОМАНДОЙ "БАН"
# ==========================================
ban_cache = {}

class BanMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        if len(ban_cache) > 1000:
            ban_cache.clear()

        current_time = int(time.time())
        ban_until = None
        
        if user.id in ban_cache and (current_time - ban_cache[user.id]["checked_at"] < 30):
            ban_until = ban_cache[user.id]["ban_until"]
        else:
            try:
                pool = await get_db()
                async with pool.acquire() as db:
                    ban_until = await db.fetchval("SELECT ban_until FROM users WHERE user_id = $1", user.id)
                
                ban_cache[user.id] = {
                    "ban_until": ban_until,
                    "checked_at": current_time
                }
            except Exception as e:
                print(f"⚠️ Ошибка проверки бана в БД: {e}")
                return await handler(event, data)

        if ban_until and ban_until > current_time:
            time_left = max(0, int((ban_until - current_time) / 3600))
            is_interaction = False
            
            if isinstance(event, CallbackQuery):
                is_interaction = True
            elif isinstance(event, Message) and event.text:
                text = event.text.lower().strip()
                first_word = text.split()[0] if text.split() else ""
                if getattr(event.chat, "type", "") == "private" or first_word in INTERACTION_TRIGGERS or text.startswith("/"):
                    is_interaction = True

            if is_interaction:
                if isinstance(event, CallbackQuery):
                    await event.answer(f"🚫 Доступ закрыт. Бан еще {time_left} ч.", show_alert=True)
                elif isinstance(event, Message):
                    try:
                        await event.reply(
                            f"🚫 <b>ДОСТУП ЗАКРЫТ</b>\n"
                            f"Ты заблокирован решением Архитектора. Осталось часов: {time_left}", 
                            parse_mode="HTML"
                        )
                    except: pass
                return 

        return await handler(event, data)


# ==========================================
# 🛑 УМНАЯ СЛЕЖКА ЗА ПОДПИСКОЙ (неактивная)
# ==========================================
class SubMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        # 🔥 ОТКЛЮЧЕНИЕ ПРОВЕРКИ: Система всегда пропускает игрока дальше
        return await handler(event, data)


# ==========================================
# 📊 УМНЫЙ ТРЕКЕР АКТИВНОСТИ
# ==========================================
class ActivityTrackerMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        handler_obj = data.get("handler")
        if handler_obj and handler_obj.callback.__name__ == "pm_garbage_handler":
            return await handler(event, data) 

        user = None
        chat_id = None

        if isinstance(event, types.Message):
            user = event.from_user
            chat_id = event.chat.id
        elif isinstance(event, types.CallbackQuery):
            user = event.from_user
            chat_id = event.message.chat.id if event.message else user.id

        if user:
            uid = user.id
            if uid not in activity_buffer:
                activity_buffer[uid] = {
                    "msgs": 0,
                    "last_seen": int(time.time()),
                    "chat_id": set(),
                    "username": user.username
                }

            activity_buffer[uid]["msgs"] += 1
            activity_buffer[uid]["last_seen"] = int(time.time())
            activity_buffer[uid]["chat_id"].add(chat_id)
            if user.username:
                activity_buffer[uid]["username"] = user.username

        return await handler(event, data)


# ==========================================
# 🧠 ТУРНИРНЫЙ ЗАМОК АРЕНЫ
# ==========================================
tournament_cache = {}

class TournamentLockMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user_id = None
        text = ""
        is_callback = False
        
        if isinstance(event, types.Message):
            user_id = event.from_user.id
            text = event.text.lower().strip() if event.text else ""
        elif isinstance(event, types.CallbackQuery):
            user_id = event.from_user.id
            is_callback = True
        else:
            return await handler(event, data)
            
        if not user_id:
            return await handler(event, data)

        # 1. РАЗРЕШАЕМ ВЫХОД
        if not is_callback and text == "покинуть турнир":
            pool = await get_db()
            async with pool.acquire() as db:
                user_status = await db.fetchrow(
                    "SELECT in_tournament, has_left_tournament FROM users WHERE user_id = $1", 
                    user_id
                )
                
                if not user_status or (not user_status['in_tournament'] and not user_status['has_left_tournament']):
                    await event.answer("🤔 Вы и так не в турнире.")
                    return

                await db.execute("UPDATE users SET in_tournament = FALSE, has_left_tournament = TRUE WHERE user_id = $1", user_id)
            
            # 🔥 ФИКС ИНДЕНТАЦИИ: Весь этот блок теперь строго внутри "if text == 'покинуть турнир'"!
            TOURNEY_DB_URL = "postgresql://postgres:asddsa123@localhost:5432/tourney_db"
            try:
                import asyncpg
                t_conn = await asyncpg.connect(TOURNEY_DB_URL)
                await t_conn.execute("""
                    INSERT INTO users (user_id, is_banned) 
                    VALUES ($1, TRUE) 
                    ON CONFLICT (user_id) DO UPDATE SET is_banned = TRUE
                """, user_id)
                await t_conn.execute("DELETE FROM farms WHERE user_id = $1", user_id)
                await t_conn.close()
                print(f"✅ Юзер {user_id} навсегда изгнан с Арены.")
            except Exception as e:
                print(f"❌ КРИТИЧЕСКАЯ ОШИБКА ИЗГНАНИЯ: {e}")

            tournament_cache[user_id] = {"is_locked": False, "expire": time.time() + 60}
            
            try:
                await event.answer(
                    "♻️ <b>Вы покинули турнир.</b>\n"
                    "Основа разморожена. Доступ на Арену закрыт навсегда.", 
                    parse_mode="HTML"
                )
            except: pass
            return
            
        # 2. УМНОЕ КЭШИРОВАНИЕ СТАТУСА
        current_time = time.time()
        is_locked = False
        
        if user_id in tournament_cache and tournament_cache[user_id]["expire"] > current_time:
            is_locked = tournament_cache[user_id]["is_locked"]
        else:
            pool = await get_db()
            async with pool.acquire() as db:
                try:
                    is_locked = await db.fetchval("SELECT in_tournament FROM users WHERE user_id = $1", user_id)
                    is_locked = bool(is_locked) 
                except:
                    is_locked = False
            
            tournament_cache[user_id] = {"is_locked": is_locked, "expire": current_time + 60}

        # 3. ИСПОЛНЕНИЕ: ТОТАЛЬНОЕ МОЛЧАНИЕ
        if is_locked:
            if is_callback:
                try: await event.answer() 
                except: pass
            return 
            
        return await handler(event, data)