# File: main.py
import asyncio  # Используется для асинхронной рассылки пуш-уведомлений
import os
import sys
import logging
import json
import time

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from logging.handlers import RotatingFileHandler

# ==========================================
# 🔥 CORE И СИСТЕМНЫЕ ЗАДАЧИ
# ==========================================
from core.database import init_db
from core.redis_driver import init_redis
from core.triggers import INTERACTION_TRIGGERS
from core.l10n import L10nMiddleware 

# ⚡️ МОДУЛЬНЫЕ ИНИЦИАЛИЗАЦИИ БАЗ ДАННЫХ
from handlers.economy.deposit_engine import init_deposit_db
from handlers.economy.donate import init_donate_db
from handlers.economy.trade import init_trade_db
from handlers.users.statuses import init_statuses_db
from handlers.users.quests import init_quests_db
from handlers.games.roulette_game import init_roulette, init_history_db
from handlers.syndicate.farms import add_golden_columns

from core.backuper import create_backup
from core.middlewares import (
    ShutdownMiddleware, RateLimitMiddleware, AntiChannelMiddleware,
    BanMiddleware, SubMiddleware, ActivityTrackerMiddleware, TournamentLockMiddleware
)
from core.system_tasks import (
    market_reaper, recover_from_hard_crash, on_shutdown, global_error_handler, infra_auto_healer
)

# ==========================================
# 📂 HANDLERS (РОУТЕРЫ)
# ==========================================
from handlers.admin import router as admin_router, ModuleStatusMiddleware

from handlers.users.statuses import router as statuses_router
from handlers.users.quests import router as quests_router
from handlers.users.tutorial import router as tutorial_router
from handlers.users.rating_system import router as rating_router
from handlers.users.tops import router as tops_router
from handlers.users.widgets import router as widgets_router
from handlers.users.titles import router as titles_router 
from handlers.users.nicks import router as nicks_router
from handlers.users.language import router as language_router

from handlers.economy.trade import router as trade_router
from handlers.economy.market import router as market_router
from handlers.economy.deposit_engine import router as deposit_router
from handlers.economy.donate import router as donate_router
from handlers.economy.loans import router as loans_router, debt_reaper
from handlers.economy.transfers import router as transfers_router
from handlers.economy.bonus import router as bonus_router
# 🔥 ИМПОРТ МОДУЛЯ КРИПТОВАЛЮТЫ UMC
from handlers.economy.crypto import router as crypto_router, update_crypto_market

from handlers.syndicate.clans import router as clans_router
from handlers.syndicate.farms import farm_router
from handlers.games.squid_game import router as squid_router
from handlers.games.cases_game import router as cases_router
from handlers.games.button_game import router as button_router
from handlers.games.race_game import router as race_router
from handlers.games.bomb_game import router as bomb_router
from handlers.games.crash_game import router as crash_router
from handlers.games.mines_game import router as mines_router
from handlers.games.roulette_game import router as roulette_router
from handlers.games.crazy_wheel import router as wheel_router
from handlers.games.sector import router as sector_router
from handlers.events.events_engine import router as events_router, global_event_monitor, global_chaos_loop
from handlers.economy.gold import router as gold_router
from handlers.economy.gold_shop import router as gold_shop_router
from handlers.economy.gold_farm import router as gold_farm_router

# ==========================================
# 🔥 НАСТРОЙКИ И ЛОГГЕР (УЛУЧШЕННЫЙ АНТИ-СПАМ)
# ==========================================
load_dotenv()
TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 1412940726))

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# Гарантируем наличие папки под логи
os.makedirs("logs", exist_ok=True)
os.makedirs("data", exist_ok=True)

log_format = '%(asctime)s - %(levelname)s - [ФАЙЛ: %(module)s.py | СТРОКА: %(lineno)d] - %(message)s'
file_formatter = logging.Formatter(log_format)

root_logger = logging.getLogger()
root_logger.setLevel(logging.WARNING) 

if root_logger.hasHandlers():
    root_logger.handlers.clear()

file_handler = RotatingFileHandler("logs/bot_errors.log", maxBytes=5*1024*1024, backupCount=5, encoding='utf-8')
file_handler.setFormatter(file_formatter)
console_handler = logging.StreamHandler()
console_handler.setFormatter(file_formatter)

root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

logger = logging.getLogger("Umbreliana")
logger.setLevel(logging.INFO)

logging.getLogger("aiogram.event").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("html2image").setLevel(logging.ERROR)

# ==========================================
# 🔥 ИНИЦИАЛИЗАЦИЯ ГЛОБАЛЬНОГО ПЛАНИРОВЩИКА
# ==========================================
scheduler = AsyncIOScheduler()  # <-- ВОТ ОН, РОДНОЙ! ТЕПЕРЬ ОН ЕСТЬ В СЕТИ!

async def set_commands(bot_instance):
    commands = [
        BotCommand(command="start", description="Перезапустить бота / Restart bot"),
        BotCommand(command="balance", description="Проверить кошелек UMBREL / Check balance"),
        BotCommand(command="language", description="Сменить язык / Change language"),
        BotCommand(command="help", description="Открыть Базу Знаний / Open Help Wiki"),
        BotCommand(command="top", description="Рейтинг магнатов / Top rich ledger"),
        BotCommand(command="top_farms", description="Топ промышленных гигантов / Top active farms")
    ]
    await bot_instance.set_my_commands(commands)

# ==========================================
# ⚙️ ФАЗЫ ИНИЦИАЛИЗАЦИИ
# ==========================================
async def setup_db():
    INIT_STEPS = [
        init_db, 
        add_golden_columns, 
        init_deposit_db, 
        init_donate_db, 
        init_trade_db,
        init_statuses_db,
        init_quests_db,
        init_history_db, 
        init_roulette
    ]
    for step in INIT_STEPS:
        try:
            await step()
        except Exception as e:
            logger.error(f"❌ Ошибка в шаге БД {step.__name__}: {e}")
            
    logger.info("✅ База данных инициализирована.")

def setup_middlewares(dispatcher: Dispatcher):
    dispatcher.errors.register(global_error_handler)
    dispatcher.update.middleware(ShutdownMiddleware())
    
    for r in (dispatcher.message, dispatcher.callback_query):
        r.middleware(TournamentLockMiddleware())
        r.middleware(RateLimitMiddleware())        
        r.middleware(AntiChannelMiddleware())      
        r.middleware(BanMiddleware())              
        r.middleware(SubMiddleware())              
        r.middleware(ActivityTrackerMiddleware())
        r.middleware(L10nMiddleware())
    logger.info("✅ Защитные щиты (Middlewares) активированы.")

def setup_routers(dispatcher: Dispatcher):
    farm_router.module_name = "ферма"
    market_router.module_name = "рынок"
    clans_router.module_name = "кланы"
    loans_router.module_name = "кредиты"
    deposit_router.module_name = "депозит"
    roulette_router.module_name = "рулетка"
    mines_router.module_name = "мины"
    cases_router.module_name = "кейсы"
    crash_router.module_name = "краш"
    squid_router.module_name = "кальмар"
    bomb_router.module_name = "бомба"
    race_router.module_name = "гонки"
    quests_router.module_name = "квесты"
    wheel_router.module_name = "колесо"
    tutorial_router.module_name = "обучение"
    titles_router.module_name = "титулы"
    gold_router.module_name = "золото"         
    gold_shop_router.module_name = "теневой рынок" 
    gold_farm_router.module_name = "ферма голд"
    nicks_router.module_name = "ники"
    sector_router.module_name = "сектор"
    crypto_router.module_name = "биржа"

    all_routers = [
        language_router, 
        crypto_router, 
        sector_router,
        gold_router, gold_shop_router, gold_farm_router, 
        titles_router, nicks_router,
        widgets_router, quests_router, transfers_router,
        tops_router, bonus_router, rating_router, trade_router,
        deposit_router, donate_router, statuses_router, cases_router,
        events_router, market_router, clans_router, button_router,
        squid_router, admin_router, farm_router, mines_router,
        roulette_router, loans_router, wheel_router, crash_router,
        bomb_router, race_router, tutorial_router
    ]

    for r in all_routers:
        if hasattr(r, 'module_name'):
            r.message.middleware(ModuleStatusMiddleware(r.module_name))
            r.callback_query.middleware(ModuleStatusMiddleware(r.module_name))
        dispatcher.include_router(r)
    logger.info(f"✅ Подключено {len(all_routers)} роутеров.")

def setup_scheduler(bot_instance: Bot):
    scheduler.add_job(debt_reaper, "interval", minutes=10, args=(bot_instance,))
    scheduler.add_job(market_reaper, "interval", minutes=20, args=(bot_instance,))
    scheduler.add_job(create_backup, "interval", hours=1, args=(bot_instance, ADMIN_ID, True))
    
    # 🔥 АКТИВАЦИЯ ДВИЖКА КРИПТЫ: запуск тика рынка каждые 2 часа
    scheduler.add_job(update_crypto_market, "interval", hours=2, args=(bot_instance,))
    
    scheduler.start()
    logger.info("✅ Планировщик задач (Scheduler) запущен.")

async def safe_task(coro):
    try:
        await coro
    except Exception as e:
        logger.error(f"❌ ФОНОВАЯ ЗАДАЧА УПАЛА: {e}", exc_info=True)

def start_background_tasks(bot_instance: Bot):
    asyncio.create_task(safe_task(global_chaos_loop(bot_instance)))
    asyncio.create_task(safe_task(global_event_monitor(bot_instance)))
    # 🔥 ИНТЕГРАЦИЯ СИСТЕМЫ САМОЛЕЧЕНИЯ ИНФРАСТРУКТУРЫ В ЯДРО
    asyncio.create_task(safe_task(infra_auto_healer(bot_instance)))
    logger.info("✅ Фоновые задачи запущены.")

async def handle_restart_json(bot_instance: Bot):
    if not os.path.exists("data/restart.json"): return
    try:
        with open("data/restart.json", "r", encoding="utf-8") as f: data = json.load(f)
        if time.time() - data.get("timestamp", 0) > 86400: raise ValueError("Old JSON")
        
        try: await bot_instance.edit_message_text(chat_id=data["chat_id"], message_id=data["message_id"], text="✅ <b>Бот активизирован!</b>\nПерезагрузка прошла на ура.", parse_mode="HTML")
        except Exception: pass

        for f_msg in data.get("frozen", []):
            try: await bot_instance.edit_message_text(chat_id=f_msg["chat_id"], message_id=f_msg["message_id"], text="🛠 <b>ТЕХНИЧЕСКИЙ ПЕРЕЗАПУСК</b>\n━━━━━━━━━━━━━\nИгра прервана.\n💰 <b>Ставки возвращены!</b>", parse_mode="HTML")
            except Exception: pass
    except Exception as e: logger.error(f"Ошибка restart.json: {e}")
    finally:
        for filename in ("data/restart.json", "data/restart.json.tmp"):
            if os.path.exists(filename): os.remove(filename)

async def revive_module_timers(bot_instance: Bot):
    from handlers.admin.system_ops import load_module_timers, auto_enable_module
    timers = load_module_timers()
    if not timers: return
    
    logger.info(f"🔄 Восстановление таймеров модулей: {len(timers)} шт.")
    for mod_name, data in timers.items():
        asyncio.create_task(auto_enable_module(bot_instance, mod_name, data["enable_at"], data["chat_id"]))

# ==========================================
# 🚀 ГЛАВНАЯ ТОЧКА ВХОДА
# ==========================================
async def main():
    print("Начинаю загрузку ядра Umbreliana...")
    
    # 1. Загружаем структуру, роутеры и мидлвари (Проверяем целостность кода)
    setup_middlewares(dp)
    setup_routers(dp)
    
    # 🔥 СВЕРХЗВУКОВОЙ СЕКТОР: Если это краш-тест рестарта, выходим ТУТ!
    # Код проверен, роутеры монолитны. Базу и сеть не трогаем, чтобы не ловить локи.
    if os.getenv("DRY_RUN") == "1":
        print("✅ [DRY-RUN] Глубокое сканирование пройдено! Роутеры и мидлвари в идеальном состоянии.")
        await bot.session.close() 
        sys.exit(0) # Моментальный чистый выход обратно в хэндлер рестарта
        
    # 2. Боевой запуск (Выполняется ТОЛЬКО основным процессом на хостинге)
    await setup_db()
    await init_redis() 
    
    # Очищаем кэш Telegram прямо перед стартом сессии
    logger.info("🧹 Очищаю очередь накопленных сообщений Telegram...")
    await bot.delete_webhook(drop_pending_updates=True)
    await set_commands(bot)
    
    setup_scheduler(bot)
    start_background_tasks(bot)
    
    await handle_restart_json(bot)
    await revive_module_timers(bot)
    await recover_from_hard_crash(bot)
    
    logger.info("🚀 Система готова. Коннор в сети.")
    
    # 🔥 ФИКС: Вшиваем принудительный сброс бэклога апдейтов в сам процесс полинга
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    try:
        dp.shutdown.register(on_shutdown)
        logging.getLogger("aiogram.dispatcher").setLevel(logging.CRITICAL)
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Terminal остановлен.")