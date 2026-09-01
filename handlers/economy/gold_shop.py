import os
import json
import logging
from aiogram import Router, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from core.database import get_db

router = Router()

fmt = lambda x: f"{int(x):,}".replace(',', ' ')

# ==========================================
# 💠 АССОРТИМЕНТ ТЕНЕВОГО РЫНКА
# ==========================================
GOLD_ITEMS = {
    "glitch": {
        "price": 3, 
        "name_key": "gs_art_name_glitch",
        "desc_key": "gs_art_desc_glitch"
    },
    "phantom": {
        "price": 7, 
        "name_key": "gs_art_name_phantom",
        "desc_key": "gs_art_desc_phantom"
    },
    "night": {
        "price": 5, 
        "name_key": "gs_art_name_night",
        "desc_key": "gs_art_desc_night"
    },
    "cursed": {
        "price": 4,
        "name_key": "gs_art_name_cursed",
        "desc_key": "gs_art_desc_cursed"
    },
    "abyss": {
        "price": 15, 
        "name_key": "gs_art_name_abyss",
        "desc_key": "gs_art_desc_abyss"
    }
}

# Резервные дефолты (Фейлсейф-предохранитель)
FALLBACK_STRINGS = {
    "gs_art_name_glitch": "👾 RTX 'Glitch' Edition",
    "gs_art_name_phantom": "👻 Phantom Core v1",
    "gs_art_name_night": "🦇 Night Hunter Core",
    "gs_art_name_cursed": "🩸 Нейро-Майнер Синдиката",
    "gs_art_name_abyss": "🌌 Осколок Бездны"
}

def get_str(key: str, translator=None, **kwargs) -> str:
    if translator and callable(translator):
        return translator(key, **kwargs)
    
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
        try:
            with open(p, "r", encoding="utf-8") as f: LOCALES[l] = json.load(f)
        except Exception as e:
            logging.error(f"Ошибка загрузки локали {l} в голд шопе: {e}")

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
# 🛒 ОТРИСОВКА ВИТРИНЫ
# ==========================================
@router.message(F.text.lower().in_(["магазин голд", "голд магазин", "гмагазин", "теневой рынок", "магазин акций", "магазин артефактов", "gold shop", "shadow market", "shares shop", "artifacts shop"]))
async def show_gold_shop(message: types.Message, _=None):
    if not _: _ = await resolve_chat_translator(message.chat.id, _)
    user_id = message.from_user.id
    
    pool = await get_db()
    async with pool.acquire() as db:
        gold_bal = await db.fetchval("SELECT gold_balance FROM users WHERE user_id = $1", user_id) or 0

    builder = InlineKeyboardBuilder()
    text = get_str("gs_title", translator=_, gold_bal=gold_bal)
    
    for key, item in GOLD_ITEMS.items():
        can_afford = "🟢" if gold_bal >= item['price'] else "🔴"
        localized_name = get_str(item['name_key'], translator=_)
        localized_desc = get_str(item['desc_key'], translator=_)
        
        text += f"{can_afford} <b>{localized_name}</b>\n├ Цена: <b>{item['price']} 📜 SH</b>\n└ <i>{localized_desc}</i>\n\n"
        
        if gold_bal >= item['price']:
            builder.button(text=get_str("gs_btn_exchange", translator=_, name=localized_name), callback_data=f"buy_g_{key}_{user_id}")
        else:
            builder.button(text=get_str("gs_btn_locked", translator=_, price=item['price']), callback_data="gold_shop_locked")
            
    builder.button(text=get_str("gs_btn_hint", translator=_), callback_data="buy_shares_fiat_hint")
    builder.adjust(1)
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "gold_shop_locked")
async def gold_shop_locked_btn(call: types.CallbackQuery, _=None):
    if not _: _ = await resolve_chat_translator(call.message.chat.id, _)
    await call.answer(get_str("gs_alert_locked", translator=_), show_alert=True)

@router.callback_query(F.data == "buy_shares_fiat_hint")
async def buy_shares_hint_btn(call: types.CallbackQuery, _=None):
    if not _: _ = await resolve_chat_translator(call.message.chat.id, _)
    await call.answer()
    await call.message.answer(get_str("gs_hint_msg", translator=_), parse_mode="HTML")

# ==========================================
# 🔒 ОБРАБОТКА ПОКУПКИ АРТЕФАКТОВ
# ==========================================
@router.callback_query(F.data.startswith("buy_g_"))
async def process_gold_purchase(call: types.CallbackQuery, _=None):
    if not _: _ = await resolve_chat_translator(call.message.chat.id, _)
    parts = call.data.split("_")
    item_key = parts[2]
    target_id = int(parts[3])
    user_id = call.from_user.id
    
    if user_id != target_id:
        return await call.answer(get_str("gs_err_foreign", translator=_), show_alert=True)
        
    item = GOLD_ITEMS.get(item_key)
    if not item:
        return await call.answer(get_str("gs_err_removed", translator=_), show_alert=True)
        
    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            gold_bal = await db.fetchval("SELECT gold_balance FROM users WHERE user_id = $1 FOR UPDATE", user_id)
            gold_bal = gold_bal or 0
            
            if gold_bal < item['price']:
                return await call.answer(get_str("gs_err_insufficient", translator=_, price=item['price'], balance=gold_bal), show_alert=True)
            
            await db.execute("UPDATE users SET gold_balance = gold_balance - $1 WHERE user_id = $2", item['price'], user_id)
            await db.execute(
                "INSERT INTO gpu_batches (user_id, gpu_id, special_type, qty, condition, was_repaired) VALUES ($1, $2, $3, 1, 100.0, 0)",
                user_id, f"gold_{item_key}", item_key
            )
            
    localized_name = get_str(item['name_key'], translator=_)
    success_text = get_str("gs_success_body", translator=_, name=localized_name, price=item['price'], rem=gold_bal - item['price'])
    await call.message.edit_text(success_text, parse_mode="HTML")
    await call.answer(get_str("gs_alert_success", translator=_))