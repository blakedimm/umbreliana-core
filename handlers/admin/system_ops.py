# File: handlers/admin/system_ops.py
import os
import sys
import time
import json
import asyncio
import logging
import subprocess
import random
import re
from datetime import datetime

from aiogram import Router, types, F, Bot, BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core import bot_state
from core.database import (
    get_db, resolve_user_id, DB_URL, force_cancel_games
)
from handlers.syndicate.farms import GPUS, get_farm, update_farm

router = Router()
# ==========================================
# 🔐 СИСТЕМНЫЕ ПЕРЕМЕННЫЕ И ДОСТУПЫ (RBAC)
# ==========================================
ADMIN_ID = int(os.getenv("ADMIN_ID", 1412940726))
MODERATORS = [int(i.strip()) for i in os.getenv("MODERATORS", "").split(",") if i.strip()]

def is_moderator(user_id):
    """Проверяет, является ли пользователь Создателем или Модератором"""
    return user_id == ADMIN_ID or user_id in MODERATORS

PG_DUMP_PATH = r"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe"

def fmt(num):
    return f"{int(num):,}".replace(",", " ")

class AdminConfirm(StatesGroup):
    waiting_for_stop_confirm = State()

# ==========================================
# 🔥 УПРАВЛЕНИЕ МОДУЛЯМИ (РУБИЛЬНИК)
# ==========================================
MODULES_FILE = "modules.json"
DEFAULT_MODULES = {
    "ферма": True, "рынок": True, "кланы": True, "кредиты": True,
    "депозит": True, "рулетка": True, "мины": True, "кейсы": True,
    "краш": True, "кальмар": True, "бомба": True, "гонки": True, "сектор": True
}

def load_modules():
    if not os.path.exists(MODULES_FILE):
        with open(MODULES_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_MODULES, f, ensure_ascii=False, indent=4)
        return DEFAULT_MODULES.copy()
    try:
        with open(MODULES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return DEFAULT_MODULES.copy()

def save_modules():
    with open(MODULES_FILE, "w", encoding="utf-8") as f:
        json.dump(SYSTEM_MODULES, f, ensure_ascii=False, indent=4)

SYSTEM_MODULES = load_modules()

# ==========================================
# ⏱ БЕССМЕРТНЫЕ ТАЙМЕРЫ ВКЛЮЧЕНИЯ
# ==========================================
MODULE_TIMERS_FILE = "data/module_timers.json"

def load_module_timers():
    if os.path.exists(MODULE_TIMERS_FILE):
        try:
            with open(MODULE_TIMERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {}

def save_module_timers(timers_data):
    os.makedirs("data", exist_ok=True)
    with open(MODULE_TIMERS_FILE, "w", encoding="utf-8") as f:
        json.dump(timers_data, f, ensure_ascii=False, indent=4)

module_warn_cooldowns = {}

class ModuleStatusMiddleware(BaseMiddleware):
    def __init__(self, module_name: str):
        self.module_name = module_name

    async def __call__(self, handler, event: TelegramObject, data: dict):
        if not SYSTEM_MODULES.get(self.module_name, True):
            handler_obj = data.get("handler")
            if handler_obj:
                func_name = handler_obj.callback.__name__
                if func_name in ["clean_chat_during_race", "pm_garbage_handler"]:
                    return 

            if isinstance(event, Message):
                text = event.text or event.caption or ""
                if not text:
                    return 

                user_id = event.from_user.id
                now = time.time()
                
                if now - module_warn_cooldowns.get(user_id, 0) > 10:
                    module_warn_cooldowns[user_id] = now
                    try:
                        await event.reply(f"🛠 <b>Модуль «{self.module_name.upper()}» временно отключен.</b>\nВедутся технические работы.", parse_mode="HTML")
                    except: pass
                        
            elif isinstance(event, CallbackQuery):
                try:
                    await event.answer(f"🛠 Модуль {self.module_name.upper()} на техобслуживании!", show_alert=True)
                except: pass
                    
            return 

        return await handler(event, data)

async def rescue_module_assets(bot: Bot, module_name: str):
    module_name = module_name.lower()
    print(f"\n⚠️ ВНИМАНИЕ: Запущен протокол сохранения активов для модуля [{module_name.upper()}]")
    if module_name in ["кейсы", "ферма", "кланы", "депозит", "кредиты", "сектор"]:
        return

    pool = await get_db()
    refunds, trade_cancels = [], []

    try:
        if module_name == "рулетка":
            from handlers.games.roulette_game import current_bets, spinning_bets
            for cid in list(current_bets.keys()):
                for b in current_bets.pop(cid, []): refunds.append((b['user_id'], b['amount'], "Рулетка отключена"))
            for cid in list(spinning_bets.keys()):
                for b in spinning_bets.pop(cid, []): refunds.append((b['user_id'], b['amount'], "Рулетка отключена"))
        elif module_name == "мины":
            from handlers.games.mines_game import active_mines
            for uid in list(active_mines.keys()): refunds.append((uid, active_mines.pop(uid)['bet'], "Мины отключены"))
        elif module_name == "краш":
            from handlers.games.crash_game import active_flights
            for cid in list(active_flights.keys()):
                for pid, pdata in active_flights.pop(cid).get('players', {}).items(): refunds.append((pid, pdata['bet'], "Краш отключен"))
        elif module_name == "кальмар":
            from handlers.games.squid_game import active_squid_games
            for cid in list(active_squid_games.keys()):
                for pid, pdata in active_squid_games.pop(cid).get('players', {}).items(): refunds.append((pid, pdata['bet'], "Кальмар отключен"))
        elif module_name == "бомба":
            from handlers.games.bomb_game import active_bombs
            for cid in list(active_bombs.keys()):
                for pid, pdata in active_bombs.pop(cid).get('players', {}).items(): refunds.append((pid, pdata['bet'], "Бомба обезврежена"))
        elif module_name == "гонки":
            from handlers.games.race_game import active_races
            for cid in list(active_races.keys()):
                for pid, pdata in active_races.pop(cid).get('players', {}).items(): refunds.append((pid, pdata['bet'], "Заезд отменен"))
        elif module_name == "рынок":
            from handlers.economy.trade import ACTIVE_TRADES
            for tid in list(ACTIVE_TRADES.keys()): trade_cancels.append(ACTIVE_TRADES.pop(tid))
    except Exception as e:
        print(f"❌ Ошибка при сборе данных модуля {module_name.upper()}: {e}")
        return

    if not refunds and not trade_cancels: return

    if refunds:
        try:
            async with pool.acquire() as db:
                async with db.transaction():
                    for uid, amount, msg in refunds:
                        await db.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", amount, uid)
            print(f"✅ БД: Успешно возвращено {len(refunds)} ставок.")
        except Exception as e:
            print(f"❌ Ошибка БД при спасении модуля: {e}")
            return

    user_refunds = {}
    for uid, amount, msg in refunds: user_refunds[uid] = user_refunds.get(uid, 0) + amount

    for uid, total_amount in user_refunds.items():
        try: 
            await bot.send_message(uid, f"⚙️ <b>СИСТЕМА:</b> Модуль <b>{module_name.upper()}</b> временно отключен.\n💰 Ваша сумма в размере <b>{fmt(total_amount)} ᴜ</b> возвращена на баланс.", parse_mode="HTML")
        except: pass
        
    for trade in trade_cancels:
        cancel_msg = "🛑 <b>ОБМЕН ПРЕРВАН:</b> Модуль рынка отключен Архитектором. Активы остались при вас."
        try:
            await bot.send_message(trade['u1_id'], cancel_msg, parse_mode="HTML")
            await bot.send_message(trade['u2_id'], cancel_msg, parse_mode="HTML")
        except: pass

@router.message(AdminConfirm.waiting_for_stop_confirm, F.from_user.id == ADMIN_ID)
async def cmd_stop_bot_confirm(message: types.Message, state: FSMContext, bot: Bot):
    if message.text == "666":
        await message.reply("💀 <b>СИСТЕМА ОТКЛЮЧЕНА АРХИТЕКТОРОМ.</b> Запускаю протокол спасения...", parse_mode="HTML")
        await state.clear()
        from core.system_tasks import rescue_all_assets
        await rescue_all_assets(bot)
        os._exit(0)
    else:
        await message.reply("✅ Отмена. Неверный код.")
        await state.clear()

@router.message(F.text.lower().in_(["перезагрузка бота", "перезагрузить бота", "перезапуск бота", "рестарт бота"]), F.from_user.id == ADMIN_ID)
async def cmd_restart_bot(message: types.Message):
    msg = await message.answer("⚙️ <b>[□□□□□□□] Инициализация протокола рестарта...</b>", parse_mode="HTML")

    # --------------------------------------------------
    # ЭТАП 1: АСИНХРОННЫЙ ВАЛИДАТОР (AST)
    # --------------------------------------------------
    await msg.edit_text("⚙️ <b>[■□□□□□□] Этап 1: Умное сканирование структуры (AST)...</b>", parse_mode="HTML")
    
    proc_val = await asyncio.create_subprocess_exec(
        sys.executable, "validator.py",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )
    stdout_val, _ = await proc_val.communicate()
    
    if proc_val.returncode != 0:
        errors = stdout_val.decode("utf-8", errors="replace").strip()
        if len(errors) > 800: errors = errors[-800:] + "\n(Лог обрезан, показан конец)"
        return await msg.edit_text(
            f"❌ <b>РЕСТАРТ ЗАБЛОКИРОВАН ВАЛИДАТОРОМ!</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"Обнаружены битые импорты:\n<code>{errors.replace('<', '[').replace('>', ']')}</code>\n\n"
            f"<i>Бот продолжает работу. Исправь код.</i>", 
            parse_mode="HTML"
        )

    # --------------------------------------------------
    # ЭТАП 2: АСИНХРОННЫЙ КРАШ-ТЕСТ (DRY-RUN)
    # --------------------------------------------------
    await msg.edit_text("⚙️ <b>[■■□□□□□] Этап 2: Теневой краш-тест (Dry-Run)...</b>", parse_mode="HTML")
    
    env = os.environ.copy()
    env["DRY_RUN"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    
    proc_dry = await asyncio.create_subprocess_exec(
        sys.executable, "gram.py",
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )
    stdout_dry, _ = await proc_dry.communicate()
    
    if proc_dry.returncode != 0:
        errors = stdout_dry.decode("utf-8", errors="replace").strip()
        if len(errors) > 800: errors = errors[-800:] + "\n(Лог обрезан, показан конец)"
        return await msg.edit_text(
            f"❌ <b>РЕСТАРТ ЗАБЛОКИРОВАН КРАШ-ТЕСТОМ!</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"Ошибка:\n<code>{errors.replace('<', '[').replace('>', ']')}</code>\n\n"
            f"<i>Бот продолжает работу. Исправь код.</i>", 
            parse_mode="HTML"
        )

    # --------------------------------------------------
    # ЭТАП 3: ОСТАНОВКА И СБОР ДАННЫХ
    # --------------------------------------------------
    await msg.edit_text("⚙️ <b>[■■■□□□□] Блокировка новых действий...</b>", parse_mode="HTML")
    bot_state.IS_SHUTTING_DOWN = True

    await msg.edit_text("⚙️ <b>[■■■■□□□] Ожидание завершения фоновых задач...</b>", parse_mode="HTML")
    try:
        from gram import scheduler 
        scheduler.shutdown(wait=True) 
    except Exception as e: 
        print(f"⚠️ Ошибка остановки планировщика: {e}")

    await msg.edit_text("⚙️ <b>[■■■■■□□] Эвакуация активов в БД...</b>", parse_mode="HTML")
    try: 
        from core.system_tasks import rescue_all_assets 
        frozen_games = await rescue_all_assets(message.bot) 
        if frozen_games:
            bot_state.FROZEN_ANIMATIONS.extend(frozen_games)
    except Exception as e: 
        print(f"❌ Ошибка при эвакуации: {e}")

    await msg.edit_text("⚙️ <b>[■■■■■■□] Создание точки возврата...</b>", parse_mode="HTML")
    disabled_modules = [m for m, state in SYSTEM_MODULES.items() if not state]
    restart_data = {
        "version": 1.0, "timestamp": int(time.time()),
        "chat_id": msg.chat.id, "message_id": msg.message_id,
        "frozen": bot_state.FROZEN_ANIMATIONS
    }
    
    os.makedirs("data", exist_ok=True)
    with open("data/restart.json.tmp", "w", encoding="utf-8") as f: 
        json.dump(restart_data, f)
    os.replace("data/restart.json.tmp", "data/restart.json")

    mod_warn = f"\n⚠️ <i>Отключено модулей: {len(disabled_modules)}</i>" if disabled_modules else ""
    await msg.edit_text(f"⚙️ <b>[■■■■■■■] ПЕРЕЗАПУСК СИСТЕМЫ...</b>\nПересборка ОЗУ ноды. До встречи в сети.{mod_warn}", parse_mode="HTML")
    
    await message.bot.session.close()
    try:
        from core.database import db_pool 
        if db_pool: await db_pool.close() 
    except: pass

    # 🔥 ЖЕЛЕЗНЫЙ АНТИ-КЭШ И ФИКС ДВОЙНОГО ПРОЦЕССА ДЛЯ WINDOWS И PM2:
    # Мы полностью убираем os.execv, который плодил скрытые зомби-процессы Питона в Win32-подсистеме.
    # Чисто завершаем текущий процесс. PM2 или батник-цикл мгновенно увидят это завершение, 
    # выгрузят старый образ из ОЗУ и поднимут ОДИН чистый, свежий процесс с новым кодом!
    os._exit(0)


# ==========================================
# 🎛 АДМИН: УПРАВЛЕНИЕ МОДУЛЯМИ
# ==========================================
@router.message(F.text.lower().startswith("отключить модуль "), F.from_user.id == ADMIN_ID)
async def cmd_disable_module_advanced(message: types.Message, bot: Bot):
    match = re.search(r"отключить модуль ([\w]+)(?: на (\d+) минут)?", message.text.lower())
    if not match: return await message.reply("❌ Формат: <code>отключить модуль рулетка на 30 минут</code>", parse_mode="HTML")
    
    module_name = match.group(1)
    duration_mins = int(match.group(2)) if match.group(2) else None

    if module_name not in SYSTEM_MODULES: return await message.reply(f"❌ Модуль <b>{module_name}</b> не найден.", parse_mode="HTML")

    await message.reply(f"⚠️ <b>ВНИМАНИЕ!</b>\nМодуль <b>{module_name.upper()}</b> будет отключен через 5 сек для техработ!", parse_mode="HTML")
    await asyncio.sleep(5) 

    SYSTEM_MODULES[module_name] = False
    save_modules()
    await rescue_module_assets(bot, module_name)
    
    msg_text = f"🔴 Модуль <b>{module_name.upper()}</b> отключен!"
    
    if duration_mins: 
        enable_at = int(time.time()) + (duration_mins * 60)
        msg_text += f"\n⏳ Авто-включение через <b>{duration_mins} мин.</b>"
        
        timers = load_module_timers()
        timers[module_name] = {"enable_at": enable_at, "chat_id": message.chat.id}
        save_module_timers(timers)
        
        asyncio.create_task(auto_enable_module(bot, module_name, enable_at, message.chat.id))
        
    await message.answer(msg_text, parse_mode="HTML")

async def auto_enable_module(bot: Bot, module_name: str, enable_at: int, chat_id: int):
    now = int(time.time())
    delay_sec = enable_at - now
    
    if delay_sec > 0:
        await asyncio.sleep(delay_sec)
        
    timers = load_module_timers()
    if module_name not in timers or timers[module_name]["enable_at"] != enable_at:
        return 

    if module_name in SYSTEM_MODULES:
        SYSTEM_MODULES[module_name] = True
        save_modules()
        
        del timers[module_name]
        save_module_timers(timers)
        
        try: await bot.send_message(chat_id, f"✅ <b>МОДУЛЬ {module_name.upper()} СНОВА В СТРОЮ!</b>\n════════════════════\nТехнические работы завершены.", parse_mode="HTML")
        except: pass
        try: await bot.send_message(ADMIN_ID, f"⚙️ <b>ПЛАНИРОВЩИК:</b> Модуль {module_name} успешно включен.")
        except: pass

@router.message(F.text.lower().startswith("включить модуль "), F.from_user.id == ADMIN_ID)
async def cmd_enable_module(message: types.Message):
    module_name = message.text.lower().replace("включить модуль ", "").strip()
    if module_name in SYSTEM_MODULES:
        SYSTEM_MODULES[module_name] = True
        save_modules() 
        
        timers = load_module_timers()
        if module_name in timers:
            del timers[module_name]
            save_module_timers(timers)
            
        await message.reply(f"🟢 Модуль <b>{module_name.upper()}</b> активирован!", parse_mode="HTML")
    else:
        await message.reply(f"❌ Модуль не найден.")

@router.message(F.text.lower() == "статус модулей", F.from_user.id == ADMIN_ID)
async def cmd_modules_status(message: types.Message):
    text = "🎛 <b>СТАТУС МОДУЛЕЙ:</b>\n════════════════════\n"
    for mod, state in SYSTEM_MODULES.items():
        text += f"├ <b>{mod.capitalize()}</b>: {'🟢 Вкл' if state else '🔴 Выкл'}\n"
    await message.reply(text, parse_mode="HTML")

# ==========================================
# 🎛 ИНТЕРАКТИВНЫЙ ПУЛЬТ АРХИТЕКТОРА
# ==========================================
@router.message(F.text.lower().in_(["модули", "пульт", "управление модулями"]), F.from_user.id == ADMIN_ID)
async def cmd_interactive_modules(message: types.Message):
    await send_modules_panel(message)

async def send_modules_panel(message_or_callback):
    builder = InlineKeyboardBuilder()
    
    for mod_name, state in SYSTEM_MODULES.items():
        icon = "🟢" if state else "🔴"
        builder.button(text=f"{icon} {mod_name.capitalize()}", callback_data=f"mod_toggle_{mod_name}")
    
    builder.adjust(2)
    
    text = (
        "🎛 <b>ГЛАВНЫЙ РУБИЛЬНИК СИСТЕМЫ</b>\n"
        "════════════════════\n"
        "<i>Нажми на модуль, чтобы экстренно включить или отменить его.</i>"
    )
    
    if isinstance(message_or_callback, types.Message):
        await message_or_callback.reply(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    else:
        await message_or_callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("mod_toggle_"), F.from_user.id == ADMIN_ID)
async def cb_toggle_module(callback: types.CallbackQuery, bot: Bot):
    mod_name = callback.data.replace("mod_toggle_", "")
    
    if mod_name not in SYSTEM_MODULES:
        return await callback.answer("Ошибка: модуль не найден!", show_alert=True)
    
    current_state = SYSTEM_MODULES[mod_name]
    new_state = not current_state
    
    SYSTEM_MODULES[mod_name] = new_state
    save_modules()
    
    if new_state:
        await callback.answer(f"✅ Модуль {mod_name.upper()} ВКЛЮЧЕН!", show_alert=True)
    else:
        await callback.answer(f"🚨 Модуль {mod_name.upper()} ОТКЛЮЧЕН! Эвакуирую активы...", show_alert=True)
        asyncio.create_task(rescue_module_assets(bot, mod_name))
        
    await send_modules_panel(callback)

# ==========================================
# ⚙️ СИСТЕМНЫЕ УТИЛИТЫ И ОТКАТЫ
# ==========================================
@router.message((F.text.lower() == "бэкап") & (F.from_user.id == ADMIN_ID))
async def admin_backup(message: types.Message):
    msg = await message.reply("⏳ Создаю полный дамп базы данных PostgreSQL...")
    backup_file = f"backup_{datetime.now().strftime('%d_%m_%H_%M')}.sql"
    try:
        subprocess.run([PG_DUMP_PATH, DB_URL, '-f', backup_file], check=True)
        await message.reply_document(FSInputFile(backup_file), caption=f"📦 Бэкап БД Umbreliana\nВремя: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        if os.path.exists(backup_file): os.remove(backup_file)
        await msg.delete()
    except subprocess.CalledProcessError as e: await msg.edit_text(f"❌ <b>Ошибка:</b>\n<code>{e}</code>", parse_mode="HTML")
    except FileNotFoundError: await msg.edit_text(f"❌ <b>Файл pg_dump.exe не найден!</b>", parse_mode="HTML")
    except Exception as e: await msg.edit_text(f"❌ <b>Критическая ошибка бэкапа:</b>\n<code>{e}</code>", parse_mode="HTML")

@router.message(F.text.lower().startswith("откатить") & (F.from_user.id == ADMIN_ID))
async def cmd_admin_rollback(message: types.Message):
    text = message.text.lower().replace("откатить", "").strip()
    seconds = 0
    
    h_match = re.search(r'(\d+)\s*(ч|h|час)', text)
    m_match = re.search(r'(\d+)\s*(м|m|мин)', text)
    s_match = re.search(r'(\d+)\s*(с|s|сек)', text)
    
    if h_match: seconds += int(h_match.group(1)) * 3600
    if m_match: seconds += int(m_match.group(1)) * 60
    if s_match: seconds += int(s_match.group(1))
    if seconds == 0 and text.isdigit(): seconds = int(text) * 60

    if seconds <= 0: return await message.reply("⚠️ <b>Укажи время для отката!</b>", parse_mode="HTML")

    start_time = int(time.time()) - seconds
    done_users, done_clans, done_items = 0, 0, 0

    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            logs = await db.fetch("SELECT id, user_id, clan_id, type, amount, target_id FROM audit_log WHERE timestamp >= $1 ORDER BY timestamp DESC", start_time)
            if logs:
                for log in logs:
                    if log['type'] in ['user_balance', 'earned_income', 'system_transfer']:
                        await db.execute("UPDATE users SET balance = balance - $1 WHERE user_id = $2", log['amount'], log['user_id'])
                        done_users += 1
                    elif log['type'] == 'clan_balance':
                        await db.execute("UPDATE clans SET balance = balance - $1 WHERE id = $2", log['amount'], log['clan_id'])
                        done_clans += 1
                    elif log['type'] == 'buy_gpu' and log['target_id'] != 'none':
                        await db.execute(f"UPDATE farms SET {log['target_id']} = GREATEST(0, {log['target_id']} - $1) WHERE user_id = $2", log['amount'], log['user_id'])
                        done_items += 1
                await db.execute("DELETE FROM audit_log WHERE timestamp >= $1", start_time)

            await db.execute("DELETE FROM user_game_history WHERE timestamp >= $1", start_time)
            await db.execute("DELETE FROM trade_history WHERE timestamp >= $1", start_time)
            await db.execute("DELETE FROM transfers WHERE timestamp >= $1", start_time)

    h, remainder = divmod(seconds, 3600)
    m, s = divmod(remainder, 60)
    time_str = f"{h}ч {m}м {s}с".replace("0ч ", "").replace("0м ", "").strip()

    await message.reply(
        f"⏪ <b>ГЛОБАЛЬНЫЙ ОТКАТ ВРЕМЕНИ</b>\n════════════════════\n"
        f"⏳ Сервер отмотан на: <b>{time_str}</b> назад.\n👤 Отменено транзакций: <b>{done_users}</b>\n"
        f"🏴‍☠️ Отменено транзакций кланов: <b>{done_clans}</b>\n📦 Отменено покупок: <b>{done_items}</b>\n\n"
        f"<i>🎲 История казино, трейдов и переводов стёрта.</i>", parse_mode="HTML"
    )

@router.message((F.text.lower() == "фикс бд") & (F.from_user.id == ADMIN_ID))
async def fix_database_schema(message: types.Message):
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute("ALTER TABLE farms ADD COLUMN IF NOT EXISTS last_wear_update BIGINT DEFAULT 0")
        await db.execute("ALTER TABLE daily_bonus ADD COLUMN IF NOT EXISTS topups_today INTEGER DEFAULT 0")
    await message.reply("✅ БД обновлена.")

@router.message((F.text.lower() == "чистка инвентаря") & (F.from_user.id == ADMIN_ID))
async def clean_ghosts_global(message: types.Message):
    status_msg = await message.reply("🔄 Зачистка...")
    pool = await get_db()
    fixed = 0
    async with pool.acquire() as db:
        all_farms = await db.fetch("SELECT * FROM farms")
        for farm in all_farms:
            uid = farm['user_id']
            for i in GPUS:
                gid = f"gpu_{i}"
                true_c = farm[gid]
                batch_c = await db.fetchval("SELECT SUM(qty) FROM gpu_batches WHERE user_id = $1 AND gpu_id = $2", uid, gid) or 0
                if true_c != batch_c:
                    await db.execute("DELETE FROM gpu_batches WHERE user_id = $1 AND gpu_id = $2", uid, gid)
                    if true_c > 0:
                        await db.execute("INSERT INTO gpu_batches (user_id, gpu_id, multiplier, qty, condition) VALUES ($1, $2, 1.0, $3, 100.0)", uid, gid, true_c)
                    fixed += 1
    await status_msg.edit_text(f"🧹 Исправлено юзеров: {fixed}")

@router.message(F.text.lower().startswith("снести клан ") & (F.from_user.id == ADMIN_ID))
async def admin_delete_clan(message: types.Message):
    parts = message.text.split()
    if len(parts) < 3: return
    clan_id = int(parts[2])
    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            await db.execute("DELETE FROM clans WHERE id = $1", clan_id)
            await db.execute("UPDATE users SET clan_id = 0 WHERE clan_id = $1", clan_id)
    await message.reply("💥 Клан уничтожен.")

@router.message(F.text.lower().startswith("сменить босса ") & (F.from_user.id == ADMIN_ID))
async def admin_change_clan_boss(message: types.Message):
    parts = message.text.split()
    if len(parts) < 4: return
    clan_id, target_id = int(parts[2]), await resolve_user_id(parts[3])
    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            await db.execute("UPDATE clans SET owner_id = $1 WHERE id = $2", target_id, clan_id)
            await db.execute("UPDATE users SET clan_id = $1 WHERE user_id = $2", clan_id, target_id)
    await message.reply("👑 Босс сменен.")

@router.message(F.text.lower().startswith("поставить рынок ") & (F.from_user.id == ADMIN_ID))
async def cmd_admin_random_market(message: types.Message):
    try: count = int(message.text.lower().replace("поставить рынок ", "").strip())
    except ValueError: return await message.reply("⚠️ Ошибка числа!")
    if count <= 0 or count > 100: return await message.reply("❌ Лимит: от 1 до 100 лотов.")

    lots_added, total_value, pearls_count, traps_count = 0, 0, 0, 0
    added_lots_text, vip_deals = [], []

    gpu_ids = [k for k, v in GPUS.items() if k < 100 and v['price'] <= 100_000_000]

    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            for _ in range(count):
                gpu_num = random.choice(gpu_ids)
                gpu = GPUS[gpu_num]
                gpu_id_str, qty = f"gpu_{gpu_num}", random.randint(1, 5) 
                condition = round(random.uniform(10.0, 100.0), 1)
                
                base_value = (gpu['price'] * qty) * (condition / 100.0)
                
                if random.random() < 0.15:
                    suggest_price, deal_type = int(base_value * random.uniform(0.7, 0.85)), "💎"
                    pearls_count += 1
                    vip_deals.append(f"💎 <b>{gpu['name']} (x{qty})</b> | {condition}% | 💰 <b>{fmt(suggest_price)} ᴜ</b>")
                else:
                    suggest_price, deal_type = int(base_value * random.uniform(1.05, 1.25)), "😈"
                    traps_count += 1
                    
                suggest_price = max(suggest_price, 1000) 
                    
                await db.execute("""
                    INSERT INTO market (seller_id, gpu_id, price, qty, condition, created_at, deposit) 
                    VALUES (0, $1, $2, $3, $4, $5, 0)
                """, gpu_id_str, suggest_price, qty, condition, int(time.time()))
                
                lots_added += 1
                total_value += suggest_price
                if len(added_lots_text) < 20:
                    added_lots_text.append(f"{deal_type} {gpu.get('emoji', '🖥')} <b>{gpu['name']} (x{qty})</b> | 🔧 {condition}% | 💰 {fmt(suggest_price)} ᴜ")

    lots_display = "\n".join(added_lots_text)
    if count > 20: lots_display += f"\n<i>...и ещё {count - 20} лотов скрыто.</i>"

    await message.reply(f"🚛 <b>ГОС. ПОСТАВКА ВЫПОЛНЕНА!</b>\n📦 Лотов: <b>{lots_added}</b> (💎:{pearls_count} | 😈:{traps_count})\n📋 <b>Превью:</b>\n{lots_display}", parse_mode="HTML")

    if vip_deals:
        from handlers.users.statuses import get_vip_market_subscribers
        async def notify_vips():
            vips = await get_vip_market_subscribers()
            if not vips: return
            deals_list = "\n".join(vip_deals[:15])
            text = f"🚨 <b>ИНСАЙД: ГОС. ПОСТАВКА!</b>\nКоннор вывалил жемчужины на рынок:\n\n{deals_list}\n\n<i>🏃‍♂️ Беги выкупать!</i>"
            for vid in vips:
                if vid == message.from_user.id: continue
                try: 
                    await message.bot.send_message(vid, text, parse_mode="HTML")
                    await asyncio.sleep(0.05)
                except: pass
        asyncio.create_task(notify_vips())

@router.message(F.text.lower() == "отключить турнир", F.from_user.id == ADMIN_ID)
async def admin_stop_tournament_global(message: types.Message):
    confirm_msg = await message.answer("🔄 <i>Запуск процесса глобальной разморозки...</i>", parse_mode="HTML")
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute("UPDATE users SET in_tournament = FALSE")

    try:
        from core.middlewares import tournament_cache
        tournament_cache.clear()
        cache_status = "✅ Кэш очищен."
    except Exception as e:
        cache_status = f"⚠️ Ошибка очистки кэша: {e}"

    await confirm_msg.edit_text(f"🚨 <b>ТУРНИР ЗАВЕРШЕН</b> 🚨\n━━━━━━━━━━━━━━━━━━━━\n• Все игроки разморожены.\n• {cache_status}\n\n<b>Все пользователи теперь могут играть в обычном режиме!</b>", parse_mode="HTML")

@router.message(F.text.lower().startswith("отмена игр"), F.from_user.id == ADMIN_ID)
async def cmd_admin_force_cancel_games(message: types.Message):
    target_id, target_name = None, "Всем"
    if message.reply_to_message:
        target_id, target_name = message.reply_to_message.from_user.id, message.reply_to_message.from_user.first_name
    else:
        args = message.text.split()
        if len(args) > 2: 
            raw_target = args[2].replace("@", "")
            if raw_target.isdigit():
                target_id, target_name = int(raw_target), f"Игроку {raw_target}"
            else:
                pool = await get_db()
                async with pool.acquire() as db:
                    row = await db.fetchval("SELECT user_id FROM users WHERE telegram_username ILIKE $1", raw_target)
                    if row: target_id, target_name = row, f"@{raw_target}"
                    else: return await message.reply("❌ Игрок не найден.")
        elif message.text.lower().strip() != "отмена игр": return

    refunded, users_count = await force_cancel_games(target_id)
    if target_id:
        if refunded > 0: await message.reply(f"🎯 <b>ТОЧЕЧНАЯ ОТМЕНА АКТИВИРОВАНА</b>\nЦель: <b>{target_name}</b>\n💰 Возвращено: <b>{fmt(refunded)} ᴜ</b>", parse_mode="HTML")
        else: await message.reply(f"👀 У <b>{target_name}</b> нет ставок.", parse_mode="HTML")
    else:
        if refunded > 0: await message.reply(f"🚨 <b>ГЛОБАЛЬНЫЙ АНТИ-АБУЗ</b>\nПоймано: <b>{users_count} чел.</b>\n💰 Возвращено: <b>{fmt(refunded)} ᴜ</b>", parse_mode="HTML")
        else: await message.reply("👀 Сервер чист. Казино пустуют.")