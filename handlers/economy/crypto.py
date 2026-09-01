# File: handlers/economy/crypto.py
import os
import asyncio
import random
import logging
import time
import json
import math
import datetime
from aiogram import Router, F, types
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder
from core.database import get_db, get_balance, add_balance, get_farm, update_farm
from core.redis_driver import get_redis  
from handlers.events.events_engine import GLOBAL_MODIFIERS
from core.triggers import register_triggers

register_triggers(
    "крипта", "курс", "биржа", "курс крипты", "купить крипту", "продать крипту", "вывести",
    "crypto", "rate", "exchange", "market", "buy crypto", "sell crypto", "withdraw"
)

router = Router()

# ==========================================
# 📊 МАКРОЭКОНОМИЧЕСКИЕ КОНСТАНТЫ
# ==========================================
MIN_COURSE = 0.25   
MAX_COURSE = 4.50   
EQUILIBRIUM_COURSE = 1.50  
BASE_ANALYSIS_COST = 3_000_000  
GROUP_ID = -1003909438997  

# 🌐 ЗАГРУЗКА ЛОКАЛЕЙ
CRYPTO_LOCALES = {}
for l in ["ru", "en"]:
    p = f"locales/{l}.json"
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                CRYPTO_LOCALES[l] = json.load(f)
        except Exception as e:
            logging.error(f"Ошибка загрузки локали {l} в крипте: {e}")

def get_str(key: str, translator=None, **kwargs) -> str:
    if translator and callable(translator):
        return translator(key, **kwargs)
    text = CRYPTO_LOCALES.get("ru", {}).get(key, key)
    if kwargs:
        try: return text.format(**kwargs)
        except: pass
    return text

def fmt(num):
    return f"{int(num):,}".replace(",", " ")

def get_dynamic_analysis_cost(current_course: float) -> int:
    return int(BASE_ANALYSIS_COST * (current_course ** 0.7) + 1_500_000)

async def get_market_state():
    redis = await get_redis()
    if not redis: return 1.50, 0, "flat_up"
    
    try:
        raw_course = await redis.get("crypto:course")
        raw_tick = await redis.get("crypto:tick")
        raw_move = await redis.get("crypto:next_move")
        
        course_str = raw_course.decode('utf-8') if isinstance(raw_course, bytes) else raw_course
        tick_str = raw_tick.decode('utf-8') if isinstance(raw_tick, bytes) else raw_tick
        move_str = raw_move.decode('utf-8') if isinstance(raw_move, bytes) else raw_move
        
        course = float(course_str) if course_str else 1.50
        tick = int(tick_str) if tick_str else 0
        next_move = move_str if move_str else "flat_up"
        
        return course, tick, next_move
    except Exception as e:
        logging.warning(f"⚠️ Ошибка чтения рыночных данных из Redis: {e}")
        return 1.50, 0, "flat_up"

# ==========================================
# 📈 СМАРТ-ДВИЖОК РЫНКА (ADAPTIVE HYBRID ENGINE)
# ==========================================
async def update_crypto_market(bot):
    redis = await get_redis()
    if not redis: return

    try:
        lock_acquired = await redis.set("crypto:tick_lock", "lock", ex=60, nx=True)
        if not lock_acquired: return
    except Exception:
        return

    old_course, current_tick, _ = await get_market_state()
    current_tick += 1

    # 1. СЧИТЫВАЕМ ОБЪЕМЫ ТОРГОВ ИГРОКОВ
    today = datetime.date.today().isoformat()
    try:
        raw_buy_vol = await redis.get("crypto:buy_volume_u") or 0
        raw_sell_vol = await redis.get("crypto:sell_volume_umc") or 0
        raw_daily_vol = await redis.get(f"crypto:daily_vol_u_{today}") or 0
        
        buy_u = float(raw_buy_vol.decode('utf-8') if isinstance(raw_buy_vol, bytes) else raw_buy_vol)
        sell_umc = float(raw_sell_vol.decode('utf-8') if isinstance(raw_sell_vol, bytes) else raw_sell_vol)
        daily_volume = float(raw_daily_vol.decode('utf-8') if isinstance(raw_daily_vol, bytes) else raw_daily_vol)
        
        await redis.delete("crypto:buy_volume_u", "crypto:sell_volume_umc")
    except Exception:
        buy_u, sell_umc, daily_volume = 0.0, 0.0, 0.0

    sell_u = sell_umc * old_course

    # 2. РАССЧИТЫВАЕМ 3 КЛЮЧЕВЫХ СОСТАВЛЯЮЩИХ ИЗМЕНЕНИЯ КУРСА

    # A) ГРАВИТАЦИЯ К МЕДИАНЕ
    alpha = 0.12
    gravity = -alpha * ((old_course - EQUILIBRIUM_COURSE) / EQUILIBRIUM_COURSE)

    # B) НАСТРОЕНИЕ ИГРОКОВ (АДАПТИВНАЯ ЛИКВИДНОСТЬ)
    beta = 0.20
    norm_vol = max(5_000_000.0, daily_volume * 0.4)
    sentiment = math.tanh((buy_u - sell_u) / norm_vol) * beta

    # C) ИНЕРЦИОННАЯ ВОЛНА
    try:
        raw_wave = await redis.get("crypto:wave_phase") or "1"
        wave_phase = int(raw_wave.decode('utf-8') if isinstance(raw_wave, bytes) else raw_wave)
    except Exception:
        wave_phase = 1

    wave_map = {1: 0.03, 2: 0.10, 3: 0.00, 4: -0.10}  
    momentum = wave_map.get(wave_phase, 0.0)

    if random.random() < 0.35:  
        wave_phase = (wave_phase % 4) + 1
        await redis.set("crypto:wave_phase", str(wave_phase))

    # D) ШУМ И ИВЕНТЫ
    noise = random.uniform(-0.04, 0.04)
    chaos_mod = GLOBAL_MODIFIERS.get("crypto_multiplier", 1.0)

    # 3. ИТОГОВЫЙ ПЕРЕСЧЕТ
    total_delta = gravity + sentiment + momentum + noise
    new_course = round(old_course * (1.0 + total_delta) * chaos_mod, 2)
    new_course = max(MIN_COURSE, min(MAX_COURSE, new_course))

    delta_pct = (new_course - old_course) / old_course
    if delta_pct >= 0.25: next_move = "super_pamp"
    elif delta_pct >= 0.06: next_move = "pamp"
    elif delta_pct >= 0.00: next_move = "flat_up"
    elif delta_pct >= -0.06: next_move = "flat_down"
    elif delta_pct >= -0.25: next_move = "dump"
    else: next_move = "crash"

    await redis.set("crypto:course", str(new_course))
    await redis.set("crypto:tick", str(current_tick))
    await redis.set("crypto:next_move", next_move)

    hardware_modifier = round(1.0 + (new_course - 1.0) * 0.4, 2)
    hardware_modifier = max(0.65, min(3.0, hardware_modifier))
    GLOBAL_MODIFIERS['shop'] = hardware_modifier

    # 4. ВЫВОД В КАНАЛ СИНДИКАТА
    lang_pool = {}
    try:
        with open("locales/ru.json", "r", encoding="utf-8") as f:
            lang_pool = json.load(f)
    except Exception: pass

    status_map = {
        "super_pamp": lang_pool.get("cr_status_super_pamp", "🚀 Исторический Памп!"),
        "pamp": lang_pool.get("cr_status_pamp", "📈 Бычий тренд!"),
        "flat_up": lang_pool.get("cr_status_flat_up", "🟢 Зеленая зона."),
        "flat_down": lang_pool.get("cr_status_flat_down", "🔴 Красная зона."),
        "dump": lang_pool.get("cr_status_dump", "📉 Дамп рынка!"),
        "crash": lang_pool.get("cr_status_crash", "💥 Тотальный крах!")
    }
    status_text = status_map.get(next_move, "Стабильность")
    trend = "🔺" if new_course >= old_course else "🔻"
    price_change_percent = int((hardware_modifier - 1.0) * 100)

    if price_change_percent > 0:
        price_trend_text = lang_pool.get("cr_price_markup", "").format(percent=price_change_percent)
    elif price_change_percent < 0:
        price_trend_text = lang_pool.get("cr_price_discount", "").format(percent=price_change_percent)
    else:
        price_trend_text = lang_pool.get("cr_price_stable", "")

    channel_msg = lang_pool.get("cr_channel_msg", "").format(
        status_text=status_text, tick=current_tick, course=new_course, trend=trend, old_course=old_course, price_trend=price_trend_text
    )

    if (buy_u - sell_u) > norm_vol * 0.5:
        channel_msg += "\n\n🟢 <i>Игроки активно скупают UMC!</i>"
    elif (sell_u - buy_u) > norm_vol * 0.5:
        channel_msg += "\n\n🔴 <i>На рынке зафиксирован массовый сбор и слив монет!</i>"

    try: await bot.send_message(chat_id=GROUP_ID, text=channel_msg, parse_mode=ParseMode.HTML)
    except Exception: pass

    if next_move in ["super_pamp", "crash"]:
        asyncio.create_task(send_market_alerts(bot, new_course))


async def send_market_alerts(bot, new_course):
    pool = await get_db()
    redis = await get_redis()
    
    locales = {"ru": {}, "en": {}}
    for l in ["ru", "en"]:
        try:
            with open(f"locales/{l}.json", "r", encoding="utf-8") as f: locales[l] = json.load(f)
        except Exception: pass

    async with pool.acquire() as db:
        holders = await db.fetch("SELECT f.user_id, f.umc_balance, u.lang FROM farms f JOIN users u ON f.user_id = u.user_id WHERE f.umc_balance > 0")
        
    for row in holders:
        user_id = row['user_id']
        if redis:
            try:
                if await redis.get(f"alert_off:{user_id}"): continue
            except Exception: pass
            
        u_lang = row['lang'] if row['lang'] in locales else "ru"
        alert_template = locales[u_lang].get("cr_alert_text", "Emergency UMC Alert!")
        
        alert_text = alert_template.format(course=new_course, balance=fmt(int(row['umc_balance'])))
        try:
            await bot.send_message(chat_id=user_id, text=alert_text, parse_mode=ParseMode.HTML)
            await asyncio.sleep(0.05)  
        except Exception: pass

# ==========================================
# 💬 ИНТЕРФЕЙС БИРЖИ И ТЕКСТОВЫЙ ОБМЕННИК
# ==========================================
@router.message(F.text.lower().in_(["курс", "крипта", "биржа", "курс крипты", "rate", "crypto", "exchange"]))
async def cmd_crypto_course(message: types.Message, _=None):
    current_course, _, _ = await get_market_state()
    dynamic_cost = get_dynamic_analysis_cost(current_course)
    
    text = get_str("cr_terminal_body", _, course=current_course)
    builder = InlineKeyboardBuilder()
    builder.button(text=get_str("cr_btn_analysis", _, price=format_short_price(dynamic_cost)), callback_data=f"crypto_buy_analysis_{message.from_user.id}")
    builder.adjust(1)
    await message.reply(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.message(F.text.lower().startswith(("купить крипту", "buy crypto")))
async def text_buy_crypto(message: types.Message, _=None):
    user_id = message.from_user.id
    parts = message.text.split()
    if len(parts) < 3: return await message.reply(get_str("cr_err_no_input_buy", _), parse_mode="HTML")
        
    amount_str = parts[-1].lower().strip()
    pool = await get_db()
    
    async with pool.acquire() as db:
        async with db.transaction():
            await db.execute("SELECT 1 FROM farms WHERE user_id = $1 FOR UPDATE", user_id)
            
            farm_row = await db.fetchrow("SELECT * FROM farms WHERE user_id = $1", user_id)
            if not farm_row: return await message.reply(get_str("cr_err_no_farm", _), parse_mode="HTML")
            farm_data = dict(farm_row)
                
            balance = await db.fetchval("SELECT balance FROM users WHERE user_id = $1", user_id) or 0
            current_course, _, _ = await get_market_state()
            if balance <= 0: return await message.reply(get_str("cr_err_no_fiat_money", _))

            if amount_str in ["все", "всё", "all", "allin", "all-in"]:
                qty_to_buy = int(balance // current_course)
            else:
                try: qty_to_buy = int(amount_str)
                except ValueError: return await message.reply(get_str("cr_err_int_only", _))
                
            if qty_to_buy <= 0: return await message.reply(get_str("cr_err_zero_qty", _))
            total_cost = int(qty_to_buy * current_course)
            if balance < total_cost: return await message.reply(get_str("cr_err_insufficient_fiat", _, price=fmt(total_cost)))

            await db.execute("UPDATE users SET balance = balance - $1 WHERE user_id = $2", total_cost, user_id)
            await db.execute("UPDATE farms SET umc_balance = umc_balance + $1 WHERE user_id = $2", qty_to_buy, user_id)

            redis = await get_redis()
            if redis:
                today = datetime.date.today().isoformat()
                try: 
                    await redis.incrbyfloat("crypto:buy_volume_u", float(total_cost))
                    await redis.incrbyfloat(f"crypto:daily_vol_u_{today}", float(total_cost))
                except Exception: pass
        
    await message.reply(get_str("cr_buy_success", _, qty=fmt(qty_to_buy), price=fmt(total_cost)), parse_mode="HTML")


@router.message(F.text.lower().startswith(("продать крипту", "sell crypto")))
async def text_sell_crypto(message: types.Message, _=None):
    user_id = message.from_user.id
    parts = message.text.split()
    if len(parts) < 3: return await message.reply(get_str("cr_err_no_input_sell", _), parse_mode="HTML")
        
    amount_str = parts[-1].lower().strip()
    pool = await get_db()
    
    async with pool.acquire() as db:
        async with db.transaction():
            await db.execute("SELECT 1 FROM farms WHERE user_id = $1 FOR UPDATE", user_id)
            
            farm_row = await db.fetchrow("SELECT * FROM farms WHERE user_id = $1", user_id)
            if not farm_row: return await message.reply(get_str("cr_err_no_farm", _), parse_mode="HTML")
            farm_data = dict(farm_row)
                
            umc_balance = int(farm_data.get('umc_balance', 0))
            if umc_balance <= 0: return await message.reply(get_str("cr_err_zero_crypto", _))

            if amount_str in ["все", "всё", "all", "allin", "all-in"]:
                qty_to_sell = umc_balance
            else:
                try: qty_to_sell = int(amount_str)
                except ValueError: return await message.reply(get_str("cr_err_int_only", _))
                
            if qty_to_sell <= 0 or qty_to_sell > umc_balance:
                return await message.reply(get_str("cr_err_sell_limits", _, qty=fmt(umc_balance)), parse_mode="HTML")

            current_course, _, _ = await get_market_state()
            fiat_payout = int(qty_to_sell * current_course)
            
            await db.execute("UPDATE farms SET umc_balance = umc_balance - $1 WHERE user_id = $2", qty_to_sell, user_id)
            await db.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", fiat_payout, user_id)

            redis = await get_redis()
            if redis:
                today = datetime.date.today().isoformat()
                try: 
                    await redis.incrbyfloat("crypto:sell_volume_umc", float(qty_to_sell))
                    await redis.incrbyfloat(f"crypto:daily_vol_u_{today}", float(fiat_payout))
                except Exception: pass
        
    await message.reply(get_str("cr_sell_success", _, qty=fmt(qty_to_sell), price=fmt(fiat_payout)), parse_mode="HTML")


@router.message(F.text.lower().startswith(("вывести", "withdraw")))
async def cmd_withdraw_crypto(message: types.Message, _=None):
    user_id = message.from_user.id
    parts = message.text.split()
    if len(parts) < 2: return await message.reply(get_str("cr_err_no_input_withdraw", _), parse_mode="HTML")
        
    amount_str = parts[1].lower().strip()
    pool = await get_db()
    
    async with pool.acquire() as db:
        async with db.transaction():
            await db.execute("SELECT 1 FROM farms WHERE user_id = $1 FOR UPDATE", user_id)
            
            farm_row = await db.fetchrow("SELECT * FROM farms WHERE user_id = $1", user_id)
            if not farm_row: return await message.reply(get_str("cr_err_no_farm", _), parse_mode="HTML")
            farm_data = dict(farm_row)
                
            umc_balance = int(farm_data.get('umc_balance', 0))
            if umc_balance <= 0: return await message.reply(get_str("cr_err_zero_crypto", _))

            if amount_str in ["все", "всё", "all", "allin", "all-in"]:
                qty_to_swap = umc_balance
            else:
                try: qty_to_swap = int(amount_str)
                except ValueError: return await message.reply(get_str("cr_err_int_only", _))
                
            if qty_to_swap <= 0 or qty_to_swap > umc_balance:
                return await message.reply(get_str("cr_err_sell_limits", _, qty=fmt(umc_balance)), parse_mode="HTML")

            current_course, _, _ = await get_market_state()
            gross_fiat = int(qty_to_swap * current_course)
            fee = int(gross_fiat * 0.15)
            net_fiat = gross_fiat - fee
            
            await db.execute("UPDATE farms SET umc_balance = umc_balance - $1 WHERE user_id = $2", qty_to_swap, user_id)
            await db.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", net_fiat, user_id)

            redis = await get_redis()
            if redis:
                today = datetime.date.today().isoformat()
                try: 
                    await redis.incrbyfloat("crypto:sell_volume_umc", float(qty_to_swap))
                    await redis.incrbyfloat(f"crypto:daily_vol_u_{today}", float(gross_fiat))
                except Exception: pass
        
    await message.reply(get_str("cr_withdraw_body", _, qty=fmt(qty_to_swap), course=current_course, fee=fmt(fee), net=fmt(net_fiat)), parse_mode="HTML")


@router.callback_query(F.data.startswith("shadow_swap_"))
async def callback_shadow_swap(call: types.CallbackQuery, _=None):
    owner_id = int(call.data.split("_")[-1])
    if call.from_user.id != owner_id: 
        return await call.answer(get_str("cr_swap_foreign_err", translator=_), show_alert=True)

    user_id = call.from_user.id
    pool = await get_db()
    
    async with pool.acquire() as db:
        async with db.transaction():
            await db.execute("SELECT 1 FROM farms WHERE user_id = $1 FOR UPDATE", user_id)
            
            farm_row = await db.fetchrow("SELECT umc_balance FROM farms WHERE user_id = $1", user_id)
            if not farm_row:
                return await call.answer(get_str("cr_text_err_no_farm", translator=_), show_alert=True)

            umc_balance = int(farm_row['umc_balance'] or 0)
            if umc_balance <= 0: 
                return await call.answer(get_str("cr_err_zero_crypto", translator=_), show_alert=True)

            current_course, _, _ = await get_market_state()
            gross_fiat = int(umc_balance * current_course)
            fee = int(gross_fiat * 0.15)
            net_fiat = gross_fiat - fee

            await db.execute("UPDATE farms SET umc_balance = 0 WHERE user_id = $1", user_id)
            await db.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", net_fiat, user_id)

            redis = await get_redis()
            if redis:
                today = datetime.date.today().isoformat()
                try: 
                    await redis.incrbyfloat("crypto:sell_volume_umc", float(umc_balance))
                    await redis.incrbyfloat(f"crypto:daily_vol_u_{today}", float(gross_fiat))
                except Exception: pass

    await call.message.edit_text(get_str("cr_swap_body", translator=_, qty=fmt(umc_balance), course=current_course, fee=fmt(fee), net=fmt(net_fiat)), parse_mode="HTML")
    await call.answer(get_str("cr_swap_alert_success", translator=_))


@router.message(F.text.lower().startswith(("/notifications", "/notif")))
async def cmd_toggle_notifications(message: types.Message, _=None):
    redis = await get_redis()
    if not redis: return
    
    action = message.text.lower().replace("/notifications", "").replace("/notif", "").strip()
    if action in ["off", "выкл", "disable"]:
        try: await redis.set(f"alert_off:{message.from_user.id}", "1")
        except Exception: pass
        await message.reply(get_str("cr_notif_off", _), parse_mode="HTML")
    else:
        try: await redis.delete(f"alert_off:{message.from_user.id}")
        except Exception: pass
        await message.reply(get_str("cr_notif_on", _), parse_mode="HTML")


# ==========================================
# 🕵️‍♂️ ДИНАМИЧЕСКИЙ ГЛУБОКИЙ ТЕХ-АНАЛИЗ В ЛС
# ==========================================
@router.callback_query(F.data.startswith("crypto_buy_analysis_"))
async def callback_buy_crypto_analysis(callback: types.CallbackQuery, _=None):
    owner_id = int(callback.data.split("_")[-1])
    if callback.from_user.id != owner_id: return await callback.answer(get_str("cr_analysis_foreign_err", _), show_alert=True)
        
    user_id = callback.from_user.id
    current_course, current_tick, real_next_move = await get_market_state()
    dynamic_cost = get_dynamic_analysis_cost(current_course)
    
    redis = await get_redis()
    analysis_key = f"crypto_analysis:{user_id}:{current_tick}"
    
    already_bought = None
    if redis:
        try: already_bought = await redis.get(analysis_key)
        except Exception: pass

    if already_bought:
        saved_msg = already_bought.decode('utf-8') if isinstance(already_bought, bytes) else already_bought
        try:
            await callback.bot.send_message(chat_id=user_id, text=saved_msg, parse_mode="HTML")
            return await callback.answer(get_str("cr_analysis_dup_msg", _), show_alert=True)
        except Exception:
            return await callback.answer(get_str("cr_analysis_closed_err", _), show_alert=True)

    balance = await get_balance(user_id)
    if balance < dynamic_cost:
        return await callback.answer(get_str("cr_analysis_no_money", _, price=fmt(dynamic_cost)), show_alert=True)

    await add_balance(user_id, -dynamic_cost)

    count_key = f"crypto_analysis_count:{user_id}"
    analysis_count = 1
    if redis:
        try:
            raw_count = await redis.incr(count_key)
            analysis_count = int(raw_count.decode('utf-8')) if isinstance(raw_count, bytes) else int(raw_count)
        except Exception: pass

    accuracy_chance = 0.70 + ((current_course - MIN_COURSE) / (MAX_COURSE - MIN_COURSE)) * 0.20
    is_accurate = random.random() < accuracy_chance

    if is_accurate:
        reported_move = real_next_move
    else:
        choices = ["super_pamp", "pamp", "flat_up", "flat_down", "dump", "crash"]
        if real_next_move in choices: choices.remove(real_next_move)
        reported_move = random.choice(choices)

    forecast_text = get_advanced_forecast_text(reported_move, is_accurate, accuracy_chance, dynamic_cost, current_tick, current_course, analysis_count, _)
    
    if redis:
        try: await redis.set(analysis_key, forecast_text, ex=7200)
        except Exception: pass

    try:
        await callback.bot.send_message(chat_id=user_id, text=forecast_text, parse_mode="HTML")
        await callback.answer(get_str("cr_analysis_success_alert", _), show_alert=True)
    except Exception:
        await callback.answer(get_str("cr_analysis_closed_msg", _), show_alert=True)
        public_text = get_str("cr_analysis_public_hdr", _, username=callback.from_user.username or "Агент") + forecast_text
        await callback.message.reply(public_text, parse_mode="HTML")


def get_advanced_forecast_text(reported_move: str, is_accurate: bool, accuracy: float, cost: int, tick: int, course: float, buy_count: int, _=None) -> str:
    accuracy_percent = int(accuracy * 100)
    status_icon = "🟢" if is_accurate else "🟡"
    
    if buy_count == 1:
        intros = [get_str("cr_hacker_newbie_1", _, tick=tick), get_str("cr_hacker_newbie_2", _, tick=tick), get_str("cr_hacker_newbie_3", _, tick=tick)]
    elif buy_count >= 10:
        intros = [get_str("cr_hacker_whale_1", _, tick=tick, accuracy=accuracy_percent), get_str("cr_hacker_whale_2", _, tick=tick), get_str("cr_hacker_whale_3", _, tick=tick)]
    else:
        intros = [get_str("cr_hacker_regular_1", _, tick=tick), get_str("cr_hacker_regular_2", _, tick=tick), get_str("cr_hacker_regular_3", _, tick=tick)]

    hacker_intro = random.choice(intros)
    header = hacker_intro + "\n" + get_str("cr_header_analysis", _, cost=fmt(cost), accuracy=accuracy_percent, icon=status_icon)

    if reported_move in ["super_pamp", "pamp"]:
        direction, trend_word = get_str("cr_dir_bull", _), get_str("cr_rec_bull", _)
    elif reported_move in ["dump", "crash"]:
        direction, trend_word = get_str("cr_dir_bear", _), get_str("cr_rec_bear", _)
    else:
        direction, trend_word = get_str("cr_dir_flat", _), get_str("cr_rec_flat", _)

    tier = current_course_tier(course)
    if tier == 1:
        return get_str("cr_tier1_body", _, direction=direction, trend_word=trend_word)
    elif tier == 2:
        return get_str("cr_tier2_body", _, rsi=random.randint(65, 85) if reported_move in ["super_pamp", "pamp"] else random.randint(15, 35) if reported_move in ["dump", "crash"] else random.randint(45, 55), direction=direction, trend_word=trend_word)
    else:
        whale_action = get_str("cr_whale_bull", _) if reported_move in ["super_pamp", "pamp"] else get_str("cr_whale_bear", _) if reported_move in ["dump", "crash"] else get_str("cr_whale_flat", _)
        return get_str("cr_tier3_body", _, accuracy=accuracy_percent, course=course, whale_action=whale_action, direction=direction, trend_word=trend_word)

def current_course_tier(course: float) -> int:
    if course < 1.50: return 1
    if course < 3.00: return 2
    return 3

def format_short_price(num: int) -> str:
    if num >= 1_000_000: return f"{num / 1_000_000:.1f}M"
    if num >= 1_000: return f"{num // 1_000}k"
    return str(num)