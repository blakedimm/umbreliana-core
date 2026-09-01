# File: core/redis_driver.py
import asyncio
import logging
import os
import time
import redis.asyncio as redis
from dotenv import load_dotenv

load_dotenv()
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

redis_client = None
IS_REDIS_AVAILABLE = False

_healer_lock = asyncio.Lock()
_last_restart_attempt = 0

# ==========================================
# 🔌 ИНИЦИАЛИЗАЦИЯ И ПОДКЛЮЧЕНИЕ MEMURAI
# ==========================================
async def init_redis():
    """Запуск соединения при старте бота с жестким таймаутом"""
    global redis_client, IS_REDIS_AVAILABLE
    try:
        redis_client = redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_timeout=2.0,
            socket_connect_timeout=2.0
        )
        await redis_client.ping()
        IS_REDIS_AVAILABLE = True
        logging.info("🚀 [Memurai] Соединение с Redis установлено успешно!")
        return redis_client
    except Exception as e:
        logging.error(f"❌ [Memurai] Ошибка или недоступен: {e}. Переход в Fallback-режим (без кэша).")
        redis_client = None
        IS_REDIS_AVAILABLE = False
        return None

async def get_redis():
    """Быстрая отдача клиента только если он доступен"""
    if IS_REDIS_AVAILABLE and redis_client is not None:
        return redis_client
    return None

async def close_redis():
    """Корректное закрытие пула при выключении (Очистка памяти)"""
    global redis_client, IS_REDIS_AVAILABLE
    if redis_client:
        try:
            await redis_client.aclose()
            logging.info("🛑 [Memurai] Пул соединений закрыт.")
        except Exception:
            pass
    redis_client = None
    IS_REDIS_AVAILABLE = False

# ==========================================
# 🛠 РЕАНИМАТОР СЛУЖБЫ MEMURAI (WINDOWS)
# ==========================================
async def restart_memurai_service() -> bool:
    """Асинхронно перезапускает службу Memurai на Windows без блокировки бота"""
    global IS_REDIS_AVAILABLE, _last_restart_attempt
    
    current_time = time.time()
    
    async with _healer_lock:
        if current_time - _last_restart_attempt < 30:
            return IS_REDIS_AVAILABLE
            
        _last_restart_attempt = current_time
        logging.warning("🚨 [Memurai] Попытка перезапуска службы Memurai на Windows...")

        try:
            proc = await asyncio.create_subprocess_shell(
                "net stop Memurai && net start Memurai",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()
        except Exception as e:
            logging.error(f"❌ Ошибка вызова net stop/start Memurai: {e}")

        await asyncio.sleep(2)
        await init_redis()
        return IS_REDIS_AVAILABLE

# ==========================================
# 🔥 РАДАР АКТИВНЫХ ИГР (SAFE WRAPPERS)
# ==========================================
async def set_active_game(user_id: int, game_name: str):
    """Помечает, что игрок начал игру (запись живет 1 час)"""
    r = await get_redis()
    if r:
        try:
            await r.set(f"active_game:{user_id}", game_name, ex=3600)
        except Exception as e:
            logging.warning(f"⚠️ Ошибка set_active_game({user_id}): {e}")

async def get_active_game(user_id: int):
    """Узнает, во что сейчас играет юзер"""
    r = await get_redis()
    if r:
        try:
            return await r.get(f"active_game:{user_id}")
        except Exception as e:
            logging.warning(f"⚠️ Ошибка get_active_game({user_id}): {e}")
    return None

async def clear_active_game(user_id: int):
    """Стирает метку, когда игра закончена"""
    r = await get_redis()
    if r:
        try:
            await r.delete(f"active_game:{user_id}")
        except Exception as e:
            logging.warning(f"⚠️ Ошибка clear_active_game({user_id}): {e}")