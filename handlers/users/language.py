import time
import logging
import os
import json
from aiogram import Router, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command
from aiogram.enums import ChatMemberStatus  # Фикс импорта перечислений для aiogram 3

from core.database import get_db

router = Router()

fmt = lambda x: f"{int(x):,}".replace(',', ' ')

FALLBACK_STRINGS = {
    "test_profile": "👤 <b>ENGLISH INTERFACE SUCCESSFULLY TESTED!</b>\n━━━━━━━━━━━━━━━━━━━━\nHello, {name}!\nYour balance: <b>{fiat} ᴜ</b>\n\nLocalization system is fully operational."
}

def get_str(key: str, translator=None, **kwargs) -> str:
    if translator and callable(translator):
        return translator(key, **kwargs)
    text = FALLBACK_STRINGS.get(key, key)
    if kwargs:
        try: return text.format(**kwargs)
        except: pass
    return text

# ==========================================
# 🌐 РУЧНАЯ СМЕНА ЯЗЫКА
# ==========================================
@router.message(Command("language", "lang"))
@router.message(F.text.lower().in_(["сменить язык", "change language", "language"]))
async def cmd_choose_language(message: types.Message, _ = None):
    user_id = message.from_user.id

    text = (
        "🌐 <b>УСТАНОВКА ИНТЕРФЕЙСА ТЕРМИНАЛА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Выбери основной язык для взаимодействия с сетью Синдиката:\n\n"
        "Select your primary language for interacting with the Syndicate network:"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🇷🇺 Русский", callback_data=f"set_lang_ru_{user_id}")
    builder.button(text="🇺🇸 English", callback_data=f"set_lang_en_{user_id}")
    builder.adjust(2)
    
    await message.reply(text, reply_markup=builder.as_markup(), parse_mode="HTML")


# ==========================================
# 💾 ОБРАБОТКА ИЗМЕНЕНИЯ ЯЗЫКА В БД
# ==========================================
@router.callback_query(F.data.startswith("set_lang_"))
async def callback_set_language(call: types.CallbackQuery):
    parts = call.data.split("_")
    target_lang = parts[2]   # 'ru' или 'en'
    owner_id = int(parts[3]) # ID инициатора сессии
    
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    if user_id != owner_id:
        return await call.answer(
            "🛑 Это не твой terminal выбора! / This is not your selection terminal!", 
            show_alert=True
        )

    pool = await get_db()
    async with pool.acquire() as db:
        # 🔥 ОПТИМИЗАЦИЯ: Атомарный UPSERT вместо лишнего SELECT-чека. Заменено на 'lang'
        await db.execute(
            """
            INSERT INTO users (user_id, lang, balance, gold_balance, gold_last_collect) 
            VALUES ($1, $2, 0, 0, $3) 
            ON CONFLICT (user_id) DO UPDATE SET lang = EXCLUDED.lang
            """,
            user_id, target_lang, int(time.time())
        )

        # 2. Апдейт локали чата через Bot API. Заменено на 'lang'
        if call.message.chat.type != "private":
            try:
                member = await call.message.bot.get_chat_member(chat_id=chat_id, user_id=user_id)
                if member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
                    await db.execute(
                        """
                        INSERT INTO chats (chat_id, lang) VALUES ($1, $2) 
                        ON CONFLICT (chat_id) DO UPDATE SET lang = EXCLUDED.lang
                        """,
                        chat_id, target_lang
                    )
            except Exception as e:
                logging.warning(f"Не удалось обновить локаль чата {chat_id}: {e}")

    # Текстовые рапорты под выбранный вектор
    if target_lang == "ru":
        success_text = (
            "🇷🇺 <b>ЯЗЫК СИСТЕМЫ ИЗМЕНЕН</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Интерфейс Umbreliana успешно переведен на русский язык.\n"
            "Используй клавиатуру команд или введи <code>профиль</code> для старта."
        )
        alert_text = "Язык установлен: Русский"
    else:
        success_text = (
            "🇺🇸 <b>SYSTEM LANGUAGE CHANGED</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Umbreliana interface has been successfully translated to English.\n"
            "Use the custom command layout or type <code>profile</code> to start operating."
        )
        alert_text = "Language set: English"

    try:
        await call.message.edit_text(success_text, parse_mode="HTML")
    except:
        await call.message.answer(success_text, parse_mode="HTML")
        
    await call.answer(alert_text, show_alert=True)


@router.message(F.text.lower() == "тест")
async def cmd_test_localization(message: types.Message, _ = None):
    if not _:
        return await message.reply("❌ Модуль локализации заблокирован для вашего ID.")
        
    fake_balance = "500 000" 
    text = get_str("test_profile", translator=_, name=message.from_user.first_name, fiat=fake_balance)
    await message.reply(text, parse_mode="HTML")