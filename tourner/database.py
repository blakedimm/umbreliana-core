import asyncpg
import os
import re
import time
import logging

logger = logging.getLogger("TourneyDB")
logging.basicConfig(level=logging.INFO)

# Используем отдельную базу для турнира, если нужно, или просто bot_database
DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:asddsa123@localhost:5432/tourney_db")
db_pool = None

async def get_db():
    """Инициализация и получение пула соединений БД"""
    global db_pool
    if db_pool is None:
        db_pool = await asyncpg.create_pool(
            DB_URL, 
            min_size=5, 
            max_size=30,
            command_timeout=60.0,
            max_inactive_connection_lifetime=300.0,
            max_queries=5000 
        )
    return db_pool

def _extract_number(val):
    nums = re.findall(r'\d+', str(val))
    return nums[0] if nums else str(val)

async def optimize_postgres_server():
    """Автоматическая умная настройка ядра PostgreSQL"""
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            configs = {
                "shared_buffers": "3GB",
                "effective_cache_size": "8GB",
                "work_mem": "32MB",
                "maintenance_work_mem": "512MB",
                "random_page_cost": "1.1",
                "effective_io_concurrency": "200",
                "synchronous_commit": "off",
                "wal_buffers": "16MB"
            }
            
            changes_made = False
            for param, target_value in configs.items():
                current_val = await db.fetchval(f"SHOW {param};")
                if _extract_number(current_val) != _extract_number(target_value):
                    await db.execute(f"ALTER SYSTEM SET {param} = '{target_value}';")
                    changes_made = True

            if changes_made:
                await db.execute("SELECT pg_reload_conf();")
                print("🚀 PostgreSQL: Применены новые оптимизированные настройки!")
    except Exception as e:
        print(f"⚠️ Ошибка умной настройки ALTER SYSTEM: {e}")

async def init_db():
    """Спартанская инициализация базы данных для Турнира"""
    try:
        await optimize_postgres_server()
        pool = await get_db()
        async with pool.acquire() as db:
            # 1. ТАБЛИЦА USERS (Максимально облегченная)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    balance BIGINT DEFAULT 0, 
                    nickname TEXT,
                    telegram_username TEXT,
                    first_seen BIGINT DEFAULT 0, 
                    last_seen BIGINT DEFAULT 0
                )
            ''')
            
            # 2. ТАБЛИЦА ИСТОРИИ РУЛЕТКИ
            await db.execute('''CREATE TABLE IF NOT EXISTS roulette_log (id SERIAL PRIMARY KEY, result TEXT, timestamp BIGINT)''')
            
            # 3. ТАБЛИЦА ФЕРМ
            await db.execute('''
                CREATE TABLE IF NOT EXISTS farms (
                    user_id BIGINT PRIMARY KEY,
                    last_collect BIGINT DEFAULT 0,
                    cooling_level INTEGER DEFAULT 1,
                    last_wear_update BIGINT DEFAULT 0
                )
            ''')
            
            # 4. ТАБЛИЦА УЧАСТНИКОВ ЧАТА (Для локального топа)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS chat_members (
                    chat_id BIGINT,
                    user_id BIGINT,
                    PRIMARY KEY (chat_id, user_id)
                )
            ''')

            # 5. ТАБЛИЦА ТЕНЕВОГО РЫНКА
            await db.execute('''
                CREATE TABLE IF NOT EXISTS market (
                    id SERIAL PRIMARY KEY,
                    seller_id BIGINT,
                    gpu_id TEXT,
                    price BIGINT,
                    qty INTEGER DEFAULT 1,
                    condition DOUBLE PRECISION DEFAULT 100.0,
                    created_at BIGINT,
                    deposit BIGINT DEFAULT 0
                )
            ''')
            
            # 6. ТАБЛИЦА ПАРТИЙ ВИДЕОКАРТ
            await db.execute('''
                CREATE TABLE IF NOT EXISTS gpu_batches (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    gpu_id TEXT,
                    multiplier DOUBLE PRECISION DEFAULT 1.0,
                    qty INTEGER DEFAULT 1,
                    condition DOUBLE PRECISION DEFAULT 100.0,
                    was_repaired INTEGER DEFAULT 0
                )
            ''')

            # === ИНДЕКСЫ ДЛЯ УСКОРЕНИЯ ЗАПРОСОВ ===
            await db.execute('CREATE INDEX IF NOT EXISTS idx_users_balance ON users(balance DESC);')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_market_gpu ON market(gpu_id);')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_batches_user_gpu ON gpu_batches(user_id, gpu_id);')
        
        await add_missing_columns_safe()

    except Exception as e:
        print(f"❌ Ошибка при инициализации БД: {e}")

async def check_table_structure():
    pool = await get_db()
    async with pool.acquire() as db:
        await db.fetch("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'users'")

async def add_missing_columns_safe():
    """Добавляет только нужные турнирным механикам колонки"""
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            # 🔥 ФЛАГ БОНУСА (то, что мы добавляли)
            try:
                await db.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS received_bonus BOOLEAN DEFAULT FALSE')
            except Exception: 
                pass

            # 🔥 ФЛАГ ПОЖИЗНЕННОГО ИСКЛЮЧЕНИЯ С ТУРНИРА
            try:
                await db.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned BOOLEAN DEFAULT FALSE')
            except Exception: pass
            
            # Колонки для ферм (Ошибка была здесь или рядом)
            try:
                await db.execute('ALTER TABLE farms ADD COLUMN IF NOT EXISTS cooling_level INTEGER DEFAULT 1')
                await db.execute('ALTER TABLE farms ADD COLUMN IF NOT EXISTS last_wear_update BIGINT DEFAULT 0')
                for i in range(1, 31):
                    await db.execute(f'ALTER TABLE farms ADD COLUMN IF NOT EXISTS gpu_{i} INTEGER DEFAULT 0')
            except Exception: 
                pass

            # Колонки для рынка
            try:
                await db.execute('ALTER TABLE market ADD COLUMN IF NOT EXISTS qty INTEGER DEFAULT 1')
                await db.execute('ALTER TABLE market ADD COLUMN IF NOT EXISTS condition DOUBLE PRECISION DEFAULT 100.0')
                await db.execute('ALTER TABLE market ADD COLUMN IF NOT EXISTS deposit BIGINT DEFAULT 0')
            except Exception: 
                pass

            # Колонки для партий
            try:
                await db.execute('ALTER TABLE gpu_batches ADD COLUMN IF NOT EXISTS was_repaired INTEGER DEFAULT 0')
            except Exception: 
                pass

    except Exception as e:
        print(f"❌ Ошибка в add_missing_columns_safe: {e}")

# ==========================================
# ФУНКЦИИ ДЛЯ БАЛАНСА И ЮЗЕРОВ
# ==========================================
async def get_user_data(user_id):
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            row = await db.fetchrow('SELECT * FROM users WHERE user_id = $1', user_id)
            if row: return dict(row)
            else:
                await db.execute('''
                    INSERT INTO users (user_id, balance, first_seen, last_seen)
                    VALUES ($1, $2, $3, $4)
                ''', user_id, 0, int(time.time()), int(time.time()))
                new_row = await db.fetchrow('SELECT * FROM users WHERE user_id = $1', user_id)
                return dict(new_row) if new_row else None
    except Exception as e:
        print(f"❌ Ошибка в get_user_data: {e}")
        return None

async def get_balance(user_id):
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            result = await db.fetchval('SELECT balance FROM users WHERE user_id = $1', user_id)
            if result is not None:
                return result
            else:
                await db.execute('''
                    INSERT INTO users (user_id, balance, first_seen, last_seen)
                    VALUES ($1, $2, $3, $4)
                ''', user_id, 0, int(time.time()), int(time.time()))
                return 0
    except Exception as e:
        print(f"❌ Ошибка в get_balance: {e}")
        return 0

async def add_balance(user_id: int, amount: float, name: str = None, is_income: bool = False) -> bool:
    # Жесткий предохранитель базы от переполнения
    MAX_BIGINT = 9_000_000_000_000_000_000
    if amount > MAX_BIGINT: amount = MAX_BIGINT
    if amount < -MAX_BIGINT: amount = -MAX_BIGINT
    
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            async with db.transaction(): 
                is_new_user = await db.fetchval("SELECT 1 FROM users WHERE user_id = $1", user_id) is None
                current_time = int(time.time())
                
                await db.fetchval("""
                    INSERT INTO users (user_id, balance, nickname, first_seen, last_seen)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT(user_id) DO UPDATE SET
                        balance = GREATEST(users.balance + $6, 0),
                        last_seen = EXCLUDED.last_seen,
                        nickname = COALESCE(users.nickname, $7)
                    RETURNING balance
                """, user_id, amount, name, current_time, current_time, amount, name)
                
                return is_new_user 
                
    except Exception as e:
        logging.exception(f"❌ КРИТИЧЕСКАЯ ОШИБКА В add_balance (ID: {user_id}, Сумма: {amount})")
        return False

async def update_username(user_id, username):
    if not username: return
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute("UPDATE users SET telegram_username = $1 WHERE user_id = $2", username.lower(), user_id)

async def resolve_user_id(target_str):
    if not target_str: 
        return None
    target_str = str(target_str).strip()
    if target_str.isdigit():
        return int(target_str)
        
    username = target_str.replace('@', '').lower()
    pool = await get_db()
    async with pool.acquire() as db:
        return await db.fetchval(
            "SELECT user_id FROM users WHERE LOWER(telegram_username) = $1", 
            username
        )

# ==========================================
# ТОПЫ (Адаптировано под турнир)
# ==========================================
ADMIN_ID = int(os.getenv("ADMIN_ID", 1412940726))

async def get_top_10_local(chat_id):
    pool = await get_db()
    async with pool.acquire() as db:
        rows = await db.fetch("""
            SELECT u.user_id, u.balance, u.nickname 
            FROM users u
            JOIN chat_members cm ON u.user_id = cm.user_id
            WHERE cm.chat_id = $1 AND u.user_id != $2
            ORDER BY u.balance DESC 
            LIMIT 10
        """, chat_id, ADMIN_ID)
        return rows

async def get_top_10_global():
    pool = await get_db()
    async with pool.acquire() as db:
        return await db.fetch("SELECT user_id, balance, nickname FROM users WHERE user_id != $1 ORDER BY balance DESC LIMIT 10", ADMIN_ID)

# ==========================================
# ФЕРМЫ (Ядро оборудования)
# ==========================================
async def get_farm(user_id):
    pool = await get_db()
    async with pool.acquire() as db:
        row = await db.fetchrow('SELECT * FROM farms WHERE user_id = $1', user_id)
        if row:
            return dict(row)
        else:
            current_time = int(time.time())
            await db.execute('INSERT INTO farms (user_id, last_collect) VALUES ($1, $2)', user_id, current_time)
            return {'user_id': user_id, 'last_collect': current_time}

async def update_farm(user_id, **kwargs):
    if not kwargs: return
    pool = await get_db()
    async with pool.acquire() as db:
        columns = []
        values = []
        for i, (k, v) in enumerate(kwargs.items(), start=1):
            columns.append(f"{k} = ${i}")
            values.append(v)
        query = f"UPDATE farms SET {', '.join(columns)} WHERE user_id = ${len(values) + 1}"
        values.append(user_id)
        await db.execute(query, *values)

async def get_gpu_batches(user_id, gpu_id, total_owned):
    pool = await get_db()
    async with pool.acquire() as db:
        rows = await db.fetch("SELECT multiplier, qty, condition FROM gpu_batches WHERE user_id = $1 AND gpu_id = $2 AND qty > 0", user_id, gpu_id)

    batches_list = []
    remaining_qty = total_owned
    
    sorted_rows = sorted([dict(r) for r in rows], key=lambda x: (x['multiplier'], x['condition']), reverse=True)

    for row in sorted_rows:
        mult, qty, cond = row['multiplier'], row['qty'], row['condition']
        if remaining_qty <= 0: break
        actual_qty = min(qty, remaining_qty)
        batches_list.append({"mult": mult, "qty": actual_qty, "cond": cond})
        remaining_qty -= actual_qty
        
    if remaining_qty > 0:
        batches_list.append({"mult": 1.0, "qty": remaining_qty, "cond": 100.0})
            
    return batches_list

async def move_gpu_batch(user_id, gpu_id, source_mult, target_mult, qty, source_cond=100.0):
    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            row1 = await db.fetchrow("SELECT qty FROM gpu_batches WHERE user_id = $1 AND gpu_id = $2 AND multiplier = $3 AND abs(condition - $4) < 0.2", user_id, gpu_id, source_mult, source_cond)
            if row1:
                await db.execute("UPDATE gpu_batches SET qty = GREATEST(0, qty - $1) WHERE user_id = $2 AND gpu_id = $3 AND multiplier = $4 AND abs(condition - $5) < 0.2", qty, user_id, gpu_id, source_mult, source_cond)

            row2 = await db.fetchrow("SELECT qty FROM gpu_batches WHERE user_id = $1 AND gpu_id = $2 AND multiplier = $3 AND abs(condition - $4) < 0.2", user_id, gpu_id, target_mult, source_cond)
            if row2:
                await db.execute("UPDATE gpu_batches SET qty = qty + $1 WHERE user_id = $2 AND gpu_id = $3 AND multiplier = $4 AND abs(condition - $5) < 0.2", qty, user_id, gpu_id, target_mult, source_cond)
            else:
                await db.execute("INSERT INTO gpu_batches (user_id, gpu_id, multiplier, qty, condition) VALUES ($1, $2, $3, $4, $5)", user_id, gpu_id, target_mult, qty, source_cond)

# ==========================================
# УТИЛИТЫ ДЛЯ АДМИН-ПАНЕЛИ
# ==========================================
async def update_user(user_id, **kwargs):
    """Универсальная функция для изменения любых данных юзера (баланс, бан и т.д.)"""
    if not kwargs: return
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            columns = []
            values = []
            for i, (k, v) in enumerate(kwargs.items(), start=1):
                columns.append(f"{k} = ${i}")
                values.append(v)
            query = f"UPDATE users SET {', '.join(columns)} WHERE user_id = ${len(values) + 1}"
            values.append(user_id)
            await db.execute(query, *values)
    except Exception as e:
        print(f"❌ Ошибка в update_user: {e}")