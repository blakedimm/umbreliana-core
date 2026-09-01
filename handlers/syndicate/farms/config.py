import logging
from PIL import ImageFont
from core.database import get_db

def fmt(num):
    return f"{int(num):,}".replace(",", " ")

# ==========================================
# 📊 КОНФИГ МАГАЗИНА, ОХЛАЖДЕНИЯ И СТОЕК
# ==========================================
GPUS = {
    1: {"name": "Intel GMA 4500", "price": 15_000, "income": 130, "heat": 1, "power": 30, "emoji": "💻"},
    2: {"name": "NVIDIA GT 1030", "price": 30_000, "income": 250, "heat": 2, "power": 60, "emoji": "🖥️"},
    3: {"name": "NVIDIA GTX 750 Ti", "price": 55_000, "income": 440, "heat": 4, "power": 120, "emoji": "🖥️"},
    4: {"name": "AMD RX 580 8Gb", "price": 140_000, "income": 1_100, "heat": 15, "power": 350, "emoji": "🪫"},
    5: {"name": "NVIDIA GTX 1060 6Gb", "price": 220_000, "income": 1_650, "heat": 12, "power": 550, "emoji": "🔋"},
    6: {"name": "NVIDIA RTX 2060 6Gb", "price": 430_000, "income": 3_100, "heat": 18, "power": 1_100, "emoji": "⚡️"},
    7: {"name": "NVIDIA RTX 3050 8Gb", "price": 640_000, "income": 4_500, "heat": 16, "power": 1_600, "emoji": "⚡️"},
    8: {"name": "NVIDIA RTX 3060 12Gb", "price": 1_000_000, "income": 6_800, "heat": 22, "power": 2_600, "emoji": "🕹️"},
    9: {"name": "AMD RX 6700 XT 12Gb", "price": 2_200_000, "income": 14_500, "heat": 26, "power": 5_200, "emoji": "🔴"},
    10: {"name": "NVIDIA RTX 5060 Ti 16Gb", "price": 3_800_000, "income": 24_000, "heat": 24, "power": 8_500, "emoji": "🔥"},
    11: {"name": "NVIDIA RTX 4070 12Gb", "price": 5_500_000, "income": 34_000, "heat": 30, "power": 12_500, "emoji": "☄️"},
    12: {"name": "NVIDIA RTX 5070 12Gb", "price": 9_000_000, "income": 54_000, "heat": 32, "power": 21_000, "emoji": "🚀"},
    13: {"name": "AMD RX 7900 XTX 24Gb", "price": 13_500_000, "income": 78_000, "heat": 48, "power": 36_000, "emoji": "🔴"},
    21: {"name": "NVIDIA RTX 4090 24Gb", "price": 20_000_000, "income": 112_000, "heat": 52, "power": 56_000, "emoji": "🔥"},
    14: {"name": "NVIDIA RTX 5090 32Gb", "price": 28_300_000, "income": 155_000, "heat": 65, "power": 82_000, "emoji": "☢️"},
    15: {"name": "NVIDIA A100 80Gb", "price": 55_000_000, "income": 290_000, "heat": 85, "power": 155_000, "emoji": "🧠"},
    16: {"name": "NVIDIA RTX 6000 Ada", "price": 90_000_000, "income": 460_000, "heat": 105, "power": 260_000, "emoji": "💎"},
    17: {"name": "NVIDIA H100 80Gb", "price": 140_000_000, "income": 680_000, "heat": 125, "power": 460_000, "emoji": "🧠"},
    18: {"name": "ASIC Antminer S21", "price": 250_000_000, "income": 1_150_000, "heat": 260, "power": 820_000, "emoji": "🕋"},
    19: {"name": "NVIDIA B200", "price": 400_000_000, "income": 1_800_000, "heat": 320, "power": 1_550_000, "emoji": "🌀"},
    20: {"name": "Квантовый компьютер", "price": 1_500_000_000, "income": 6_500_000, "heat": 1050, "power": 5_200_000, "emoji": "🌌"}
}

GOLDEN_GPUS = {}
for i, gpu in list(GPUS.items()):
    gold_name = f"✨ Золотой {gpu['name']}" if "Квантовый" in gpu['name'] or "ASIC" in gpu['name'] else f"✨ Золотая {gpu['name']}"
    gold_name_en = f"✨ Golden {gpu['name']}"
    GOLDEN_GPUS[i + 100] = {
        "name": gold_name, 
        "name_en": gold_name_en, # Динамический ключ для отображения на английском узле
        "price": int(gpu['price'] * 0.8), 
        "income": int(gpu['income'] * 1.2),
        "heat": gpu['heat'], 
        "power": gpu['power'], 
        "emoji": "🌟"
    }
GPUS.update(GOLDEN_GPUS)

# Добавлены lang_key для полной интернационализации названий модулей
COOLING = {
    1: {"name": "Балкон зимой", "lang_key": "cl_tier_1", "price": 0, "capacity": 50, "emoji": "🌬"},
    2: {"name": "Обычные вентиляторы", "lang_key": "cl_tier_2", "price": 1_500_000, "capacity": 200, "emoji": "💨"},
    3: {"name": "Кондиционер", "lang_key": "cl_tier_3", "price": 15_000_000, "capacity": 800, "emoji": "❄️"},
    4: {"name": "Промышленная вытяжка", "lang_key": "cl_tier_4", "price": 75_000_000, "capacity": 3000, "emoji": "🌪"},
    5: {"name": "Дата-центр", "lang_key": "cl_tier_5", "price": 650_000_000, "capacity": 15000, "emoji": "🏢"},
    6: {"name": "Криокамера", "lang_key": "cl_tier_6", "price": 7_500_000_000, "capacity": 150_000, "emoji": "🧊"},
    7: {"name": "Жидкий азот", "lang_key": "cl_tier_7", "price": 35_000_000_000, "capacity": 800_000, "emoji": "🧪"},
    8: {"name": "Подводный сервер", "lang_key": "cl_tier_8", "price": 200_000_000_000, "capacity": 5_000_000, "emoji": "🌊"},
    9: {"name": "Орбитальная станция", "lang_key": "cl_tier_9", "price": 950_000_000_000, "capacity": 25_000_000, "emoji": "🛰"},
    10: {"name": "Абсолютный ноль", "lang_key": "cl_tier_10", "price": 6_000_000_000_000, "capacity": 150_000_000, "emoji": "🌌"}
}

# Добавлены lang_key для полной интернационализации названий стоек
SLOTS_UPGRADES = {
    1: {"name": "Базовая стойка", "lang_key": "rk_tier_1", "price": 0, "capacity": 30, "emoji": "📦"},
    2: {"name": "Железный каркас", "lang_key": "rk_tier_2", "price": 1_000_000, "capacity": 60, "emoji": "🪜"},
    3: {"name": "Усиленная серверная", "lang_key": "rk_tier_3", "price": 8_500_000, "capacity": 120, "emoji": "🗄️"},
    4: {"name": "Фирменный шкаф", "lang_key": "rk_tier_4", "price": 35_000_000, "capacity": 250, "emoji": "🚪"},
    5: {"name": "Промышленная стойка", "lang_key": "rk_tier_5", "price": 180_000_000, "capacity": 500, "emoji": "🏭"},
    6: {"name": "Магистральный узел", "lang_key": "rk_tier_6", "price": 950_000_000, "capacity": 750, "emoji": "🌐"},
    7: {"name": "Ангар Синдиката", "lang_key": "rk_tier_7", "price": 5_000_000_000, "capacity": 1000, "emoji": "🌌"}
}

MAX_STORAGE_HOURS = 4
ELECTRICITY_PRICE = 0.25

# ==========================================
# 🎨 ШРИФТЫ
# ==========================================
try:
    FARM_FONT_TITLE = ImageFont.truetype("assets/fonts/Montserrat-Regular.ttf", 32)
    FARM_FONT_LARGE = ImageFont.truetype("assets/fonts/Montserrat-Regular.ttf", 46)
    FARM_FONT_TEXT = ImageFont.truetype("assets/fonts/Montserrat-Light.ttf", 20)
    FARM_FONT_STATUS = ImageFont.truetype("assets/fonts/Montserrat-Regular.ttf", 28)
except Exception as e:
    logging.warning(f"Шрифты фермы не загружены, используем дефолтные: {e}")
    FARM_FONT_TITLE = ImageFont.truetype("arial.ttf", 32)
    FARM_FONT_LARGE = ImageFont.truetype("arial.ttf", 46)
    FARM_FONT_TEXT = ImageFont.truetype("arial.ttf", 20)
    FARM_FONT_STATUS = ImageFont.truetype("arial.ttf", 28)

def get_tax_rate(income_per_hour):
    if income_per_hour < 50000: return 0.05
    elif income_per_hour < 150000: return 0.12
    elif income_per_hour < 400000: return 0.25
    elif income_per_hour < 1000000: return 0.40
    else: return 0.55

# Обновляем авто-миграцию в config.py / структуре
async def add_golden_columns():
    pool = await get_db()
    async with pool.acquire() as db:
        try:
            await db.execute("ALTER TABLE farms ADD COLUMN IF NOT EXISTS slots_level INTEGER DEFAULT 1")
            await db.execute("ALTER TABLE farms ADD COLUMN IF NOT EXISTS max_slots INTEGER DEFAULT 30")
            # 🔥 НОВАЯ КОЛОНКА ДЛЯ КРИПТОВАЛЮТЫ UMC
            await db.execute("ALTER TABLE farms ADD COLUMN IF NOT EXISTS umc_balance NUMERIC DEFAULT 0.0")
        except Exception as e:
            logging.error(f"Ошибка миграции БД для стоек и крипты: {e}")

        # Миграция золотых видеокарт
        for i in GOLDEN_GPUS.keys():
            try: 
                await db.execute(f"ALTER TABLE farms ADD COLUMN IF NOT EXISTS gpu_{i} INTEGER DEFAULT 0")
            except Exception: 
                pass