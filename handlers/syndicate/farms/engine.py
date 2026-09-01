# File: handlers/syndicate/farms/engine.py
import time
import random
import json
import logging
import os
from core.database import get_db, get_balance, get_user_data, get_clan, update_farm, add_balance, change_rating, get_farm
from handlers.users.statuses import get_active_statuses, has_active_status
from handlers.events.events_engine import GLOBAL_MODIFIERS
from .config import GPUS, COOLING, MAX_STORAGE_HOURS, ELECTRICITY_PRICE, get_tax_rate

# 🔥 ЯВНЫЙ МАКРОС ФОРМАТИРОВАНИЯ
fmt = lambda x: f"{int(x):,}".replace(',', ' ')

def is_standard_gpu(gpu_id: str) -> bool:
    """Проверяет, является ли предмет стандартной видеокартой"""
    return gpu_id.startswith('gpu_') and gpu_id.split('_')[-1].isdigit()

# ==========================================
# 🛡 МУЛЬТИЯЗЫЧНЫЙ ЛОКАЛИЗАТОР ДЛЯ ДВИЖКА (ПО ЮЗЕРУ)
# ==========================================
LOCALES = {}
for lang in ["ru", "en"]:
    path = f"locales/{lang}.json"
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                LOCALES[lang] = json.load(f)
        except Exception as e:
            logging.error(f"Ошибка загрузки локали {lang} в ядре фермы: {e}")

def get_translator(lang: str):
    target_lang = lang if lang in LOCALES else "ru"
    def translate(key: str, **kwargs) -> str:
        locales_dict = LOCALES.get(target_lang, LOCALES["ru"].get(key, key))
        text = locales_dict.get(key, LOCALES["ru"].get(key, key))
        if kwargs:
            try: return text.format(**kwargs)
            except: pass
        return text
    return translate

async def resolve_user_translator(user_id: int):
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            lang = await db.fetchval("SELECT lang FROM users WHERE user_id = $1", user_id)
            if lang: return get_translator(lang)
    except: pass
    return get_translator("ru")


async def sync_farm_passive(user_id, farm_data, force_sync=False):
    current_time = int(time.time())
    
    last_update = farm_data.get('last_wear_update') or farm_data.get('last_collect') or current_time
    elapsed_seconds = current_time - last_update
    elapsed_h = float(elapsed_seconds) / 3600.0

    if elapsed_h < 0.01 and not force_sync: 
        return

    active_statuses = await get_active_statuses(user_id)
    is_tech = 1 in active_statuses
    current_max_hours = 8 if is_tech else MAX_STORAGE_HOURS
    
    time_since_collect = current_time - farm_data.get('last_collect', current_time)
    if time_since_collect >= (current_max_hours * 3600) and farm_data.get('last_wear_update', 0) >= farm_data.get('last_collect', 0) + (current_max_hours * 3600):
        await update_farm(user_id, last_wear_update=current_time)
        return

    inc_temp, prof_temp, full_temp, total_heat, cooling_capacity, power_temp, watts_temp = await calculate_farm_state(user_id, farm_data)
    overheat_factor = min(4.0, 1.0 + (float(total_heat - cooling_capacity) / cooling_capacity * 2.0)) if total_heat > cooling_capacity else 1.0

    is_sov = 777 in active_statuses or 5 in active_statuses

    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            db_batches = await db.fetch("SELECT id, gpu_id, qty, condition, multiplier, was_repaired = 0 FROM gpu_batches WHERE user_id = $1 ORDER BY id ASC", user_id)
            
            if not is_sov:
                for row in db_batches:
                    if is_standard_gpu(row['gpu_id']):
                        gpu_num = int(row['gpu_id'].split('_')[1])
                        if gpu_num > 100:
                            base_id = f'gpu_{gpu_num - 100}'
                            await db.execute("UPDATE gpu_batches SET gpu_id = $1 WHERE id = $2", base_id, row['id'])
                            count = row['qty']
                            await db.execute(f"UPDATE farms SET {base_id} = COALESCE({base_id}, 0) + $1, {row['gpu_id']} = 0 WHERE user_id = $2", count, user_id)
    
            db_batches = await db.fetch("SELECT id, gpu_id, qty, condition, multiplier, was_repaired FROM gpu_batches WHERE user_id = $1 ORDER BY id ASC", user_id)

            gpu_counts_in_db = {}
            for row in db_batches:
                gpu_counts_in_db[row['gpu_id']] = gpu_counts_in_db.get(row['gpu_id'], 0) + row['qty']

            for i in GPUS:
                gpu_id = f'gpu_{i}'
                count_in_farm = farm_data.get(gpu_id, 0)
                count_in_db = gpu_counts_in_db.get(gpu_id, 0)

                if count_in_db < count_in_farm:
                    await db.execute("INSERT INTO gpu_batches (user_id, gpu_id, multiplier, qty, condition, was_repaired) VALUES ($1, $2, 1.0, $3, 100.0, 0)", user_id, gpu_id, count_in_farm - count_in_db)
                elif count_in_db > count_in_farm:
                    diff = count_in_db - count_in_farm
                    for row in sorted([r for r in db_batches if r['gpu_id'] == gpu_id], key=lambda x: x['condition']):
                        if diff <= 0: break
                        if row['qty'] <= diff:
                            await db.execute("DELETE FROM gpu_batches WHERE id = $1", row['id'])
                            diff -= row['qty']
                        else:
                            await db.execute("UPDATE gpu_batches SET qty = qty - $1 WHERE id = $2", diff, row['id'])
                            diff = 0

            allowed_wear_seconds = min(elapsed_seconds, max(0, (current_max_hours * 3600) - (last_update - farm_data.get('last_collect', current_time))))
            allowed_wear_h = float(allowed_wear_seconds) / 3600.0

            if allowed_wear_h > 0:
                active_rows = await db.fetch("SELECT id, gpu_id, qty, condition, multiplier, was_repaired FROM gpu_batches WHERE user_id = $1 AND condition > 0 ORDER BY id ASC", user_id)
                
                standard_active = [r for r in active_rows if is_standard_gpu(r['gpu_id'])]
                sorted_active = sorted(standard_active, key=lambda x: GPUS.get(int(x['gpu_id'].split('_')[1]), {}).get('price', 0), reverse=True)
                
                max_slots = farm_data.get('max_slots', 30)
                slots_used = 0
                
                for row in sorted_active:
                    if slots_used >= max_slots:
                        break
                        
                    qty = row['qty']
                    usable_qty = min(qty, max_slots - slots_used)
                    slots_used += usable_qty
                    
                    gpu_num = int(row['gpu_id'].split('_')[1])
                    gpu_config = GPUS.get(gpu_num)
                    if not gpu_config: continue
                    
                    lifspan_h = float(gpu_config['price'] * 2.2) / float(gpu_config['income'])
                    total_wear = round((100.0 / lifspan_h) * allowed_wear_h * overheat_factor, 2)
                    
                    if total_wear > 0:
                        if usable_qty < qty:
                            idle_qty = qty - usable_qty
                            await db.execute("UPDATE gpu_batches SET qty = $1 WHERE id = $2", usable_qty, row['id'])
                            await db.execute("""
                                INSERT INTO gpu_batches (user_id, gpu_id, multiplier, qty, condition, was_repaired) 
                                VALUES ($1, $2, $3, $4, $5, $6)
                            """, user_id, row['gpu_id'], row['multiplier'], idle_qty, row['condition'], row['was_repaired'])
                        
                        await db.execute("""
                            UPDATE gpu_batches 
                            SET condition = CASE WHEN condition - $1 <= 0 THEN 0.0 ELSE condition - $1 END 
                            WHERE id = $2
                        """, total_wear, row['id'])

        await db.execute("UPDATE farms SET last_wear_update = $1 WHERE user_id = $2", current_time, user_id)


async def calculate_farm_state(user_id, farm_data): 
    total_income_ph, total_heat, total_power_ph, total_watts = 0, 0, 0, 0
    cooling_level = farm_data.get('cooling_level', 1)
    cooling_capacity = COOLING.get(cooling_level, COOLING[1])['capacity']
        
    pool = await get_db()
    async with pool.acquire() as db:
        batches = await db.fetch("SELECT gpu_id, qty, multiplier, condition FROM gpu_batches WHERE user_id = $1 AND condition > 0 ORDER BY id ASC", user_id)

    user_data = await get_user_data(user_id)
    clan_id = user_data.get('clan_id', 0)
    clan_income_mult, clan_heat_mult = 1.0, 1.0
    if clan_id > 0:
        clan = await get_clan(clan_id)
        if clan:
            clan_income_mult += (clan.get('tech_income', 0) * 0.02)
            clan_heat_mult -= (clan.get('tech_cooling', 0) * 0.05)

    standard_batches = [b for b in batches if is_standard_gpu(b['gpu_id'])]
    sorted_batches = sorted(standard_batches, key=lambda x: GPUS.get(int(x['gpu_id'].split('_')[1]), {}).get('price', 0), reverse=True)
    
    max_slots = farm_data.get('max_slots', 30)
    slots_used = 0

    for batch in sorted_batches:
        if slots_used >= max_slots:
            break
            
        qty = batch['qty']
        usable_qty = min(qty, max_slots - slots_used)
        slots_used += usable_qty

        gpu_num = int(batch['gpu_id'].split('_')[1])
        gpu_config = GPUS.get(gpu_num)
        if not gpu_config: 
            continue

        mult = batch['multiplier'] or 1.0
        
        for_mod = GLOBAL_MODIFIERS.get("income", 1.0)
        total_income_ph += int(usable_qty * gpu_config["income"] * mult * for_mod * clan_income_mult) 
        total_heat += int(usable_qty * gpu_config["heat"] * mult * clan_heat_mult) 
        total_watts += int(usable_qty * gpu_config.get("power", 0))
        
        elec_mod = GLOBAL_MODIFIERS.get("electricity", 1.0)
        total_power_ph += int(usable_qty * gpu_config.get("power", 0) * elec_mod * ELECTRICITY_PRICE)

    active_statuses = await get_active_statuses(user_id)
    is_tech = 1 in active_statuses
    
    if is_tech: 
        total_power_ph = int(total_power_ph * 0.50) 
    if 0 in active_statuses: 
        total_power_ph = int(total_power_ph * 0.85) 

    current_time = int(time.time())
    elapsed_seconds = current_time - farm_data.get('last_collect', current_time)
    current_max_hours = 8 if is_tech else MAX_STORAGE_HOURS
    
    is_full = False
    if total_income_ph > 0 and elapsed_seconds >= (current_max_hours * 3600):
        elapsed_seconds = current_max_hours * 3600
        is_full = True

    return total_income_ph, int((total_income_ph / 3600) * elapsed_seconds), is_full, total_heat, cooling_capacity, total_power_ph, total_watts


async def perform_collection(user_id, farm_data): 
    _ = await resolve_user_translator(user_id)
    
    await sync_farm_passive(user_id, farm_data) 
    farm_data = await get_farm(user_id)         

    income_ph, pending_crypto, is_full_temp, total_heat, cooling_capacity, power_ph, total_watts = await calculate_farm_state(user_id, farm_data)
    fire_message, overheat = None, total_heat - cooling_capacity
    is_tech = await has_active_status(user_id, 1)

    fire_chance = min(0.85, (overheat / cooling_capacity) * 0.35) if overheat > 0 else 0
    if is_tech: 
        fire_chance /= 2.0 

    pool = await get_db()
    if overheat > 0 and random.random() < fire_chance:
        owned_gpus = [i for i in GPUS if farm_data.get(f'gpu_{i}', 0) > 0]
        if owned_gpus:
            target_gpu = max(owned_gpus, key=lambda x: GPUS[x]['price'])
            gpu_id_str = f"gpu_{target_gpu}"
            
            async with pool.acquire() as db:
                async with db.transaction():
                    target_batch = await db.fetchrow("SELECT id, qty FROM gpu_batches WHERE user_id = $1 AND gpu_id = $2 AND condition > 0 ORDER BY condition DESC LIMIT 1", user_id, gpu_id_str)
                    if target_batch:
                        if target_batch['qty'] > 1:
                            await db.execute("UPDATE gpu_batches SET qty = qty - 1 WHERE id = $1", target_batch['id'])
                        else:
                            await db.execute("DELETE FROM gpu_batches WHERE id = $1", target_batch['id'])
                        await db.execute(f"UPDATE farms SET {gpu_id_str} = GREATEST(0, {gpu_id_str} - 1) WHERE user_id = $1", user_id)
            
            await change_rating(user_id, -30)
            return 0, _("farm_fire_msg", name=GPUS[target_gpu]['name']), None, 0, 0, "0 ᴜ", "", 0 

    if pending_crypto <= 0: 
        return 0, None, None, 0, 0, "0 ᴜ", "", 0

    current_time = int(time.time())
    work_seconds = min(current_time - farm_data.get('last_collect', current_time), (8 if is_tech else MAX_STORAGE_HOURS) * 3600)
    electricity_bill_fiat = int(power_ph * (work_seconds / 3600.0))
    tax_rate = get_tax_rate(income_ph) 
    
    clan_id = (await get_user_data(user_id)).get('clan_id', 0)
    if clan_id > 0 and tax_rate > 0:
        clan = await get_clan(clan_id)
        if clan: 
            tax_rate = max(0.0, tax_rate - (clan.get('tech_tax', 0) * 0.01))
    
    active_statuses = await get_active_statuses(user_id)
    if 0 in active_statuses: tax_rate = max(0.0, tax_rate - 0.02)
    if 2 in active_statuses: tax_rate = min(tax_rate, 0.15)
        
    tax_mod = GLOBAL_MODIFIERS.get("tax", 1.0)
    tax_amount = int(pending_crypto * tax_rate * tax_mod)
    crypto_after_tax = max(0, pending_crypto - tax_amount)

    # 💱 МЕХАНИКА ТАРИФА «МАЙНИНГ-ПУЛ»: Расчет ЭЭ прямо в крипте UMC
    course = 0.31  
    try:
        from handlers.economy.crypto import get_market_state
        course, *unused_crypto_state = await get_market_state()
    except Exception as e:
        logging.error(f"Ошибка получения рыночного курса для ЭЭ: {e}")
        
    umc_for_electricity = int(electricity_bill_fiat / course) if course > 0 else 0
    emergency_msg = ""
    elec_str = ""

    # 💱 МЕХАНИКА ТАРИФА «МАЙНИНГ-ПУЛ»: Расчет ЭЭ прямо в крипте UMC
    if crypto_after_tax >= umc_for_electricity:
        net_crypto_profit = crypto_after_tax - umc_for_electricity
        elec_str = f"0 (~{fmt(umc_for_electricity)} UMC)"
        if umc_for_electricity > 0:
            emergency_msg = f"🔌 <b>Тариф «Пул»:</b> За обслуживание ригов списано <code>{fmt(umc_for_electricity)} UMC</code> по курсу биржи ({course} ᴜ)."
    else:
        # Если крипты не хватило, остаток списывается с фиатного счета!
        umc_burned = crypto_after_tax
        net_crypto_profit = 0
        fiat_deducted = electricity_bill_fiat - int(umc_burned * course)
        if fiat_deducted < 0: fiat_deducted = 0
        
        elec_str = f"{fmt(fiat_deducted)} (-{fmt(umc_burned)} UMC)"
        emergency_msg = f"⚠️ <b>Кризис мощностей:</b> Вся добыча (<code>{fmt(umc_burned)} UMC</code>) ушла на розетку. Остаток долга списан с фиатного счета!"
        
        if fiat_deducted > 0:
            await add_balance(user_id, -fiat_deducted)

    raid_chance = min(0.35, (total_watts / 15000.0) * 0.05) if total_watts > 0 else 0
    if net_crypto_profit > 0 and random.random() < raid_chance:
        await update_farm(user_id, last_collect=current_time)
        return net_crypto_profit, "POLICE_RAID", None, tax_amount, tax_rate, "0 ᴜ", "", pending_crypto

    old_umc = float(farm_data.get('umc_balance', 0.0))
    await update_farm(user_id, umc_balance=old_umc + net_crypto_profit, last_collect=current_time)
    
    if net_crypto_profit > 0: 
        await change_rating(user_id, 2)
    
    broken_msg = ""
    async with pool.acquire() as db:
        for r in await db.fetch("SELECT gpu_id, SUM(qty) as q FROM gpu_batches WHERE user_id = $1 AND condition <= 0 AND was_repaired = 0 AND gpu_id LIKE 'gpu_%' GROUP BY gpu_id", user_id):
            if r['q'] and r['q'] > 0:
                if not is_standard_gpu(r['gpu_id']): continue
                gpu_num = int(r['gpu_id'].split('_')[1])
                if gpu_num < 100:
                    broken_msg += _("farm_broken_row", qty=r['q'], name=GPUS[gpu_num]['name'])

    # Теперь elec_str отдается в текстовом, сформированном виде!
    return net_crypto_profit, fire_message, broken_msg if broken_msg else None, tax_amount, tax_rate, elec_str, emergency_msg, pending_crypto