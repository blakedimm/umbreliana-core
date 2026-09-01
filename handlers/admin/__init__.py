from aiogram import Router

# Импортируем роутеры из наших новых модулей
from .panel import router as panel_router
from .system_ops import router as system_router
from .economy_ops import router as economy_router
from .justice_ops import router as justice_router
from .farm_ops import router as farm_router
from .eye_of_god import router as eye_router # Твой глаз бога

# Экспортируем мидлварь, чтобы gram.py мог её импортировать
from .system_ops import ModuleStatusMiddleware, SYSTEM_MODULES

router = Router()

# Подключаем всё в единый админ-роутер. 
# ВАЖНО: panel_router подключаем последним, так как там ловцы стейтов FSM.
router.include_routers(
    system_router, 
    economy_router, 
    justice_router, 
    farm_router, 
    panel_router
)