import time
import random
import asyncio
import re

from aiogram import Router, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest

# 🔥 ПЛОСКИЕ ИМПОРТЫ (Из той же папки tourner)
from database import get_db, get_balance, add_balance, get_farm, update_farm, get_gpu_batches, move_gpu_batch

router = Router()

def fmt(num):
    return f"{int(num):,}".replace(",", " ")

ADMIN_ID = 1412940726  

# 🔥 БРОНЯ ОТ СПАМА И ДАБЛ-КЛИКОВ В МАГАЗИНЕ
shop_cooldowns = {}

# ==========================================
# 📊 КОНФИГ МАГАЗИНА (БЕЗ ЗОЛОТЫХ КАРТ)
# ==========================================
GPUS = {
    1: {"name": "Intel GMA 4500", "price": 10_000, "income": 200, "heat": 1, "power": 20, "emoji": "💻"},
    2: {"name": "NVIDIA GT 1030", "price": 25_000, "income": 600, "heat": 2, "power": 50, "emoji": "🖥️"},
    3: {"name": "NVIDIA GTX 750 Ti", "price": 50_000, "income": 1_200, "heat": 4, "power": 100, "emoji": "🖥️"},
    4: {"name": "AMD RX 580 8Gb", "price": 120_000, "income": 3_000, "heat": 15, "power": 300, "emoji": "🪫"},
    5: {"name": "NVIDIA GTX 1060 6Gb", "price": 200_000, "income": 5_000, "heat": 10, "power": 500, "emoji": "🔋"},
    6: {"name": "NVIDIA RTX 2060 6Gb", "price": 400_000, "income": 9_500, "heat": 18, "power": 1_000, "emoji": "⚡️"},
    7: {"name": "NVIDIA RTX 3050 8Gb", "price": 600_000, "income": 13_000, "heat": 15, "power": 1_500, "emoji": "⚡️"},
    8: {"name": "NVIDIA RTX 3060 12Gb", "price": 1_000_000, "income": 20_000, "heat": 20, "power": 2_500, "emoji": "🕹️"},
    9: {"name": "AMD RX 6700 XT 12Gb", "price": 2_000_000, "income": 37_000, "heat": 25, "power": 5_000, "emoji": "🔴"},
    10: {"name": "NVIDIA RTX 5060 Ti 16Gb", "price": 3_500_000, "income": 60_000, "heat": 22, "power": 8_000, "emoji": "🔥"},
    11: {"name": "NVIDIA RTX 4070 12Gb", "price": 5_000_000, "income": 80_000, "heat": 28, "power": 12_000, "emoji": "☄️"},
    12: {"name": "NVIDIA RTX 5070 12Gb", "price": 8_000_000, "income": 125_000, "heat": 30, "power": 20_000, "emoji": "🚀"},
    13: {"name": "AMD RX 7900 XTX 24Gb", "price": 12_000_000, "income": 175_000, "heat": 45, "power": 35_000, "emoji": "🔴"},
    14: {"name": "NVIDIA RTX 5090 32Gb", "price": 25_000_000, "income": 350_000, "heat": 60, "power": 80_000, "emoji": "☢️"},
    15: {"name": "NVIDIA A100 80Gb", "price": 50_000_000, "income": 650_000, "heat": 80, "power": 150_000, "emoji": "🧠"},
    16: {"name": "NVIDIA RTX 6000 Ada", "price": 85_000_000, "income": 1_000_000, "heat": 100, "power": 250_000, "emoji": "💎"},
    17: {"name": "NVIDIA H100 80Gb", "price": 130_000_000, "income": 1_600_000, "heat": 120, "power": 450_000, "emoji": "🧠"},
    18: {"name": "ASIC Antminer S21", "price": 200_000_000, "income": 2_500_000, "heat": 250, "power": 800_000, "emoji": "🕋"},
    19: {"name": "NVIDIA B200", "price": 350_000_000, "income": 4_000_000, "heat": 300, "power": 1_500_000, "emoji": "🌀"},
    20: {"name": "Квантовый компьютер", "price": 1_000_000_000, "income": 12_000_000, "heat": 1000, "power": 5_000_000, "emoji": "🌌"},
    21: {"name": "NVIDIA RTX 4090 24Gb", "price": 18_000_000, "income": 260_000, "heat": 50, "power": 55_000, "emoji": "🔥"}
}

# (Пустышка, чтобы не сломать импорты в main.py, если они там остались)
async def add_golden_columns():
    pass

COOLING = {
    1: {"name": "Балкон зимой", "price": 0, "capacity": 50, "emoji": "🌬"},
    2: {"name": "Обычные вентиляторы", "price": 1_000_000, "capacity": 200, "emoji": "💨"},
    3: {"name": "Кондиционер", "price": 10_000_000, "capacity": 800, "emoji": "❄️"},
    4: {"name": "Промышленная вытяжка", "price": 50_000_000, "capacity": 3000, "emoji": "🌪"},
    5: {"name": "Дата-центр", "price": 500_000_000, "capacity": 15000, "emoji": "🏢"},
    6: {"name": "Криокамера", "price": 5_000_000_000, "capacity": 150_000, "emoji": "🧊"},
    7: {"name": "Жидкий азот", "price": 25_000_000_000, "capacity": 800_000, "emoji": "🧪"},
    8: {"name": "Подводный сервер", "price": 150_000_000_000, "capacity": 5_000_000, "emoji": "🌊"},
    9: {"name": "Орбитальная станция", "price": 800_000_000_000, "capacity": 25_000_000, "emoji": "🛰"},
    10: {"name": "Абсолютный ноль", "price": 5_000_000_000_000, "capacity": 150_000_000, "emoji": "🌌"}
}

MAX_STORAGE_HOURS = 4
ELECTRICITY_PRICE = 0.2

def get_tax_rate(income_per_hour):
    if income_per_hour < 50000: return 0.05
    elif income_per_hour < 100000: return 0.10
    elif income_per_hour < 200000: return 0.20
    elif income_per_hour < 500000: return 0.40
    else: return 0.50

# ==========================================
# ⚙️ ПАССИВНАЯ СИНХРОНИЗАЦИЯ 
# ==========================================
async def sync_farm_passive(user_id, farm_data, force_sync=False):
    current_time = int(time.time())
    last_update = farm_data.get('last_wear_update') or farm_data.get('last_collect') or current_time
    elapsed_seconds = current_time - last_update
    elapsed_h = float(elapsed_seconds) / 3600.0

    if elapsed_h < 0.01 and not force_sync: 
        return

    _, _, _, total_heat, cooling_capacity, _ = await calculate_farm_state(user_id, farm_data)
    
    overheat_factor = 1.0
    if total_heat > cooling_capacity:
        overheat_factor = min(3.0, 1.0 + (float(total_heat - cooling_capacity) / cooling_capacity))

    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            
            for i in GPUS:
                gpu_id = f'gpu_{i}'
                count = farm_data.get(gpu_id, 0)
                
                db_count = await db.fetchval("SELECT SUM(qty) FROM gpu_batches WHERE user_id = $1 AND gpu_id = $2", user_id, gpu_id)
                db_count = db_count if db_count is not None else 0
                
                if db_count < count:
                    await db.execute("INSERT INTO gpu_batches (user_id, gpu_id, multiplier, qty, condition, was_repaired) VALUES ($1, $2, 1.0, $3, 100.0, 0)", 
                                   user_id, gpu_id, count - db_count)
                                   
                elif db_count > count:
                    diff = db_count - count
                    rows = await db.fetch("SELECT id, qty FROM gpu_batches WHERE user_id = $1 AND gpu_id = $2 ORDER BY condition ASC", user_id, gpu_id)
                    
                    for row in rows:
                        if diff <= 0: break
                        if row['qty'] <= diff:
                            await db.execute("DELETE FROM gpu_batches WHERE id = $1", row['id'])
                            diff -= row['qty']
                        else:
                            await db.execute("UPDATE gpu_batches SET qty = qty - $1 WHERE id = $2", diff, row['id'])
                            diff = 0

            # Начисляем износ (Для всех одинаково)
            for i in GPUS:
                gpu_id = f'gpu_{i}'
                if farm_data.get(gpu_id, 0) > 0:
                    lifspan_h = float(GPUS[i]['price'] * 1.5) / float(GPUS[i]['income'])
                    wear_per_hour = (100.0 / lifspan_h) * 1.0 
                    total_wear = round(wear_per_hour * elapsed_h * overheat_factor, 2)
            
                    if total_wear > 0:
                        await db.execute("UPDATE gpu_batches SET condition = condition - $1 WHERE user_id = $2 AND gpu_id = $3 AND condition > 0", total_wear, user_id, gpu_id)
                        await db.execute("UPDATE gpu_batches SET condition = 0.0 WHERE condition < 0 AND user_id = $1 AND gpu_id = $2", user_id, gpu_id)
    
    await update_farm(user_id, last_wear_update=current_time)

# ==========================================
# 🧠 ВНУТРЕННИЙ ДВИЖОК
# ==========================================
async def calculate_farm_state(user_id, farm_data): 
    total_income_ph = 0
    total_heat = 0
    total_power_ph = 0
    real_counts = {}
    
    pool = await get_db()
    async with pool.acquire() as db:
        rows = await db.fetch("SELECT gpu_id, SUM(qty) as total FROM gpu_batches WHERE user_id = $1 GROUP BY gpu_id", user_id)
        for row in rows:
            real_counts[row['gpu_id']] = row['total']

    for i in GPUS:
        gpu_id = f'gpu_{i}'
        count = real_counts.get(gpu_id, 0)
        
        if count > 0:
            batches = await get_gpu_batches(user_id, gpu_id, count)
            if batches:
                for batch in batches:
                    hp = batch.get('condition', batch.get('cond', 100.0))
                    if hp > 0:
                        mult = batch.get('mult', 1.0)
                        qty = batch['qty']
                        
                        total_income_ph += int(qty * GPUS[i]["income"] * mult) 
                        total_heat += int(qty * GPUS[i]["heat"] * mult) 
                        total_power_ph += int(qty * GPUS[i].get("power", 0) * ELECTRICITY_PRICE)

    current_time = int(time.time())
    last_collect = farm_data.get('last_collect', current_time)
    elapsed_seconds = current_time - last_collect
    
    is_full = False
    if total_income_ph > 0 and elapsed_seconds >= (MAX_STORAGE_HOURS * 3600):
        elapsed_seconds = MAX_STORAGE_HOURS * 3600
        is_full = True

    pending_profit = int((total_income_ph / 3600) * elapsed_seconds)
    cooling_level = farm_data.get('cooling_level')

    if cooling_level is None or cooling_level not in COOLING:
        cooling_level = 1
        
    cooling_capacity = COOLING[cooling_level]['capacity']

    return total_income_ph, pending_profit, is_full, total_heat, cooling_capacity, total_power_ph


async def perform_collection(user_id, farm_data): 

    await sync_farm_passive(user_id, farm_data) 
    farm_data = await get_farm(user_id)         

    income_ph, pending_profit, _, total_heat, cooling_capacity, power_ph = await calculate_farm_state(user_id, farm_data)
    
    electricity_bill = 0
    fire_message = None
    overheat = total_heat - cooling_capacity

    # ПОЖАР (У всех равные шансы)
    if overheat > 0 and random.random() < min(0.30, (overheat / cooling_capacity) * 0.15):
        owned_gpus = [i for i in GPUS if farm_data.get(f'gpu_{i}', 0) > 0]
        if owned_gpus:
            target_gpu = max(owned_gpus, key=lambda x: GPUS[x]['price'])
            await update_farm(user_id, **{f'gpu_{target_gpu}': farm_data[f'gpu_{target_gpu}'] - 1})
            fire_message = f"💥 <b>ПОЖАР!</b> Из-за перегрева сгорела 1x {GPUS[target_gpu]['name']}."
            return 0, fire_message, None, 0, 0, 0 

    if pending_profit <= 0: 
        return 0, None, None, 0, 0, 0

    current_time = int(time.time())
    last_collect = farm_data.get('last_collect', current_time)
    
    work_seconds = min(current_time - last_collect, MAX_STORAGE_HOURS * 3600)
    elapsed_h = work_seconds / 3600.0
    
    electricity_bill = int(power_ph * elapsed_h)
    tax_rate = get_tax_rate(income_ph) 
        
    tax_amount = int(pending_profit * tax_rate)
    net_profit = max(0, pending_profit - tax_amount - electricity_bill)

    await add_balance(user_id, net_profit, is_income=True)
    await update_farm(user_id, last_collect=current_time)
    
    broken_msg = ""
    broken_summary = {} 
    
    pool = await get_db()
    async with pool.acquire() as db:
        broken_batches = await db.fetch("SELECT id, gpu_id, qty FROM gpu_batches WHERE user_id = $1 AND condition <= 0 AND was_repaired = 0", user_id)
        if broken_batches:
            for row in broken_batches:
                b_id, gpu_id_str, qty = row['id'], row['gpu_id'], row['qty']
                if qty <= 0: continue
                gpu_num = int(gpu_id_str.split('_')[1])
                gpu_name = GPUS.get(gpu_num, {}).get('name', 'Неизвестная карта')
                broken_summary[gpu_name] = broken_summary.get(gpu_name, 0) + qty
                    
    if broken_summary:
        for name, q in broken_summary.items():
            broken_msg += f"🪫 {q}x <b>{name}</b> (Сломались, нужен ремонт!)\n"

    return net_profit, fire_message, broken_msg if broken_msg else None, tax_amount, tax_rate, electricity_bill


# ==========================================
# 🏠 ГЛАВНОЕ МЕНЮ ФЕРМЫ
# ==========================================
@router.message(lambda msg: msg.text and msg.text.lower().strip() in ["ферма", "🏭 ферма", "фарма", "собрать ферму"])
async def cmd_farm(message: types.Message):
    await send_farm_menu(message.from_user.id, message)

@router.callback_query(F.data.startswith("farm_main_"))
async def callback_farm_main(callback: types.CallbackQuery):
    owner_id = int(callback.data.split("_")[-1])
    if callback.from_user.id != owner_id:
        return await callback.answer("🛑 РУКИ ПРОЧЬ! Это чужая ферма!", show_alert=True)
        
    await send_farm_menu(owner_id, callback.message, is_edit=True)
    await callback.answer()

async def send_farm_menu(user_id, message_obj, is_edit=False):
    farm_data = await get_farm(user_id)
    await sync_farm_passive(user_id, farm_data)
    farm_data = await get_farm(user_id)
    balance = await get_balance(user_id)
    
    income_ph, pending_profit, is_full, total_heat, cooling_capacity, power_ph = await calculate_farm_state(user_id, farm_data)
    
    try:
        chat_member = await message_obj.bot.get_chat(user_id)
        user_name = chat_member.first_name
    except:
        user_name = f"Агент {user_id}"
    user_mention = f"<a href='tg://user?id={user_id}'>{user_name}</a>"
    
    current_tax_rate = get_tax_rate(income_ph)
    tax_percent = int(current_tax_rate * 100)

    income_ph_text = f"+{fmt(income_ph)} ᴜ/ч"
    pending_profit_text = f"~{fmt(pending_profit)} ᴜ"

    cooling_level = farm_data.get('cooling_level')
    if cooling_level is None or cooling_level not in COOLING:
        cooling_level = 1
    
    pool = await get_db()
    async with pool.acquire() as db:
        total_cards = await db.fetchval("SELECT SUM(qty) FROM gpu_batches WHERE user_id = $1", user_id) or 0
    
    heat_status = "🟢 Норма"
    if total_heat > cooling_capacity:
        heat_status = "🔴 <b>КРИТИКАЛ (Ускоренный износ!)</b>"
    elif total_heat > cooling_capacity * 0.8:
        heat_status = "🟡 <b>Высокая температура</b>"

    if is_full:
        status = "🔴 <b>СКЛАД ПЕРЕПОЛНЕН!</b>"
    elif income_ph > 0:
        status = "🟢 <b>Ферма работает штатно</b>"
    else:
        status = "⚪️ <b>Ферма выключена</b>"

    header = f"🏭 <b>Турнирная Ферма: {user_mention}</b>"
    sep = "━━━━━━━━━━━━━━━━━━━━"
    balance_style = f"<b>{fmt(balance)} ᴜ</b>"

    text = (
        f"{header}\n"
        f"{sep}\n"
        f"{status}\n\n"
        f"📊 <b>Финансовая сводка</b>\n"
        f"├ 📦 На складе: <b>{pending_profit_text}</b>\n"
        f"├ ⚡️ Доходность: <b>{income_ph_text}</b>\n"
        f"├ 🔌 Оплата ЭЭ: <b>-{fmt(power_ph)} ᴜ/ч</b>\n"
        f"└ 🏛 Налог Арены: <b>{tax_percent}%</b>\n\n"
        f"⚙️ <b>ИНФРАСТРУКТУРА</b>\n"
        f"├ 🖥 Видеокарт в работе: <b>{total_cards} шт.</b>\n"
        f"├ ❄️ Система: {COOLING[cooling_level]['emoji']} <b>{COOLING[cooling_level]['name']}</b>\n"
        f"├ 🌡 Тепловыделение: <b>{fmt(total_heat)} / {fmt(cooling_capacity)}</b>\n"
        f"└ 🚦 Состояние охлада: {heat_status}\n\n"
        f"{sep}\n"
        f"💳 Турнирный капитал: {balance_style}"
    )

    builder = InlineKeyboardBuilder()
    if income_ph > 0:
        builder.row(types.InlineKeyboardButton(text="📥 Собрать прибыль", callback_data=f"farm_collect_{user_id}"))
    builder.row(types.InlineKeyboardButton(text="🖥 Инвентарь", callback_data=f"farm_my_gpus_{user_id}"))
    builder.row(
        types.InlineKeyboardButton(text="🛒 Магазин GPU", callback_data=f"farm_shop_{user_id}"),
        types.InlineKeyboardButton(text="❄️ Охлаждение", callback_data=f"farm_cooling_{user_id}")
    )
    builder.row(types.InlineKeyboardButton(text="❌ Закрыть ферму", callback_data=f"farm_close_{user_id}"))

    if is_edit:
        await safe_edit_text(message_obj, text, builder.as_markup())
    else:
        await message_obj.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")

# ==========================================
# ❌ ЗАКРЫТИЕ ФЕРМЫ
# ==========================================
@router.callback_query(F.data.startswith("farm_close_"))
async def close_farm_menu(callback: types.CallbackQuery):
    owner_id = int(callback.data.split("_")[-1])
    if callback.from_user.id != owner_id:
        return await callback.answer("🛑 РУКИ ПРОЧЬ! Это чужая ферма!", show_alert=True)
    
    try: await callback.message.delete()
    except: await callback.answer("Ферма свернута.", show_alert=True)

# ==========================================
# 🧠 ЯДРО СБОРА ПРИБЫЛИ
# ==========================================
async def process_farm_collection(user_id: int, first_name: str) -> dict:
    farm_data = await get_farm(user_id)
    net_profit, fire_message, broken_msg, tax_amount, tax_rate, elec_bill = await perform_collection(user_id, farm_data)
    
    user_mention = f"<a href='tg://user?id={user_id}'>{first_name}</a>"

    if fire_message:
        return {"status": "fire", "text": f"{user_mention},\n🔥 ПОЖАР НА ФЕРМЕ!\n{fire_message}"}
        
    if net_profit <= 0 and tax_amount <= 0 and not broken_msg:
        return {"status": "empty", "text": f"⚠️ {user_mention}, <b>Склад пуст!</b> Карты еще не успели намайнить UMBREL."}

    total_mined = net_profit + tax_amount + elec_bill
    tax_percent = int(tax_rate * 100)

    header = f"⚡️ <b>{user_mention}, майнинг завершен!</b>"
    sep = "──────────────────"
    footer = "<i>💡 Чем мощнее ферма, тем выше налог!</i>"
    profit_label = f"💵 Зачислено на счет:"
    val_prefix = "+"
    broken_block = f"\n{sep}\n⚠️ <b>ОТЧЕТ ОБ ИЗНОСЕ:</b>\n{broken_msg.strip()}" if broken_msg else ""

    receipt_text = (
        f"{header}\n{sep}\n"
        f"⛏ Добыто: <b>{fmt(total_mined)} ᴜ</b>\n"
        f"🏛 Налог арены ({tax_percent}%): <b>-{fmt(tax_amount)} ᴜ</b>\n"
        f"🔌 Электричество: <b>-{fmt(elec_bill)} ᴜ</b>\n{sep}\n"
        f"{profit_label} <b>{val_prefix}{fmt(net_profit)} ᴜ</b>"
        f"{broken_block}\n\n{footer}"
    )
    
    return {"status": "success", "text": receipt_text, "broken": bool(broken_msg)}

@router.message(F.text.lower().in_(["собрать", "собрать прибыль", "снять прибыль", "сбор"]))
async def text_farm_collect_profit(message: types.Message):
    result = await process_farm_collection(message.from_user.id, message.from_user.first_name)
    await message.reply(result["text"], parse_mode="HTML")

@router.callback_query(F.data.startswith("farm_collect_"))
async def farm_collect_profit(callback: types.CallbackQuery):
    owner_id = int(callback.data.split("_")[-1])
    if callback.from_user.id != owner_id:
        return await callback.answer("🛑 РУКИ ПРОЧЬ! Это чужая ферма!", show_alert=True)
        
    user_id = callback.from_user.id
    result = await process_farm_collection(user_id, callback.from_user.first_name)
    
    if result["status"] == "fire":
        await callback.answer("🔥 ПОЖАР НА ФЕРМЕ!", show_alert=True)
    elif result["status"] == "empty":
        await callback.answer("⚠️ Склад пуст!", show_alert=True)
    else:
        if result.get("broken"):
            await callback.answer("⚠️ Оборудование повреждено!", show_alert=True)
        else:
            await callback.answer("✅ Прибыль в сейфе!", show_alert=False)
            
    await callback.message.answer(result["text"], parse_mode="HTML")
    await send_farm_menu(user_id, callback.message, is_edit=True)

# ==========================================
# ❄️ УЛУЧШЕНИЕ ОХЛАЖДЕНИЯ
# ==========================================
@router.callback_query(F.data.startswith("farm_cooling_"))
async def farm_cooling_menu(callback: types.CallbackQuery):
    owner_id = int(callback.data.split("_")[-1])
    if callback.from_user.id != owner_id: return await callback.answer("🛑 РУКИ ПРОЧЬ!", show_alert=True)

    user_id = callback.from_user.id
    farm_data = await get_farm(user_id)
    current_level = farm_data.get('cooling_level', 1)
    balance = await get_balance(user_id)
    
    if current_level >= len(COOLING): return await callback.answer("У вас уже максимальное охлаждение!", show_alert=True)
        
    next_lvl = current_level + 1
    next_data = COOLING[next_lvl]
    
    text = (
        f"❄️ <b>СИСТЕМА ОХЛАЖДЕНИЯ</b>\n"
        f"════════════════════\n"
        f"Текущий уровень: <b>{COOLING[current_level]['name']}</b>\n"
        f"Отвод тепла: <b>{COOLING[current_level]['capacity']} ед.</b>\n\n"
        f"🔧 <b>Доступно улучшение:</b>\n"
        f"{next_data['emoji']} <b>{next_data['name']}</b>\n"
        f"Отвод тепла: <b>{next_data['capacity']} ед.</b>\n"
        f"💰 Цена: <b>{fmt(next_data['price'])} ᴜ</b>\n\n"
        f"💳 Ваш баланс: <b>{fmt(balance)} ᴜ</b>\n"
        f"<i>Если железо перегреется, ферма сгорит при сборе прибыли!</i>"
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text=f"🛒 Купить улучшение", callback_data=f"farm_buy_cooling_{user_id}"))
    builder.row(types.InlineKeyboardButton(text="◀️ Назад на ферму", callback_data=f"farm_main_{user_id}"))
    
    await safe_edit_text(callback.message, text, builder.as_markup())
    await callback.answer()

@router.callback_query(F.data.startswith("farm_buy_cooling_"))
async def farm_buy_cooling(callback: types.CallbackQuery):
    owner_id = int(callback.data.split("_")[-1])
    if callback.from_user.id != owner_id: return await callback.answer("🛑 РУКИ ПРОЧЬ!", show_alert=True)
    
    user_id = callback.from_user.id
    now = time.time()
    if user_id in shop_cooldowns and (now - shop_cooldowns[user_id] < 1.5): return await callback.answer("⏳ Не торопись!", show_alert=True)
    shop_cooldowns[user_id] = now

    farm_data = await get_farm(user_id)
    current_level = farm_data.get('cooling_level', 1)
    
    if current_level >= len(COOLING): return await callback.answer("Максимальный уровень!", show_alert=True)
        
    next_lvl = current_level + 1
    price = COOLING[next_lvl]['price']
    
    if await get_balance(user_id) < price: return await callback.answer("❌ Недостаточно средств!", show_alert=True)
        
    await add_balance(user_id, -price)
    await update_farm(user_id, cooling_level=next_lvl)
    
    await callback.answer(f"✅ Охлаждение улучшено до {COOLING[next_lvl]['name']}!", show_alert=True)
    await send_farm_menu(user_id, callback.message, is_edit=True)

# ==========================================
# 🛒 МАГАЗИН И КАРТОЧКА ТОВАРА
# ==========================================
async def safe_edit_text(obj, text: str, markup):
    from aiogram.types import CallbackQuery
    message_obj = obj.message if isinstance(obj, CallbackQuery) else obj
    if message_obj.photo:
        try: await message_obj.delete()
        except: pass
        try: await message_obj.answer(text, reply_markup=markup, parse_mode="HTML")
        except: pass
    else:
        try: await message_obj.edit_text(text, reply_markup=markup, parse_mode="HTML")
        except: pass

@router.callback_query(F.data.startswith("farm_shop_"))
async def farm_shop_menu(callback: types.CallbackQuery):
    owner_id = int(callback.data.split("_")[-1])
    if callback.from_user.id != owner_id: return await callback.answer("🛑 РУКИ ПРОЧЬ!", show_alert=True)

    user_id = callback.from_user.id
    balance = await get_balance(user_id)
    
    text = f"🛒 <b>МАГАЗИН ОБОРУДОВАНИЯ</b>\n════════════════════\n💰 Баланс: <b>{fmt(balance)} ᴜ</b>\n\n"
    
    builder = InlineKeyboardBuilder()
    sorted_gpus = sorted([(k, v) for k, v in GPUS.items()], key=lambda x: x[1]['price'])
    
    for i, gpu in sorted_gpus:
        btn_text = f"{gpu['emoji']} {gpu['name']} — {fmt(gpu['price'])} ᴜ"
        builder.button(text=btn_text, callback_data=f"farm_item_{i}_{user_id}")

    builder.button(text="◀️ Назад на ферму", callback_data=f"farm_main_{user_id}")
    builder.adjust(1)
    
    await safe_edit_text(callback, text, builder.as_markup())

@router.callback_query(F.data.startswith("farm_item_"))
async def show_gpu_item(callback: types.CallbackQuery):
    owner_id = int(callback.data.split("_")[-1])
    if callback.from_user.id != owner_id: return await callback.answer("🛑 РУКИ ПРОЧЬ!", show_alert=True)
    
    gpu_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    gpu = GPUS.get(gpu_id)
    balance = await get_balance(user_id)
    farm_data = await get_farm(user_id)
    owned = farm_data.get(f'gpu_{gpu_id}', 0)
    
    current_price = int(gpu['price'])
    max_qty = balance // current_price if current_price > 0 else 0
    sell_price = int(gpu['price'] * 0.5) 

    text = (
        f"{gpu['emoji']} <b>{gpu['name']}</b>\n"
        f"════════════════════\n"
        f"💰 Покупка: <b>{fmt(gpu['price'])} ᴜ</b>\n"
        f"📉 Продажа: <b>{fmt(sell_price)} ᴜ</b> (50%)\n"
        f"⚡️ Доходность: <b>{fmt(gpu['income'])} ᴜ/ч</b>\n"
        f"🌡 Тепловыделение: <b>{gpu['heat']} ед.</b>\n"
        f"📦 В стойках: <b>{owned} шт.</b>\n"
        f"💳 Баланс: <b>{fmt(balance)} ᴜ</b>\n"
        f"════════════════════\n"
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="1 шт", callback_data=f"farm_buy_{gpu_id}_1_{user_id}"),
        types.InlineKeyboardButton(text="5 шт", callback_data=f"farm_buy_{gpu_id}_5_{user_id}"),
        types.InlineKeyboardButton(text="10 шт", callback_data=f"farm_buy_{gpu_id}_10_{user_id}")
    )
    builder.row(types.InlineKeyboardButton(text=f"🛒 Купить MAX ({max_qty} шт)", callback_data=f"farm_buy_{gpu_id}_max_{user_id}"))
    
    if owned > 0:
        builder.row(
            types.InlineKeyboardButton(text="📉 Продать 1", callback_data=f"farm_sell_{gpu_id}_1_{user_id}"),
            types.InlineKeyboardButton(text=f"📉 Продать ВСЕ ({owned})", callback_data=f"farm_sell_{gpu_id}_all_{user_id}")
        )
    
    builder.row(types.InlineKeyboardButton(text="◀️ Назад в магазин", callback_data=f"farm_shop_{user_id}"))
    await safe_edit_text(callback, text, builder.as_markup())

# ==========================================
# 🛒 ПОКУПКА ВИДЕОКАРТЫ ЧЕРЕЗ ТЕКСТ 
# ==========================================
@router.message(F.text.lower().startswith("купить "))
async def text_buy_gpu(message: types.Message):
    user_id = message.from_user.id
    now = time.time()
    if user_id in shop_cooldowns and (now - shop_cooldowns[user_id] < 1.5): return 
    shop_cooldowns[user_id] = now
    
    balance = await get_balance(user_id)
    text = message.text.lower().replace("купить ", "").strip()

    if text in ["видеокарту", "карту"]:
        affordable = {k: v for k, v in GPUS.items() if int(v['price']) <= balance}
        if not affordable:
            return await message.reply(f"💰 Баланс: <b>{fmt(balance)} ᴜ</b>\n❌ Не хватает денег на старт.")
        best_id = max(affordable, key=lambda k: affordable[k]['price'])
        best_gpu = affordable[best_id]
        match = re.search(r'[a-zA-Z]?\d{2,}', best_gpu['name'])
        suggest_word = match.group(0) if match else best_gpu['name']

        return await message.reply(
            f"👤 Твой баланс: <b>{fmt(balance)} ᴜ</b>\n"
            f"🚀 Лучшая карта по бюджету:\n\n"
            f"{best_gpu['emoji']} <b>{best_gpu['name']}</b>\n"
            f"👉 <i>Напиши:</i> <code>купить {suggest_word}</code>",
            parse_mode="HTML"
        )

    def find_gpu(search_str):
        search_str = search_str.lower().strip()
        for word in ["gpu", "видеокарту", "карту"]: search_str = search_str.replace(word, "")
        clean_search = search_str.strip()

        for gid, gpu in GPUS.items():
            model_digits = re.findall(r'\d+', gpu['name'])
            if model_digits and any(d in clean_search for d in model_digits): return gid, gpu
        for gid, gpu in GPUS.items():
            if clean_search in gpu['name'].lower(): return gid, gpu
        return None, None

    parts = text.split()
    target_id, target_gpu = find_gpu(text)
    qty = 1

    if not target_gpu and len(parts) > 1 and parts[-1].isdigit():
        potential_qty = int(parts[-1])
        potential_search = " ".join(parts[:-1]).strip()
        tid, tgpu = find_gpu(potential_search)
        if tgpu:
            target_id = tid
            target_gpu = tgpu
            qty = potential_qty

    if not target_gpu:
        return await message.reply("❌ Карта не найдена!\nПример: <code>купить 5090 5</code>", parse_mode="HTML")

    if qty <= 0: return await message.reply("❌ Количество должно быть больше нуля!")

    total_price = int(target_gpu['price']) * qty

    if balance < total_price:
        return await message.reply(
            f"❌ <b>Не хватает бабок!</b>\n"
            f"{qty} шт. <b>{target_gpu['name']}</b> стоят <b>{fmt(total_price)} ᴜ</b>.\n"
            f"Твой баланс: <b>{fmt(balance)} ᴜ</b>",
            parse_mode="HTML"
        )

    farm_data = await get_farm(user_id)
    _, fire_message, *_ = await perform_collection(user_id, farm_data)
    if fire_message: await message.answer(fire_message, parse_mode="HTML")

    await add_balance(user_id, -total_price)
    farm_data = await get_farm(user_id) 
    
    updates = {f'gpu_{target_id}': farm_data.get(f'gpu_{target_id}', 0) + qty}
    await update_farm(user_id, **updates)
    await sync_farm_passive(user_id, await get_farm(user_id), force_sync=True)

    await message.reply(
        f"🎉 Успешно! Куплено <b>{qty} шт. {target_gpu['name']}</b> за <b>{fmt(total_price)} ᴜ</b>.",
        parse_mode="HTML"
    )

# ==========================================
# 💥 ГЛОБАЛЬНАЯ РАСПРОДАЖА
# ==========================================
@router.message(F.text.lower().in_(["продать все", "продать всё"]))
async def cmd_sell_all_gpus(message: types.Message):
    user_id = message.from_user.id
    farm_data = await get_farm(user_id)
    
    _, fire_message, *_ = await perform_collection(user_id, farm_data)
    if fire_message:
        await message.answer(fire_message, parse_mode="HTML")
        farm_data = await get_farm(user_id) 
        
    total_revenue = 0
    total_cards_sold = 0
    updates = {}
    
    sell_percent = 0.50
    
    pool = await get_db()
    async with pool.acquire() as db:
        for key, qty in farm_data.items():
            if key.startswith('gpu_') and qty > 0:
                gpu_num = int(key.split('_')[1])
                gpu_info = GPUS.get(gpu_num)
                
                if gpu_info:
                    avg_cond = await db.fetchval("SELECT SUM(qty * condition) / SUM(qty) FROM gpu_batches WHERE user_id=$1 AND gpu_id=$2 AND condition>0", user_id, key)
                    if avg_cond is None: avg_cond = 100.0
                    
                    revenue = int((gpu_info['price'] * sell_percent) * (avg_cond / 100.0) * qty)
                    total_revenue += revenue
                    total_cards_sold += qty
                    updates[key] = 0 

    if total_cards_sold == 0: return await message.reply("❌ Ферма пуста!", parse_mode="HTML")

    await add_balance(user_id, total_revenue, is_income=True)
    updates['last_collect'] = int(time.time())
    await update_farm(user_id, **updates)
    await sync_farm_passive(user_id, await get_farm(user_id), force_sync=True)

    await message.reply(
        f"💥 <b>ГЛОБАЛЬНАЯ ОЧИСТКА!</b>\n"
        f"════════════════════\n"
        f"Проданы все карты (<b>{total_cards_sold} шт.</b>).\n"
        f"💰 Выручка (с учетом износа): <b>{fmt(total_revenue)} ᴜ</b>",
        parse_mode="HTML"
    )
    
# ==========================================
# 📉 ПРОДАЖА ВИДЕОКАРТЫ ЧЕРЕЗ ТЕКСТ
# ==========================================
@router.message(F.text.lower().startswith("продать "))
async def text_sell_gpu(message: types.Message):
    user_id = message.from_user.id
    now = time.time()
    if user_id in shop_cooldowns and (now - shop_cooldowns[user_id] < 1.5): return
    shop_cooldowns[user_id] = now
    text = message.text.lower().replace("продать ", "").strip()

    def find_gpu(search_str):
        for gid, gpu in GPUS.items():
            if re.search(r'\b' + re.escape(search_str) + r'\b', gpu['name'].lower()): return gid, gpu
        for gid, gpu in GPUS.items():
            if search_str in gpu['name'].lower(): return gid, gpu
        return None, None

    parts = text.split()
    target_id, target_gpu = find_gpu(text)
    qty_str = "1"

    if not target_gpu and len(parts) > 1 and (parts[-1].isdigit() or parts[-1] in ["все", "всё"]):
        qty_str = parts[-1]
        potential_search = " ".join(parts[:-1]).strip()
        tid, tgpu = find_gpu(potential_search)
        if tgpu:
            target_id = tid
            target_gpu = tgpu

    if not target_gpu: return await message.reply("❌ Карта не найдена!")

    farm_data = await get_farm(user_id)
    owned = farm_data.get(f'gpu_{target_id}', 0)

    if owned <= 0: return await message.reply(f"❌ Нет видеокарт <b>{target_gpu['name']}</b>!", parse_mode="HTML")

    qty = owned if qty_str in ["все", "всё"] else int(qty_str)
    if qty <= 0: return await message.reply("❌ Количество должно быть больше нуля!")
    if qty > owned: return await message.reply(f"❌ В наличии только <b>{owned} шт.</b>", parse_mode="HTML")

    _, fire_message, *_ = await perform_collection(user_id, farm_data)
    if fire_message: await message.answer(fire_message, parse_mode="HTML")
        
    farm_data = await get_farm(user_id)
    owned = farm_data.get(f'gpu_{target_id}', 0)
    qty = min(qty, owned)
    if qty <= 0: return await message.reply(f"🔥 Твои карты сгорели до продажи...", parse_mode="HTML")

    gpu_id_str = f'gpu_{target_id}'  
    avg_condition = 100.0
    
    pool = await get_db()
    async with pool.acquire() as db:
        rows = await db.fetch("SELECT qty, condition FROM gpu_batches WHERE user_id=$1 AND gpu_id=$2 ORDER BY condition ASC", user_id, gpu_id_str)
            
        collected = 0
        cond_points = 0.0
        for r in rows:
            if collected >= qty: break
            take = min(qty - collected, r['qty'])
            cond_points += take * r['condition']
            collected += take
            
        if collected > 0: avg_condition = cond_points / collected

    sell_percent = 0.50
    revenue = int((target_gpu['price'] * sell_percent) * (avg_condition / 100.0) * qty)
    
    await add_balance(user_id, revenue, is_income=True)
    updates = {f'gpu_{target_id}': owned - qty}
    await update_farm(user_id, **updates)
    await sync_farm_passive(user_id, await get_farm(user_id), force_sync=True)

    await message.reply(f"✅ Продано <b>{qty} шт. {target_gpu['name']}</b> за <b>{fmt(revenue)} ᴜ</b> (с учетом износа).", parse_mode="HTML")

# ==========================================
# 💳 ПОКУПКА / ПРОДАЖА КНОПКОЙ
# ==========================================
@router.callback_query(F.data.startswith("farm_buy_"))
async def farm_buy_gpu(callback: types.CallbackQuery):
    owner_id = int(callback.data.split("_")[-1])
    if callback.from_user.id != owner_id: return await callback.answer("🛑 РУКИ ПРОЧЬ!", show_alert=True)

    user_id = callback.from_user.id
    now = time.time()
    if user_id in shop_cooldowns and (now - shop_cooldowns[user_id] < 1.5): return await callback.answer("⏳ Не кликай так быстро!", show_alert=True)
    shop_cooldowns[user_id] = now

    parts = callback.data.split("_")
    gpu_id, qty_str = int(parts[2]), parts[3]
    
    gpu = GPUS.get(gpu_id)
    balance = await get_balance(user_id)
    current_price = int(gpu['price'])
    qty = (balance // current_price) if qty_str == 'max' else int(qty_str)
    
    if qty <= 0: return await callback.answer("❌ Нет денег!", show_alert=True)
    total_price = current_price * qty
    
    if balance < total_price: return await callback.answer("❌ Недостаточно средств!", show_alert=True)
        
    farm_data = await get_farm(user_id)
    _, fire_message, *_ = await perform_collection(user_id, farm_data)
    if fire_message: await callback.message.answer(fire_message, parse_mode="HTML")
        
    await add_balance(user_id, -total_price)
    farm_data = await get_farm(user_id) 
    updates = {f'gpu_{gpu_id}': farm_data.get(f'gpu_{gpu_id}', 0) + qty}
    await update_farm(user_id, **updates)
    await sync_farm_passive(user_id, await get_farm(user_id), force_sync=True)
    
    await callback.answer(f"🎉 Куплено {qty} шт. {gpu['name']}!", show_alert=True)
    await send_farm_menu(user_id, callback.message, is_edit=True)

@router.callback_query(F.data.startswith("farm_sell_"))
async def farm_sell_gpu(callback: types.CallbackQuery):
    owner_id = int(callback.data.split("_")[-1])
    if callback.from_user.id != owner_id: return await callback.answer("🛑 РУКИ ПРОЧЬ!", show_alert=True)
    
    user_id = callback.from_user.id
    now = time.time()
    if user_id in shop_cooldowns and (now - shop_cooldowns[user_id] < 1.5): return await callback.answer("⏳ Идет оценка...", show_alert=True)
    shop_cooldowns[user_id] = now

    parts = callback.data.split("_")
    gpu_id_int, qty_str = int(parts[2]), parts[3]
    gpu = GPUS.get(gpu_id_int)
    
    farm_data = await get_farm(user_id)
    gpu_id_str = f'gpu_{gpu_id_int}'
    owned = farm_data.get(gpu_id_str, 0)
    
    qty = owned if qty_str == 'all' else int(qty_str)
    if qty > owned or qty <= 0: return await callback.answer("❌ Ошибка количества!", show_alert=True)
        
    _, fire_message, *_ = await perform_collection(user_id, farm_data)
    if fire_message:
        await callback.message.answer(fire_message, parse_mode="HTML")
        farm_data = await get_farm(user_id) 
        owned = farm_data.get(gpu_id_str, 0)
        qty = min(qty, owned) 
        if qty <= 0:
            await send_farm_menu(user_id, callback.message, is_edit=True)
            return
            
    avg_condition = 100.0
    pool = await get_db()
    async with pool.acquire() as db:
        rows = await db.fetch("SELECT qty, condition FROM gpu_batches WHERE user_id=$1 AND gpu_id=$2 ORDER BY condition ASC", user_id, gpu_id_str)
            
        collected = 0
        cond_points = 0.0
        for r in rows:
            if collected >= qty: break
            take = min(qty - collected, r['qty'])
            cond_points += take * r['condition']
            collected += take
            
        if collected > 0: avg_condition = cond_points / collected

    sell_percent = 0.50
    total_revenue = int((gpu['price'] * sell_percent) * (avg_condition / 100.0) * qty)

    await add_balance(user_id, total_revenue, is_income=True)
    updates = {gpu_id_str: owned - qty}
    await update_farm(user_id, **updates)
    await sync_farm_passive(user_id, await get_farm(user_id), force_sync=True)
    
    await callback.answer(f"✅ Продано {qty} шт. за {fmt(total_revenue)} ᴜ", show_alert=True)
    await send_farm_menu(user_id, callback.message, is_edit=True)

# ==========================================
# ⚡️ РАЗГОН 
# ==========================================
@router.callback_query(F.data.startswith("farm_overclock_"))
async def btn_overclock_menu(callback: types.CallbackQuery):
    owner_id = int(callback.data.split("_")[-1])
    if callback.from_user.id != owner_id: return await callback.answer("🛑 РУКИ ПРОЧЬ!", show_alert=True)
    await overclock_menu(callback.message, is_edit=True, user_id=callback.from_user.id)
    await callback.answer()

@router.message(F.text.lower() == "разгон")
async def overclock_menu(message: types.Message, is_edit=False, user_id=None):
    if user_id is None: user_id = message.from_user.id
        
    farm_data = await get_farm(user_id)
    owned_gpus = {int(k.split('_')[1]): v for k, v in farm_data.items() if k.startswith('gpu_') and v > 0}
    
    if not owned_gpus:
        msg = "❌ У тебя нет видеокарт для разгона. Купи их в магазине!"
        try:
            if is_edit: return await message.edit_text(msg, reply_markup=InlineKeyboardBuilder().button(text="◀️ Назад", callback_data=f"farm_main_{user_id}").as_markup())
            return await message.reply(msg)
        except: return
        
    text = "⚡️ <b>ЦЕНТР РАЗГОНА</b>\n════════════════════\nВыбери модель оборудования:\n"
    builder = InlineKeyboardBuilder()
    
    for gpu_id, count in owned_gpus.items():
        gpu_info = GPUS.get(gpu_id)
        if gpu_info: builder.button(text=f"{gpu_info['emoji']} {gpu_info['name']} ({count} шт)", callback_data=f"oc_model_{gpu_id}_{user_id}")
            
    builder.button(text="◀️ Назад на ферму", callback_data=f"farm_main_{user_id}")
    builder.adjust(1)
    
    try:
        if is_edit: await safe_edit_text(message, text, builder.as_markup())
        else: await message.reply(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    except: pass

@router.callback_query(F.data.startswith("oc_model_"))
async def oc_batch_menu(callback: types.CallbackQuery):
    owner_id = int(callback.data.split("_")[-1])
    if callback.from_user.id != owner_id: return await callback.answer("🛑 РУКИ ПРОЧЬ!", show_alert=True)

    user_id = callback.from_user.id
    gpu_id_int = int(callback.data.split("_")[2])
    gpu_id = f"gpu_{gpu_id_int}"
    gpu_info = GPUS.get(gpu_id_int)
    
    total_count = (await get_farm(user_id)).get(gpu_id, 0)
    if total_count <= 0: return await callback.answer("Нет карт!", show_alert=True)
        
    batches = await get_gpu_batches(user_id, gpu_id, total_count)
    
    text = (
        f"⚡️ <b>СОСТОЯНИЕ ЧИПОВ: {gpu_info['name']}</b>\n"
        f"════════════════════\n"
        f"Какую партию отправим на стресс-тест?\n"
    )
    
    builder = InlineKeyboardBuilder()
    for batch in batches:
        mult, qty, cond = batch['mult'], batch['qty'], round(batch['cond'], 1)
        status = "🔥 ТОП" if mult > 1.0 else ("📉 БРАК" if mult < 1.0 else "⚙️ СТОК")
        builder.button(text=f"{status} [x{mult}] — {qty} шт. (❤️ {cond}%)", callback_data=f"oc_qty_{gpu_id_int}_{mult}_{cond}_{user_id}")
        
    builder.button(text="◀️ Назад", callback_data=f"oc_back_main_{user_id}")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("oc_back_main_"))
async def oc_back_main_menu(callback: types.CallbackQuery):
    owner_id = int(callback.data.split("_")[-1])
    if callback.from_user.id != owner_id: return await callback.answer("🛑 РУКИ ПРОЧЬ!", show_alert=True)
    await overclock_menu(callback.message, is_edit=True, user_id=owner_id)
    await callback.answer()

@router.callback_query(F.data.startswith("oc_qty_"))
async def oc_qty_menu(callback: types.CallbackQuery):
    owner_id = int(callback.data.split("_")[-1])
    if callback.from_user.id != owner_id: return await callback.answer("🛑 РУКИ ПРОЧЬ!", show_alert=True)

    user_id = callback.from_user.id
    parts = callback.data.split("_")
    gpu_id_int, mult, cond = int(parts[2]), float(parts[3]), float(parts[4])
    
    gpu_id = f"gpu_{gpu_id_int}"
    total_count = (await get_farm(user_id)).get(gpu_id, 0) 
    batches = await get_gpu_batches(user_id, gpu_id, total_count)
    
    available_qty = next((b['qty'] for b in batches if b['mult'] == mult and abs(b['cond'] - cond) < 0.2), 0)
    if available_qty <= 0: return await callback.answer("Карты закончились!", show_alert=True)

    text = (
        f"⚙️ <b>КОЛИЧЕСТВО ДЛЯ РАЗГОНА</b>\n"
        f"════════════════════\n"
        f"Партия: <b>x{mult} (❤️ {cond}%)</b>\n"
        f"Доступно: {available_qty} шт.\n\n"
        f"Сколько карт разгоняем?"
    )
    
    builder = InlineKeyboardBuilder()
    options = [1, 5, 10, 30, 50, 100]
    for opt in options:
        if opt <= available_qty: builder.button(text=f"{opt} шт.", callback_data=f"oc_type_{gpu_id_int}_{mult}_{cond}_{opt}_{user_id}")
    if available_qty not in options:
        builder.button(text=f"ВСЕ {available_qty} шт.", callback_data=f"oc_type_{gpu_id_int}_{mult}_{cond}_{available_qty}_{user_id}")

    builder.button(text="◀️ Назад", callback_data=f"oc_model_{gpu_id_int}_{user_id}")
    builder.adjust(3) 
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("oc_type_"))
async def oc_type_menu(callback: types.CallbackQuery):
    owner_id = int(callback.data.split("_")[-1])
    if callback.from_user.id != owner_id: return await callback.answer("🛑 РУКИ ПРОЧЬ!", show_alert=True)

    user_id = callback.from_user.id
    parts = callback.data.split("_")
    gpu_id_int, mult, cond, qty = int(parts[2]), float(parts[3]), float(parts[4]), int(parts[5])
    gpu_info = GPUS.get(gpu_id_int)

    mod_cost = max(15000, int(gpu_info['price'] * 0.02))
    ext_cost = max(35000, int(gpu_info['price'] * 0.06))

    degradation = max(0, (mult - 1.0) * 0.5) 
    mod_chance = max(0.10, 0.80 - degradation)
    ext_chance = max(0.05, 0.40 - degradation)

    text = (
        f"🌡 <b>ВЫБОР РЕЖИМА: {gpu_info['name']} ({qty} шт)</b>\n"
        f"Текущая мощность: <b>x{mult}</b> | Здоровье: ❤️ {cond}%\n"
        f"════════════════════\n"
        f"Выбери профиль напряжения:\n\n"
        f"🟢 <b>Умеренный:</b>\n"
        f"├ Цена: <b>{fmt(mod_cost)} ᴜ</b> за шт.\n"
        f"├ Шанс успеха: <b>{int(mod_chance * 100)}%</b>\n"
        f"└ Эффект: <b>+0.1</b> / <b>-0.1</b>\n\n"
        f"🔴 <b>Экстремальный:</b>\n"
        f"├ Цена: <b>{fmt(ext_cost)} ᴜ</b> за шт.\n"
        f"├ Шанс успеха: <b>{int(ext_chance * 100)}%</b>\n"
        f"└ Эффект: <b>+0.3</b> / <b>-0.4</b>\n"
        f"════════════════════\n"
        f"⚠️ <i>При неудаче есть 20% шанс критического пробоя (карта сгорит)!</i>"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🟢 Умеренный", callback_data=f"oc_run_{gpu_id_int}_{mult}_{cond}_{qty}_mod_{user_id}")
    builder.button(text="🔴 Экстремальный", callback_data=f"oc_run_{gpu_id_int}_{mult}_{cond}_{qty}_ext_{user_id}")
    builder.button(text="◀️ Отмена", callback_data=f"oc_qty_{gpu_id_int}_{mult}_{cond}_{user_id}")
    builder.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("oc_run_"))
async def process_overclock_run(callback: types.CallbackQuery):
    owner_id = int(callback.data.split("_")[-1])
    if callback.from_user.id != owner_id: return await callback.answer("🛑 РУКИ ПРОЧЬ!", show_alert=True)

    user_id = callback.from_user.id
    now = time.time()
    if user_id in shop_cooldowns and (now - shop_cooldowns[user_id] < 5.0): return await callback.answer("⏳ Стенд работает!", show_alert=True)
    shop_cooldowns[user_id] = now

    await callback.answer() 
    try: await callback.message.edit_reply_markup(reply_markup=None)
    except: pass

    parts = callback.data.split("_")
    gpu_id_int, mult, cond, qty, mode = int(parts[2]), float(parts[3]), float(parts[4]), int(parts[5]), parts[6]
    
    gpu_id = f"gpu_{gpu_id_int}"
    gpu_info = GPUS.get(gpu_id_int)
    
    farm_data = await get_farm(user_id)
    total_count = farm_data.get(gpu_id, 0)
    batches = await get_gpu_batches(user_id, gpu_id, total_count)
    
    target_batch = next((b for b in batches if b['mult'] == mult and abs(b['cond'] - cond) < 0.2), None)
    if not target_batch: return await callback.message.answer("❌ Ошибка: партия не найдена!")
        
    source_cond = target_batch['cond'] 
    degradation = max(0, (mult - 1.0) * 0.5)

    if mode == "mod":
        cost_per_card = max(15000, int(gpu_info['price'] * 0.02))
        chance = max(0.10, 0.80 - degradation)
        reward, penalty = 0.1, 0.1
        mode_name = "🟢 Умеренный"
    else:
        cost_per_card = max(35000, int(gpu_info['price'] * 0.06))
        chance = max(0.05, 0.40 - degradation)
        reward, penalty = 0.3, 0.4
        mode_name = "🔴 Экстремальный"

    total_cost = int(cost_per_card * qty)
    
    if await get_balance(user_id) < total_cost: return await callback.message.answer(f"❌ Нужно {fmt(total_cost)} ᴜ! Не хватает.")
        
    await add_balance(user_id, -total_cost)
    
    stages = [
        (40, "⚡️ Снятие лимитов..."),
        (85, "🔥 Стресс-тест памяти...")
    ]
    
    anim_msg = callback.message
    try: await anim_msg.edit_text(f"⚙️ <b>РАЗГОН: {gpu_info['name']}</b>\n━━━━━━━━━━━━━━━━━━━━\n▶️ Подготовка... <b>[0%]</b>", parse_mode="HTML")
    except: pass
        
    flood_hit = False
    for percent, text in stages:
        if flood_hit: break 
        await asyncio.sleep(2.0) 
        try: await anim_msg.edit_text(f"⚙️ <b>РАЗГОН: {gpu_info['name']}</b>\n━━━━━━━━━━━━━━━━━━━━\n{text} <b>[{percent}%]</b>", parse_mode="HTML")
        except TelegramRetryAfter as e:
            flood_hit = True
            await asyncio.sleep(e.retry_after) 
        except: pass 
            
    if not flood_hit: await asyncio.sleep(1.5) 
        
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data=f"oc_model_{gpu_id_int}_{user_id}")
    
    is_success = random.random() < chance

    if is_success:
        new_mult = min(3.0, round(mult + reward, 2))
        await move_gpu_batch(user_id, gpu_id, mult, new_mult, qty, source_cond)
        final_text = (
            f"⚡️ <b>РАЗГОН УДАЛСЯ! [100%]</b>\n"
            f"════════════════════\n"
            f"Оборудование: <b>{gpu_info['name']}</b> ({qty} шт)\n"
            f"Эффективность: <b>x{mult}</b> ➔ <b>x{new_mult}</b> 🔥\n"
        )
    else:
        if random.random() < 0.20:
            await move_gpu_batch(user_id, gpu_id, mult, mult, qty, 0.0)
            final_text = (
                f"💥 <b>КРИТИЧЕСКИЙ ПРОБОЙ! [FATAL ERROR]</b>\n"
                f"════════════════════\n"
                f"🚨 <b>Здоровье карт упало до 0%! Срочно в ремонт!</b>\n"
            )
        else:
            new_mult = round(max(0.5, mult - penalty), 2)
            await move_gpu_batch(user_id, gpu_id, mult, new_mult, qty, source_cond)
            final_text = (
                f"📉 <b>СБОЙ В СИСТЕМЕ! [FAIL]</b>\n"
                f"════════════════════\n"
                f"Эффективность: <b>x{mult}</b> ➔ <b>x{new_mult}</b> 📉\n"
            )

    retry_count = 0
    while retry_count < 3:
        try:
            await anim_msg.edit_text(final_text, reply_markup=builder.as_markup(), parse_mode="HTML")
            break 
        except TelegramRetryAfter as e:
            retry_count += 1
            await asyncio.sleep(e.retry_after + 0.5) 
        except:
            try:
                await callback.message.answer(final_text, reply_markup=builder.as_markup(), parse_mode="HTML")
                break
            except: break

# ==========================================
# 🖥 ИНВЕНТАРЬ И УПРАВЛЕНИЕ 
# ==========================================
@router.message(F.text.lower().in_(["мои видюхи", "мои видеокарты", "инвентарь", "мои карты", "мои вд"]))
async def cmd_my_gpus(message: types.Message):
    await send_inventory_menu(message.from_user.id, message, is_edit=False)

@router.callback_query(F.data.startswith("farm_my_gpus_"))
async def callback_my_gpus(callback: types.CallbackQuery):
    owner_id = int(callback.data.split("_")[-1])
    if callback.from_user.id != owner_id: return await callback.answer("🛑 РУКИ ПРОЧЬ!", show_alert=True)
    await send_inventory_menu(owner_id, callback.message, is_edit=True)
    await callback.answer()

async def send_inventory_menu(user_id, message_obj, is_edit=False):
    farm_data = await get_farm(user_id) 
    await sync_farm_passive(user_id, farm_data)

    try:
        chat_member = await message_obj.bot.get_chat(user_id)
        user_name = chat_member.first_name
    except: user_name = f"Агент {user_id}"
    user_mention = f"<a href='tg://user?id={user_id}'>{user_name}</a>"

    pool = await get_db()
    async with pool.acquire() as db:
        rows = await db.fetch("SELECT gpu_id, SUM(qty) as total FROM gpu_batches WHERE user_id = $1 GROUP BY gpu_id", user_id)
        total_stats = {row['gpu_id']: row['total'] for row in rows}
        repairable_count = await db.fetchval("SELECT SUM(qty) FROM gpu_batches WHERE user_id = $1 AND condition <= 0 AND was_repaired = 0", user_id) or 0
        dead_count = await db.fetchval("SELECT SUM(qty) FROM gpu_batches WHERE user_id = $1 AND condition <= 0 AND was_repaired = 1", user_id) or 0

    inventory_lines = []
    builder = InlineKeyboardBuilder()
    has_working_cards = False
    sorted_gpus = sorted(GPUS.items(), key=lambda x: x[1]['price'], reverse=True)

    for i, gpu in sorted_gpus:
        gpu_id_str = f'gpu_{i}'
        db_total = total_stats.get(gpu_id_str, 0)
        
        if db_total > 0:
            batches = await get_gpu_batches(user_id, gpu_id_str, db_total)
            working_batches = []
            broken_qty = 0
            dead_qty_local = 0
            
            for b in batches:
                hp = b.get('condition', b.get('cond', 100.0))
                repaired_flag = b.get('was_repaired', 0)
                qty = b['qty']
                
                if hp > 0: working_batches.append(b)
                else:
                    if repaired_flag == 1: dead_qty_local += qty
                    else: broken_qty += qty

            if working_batches or broken_qty > 0 or dead_qty_local > 0:
                has_working_cards = True
                inventory_lines.append(f"<b>{gpu['emoji']} {gpu['name']}</b>")
                
                grouped_batches = {}
                for b in working_batches:
                    cond = round(b.get('condition', b.get('cond', 100.0)), 1) 
                    mult = b.get('multiplier', b.get('mult', 1.0))
                    key = (cond, mult)
                    grouped_batches[key] = grouped_batches.get(key, 0) + b['qty']
                
                for (cond_rounded, mult), b_qty in sorted(grouped_batches.items(), key=lambda x: x[0][0], reverse=True):
                    mult_str = f" [x{mult}]" if mult != 1.0 else ""
                    hp_emoji = "💚" if cond_rounded >= 80 else ("💛" if cond_rounded >= 40 else "💔")
                    inventory_lines.append(f" ├ {b_qty} шт. — {hp_emoji} <b>{cond_rounded:.1f}%</b>{mult_str}")
                
                if broken_qty > 0: inventory_lines.append(f" ├ {broken_qty} шт. — 🪫 <b>0.0%</b> (Сломаны)")
                if dead_qty_local > 0: inventory_lines.append(f" ├ {dead_qty_local} шт. — 💀 <b>Утиль</b>")
                inventory_lines.append(f" └ <i>Ломбард: ~{fmt(int(gpu['price']*0.25))} ᴜ за шт.</i>\n")

    text = f"🖥 <b>ИНВЕНТАРЬ ИГРОКА {user_mention}</b>\n════════════════════\n"
    text += "\n".join(inventory_lines) if has_working_cards else "<i>В стойках нет оборудования.</i>\n\n"
    
    if repairable_count > 0: text += f"⚠️ <b>В ремонте нуждаются: {repairable_count} шт.</b>\n"
    if dead_count > 0: text += f"💀 <b>Сгорели навсегда (в утиль): {dead_count} шт.</b>\n"
            
    if has_working_cards:
        builder.row(types.InlineKeyboardButton(text="📉 Продать", callback_data=f"fsell_list_{user_id}"),
                    types.InlineKeyboardButton(text="⚡️ Разгон", callback_data=f"farm_overclock_{user_id}"))
    
    if repairable_count > 0: builder.row(types.InlineKeyboardButton(text=f"🔧 Ремонтный цех ({repairable_count})", callback_data=f"frepair_list_{user_id}"))
    if dead_count > 0: builder.row(types.InlineKeyboardButton(text=f"🗑 Утилизировать ({dead_count})", callback_data=f"farm_scrap_{user_id}"))
    
    builder.row(types.InlineKeyboardButton(text="◀️ Назад на ферму", callback_data=f"farm_main_{user_id}"))
    
    if is_edit: await safe_edit_text(message_obj, text, builder.as_markup())
    else: await message_obj.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")

# ==========================================
# 🗑 УТИЛИЗАЦИЯ
# ==========================================
@router.callback_query(F.data.startswith("farm_scrap_"))
async def scrap_dead_cards(callback: types.CallbackQuery):
    owner_id = int(callback.data.split("_")[-1])
    if callback.from_user.id != owner_id: return await callback.answer("🛑 РУКИ ПРОЧЬ!", show_alert=True)
    user_id = callback.from_user.id
    
    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            dead_batches = await db.fetch("SELECT gpu_id, SUM(qty) as s_qty FROM gpu_batches WHERE user_id=$1 AND condition <= 0 AND was_repaired = 1 GROUP BY gpu_id", user_id)
            if not dead_batches: return await callback.answer("У вас нет карт для утиля!", show_alert=True)
            await db.execute("DELETE FROM gpu_batches WHERE user_id=$1 AND condition <= 0 AND was_repaired = 1", user_id)

    farm_data = await get_farm(user_id)
    updates = {}
    for row in dead_batches:
        gpu_id_str, qty = row['gpu_id'], row['s_qty']
        current = farm_data.get(gpu_id_str, 0)
        updates[gpu_id_str] = max(0, current - qty)
        
    if updates: await update_farm(user_id, **updates)

    await callback.answer("🗑 Навсегда сгоревшие видеокарты выброшены на свалку!", show_alert=True)
    await send_inventory_menu(user_id, callback.message, is_edit=True)

# ==========================================
# 📉 ПРОДАЖА ИЗ ИНВЕНТАРЯ
# ==========================================
@router.callback_query(F.data.startswith("fsell_list_"))
async def inventory_sell_list(callback: types.CallbackQuery):
    owner_id = int(callback.data.split("_")[-1])
    if callback.from_user.id != owner_id: return await callback.answer("🛑 РУКИ ПРОЧЬ!", show_alert=True)

    user_id = callback.from_user.id
    farm_data = await get_farm(user_id)
    builder = InlineKeyboardBuilder()
    has_cards = False
    
    for gpu_id, gpu_info in GPUS.items():
        owned = farm_data.get(f'gpu_{gpu_id}', 0)
        if owned > 0:
            has_cards = True
            builder.button(text=f"📉 {gpu_info['emoji']} {gpu_info['name']} ({owned} шт)", callback_data=f"farm_item_{gpu_id}_{user_id}")

    if not has_cards: return await callback.answer("У тебя нет карт!", show_alert=True)

    builder.button(text="◀️ Назад в инвентарь", callback_data=f"farm_my_gpus_{user_id}")
    builder.adjust(1) 

    text = "📉 <b>ПРОДАЖА ОБОРУДОВАНИЯ</b>\n════════════════════\nВыбери модель (возврат с учетом износа):\n"
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    
# ==========================================
# 🔧 СИСТЕМА РЕМОНТА
# ==========================================
@router.callback_query(F.data.startswith("frepair_list_"))
async def frepair_list_menu(callback: types.CallbackQuery):
    owner_id = int(callback.data.split("_")[-1])
    if callback.from_user.id != owner_id: return await callback.answer("🛑 РУКИ ПРОЧЬ!", show_alert=True)

    user_id = callback.from_user.id
    pool = await get_db()
    async with pool.acquire() as db:
        broken_batches = await db.fetch("SELECT gpu_id, SUM(qty) as total_broken FROM gpu_batches WHERE user_id = $1 AND condition <= 0 AND was_repaired = 0 GROUP BY gpu_id", user_id)

    if not broken_batches: return await callback.answer("✅ Нет сломанных карт!", show_alert=True)

    text = "🔧 <b>РЕМОНТНЫЙ ЦЕХ</b>\n════════════════════\nКакое оборудование отдаем мастеру?\n\n"
    builder = InlineKeyboardBuilder()

    for batch in broken_batches:
        gpu_num = int(batch['gpu_id'].split('_')[1])
        gpu_info = GPUS.get(gpu_num)
        broken_qty = batch['total_broken']
        repair_cost = int(gpu_info['price'] * 0.3 * broken_qty)
        
        text += f"🪫 <b>{gpu_info['name']}</b> ({broken_qty} шт)\n└ <i>Ремонт всех: {fmt(repair_cost)} ᴜ</i>\n\n"
        builder.button(text=f"🔧 Починить {gpu_info['name']}", callback_data=f"frepair_qty_{gpu_num}_{user_id}")

    builder.button(text="◀️ Назад в инвентарь", callback_data=f"farm_my_gpus_{user_id}")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("frepair_qty_"))
async def frepair_qty_menu(callback: types.CallbackQuery):
    owner_id = int(callback.data.split("_")[-1])
    if callback.from_user.id != owner_id: return await callback.answer("🛑 РУКИ ПРОЧЬ!", show_alert=True)

    user_id = callback.from_user.id
    gpu_num = int(callback.data.split("_")[2])
    gpu_id_str = f"gpu_{gpu_num}"
    gpu_info = GPUS.get(gpu_num)

    pool = await get_db()
    async with pool.acquire() as db:
        broken_qty = await db.fetchval("SELECT SUM(qty) FROM gpu_batches WHERE user_id = $1 AND gpu_id = $2 AND condition <= 0 AND was_repaired = 0", user_id, gpu_id_str) or 0

    if broken_qty <= 0: return await callback.answer("❌ Карты не найдены!", show_alert=True)

    repair_cost_per_card = int(gpu_info['price'] * 0.3)
    text = (
        f"🔧 <b>КОЛИЧЕСТВО ДЛЯ РЕМОНТА</b>\n"
        f"════════════════════\n"
        f"Модель: <b>{gpu_info['name']}</b>\n"
        f"Ожидает ремонта: <b>{broken_qty} шт.</b>\n"
        f"Цена за 1 шт: <b>{fmt(repair_cost_per_card)} ᴜ</b>\n\n"
        f"Сколько карт восстанавливаем?"
    )

    builder = InlineKeyboardBuilder()
    options = [1, 5, 10, 50]
    for opt in options:
        if opt <= broken_qty: builder.button(text=f"{opt} шт.", callback_data=f"frepair_do_{gpu_num}_{opt}_{user_id}")
    if broken_qty not in options:
        builder.button(text=f"ВСЕ {broken_qty} шт.", callback_data=f"frepair_do_{gpu_num}_{broken_qty}_{user_id}")

    builder.button(text="◀️ Назад", callback_data=f"frepair_list_{user_id}")
    builder.adjust(3) 
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("frepair_do_"))
async def frepair_execute(callback: types.CallbackQuery):
    owner_id = int(callback.data.split("_")[-1])
    if callback.from_user.id != owner_id: return await callback.answer("🛑 РУКИ ПРОЧЬ!", show_alert=True)

    user_id = callback.from_user.id
    now = time.time()
    if user_id in shop_cooldowns and (now - shop_cooldowns[user_id] < 1.5): return await callback.answer("⏳ Мастер уже работает!", show_alert=True)
    shop_cooldowns[user_id] = now

    parts = callback.data.split("_")
    gpu_num = int(parts[2])
    qty_to_repair = int(parts[3]) 

    farm_data = await get_farm(user_id)
    await sync_farm_passive(user_id, farm_data)

    gpu_id_str = f"gpu_{gpu_num}"
    gpu_info = GPUS.get(gpu_num)
    repair_cost = int(gpu_info['price'] * 0.3 * qty_to_repair)

    current_balance = await get_balance(user_id)
    if current_balance < repair_cost: return await callback.answer(f"💸 Не хватает средств! Нужно {fmt(repair_cost)} ᴜ", show_alert=True)

    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            broken_qty = await db.fetchval("SELECT SUM(qty) FROM gpu_batches WHERE user_id = $1 AND gpu_id = $2 AND condition <= 0 AND was_repaired = 0", user_id, gpu_id_str) or 0
            if broken_qty < qty_to_repair: return await callback.answer("❌ Нет столько сломанных карт!", show_alert=True)
                
            await db.execute("UPDATE users SET balance = balance - $1 WHERE user_id = $2", repair_cost, user_id)
            rows = await db.fetch("SELECT id, qty, multiplier FROM gpu_batches WHERE user_id = $1 AND gpu_id = $2 AND condition <= 0 AND was_repaired = 0 ORDER BY id", user_id, gpu_id_str)
            
            remaining = qty_to_repair
            for r in rows:
                if remaining <= 0: break
                b_id, b_qty, mult = r['id'], r['qty'], r['multiplier']
                take = min(b_qty, remaining)
                
                if take == b_qty: await db.execute("UPDATE gpu_batches SET condition = 100.0, was_repaired = 1 WHERE id = $1", b_id)
                else:
                    await db.execute("UPDATE gpu_batches SET qty = qty - $1 WHERE id = $2", take, b_id)
                    exist_rep = await db.fetchval("SELECT id FROM gpu_batches WHERE user_id = $1 AND gpu_id = $2 AND multiplier = $3 AND condition = 100.0 AND was_repaired = 1", user_id, gpu_id_str, mult)
                    if exist_rep: await db.execute("UPDATE gpu_batches SET qty = qty + $1 WHERE id = $2", take, exist_rep)
                    else: await db.execute("INSERT INTO gpu_batches (user_id, gpu_id, multiplier, qty, condition, was_repaired) VALUES ($1, $2, $3, $4, 100.0, 1)", user_id, gpu_id_str, mult, take)
                remaining -= take

    await callback.answer(f"✅ Успешно! {qty_to_repair} шт. {gpu_info['name']} починено. Списано {fmt(repair_cost)} ᴜ", show_alert=True)
    await send_inventory_menu(user_id, callback.message, is_edit=True)