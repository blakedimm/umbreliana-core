import asyncio
import io
import random
import os
import logging
import time
import json
from datetime import date

from aiogram.types import BufferedInputFile
from dotenv import load_dotenv

# Aiogram
from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.filters import CommandStart, Command, CommandObject # 🔥 Добавь CommandObject
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from logging.handlers import RotatingFileHandler

# ==========================================
# 🔥 ПЛОСКИЕ ИМПОРТЫ (ВСЕ В ОДНОЙ ПАПКЕ)
# ==========================================
from database import get_db, init_db, check_table_structure, add_missing_columns_safe, add_balance, get_balance, get_top_10_global, get_top_10_local
from middlewares import (
    ShutdownMiddleware,
    RateLimitMiddleware,
    AntiChannelMiddleware,
    BanMiddleware,
    AccessMiddleware
)
from backuper import create_backup

from admin_handlers import router as admin_router
from farm_game import router as farm_router, GPUS
from mines_game import router as mines_router
from roulette_game import router as roulette_router, init_roulette, init_history_db

router = Router()

# Загружаем данные из файла .env
load_dotenv()
TOKEN = os.getenv("TOKEN") 
ADMIN_ID = int(os.getenv("ADMIN_ID"))

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

def fmt(num):
    return f"{int(num):,}".replace(",", " ")

# Настройка логгера
logger = logging.getLogger("TourneyBot")
logger.setLevel(logging.INFO)
logging.getLogger("aiogram.event").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

file_handler = RotatingFileHandler("tourney_errors.log", maxBytes=5*1024*1024, backupCount=5, encoding='utf-8')
file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s')
file_handler.setFormatter(file_formatter)
console_handler = logging.StreamHandler()
console_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# ==========================================
# 🏠 ГЛАВНОЕ МЕНЮ (Турнирное)
# ==========================================
def get_main_reply_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🏭 Ферма")], 
            [KeyboardButton(text="🎁 ПОЛУЧИТЬ 150 000 ᴜ")],
            [KeyboardButton(text="🌐 Чаты"), KeyboardButton(text="🚔 Команды")]
        ],
        resize_keyboard=True, 
        input_field_placeholder="Арена активна..." 
    )

@dp.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    pool = await get_db()
    
    async with pool.acquire() as db:
        # 🔥 Теперь переменная называется user_status, как и просят условия ниже
        user_status = await db.fetchrow("SELECT is_banned, balance FROM users WHERE user_id = $1", user_id)
        
        # 1. Проверка на "черную метку" (дезертирство)
        if user_status and user_status['is_banned']:
            return await message.answer(
                "🚫 <b>ДОСТУП ЗАБЛОКИРОВАН</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Ты покинул Арену по собственной воле. Дезертирам вход на турнир закрыт навсегда. Возвращайся в основу!", 
                parse_mode="HTML"
            )

        # 2. Регистрация через официальную ссылку
        if command.args == "join_tourney":
            if not user_status:
                # Создаем игрока и выдаем капитал
                await add_balance(user_id, 150000, message.from_user.first_name)
                try:
                    await db.execute("UPDATE users SET received_bonus = TRUE WHERE user_id = $1", user_id)
                except: pass
            
            welcome_text = (
                "⚔️ <b>ВХОД НА АРЕНУ ПОДТВЕРЖДЕН!</b> ⚔️\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Тебе начислено <b>150 000 ᴜ</b>.\n\n"
                "👇 <b>Используй меню ниже, чтобы начать.</b>"
            )
            return await message.answer(welcome_text, reply_markup=get_main_reply_keyboard(), parse_mode="HTML")

        # 3. Если игрок уже в базе (просто нажал старт в боте)
        if user_status:
            return await message.answer("⚔️ Ты на Арене! Капитал в работе.", reply_markup=get_main_reply_keyboard())

        # 4. Если зашел "с улицы" без ссылки и его нет в базе
        await message.answer(
            "🛰 <b>ОШИБКА ДОСТУПА</b>\n"
            "Вход на Арену возможен только через терминал регистрации в @Umbreliana_bot!", 
            parse_mode="HTML"
        )

@dp.message(F.text == "🎁 ПОЛУЧИТЬ 150 000 ᴜ")
async def cmd_claim_start_bonus(message: types.Message):
    user_id = message.from_user.id
    pool = await get_db()
    
    async with pool.acquire() as db:
        # Проверяем, брал ли уже бонус и какой баланс
        user = await db.fetchrow("SELECT balance, received_bonus FROM users WHERE user_id = $1", user_id)
        
        if not user:
            return # Если юзера нет, AccessMiddleware его и так отсечет

        if user['received_bonus']:
            return await message.reply("🚫 <b>ОТКАЗ:</b> Вы уже забирали стартовый капитал!")

        if user['balance'] >= 150000:
            # Если у него уже есть деньги (выдались при старте), просто помечаем, что бонус получен
            await db.execute("UPDATE users SET received_bonus = TRUE WHERE user_id = $1", user_id)
            return await message.reply("✅ <b>Система синхронизирована.</b> У вас уже есть стартовый капитал.")

        # Выдаем бонус и ставим метку
        async with db.transaction():
            await db.execute("UPDATE users SET balance = balance + 150000, received_bonus = TRUE WHERE user_id = $1", user_id)
        
        await message.reply(
            "💰 <b>АКТИВАЦИЯ КАПИТАЛА!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Тебе начислено <b>150 000 ᴜ</b>.\n\n"
            "<i>Распорядись ими с умом. На Арене выживает самый расчетливый. Удачной охоты!</i>",
            parse_mode="HTML"
        )

# ==========================================
# 👤 ПРОФИЛЬ (Облегченный)
# ==========================================
@router.message(F.text.lower().startswith("профиль") | (F.text.lower() == "👤 профиль"))
async def widget_profile(message: types.Message):
    target_id = message.from_user.id
    target_name = message.from_user.first_name

    args = message.text.split()
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        target_name = message.reply_to_message.from_user.first_name
    elif len(args) > 1 and args[0].lower() == "профиль":
        raw_target = args[1].replace('@', '')
        if raw_target.isdigit():
            target_id = int(raw_target)
            target_name = f"Гладиатор {target_id}" 
        else:
            return await message.reply("❌ Используй ID или реплай.")

    if target_id == message.bot.id:
        return await message.reply("🤖 Я — Коннор. Я слежу за чистотой турнира.")

    balance = await get_balance(target_id)
    
    profile_text = (
        f"⚔️ <b>ДОСЬЕ ГЛАДИАТОРА</b> ⚔️\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Участник: <b>{target_name}</b>\n"
        f"ID: <code>{target_id}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Капитал: <b>{fmt(balance)} ᴜ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
    )
    await message.reply(profile_text, parse_mode="HTML")

# ==========================================
# 💰 БАЛАНС И ТОПЫ
# ==========================================
@dp.message(Command("balance"))
@dp.message(F.text.lower().strip().in_(["б", "баланс", "счёт"]))
async def show_balance(message: types.Message):
    user_id = message.from_user.id
    balance = await get_balance(user_id)
    user_mention = f"<a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>"
    await message.reply(f"⚔️ {user_mention},\n💰 Твой турнирный счет: <b>{fmt(balance)}</b> ᴜ", parse_mode="HTML")

@router.message(Command("top_farms"))
@router.message(F.text.lower().startswith("топ ферм") | F.text.lower().startswith("топ ферма"))
async def show_top_farms(message: types.Message):
    chat_id = message.chat.id
    text_args = message.text.lower().split()
    is_global = "глобал" in text_args or "мир" in text_args or message.chat.type == "private"
    
    users_dict = {}
    pool = await get_db()
    async with pool.acquire() as db:
        if is_global:
            rows = await db.fetch("SELECT user_id, telegram_username as nick FROM users WHERE user_id != $1", ADMIN_ID)
        else:
            rows = await db.fetch("""
                SELECT u.user_id, u.telegram_username as nick 
                FROM users u
                JOIN chat_members cm ON u.user_id = cm.user_id
                WHERE cm.chat_id = $1 AND u.user_id != $2
            """, chat_id, ADMIN_ID)
            
        for row in rows:
            users_dict[row['user_id']] = row['nick'] if row['nick'] else f"Игрок {row['user_id']}"

    if not users_dict: return await message.reply("Ферм пока нет.")

    farm_power = {uid: 0 for uid in users_dict}
    user_ids = list(users_dict.keys())
    
    async with pool.acquire() as db:
        batches = await db.fetch(
            "SELECT user_id, gpu_id, multiplier, qty FROM gpu_batches WHERE condition > 0 AND user_id = ANY($1::bigint[])", user_ids
        )
        
    for b in batches:
        uid = b['user_id']
        if uid in farm_power:
            gpu_id_str = b['gpu_id']
            try:
                gpu_num = int(gpu_id_str.split('_')[1])
                if gpu_num in GPUS:
                    income = GPUS[gpu_num]['income']
                    farm_power[uid] += int(b['qty'] * income * b['multiplier'])
            except: pass

    farm_list = [{'nick': users_dict[uid], 'income': power} for uid, power in farm_power.items() if power > 0]
    farm_list.sort(key=lambda x: x['income'], reverse=True)
    top_10 = farm_list[:10]
    
    if not top_10: return await message.reply("Никто еще не купил оборудование.")

    header = "🌍 <b>ТУРНИРНЫЙ ТОП ФЕРМ</b>\n" if is_global else "📍 <b>ТОП ФЕРМ ЧАТА</b>\n"
    sep = "════════════════════\n"
    text = header + sep
    
    for i, player in enumerate(top_10, 1):
        prefix = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"<b>{i}.</b>"
        text += f"{prefix} <b>{player['nick']}</b> — ⚡️ {fmt(player['income'])} ᴜ/ч\n"
    await message.answer(text + sep, parse_mode="HTML")

@router.message(Command("top"))
@router.message(F.text.lower().startswith("топ"))
async def cmd_show_top(message: types.Message):
    chat_id = message.chat.id
    text_args = message.text.lower().split()
    is_global = "глобал" in text_args or "мир" in text_args
    
    if is_global or message.chat.type == "private":
        rows = await get_top_10_global()
        header = "🌍 <b>ТУРНИРНЫЕ ЛИДЕРЫ (ГЛОБАЛ)</b>\n"
    else:
        rows = await get_top_10_local(chat_id)
        header = f"📍 <b>ЛИДЕРЫ ЧАТА</b>\n"

    if not rows: return await message.reply("Список пока пуст.")

    sep = "════════════════════\n"
    text = header + sep
    
    for i, row in enumerate(rows, 1):
        uid, bal, nick = row['user_id'], row['balance'], row['nickname']
        if uid == ADMIN_ID: continue
        name = nick if nick else f"Игрок {uid}"
        prefix = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"<b>{i}.</b>"
        text += f"{prefix} <b>{name}</b> — 💰 {fmt(bal)} ᴜ\n"
    await message.answer(text + sep, parse_mode="HTML")

# ==========================================
# 📚 НАВИГАТОР
# ==========================================
@router.message(Command("help"))
@router.message(F.text.lower().in_(["команды", "помощь", "меню", "help", "инфо", "🚔 команды"]))
async def widget_commands_link(message: types.Message):
    guide_text = (
        "⚔️ <b>Команды Турнира</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🔹 <code>б</code> — проверить баланс\n"
        "🔹 <code>профиль</code> — статистика\n"
        "🔹 <code>топ глобал</code> — рейтинг турнира\n"
        "🔹 <code>ферма</code> — управление майнингом\n"
        "🔹 <code>рулетка [сумма] [число/цвет]</code>\n"
        "🔹 <code>мины [сложность] [сумма]</code>\n"
    )
    await message.reply(guide_text, parse_mode="HTML")

@dp.message(F.text == "🌐 Чаты")
async def cmd_official_chats(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.button(text="💬 Подключиться к турнирному чату", url="https://t.me/umbrelianachat")
    await message.reply("🌐 <b>Чат Турнира</b>\nЗаходи, чтобы найти соперников для игры.", reply_markup=builder.as_markup(), parse_mode="HTML")

# ==========================================
# 🛡 ФОНОВЫЕ ПРОЦЕССЫ
# ==========================================
@dp.errors()
async def global_error_handler(event: types.ErrorEvent):
    if isinstance(event.exception, TelegramRetryAfter) or isinstance(event.exception, TelegramBadRequest):
        return True 
    logging.error(f"Произошла ошибка: {event.exception}")
    return False

BACKUP_FILE = "hard_crash_tourney.json"

async def ssd_backup_loop():
    while True:
        await asyncio.sleep(10)
        try:
            backup_data = {"refunds": {}} 
            from roulette_game import current_bets, spinning_bets
            for cid, bets in list(current_bets.items()) + list(spinning_bets.items()):
                for b in bets:
                    uid = b['user_id']
                    backup_data["refunds"][uid] = backup_data["refunds"].get(uid, 0) + b['amount']

            from mines_game import active_mines
            for uid, data in list(active_mines.items()):
                backup_data["refunds"][uid] = backup_data["refunds"].get(uid, 0) + data['bet']

            if backup_data["refunds"]:
                with open(BACKUP_FILE, "w", encoding="utf-8") as f:
                    json.dump(backup_data, f)
            else:
                if os.path.exists(BACKUP_FILE):
                    os.remove(BACKUP_FILE)
        except: pass 

async def recover_from_hard_crash(bot_instance: Bot):
    if not os.path.exists(BACKUP_FILE): return 
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
            print(f"🛡 Успешно восстановлено {len(refunds)} балансов турнира из дампа!")
    except: pass
    finally:
        if os.path.exists(BACKUP_FILE): os.remove(BACKUP_FILE)
 
async def on_shutdown(bot: Bot):
    # Флаг выключения (замок мидлварей)
    import middlewares
    middlewares.IS_SHUTTING_DOWN = True
    
    try:
        from roulette_game import current_bets, spinning_bets
        all_bets = []
        for chat_id in list(current_bets.keys()): all_bets.extend(current_bets.pop(chat_id, []))
        for chat_id in list(spinning_bets.keys()): all_bets.extend(spinning_bets.pop(chat_id, []))
        if all_bets:
            refund_map = {}
            for b in all_bets:
                uid = b['user_id']
                refund_map[uid] = refund_map.get(uid, 0) + b['amount']
            for uid, amount in refund_map.items():
                await add_balance(uid, amount)
    except: pass

    try:
        from mines_game import active_mines
        for uid in list(active_mines.keys()):
            data = active_mines.pop(uid)
            await add_balance(uid, data['bet'])
    except: pass

    if os.path.exists(BACKUP_FILE): os.remove(BACKUP_FILE)
    print("👋 Турнирная арена сохранена и отключена.")

# ==========================================
# 🚀 ЗАПУСК БОТА
# ==========================================
async def main():
    await init_db()
    await check_table_structure()
    await add_missing_columns_safe()
    await init_history_db()
    await init_roulette()
    await recover_from_hard_crash(bot)

    dp.update.middleware(ShutdownMiddleware())
    for current_router in (dp.message, dp.callback_query):
        current_router.middleware(AccessMiddleware())
        current_router.middleware(RateLimitMiddleware())       
        current_router.middleware(AntiChannelMiddleware())     
        current_router.middleware(BanMiddleware())             

    dp.include_router(router) 
    dp.include_router(farm_router)
    dp.include_router(mines_router) 
    dp.include_router(roulette_router) 
    dp.include_router(admin_router)
    
    await bot.delete_webhook(drop_pending_updates=True)

    scheduler = AsyncIOScheduler()
    # Фоновый бэкап каждый час
    scheduler.add_job(create_backup, "interval", hours=1, args=(bot, ADMIN_ID, True))
    scheduler.start()
    
    asyncio.create_task(ssd_backup_loop())

    print("⚔️ Турнирная Арена готова. Бот запущен.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        dp.shutdown.register(on_shutdown)
        logging.getLogger("aiogram.dispatcher").setLevel(logging.CRITICAL)
        asyncio.run(main())
    except KeyboardInterrupt:
        pass