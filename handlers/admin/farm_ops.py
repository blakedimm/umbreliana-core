import os
import re
import time
from datetime import datetime

from aiogram import Router, types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.database import (
    get_db, resolve_user_id, get_gpu_batches
)
from handlers.users.statuses import has_active_status
from handlers.syndicate.farms import (
    get_farm, update_farm, calculate_farm_state, 
    get_tax_rate, perform_collection, GPUS
)

router = Router()
# ==========================================
# 🔐 СИСТЕМНЫЕ ПЕРЕМЕННЫЕ И ДОСТУПЫ (RBAC)
# ==========================================
ADMIN_ID = int(os.getenv("ADMIN_ID", 1412940726))

# Достаем список модераторов из .env и чистим от пробелов
MODERATORS = [int(i.strip()) for i in os.getenv("MODERATORS", "").split(",") if i.strip()]

def is_moderator(user_id):
    """Проверяет, является ли пользователь Создателем или Модератором"""
    return user_id == ADMIN_ID or user_id in MODERATORS

def fmt(num):
    return f"{int(num):,}".replace(",", " ")

async def get_target_id(message: types.Message):
    if message.reply_to_message:
        return message.reply_to_message.from_user.id
    parts = message.text.split()
    if len(parts) > 1:
        return await resolve_user_id(parts[1]) 
    return None

# ==========================================
# 🛠 ВСПОМОГАТЕЛЬНЫЕ ПАРСЕРЫ ДЛЯ GPU
# ==========================================

def parse_bulk_query(text):
    """Разбирает строку вида '3060 2, 5060 4' в список (search_str, qty)"""
    items = []
    for part in text.split(','):
        part = part.strip()
        if not part: continue
        sub_parts = part.split()
        if len(sub_parts) == 1:
            qty = 1
            search_str = sub_parts[0].lower()
        else:
            qty_str = sub_parts[-1]
            if qty_str.isdigit():
                qty = int(qty_str)
                search_str = " ".join(sub_parts[:-1]).lower()
            else:
                qty = 1
                search_str = " ".join(sub_parts).lower()
        items.append((search_str, qty))
    return items

def find_gpu_universal(search_str):
    """Универсальный поиск видеокарты по названию"""
    for gid, gpu in GPUS.items():
        if re.search(r'\b' + re.escape(search_str) + r'\b', gpu['name'].lower()):
            return gid, gpu
    for gid, gpu in GPUS.items():
        if search_str in gpu['name'].lower():
            return gid, gpu
    return None, None

def find_gpu_by_text(text):
    search_str = text.lower().strip()
    for gid, gpu in GPUS.items():
        if re.search(r'\b' + re.escape(search_str) + r'\b', gpu['name'].lower()):
            return gid, gpu
    for gid, gpu in GPUS.items():
        if search_str in gpu['name'].lower():
            return gid, gpu
    return None, None

def parse_gpu_command(text, prefix):
    raw_text = text.lower().replace(prefix, "").strip()
    parts = raw_text.split()
    qty = 1
    search_term = raw_text
    if len(parts) > 1 and parts[-1].isdigit():
        qty = int(parts[-1])
        search_term = " ".join(parts[:-1]).strip()
    return search_term, qty

# ==========================================
# 🏭 БАЗОВОЕ УПРАВЛЕНИЕ (ШПАРГАЛКИ И ВЫДАЧА)
# ==========================================

@router.message((F.text.lower() == "админ ферма") & (F.from_user.id == ADMIN_ID))
async def admin_farm_help(message: types.Message):
    text = "👑 <b>ШПАРГАЛКА ПО ID ВИДЕОКАРТ:</b>\n════════════════════\n"
    for i, gpu in sorted(GPUS.items(), key=lambda x: x[1]['price']):
        text += f"ID: <b>{i}</b> ➔ {gpu.get('emoji', '🖥')} {gpu['name']} | 💰 <b>{fmt(gpu['price'])} ᴜ</b>\n"
    text += "════════════════════"
    await message.reply(text, parse_mode="HTML")

@router.message(F.text.lower() == "видюхи")
async def cmd_global_gpus(message: types.Message):
    pool = await get_db()
    async with pool.acquire() as db:
        rows = await db.fetch("SELECT gpu_id, SUM(qty) as total FROM gpu_batches GROUP BY gpu_id")
        db_stats = {r['gpu_id']: r['total'] for r in rows}
        
    text = "👑 <b>ГЛОБАЛЬНО:</b>\n"
    for i, gpu in GPUS.items():
        text += f"{gpu.get('emoji', '🖥')} {gpu['name']}: <b>{db_stats.get(f'gpu_{i}', 0)} шт.</b>\n"
    await message.reply(text, parse_mode="HTML")

@router.message(F.text.lower().startswith("+карта оптом ") & (F.from_user.id == ADMIN_ID))
async def cmd_admin_bulk_give(message: types.Message):
    raw_text = message.text.lower().replace("+карта оптом ", "").strip()
    parsed_items = parse_bulk_query(raw_text)
    if not parsed_items: return await message.reply("❌ Ошибка формата.")
        
    target_user = message.reply_to_message.from_user.id if message.reply_to_message else message.from_user.id
    farm_data = await get_farm(target_user)
    
    added_log = []
    updates = {}
    pool = await get_db()
    
    async with pool.acquire() as db:
        async with db.transaction():
            for search_str, qty in parsed_items:
                gid, gpu = find_gpu_universal(search_str)
                if not gpu:
                    added_log.append(f"❌ <i>'{search_str}' не найдено</i>")
                    continue
                    
                gpu_id_str = f'gpu_{gid}'
                current_count = updates.get(gpu_id_str, farm_data.get(gpu_id_str, 0))
                updates[gpu_id_str] = current_count + qty
                
                await db.execute("""
                    INSERT INTO gpu_batches (user_id, gpu_id, multiplier, qty, condition, was_repaired) 
                    VALUES ($1, $2, 1.0, $3, 100.0, 0)
                """, target_user, gpu_id_str, qty)
                
                added_log.append(f"✅ {gpu.get('emoji', '🖥')} {gpu['name']}: <b>+{qty} шт.</b>")
            
    if updates:
        updates['last_wear_update'] = int(time.time())
        await update_farm(target_user, **updates)
        
    await message.reply(f"🚛 <b>ОПТОВАЯ ПОСТАВКА!</b>\n" + "\n".join(added_log), parse_mode="HTML")

@router.message(F.text.lower().startswith("+карта ") & (F.from_user.id == ADMIN_ID) & (~F.text.lower().startswith("+карта оптом")))
async def admin_give_card(message: types.Message):
    search_term, qty = parse_gpu_command(message.text, "+карта ")
    gpu_num, target_gpu = find_gpu_by_text(search_term)
    if not target_gpu: return await message.reply("❌ Не найдено.")
    
    gpu_id_str = f"gpu_{gpu_num}"
    target_user = message.reply_to_message.from_user.id if message.reply_to_message else message.from_user.id
    farm_data = await get_farm(target_user)
    
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute("""
            INSERT INTO gpu_batches (user_id, gpu_id, multiplier, qty, condition, was_repaired) 
            VALUES ($1, $2, 1.0, $3, 100.0, 0)
        """, target_user, gpu_id_str, qty)

    await update_farm(target_user, **{gpu_id_str: farm_data.get(gpu_id_str, 0) + qty, 'last_wear_update': int(time.time())})
    await message.reply(f"👑 Выдано: <b>{qty}x {target_gpu['name']}</b>")

@router.message(F.text.lower().startswith("-карта ") & (F.from_user.id == ADMIN_ID))
async def admin_take_card(message: types.Message):
    raw_args = message.text[len("-карта "):].strip().split()
    if not raw_args:
        return await message.reply("⚠️ Укажи цель и карту. Пример: <code>-карта @elon_zxc 20</code>", parse_mode="HTML")

    target_id = None
    target_name = "Игрок"
    gpu_search_parts = raw_args

    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        target_name = message.reply_to_message.from_user.first_name
    else:
        first_arg = raw_args[0]
        if first_arg.startswith('@') or (first_arg.isdigit() and len(first_arg) >= 6):
            target_id = await resolve_user_id(first_arg)
            if not target_id: return await message.reply("❌ Игрок не найден.")
            target_name = first_arg
            gpu_search_parts = raw_args[1:] 
        else:
            return await message.reply("⚠️ Ответь на сообщение или укажи цель: <code>-карта @юзер [карта] [кол-во]</code>", parse_mode="HTML")

    if not gpu_search_parts: return await message.reply("⚠️ Ты не указал, какую карту нужно забрать!")

    simulated_text = "-карта " + " ".join(gpu_search_parts)
    search_term, qty = parse_gpu_command(simulated_text, "-карта ")
    
    gpu_num, target_gpu = None, None
    if search_term.isdigit() and int(search_term) in GPUS:
        gpu_num = int(search_term)
        target_gpu = GPUS[gpu_num]
    else:
        gpu_num, target_gpu = find_gpu_by_text(search_term)
        
    if not target_gpu: return await message.reply("❌ Видеокарта не найдена.")

    gpu_id_str = f"gpu_{gpu_num}"
    farm_data = await get_farm(target_id)
    current_count = farm_data.get(gpu_id_str, 0)

    if current_count == 0: return await message.reply(f"У <b>{target_name}</b> нет таких карт в стойках.", parse_mode="HTML")
    qty = min(qty, current_count)

    try: await perform_collection(target_id, farm_data)
    except Exception as e: print(f"Ошибка сбора при изъятии карты: {e}")

    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            batches = await db.fetch("SELECT id, qty FROM gpu_batches WHERE user_id = $1 AND gpu_id = $2 ORDER BY condition ASC", target_id, gpu_id_str)
            left_to_remove = qty
            for batch in batches:
                if left_to_remove <= 0: break
                b_id, b_qty = batch['id'], batch['qty']
                if b_qty <= left_to_remove:
                    await db.execute("DELETE FROM gpu_batches WHERE id = $1", b_id)
                    left_to_remove -= b_qty
                else:
                    await db.execute("UPDATE gpu_batches SET qty = qty - $1 WHERE id = $2", left_to_remove, b_id)
                    left_to_remove = 0

    await update_farm(target_id, **{gpu_id_str: current_count - qty, 'last_collect': int(time.time())})
    await message.reply(f"💥 Изъято: <b>{qty}x {target_gpu['name']}</b> у пользователя <b>{target_name}</b>.", parse_mode="HTML")

# ==========================================
# 🔎 ИНТЕРФЕЙС И ОЦЕНКА ФЕРМЫ (ИИ-АУДИТ)
# ==========================================

async def admin_check_farm_logic(target_id, message_obj, is_edit=False, is_admin=False):
    farm_data = await get_farm(target_id)
    if not farm_data:
        text = "❌ У этого игрока нет фермы."
        return await (message_obj.edit_text(text) if is_edit else message_obj.reply(text))

    income_ph, pending_profit, is_full, total_heat, cooling_capacity, power_ph = await calculate_farm_state(target_id, farm_data)
    
    # 1. Тянем статистику из БД
    pool = await get_db()
    async with pool.acquire() as db:
        rows = await db.fetch("SELECT gpu_id, SUM(qty) as total FROM gpu_batches WHERE user_id = $1 GROUP BY gpu_id", target_id)
        total_stats = {row['gpu_id']: row['total'] for row in rows}
        repairable_count = await db.fetchval("SELECT SUM(qty) FROM gpu_batches WHERE user_id = $1 AND condition <= 0 AND was_repaired = 0", target_id) or 0
        dead_count = await db.fetchval("SELECT SUM(qty) FROM gpu_batches WHERE user_id = $1 AND condition <= 0 AND was_repaired = 1", target_id) or 0

    inventory_lines = []
    has_working_cards = False
    sorted_gpus = sorted(GPUS.items(), key=lambda x: x[1]['price'], reverse=True)

    # 2. Рендерим инвентарь по новому стандарту
    for i, gpu in sorted_gpus:
        gpu_id_str = f'gpu_{i}'
        db_total = total_stats.get(gpu_id_str, 0)
        
        if db_total > 0:
            batches = await get_gpu_batches(target_id, gpu_id_str, db_total)
            working_batches = []
            saved_qty = broken_qty = dead_qty_local = 0
            
            for b in batches:
                hp = b.get('condition', b.get('cond', 100.0))
                repaired_flag = b.get('was_repaired', 0)
                qty = b['qty']
                
                if hp > 0:
                    if repaired_flag == -1 and hp <= 1.0: saved_qty += qty
                    else: working_batches.append(b)
                else:
                    if repaired_flag == 1: dead_qty_local += qty
                    else: broken_qty += qty

            if working_batches or saved_qty > 0 or broken_qty > 0 or dead_qty_local > 0:
                has_working_cards = True
                inventory_lines.append(f"<b>{gpu.get('emoji', '🖥')} {gpu['name']}</b> (ID: <b>{i}</b>)")
                
                grouped_batches = {}
                for b in working_batches:
                    cond_rounded = round(b.get('condition', b.get('cond', 100.0)), 1)
                    mult = b.get('multiplier', b.get('mult', 1.0))
                    key = (cond_rounded, mult)
                    grouped_batches[key] = grouped_batches.get(key, 0) + b['qty']
                
                for (cond_rounded, mult), b_qty in sorted(grouped_batches.items(), key=lambda x: x[0][0], reverse=True):
                    mult_str = f" [x{mult}]" if mult != 1.0 else ""
                    hp_emoji = "💚" if cond_rounded >= 80 else ("💛" if cond_rounded >= 40 else "💔")
                    inventory_lines.append(f" ├ {b_qty} шт. — {hp_emoji} <b>{cond_rounded:.1f}%</b>{mult_str}")
                
                if saved_qty > 0: inventory_lines.append(f" ├ {saved_qty} шт. — 🛡 <b>1.0%</b> (Спасены)")
                if broken_qty > 0: inventory_lines.append(f" ├ {broken_qty} шт. — 🪫 <b>0.0%</b> (Сломаны)")
                if dead_qty_local > 0: inventory_lines.append(f" ├ {dead_qty_local} шт. — 💀 <b>Утиль</b>")
                inventory_lines.append(f" └ <i>Базовая цена: {fmt(gpu['price'])} ᴜ</i>\n")

    inventory_text = "\n".join(inventory_lines) if has_working_cards else " └ <i>В стойках нет оборудования.</i>\n"
    tax_percent = int(get_tax_rate(income_ph) * 100)

    # 3. Сборка финального текста
    text = (
        f"🔎 <b>ДОСЬЕ ФЕРМЫ:</b> <code>{target_id}</code>\n"
        f"════════════════════\n"
        f"⚡️ Доход: <b>{fmt(income_ph)} ᴜ/ч</b>\n"
        f"🔌 Энергия: <b>{fmt(power_ph)} ᴜ/ч</b>\n"
        f"🏛 Налог: <b>{tax_percent}%</b>\n"
        f"🌡 Тепло: <b>{fmt(total_heat)} / {fmt(cooling_capacity)}</b>\n"
        f"════════════════════\n"
        f"🖥 <b>Оборудование:</b>\n{inventory_text}"
    )
    
    if repairable_count > 0: text += f"⚠️ <b>В ремонте нуждаются: {repairable_count} шт.</b>\n"
    if dead_count > 0: text += f"💀 <b>Сгорели навсегда: {dead_count} шт.</b>\n"

    # 4. Админские кнопки
    builder = InlineKeyboardBuilder()
    if is_admin:
        builder.row(types.InlineKeyboardButton(text="🎁 Подарить карту", callback_data=f"adm_gift_list_{target_id}"))
        builder.row(
            types.InlineKeyboardButton(text="📉 Конфискация", callback_data=f"adm_farm_conf_{target_id}"),
            types.InlineKeyboardButton(text="💥 Сжечь всё", callback_data=f"adm_farm_burn_{target_id}")
        )
    
    if is_edit:
        try: await message_obj.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
        except: pass
    else:
        await message_obj.reply(text, reply_markup=builder.as_markup(), parse_mode="HTML")

CHECK_FARM_PATTERN = re.compile(r"^чек\s+ферма(?:\s+([@\w]+))?$", re.IGNORECASE)

@router.message(F.text.lower().startswith("чек ферма"))
async def admin_check_farm_cmd(message: types.Message):
    user_id = message.from_user.id
    is_admin = (user_id == ADMIN_ID)
    is_sovereign = await has_active_status(user_id, 777)
    
    if not is_admin and not is_sovereign: return 
        
    match = CHECK_FARM_PATTERN.match(message.text.lower())
    target_str = match.group(1) if match else None
    target_id = None

    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
    elif target_str:
        target_id = await resolve_user_id(target_str)

    if not target_id: 
        return await message.reply("⚠️ Ответь на сообщение или укажи ID / @username.\nПример: <code>чек ферма @elon_zxc</code>", parse_mode="HTML")
    
    await admin_check_farm_logic(target_id, message, is_admin=is_admin)

@router.callback_query(F.data.startswith("adm_farm_back_") & (F.from_user.id == ADMIN_ID))
async def admin_farm_back_btn(callback: types.CallbackQuery):
    target_id = int(callback.data.split("_")[3])
    await admin_check_farm_logic(target_id, callback.message, is_edit=True, is_admin=True)
    await callback.answer()

@router.callback_query(F.data.startswith("adm_gift_list_") & (F.from_user.id == ADMIN_ID))
async def admin_gift_gpu_selection(callback: types.CallbackQuery):
    target_id = int(callback.data.split("_")[3])
    builder = InlineKeyboardBuilder()
    for i, gpu in sorted(GPUS.items(), key=lambda x: x[1]['price']):
        builder.button(text=f"{gpu.get('emoji', '🖥')} {gpu['name']}", callback_data=f"adm_do_gift_{target_id}_{i}")
    builder.adjust(2)
    builder.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data=f"adm_farm_back_{target_id}"))
    await callback.message.edit_text("🎁 Какую карту дарим?", reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("adm_do_gift_") & (F.from_user.id == ADMIN_ID))
async def admin_execute_gift(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    target_id, gpu_id = int(parts[3]), int(parts[4])
    
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute("""
            INSERT INTO gpu_batches (user_id, gpu_id, multiplier, qty, condition, was_repaired) 
            VALUES ($1, $2, 1.0, 1, 100.0, 0)
        """, target_id, f"gpu_{gpu_id}")
        
    farm_data = await get_farm(target_id)
    await update_farm(target_id, **{f'gpu_{gpu_id}': farm_data.get(f'gpu_{gpu_id}', 0) + 1})
    await callback.answer(f"✅ Выдано!", show_alert=True)
    await admin_check_farm_logic(target_id, callback.message, is_edit=True, is_admin=True)

@router.callback_query(F.data.startswith("adm_farm_conf_") & (F.from_user.id == ADMIN_ID))
async def admin_confiscate_farm_btn(callback: types.CallbackQuery):
    target_id = int(callback.data.split("_")[3])
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute("DELETE FROM gpu_batches WHERE user_id = $1", target_id)
        
    updates = {f'gpu_{i}': 0 for i in range(1, 100)}
    updates['last_collect'] = int(time.time())
    await update_farm(target_id, **updates)
    await callback.message.edit_text("📉 Ферма очищена.")

@router.callback_query(F.data.startswith("adm_farm_burn_") & (F.from_user.id == ADMIN_ID))
async def admin_burn_farm_btn(callback: types.CallbackQuery):
    target_id = int(callback.data.split("_")[3])
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute("DELETE FROM gpu_batches WHERE user_id = $1", target_id)
        
    updates = {f'gpu_{i}': 0 for i in range(1, 100)}
    updates['cooling_level'] = 1
    updates['last_collect'] = int(time.time())
    await update_farm(target_id, **updates)
    await callback.message.edit_text("🔥 Ферма уничтожена дотла.")

@router.message(F.text.lower().startswith("оценка фермы") | F.text.lower().startswith("аудит"))
async def cmd_farm_audit(message: types.Message):
    target_id = message.from_user.id
    target_name = message.from_user.first_name
    
    args = message.text.split()
    if len(args) > 2 and args[2].isdigit() and message.from_user.id == ADMIN_ID:
        target_id = int(args[2])
        target_name = f"Агент {target_id}"
    elif message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        target_name = message.reply_to_message.from_user.first_name

    farm_data = await get_farm(target_id)
    if not farm_data: 
        return await message.reply("❌ У этого пользователя нет фермы для аудита.")

    income_ph, pending_profit, is_full, total_heat, cooling_capacity, power_ph = await calculate_farm_state(target_id, farm_data)
    
    if income_ph == 0 and total_heat == 0:
         return await message.reply("🕸 Ферма пуста. Оценивать пока нечего.")

    tax_rate = get_tax_rate(income_ph)
    is_magnate = await has_active_status(target_id, 2)
    is_enthusiast = await has_active_status(target_id, 0)
    is_technician = await has_active_status(target_id, 1)
    is_architect = await has_active_status(target_id, 4)

    if is_magnate: tax_rate = 0.0
    elif is_enthusiast and tax_rate > 0.05: tax_rate = 0.05

    if is_technician: power_ph = 0
    elif is_enthusiast: power_ph = int(power_ph * 0.75)

    net_income_ph = income_ph - int(income_ph * tax_rate) - power_ph
    if is_architect: net_income_ph = int(net_income_ph * 1.5)
    daily_net = net_income_ph * 24

    total_investment, total_health, cards_count, repair_debt = 0, 0, 0, 0
    alive_cards, dead_cards = 0, 0
    
    pool = await get_db()
    async with pool.acquire() as db:
        rows = await db.fetch("SELECT gpu_id, qty, condition FROM gpu_batches WHERE user_id = $1", target_id)
        for row in rows:
            try:
                gpu_num = int(row['gpu_id'].split('_')[1])
                if gpu_num not in GPUS: continue 
                price, qty = GPUS[gpu_num]['price'], row['qty']
                total_investment += price * qty
                cards_count += qty
                
                if row['condition'] > 0: 
                    total_health += row['condition'] * qty
                    alive_cards += qty
                else: 
                    repair_debt += int(price * 0.3 * qty)
                    dead_cards += qty
            except: continue

    avg_health = (total_health / alive_cards) if alive_cards > 0 else 0.0
    roi_days = int(total_investment / daily_net) if daily_net > 0 else float('inf')

    score = 0
    if avg_health >= 90: score += 30
    elif avg_health >= 70: score += 25
    elif avg_health >= 50: score += 15
    elif avg_health >= 30: score += 5
    
    if cards_count > 0:
        dead_ratio = dead_cards / cards_count
        score -= int(dead_ratio * 25)

    heat_ratio = total_heat / cooling_capacity if cooling_capacity > 0 else 2.0
    if heat_ratio <= 0.8: score += 25
    elif heat_ratio <= 1.0: score += 15
    else: score -= 20 
    
    if tax_rate == 0: score += 25
    elif tax_rate <= 0.1: score += 15
    elif tax_rate <= 0.2: score += 10
    
    if 0 < roi_days <= 10: score += 20
    elif roi_days <= 20: score += 15
    elif roi_days <= 40: score += 10
    elif roi_days <= 60: score += 5
    
    score = max(0, min(100, score)) 

    if score >= 95: grade, title, color = "S+", "💎 Цифровой Гений", "🟢"
    elif score >= 85: grade, title, color = "S", "🔥 Топовый Архитектор", "🟢"
    elif score >= 70: grade, title, color = "A", "📈 Опытный Делец", "🟡"
    elif score >= 50: grade, title, color = "B", "⚙️ Крепкий Среднячок", "🟡"
    elif score >= 30: grade, title, color = "C", "⚠️ Рискованный Игрок", "🟠"
    else: grade, title, color = "F", "💀 Кандидат на Банкротство", "🔴"

    advice = []
    if heat_ratio > 1.0: advice.append("🚨 <b>КРИТИЧЕСКАЯ УГРОЗА:</b> Тепловыделение превышает норму. Шанс пожара!")
    elif heat_ratio > 0.9: advice.append("⚠️ <b>Опасность:</b> Охлаждение работает на пределе.")
        
    if dead_cards > 0: advice.append(f"🛠 <b>Мертвый груз:</b> {dead_cards} карт сгорели. Долг по ремонту: {fmt(repair_debt)} ᴜ.")
    if 0 < avg_health < 40: advice.append("📉 <b>Износ критичен:</b> Скоро начнутся массовые поломки.")
    if tax_rate >= 0.4 and not is_magnate: advice.append("🏛 <b>Налоговое удушье:</b> Рекомендуется купить лицензию Магната.")
        
    if roi_days == float('inf') or roi_days < 0: advice.append("💸 <b>УБЫТОК:</b> Ферма работает в минус! Расходы превышают доход.")
    elif roi_days > 50: advice.append("⏳ <b>Долгая окупаемость:</b> Капитал заморожен. Нужны новые чипы.")

    if not advice:
        if score >= 90: advice.append("👑 <b>Идеальная система.</b> Коннор восхищен вашей эффективностью.")
        else: advice.append("✅ <b>Стабильная работа.</b> Уязвимостей не выявлено.")

    advice_text = "\n".join(advice)

    audit_text = (
        f"🔎 <b>Глобальная оценка фермы</b>\nПользователь: <b>{target_name}</b>\n════════════════════\n"
        f"📊 <b>ОБЩИЙ РЕЙТИНГ ИНФРАСТРУКТУРЫ</b>\nИндекс надежности: <b>{score}/100</b>\n"
        f"Оценка: {color} <b>[ {grade} ] — {title}</b>\n════════════════════\n"
        f"💵 <b>ФИНАНСОВЫЙ БЛОК</b>\n├ Капитализация: <b>{fmt(total_investment)} ᴜ</b>\n"
        f"├ Чистая прибыль: <b>{fmt(daily_net)} ᴜ/сутки</b>\n├ Налог Сети: <b>{int(tax_rate*100)}%</b>\n"
        f"└ Окупаемость (ROI): <b>{roi_days if roi_days != float('inf') else '—'} дней</b>\n\n"
        f"⚙️ <b>ТЕХНИЧЕСКИЙ БЛОК</b>\n├ Всего оборудования: <b>{cards_count} шт.</b>\n"
        f"├ Активных / Сгоревших: <b>{alive_cards} / {dead_cards}</b>\n"
        f"├ Средний запас прочности: <b>{avg_health:.1f}%</b>\n"
        f"└ Нагрузка охлаждения: <b>{fmt(total_heat)} / {fmt(cooling_capacity)}</b>\n"
        f"════════════════════\n🧠 <b>Вердикт и стратегия</b>\n{advice_text}"
    )

    await message.reply(audit_text, parse_mode="HTML")

# ==========================================
# 🔧 РЕМОНТ И ПОЛОМКА
# ==========================================
@router.message(F.text.lower().startswith("чинить") & (F.fromuser.id == ADMIN_ID))
async def admin_repair_gpu(message: types.Message):
    target_id = await get_target_id(message)
    if not target_id: return await message.reply("⚠️ Укажите ID.")

    text_raw = message.text.lower().strip()
    pool = await get_db()
    async with pool.acquire() as db:
        if text_raw == "чинить" or (len(text_raw.split()) == 2 and text_raw.split()[1].isdigit()):
            await db.execute("UPDATE gpu_batches SET condition = 100.0, was_repaired = 0 WHERE user_id = $1", target_id)
            stats = await db.fetch("SELECT gpu_id, SUM(qty) as total FROM gpu_batches WHERE user_id = $1 AND condition > 0 GROUP BY gpu_id", target_id)
            reset_updates = {f'gpu_{i}': 0 for i in GPUS}
            await update_farm(target_id, **reset_updates)
            for s in stats: await update_farm(target_id, **{s['gpu_id']: s['total']})
            return await message.reply("🔧 Всё восстановлено!")

        search_term, repair_qty = parse_gpu_command(message.text, "чинить ")
        gpu_num, target_gpu = find_gpu_by_text(search_term)
        if not target_gpu: return await message.reply("❌ Не найдено.")
        gpu_id_str = f"gpu_{gpu_num}"

        async with db.transaction():
            broken_batches = await db.fetch("SELECT id, qty, multiplier, was_repaired FROM gpu_batches WHERE user_id = $1 AND gpu_id = $2 AND condition <= 0", target_id, gpu_id_str)
            total_broken = sum(b['qty'] for b in broken_batches)
            if total_broken == 0: return await message.reply("У игрока нет сломанных карт.")

            to_fix = min(repair_qty, total_broken)
            fixed_count = 0
            
            for batch in broken_batches:
                if to_fix <= 0: break
                b_id, b_qty, b_mult = batch['id'], batch['qty'], batch['multiplier']
                
                if b_qty <= to_fix:
                    await db.execute("UPDATE gpu_batches SET condition = 100.0, was_repaired = 0 WHERE id = $1", b_id)
                    to_fix -= b_qty
                    fixed_count += b_qty
                else:
                    await db.execute("UPDATE gpu_batches SET qty = qty - $1 WHERE id = $2", to_fix, b_id)
                    await db.execute("""
                        INSERT INTO gpu_batches (user_id, gpu_id, multiplier, qty, condition, was_repaired) 
                        VALUES ($1, $2, $3, $4, 100.0, 0)
                    """, target_id, gpu_id_str, b_mult, to_fix)
                    fixed_count += to_fix
                    to_fix = 0

        farm_data = await get_farm(target_id)
        await update_farm(target_id, **{gpu_id_str: farm_data.get(gpu_id_str, 0) + fixed_count})
        await message.reply(f"🔧 Исправлено: <b>{fixed_count} шт.</b>")

@router.message(F.text.lower().startswith("сломать ") & (F.from_user.id == ADMIN_ID))
async def admin_break_card(message: types.Message):
    search_term, break_qty = parse_gpu_command(message.text, "сломать ")
    gpu_num, target_gpu = find_gpu_by_text(search_term)
    if not target_gpu: return await message.reply("❌ Не найдено.")
    
    gpu_id_str = f"gpu_{gpu_num}"
    target_id = message.reply_to_message.from_user.id if message.reply_to_message else message.from_user.id
    farm_data = await get_farm(target_id)
    current_active = farm_data.get(gpu_id_str, 0)
    if current_active < break_qty: return await message.reply("Столько нет.")

    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            batches = await db.fetch("SELECT id, qty, multiplier, was_repaired FROM gpu_batches WHERE user_id = $1 AND gpu_id = $2 AND condition > 0", target_id, gpu_id_str)
            left_to_break = break_qty
            for batch in batches:
                if left_to_break <= 0: break
                if batch['qty'] <= left_to_break:
                    await db.execute("UPDATE gpu_batches SET condition = 0.0 WHERE id = $1", batch['id'])
                    left_to_break -= batch['qty']
                else:
                    await db.execute("UPDATE gpu_batches SET qty = qty - $1 WHERE id = $2", left_to_break, batch['id'])
                    await db.execute("INSERT INTO gpu_batches (user_id, gpu_id, multiplier, qty, condition, was_repaired) VALUES ($1, $2, $3, $4, 0.0, $5)", target_id, gpu_id_str, batch['multiplier'], left_to_break, batch['was_repaired'])
                    left_to_break = 0

    await update_farm(target_id, **{gpu_id_str: current_active - break_qty})
    await message.reply(f"💥 Сломано: {break_qty} шт.")

@router.message((F.text.lower().startswith("ферма время")) & (F.from_user.id == ADMIN_ID))
async def admin_time_machine(message: types.Message):
    parts = message.text.split()
    if len(parts) < 3: return
    hours = int(parts[2])
    target_user = message.reply_to_message.from_user.id if message.reply_to_message else message.from_user.id
    farm_data = await get_farm(target_user)
    shift = hours * 3600
    new_collect = farm_data.get('last_collect', int(time.time())) - shift
    new_wear = farm_data.get('last_wear_update', int(time.time())) - shift
    await update_farm(target_user, last_collect=new_collect, last_wear_update=new_wear)
    await message.reply(f"⏳ Время сдвинуто на {hours} ч.")