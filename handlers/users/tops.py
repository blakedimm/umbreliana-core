import time
from aiogram import Router, types, F
from aiogram.filters import Command

# Импорты ядра
from core.database import get_db, get_top_10_global, get_top_10_local
from handlers.syndicate.farms import GPUS
from core.redis_driver import get_redis # ⚡️ ПОДКЛЮЧАЕМ РЕДИС

router = Router()

# Системные ID, которые не должны отображаться в топах (Боты, Админы)
IGNORE_IN_TOPS = [8489556437, 1412940726, 8591496159, 1580552207, 7502224450]

def fmt(num):
    return f"{int(num):,}".replace(",", " ")

# ==========================================
# 🎨 БЕЗОПАСНЫЙ СЛОВАРЬ ДЕФОЛТОВ (ДЛЯ ФОЛБЕКА)
# ==========================================
FALLBACK_STRINGS = {
    "tp_farms_empty": "В этом секторе пока нет ни одной работающей фермы. Все сидят без дела.",
    "tp_farms_no_gpus": "Даже Intel GMA ни у кого нет. Позорище.",
    "tp_farms_global_hdr": "🌍 <b>GLOBAL MINING LEADERS</b>\n",
    "tp_farms_global_ftr": "<i>Мировое господство. Разгоняй карты!</i>",
    "tp_farms_local_hdr": "<b>ТОП-10 ФЕРМ ЧАТА</b>\n",
    "tp_farms_local_ftr": "<i>Рейтинг чата. Напиши «топ ферм глобал» для общего рейтинга.</i>",
    "tp_row_template_ph": "{prefix} <b>{name}</b> — {income} ᴜ/ч\n",
    "tp_wealth_global_hdr": "🌍 <b>GLOBAL WEALTH LEADERS</b>\n",
    "tp_wealth_global_ftr": "<i>Элита Теневой Сети.</i>",
    "tp_wealth_local_hdr": "<b>ТОП-10 БОГАЧЕЙ ЧАТА</b>\n",
    "tp_wealth_local_ftr": "<i>Рейтинг чата. Напиши «топ глобал» для общего рейтинга.</i>",
    "tp_wealth_empty": "Список пока пуст.",
    "tp_row_template_bal": "{prefix} <b>{name}</b> — {balance} ᴜ\n"
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
# 1. ТОП ФЕРМ
# ==========================================
@router.message(Command("top_farms"))
@router.message(F.text.lower().startswith(("топ ферм", "топ ферма", "top farms", "top farm")))
async def show_top_farms(message: types.Message, _=None):
    chat_id = message.chat.id
    user_id = message.from_user.id
    text_args = message.text.lower().split()
    
    is_global = any(w in text_args for w in ["глобал", "мир", "global", "world"]) or message.chat.type == "private"
    
    pool = await get_db()
    # Получаем язык пользователя для создания изолированного кэш-ключа в Redis
    async with pool.acquire() as db:
        lang = await db.fetchval("SELECT lang FROM users WHERE user_id=$1", user_id) or "ru"
        
    # ⚡️ 1. ПРОВЕРЯЕМ КЭШ REDIS С УЧЕТОМ ЯЗЫКА СЕССИИ
    redis = await get_redis()
    cache_key = f"cache:top_farms:global:{lang}" if is_global else f"cache:top_farms:local:{chat_id}:{lang}"
    
    if redis:
        cached_text = await redis.get(cache_key)
        if cached_text:
            return await message.answer(cached_text, parse_mode="HTML")

    # 🐌 2. ЕСЛИ КЭША НЕТ — РАБОТАЕТ БАЗА (Тяжелая операция)
    users_dict = {}
    async with pool.acquire() as db:
        if is_global:
            rows = await db.fetch(
                "SELECT user_id, telegram_username as nick FROM users WHERE NOT user_id = ANY($1::bigint[])", 
                IGNORE_IN_TOPS
            )
        else:
            rows = await db.fetch("""
                SELECT u.user_id, u.telegram_username as nick 
                FROM users u
                JOIN chat_members cm ON u.user_id = cm.user_id
                WHERE cm.chat_id = $1 AND NOT u.user_id = ANY($2::bigint[])
            """, chat_id, IGNORE_IN_TOPS)
            
        for row in rows:
            users_dict[row['user_id']] = row['nick'] if row['nick'] else f"Агент {row['user_id']}"

    if not users_dict:
        return await message.reply(get_str("tp_farms_empty", _))

    farm_power = {uid: 0 for uid in users_dict}
    user_ids = list(users_dict.keys())
    
    async with pool.acquire() as db:
        batches = await db.fetch(
            "SELECT user_id, gpu_id, multiplier, qty FROM gpu_batches WHERE condition > 0 AND user_id = ANY($1::bigint[])",
            user_ids
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
            except Exception:
                pass

    farm_list = [{'nick': users_dict[uid], 'income': power} for uid, power in farm_power.items() if power > 0]
    farm_list.sort(key=lambda x: x['income'], reverse=True)
    top_10 = farm_list[:10]
    
    if not top_10:
        return await message.reply(get_str("tp_farms_no_gpus", _))

    if is_global:
        header = get_str("tp_farms_global_hdr", _)
        sep = "════════════════════\n"
        footer = get_str("tp_farms_global_ftr", _)
    else:
        header = get_str("tp_farms_local_hdr", _)
        sep = "━━━━━━━━━━━━━━━━━━━━\n"
        footer = get_str("tp_farms_local_ftr", _)

    text = header + sep
    
    for i, player in enumerate(top_10, 1):
        prefix = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"<b>{i}.</b>"
        text += get_str("tp_row_template_ph", _, prefix=prefix, name=player['nick'], income=fmt(player['income']))

    text += sep + footer
    
    # ⚡️ 3. СОХРАНЯЕМ РЕЗУЛЬТАТ В КЭШ НА 60 СЕКУНД ДЛЯ КОНКРЕТНОГО ЯЗЫКА
    if redis:
        await redis.setex(cache_key, 60, text)
        
    await message.answer(text, parse_mode="HTML")

# ==========================================
# 2. ТОП БАЛАНСОВ
# ==========================================
@router.message(Command("top"))
@router.message(F.text.lower().startswith(("топ", "top")))
async def cmd_show_top(message: types.Message, _=None):
    chat_id = message.chat.id
    user_id = message.from_user.id
    text_args = message.text.lower().split()
    
    is_global = any(w in text_args for w in ["глобал", "мир", "global", "world"]) or message.chat.type == "private"
    
    pool = await get_db()
    async with pool.acquire() as db:
        lang = await db.fetchval("SELECT lang FROM users WHERE user_id=$1", user_id) or "ru"
        
    # ⚡️ 1. ПРОВЕРЯЕМ КЭШ REDIS С УЧЕТОМ ЯЗЫКА
    redis = await get_redis()
    cache_key = f"cache:top_wealth:global:{lang}" if is_global else f"cache:top_wealth:local:{chat_id}:{lang}"
    
    if redis:
        cached_text = await redis.get(cache_key)
        if cached_text:
            return await message.answer(cached_text, parse_mode="HTML")
            
    # 🐌 2. ЕСЛИ КЭША НЕТ — ДЕРГАЕМ БАЗУ
    if is_global:
        rows = await get_top_10_global()
        header = get_str("tp_wealth_global_hdr", _)
        sep = "════════════════════\n"
        footer = get_str("tp_wealth_global_ftr", _)
    else:
        rows = await get_top_10_local(chat_id)
        header = get_str("tp_wealth_local_hdr", _)
        sep = "━━━━━━━━━━━━━━━━━━━━\n"
        footer = get_str("tp_wealth_local_ftr", _)

    if not rows:
        return await message.reply(get_str("tp_wealth_empty", _))

    text = header + sep
    
    for i, row in enumerate(rows, 1):
        uid, bal, nick = row['user_id'], row['balance'], row['nickname']
        if uid in IGNORE_IN_TOPS: continue
        
        name = nick if nick else f"Агент {uid}"
        prefix = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"<b>{i}.</b>"
        text += get_str("tp_row_template_bal", _, prefix=prefix, name=name, balance=fmt(bal))
    
    text += sep + footer
    
    # ⚡️ 3. СОХРАНЯЕМ В ИЗОЛИРОВАННЫЙ КЭШ НА 60 СЕКУНД
    if redis:
        await redis.setex(cache_key, 60, text)
        
    await message.answer(text, parse_mode="HTML")