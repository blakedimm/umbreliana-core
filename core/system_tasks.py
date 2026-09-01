# File: core/system_tasks.py
import asyncio
import os
import json
import time
import random
import logging
import traceback
import html
from aiogram import Bot, types, Dispatcher
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest

# Импортируем модули целиком для управления внутренним кэшем коннектов
import core.database
import core.redis_driver

from core.database import get_db, add_balance
from core.redis_driver import close_redis
from handlers.syndicate.farms import GPUS

ADMIN_ID = int(os.getenv("ADMIN_ID", 1412940726))
BACKUP_FILE = "data/hard_crash_backup.json"

# ==========================================
# 🧠 НАСТРОЙКИ СИСТЕМЫ ТИШИНЫ И БУФЕРОВ
# ==========================================
ALERT_COOLDOWN = 300  # Время тишины в ОЗУ (5 минут после первого падения)
LAST_SENT_ALERTS = {}  # Хранилище таймингов последних алертов в оперативке
_last_infra_alert_time = 0

activity_buffer = {}  # Буфер активности пользователей

MUTED_TG_ERRORS = [
    "not enough rights to send text messages",
    "bot was blocked by the user",
    "message to be deleted not found",
    "message is not modified",
    "message to be replied not found",
    "chat not found",
    "bad request: chat description is not modified"
]

def fmt(num):
    return f"{int(num):,}".replace(",", " ")

# ==========================================
# 🛑 ГЛОБАЛЬНЫЙ АНТИ-ФЛУД И РАДАР ОШИБОК
# ==========================================
async def global_error_handler(event: types.ErrorEvent, bot: Bot):
    exception = event.exception
    exc_name = type(exception).__name__
    exc_message = str(exception)
    current_time = time.time()

    # 1. Игнорим стандартный флуд-контроль Телеграма
    if isinstance(exception, TelegramRetryAfter):
        logging.warning(f"⚠️ Флуд-контроль. Ждем {exception.retry_after} сек.")
        return True 
        
    # 2. ИГНОР ЛОКАЛЬНОГО МУСОРА ТЕЛЕГРАМА
    err_msg_lower = exc_message.lower()
    if isinstance(exception, TelegramBadRequest) or "telegram" in exc_name.lower():
        if any(muted in err_msg_lower for muted in MUTED_TG_ERRORS):
            logging.warning(f"🔕 [Muted TG Error] Глушим спам прав/модификации чата: {exc_message}")
            return True 
            
    # 3. ТРОТТЛИНГ ИНФРАСТРУКТУРНЫХ КРАШЕЙ
    is_infrastructure_fault = (
        "timeout" in exc_name.lower() or 
        "connection" in exc_name.lower() or 
        "redis" in type(exception).__module__.lower() or
        isinstance(exception, OSError)
    )
    
    if is_infrastructure_fault:
        last_sent = LAST_SENT_ALERTS.get(exc_name, 0)
        if current_time - last_sent < ALERT_COOLDOWN:
            logging.error(f"🤫 [Throttled Alert] Redis/БД лежит. Глушим спам в ЛС. Ошибка: {exc_message}")
            return True
        else:
            LAST_SENT_ALERTS[exc_name] = current_time
            exc_message += "\n\n⚠️ <b>[🚨 СИСТЕМА ТРОТТЛИНГА ВКЛЮЧЕНА: СЛЕДУЮЩИЕ 5 МИНУТ СБОИ ЭТОГО ТИПА БУДУТ ГЛУШИТЬСЯ]</b>"

    # 4. ВЫТАСКИВАЕМ ДАННЫЕ ЮЗЕРА И ЕГО ДЕЙСТВИЕ
    update = event.update
    user_info = "Неизвестный Агент"
    action_info = "Системный процесс / Неизвестно"

    if update.message:
        user = update.message.from_user
        user_info = f"{user.first_name} (ID: {user.id})"
        action_info = f"Текст: {update.message.text}"
    elif update.callback_query:
        user = update.callback_query.from_user
        user_info = f"{user.first_name} (ID: {user.id})"
        
        button_text = "Неизвестная кнопка"
        cb_data = update.callback_query.data
        
        if update.callback_query.message and update.callback_query.message.reply_markup:
            for row in update.callback_query.message.reply_markup.inline_keyboard:
                for btn in row:
                    if btn.callback_data == cb_data:
                        button_text = btn.text
                        break
                        
        action_info = f"Кнопка: «{button_text}» (Код: {cb_data})"
        
    elif update.inline_query:
        user = update.inline_query.from_user
        user_info = f"{user.first_name} (ID: {user.id})"
        action_info = f"Инлайн: {update.inline_query.query}"

    # 5. ВЫТАСКИВАЕМ ТРЕЙСБЕК
    tb_string = traceback.format_exc()
    
    logging.error(f"❌ КРИТ: {user_info} | Действие: {action_info}\nОшибка: {exception}\n{tb_string}")
    
    try:
        short_tb = "\n".join(tb_string.strip().split('\n')[-3:])
        
        error_msg = (
            f"⚠️ <b>АХТУНГ! СБОЙ СИСТЕМЫ!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Агент:</b> {user_info}\n"
            f"🎬 <b>Действие:</b> <code>{action_info}</code>\n"
            f"🛑 <b>Тип:</b> <code>{exc_name}</code>\n"
            f"📝 <b>Текст:</b> {exc_message}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 <b>Где упало:</b>\n<pre>{html.escape(short_tb)}</pre>"
        )
        await bot.send_message(ADMIN_ID, error_msg, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Не удалось отправить детальный лог Архитектору: {e}")
        
    return True

# ==========================================
# 🧠 АВТОНОМНЫЙ МЕНЕДЖЕР САМОЛЕЧЕНИЯ СЕТИ (NO-CRASH)
# ==========================================
async def infra_auto_healer(bot: Bot):
    """
    Фоновый страж инфраструктуры. Проверяет пинги Redis и PostgreSQL.
    Безопасно восстанавливает службы без принудительного самоубийства процесса!
    """
    global _last_infra_alert_time
    redis_fail_count = 0
    db_fail_count = 0
    
    logging.info("🛡 [Auto-Healer] Фоновый санитар инфраструктуры успешно запущен!")
    
    while True:
        await asyncio.sleep(45)  # Проверка каждые 45 секунд
        
        # 1. ТЕСТИРОВАНИЕ КАНАЛА REDIS / MEMURAI
        try:
            r = core.redis_driver.redis_client
            if r is None or not core.redis_driver.IS_REDIS_AVAILABLE:
                raise Exception("Клиент Memurai/Redis равен None или помечен недоступным.")
            await r.ping()
            redis_fail_count = 0
        except Exception as e:
            redis_fail_count += 1
            logging.warning(f"🔧 [Auto-Healer] Сбой Memurai (Авария {redis_fail_count}/3): {e}")
            
            if redis_fail_count >= 2:
                try:
                    healed = await core.redis_driver.restart_memurai_service()
                    if healed:
                        logging.info("🚀 [Auto-Healer] Служба Memurai успешно реанимирована!")
                        redis_fail_count = 0
                except Exception as re_err:
                    logging.error(f"❌ [Auto-Healer] Ошибка авто-реанимации Memurai: {re_err}")
                
                # 🔥 БОЛЬШЕ НИКАКИХ os._exit(1)!
                # Переводим бота в безопасный фолбэк-режим
                core.redis_driver.IS_REDIS_AVAILABLE = False
                
                now = time.time()
                if now - _last_infra_alert_time > 1800:  # Раз в 30 минут
                    _last_infra_alert_time = now
                    try:
                        await bot.send_message(
                            ADMIN_ID,
                            "⚠️ <b>ВНИМАНИЕ: СЛУЖБА MEMURAI (REDIS) НЕДОСТУПНА</b>\n"
                            "━━━━━━━━━━━━━━━━━━━━\n"
                            "Система самолечения не смогла перезапустить Memurai.\n"
                            "<b>Бот переведен в безопасный фолбэк-режим (ОЗУ + PostgreSQL).</b>\n\n"
                            "<i>Работа проекта НЕ прерывается, балансы и игры в безопасности.</i>",
                            parse_mode="HTML"
                        )
                    except: pass

        # 2. ТЕСТИРОВАНИЕ КАНАЛА POSTGRESQL
        try:
            pool = await core.database.get_db()
            if pool is None:
                raise Exception("Пул базы данных равен None.")
            
            async with pool.acquire() as conn:
                await conn.execute("SELECT 1")
            db_fail_count = 0
        except Exception as e:
            db_fail_count += 1
            logging.warning(f"🔧 [Auto-Healer] Обнаружен сбой PostgreSQL (Авария {db_fail_count}/3): {e}")
            try:
                if core.database.db_pool:
                    try: await core.database.db_pool.close()
                    except: pass
                
                core.database.db_pool = None
                await core.database.get_db()
                logging.info("🚀 [Auto-Healer] Пул соединений PostgreSQL пересоздан.")
            except Exception as db_err:
                logging.error(f"❌ [Auto-Healer] Ошибка реанимации PostgreSQL: {db_err}")

# ==========================================
# 🛒 ФОНОВЫЙ САНИТАР РЫНКА
# ==========================================
async def market_reaper(bot_instance: Bot):
    try:
        now = int(time.time())
        user_expire = now - 86400  
        state_expire = now - 14400 
        messages_to_send = [] 
        
        pool = await get_db()
        async with pool.acquire() as db:
            async with db.transaction():
                expired_user_lots = await db.fetch("SELECT * FROM market WHERE seller_id != 0 AND created_at < $1", user_expire)
                
                for lot in expired_user_lots:
                    await db.execute(
                        "INSERT INTO gpu_batches (user_id, gpu_id, multiplier, qty, condition, was_repaired) VALUES ($1, $2, 1.0, $3, $4, 0)", 
                        lot['seller_id'], lot['gpu_id'], lot['qty'], lot['condition']
                    )
                    await db.execute("DELETE FROM market WHERE id = $1", lot['id'])
                    
                    gpu_col = lot['gpu_id']
                    await db.execute(f"UPDATE farms SET {gpu_col} = {gpu_col} + $1 WHERE user_id = $2", lot['qty'], lot['seller_id'])
                    
                    deposit = lot['deposit']
                    burn_msg = f"\n🔥 Твой залог <b>{int(deposit):,} ᴜ</b> сгорел!" if deposit > 0 else ""
                    msg_text = f"📦 <b>Срок лота истёк</b>\nТвой товар <code>{lot['id']}</code> не купили за 24 часа. Карты возвращены на склад.{burn_msg}"
                    messages_to_send.append((lot['seller_id'], msg_text))

                await db.execute("DELETE FROM market WHERE seller_id = 0 AND created_at < $1", state_expire)
                state_lots_count = await db.fetchval("SELECT COUNT(*) FROM market WHERE seller_id = 0") or 0

                if state_lots_count < 15: 
                    lots_to_spawn = random.randint(5, 12)
                    available_gpus = [k for k, v in GPUS.items() if 3 <= k < 100 and v['price'] <= 100_000_000]
                    
                    for _ in range(lots_to_spawn):
                        if not available_gpus: break
                        gpu_num = random.choice(available_gpus) 
                        qty = random.randint(1, 5)
                        cond = round(random.uniform(10.0, 75.0), 1)
                        base_value = (GPUS[gpu_num]['price'] * qty) * (cond / 100.0)
                        
                        if random.random() < 0.15: 
                            price = int(base_value * random.uniform(0.4, 0.7))
                            deal_type = "💎 Жемчужина"
                        else: 
                            price = int(base_value * random.uniform(1.1, 1.6))
                            deal_type = "😈 Оверпрайс"
                        
                        price = max(price, 1000)
                        await db.execute(
                            "INSERT INTO market (seller_id, gpu_id, price, qty, condition, created_at, deposit) VALUES (0, $1, $2, $3, $4, $5, 0)", 
                            f"gpu_{gpu_num}", price, qty, cond, now
                        )
                        logging.debug(f"РЫНОК: Выставлена {deal_type} (ID:{gpu_num} x{qty}) за {price}")

        for uid, text in messages_to_send:
            try:
                await bot_instance.send_message(uid, text, parse_mode="HTML")
                await asyncio.sleep(0.05) 
            except: pass
            
    except Exception as e:
        logging.error(f"КРИТИЧЕСКАЯ ОШИБКА market_reaper: {e}")

# ==========================================
# 🚀 АСИНХРОННЫЙ БУФЕР АКТИВНОСТИ
# ==========================================
async def activity_flusher():
    while True:
        await asyncio.sleep(15) 
        try:
            if not activity_buffer:
                continue 
                
            buffer_copy = activity_buffer.copy()
            activity_buffer.clear()
            
            pool = await get_db()
            async with pool.acquire() as db:
                user_data, chat_data = [], []
                
                for uid, data in buffer_copy.items():
                    user_data.append((uid, data['last_seen'], data['msgs'], data['username']))
                    for cid in data['chat_id']:
                        chat_data.append((cid, uid))
                
                async with db.transaction():
                    if user_data:
                        await db.executemany('''
                            INSERT INTO users (user_id, balance, first_seen, last_seen, total_messages, telegram_username)
                            VALUES ($1, 0, $2, $2, $3, $4)
                            ON CONFLICT(user_id) DO UPDATE 
                            SET last_seen = $2, 
                                total_messages = users.total_messages + $3, 
                                telegram_username = COALESCE($4, users.telegram_username)
                        ''', user_data)
                    
                    if chat_data:
                        await db.executemany(
                            "INSERT INTO chat_members (chat_id, user_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                            chat_data
                        )

            for uid, data in buffer_copy.items():
                if data['msgs'] > 0:
                    await process_quest_action(uid, "bot_interaction", data['msgs'])

        except Exception as e:
            logging.error(f"❌ Ошибка в activity_flusher: {e}")
            await asyncio.sleep(5)

# ==========================================
# 🛡 SSD-ЩИТ И ВОССТАНОВЛЕНИЕ
# ==========================================
def _save_ssd_backup_sync(data):
    with open(BACKUP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)

def _delete_ssd_backup_sync():
    if os.path.exists(BACKUP_FILE):
        os.remove(BACKUP_FILE)

async def ssd_backup_loop():
    while True:
        await asyncio.sleep(10)
        try:
            backup_data = {"refunds": {}} 

            from handlers.games.roulette_game import current_bets, spinning_bets
            for cid, bets in list(current_bets.items()) + list(spinning_bets.items()):
                for b in bets:
                    uid = b['user_id']
                    backup_data["refunds"][uid] = backup_data["refunds"].get(uid, 0) + b['amount']

            from handlers.games.mines_game import active_mines
            for uid, data in list(active_mines.items()):
                backup_data["refunds"][uid] = backup_data["refunds"].get(uid, 0) + data['bet']

            from handlers.games.crash_game import active_flights
            for cid, flight in list(active_flights.items()):
                for p_id, p_data in flight.get('players', {}).items():
                    backup_data["refunds"][p_id] = backup_data["refunds"].get(p_id, 0) + p_data['bet']
            
            if backup_data["refunds"]:
                await asyncio.to_thread(_save_ssd_backup_sync, backup_data)
            else:
                await asyncio.to_thread(_delete_ssd_backup_sync)

        except Exception as e:
            logging.error(f"❌ Ошибка в SSD-щите: {e}")

async def recover_from_hard_crash(bot_instance: Bot):
    if not os.path.exists(BACKUP_FILE):
        return 

    print("🚨 ОБНАРУЖЕН СЛЕД ЖЕСТКОГО КРАША! Читаю дамп с SSD...")
    try:
        with open(BACKUP_FILE, "r", encoding="utf-8") as f:
            backup_data = json.load(f)

        refunds = backup_data.get("refunds", {})
        if refunds:
            pool = await get_db()
            async with pool.acquire() as db:
                async with db.transaction():
                    for uid_str, amount in refunds.items():
                        uid = int(uid_str) 
                        await db.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", amount, uid)
                        try:
                            await bot_instance.send_message(
                                uid,
                                f"⚙️ <b>АВАРИЙНОЕ ВОССТАНОВЛЕНИЕ:</b>\nСервер пережил внезапное отключение питания.\n💰 Ваши фишки (<b>{fmt(amount)} ᴜ</b>) спасены из SSD-кэша!",
                                parse_mode="HTML"
                            )
                        except: pass
            print(f"🛡 Успешно восстановлено {len(refunds)} балансов из SSD-дампа!")
        
    except Exception as e:
        print(f"❌ Ошибка восстановления из SSD-дампа: {e}")
    finally:
        _delete_ssd_backup_sync()

# ==========================================
# 🛑 ЯДРО СПАСЕНИЯ АКТИВОВ
# ==========================================
async def rescue_all_assets(bot: Bot):
    print("\n⚠️ ВНИМАНИЕ: Запуск ТОТАЛЬНОГО АТОМАРНОГО протокола спасения активов!")
    from core.database import get_db
    pool = await get_db()
    refunds = []
    frozen_msgs = [] 

    try:
        from handlers.games.roulette_game import current_bets, spinning_bets
        for cid in list(current_bets.keys()): 
            for b in current_bets.pop(cid, []): refunds.append((b['user_id'], b['amount'], "Рулетке"))
        for cid in list(spinning_bets.keys()): 
            for b in spinning_bets.pop(cid, []): refunds.append((b['user_id'], b['amount'], "Рулетке"))
    except: pass

    try:
        from handlers.games.mines_game import active_mines
        for uid in list(active_mines.keys()):
            data = active_mines.pop(uid)
            refunds.append((uid, data['bet'], "Минах"))
            if 'message_id' in data and 'chat_id' in data:
                frozen_msgs.append({"chat_id": data['chat_id'], "message_id": data['message_id']})
    except: pass

    try:
        from handlers.games.crash_game import active_flights
        for cid in list(active_flights.keys()):
            flight = active_flights.pop(cid)
            if 'message_id' in flight: frozen_msgs.append({"chat_id": cid, "message_id": flight['message_id']})
            for pid, pdata in flight.get('players', {}).items():
                refunds.append((pid, pdata['bet'], "Краше"))
    except: pass

    try:
        from handlers.games.race_game import active_races
        for cid in list(active_races.keys()):
            race = active_races.pop(cid)
            if 'message_id' in race: frozen_msgs.append({"chat_id": cid, "message_id": race['message_id']})
            for pid, pdata in race.get('players', {}).items():
                refunds.append((pid, pdata['bet'], "Гонках"))
    except: pass

    try:
        from handlers.games.bomb_game import active_bombs
        for cid in list(active_bombs.keys()):
            bomb = active_bombs.pop(cid)
            if 'message_id' in bomb: frozen_msgs.append({"chat_id": cid, "message_id": bomb['message_id']})
            for pid, pdata in bomb.get('players', {}).items():
                refunds.append((pid, pdata['bet'], "Бомбе"))
    except: pass

    try:
        from handlers.games.squid_game import active_squid_games
        for cid in list(active_squid_games.keys()):
            squid = active_squid_games.pop(cid)
            if 'message_id' in squid: frozen_msgs.append({"chat_id": cid, "message_id": squid['message_id']})
            for pid, pdata in squid.get('players', {}).items():
                refunds.append((pid, pdata['bet'], "Кальмаре"))
    except: pass

    if refunds:
        try:
            async with pool.acquire() as db:
                async with db.transaction():
                    for uid, amount, game_name in refunds:
                        await db.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", amount, uid)
            print(f"✅ Успешно спасено {len(refunds)} ставок. Деньги возвращены.")
            
            user_refunds = {}
            for uid, amount, game_name in refunds:
                if uid not in user_refunds: user_refunds[uid] = {'amount': 0, 'games': set()}
                user_refunds[uid]['amount'] += amount
                user_refunds[uid]['games'].add(game_name)

            for uid, data in user_refunds.items():
                games_str = ", ".join(data['games'])
                try: 
                    await bot.send_message(
                        uid, 
                        f"⚙️ <b>РЕСТАРТ СИСТЕМЫ</b>\n━━━━━━━━━━━━━━━━━━━━\n"
                        f"Активные сессии в: <b>{games_str}</b> были прерваны.\n"
                        f"💰 На баланс возвращено: <b>{fmt(data['amount'])} ᴜ</b>",
                        parse_mode="HTML"
                    )
                except: pass
        except Exception as e:
            print(f"❌ КРИТИЧЕСКАЯ ОШИБКА БД ПРИ ВОЗВРАТЕ: {e}")

    return frozen_msgs

# ==========================================
# 🛑 АВТОМАТИЧЕСКИЙ ХУК (При остановке)
# ==========================================
async def on_shutdown(dispatcher: Dispatcher, bot: Bot):
    print("🛑 Инициирован протокол экстренной остановки. Сохраняю данные...")
    
    frozen_messages = await rescue_all_assets(bot)
    
    if frozen_messages:
        os.makedirs("data", exist_ok=True)
        restart_data = {"timestamp": time.time(), "frozen": frozen_messages}
        try:
            with open("data/restart.json", "w", encoding="utf-8") as f:
                json.dump(restart_data, f)
            print("✅ Файл restart.json успешно записан.")
        except Exception as e:
            print(f"❌ Ошибка записи restart.json: {e}")

    try:
        from core.redis_driver import close_redis
        await close_redis()
        print("✅ Подключение к Redis закрыто.")
    except: pass

    print("👋 Все активы в безопасности. Система остановлена.")