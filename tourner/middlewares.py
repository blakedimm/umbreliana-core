import time
from aiogram import BaseMiddleware, types
from aiogram.types import Message, CallbackQuery

# 🔥 ПЛОСКИЙ ИМПОРТ
from database import get_db

IS_SHUTTING_DOWN = False
ADMIN_ID = 1412940726

# Оставили только то, что работает на турнире
INTERACTION_TRIGGERS = {
    "б", "баланс", "мины", "рулетка", "го", "топ",
    "ферма", "сбор", "собрать", "инвентарь", "мои", "купить", "продать",
    "рынок", "профиль", "команды", "чаты", "чат", "общение"
}

# ==========================================
# 🛑 УЛУЧШЕННАЯ АНТИ-СПАМ СИСТЕМА (RATE LIMIT)
# ==========================================
rate_limit_cache = {}

class RateLimitMiddleware(BaseMiddleware):
    def __init__(self, limit_seconds: float = 0.7):
        self.limit = limit_seconds

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if not user or user.is_bot:
            return await handler(event, data)

        if isinstance(event, (Message, CallbackQuery)):
            user_id = user.id
            current_time = time.time()
            
            if len(rate_limit_cache) > 5000:
                rate_limit_cache.clear()
                
            if user_id in rate_limit_cache:
                time_passed = current_time - rate_limit_cache[user_id]
                
                if time_passed < self.limit:
                    if isinstance(event, CallbackQuery):
                        try: await event.answer() 
                        except: pass
                    return 
            
            rate_limit_cache[user_id] = current_time

        return await handler(event, data)
    
# ==========================================
# 🛑 ЗАЩИТА ПРИ ПЕРЕЗАГРУЗКЕ (SHUTDOWN)
# ==========================================
class ShutdownMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        global IS_SHUTTING_DOWN
        if IS_SHUTTING_DOWN:
            message = event.message if hasattr(event, "message") else (event if isinstance(event, Message) else None)
            callback = event.callback_query if hasattr(event, "callback_query") else (event if isinstance(event, CallbackQuery) else None)
            
            if message:
                is_private = message.chat.type == "private"
                text = message.text.lower() if message.text else ""
                first_word = text.split()[0] if text.split() else ""
                
                is_command = text.startswith("/") or first_word in INTERACTION_TRIGGERS or text in INTERACTION_TRIGGERS
                
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
                            "Писать от имени каналов на Арене запрещено.\n"
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
# 📊 ВЫШИБАЛА, СЛЕДИТ ЗА КОМАНДОЙ "БАН"
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
                    # Ловим ошибку, если вдруг колонки ban_until нет (подстраховка)
                    try:
                        ban_until = await db.fetchval("SELECT ban_until FROM users WHERE user_id = $1", user.id)
                    except:
                        ban_until = 0
                
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

class AccessMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if not user or user.is_bot:
            return await handler(event, data)

        # 🔥 АБСОЛЮТНЫЙ ПРОПУСК ДЛЯ АРХИТЕКТОРА
        if user.id == ADMIN_ID:
            return await handler(event, data)

        # 1. Разрешаем /start всем (чтобы новички могли войти, а дезертиры получили отказ в хендлере)
        if isinstance(event, types.Message) and event.text and event.text.startswith("/start"):
            return await handler(event, data)

        # 2. Для всех остальных команд
        pool = await get_db()
        async with pool.acquire() as db:
            # Получаем и наличие игрока, и его статус бана
            row = await db.fetchrow("SELECT is_banned FROM users WHERE user_id = $1", user.id)
            
            # Если игрока нет ИЛИ он помечен как забаненный (покинувший)
            if not row or row['is_banned']:
                # ПОЛНОЕ МОЛЧАНИЕ. Турнирный бот исчезает для этого юзера.
                if isinstance(event, CallbackQuery):
                    try: await event.answer()
                    except: pass
                return 

        return await handler(event, data)