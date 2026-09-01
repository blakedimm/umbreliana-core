# ==========================================
# 🧠 ГЛОБАЛЬНЫЙ РЕЕСТР ТРИГГЕРОВ UMBRELIANA
# ==========================================

ECONOMY_TRIGGERS = {
    "б", "баланс", "бонус", "банк", "ферма", "сбор", "собрать", "инвентарь", 
    "рынок", "трейд", "донат", "на", "с", "купить", "продать", "разгон",
    "b", "balance", "bal", "bonus", "bank", "farm", "collect", "extract", "claim", "inventory",
    "market", "trade", "donate", "buy", "sell", "overclock", "withdraw", "take"
}

GAME_TRIGGERS = {
    "п", "колесо", "гоу", "мины", "рулетка", "гонка", "бомба", "авиация", "авто", "сектор",
    "p", "wheel", "go", "mines", "roulette", "race", "races", "bomb", "aviation", "crash", "auto", "sector"
}

# Кланы теперь робят на обоих языках без сучка
CLAN_TRIGGERS = {
    "создать", "клан", "вступить", "взнос", "покинуть", "империя", "+зам", "-зам", "передать", "🏴‍☠️ кланы",
    "create", "clan", "clans", "join", "contribute", "leave", "empire", "🏴‍☠️ clans"
}

UI_TRIGGERS = {
    "профиль", "👤 профиль", "🎁 бонус", "🏭 ферма", "🏦 банк", "💎 донат", "🌐 чаты", 
    "комьюнити", "📜 квесты", "задания", "миссии", "📚 инструктаж", "инструктаж", 
    "события", "лог", "бан", "мой", "топ", "титулы", "титул", "мои титулы", 
    "отменить трейд", "история трейдов", "глобал трейды", "чаты", "чат", "общение", 
    "магазин титулов", "вещание",
    "profile", "👤 profile", "🎁 bonus", "🏭 farm", "🏦 bank", "💎 donate", "🌐 channels", "🌐 chats",
    "community", "📜 quests", "quests", "missions", "📚 briefing", "briefing",
    "events", "logs", "log", "ban", "my", "top", "titles", "title", "my titles",
    "cancel trade", "trade history", "global trades", "chats", "chat", "title shop", "broadcast"
}

# Автоматически объединяем все домены в единый белый список для мидлварей
INTERACTION_TRIGGERS = ECONOMY_TRIGGERS | GAME_TRIGGERS | CLAN_TRIGGERS | UI_TRIGGERS

def register_triggers(*args):
    """
    Динамический регистратор. Любой новый модуль (например, крипта) 
    при вызове этой функции сам допишет свои команды в общий список.
    """
    for trigger in args:
        INTERACTION_TRIGGERS.add(trigger.lower().strip())