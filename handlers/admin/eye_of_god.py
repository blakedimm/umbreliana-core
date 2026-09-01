import os
import time
import asyncio
import logging
from aiogram import Router, F, types
from core.database import get_db, resolve_user_id

# Локальная функция для красоты цифр
fmt = lambda x: f"{int(x):,}".replace(',', ' ')

router = Router()

# ==========================================
# 🔐 СИСТЕМНЫЕ ИСКЛЮЧЕНИЯ
# ==========================================
ADMIN_ID = int(os.getenv("ADMIN_ID", 1412940726))
MODERATORS = [int(i.strip()) for i in os.getenv("MODERATORS", "").split(",") if i.strip()]
EXCLUDED_IDS = [ADMIN_ID] + MODERATORS

audit_logger = logging.getLogger("EyeOfGod")
user_names_cache = {}

async def get_user_display_name(bot, user_id):
    """Пытается достать красивое имя юзера."""
    if user_id in user_names_cache:
        return user_names_cache[user_id]
        
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            row = await db.fetchrow("SELECT telegram_username FROM users WHERE user_id = $1", user_id)
            if row and row['telegram_username']:
                name = f"@{row['telegram_username']} (ID:{user_id})"
                user_names_cache[user_id] = name
                return name
    except: pass

    try:
        chat = await bot.get_chat(user_id)
        name_parts = filter(None, [chat.first_name, chat.last_name])
        full_name = " ".join(name_parts) if name_parts else f"Агент {user_id}"
        username = f" (@{chat.username})" if chat.username else ""
        final_name = f"{full_name}{username}"
        user_names_cache[user_id] = final_name
        return final_name
    except:
        return f"ID:{user_id}"

# ==========================================
# 🐳 ЛОГГЕР КИТОВ (Мониторинг переводов)
# ==========================================
async def log_whale_transaction(bot, sender_id, receiver_id, amount):
    if amount < 100_000_000: return
    if sender_id in EXCLUDED_IDS or receiver_id in EXCLUDED_IDS: return

    try:
        pool = await get_db()
        async with pool.acquire() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS whale_logs (
                    id SERIAL PRIMARY KEY,
                    sender_id BIGINT,
                    receiver_id BIGINT,
                    amount BIGINT,
                    timestamp BIGINT
                )
            """)
            await db.execute("INSERT INTO whale_logs (sender_id, receiver_id, amount, timestamp) VALUES ($1, $2, $3, $4)", 
                             sender_id, receiver_id, amount, int(time.time()))
    except Exception as e:
        audit_logger.error(f"Не удалось записать транзакцию кита: {e}")

# ==========================================
# 🐳 ПРОСМОТР АКТИВНОСТИ КИТОВ
# ==========================================
@router.message(F.text.lower() == "/киты", F.from_user.id == ADMIN_ID)
async def admin_view_whales(message: types.Message):
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            rows = await db.fetch("SELECT * FROM whale_logs ORDER BY timestamp DESC LIMIT 10")
            
        if not rows:
            return await message.reply("Китовых активностей пока не зафиксировано.")
            
        text = "🐳 <b>ПОСЛЕДНИЕ ТРАНЗАКЦИИ КИТОВ (>100M ᴜ)</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        for r in rows:
            sender = await get_user_display_name(message.bot, r['sender_id'])
            receiver = await get_user_display_name(message.bot, r['receiver_id'])
            time_str = time.strftime('%H:%M', time.localtime(r['timestamp']))
            text += f"🕒 {time_str} | <b>{sender}</b> ➡ <b>{receiver}</b>\n💸 <code>{fmt(r['amount'])} ᴜ</code>\n\n"
            
        await message.reply(text, parse_mode="HTML")
    except Exception as e:
        await message.reply(f"Ошибка чтения логов: {e}")