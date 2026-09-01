import pytest
import asyncio
import os
import sys

# 1. Добавляем путь к корню
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# 2. ЖЕСТКО ЗАДАЕМ АДРЕС БАЗЫ (Заменяем localhost на IP ноутбука)
# Это заставит Python использовать этот адрес ИГНОРИРУЯ всё остальное
os.environ['DATABASE_URL'] = "postgresql://postgres:asddsa123@26.16.170.114:5432/bot_database"

# 3. Теперь импортируем базу
from core.database import (
    init_db, get_db, get_balance, add_balance, 
    get_user_data, update_user, analyze_player_strategy, DB_URL
)

print(f"\n🚀 КОННОР: СИЛОВОЙ ЗАПУСК! ПОДКЛЮЧАЕМСЯ К: {DB_URL}")

# Выбираем ID, которого точно нет у реальных игроков
TEST_USER_ID = 777666555444

# Эта настройка говорит pytest, что мы используем асинхронность
pytestmark = pytest.mark.asyncio

async def setup_db():
    """Служебная функция: инициализирует БД перед тестами"""
    await init_db()

async def teardown_db():
    """Служебная функция: удаляет тестового юзера после тестов, чтобы не мусорить в БД"""
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute("DELETE FROM users WHERE user_id = $1", TEST_USER_ID)
        await db.execute("DELETE FROM audit_log WHERE user_id = $1", TEST_USER_ID)

async def test_database_functions():
    """Главный интеграционный тест для проверки Ядра"""
    
    # 1. Подключаемся к БД
    await setup_db()
    
    try:
        # 2. Тестируем создание юзера и базовый баланс
        initial_balance = await get_balance(TEST_USER_ID)
        assert initial_balance == 0, "Новый пользователь должен иметь 0 на балансе"
        
        # 3. Тестируем начисление денег (add_balance)
        success = await add_balance(TEST_USER_ID, 50000, name="TestAgent", is_income=True)
        assert success is not None, "Функция add_balance вернула ошибку"
        
        # 4. Проверяем, что деньги реально дошли
        new_balance = await get_balance(TEST_USER_ID)
        # Тест пройдет и на 60к (новый юзер) и на 50к (если юзер уже был в базе)
        assert new_balance in [50000, 60000], f"Ошибка! Баланс {new_balance} не совпадает с ожидаемым"
        
        # 5. Тестируем изменение данных (update_user)
        await update_user(TEST_USER_ID, debt=15000)
        user_data = await get_user_data(TEST_USER_ID)
        assert user_data['debt'] == 15000, "Долг не обновился в БД"
        
        # 6. Тестируем ИИ-Аудит (analyze_player_strategy)
        score, verdict = await analyze_player_strategy(TEST_USER_ID)
        assert "непогашенный долг" in verdict, "Аудитор не заметил долг тестового юзера!"
        
        print("\n✅ ВСЕ ЯДЕРНЫЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!")
        
    finally:
        # 7. Заметаем следы (удаляем тестового юзера)
        await teardown_db()