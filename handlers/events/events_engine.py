# File: handlers/events/events_engine.py
import asyncio
import random
import time
import json
import logging
from core.database import get_db, get_balance, add_balance, get_farm, update_farm, get_user_buffs
from aiogram import Router, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder

router = Router()

MAIN_CHAT_ID = -1003909438997
ADMIN_ID = 1412940726 

def fmt(num):
    return f"{int(num):,}".replace(",", " ")

# ==========================================
# 🌍 АКТИВНЫЕ ГЛОБАЛЬНЫЕ ЭФФЕКТЫ
# ==========================================
GLOBAL_MODIFIERS = {
    "income": 1.0,       # Множитель дохода
    "tax": 1.0,          # Множитель налога
    "electricity": 1.0,  # Множитель стоимости света
    "shop": 1.0,         # Множитель цен в гос. магазине
    "market": 1.0,       # Множитель цен на теневом рынке
    "oc_cost": 1.0,      # Стоимость разгона
    "oc_chance": 0.0,    # Бонус к шансу разгона (+0.2 = +20%)
    "overheat_dmg": 1.0, # Урон от перегрева
    "god_mode": False,   # Режим бога (нет износа)
    "end_time": 0,       
    "event_name": "Нет",
    "msg_ids": {}        # Заменили msg_id (int) на msg_ids (dict)
}

# ==========================================
# 🗄 АСИНХРОННЫЕ ФУНКЦИИ БАЗЫ ДАННЫХ
# ==========================================

_init_lock = asyncio.Lock()
_is_db_initialized = False

async def init_events_db():
    global _is_db_initialized
    if _is_db_initialized:
        return

    async with _init_lock:
        if _is_db_initialized:
            return
            
        pool = await get_db()
        async with pool.acquire() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS event_history (
                    id SERIAL PRIMARY KEY,
                    event_name TEXT,
                    event_type TEXT,
                    timestamp BIGINT,
                    chat_id BIGINT DEFAULT 0
                )
            """)
            try: await db.execute("ALTER TABLE event_history ADD COLUMN IF NOT EXISTS chat_id BIGINT DEFAULT 0")
            except: pass
            
            await db.execute("CREATE TABLE IF NOT EXISTS server_state (id SERIAL PRIMARY KEY, data TEXT)")
            await db.execute("INSERT INTO server_state (id, data) VALUES (1, '{}') ON CONFLICT(id) DO NOTHING")
            
        _is_db_initialized = True

async def log_event(name: str, ev_type: str, chat_id: int = 0):
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute(
            "INSERT INTO event_history (event_name, event_type, timestamp, chat_id) VALUES ($1, $2, $3, $4)",
            name, ev_type, int(time.time()), chat_id
        )

async def load_global_modifiers():
    pool = await get_db()
    async with pool.acquire() as db:
        data_str = await db.fetchval("SELECT data FROM server_state WHERE id = 1")
        if data_str and data_str != '{}':
            loaded_data = json.loads(data_str)
            GLOBAL_MODIFIERS.update(loaded_data)

async def save_global_modifiers():
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute("UPDATE server_state SET data = $1 WHERE id = 1", json.dumps(GLOBAL_MODIFIERS))

# ==========================================
# 🌪 БАЗА ДАННЫХ СОБЫТИЙ (ТОЛЬКО ГЛОБАЛЬНЫЕ)
# ==========================================

GLOBAL_EVENTS = [
    {"name": "🚀 Листинг на Binance", "desc": "UMBREL взлетел в космос! Доход всех ферм увеличен в 2 раза на 3 часа.", "weight": 10, "effect": "buff_income_2.0", "duration_h": 3},
    {"name": "❄️ Криптозима", "desc": "Рынок рухнул. Доходность майнинга упала на 50% на 4 часа.", "weight": 8, "effect": "nerf_income_0.5", "duration_h": 4},
    {"name": "🌩 Авария на подстанции", "desc": "Электричество подорожало в 3 раза на 5 часов!", "weight": 10, "effect": "nerf_elec_3.0", "duration_h": 5},
    {"name": "❄️ Государственные субсидии", "desc": "Мэр выделил квоты на свет. Электричество бесплатно (0 ᴜ) на 3 часа!", "weight": 5, "effect": "buff_elec_0.0", "duration_h": 3},
    {"name": "🚔 Налоговая облава", "desc": "ФНС свирепствует! Налоги умножены на 1.5x до конца дня (6 часов).", "weight": 10, "effect": "nerf_tax_1.5", "duration_h": 6},
    {"name": "🏝 Налоговая амнистия", "desc": "Офшоры открыты! Налог на добычу снижен до нуля на 2 часа.", "weight": 5, "effect": "buff_tax_0.0", "duration_h": 2},
    {"name": "📦 Дефицит чипов", "desc": "Завод TSMC затопило. Цены в магазине Коннора выросли в 2 раза на 4 часа.", "weight": 8, "effect": "nerf_shop_2.0", "duration_h": 4},
    {"name": "🚚 Глобальная распродажа", "desc": "Таможня конфисковала партию карт и сливает их. Скидка 50% в магазине на 2 часа!", "weight": 5, "effect": "buff_shop_0.5", "duration_h": 2},
    {"name": "💎 Аирдроп от Дурова", "desc": "Павел Дуров раздал всем активным игрокам по 5 000 000 ᴜ!", "weight": 2, "effect": "give_everyone_5m", "duration_h": 0},
    {"name": "🌪 Магнитная буря", "desc": "Связь со спутниками потеряна. Налоги х2, свет х2, доход х0.5 на 2 часа! Выживайте.", "weight": 2, "effect": "hardcore_mode", "duration_h": 2},
    {"name": "🛸 Вторжение ИИ", "desc": "Сеть захвачена! Случайные 20% карт у всех игроков сломаны (0%).", "weight": 3, "effect": "break_global_gpus", "duration_h": 0},
    {"name": "🔧 Хакерская атака на рынок", "desc": "Все лоты на рынке подешевели на 30% на 4 часа. Торопитесь!", "weight": 5, "effect": "market_discount_30", "duration_h": 4},
    {"name": "🧬 Экспериментальные чипы", "desc": "Разгон стал на 50% дешевле и на 20% успешнее на 2 часа.", "weight": 4, "effect": "oc_buff", "duration_h": 2},
    {"name": "🛡 Благословение Коннора", "desc": "В течение часа износ карт равен нулю, налог 0%", "weight": 2, "effect": "god_mode", "duration_h": 1},
    {"name": "📈 Майнинг-бум", "desc": "Доходность увеличена на 100%, но налог тоже удвоен на 4 часа.", "weight": 8, "effect": "boom_and_tax", "duration_h": 4},
    {"name": "❄️ Аномальный холод", "desc": "Перегрев не влияет на износ 3 часа (охлаждение не требуется)", "weight": 5, "effect": "no_overheat_penalty", "duration_h": 3},
    {"name": "🔥 Аномальная жара", "desc": "Перегрев увеличивает износ в 2 раза на 5 часов.", "weight": 8, "effect": "overheat_hell", "duration_h": 5},
    {"name": "👑 Конкурс на лучшую ферму", "desc": "Топ-5 самых богатых игроков только что получили по 10 млн ᴜ!", "weight": 2, "effect": "top_farms_reward", "duration_h": 0},
    {"name": "🎁 Щедрый меценат", "desc": "Каждый игрок получил 1 000 000 ᴜ и случайную карту!", "weight": 1, "effect": "give_money_and_gpu", "duration_h": 0},
    {"name": "📉 Обвал UMBREL", "desc": "Цены в магазине и налоги снижены на 20% на 4 часа.", "weight": 5, "effect": "everything_discount_20", "duration_h": 4},
    {"name": "📈 Пузырь UMBREL", "desc": "Цены в магазине и налоги увеличены на 30% на 3 часа.", "weight": 6, "effect": "everything_inflate_30", "duration_h": 3},
    {"name": "🏴‍☠️ Пиратская атака", "desc": "Пираты забрали 5% баланса у всех, но скинули с корабля кучу карт!", "weight": 3, "effect": "steal_and_give_gpus", "duration_h": 0}
]

async def force_global_collection(bot):
    # 🔥 ЖЕЛЕЗНЫЙ ИМПОРТ ИЗ НАШЕГО ОБНОВЛЕННОГО КРИПТО-ДВИЖКА
    from handlers.syndicate.farms.engine import perform_collection
    from core.database import add_to_dividend_pool
    
    collected_count = 0
    total_dividends = 0
    
    pool = await get_db()
    async with pool.acquire() as db:
        all_users = await db.fetch("SELECT user_id FROM users")

    for row in all_users:
        user_id = row['user_id']
        farm_data = await get_farm(user_id)
        if not farm_data:
            continue
            
        has_cards = any(k.startswith('gpu_') and v > 0 for k, v in farm_data.items())
        if not has_cards: 
            continue

        # ✅ ИДЕАЛЬНЫЙ СБОР: Вызываем новое крипто-ядро, защищенное от распаковки и долгов
        net_crypto_profit, fire_message, broken_msg, tax_amount, tax_rate, electricity_bill, emergency_msg, pending_crypto = await perform_collection(user_id, farm_data)
        
        if pending_crypto > 0:
            collected_count += 1
            total_dividends += int(pending_crypto * 0.01)
            
    # Заливаем налоги в банк Синдиката
    if total_dividends > 0:
        await add_to_dividend_pool(total_dividends)
            
    if collected_count > 0:
        try:
            msg_text = (
                f"🏦 <b>ПРИНУДИТЕЛЬНАЯ ИНКАССАЦИЯ!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Смена экономики! Коннор автоматически собрал прибыль со всех активных ферм (<b>{collected_count} шт.</b>) по СТАРЫМ тарифам крипто-ноды.\n\n"
                f"<i>Склады очищены, таймеры перезапущены. Никаких налоговых махинаций!</i> 😎"
            )
            await bot.send_message(MAIN_CHAT_ID, msg_text, parse_mode="HTML")
        except Exception as e: 
            print(f"Ошибка отправки уведомления об инкассации: {e}")

# ==========================================
# ⚙️ СЕРДЦЕ ХАОСА (ТОЛЬКО ГЛОБАЛ)
# ==========================================
async def run_random_event(bot):
    event = random.choices(GLOBAL_EVENTS, weights=[e["weight"] for e in GLOBAL_EVENTS])[0]

    await force_global_collection(bot)
    
    GLOBAL_MODIFIERS.update({"income": 1.0, "tax": 1.0, "electricity": 1.0, "shop": 1.0, "market": 1.0, "oc_cost": 1.0, "oc_chance": 0.0, "overheat_dmg": 1.0, "god_mode": False})
    eff = event["effect"]
    
    if eff == "buff_income_2.0": GLOBAL_MODIFIERS["income"] = 2.0
    elif eff == "nerf_income_0.5": GLOBAL_MODIFIERS["income"] = 0.5
    elif eff == "nerf_elec_3.0": GLOBAL_MODIFIERS["electricity"] = 3.0
    elif eff == "buff_elec_0.0": GLOBAL_MODIFIERS["electricity"] = 0.0
    elif eff == "nerf_tax_1.5": GLOBAL_MODIFIERS["tax"] = 1.5
    elif eff == "buff_tax_0.0": GLOBAL_MODIFIERS["tax"] = 0.0
    elif eff == "nerf_shop_2.0": GLOBAL_MODIFIERS["shop"] = 2.0
    elif eff == "buff_shop_0.5": GLOBAL_MODIFIERS["shop"] = 0.5
    elif eff == "market_discount_30": GLOBAL_MODIFIERS["market"] = 0.7
    elif eff == "oc_buff": 
        GLOBAL_MODIFIERS["oc_cost"] = 0.5
        GLOBAL_MODIFIERS["oc_chance"] = 0.2
    elif eff == "god_mode": 
        GLOBAL_MODIFIERS["god_mode"] = True
        GLOBAL_MODIFIERS["tax"] = 0.0
    elif eff == "boom_and_tax":
        GLOBAL_MODIFIERS["income"] = 2.0
        GLOBAL_MODIFIERS["tax"] = 2.0
    elif eff == "no_overheat_penalty": GLOBAL_MODIFIERS["overheat_dmg"] = 0.0
    elif eff == "overheat_hell": GLOBAL_MODIFIERS["overheat_dmg"] = 2.0
    elif eff == "everything_discount_20":
        GLOBAL_MODIFIERS.update({"tax": 0.8, "shop": 0.8, "market": 0.8})
    elif eff == "everything_inflate_30":
        GLOBAL_MODIFIERS.update({"tax": 1.3, "shop": 1.3, "market": 1.3})
    elif eff == "hardcore_mode":
        GLOBAL_MODIFIERS.update({"income": 0.5, "tax": 2.0, "electricity": 2.0})
        
    # МГНОВЕННЫЕ ГЛОБАЛЬНЫЕ
    elif eff == "give_everyone_5m":
        pool = await get_db()
        async with pool.acquire() as db:
            await db.execute("UPDATE users SET balance = balance + 10000000 WHERE user_id IN (SELECT user_id FROM users ORDER BY balance DESC LIMIT 5)")
    elif eff == "break_global_gpus":
        pool = await get_db()
        async with pool.acquire() as db:
            await db.execute("UPDATE gpu_batches SET condition = 0.0 WHERE id IN (SELECT id FROM gpu_batches ORDER BY random() LIMIT (SELECT COUNT(*)/5 FROM gpu_batches))")
    elif eff == "top_farms_reward":
        pool = await get_db()
        async with pool.acquire() as db:
            await db.execute("INSERT INTO gpu_batches (user_id, gpu_id, multiplier, qty, condition, was_repaired) SELECT user_id, 'gpu_5', 1.0, 1, 100.0, 0 FROM users WHERE balance IS NOT NULL")
    elif eff == "give_money_and_gpu":
        pool = await get_db()
        async with pool.acquire() as db:
            await db.execute("UPDATE users SET balance = balance + 1000000 WHERE balance IS NOT NULL")
            await db.execute("INSERT INTO gpu_batches (user_id, gpu_id, multiplier, qty, condition, was_repaired) SELECT user_id, 'gpu_5', 1.0, 1, 100.0, 0 FROM users WHERE balance IS NOT NULL")
    elif eff == "steal_and_give_gpus":
        pool = await get_db()
        async with pool.acquire() as db:
            await db.execute("UPDATE users SET balance = CAST(balance * 0.95 AS BIGINT) WHERE balance IS NOT NULL")
            await db.execute("INSERT INTO gpu_batches (user_id, gpu_id, multiplier, qty, condition, was_repaired) SELECT user_id, 'gpu_4', 1.0, 3, 50.0, 0 FROM users WHERE balance IS NOT NULL")

    if event["duration_h"] > 0:
        GLOBAL_MODIFIERS["end_time"] = int(time.time()) + (event["duration_h"] * 3600)
        GLOBAL_MODIFIERS["event_name"] = event["name"]

    await log_event(event['name'], "🌍 Глобальное")
    
    news_text = f"📰 <b>ГЛОБАЛЬНОЕ СОБЫТИЕ</b>\n━━━━━━━━━━━━━━━━━━━━\n<b>{event['name']}</b>\n\n{event['desc']}"
    
    GLOBAL_MODIFIERS["msg_ids"] = {} 
    
    try: 
        msg = await bot.send_message(MAIN_CHAT_ID, news_text, parse_mode="HTML")
        await bot.pin_chat_message(MAIN_CHAT_ID, msg.message_id, disable_notification=False)
        GLOBAL_MODIFIERS["msg_ids"][str(MAIN_CHAT_ID)] = msg.message_id 
    except Exception as e:
        logging.error(f"Ошибка отправки глобалки в главный чат: {e}")

    await save_global_modifiers()

# ==========================================
# ⏱ ФОНОВЫЕ ТАЙМЕРЫ
# ==========================================

async def global_chaos_loop(bot):
    while True:
        try:
            sleep_time = random.randint(36000, 57600) # от 10 до 16 часов
            await asyncio.sleep(sleep_time)
            await run_random_event(bot)
        except Exception as e:
            logging.error(f"❌ Критическая ошибка в Global Хаосе: {e}")
            await asyncio.sleep(60)

async def global_event_monitor(bot):
    try:
        await init_events_db()
    except Exception as e:
        logging.error(f"❌ Ошибка инициализации БД событий: {e}")

    while True:
        try:
            await asyncio.sleep(60) 
            
            try:
                from core import bot_state
                if getattr(bot_state, 'IS_SHUTTING_DOWN', False): 
                    logging.info("🛑 Монитор событий остановлен из-за перезагрузки ядра.")
                    break 
            except ImportError:
                pass 
            
            await load_global_modifiers()
            
            if GLOBAL_MODIFIERS.get("end_time", 0) > 0 and time.time() > GLOBAL_MODIFIERS["end_time"]:
                logging.info("⏰ Таймер события истек! Начинаю глобальный сброс...")
                
                try: 
                    await force_global_collection(bot)
                except Exception as e: 
                    logging.warning(f"⚠️ Ошибка force_global_collection: {e}")
                
                msg_ids_dict = GLOBAL_MODIFIERS.get("msg_ids", {})
                if isinstance(msg_ids_dict, dict):
                    for chat_id_str, msg_id in msg_ids_dict.items():
                        try:
                            await bot.unpin_chat_message(chat_id=int(chat_id_str), message_id=int(msg_id))
                        except Exception as e:
                            logging.warning(f"⚠️ Не смог открепить в чате {chat_id_str}: {e}")
                
                GLOBAL_MODIFIERS.update({
                    "income": 1.0, "tax": 1.0, "electricity": 1.0, "shop": 1.0, 
                    "market": 1.0, "oc_cost": 1.0, "oc_chance": 0.0, 
                    "overheat_dmg": 1.0, "god_mode": False, "end_time": 0, "event_name": "Нет", "msg_ids": {}
                })
                await save_global_modifiers() 
                
                if isinstance(msg_ids_dict, dict):
                     for chat_id_str in msg_ids_dict.keys():
                         try: 
                             await bot.send_message(int(chat_id_str), "🌤 <b>Рынок стабилизировался.</b> Глобальные эффекты прекратили действие.", parse_mode="HTML")
                         except: 
                             pass
                
        except Exception as e:
            logging.error(f"❌ Критическая ошибка в мониторе событий: {e}")
            await asyncio.sleep(5)

async def start_events_engine(bot):
    await init_events_db()
    await load_global_modifiers()
    
    asyncio.create_task(global_chaos_loop(bot))
    asyncio.create_task(global_event_monitor(bot))
    
    print("🌪 Движок Хаоса запущен. Ожидайте событий...")

# ==========================================
# 📜 ЖУРНАЛ СОБЫТИЙ С ПАГИНАЦИЕЙ
# ==========================================

EVENTS_PER_PAGE = 10

async def get_events_page(page: int, current_chat_id: int):
    day_ago = int(time.time()) - 86400
    
    pool = await get_db()
    async with pool.acquire() as db:
        total_events = await db.fetchval("SELECT COUNT(*) FROM event_history WHERE timestamp > $1 AND (chat_id = $2 OR event_type = '🌍 Глобальное')", day_ago, current_chat_id) or 0
        
        active_text = ""
        if GLOBAL_MODIFIERS.get("end_time", 0) > 0 and time.time() < GLOBAL_MODIFIERS["end_time"]:
            time_left = int((GLOBAL_MODIFIERS["end_time"] - time.time()) / 60)
            active_text = f"🌍 <b>АКТИВНО СЕЙЧАС:</b>\n└ <b>{GLOBAL_MODIFIERS['event_name']}</b> (ещё {time_left} мин)\n════════════════════\n"

        if total_events == 0:
            return active_text + "📜 <b>Журнал пуст.</b> За последние 24 часа в этом секторе аномалий не зафиксировано.", None

        total_pages = (total_events + EVENTS_PER_PAGE - 1) // EVENTS_PER_PAGE
        if page >= total_pages: page = total_pages - 1
        if page < 0: page = 0
            
        offset = page * EVENTS_PER_PAGE
        
        history = await db.fetch("""
            SELECT event_name, event_type, timestamp 
            FROM event_history 
            WHERE timestamp > $1 AND (chat_id = $2 OR event_type = '🌍 Глобальное')
            ORDER BY timestamp DESC 
            LIMIT $3 OFFSET $4
        """, day_ago, current_chat_id, EVENTS_PER_PAGE, offset)

    text = active_text + f"📜 <b>ЖУРНАЛ СОБЫТИЙ ЗА 24Ч</b> (Стр. {page + 1}/{total_pages})\n════════════════════\n"
    for row in history:
        event_time = time.strftime("%H:%M", time.localtime(row['timestamp']))
        text += f"🕒 <code>{event_time}</code> | {row['event_type']}\n└ <b>{row['event_name']}</b>\n\n"
    
    builder = InlineKeyboardBuilder()
    buttons = []
    
    if page > 0:
        buttons.append(types.InlineKeyboardButton(text="◀️ Новее", callback_data=f"elog_{page - 1}"))
    if page < total_pages - 1:
        buttons.append(types.InlineKeyboardButton(text="Старее ▶️", callback_data=f"elog_{page + 1}"))
        
    if buttons:
        builder.row(*buttons)
        
    return text, builder.as_markup() if buttons else None

@router.message(F.text.lower().in_(["события", "события за сегодня", "что произошло"]))
async def cmd_events_history(message: types.Message):
    text, markup = await get_events_page(0, message.chat.id) 
    await message.reply(text, reply_markup=markup, parse_mode="HTML")

@router.callback_query(F.data.startswith("elog_"))
async def callback_event_log_page(callback: types.CallbackQuery):
    page = int(callback.data.split("_")[1])
    text, markup = await get_events_page(page, callback.message.chat.id)
    
    try:
        await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except: pass 
        
    await callback.answer()

# ==========================================
# 🎛 ПУЛЬТ АДМИНА: УПРАВЛЕНИЕ ХАОСОМ
# ==========================================
@router.message(F.text.lower() == "+событие", F.from_user.id == ADMIN_ID)
async def cmd_admin_events_menu(message: types.Message):
    await send_chaos_main_menu(message)

async def send_chaos_main_menu(message_or_callback):
    builder = InlineKeyboardBuilder()
    builder.button(text="🌍 Глобальное", callback_data="fchaos_type_global")
    builder.button(text="🔪 Маньяк", callback_data="fchaos_type_maniac")
    builder.button(text="☄️ Метеорит", callback_data="fchaos_type_meteor")
    builder.adjust(1)
    
    text = "🎛 <b>ПУЛЬТ УПРАВЛЕНИЯ ХАОСОМ</b>\n════════════════════\nВыбери тип события:"
    
    if isinstance(message_or_callback, types.Message):
        await message_or_callback.reply(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    else:
        await message_or_callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("fchaos_type_"))
async def chaos_qty_menu(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return await callback.answer("🛑 Только Архитектор!", show_alert=True)
    action = callback.data.split("_")[2]
    
    action_names = {
        "global": "🌍 Глобальных событий",
        "maniac": "🔪 Нападений Маньяка",
        "meteor": "☄️ Метеоритных дождей",
    }
    
    builder = InlineKeyboardBuilder()
    builder.button(text="x1", callback_data=f"fchaos_run_{action}_1")
    builder.button(text="x5", callback_data=f"fchaos_run_{action}_5")
    builder.button(text="x10", callback_data=f"fchaos_run_{action}_10")
    builder.button(text="◀️ Назад", callback_data="fchaos_back_main")
    builder.adjust(3, 1)
    
    await callback.message.edit_text(
        f"⚙️ Сколько <b>{action_names[action]}</b> запускаем подряд?", 
        reply_markup=builder.as_markup(), 
        parse_mode="HTML"
    )
    
@router.callback_query(F.data == "fchaos_back_main")
async def chaos_back_main(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return await callback.answer("🛑", show_alert=True)
    await send_chaos_main_menu(callback)

@router.callback_query(F.data.startswith("fchaos_run_"))
async def process_force_chaos(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return await callback.answer("🛑 Только Архитектор!", show_alert=True)
        
    parts = callback.data.split("_")
    action = parts[2]
    qty = int(parts[3])
    bot = callback.message.bot
    
    await callback.message.delete() 
    await callback.answer(f"🚀 Орудия заряжены. Произвожу {qty} выстрелов...", show_alert=False)
    
    # 🔥 ЖЕЛЕЗНЫЙ ИМПОРТ КОНФИГА GPU
    from handlers.syndicate.farms.config import GPUS
    
    for i in range(qty):
        if action == "global":
            await run_random_event(bot)

        elif action == "maniac":
            current_time = int(time.time())
            seven_days_ago = current_time - 604800
            
            target_id = None
            target_name = None
            current_chat_id = callback.message.chat.id 
            
            pool = await get_db()
            async with pool.acquire() as db:
                candidates = await db.fetch("""
                    SELECT u.user_id FROM users u
                    JOIN chat_members cm ON u.user_id = cm.user_id
                    WHERE u.first_seen <= $1 AND u.last_seen >= $2 AND cm.chat_id = $3
                    ORDER BY random() LIMIT 10
                """, seven_days_ago, seven_days_ago, current_chat_id)
            
            for row in candidates:
                uid = row['user_id']
                try:
                    chat_member = await bot.get_chat(uid)
                    if chat_member.first_name:
                        target_id = uid
                        target_name = chat_member.first_name
                        break
                except:
                    continue
                    
            if target_id:
                target_name_link = f'<a href="tg://user?id={target_id}">{target_name}</a>'
                target_chat_id = MAIN_CHAT_ID 
                
                try:
                    msg = await bot.send_message(target_chat_id, "🔪 <b>Маньяк вышел на улицу...</b> Он ищет жертву.", parse_mode="HTML")
                    await asyncio.sleep(2.0)
                    await msg.edit_text("🚪 <i>*Тук-тук-тук*...</i> Маньяк стучится в чью-то дверь.", parse_mode="HTML")
                    await asyncio.sleep(2.0)
                    await msg.edit_text(f"🩸 Дверь открывается... На пороге <b>{target_name_link}</b>!", parse_mode="HTML")
                    await asyncio.sleep(2.0)
                except Exception as e:
                    print(f"Ошибка маньяка: {e}")
                    msg = None

            balance = await get_balance(target_id)
            farm_data = await get_farm(target_id)
            owned_gpus = [k for k, v in farm_data.items() if k.startswith('gpu_') and v > 0]
            
            rand_val = random.random()
            
            if rand_val < 0.25:
                reward = random.randint(10_000, 20_000)
                await add_balance(target_id, reward, is_income=True)
                
                result_text = f"👮‍♂️ <b>ОТПОР!</b> Игрок оказался готов. Он скрутил маньяка и сдал его копам! Полиция выплатила премию: <b>+{fmt(reward)} ᴜ</b>"
                
                await log_event(f"{target_name} скрутил Маньяка (+{fmt(reward)} ᴜ)", "👮‍♂️ Геройство", target_chat_id)
                
                final_news = (
                    f"🔪 <b>НАПАДЕНИЕ В МАЙНИНГ-СИТИ!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Цель: <b>{target_name_link}</b>\n"
                    f"{result_text}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"<i>Коннор гордится такой реакцией. Улицы стали чуть чище.</i>"
                )
                try: await bot.send_message(target_id, f"👮‍♂️ К тебе вломился маньяк, но ты вырубил его с вертушки! Полиция перевела награду: <b>+{fmt(reward)} ᴜ</b>.", parse_mode="HTML")
                except: pass

            else:
                punishment_type = "money"
                if owned_gpus and random.random() < 0.5:
                    punishment_type = "gpu"

                if punishment_type == "money":
                    lost_pct = random.uniform(0.1, 0.3)
                    lost_money = int(balance * lost_pct)
                    await add_balance(target_id, -lost_money)
                    result_text = f"💸 Маньяк выпотрошил сейф и украл <b>{fmt(lost_money)} ᴜ</b>!"
                else:
                    target_gpu = random.choice(owned_gpus)
                    gpu_num = int(target_gpu.split('_')[1])
                    await update_farm(target_id, **{target_gpu: farm_data[target_gpu] - 1})
                    result_text = f"🖥 Маньяк топором разрубил стойку! Уничтожена <b>1x {GPUS[gpu_num]['name']}</b>!"

                final_news = (
                    f"🔪 <b>УБИЙСТВО В МАЙНИНГ-СИТИ!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Жертва: <b>{target_name_link}</b> 💀\n"
                    f"{result_text}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"<i>Полиция разводит руками. Коннор рекомендует купить электрошок.</i>"
                )
                
                await log_event(f"Маньяк зарезал {target_name}", "🔪 Специальное", target_chat_id)
                
                try: await bot.send_message(target_id, "🔪 В твою дверь постучали... Ты открыл и получил нож под ребро. Проверь баланс и инвентарь.", parse_mode="HTML")
                except: pass

            try: 
                if msg: await msg.edit_text(final_news, parse_mode="HTML")
                else: await bot.send_message(target_chat_id, final_news, parse_mode="HTML")
            except: pass
        
        elif action == "meteor":
            current_time = int(time.time())
            seven_days_ago = current_time - 604800
            
            target_id = None
            target_name = None
            current_chat_id = callback.message.chat.id 
            
            pool = await get_db()
            async with pool.acquire() as db:
                candidates = await db.fetch("""
                    SELECT u.user_id FROM users u
                    JOIN chat_members cm ON u.user_id = cm.user_id
                    WHERE u.first_seen <= $1 AND u.last_seen >= $2 AND cm.chat_id = $3
                    ORDER BY random() LIMIT 10
                """, seven_days_ago, seven_days_ago, current_chat_id)
            
            for row in candidates:
                uid = row['user_id']
                try:
                    chat_member = await bot.get_chat(uid)
                    if chat_member.first_name:
                        target_id = uid
                        target_name = chat_member.first_name
                        break
                except:
                    continue
            
            if target_id:
                target_name_link = f'<a href="tg://user?id={target_id}">{target_name}</a>'
                target_chat_id = MAIN_CHAT_ID 

                if random.random() < 0.05:
                    jackpot = random.randint(10_000_000, 20_000_000)
                    await add_balance(target_id, jackpot, is_income=True)
                    
                    await log_event(f"Золотой метеорит упал на {target_name} (+{fmt(jackpot)} ᴜ)", "🌟 Специальное", target_chat_id)
                    
                    try: await bot.send_message(target_chat_id, f"🌟 <b>ЧУДО С НЕБЕС!</b> Золотой метеорит рухнул прямо во двор <b>{target_name_link}</b>!\nВнутри оказались редкие инопланетные сплавы, за которые ученые заплатили <b>{fmt(jackpot)} ᴜ</b>!", parse_mode="HTML")
                    except: pass
                    try: await bot.send_message(target_id, f"🌟 На тебя упал ЗОЛОТОЙ метеорит! Ты чудом выжил и стал богаче на <b>{fmt(jackpot)} ᴜ</b>. Иди празднуй!", parse_mode="HTML")
                    except: pass
                    
                    continue 

                farm_data = await get_farm(target_id)
                owned_gpus = [int(k.split('_')[1]) for k, v in farm_data.items() if k.startswith('gpu_') and v > 0]
                
                if owned_gpus:
                    weights = [gpu ** 2 for gpu in owned_gpus] 
                    target_gpu_id = random.choices(owned_gpus, weights=weights, k=1)[0]
                    
                    await update_farm(target_id, **{f'gpu_{target_gpu_id}': farm_data[f'gpu_{target_gpu_id}'] - 1})
                    gpu_name = GPUS[target_gpu_id]['name']
                    
                    await log_event(f"Метеорит сжег {gpu_name} у {target_name}", "☄️ Специальное", target_chat_id)
                    
                    try: await bot.send_message(target_chat_id, f"☄️ <b>КАТАСТРОФА!</b> Метеорит пробил крышу фермы <b>{target_name_link}</b>!\n💥 Прямое попадание в стойку! Уничтожена видеокарта: <b>{gpu_name}</b>!", parse_mode="HTML")
                    except: pass
                    try: await bot.send_message(target_id, f"☄️ Твоя ферма в огне! Метеорит уничтожил твою <b>{gpu_name}</b>. Соболезную.", parse_mode="HTML")
                    except: pass
                    
                else:
                    balance = await get_balance(target_id)
                    lost_money = int(balance * 0.5)
                    await add_balance(target_id, -lost_money)
                    
                    await log_event(f"Метеорит упал на {target_name} (-{fmt(lost_money)} ᴜ)", "☄️ Специальное", target_chat_id)
                    
                    try: await bot.send_message(target_chat_id, f"☄️ <b>КАТАСТРОФА!</b> Метеорит прилетел в <b>{target_name_link}</b>!\nФерма пуста, поэтому сгорел сейф. Утеряно: <b>{fmt(lost_money)} ᴜ</b>", parse_mode="HTML")
                    except: pass
                    try: await bot.send_message(target_id, "☄️ Вызывай скорую. Тебе пиздец. Минус половина денег.", parse_mode="HTML")
                    except: pass
                
        if qty > 1 and i < qty - 1:
            await asyncio.sleep(1.5)