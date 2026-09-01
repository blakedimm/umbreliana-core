import time
import random
import os
import json
from aiogram import Router, F, types, Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder
from core.database import get_db, get_balance, add_balance, update_farm, change_rating

router = Router()

fmt = lambda x: f"{int(x):,}".replace(',', ' ')

# ==========================================
# 📊 ХАРАКТЕРИСТИКИ КВАНТОВЫХ АРТЕФАКТОВ
# ==========================================
ARTIFACT_STATS = {
    "phantom": {"name_key": "lb_art_name_phantom", "daily_income": 12_000_000}, 
    "cursed":  {"name_key": "lb_art_name_cursed",  "daily_income": 25_000_000}, 
    "glitch":  {"name_key": "lb_art_name_glitch",  "daily_income": 16_000_000}, 
    "night":   {"name_key": "lb_art_name_night",   "daily_income": 8_000_000},  
    "abyss":   {"name_key": "lb_art_name_abyss",   "daily_income": 80_000_000}, 
    "nexus":   {"name_key": "lb_art_name_nexus",   "daily_income": 0}, 
    "chrono":  {"name_key": "lb_art_name_chrono",  "daily_income": 4_000_000}   
}

# Резервные дефолты
FALLBACK_STRINGS = {
    "lb_art_name_phantom": "👻 Phantom Core v1", "lb_art_name_cursed": "🩸 Нейро-Майнер",
    "lb_art_name_glitch": "👾 RTX 'Glitch'", "lb_art_name_night": "🦇 Night Hunter",
    "lb_art_name_abyss": "🌌 Осколок Бездны", "lb_art_name_nexus": "💠 Ядро Нексуса", "lb_art_name_chrono": "⏳ Хроно-Сфера",
    "lb_empty_err": "🧪 <b>В твоей Квантовой Лаборатории пусто.</b>\nЗагляни на <code>теневой рынок</code> за артефактами.",
    "lb_title": "🧪 <b>КВАНТОВАЯ ЛАБОРАТОРИЯ СИНДИКАТА</b>\n━━━━━━━━━━━━━━━━━━━━\n",
    "lb_btn_collect": "📥 Извлечь фиатную энергию", "lb_btn_wait": "⏳ Ядро нестабильно...",
    "lb_alert_not_ready": "Матрица еще не накопила критический заряд!"
}

def get_str(key: str, translator=None, **kwargs) -> str:
    # Если передан мультиязычный транслятор _, берем строку из JSON
    if translator and callable(translator):
        return translator(key, **kwargs)
    
    # Если транслятора нет, берем из локального дефолта
    text = FALLBACK_STRINGS.get(key, key)
    if kwargs:
        try: return text.format(**kwargs)
        except: pass
    return text

# Внешняя l10n сборка для распределенной структуры транзакций
LOCALES = {}
for l in ["ru", "en"]:
    p = f"locales/{l}.json"
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f: LOCALES[l] = json.load(f)

def get_translator(lang: str):
    t_lang = lang if lang in LOCALES else "ru"
    def translate(key: str, **kwargs) -> str:
        text = LOCALES[t_lang].get(key, FALLBACK_STRINGS.get(key, key))
        if kwargs:
            try: return text.format(**kwargs)
            except: pass
        return text
    return translate

async def resolve_chat_translator(chat_id: int, default__ = None):
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            chat_lang = await db.fetchval("SELECT lang FROM chats WHERE chat_id = $1", chat_id)
            if chat_lang: return get_translator(chat_lang)
    except: pass
    return default__ if default__ else get_translator("ru")


async def calculate_gold_farm(user_id: int, current_time: int):
    pool = await get_db()
    async with pool.acquire() as db:
        last_collect = await db.fetchval("SELECT gold_last_collect FROM users WHERE user_id = $1", user_id) or 0
        rows = await db.fetch(
            "SELECT special_type, SUM(qty) as total_qty, AVG(condition) as avg_cond "
            "FROM gpu_batches WHERE gpu_id LIKE 'gold_%' AND user_id = $1 GROUP BY special_type",
            user_id
        )
        
    if not rows: return None 

    artifacts = {row['special_type']: {'qty': row['total_qty'], 'cond': row['avg_cond']} for row in rows}
    
    if last_collect == 0:
        async with pool.acquire() as db:
            await db.execute("UPDATE users SET gold_last_collect = $1 WHERE user_id = $2", current_time, user_id)
        last_collect = current_time

    chrono_qty = artifacts.get('chrono', {}).get('qty', 0)
    cycle_time = max(43200, 86400 - (chrono_qty * 10800))

    seconds_passed = current_time - last_collect
    full_cycles_passed = int(seconds_passed // cycle_time)
    has_abyss = artifacts.get('abyss', {}).get('qty', 0) > 0
    
    if has_abyss:
        if full_cycles_passed > 7: full_cycles_passed = 7
    else:
        if full_cycles_passed > 1: full_cycles_passed = 1

    hour_now = time.localtime(current_time).tm_hour
    is_night = 0 <= hour_now < 6

    base_daily = 0
    for a_type, data in artifacts.items():
        if a_type not in ARTIFACT_STATS: continue
        qty = data['qty']
        rate = ARTIFACT_STATS[a_type]["daily_income"]
        if a_type == "night" and is_night: rate *= 3
        base_daily += rate * qty

    nexus_qty = artifacts.get('nexus', {}).get('qty', 0)
    nexus_multiplier = 1.0 + (0.07 * nexus_qty)
    
    daily_total = int(base_daily * nexus_multiplier)
    total_income = daily_total * full_cycles_passed
    time_to_next = cycle_time - (seconds_passed % cycle_time)

    return artifacts, total_income, full_cycles_passed, is_night, time_to_next, daily_total, cycle_time, seconds_passed

# ==========================================
# 🌌 ИНТЕРФЕЙС ЛАБОРАТОРИИ
# ==========================================
@router.message(F.text.lower().in_(["лаборатория", "лаба", "квантовая лаба", "артефакты", "laboratory", "lab", "quantum lab", "artifacts"]))
async def show_gold_farm(message: types.Message, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    user_id = message.from_user.id
    current_time = int(time.time())
    
    data = await calculate_gold_farm(user_id, current_time)
    if not data: return await message.reply(get_str("lb_empty_err", translator=_), parse_mode="HTML")
        
    # 🔥 ИСПРАВЛЕНИЕ: Заменили затирающую пустую переменную "_" на "seconds_passed"
    artifacts, total_income, full_cycles_passed, is_night, time_to_next, daily_total, cycle_time, seconds_passed = data
    has_abyss = artifacts.get('abyss', {}).get('qty', 0) > 0
    
    text = get_str("lb_title", translator=_)
    
    for a_type, a_data in artifacts.items():
        if a_type in ARTIFACT_STATS:
            qty = a_data['qty']
            cond = a_data['cond']
            cond_icon = "🟢" if cond > 70 else "🟡" if cond > 30 else "🔴"
            localized_art_name = get_str(ARTIFACT_STATS[a_type]['name_key'], translator=_)
            text += get_str("lb_row", translator=_, name=localized_art_name, qty=qty, cond_icon=cond_icon, cond=f"{cond:.1f}")
            
    text += "━━━━━━━━━━━━━━━━━━━━\n"
    if is_night and artifacts.get('night', {}).get('qty', 0) > 0: text += get_str("lb_phase_night", translator=_)
    if artifacts.get('nexus', {}).get('qty', 0) > 0: text += get_str("lb_phase_nexus", translator=_, percent=artifacts['nexus']['qty'] * 7)
    if artifacts.get('chrono', {}).get('qty', 0) > 0: text += get_str("lb_phase_chrono", translator=_, hours=int(cycle_time//3600))
        
    text += get_str("lb_potential", translator=_, total=fmt(daily_total))
    
    if full_cycles_passed > 0:
        days_text = get_str("lb_accumulated_cycles", translator=_, cycles=full_cycles_passed) if has_abyss and full_cycles_passed > 1 else ""
        text += get_str("lb_status_ready", translator=_, income=fmt(total_income), days_text=days_text)
    else:
        percent = int(((cycle_time - time_to_next) / cycle_time) * 100)
        progress_bar = "█" * (percent // 10) + "░" * (10 - (percent // 10))
        text += get_str("lb_status_charging", translator=_, hours=int(time_to_next // 3600), minutes=int((time_to_next % 3600) // 60), bar=progress_bar, percent=percent)

    kb = InlineKeyboardBuilder()
    if full_cycles_passed > 0: kb.button(text=get_str("lb_btn_collect", translator=_), callback_data="collect_gold_farm")
    else: kb.button(text=get_str("lb_btn_wait", translator=_), callback_data="gold_farm_wait")
        
    await message.reply(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "gold_farm_wait")
async def wait_gold_farm_btn(call: types.CallbackQuery, _=None):
    if not _: _ = await resolve_chat_translator(call.message.chat.id, _)
    await call.answer(get_str("lb_alert_not_ready", translator=_), show_alert=True)

# ==========================================
# 📥 ИЗВЛЕЧЕНИЕ ПРИБЫЛИ
# ==========================================
@router.message(F.text.lower().in_(["сбор лабы", "собрать лабу", "извлечь", "collect lab", "gather lab", "extract"]))
async def collect_gold_farm_cmd(message: types.Message, _=None):
    _ = await resolve_chat_translator(message.chat.id, _)
    await process_gold_collection(message.from_user.id, message, _=_)

@router.callback_query(F.data == "collect_gold_farm")
async def collect_gold_farm_btn(call: types.CallbackQuery, _=None):
    _ = await resolve_chat_translator(call.message.chat.id, _)
    await process_gold_collection(call.from_user.id, call.message, call=call, _=_)

async def process_gold_collection(user_id: int, message: types.Message, call=None, _=None):
    current_time = int(time.time())
    data = await calculate_gold_farm(user_id, current_time)
    
    if not data:
        text = get_str("lb_err_nothing_to_collect", translator=_)
        return await call.answer(text, show_alert=True) if call else await message.reply(text)
        
    # 🔥 ИСПРАВЛЕНИЕ: Избавились от перезаписи "_"
    artifacts, total_income, full_cycles_passed, is_night_unused, time_to_next_unused, daily_total_unused, cycle_time, seconds_passed = data
    if full_cycles_passed == 0:
        text = get_str("lb_err_cycle_not_finished", translator=_)
        return await call.answer(text, show_alert=True) if call else await message.reply(text)

    # ИНКВИЗИЦИЯ СИНДИКАТА (Шанс 1.5%)
    if random.random() < 0.015:
        if call: 
            try: await call.message.delete()
            except: pass
        
        kb = InlineKeyboardBuilder()
        kb.button(text=get_str("lb_inq_btn_bribe", translator=_), callback_data=f"inq_bribe_{user_id}")
        kb.button(text=get_str("lb_inq_btn_risk", translator=_), callback_data=f"inq_risk_{user_id}")
        kb.adjust(1)
        return await message.bot.send_message(chat_id=user_id, text=get_str("lb_inq_title", translator=_), reply_markup=kb.as_markup(), parse_mode="HTML")

    extra_msgs = ""

    # КВАНТОВЫЙ РЕЗОНАНС (Шанс 3% - Сгорает 30% фиата)
    if random.random() < 0.03:
        fiat_bal = await get_balance(user_id)
        if fiat_bal > 0:
            burn_fiat = int(fiat_bal * 0.3)
            await add_balance(user_id, -burn_fiat)
            extra_msgs += get_str("lb_resonance_msg", translator=_, amount=fmt(burn_fiat))

    # Идеальный тайминг и Глитч-видеокарты
    time_since_ready = seconds_passed - (full_cycles_passed * cycle_time)
    if 0 <= time_since_ready <= 3600 and full_cycles_passed == 1:
        timing_bonus = int(total_income * 0.15)
        total_income += timing_bonus
        extra_msgs += get_str("lb_timing_bonus_msg", translator=_, amount=fmt(timing_bonus))

    glitch_qty = artifacts.get('glitch', {}).get('qty', 0)
    if glitch_qty > 0 and random.random() < 0.05:
        total_income *= 3
        extra_msgs += get_str("lb_glitch_mult_msg", translator=_)
        if random.random() < 0.20:
            pool = await get_db()
            async with pool.acquire() as db:
                await db.execute("UPDATE gpu_batches SET qty = qty - 1 WHERE id = (SELECT id FROM gpu_batches WHERE user_id = $1 AND special_type = 'glitch' LIMIT 1)", user_id)
                await db.execute("DELETE FROM gpu_batches WHERE qty <= 0")
            extra_msgs += get_str("lb_glitch_burn_msg", translator=_)

    seconds_to_add = full_cycles_passed * cycle_time
    degrade_amount = 10.0 * full_cycles_passed
    
    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            await add_balance(user_id, total_income)
            await db.execute("UPDATE users SET gold_last_collect = gold_last_collect + $1 WHERE user_id = $2", seconds_to_add, user_id)
            await db.execute("UPDATE gpu_batches SET condition = CASE WHEN condition - $1 <= 0 THEN 0.0 ELSE condition - $1 END WHERE user_id = $2 AND gpu_id LIKE 'gold_%'", degrade_amount, user_id)
            
            destroyed = await db.fetch("DELETE FROM gpu_batches WHERE user_id = $1 AND gpu_id LIKE 'gold_%' AND condition <= 0 RETURNING special_type, qty", user_id)
            if destroyed:
                for d in destroyed:
                    a_name = get_str(ARTIFACT_STATS.get(d['special_type'], {}).get('name_key', ''), translator=_)
                    extra_msgs += get_str("lb_critical_wear_msg", translator=_, name=a_name, qty=d['qty'])

    final_text = get_str("lb_collect_success", translator=_, income=fmt(total_income), degrade=degrade_amount, extra=extra_msgs, hours=int(cycle_time//3600))
    
    if call:
        await call.message.edit_text(final_text, parse_mode="HTML")
        await call.answer(get_str("lb_collect_success_alert", translator=_))
    else:
        await message.reply(final_text, parse_mode="HTML")

# ==========================================
# 🚨 ВЫБОР ИСХОДА ОБЛАВЫ ИНКВИЗИЦИИ
# ==========================================
@router.callback_query(F.data.startswith("inq_"))
async def process_inquisition_choice(call: types.CallbackQuery, _=None):
    if not _: _ = await resolve_chat_translator(call.message.chat.id, _)
    parts = call.data.split("_")
    action, target_id = parts[1], int(parts[2])
    if call.from_user.id != target_id: return await call.answer(get_str("lb_inq_alert_foreign", translator=_), show_alert=True)
    
    pool = await get_db()
    current_time = int(time.time())
    
    if action == "bribe":
        async with pool.acquire() as db:
            async with db.transaction():
                target_art = await db.fetchrow("SELECT id, special_type, qty FROM gpu_batches WHERE user_id = $1 AND gpu_id LIKE 'gold_%' LIMIT 1", target_id)
                if target_art:
                    if target_art['qty'] > 1: await db.execute("UPDATE gpu_batches SET qty = qty - 1 WHERE id = $1", target_art['id'])
                    else: await db.execute("DELETE FROM gpu_batches WHERE id = $1", target_art['id'])
                    art_name = get_str(ARTIFACT_STATS.get(target_art['special_type'], {}).get('name_key', ''), translator=_)
                    
                    data = await calculate_gold_farm(target_id, current_time)
                    if data:
                        # 🔥 ИСПРАВЛЕНИЕ: Никаких "_" в распаковке
                        artifacts_u, income_u, cycle_time_u, is_night_u, time_to_next_u, daily_total_u, cycle_time_u, seconds_passed_u = data
                        await add_balance(target_id, int(income_u * 0.3)) 
                        await db.execute("UPDATE users SET gold_last_collect = $1 WHERE user_id = $2", current_time, target_id)
                        msg = get_str("lb_inq_bribe_success", translator=_, name=art_name)
                    else: msg = get_str("lb_inq_bribe_empty", translator=_)
                else:
                    return await call.answer(get_str("lb_inq_bribe_no_artifacts", translator=_), show_alert=True)
        await call.message.edit_text(msg, parse_mode="HTML")

    elif action == "risk":
        if random.random() < 0.50:
            data = await calculate_gold_farm(target_id, current_time)
            if data:
                artifacts_u, income_u, cycle_time_u, is_night_u, time_to_next_u, daily_total_u, cycle_time_u, seconds_passed_u = data
                await add_balance(target_id, income_u)
                async with pool.acquire() as db:
                    await db.execute("UPDATE users SET gold_last_collect = $1 WHERE user_id = $2", current_time, target_id)
                msg = get_str("lb_inq_risk_success", translator=_, income=fmt(income_u))
            else: msg = get_str("lb_inq_risk_empty", translator=_)
        else:
            ban_expiration = current_time + 43200 
            async with pool.acquire() as db:
                async with db.transaction():
                    await db.execute("DELETE FROM gpu_batches WHERE user_id = $1 AND gpu_id LIKE 'gold_%'", target_id)
                    await db.execute("UPDATE users SET ban_until = $1, gold_last_collect = $2 WHERE user_id = $3", ban_expiration, current_time, target_id)
            await change_rating(target_id, -100)
            msg = get_str("lb_inq_risk_fail", translator=_)
        await call.message.edit_text(msg, parse_mode="HTML")
    await call.answer()