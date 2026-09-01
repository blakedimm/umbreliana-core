import time
import os
import re
import json
import logging
from aiogram import Router, F, types, Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from core.database import get_db, get_balance, add_balance, get_dynamic_gold_rate
from handlers.users.statuses import has_active_status

router = Router()

ADMIN_ID = int(os.getenv("ADMIN_ID", 1412940726))
MODERATORS = [int(i.strip()) for i in os.getenv("MODERATORS", "").split(",") if i.strip()]

fmt = lambda x: f"{int(x):,}".replace(',', ' ')

# ==========================================
# 🎨 БЕЗОПАСНАЯ ФЕЙЛСЕЙФ СИСТЕМА ЛОКАЛИЗАЦИИ
# ==========================================
FALLBACK_STRINGS = {
    "sh_buy_err_zero": "🤡 Сумма должна быть больше нуля.",
    "sh_cancel_foreign": "Не лезь в чужие контракты!",
    "sh_cancel_msg": "❌ <b>Сделка отменена.</b> Средства остались на счету."
}

def get_str(key: str, translator=None, **kwargs) -> str:
    if translator and callable(translator):
        return translator(key, **kwargs)
    text = FALLBACK_STRINGS.get(key, key)
    if kwargs:
        try: return text.format(**kwargs)
        except: pass
    return text

LOCALES = {}
for l in ["ru", "en"]:
    p = f"locales/{l}.json"
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f: LOCALES[l] = json.load(f)
        except Exception as e:
            logging.error(f"Ошибка загрузки локали {l} в акциях: {e}")

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

# ==========================================
# 📜 1. ПОКУПКА АКЦИЙ СИНДИКАТА (ПОДДЕРЖКА ДВУХ СИНТАКСИСОВ)
# ==========================================
@router.message(
    lambda msg: msg.text and (
        msg.text.lower().strip().startswith(("купить акции", "buy shares", "buy stock")) or (
            msg.text.lower().strip().startswith(("купить ", "buy ")) and 
            any(word in msg.text.lower() for word in ["акци", "sh", "share", "stock"])
        )
    )
)
async def buy_gold_currency(message: types.Message, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    user_id = message.from_user.id
    text = message.text.lower().strip()
    
    # 🔍 ДИНАМИЧЕСКИЙ ПАРСИНГ ОБИХ ВАРИАНТОВ НАПИСАНИЯ
    amount_to_buy = None
    
    # Вариант 1: купить акции 7 / buy shares 7 (число в конце)
    m1 = re.match(r"^(?:купить\s+акции|buy\s+shares|buy\s+stock)(?:\s+(\d+))?$", text, re.IGNORECASE)
    # Вариант 2: купить 7 акций / buy 7 sh (число в середине/начале)
    m2 = re.match(r"^(?:купить|buy)\s+(\d+)\s+(?:акций|акции|sh|shares|stock)$", text, re.IGNORECASE)
    
    if m1 and m1.group(1):
        amount_to_buy = int(m1.group(1))
    elif m2 and m2.group(1):
        amount_to_buy = int(m2.group(1))
        
    rate_data = await get_dynamic_gold_rate()
    if isinstance(rate_data, tuple) and len(rate_data) == 3:
        real_rate, market_discount, raw_rate = rate_data
    else:
        real_rate, market_discount, raw_rate = 100_000_000, 0.0, 100_000_000
        
    is_sovereign = await has_active_status(user_id, 5) or await has_active_status(user_id, 777)
    
    first_coin_price = int(real_rate * 0.9) if is_sovereign else real_rate
    rest_coins_price = int(raw_rate * 0.9) if is_sovereign else raw_rate
    
    # Если число не указано вообще (просто "купить акции" или "buy shares")
    if amount_to_buy is None:
        return await message.reply(get_str("sh_buy_header", translator=_, price=fmt(first_coin_price)), parse_mode="HTML")
    
    if amount_to_buy <= 0:
        return await message.reply(get_str("sh_buy_err_zero", translator=_))

    if amount_to_buy == 1:
        cost = first_coin_price
        slippage_text = ""
    else:
        cost = first_coin_price + (rest_coins_price * (amount_to_buy - 1))
        slippage_text = get_str("sh_buy_slippage_text", translator=_, qty=amount_to_buy - 1, price=fmt(rest_coins_price))

    user_bal = await get_balance(user_id)
    if user_bal < cost:
        return await message.reply(get_str("sh_buy_err_no_money", translator=_, qty=amount_to_buy, price=fmt(cost)), parse_mode="HTML")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=get_str("sh_btn_invest", translator=_), callback_data=f"gold_yes_{user_id}_{amount_to_buy}"),
            InlineKeyboardButton(text=get_str("sh_btn_cancel", translator=_), callback_data=f"gold_no_{user_id}")
        ]
    ])

    discount_text = get_str("sh_buy_discount_sov", translator=_) if is_sovereign else ""
    market_text = get_str("sh_buy_discount_market", translator=_, percent=int(market_discount*100)) if market_discount > 0 else ""

    confirm_text = get_str("sh_confirm_title", translator=_, price=fmt(cost), qty=amount_to_buy, discount=discount_text, market=market_text, slippage=slippage_text)
    await message.reply(confirm_text, reply_markup=kb, parse_mode="HTML")

# ==========================================
# 📜 2. ОБРАБОТКА ПОДТВЕРЖДЕНИЯ
# ==========================================
@router.callback_query(F.data.startswith("gold_yes_"))
async def confirm_buy_gold(call: types.CallbackQuery, _=None):
    if not _: _ = await resolve_chat_translator(call.message.chat.id, _)
    parts = call.data.split('_')
    target_user_id = int(parts[2])
    amount_to_buy = int(parts[3])

    if call.from_user.id != target_user_id:
        return await call.answer(get_str("sh_cancel_foreign", translator=_), show_alert=True)

    rate_data = await get_dynamic_gold_rate()
    real_rate, market_discount, raw_rate = rate_data if len(rate_data) == 3 else (100_000_000, 0.0, 100_000_000)
    
    is_sovereign = await has_active_status(target_user_id, 5) or await has_active_status(target_user_id, 777)
    first_coin_price = int(real_rate * 0.9) if is_sovereign else real_rate
    rest_coins_price = int(raw_rate * 0.9) if is_sovereign else raw_rate

    if amount_to_buy == 1:
        cost = first_coin_price
    else:
        cost = first_coin_price + (rest_coins_price * (amount_to_buy - 1))

    user_bal = await get_balance(target_user_id)
    if user_bal < cost:
        await call.message.edit_text(get_str("sh_confirm_err_balance", translator=_), parse_mode="HTML")
        return await call.answer()

    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            await db.execute("INSERT INTO users (user_id) VALUES ($1) ON CONFLICT(user_id) DO NOTHING", target_user_id)
            await add_balance(target_user_id, -cost)
            await db.execute("UPDATE users SET gold_balance = COALESCE(gold_balance, 0) + $1 WHERE user_id = $2", amount_to_buy, target_user_id)

            is_admin = (target_user_id == ADMIN_ID or target_user_id in MODERATORS)
            if not is_admin:
                current_timestamp = int(time.time())
                await db.execute("""
                    INSERT INTO system_stats (key, value_int) VALUES ('last_gold_buy', $1)
                    ON CONFLICT (key) DO UPDATE SET value_int = $1
                """, current_timestamp)

    success_text = get_str("sh_confirm_success", translator=_, price=fmt(cost), qty=amount_to_buy)
    await call.message.edit_text(success_text, parse_mode="HTML")
    await call.answer(get_str("sh_confirm_alert", translator=_))

@router.callback_query(F.data.startswith("gold_no_"))
async def cancel_buy_gold(call: types.CallbackQuery, _=None):
    if not _: _ = await resolve_chat_translator(call.message.chat.id, _)
    parts = call.data.split('_')
    target_user_id = int(parts[2])

    if call.from_user.id != target_user_id:
        return await call.answer(get_str("sh_cancel_foreign", translator=_), show_alert=True)

    await call.message.edit_text(get_str("sh_cancel_msg", translator=_), parse_mode="HTML")
    await call.answer()

# ==========================================
# 📜 ПРОВЕРКА ПОРТФЕЛЯ
# ==========================================
@router.message(F.text.lower().in_(["портфель", "мои акции", "активы", "portfolio", "my shares", "assets"]))
async def check_gold_balance(message: types.Message, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    user_id = message.from_user.id
    
    pool = await get_db()
    async with pool.acquire() as db:
        gold = await db.fetchval("SELECT gold_balance FROM users WHERE user_id = $1", user_id) or 0
        
    if gold == 0:
        await message.reply(get_str("sh_portfolio_empty", translator=_), parse_mode="HTML")
    else:
        await message.reply(get_str("sh_portfolio_body", translator=_, gold=fmt(gold)), parse_mode="HTML")

# ==========================================
# 📈 ПРОСМОТР ИНДЕКСА
# ==========================================
@router.message(F.text.lower().in_(["индекс", "акции", "курс акций", "index", "shares", "stock rate"]))
async def show_gold_rate(message: types.Message, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    user_id = message.from_user.id
    
    rate_data = await get_dynamic_gold_rate()
    if isinstance(rate_data, tuple) and len(rate_data) == 3:
        real_rate, market_discount, raw_rate = rate_data
    else:
        real_rate, market_discount, raw_rate = 100_000_000, 0.0, 100_000_000
        
    is_sovereign = await has_active_status(user_id, 5) or await has_active_status(user_id, 777)
    personal_rate = int(real_rate * 0.9) if is_sovereign else real_rate
    
    user_bal = await get_balance(user_id)
    possible_to_buy = user_bal // personal_rate
    
    if market_discount > 0:
        market_state = get_str("sh_index_state_correction", translator=_, percent=int(market_discount * 100))
        price_text = get_str("sh_index_price_correction_lbl", translator=_, raw=fmt(raw_rate), real=fmt(real_rate))
    else:
        market_state = get_str("sh_index_state_growth", translator=_)
        price_text = get_str("sh_index_price_growth_lbl", translator=_, real=fmt(real_rate))

    text = get_str("sh_index_body", translator=_, state=market_state, price_text=price_text)
    
    if is_sovereign:
        text += get_str("sh_index_sov_row", translator=_, price=fmt(personal_rate))
    
    text += get_str("sh_index_footer", translator=_, balance=fmt(user_bal), qty=fmt(possible_to_buy))
    await message.reply(text, parse_mode="HTML")

# ==========================================
# 🏢 РАСПРЕДЕЛЕНИЕ ДИВИДЕНДОВ (БЭКГРАУНД КРОН)
# ==========================================
async def distribute_dividends(bot: Bot):
    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            total_pool = await db.fetchval("SELECT value_int FROM system_stats WHERE key = 'dividend_pool'") or 0
            if total_pool < 1000: return

            holders = await db.fetch("SELECT user_id, gold_balance FROM users WHERE gold_balance > 0")
            if not holders: return

            effective_holders = []
            total_effective_gold = 0.0

            # Вычистили "_" из логики итераций, уберегая крон от зависания
            for holder in holders:
                g = holder['gold_balance']
                eff_g = 0.0
                if g > 0: eff_g += min(g, 10) 
                if g > 10: eff_g += min(g - 10, 40) * 0.75 
                if g > 50: eff_g += (g - 50) * 0.30 
                
                total_effective_gold += eff_g
                effective_holders.append({'user_id': holder['user_id'], 'real_gold': g, 'eff_gold': eff_g})

            if total_effective_gold <= 0: return
            payout_per_eff_gold = total_pool / total_effective_gold

            for h in effective_holders:
                payout = int(h['eff_gold'] * payout_per_eff_gold)
                if payout > 0:
                    await add_balance(h['user_id'], payout)
                    
                    # 🔥 ЖЕСТКИЙ ПЕРЕХВАТ ЯЗЫКА КЛИЕНТА ВНУТРИ ЦИКЛА РАССЫЛКИ
                    user_lang = await db.fetchval("SELECT lang FROM users WHERE user_id = $1", h['user_id']) or "ru"
                    _user_trans = get_translator(user_lang)
                    
                    try:
                        await bot.send_message(
                            h['user_id'], 
                            get_str("sh_dividend_payout_msg", translator=_user_trans, qty=h['real_gold'], payout=fmt(payout)),
                            parse_mode="HTML"
                        )
                    except: pass

            await db.execute("UPDATE system_stats SET value_int = 0 WHERE key = 'dividend_pool'")
            
    logging.info(f"💰 Дивиденды распределены: {fmt(total_pool)} ᴜ раздано {len(holders)} акционерам.")