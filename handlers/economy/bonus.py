import time
from datetime import date
from cachetools import TTLCache
from aiogram import Router, types, F

# Импорты ядра
from core.database import get_db, get_balance, add_balance, get_last_bonus, update_last_bonus, get_user_data
from handlers.users.statuses import has_active_status
from handlers.users.rating_system import get_rank_info

router = Router()

def fmt(num):
    return f"{int(num):,}".replace(",", " ")

# ==========================================
# 🧠 УМНОЕ КЭШИРОВАНИЕ ДАННЫХ (ОПТИМИЗАЦИЯ 2.0)
# ==========================================
user_data_cache = TTLCache(maxsize=2000, ttl=5.0)

async def get_cached_user_data(user_id: int):
    if user_id in user_data_cache:
        return user_data_cache[user_id]
        
    data = await get_user_data(user_id)
    user_data_cache[user_id] = data
    return data

# ==========================================
# 🎨 БЕЗОПАСНЫЙ СЛОВАРЬ ДЕФОЛТОВ (ДЛЯ ФОЛБЕКА)
# ==========================================
FALLBACK_STRINGS = {
    "bn_already_claimed": "⏳ <b>Отказ.</b> Резервы на сегодня исчерпаны. Возвращайся завтра.",
    "bn_prefix_sovereign": "👑 <b>ВИП, Ваш бонус получен!</b>",
    "bn_prefix_newbie": "🎉 <b>Стартовый грант получен!</b>",
    "bn_prefix_default": "🎁 <b>Успешно!</b>",
    "bn_rank_text": "\n🎖 <b>Грант за статус A:</b> +{bonus} ᴜ",
    "bn_bonus_sovereign_fx": "<b>{bonus}</b> ᴜ 🔥 (+30%)",
    "bn_bonus_default_fx": "<b>{bonus}</b> ᴜ",
    "bn_final_text": "{user_mention}, {prefix_text}\nСеть выделила тебе: {bonus_text}{rank_text}\n💰 Твой капитал: <b>{balance}</b> ᴜ",
    "bn_alert_foreign": "🛑 Это не твой бонус! Напиши «б», чтобы проверить свой.",
    "bn_alert_already": "⏳ Бонус уже получен!",
    "bn_alert_success": "✅ Бонус зачислен!"
}

def get_str(key: str, _=None, **kwargs) -> str:
    """Умный распределитель строк локализации с защитой сессии"""
    if _:
        return _(key, **kwargs)
    text = FALLBACK_STRINGS.get(key, key)
    if kwargs:
        try: return text.format(**kwargs)
        except: pass
    return text

# ==========================================
# 🧠 ЯДРО БОНУСНОЙ СИСТЕМЫ
# ==========================================
async def process_daily_bonus(user_id: int, chat_type: str, first_name: str, _=None) -> tuple[bool, str]:
    today = str(date.today()) 
    last_claim = await get_last_bonus(user_id)
    
    if last_claim == today:
        return False, get_str("bn_already_claimed", _)

    is_sovereign = await has_active_status(user_id, 777)
    user_data = await get_cached_user_data(user_id)
    current_balance = await get_balance(user_id)
    
    first_seen = user_data.get('first_seen', int(time.time())) if user_data else int(time.time())
    account_age_hours = (int(time.time()) - first_seen) / 3600.0
    
    is_real_newbie = (last_claim is None) and (account_age_hours <= 24) and (current_balance < 100_000)

    if is_sovereign:
        base_bonus = 200_000
        prefix_text = get_str("bn_prefix_sovereign", _)
    elif is_real_newbie:
        base_bonus = 50_000
        prefix_text = get_str("bn_prefix_newbie", _)
    else:
        base_bonus = 15_000
        prefix_text = get_str("bn_prefix_default", _)

    rank_bonus = 0
    rank_text = ""

    if chat_type == "private":
        pool = await get_db()
        async with pool.acquire() as db:
            points = await db.fetchval("SELECT rating_points FROM user_rating WHERE user_id = $1", user_id)
            if points is not None:
                letter, val = get_rank_info(points)
                if letter == "A":
                    if val == 100: rank_bonus = 120_000
                    elif val >= 90: rank_bonus = 70_000
                    else: rank_bonus = 50_000
                    rank_text = get_str("bn_rank_text", _, bonus=fmt(rank_bonus))

    total_bonus = base_bonus + rank_bonus

    if is_sovereign:
        total_bonus = int(total_bonus * 1.3)
        bonus_text = get_str("bn_bonus_sovereign_fx", _, bonus=fmt(total_bonus))
    else:
        bonus_text = get_str("bn_bonus_default_fx", _, bonus=fmt(total_bonus))

    await add_balance(user_id, total_bonus, is_income=True) 
    await update_last_bonus(user_id, today)

    new_balance = await get_balance(user_id)
    user_mention = f"<a href='tg://user?id={user_id}'>{first_name}</a>"

    final_text = get_str("bn_final_text", _, user_mention=user_mention, prefix_text=prefix_text, bonus_text=bonus_text, rank_text=rank_text, balance=fmt(new_balance))
    return True, final_text

# ==========================================
# 🎁 ОБРАБОТЧИК ДЛЯ ТЕКСТОВЫХ КОМАНД (ВЕЗДЕ)
# ==========================================
@router.message(F.text.lower().in_(["бонус", "🎁 бонус", "bonus", "🎁 bonus", "claim bonus", "get bonus"]))
async def cmd_claim_bonus(message: types.Message, _=None):
    success, text = await process_daily_bonus(
        user_id=message.from_user.id, 
        chat_type=message.chat.type, 
        first_name=message.from_user.first_name,
        _=_
    )
    await message.reply(text, parse_mode="HTML")

# ==========================================
# 🎁 ОБРАБОТЧИК ИНЛАЙН-КНОПКИ ПОД БАЛАНСОМ
# ==========================================
@router.callback_query(F.data.startswith("claim_bonus_inline_"))
async def callback_claim_bonus_inline(callback: types.CallbackQuery, _=None):
    owner_id = int(callback.data.split("_")[-1])
    if callback.from_user.id != owner_id:
        return await callback.answer(get_str("bn_alert_foreign", _), show_alert=True)

    success, text = await process_daily_bonus(
        user_id=callback.from_user.id, 
        chat_type=callback.message.chat.type, 
        first_name=callback.from_user.first_name,
        _=_
    )

    if not success:
        await callback.answer(get_str("bn_alert_already", _), show_alert=True)
        try: await callback.message.edit_reply_markup(reply_markup=None) 
        except: pass
        return

    await callback.answer(get_str("bn_alert_success", _), show_alert=False)
    try: await callback.message.edit_reply_markup(reply_markup=None) 
    except: pass
    
    await callback.message.answer(text, parse_mode="HTML")