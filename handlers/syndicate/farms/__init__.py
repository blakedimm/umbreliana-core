from aiogram import Router
from .menu import router as menu_router
from .shop import router as shop_router
from .inventory import router as inventory_router
from .overclock import router as overclock_router

farm_router = Router()
farm_router.include_router(menu_router)
farm_router.include_router(shop_router)
farm_router.include_router(inventory_router)
farm_router.include_router(overclock_router)

# 🔥 ЭКСПОРТИРУЕМ ВСЁ ДЛЯ ВНЕШНИХ МОДУЛЕЙ (АДМИНКА, РАДАР, ДЕПОЗИТЫ) 🔥
from .config import (
    GPUS, GOLDEN_GPUS, COOLING, 
    MAX_STORAGE_HOURS, ELECTRICITY_PRICE, 
    get_tax_rate, fmt, add_golden_columns
)
from .engine import calculate_farm_state, sync_farm_passive, perform_collection
from .menu import send_farm_menu

# 👇 ДОБАВЛЯЕМ ЭТИ СТРОЧКИ, ЧТОБЫ РАДАР ВИДЕЛ ФУНКЦИИ БАЗЫ ЧЕРЕЗ ЭТОТ МОДУЛЬ
from core.database import get_farm, update_farm