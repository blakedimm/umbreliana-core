import os
import json
import logging
from aiogram import BaseMiddleware
from core.database import get_db

class L10nMiddleware(BaseMiddleware):
    def __init__(self, locales_dir="locales"):
        super().__init__()
        self.locales = {}
        self.locales_dir = locales_dir
        self.load_locales()

    def load_locales(self):
        if not os.path.exists(self.locales_dir):
            os.makedirs(self.locales_dir)
            return

        for filename in os.listdir(self.locales_dir):
            if filename.endswith(".json"):
                lang_code = filename.split(".")[0]
                file_path = os.path.join(self.locales_dir, filename)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        self.locales[lang_code] = json.load(f)
                    logging.info(f"🌐 Локализация загружена: {lang_code}")
                except Exception as e:
                    logging.error(f"❌ Ошибка загрузки локали {filename}: {e}")

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        chat = data.get("event_chat")
        
        if not user:
            return await handler(event, data)

        # Устанавливаем базовый дефолт сети
        lang = "ru"
        pool = await get_db()
        
        try:
            async with pool.acquire() as db:
                # 1. Если это группа/супергруппа — приоритет отдаём локали самого чата
                if chat and chat.type != "private":
                    chat_lang = await db.fetchval("SELECT lang FROM chats WHERE chat_id = $1", chat.id)
                    if chat_lang:
                        lang = chat_lang
                    else:
                        # Если чата нет в базе, смотрим на личный язык юзера
                        user_lang = await db.fetchval("SELECT lang FROM users WHERE user_id = $1", user.id)
                        if user_lang:
                            lang = user_lang
                else:
                    # 2. В ЛС с ботом — берём личный язык из профиля агента
                    user_lang = await db.fetchval("SELECT lang FROM users WHERE user_id = $1", user.id)
                    if user_lang:
                        lang = user_lang
        except Exception as e:
            logging.error(f"❌ Ошибка резолва языка в мидлваре: {e}")

        # Проверяем, загружен ли выбранный язык, иначе падаем в русскую локаль
        if lang not in self.locales:
            lang = "ru"
            
        strings = self.locales.get(lang, {})

        # Изолированная функция перевода для конкретного контекста выполнения
        def translate(key: str, **kwargs) -> str:
            text = strings.get(key, self.locales.get("ru", {}).get(key, key))
            if kwargs:
                try: return text.format(**kwargs)
                except: pass
            return text

        # Прокидываем функцию перевода в data хэндлера для ВСЕХ игроков
        data["_"] = translate
        return await handler(event, data)