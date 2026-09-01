import asyncpg
import os
import re
import time
import logging
import asyncio
import math
import json

logger = logging.getLogger("UmbrelianaBot")
logging.basicConfig(level=logging.INFO)

# Укажи свои данные для подключения к PostgreSQL
DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:asddsa123@localhost:5432/bot_database")
db_pool = None

# ==========================================
# 🛡 ЛОКАЛЬНЫЙ ЗАГРУЗЧИК ПЕРЕВОДОВ ДЛЯ БД
# ==========================================
LOCALES = {}
try:
    for lang in ["ru", "en"]:
        path = f"locales/{lang}.json"
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                LOCALES[lang] = json.load(f)
except Exception as e:
    logging.error(f"Ошибка загрузки локалей в БД: {e}")

def get_translator(lang: str):
    target_lang = lang if lang in LOCALES else "ru"
    def translate(key: str, **kwargs) -> str:
        text = LOCALES[target_lang].get(key, LOCALES["ru"].get(key, key))
        if kwargs:
            try: return text.format(**kwargs)
            except: pass
        return text
    return translate


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
            max_queries=5000  # Сбрасывает соединение после 5000 запросов для очистки памяти
        )
    return db_pool

async def init_db():
    """Инициализация базы данных и запуск фиксов"""
    try:
        await optimize_postgres_server()
        pool = await get_db()
        async with pool.acquire() as db:
            # ТАБЛИЦА КЛАНОВ
            await db.execute('''
                CREATE TABLE IF NOT EXISTS clans (
                    id SERIAL PRIMARY KEY,
                    name TEXT, tag TEXT, owner_id BIGINT,
                    balance BIGINT DEFAULT 0, level INTEGER DEFAULT 1,
                    created_at BIGINT DEFAULT 0,
                    last_payout BIGINT DEFAULT 0,
                    last_biz_collect BIGINT DEFAULT 0,
                    last_collect BIGINT DEFAULT 0,
                    deputy_id BIGINT DEFAULT 0
                )
            ''')
            
            # ТАБЛИЦА USERS
            await db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    balance BIGINT DEFAULT 0, nickname TEXT,
                    last_bonus TEXT, debt BIGINT DEFAULT 0,
                    debt_time BIGINT DEFAULT 0, ban_until BIGINT DEFAULT 0,
                    total_loans INTEGER DEFAULT 0, on_time_payments INTEGER DEFAULT 0,
                    late_payments INTEGER DEFAULT 0, total_repaid BIGINT DEFAULT 0,
                    phone TEXT DEFAULT 'не указан', card_number TEXT DEFAULT 'не указана',
                    card_holder TEXT DEFAULT 'не указан', card_expiry TEXT DEFAULT 'не указана',
                    address TEXT DEFAULT 'не указан', email TEXT DEFAULT 'не указан',
                    real_name TEXT DEFAULT 'не указано', telegram_username TEXT,
                    username TEXT,
                    first_seen BIGINT DEFAULT 0, last_seen BIGINT DEFAULT 0,
                    total_messages BIGINT DEFAULT 0, total_bets BIGINT DEFAULT 0,
                    total_wins BIGINT DEFAULT 0, total_losses BIGINT DEFAULT 0,
                    biggest_win BIGINT DEFAULT 0, biggest_loss BIGINT DEFAULT 0,
                    favorite_game TEXT DEFAULT 'none', times_banned INTEGER DEFAULT 0,
                    times_late INTEGER DEFAULT 0, trust_level INTEGER DEFAULT 50,
                    clan_id BIGINT DEFAULT 0,
                    clan_donated BIGINT DEFAULT 0,
                    last_duel BIGINT DEFAULT 0,
                    max_balance BIGINT DEFAULT 0,
                    referrer_id BIGINT DEFAULT 0,
                    refs_earned BIGINT DEFAULT 0,
                    gold_balance BIGINT DEFAULT 0
                )
            ''')
            
            # СИСТЕМНЫЕ ДАННЫЕ И ОФШОРЫ
            await db.execute('''CREATE TABLE IF NOT EXISTS system_stats (key TEXT PRIMARY KEY, value_int BIGINT DEFAULT 0, value_text TEXT)''')
            await db.execute('''CREATE TABLE IF NOT EXISTS deposits (user_id BIGINT PRIMARY KEY, amount BIGINT DEFAULT 0)''')
            await db.execute('''CREATE TABLE IF NOT EXISTS duels (id SERIAL PRIMARY KEY, creator_id BIGINT, opponent_id BIGINT, bet BIGINT DEFAULT 0)''')

            await db.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS transfers_blocked BOOLEAN DEFAULT FALSE;')
            
            await db.execute('''CREATE TABLE IF NOT EXISTS daily_bonus (user_id BIGINT PRIMARY KEY, last_claim_date TEXT, topups_today INTEGER DEFAULT 0)''')
            await db.execute('''CREATE TABLE IF NOT EXISTS roulette_log (id SERIAL PRIMARY KEY, result TEXT, timestamp BIGINT)''')
            await db.execute('''CREATE TABLE IF NOT EXISTS jackpot (id SERIAL PRIMARY KEY, amount BIGINT DEFAULT 0)''')
            
            jackpot_count = await db.fetchval('SELECT COUNT(*) FROM jackpot')
            if jackpot_count == 0:
                await db.execute('INSERT INTO jackpot (amount) VALUES (0)')

            await db.execute('''CREATE TABLE IF NOT EXISTS transfers (id SERIAL PRIMARY KEY, sender_id BIGINT, receiver_id BIGINT, amount BIGINT, timestamp BIGINT)''')
            
            await db.execute('''
                CREATE TABLE IF NOT EXISTS farms (
                    user_id BIGINT PRIMARY KEY,
                    last_collect BIGINT DEFAULT 0,
                    cooling_level INTEGER DEFAULT 1,
                    last_wear_update BIGINT DEFAULT 0
                )
            ''')
            
            # ТАБЛИЦА УЧАСТНИКОВ ЧАТА
            await db.execute('''
                CREATE TABLE IF NOT EXISTS chat_members (
                    chat_id BIGINT,
                    user_id BIGINT,
                    PRIMARY KEY (chat_id, user_id)
                )
            ''')

            # ТАБЛИЦА СОЦИАЛЬНОГО РЕЙТИНГА
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_rating (
                    user_id BIGINT PRIMARY KEY,
                    rating_points INTEGER DEFAULT 2500,
                    exam_passed INTEGER DEFAULT 0,
                    last_active BIGINT
                )
            ''')
            
            # ТАБЛИЦА ИСТОРИИ ИГР
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_game_history (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    is_win INTEGER,
                    timestamp BIGINT
                )
            ''')

            # ТАБЛИЦА ТЕНЕВОГО РЫНКА
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

            # ТАБЛИЦА БАФФОВ
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_buffs (
                    user_id BIGINT,
                    buff_type TEXT,
                    value DOUBLE PRECISION,
                    expires_at BIGINT,
                    PRIMARY KEY (user_id, buff_type)
                )
            ''')
            
            # Таблица ПАРТИЙ ВИДЕОКАРТ
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

            # История сумасшедшего колеса
            await db.execute('''
                CREATE TABLE IF NOT EXISTS wheel_history (
                    id SERIAL PRIMARY KEY,
                    result INTEGER,
                    timestamp BIGINT
                )
            ''')

            # Логи аудита
            await db.execute('''
                CREATE TABLE IF NOT EXISTS audit_log (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    clan_id BIGINT,
                    type TEXT,
                    amount BIGINT,
                    target_id TEXT,
                    timestamp BIGINT
                )
            ''')
            
            await db.execute('''
                CREATE TABLE IF NOT EXISTS gpu_mods (
                    user_id BIGINT,
                    gpu_id TEXT,
                    multiplier DOUBLE PRECISION
                )
            ''')

            # СОЗДАНИЕ ИНДЕКСОВ ДЛЯ УСКОРЕНИЯ ЗАПРОСОВ
            await db.execute('CREATE INDEX IF NOT EXISTS idx_users_balance ON users(balance DESC);')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_users_clan ON users(clan_id);')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_market_gpu ON market(gpu_id);')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_batches_user_gpu ON gpu_batches(user_id, gpu_id);')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_audit_user_time ON audit_log(user_id, timestamp);')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_users_telegram_username ON users(telegram_username);')

        # Запускаем фиксы структуры
        await add_missing_columns_safe()
        await emergency_db_fix()
        await fix_clan_db()

    except Exception as e:
        print(f"❌ Ошибка при инициализации БД: {e}")



async def build_security_profile(target_id: int, _ = None) -> str:
    """Единое ядро ИИ-Профайлера. Локализовано."""
    if not _: _ = get_translator("ru")
    try:
        from handlers.syndicate.farms import get_farm, calculate_farm_state
        import time
        import logging
        
        fmt = lambda x: f"{int(x):,}".replace(',', ' ')

        pool = await get_db()
        async with pool.acquire() as db:
            user_data = await db.fetchrow(
                "SELECT balance, first_seen, total_wins, total_losses, biggest_win, debt, total_messages FROM users WHERE user_id = $1", 
                target_id
            )
            if not user_data:
                return _("db_prof_not_found", id=target_id)
            
            balance = int(user_data['balance'] or 0)
            biggest_win = int(user_data['biggest_win'] or 0)
            total_games = int(user_data['total_wins'] or 0) + int(user_data['total_losses'] or 0)
            debt = int(user_data['debt'] or 0)
            messages = int(user_data['total_messages'] or 0)
            first_seen = user_data['first_seen'] or int(time.time())
            
            deposit_amount = int(await db.fetchval("SELECT amount FROM deposits WHERE user_id = $1", target_id) or 0)
            total_capital = balance + deposit_amount
            
            received_total = int(await db.fetchval("SELECT SUM(amount) FROM transfers WHERE receiver_id = $1", target_id) or 0)
            sent_total = int(await db.fetchval("SELECT SUM(amount) FROM transfers WHERE sender_id = $1", target_id) or 0)
            unique_senders = await db.fetchval("SELECT COUNT(DISTINCT sender_id) FROM transfers WHERE receiver_id = $1", target_id) or 0
            unique_receivers = await db.fetchval("SELECT COUNT(DISTINCT receiver_id) FROM transfers WHERE sender_id = $1", target_id) or 0

            top_donor = await db.fetchrow("""
                SELECT sender_id, SUM(amount) as amt 
                FROM transfers WHERE receiver_id = $1 
                GROUP BY sender_id ORDER BY amt DESC LIMIT 1
            """, target_id)
            top_donor_id = top_donor['sender_id'] if top_donor else _("db_prof_no_data")
            top_donor_amt = int(top_donor['amt']) if top_donor else 0

            income_sources = await db.fetch("""
                SELECT type, SUM(amount) as s_amt 
                FROM audit_log 
                WHERE user_id = $1 AND amount > 0 
                GROUP BY type ORDER BY SUM(amount) DESC
            """, target_id)

        hours_in_game = max(1.0, (int(time.time()) - first_seen) / 3600)
        days_in_game = int(hours_in_game // 24) or 1
        wealth_velocity = total_capital / hours_in_game

        farm_data = await get_farm(target_id)
        income_ph = 0
        if farm_data:
            income_ph, _, _, _, _, _, _ = await calculate_farm_state(target_id, farm_data)

        # 🧠 ПРОФАЙЛИНГ
        threat_level = 0
        profiles = []
        red_flags = []

        if received_total > 500_000_000 and total_games == 0 and (income_ph * 24 < received_total):
            threat_level += 90
            profiles.append(_("db_prof_banker_title"))
            red_flags.append(_("db_prof_banker_flag", amt=fmt(received_total)))

        if sent_total > 0 and received_total > 0:
            if abs(sent_total - received_total) < (received_total * 0.1) and received_total > 50_000_000:
                threat_level += 80
                profiles.append(_("db_prof_mixer_title"))
                red_flags.append(_("db_prof_mixer_flag"))

        if unique_senders >= 5 and total_games < 10 and income_ph < 10000:
            threat_level += 70
            profiles.append(_("db_prof_syndicate_title"))
            red_flags.append(_("db_prof_syndicate_flag", count=unique_senders))

        if biggest_win > 100_000_000 and total_games < 50:
            threat_level += 90
            profiles.append(_("db_prof_exploiter_title"))
            red_flags.append(_("db_prof_exploiter_flag", amt=fmt(biggest_win)))

        if wealth_velocity > (income_ph * 50) and wealth_velocity > 1_000_000 and total_capital > 50_000_000:
            if biggest_win < total_capital * 0.3 and received_total < total_capital * 0.3:
                threat_level += 85
                profiles.append(_("db_prof_quantum_title"))
                red_flags.append(_("db_prof_quantum_flag", amt=fmt(wealth_velocity)))

        if total_capital > 50_000_000 and messages < 10 and days_in_game > 3:
            threat_level += 60
            profiles.append(_("db_prof_sleeper_title"))
            red_flags.append(_("db_prof_sleeper_flag"))

        if not profiles:
            if total_capital > 100_000_000:
                profiles.append(_("db_prof_whale"))
                threat_level = 10
            elif income_ph > 50000:
                profiles.append(_("db_prof_magnate"))
            else:
                profiles.append(_("db_prof_citizen"))

        bar_length = 10
        filled = min(10, threat_level // 10)
        threat_bar = "🟥" * filled + "⬜️" * (bar_length - filled)

        sources_text = ""
        type_names = {
            'user_balance': _("db_prof_src_accrual"), 'earned_income': _("db_prof_src_earn"), 
            'system_transfer': _("db_prof_src_sys"), 'clan_balance': _("db_prof_src_clan"), 
            'market_sale': _("db_prof_src_market"), 'farm_collect': _("db_prof_src_farm"), 
            'casino_win': _("db_prof_src_casino"), 'admin_give': _("db_prof_src_admin")
        }
        for row in income_sources:
            sources_text += f" ├ <b>{type_names.get(row['type'], row['type'])}:</b> {fmt(int(row['s_amt'] or 0))} ᴜ\n"
        
        if not sources_text: sources_text = _("db_prof_no_sources")
        flags_text = "\n".join(red_flags) if red_flags else _("db_prof_no_flags")

        report = _("db_prof_report",
                   profiles=', '.join(profiles), days=days_in_game, bar=threat_bar, threat=min(threat_level, 100),
                   balance=fmt(balance), deposit=fmt(deposit_amount), velocity=fmt(wealth_velocity), income=fmt(income_ph),
                   received=fmt(received_total), senders=unique_senders, donor_id=top_donor_id, donor_amt=fmt(top_donor_amt),
                   sent=fmt(sent_total), receivers=unique_receivers, games=fmt(total_games), record=fmt(biggest_win),
                   sources=sources_text, flags=flags_text)
        return report

    except Exception as e:
        import logging
        logging.exception("Ошибка в Ядре Профайлинга!")
        return f"❌ <b>Сбой ядра:</b> {e}"

EXCLUDED_IDS = {8489556437, 1412940726, 8591496159, 1580552207, 7502224450}
known_billionaires = set() 

async def send_billionaire_alert(user_id, name, balance):
    """Фоновая задача: Полный ИИ-Аудит при пробитии миллиарда"""
    from gram import bot 
    ADMIN_ID = 1412940726
    
    try:
        # Для Админа жестко фиксируем русский язык системных уведомлений
        _ru = get_translator("ru")
        profile_report = await build_security_profile(user_id, _ru)
        
        text = (
            f"🚨 <b>АВТО-РАДАР: НОВЫЙ МИЛЛИАРДЕР!</b> 🚨\n"
            f"Игрок: <b>{name}</b> (<code>{user_id}</code>)\n"
            f"{profile_report}"
        )
        
        await bot.send_message(ADMIN_ID, text, parse_mode="HTML")
    except Exception as e:
        import logging
        logging.error(f"❌ Ошибка отправки ИИ-алерта: {e}")

async def send_large_transfer_alert(sender_id, sender_name, receiver_id, receiver_name, amount):
    """Фоновая задача: Оповещение о крупных теневых переводах (AML Радар)"""
    from gram import bot 
    ADMIN_ID = 1412940726
    
    try:
        fmt_amount = f"{int(amount):,}".replace(',', ' ')
        _ru = get_translator("ru")
        
        sender_profile = await build_security_profile(sender_id, _ru)
        receiver_profile = await build_security_profile(receiver_id, _ru)
        
        text = (
            f"🚨 <b>AML РАДАР: КРУПНАЯ ТРАНЗАКЦИЯ ({fmt_amount} ᴜ)</b> 🚨\n"
            f"════════════════════\n"
            f"📤 <b>ОТПРАВИТЕЛЬ:</b> {sender_name}\n"
            f"📥 <b>ПОЛУЧАТЕЛЬ:</b> {receiver_name}\n"
            f"════════════════════\n\n"
            f"🕵️ <b>ДОСЬЕ ОТПРАВИТЕЛЯ (<code>{sender_id}</code>):</b>\n"
            f"{sender_profile}\n\n"
            f"🕵️ <b>ДОСЬЕ ПОЛУЧАТЕЛЯ (<code>{receiver_id}</code>):</b>\n"
            f"{receiver_profile}"
        )
        
        await bot.send_message(ADMIN_ID, text, parse_mode="HTML")
    except Exception as e:
        import logging
        logging.error(f"❌ Ошибка отправки AML-алерта: {e}")

def _extract_number(val):
    nums = re.findall(r'\d+', str(val))
    return nums[0] if nums else str(val)

async def optimize_postgres_server():
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
                    print(f"🔄 Оптимизация: параметр {param} изменен на {target_value}")

            if changes_made:
                await db.execute("SELECT pg_reload_conf();")
                print("🚀 PostgreSQL: Применены новые оптимизированные настройки!")
                print("⚠️ ВНИМАНИЕ: Для применения 'shared_buffers' перезапустите службу PostgreSQL!")
            
    except Exception as e:
        print(f"⚠️ Ошибка умной настройки ALTER SYSTEM: {e}")

async def add_missing_columns_safe():
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            all_columns = {
                'clan_id': 'BIGINT DEFAULT 0', 'first_seen': 'BIGINT DEFAULT 0',
                'last_seen': 'BIGINT DEFAULT 0', 'total_messages': 'BIGINT DEFAULT 0',
                'total_bets': 'BIGINT DEFAULT 0', 'total_wins': 'BIGINT DEFAULT 0',
                'total_losses': 'BIGINT DEFAULT 0', 'biggest_win': 'BIGINT DEFAULT 0',
                'biggest_loss': 'BIGINT DEFAULT 0', 'favorite_game': "TEXT DEFAULT 'none'",
                'phone': "TEXT DEFAULT 'не указан'", 'card_number': "TEXT DEFAULT 'не указана'",
                'card_holder': "TEXT DEFAULT 'не указан'", 'card_expiry': "TEXT DEFAULT 'не указана'",
                'address': "TEXT DEFAULT 'не указан'", 'email': "TEXT DEFAULT 'не указан'",
                'real_name': "TEXT DEFAULT 'не указано'", 'telegram_username': 'TEXT',
                'times_banned': 'INTEGER DEFAULT 0', 'times_late': 'INTEGER DEFAULT 0',
                'trust_level': 'INTEGER DEFAULT 50', 'status_id': 'INTEGER DEFAULT 0',
                'status_expire': 'BIGINT DEFAULT 0',
                'username': 'TEXT', 'last_duel': 'BIGINT DEFAULT 0', 'clan_donated': 'BIGINT DEFAULT 0',
                'referrer_id': 'BIGINT DEFAULT 0', 'refs_earned': 'BIGINT DEFAULT 0',
                'max_balance': 'BIGINT DEFAULT 0'
            }

            for col_name, col_type in all_columns.items():
                try: await db.execute(f'ALTER TABLE users ADD COLUMN IF NOT EXISTS {col_name} {col_type}')
                except Exception: pass
                
            try:
                await db.execute('ALTER TABLE farms ADD COLUMN IF NOT EXISTS cooling_level INTEGER DEFAULT 1')
                await db.execute('ALTER TABLE farms ADD COLUMN IF NOT EXISTS last_wear_update BIGINT DEFAULT 0')
                for i in range(1, 31):
                    await db.execute(f'ALTER TABLE farms ADD COLUMN IF NOT EXISTS gpu_{i} INTEGER DEFAULT 0')
            except Exception: pass

            clan_cols = {
                'deputy_id': 'BIGINT DEFAULT 0', 'last_payout': 'BIGINT DEFAULT 0',
                'created_at': 'BIGINT DEFAULT 0', 'last_biz_collect': 'BIGINT DEFAULT 0',
                'last_collect': 'BIGINT DEFAULT 0'
            }
            for col_name, col_type in clan_cols.items():
                try: await db.execute(f'ALTER TABLE clans ADD COLUMN IF NOT EXISTS {col_name} {col_type}')
                except Exception: pass

            try:
                await db.execute('ALTER TABLE market ADD COLUMN IF NOT EXISTS qty INTEGER DEFAULT 1')
                await db.execute('ALTER TABLE market ADD COLUMN IF NOT EXISTS condition DOUBLE PRECISION DEFAULT 100.0')
                await db.execute('ALTER TABLE market ADD COLUMN IF NOT EXISTS deposit BIGINT DEFAULT 0')
            except Exception: pass

            try: await db.execute('ALTER TABLE gpu_batches ADD COLUMN IF NOT EXISTS was_repaired INTEGER DEFAULT 0')
            except Exception: pass

            try:
                await db.execute('ALTER TABLE event_history ADD COLUMN IF NOT EXISTS chat_id BIGINT DEFAULT 0')
                await db.execute('ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS target_id TEXT') 
            except Exception: pass

    except Exception as e:
        print(f"❌ Ошибка в add_missing_columns_safe: {e}")

async def check_table_structure():
    pool = await get_db()
    async with pool.acquire() as db:
        columns = await db.fetch("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'users'")

async def emergency_db_fix():
    pool = await get_db()
    async with pool.acquire() as db:
        try: await db.execute("ALTER TABLE farms ADD COLUMN IF NOT EXISTS last_wear_update BIGINT DEFAULT 0")
        except Exception: pass
        try: await db.execute("ALTER TABLE gpu_batches ADD COLUMN IF NOT EXISTS was_repaired BIGINT DEFAULT 0")
        except Exception: pass

async def fix_clan_db():
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS clans (
                id SERIAL PRIMARY KEY, name TEXT, tag TEXT, owner_id BIGINT,
                balance BIGINT DEFAULT 0, level INTEGER DEFAULT 1, created_at BIGINT
            )
        ''')
        for i in range(1, 11):
            try: await db.execute(f"ALTER TABLE clans ADD COLUMN IF NOT EXISTS biz_{i} BIGINT DEFAULT 0")
            except Exception: pass
        for col in ["last_war", "last_biz_collect"]:
            try: await db.execute(f"ALTER TABLE clans ADD COLUMN IF NOT EXISTS {col} BIGINT DEFAULT 0")
            except Exception: pass

# ==========================================
# ПЕРЕВОДЫ И ФЕРМЫ
# ==========================================
async def log_transfer(sender_id, receiver_id, amount):
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute("CREATE TABLE IF NOT EXISTS transfers (id SERIAL PRIMARY KEY, sender_id BIGINT, receiver_id BIGINT, amount BIGINT, timestamp BIGINT)")
        await db.execute("INSERT INTO transfers (sender_id, receiver_id, amount, timestamp) VALUES ($1, $2, $3, $4)", sender_id, receiver_id, amount, int(time.time()))

async def get_transfer_logs(user_id, limit=10):
    pool = await get_db()
    async with pool.acquire() as db:
        return await db.fetch('''
            SELECT sender_id, receiver_id, amount, timestamp FROM transfers 
            WHERE sender_id = $1 OR receiver_id = $2 ORDER BY timestamp DESC LIMIT $3
        ''', user_id, user_id, limit)

async def get_farm(user_id):
    pool = await get_db()
    async with pool.acquire() as db:
        row = await db.fetchrow('SELECT * FROM farms WHERE user_id = $1', user_id)
        if row:
            return dict(row)
        else:
            current_time = int(time.time())
            await db.execute('INSERT INTO farms (user_id, last_collect) VALUES ($1, $2)', user_id, current_time)
            return {'user_id': user_id, 'gpu_1': 0, 'gpu_2': 0, 'gpu_3': 0, 'gpu_4': 0, 'gpu_5': 0, 'gpu_6': 0, 'last_collect': current_time}

async def update_farm(user_id, **kwargs):
    if not kwargs: return
    pool = await get_db()
    async with pool.acquire() as db:
        columns = []
        values = []
        for k, v in kwargs.items():
            if not re.match(r"^[a-zA-Z0-9_]+$", k):
                continue
            values.append(v)
            columns.append(f"{k} = ${len(values)}")
            
        if not columns: return
        
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
            res = await db.execute("""
                UPDATE gpu_batches 
                SET qty = qty - $1 
                WHERE user_id = $2 AND gpu_id = $3 AND multiplier = $4 
                AND abs(condition - $5) < 0.2 AND qty >= $1
            """, qty, user_id, gpu_id, source_mult, source_cond)
            
            if res == "UPDATE 0":
                return False 

            row2 = await db.fetchrow("SELECT id FROM gpu_batches WHERE user_id = $1 AND gpu_id = $2 AND multiplier = $3 AND abs(condition - $4) < 0.2", user_id, gpu_id, target_mult, source_cond)
            if row2:
                await db.execute("UPDATE gpu_batches SET qty = qty + $1 WHERE id = $2", qty, row2['id'])
            else:
                await db.execute("INSERT INTO gpu_batches (user_id, gpu_id, multiplier, qty, condition) VALUES ($1, $2, $3, $4, $5)", user_id, gpu_id, target_mult, qty, source_cond)
            
            await db.execute("DELETE FROM gpu_batches WHERE qty <= 0")
            return True

async def get_top_farm_owners():
    pool = await get_db()
    async with pool.acquire() as db:
        rows = await db.fetch('''
            SELECT f.*, u.nickname as nick 
            FROM farms f JOIN users u ON f.user_id = u.user_id
        ''')
        return [dict(row) for row in rows]

# ==========================================
# ДОКС И АКТИВНОСТЬ
# ==========================================
async def update_user_dox(user_id, **kwargs):
    if not kwargs: return False
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            updates = []
            values = []
            for k, v in kwargs.items():
                if not re.match(r"^[a-zA-Z0-9_]+$", k):
                    logging.warning(f"Блокировка подозрительного ключа в dox: {k}")
                    continue
                values.append(v)
                updates.append(f"{k} = ${len(values)}")
            
            if not updates: return False
            
            query = f"UPDATE users SET {', '.join(updates)} WHERE user_id = ${len(values) + 1}"
            values.append(user_id)
            await db.execute(query, *values)
            return True
    except Exception as e:
        logging.error(f"❌ Ошибка в update_user_dox: {e}")
        return False

async def get_user_data(user_id):
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            row = await db.fetchrow('SELECT * FROM users WHERE user_id = $1', user_id)
            if row:
                return dict(row)
            else:
                await db.execute('''
                    INSERT INTO users (user_id, balance, first_seen, last_seen, total_messages)
                    VALUES ($1, $2, $3, $4, $5)
                ''', user_id, 0, int(time.time()), int(time.time()), 0)
                
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
    MAX_BIGINT = 9_000_000_000_000_000_000
    amount = int(amount)
    if amount > MAX_BIGINT: amount = MAX_BIGINT
    if amount < -MAX_BIGINT: amount = -MAX_BIGINT
    
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            async with db.transaction(): 
                is_new_user = await db.fetchval("SELECT 1 FROM users WHERE user_id = $1", user_id) is None
                current_time = int(time.time())
                start_amount = 10000
                
                new_balance = await db.fetchval("""
                    INSERT INTO users (user_id, balance, nickname, first_seen, last_seen, total_messages, max_balance)
                    VALUES ($1, $2, $3, $4, $5, 0, $2)
                    ON CONFLICT(user_id) DO UPDATE SET
                        balance = LEAST(GREATEST(users.balance + $6, 0::bigint), 9000000000000000000::bigint),
                        max_balance = LEAST(GREATEST(COALESCE(users.max_balance, 0::bigint), GREATEST(users.balance + $6, 0::bigint)), 9000000000000000000::bigint),
                        last_seen = EXCLUDED.last_seen,
                        nickname = COALESCE(users.nickname, $7)
                    RETURNING balance
                """, user_id, start_amount + amount, name, current_time, current_time, amount, name)
                
                if new_balance >= 10_000_000_000 and user_id not in EXCLUDED_IDS:
                    if user_id not in known_billionaires:
                        known_billionaires.add(user_id)
                        asyncio.create_task(send_billionaire_alert(user_id, name, new_balance))
                elif new_balance < 10_000_000_000 and user_id in known_billionaires:
                    known_billionaires.discard(user_id)

                if amount != 0:
                    log_type = 'earned_income' if is_income else 'system_transfer'
                    await db.execute("""
                        INSERT INTO audit_log (user_id, clan_id, type, amount, target_id, timestamp) 
                        VALUES ($1, 0, $2, $3, 'none', $4)
                    """, user_id, log_type, amount, current_time)
                
                return is_new_user 
                
    except Exception as e:
        logging.exception(f"❌ КРИТИЧЕСКАЯ ОШИБКА В add_balance (ID: {user_id}, Сумма: {amount})")
        return False

# ==========================================
# СИСТЕМА ДИВИДЕНДОВ И КУРСОВ
# ==========================================   
async def add_to_dividend_pool(amount: int):
    if amount <= 0: return 
        
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute(
            """
            INSERT INTO system_stats (key, value_int) 
            VALUES ('dividend_pool', $1)
            ON CONFLICT (key) 
            DO UPDATE SET value_int = system_stats.value_int + EXCLUDED.value_int
            """,
            int(amount)
        )

async def get_dynamic_gold_rate():
    pool = await get_db()
    try: admin_id = int(os.getenv("ADMIN_ID", 0))
    except: admin_id = 0
        
    try:
        mods_str = os.getenv("MODERATORS", "")
        moderators = [int(i.strip()) for i in mods_str.split(",") if i.strip()]
    except:
        moderators = []
        
    staff_ids = [admin_id] + moderators
    
    async with pool.acquire() as db:
        row = await db.fetchrow("""
            SELECT SUM(balance) as total_sum, COUNT(user_id) as user_count, SUM(gold_balance) as total_gold
            FROM users WHERE balance > 0 AND NOT (user_id = ANY($1::bigint[]))
        """, staff_ids)
        
        total_supply = int(row['total_sum'] or 0)
        user_count = int(row['user_count'] or 1)
        total_gold = int(row['total_gold'] or 0)

        last_buy = await db.fetchval("SELECT value_int FROM system_stats WHERE key = 'last_gold_buy'")
        last_buy = last_buy or int(time.time())

    base_rate = 100_000_000 
    avg_balance_impact = (total_supply // user_count) // 10
    scarcity_impact = int(math.sqrt(total_gold + 100) * 1_500_000)
    
    raw_rate = base_rate + avg_balance_impact + scarcity_impact

    current_time = int(time.time())
    hours_passed = (current_time - last_buy) // 3600
    discount_percent = min(hours_passed * 0.05, 0.60)
    final_rate = int(raw_rate * (1.0 - discount_percent))
    
    return final_rate, discount_percent, raw_rate

# ==========================================
# БОНУСЫ, ДЖЕКПОТ И ЛОГИ ИГР
# ==========================================
async def get_last_bonus(user_id):
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            return await db.fetchval('SELECT last_claim_date FROM daily_bonus WHERE user_id = $1', user_id)
    except Exception as e: return None

async def update_last_bonus(user_id, date_str):
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            await db.execute('''
                INSERT INTO daily_bonus (user_id, last_claim_date) VALUES ($1, $2) 
                ON CONFLICT(user_id) DO UPDATE SET last_claim_date = $3
            ''', user_id, date_str, date_str)
    except Exception as e: print(f"❌ Ошибка в update_last_bonus: {e}")

async def add_jackpot_amount(amount):
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            await db.execute('UPDATE jackpot SET amount = amount + $1', amount)
    except Exception as e: print(f"❌ Ошибка в add_jackpot_amount: {e}")

async def get_jackpot():
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            res = await db.fetchval('SELECT amount FROM jackpot')
            return res if res is not None else 0
    except Exception as e: return 0

async def save_spin_to_db(chat_id, result_text):
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute("INSERT INTO roulette_history (chat_id, result) VALUES ($1, $2)", chat_id, result_text)

async def load_history_from_db():
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute('CREATE TABLE IF NOT EXISTS roulette_history (id SERIAL PRIMARY KEY, chat_id BIGINT, result TEXT)')
        rows = await db.fetch("SELECT chat_id, result FROM roulette_history ORDER BY id DESC LIMIT 500")
            
    history_dict = {}
    for row in rows:
        chat_id, result = row['chat_id'], row['result']
        if chat_id not in history_dict: history_dict[chat_id] = []
        if len(history_dict[chat_id]) < 10: history_dict[chat_id].append(result)
    return history_dict

async def add_wheel_history(result):
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            await db.execute("CREATE TABLE IF NOT EXISTS wheel_history (id SERIAL PRIMARY KEY, result INTEGER, timestamp BIGINT)")
            await db.execute("INSERT INTO wheel_history (result, timestamp) VALUES ($1, $2)", result, int(time.time()))
            await db.execute("DELETE FROM wheel_history WHERE id NOT IN (SELECT id FROM wheel_history ORDER BY id DESC LIMIT 10)")
    except Exception as e: print(f"❌ Ошибка в add_wheel_history: {e}")

async def get_wheel_history(limit=5):
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            await db.execute("CREATE TABLE IF NOT EXISTS wheel_history (id SERIAL PRIMARY KEY, result INTEGER, timestamp BIGINT)")
            rows = await db.fetch("SELECT result FROM wheel_history ORDER BY id DESC LIMIT $1", limit)
            return [row['result'] for row in rows]
    except Exception as e: return []

# ==========================================
# ТОПЫ И КРЕДИТЫ
# ==========================================
async def get_top_10_local(chat_id):
    pool = await get_db()
    async with pool.acquire() as db:
        rows = await db.fetch("""
            SELECT u.user_id, u.balance, u.nickname 
            FROM users u JOIN chat_members cm ON u.user_id = cm.user_id
            WHERE cm.chat_id = $1 AND u.user_id NOT IN (8489556437, 1412940726, 8591496159, 1580552207)
            ORDER BY u.balance DESC LIMIT 10
        """, chat_id)
        return rows

async def get_top_10_global():
    pool = await get_db()
    async with pool.acquire() as db:
        return await db.fetch("SELECT user_id, balance, nickname FROM users WHERE user_id NOT IN (8489556437, 1412940726, 8591496159, 1580552207) ORDER BY balance DESC LIMIT 10")

async def update_user(user_id, **kwargs):
    if not kwargs: return
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            columns = []
            values = []
            for k, v in kwargs.items():
                if not re.match(r"^[a-zA-Z0-9_]+$", k):
                    logging.warning(f"Блокировка подозрительного ключа: {k}")
                    continue
                values.append(v)
                columns.append(f"{k} = ${len(values)}")
                
            if not columns: return
            
            query = f"UPDATE users SET {', '.join(columns)} WHERE user_id = ${len(values) + 1}"
            values.append(user_id)
            await db.execute(query, *values)
    except Exception as e: logging.error(f"❌ Ошибка в update_user: {e}")

async def get_overdue_users():
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            rows = await db.fetch("SELECT user_id FROM users WHERE debt > 0 AND debt_time < $1", int(time.time()))
            return [{'id': row['user_id']} for row in rows]
    except Exception as e: return []

async def get_all_debtors():
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            return await db.fetch("SELECT user_id, nickname, debt FROM users WHERE debt > 0 ORDER BY debt DESC LIMIT 20")
    except Exception as e: return []

async def mass_forgive_all():
    pool = await get_db()
    async with pool.acquire() as db:
        result = await db.execute("UPDATE users SET debt = 0, debt_time = 0, ban_until = 0")
        return int(result.split()[-1])

async def mass_unban_all():
    pool = await get_db()
    async with pool.acquire() as db:
        result = await db.execute("UPDATE users SET ban_until = 0 WHERE ban_until > $1", int(time.time()))
        return int(result.split()[-1])

async def mass_fine_debtors(amount):
    pool = await get_db()
    async with pool.acquire() as db:
        result = await db.execute("UPDATE users SET debt = debt + $1 WHERE debt > 0", amount)
        return int(result.split()[-1])

async def mass_execute_all(ban_ts):
    pool = await get_db()
    async with pool.acquire() as db:
        result = await db.execute("UPDATE users SET ban_until = $1, balance = 0, debt = 0, debt_time = 0 WHERE debt > 0", ban_ts)
        return int(result.split()[-1])

async def set_user_nickname(user_id, nickname):
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute('UPDATE users SET nickname = $1 WHERE user_id = $2', nickname, user_id)


# ==========================================
# ГЛОБАЛЬНАЯ СТАТИСТИКА
# ==========================================
async def get_global_stats():
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            stats = {}
            row = await db.fetchrow("SELECT COUNT(*) as c, SUM(balance) as b, SUM(debt) as d, SUM(total_messages) as tm FROM users")
            stats['total_users'] = row['c'] or 0
            stats['total_balance'] = row['b'] or 0
            stats['total_debt'] = row['d'] or 0
            stats['total_messages'] = row['tm'] or 0
            
            day_ago = int(time.time()) - 86400
            stats['active_24h'] = await db.fetchval("SELECT COUNT(*) FROM users WHERE last_seen >= $1", day_ago) or 0

            try:
                row = await db.fetchrow("SELECT COUNT(DISTINCT user_id) as farms, SUM(qty) as gpus FROM gpu_batches WHERE condition > 0")
                stats['active_farms'] = row['farms'] or 0
                stats['total_gpus'] = row['gpus'] or 0
            except Exception:
                stats['active_farms'], stats['total_gpus'] = 0, 0

            try:
                row = await db.fetchrow("SELECT COUNT(*) as lots, SUM(price) as val FROM market")
                stats['market_lots'] = row['lots'] or 0
                stats['market_value'] = row['val'] or 0
            except Exception:
                stats['market_lots'], stats['market_value'] = 0, 0

            try:
                row = await db.fetchrow("SELECT COUNT(*) as tc, SUM(balance) as cb FROM clans")
                stats['total_clans'] = row['tc'] or 0
                stats['clans_balance'] = row['cb'] or 0
            except Exception:
                stats['total_clans'], stats['clans_balance'] = 0, 0

            rows = await db.fetch("SELECT nickname, telegram_username, balance, user_id FROM users ORDER BY balance DESC LIMIT 3")
            stats['top_rich'] = [(r['nickname'] or r['telegram_username'] or f"ID:{r['user_id']}", r['balance']) for r in rows]

            rows = await db.fetch("SELECT nickname, telegram_username, debt, user_id FROM users WHERE debt > 0 ORDER BY debt DESC LIMIT 3")
            stats['top_debtors'] = [(r['nickname'] or r['telegram_username'] or f"ID:{r['user_id']}", r['debt']) for r in rows]

            stats['db_size'] = (await db.fetchval("SELECT pg_database_size(current_database())")) / (1024 * 1024)
            stats['log_size'] = os.path.getsize("bot_errors.log") / (1024 * 1024) if os.path.exists("bot_errors.log") else 0
            return stats
    except Exception as e:
        print(f"Ошибка сбора статы: {e}")
        return None

# ==========================================
# КЛАНЫ
# ==========================================
async def update_clan(clan_id, **kwargs):
    if not kwargs: return
    pool = await get_db()
    async with pool.acquire() as db:
        columns = []
        values = []
        for k, v in kwargs.items():
            if not re.match(r"^[a-zA-Z0-9_]+$", k): continue
            values.append(v)
            columns.append(f"{k} = ${len(values)}")
            
        if not columns: return
        query = f"UPDATE clans SET {', '.join(columns)} WHERE id = ${len(values) + 1}"
        values.append(clan_id)
        await db.execute(query, *values)

async def create_clan(owner_id, tag, name):
    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            clan_id = await db.fetchval("INSERT INTO clans (name, tag, owner_id, created_at) VALUES ($1, $2, $3, $4) RETURNING id", name, tag, owner_id, int(time.time()))
            await db.execute("UPDATE users SET clan_id = $1 WHERE user_id = $2", clan_id, owner_id)
            return clan_id

async def get_clan(clan_id):
    pool = await get_db()
    async with pool.acquire() as db:
        row = await db.fetchrow("SELECT * FROM clans WHERE id = $1", clan_id)
        return dict(row) if row else None

async def get_clan_members(clan_id):
    pool = await get_db()
    async with pool.acquire() as db:
        return await db.fetch("SELECT user_id, nickname, balance FROM users WHERE clan_id = $1 ORDER BY balance DESC", clan_id)

async def add_clan_balance(clan_id, amount):
    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            await db.execute("UPDATE clans SET balance = balance + $1 WHERE id = $2", amount, clan_id)
            if amount != 0:
                await db.execute("INSERT INTO audit_log (user_id, clan_id, type, amount, target_id, timestamp) VALUES (0, $1, 'clan_balance', $2, 'none', $3)", clan_id, amount, int(time.time()))

async def get_top_clans(limit=10):
    pool = await get_db()
    async with pool.acquire() as db:
        rows = await db.fetch("SELECT id, tag, name, balance FROM clans ORDER BY balance DESC LIMIT $1", limit)
        return [dict(row) for row in rows]

# ==========================================
# ПРОЧЕЕ (УТИЛИТЫ)
# ==========================================
async def update_username(user_id, username):
    if not username: return
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute("UPDATE users SET telegram_username = $1 WHERE user_id = $2", username.lower(), user_id)

async def resolve_user_id(target_str):
    if not target_str: return None
    target_str = str(target_str).strip()
    if target_str.isdigit(): return int(target_str)
    
    username = target_str.replace('@', '').lower()
    pool = await get_db()
    async with pool.acquire() as db:
        return await db.fetchval("SELECT user_id FROM users WHERE LOWER(telegram_username) = $1", username)

async def get_user_buffs(user_id):
    current_time = int(time.time())
    buffs = {}
    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            await db.execute("DELETE FROM user_buffs WHERE expires_at <= $1", current_time)
            rows = await db.fetch("SELECT buff_type, value FROM user_buffs WHERE user_id = $1", user_id)
            for row in rows: buffs[row['buff_type']] = row['value']
    return buffs

async def force_cancel_games(target_id=None):
    total_refunded = 0
    affected_users = set()
    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            checks = [
                ("mines_games", "user_id", "bet"), ("bomb_games", "user_id", "bet"),
                ("crash_bets", "user_id", "amount"), ("wheel_bets", "user_id", "bet"),
                ("roulette_bets", "user_id", "bet"), ("race_bets", "user_id", "bet"),
                ("squid_bets", "user_id", "bet"), ("button_bets", "user_id", "bet")
            ]
            for table, uid_col, bet_col in checks:
                try:
                    query = f"SELECT {uid_col}, SUM({bet_col}) as total_bet FROM {table}"
                    if target_id: query += f" WHERE {uid_col} = $1"
                    query += f" GROUP BY {uid_col}"
                    
                    params = (target_id,) if target_id else ()
                    rows = await db.fetch(query, *params)
                    
                    for row in rows:
                        uid, total_bet = row[uid_col], row['total_bet']
                        if total_bet and total_bet > 0:
                            await db.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", total_bet, uid)
                            total_refunded += total_bet
                            affected_users.add(uid)
                            
                    del_query = f"DELETE FROM {table}" + (f" WHERE {uid_col} = $1" if target_id else "")
                    await db.execute(del_query, *params)
                except Exception as e:
                    logging.error(f"Ошибка отмены в {table}: {e}") 

            try:
                query = "SELECT creator_id, SUM(bet) as total_bet FROM duels WHERE opponent_id IS NULL"
                if target_id: query += " AND creator_id = $1"
                query += " GROUP BY creator_id"
                
                params = (target_id,) if target_id else ()
                duel_rows = await db.fetch(query, *params)
                    
                for row in duel_rows:
                    uid, total_bet = row['creator_id'], row['total_bet']
                    if total_bet and total_bet > 0:
                        await db.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", total_bet, uid)
                        total_refunded += total_bet
                        affected_users.add(uid)
                        
                del_query = "DELETE FROM duels WHERE opponent_id IS NULL" + (" AND creator_id = $1" if target_id else "")
                await db.execute(del_query, *params)
            except Exception as e:
                logging.error(f"Ошибка отмены дуэлей: {e}")
                
    return total_refunded, len(affected_users)

async def check_and_apply_cashback(user_id, loss_amount):
    from handlers.users.statuses import has_active_status
    if await has_active_status(user_id, 3): 
        cashback_sum = int(loss_amount * 0.10)
        if cashback_sum > 0:
            await add_balance(user_id, cashback_sum)
            return cashback_sum
    return 0

# ==========================================
# 🧬 СИСТЕМА СОЦИАЛЬНОГО РЕЙТИНГА (ИИ АУДИТОР)
# ==========================================
async def change_rating(user_id: int, amount: int):
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            await db.execute("""
                UPDATE user_rating 
                SET rating_points = GREATEST(0, LEAST(5000, rating_points + $1)) 
                WHERE user_id = $2
            """, amount, user_id)
    except Exception as e:
        logging.error(f"❌ Ошибка в change_rating: {e}")

async def analyze_player_strategy(user_id: int, _ = None):
    """ИИ-Аудитор. Локализовано."""
    if not _: _ = get_translator("ru")
    score_modifier = 0
    verdict_lines = []

    try:
        pool = await get_db()
        async with pool.acquire() as db:
            user_data = await db.fetchrow("SELECT debt, total_wins, total_losses FROM users WHERE user_id = $1", user_id)

            if user_data:
                debt, wins, losses = user_data['debt'], user_data['total_wins'], user_data['total_losses']

                if debt > 0:
                    score_modifier -= 50
                    verdict_lines.append(_("db_strat_debt_bad", debt=debt))
                else:
                    score_modifier += 15
                    verdict_lines.append(_("db_strat_debt_ok"))

                total_games = wins + losses
                if total_games > 15:
                    winrate = wins / total_games
                    if winrate < 0.4:
                        score_modifier -= 40
                        verdict_lines.append(_("db_strat_ludo_bad", rate=round(winrate*100, 1)))
                    elif winrate > 0.55:
                        score_modifier += 30
                        verdict_lines.append(_("db_strat_ludo_good", rate=round(winrate*100, 1)))
                    else:
                        verdict_lines.append(_("db_strat_ludo_mid"))
                elif total_games > 0:
                    verdict_lines.append(_("db_strat_ludo_none"))

            gpu_data = await db.fetchrow("SELECT SUM(qty) as qty, MAX(multiplier) as mult FROM gpu_batches WHERE user_id = $1 AND condition > 0", user_id)

            if gpu_data and gpu_data['qty'] and gpu_data['qty'] > 0:
                total_gpus = gpu_data['qty']
                best_mult = gpu_data['mult']
                
                score_modifier += min(100, total_gpus * 2) 
                
                if best_mult >= 5.0:
                    score_modifier += 30
                    verdict_lines.append(_("db_strat_farm_pro"))
                else:
                    verdict_lines.append(_("db_strat_farm_mid"))
            else:
                score_modifier -= 30
                verdict_lines.append(_("db_strat_farm_none"))

    except Exception as e:
        logging.error(f"❌ Ошибка аудитора стратегии: {e}")
        return 0, _("db_strat_err")

    verdict = "\n".join(verdict_lines) if verdict_lines else _("db_strat_empty")
    return score_modifier, verdict

async def update_user_activity(user_id: int):
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            row = await db.fetchrow("SELECT rating_points, last_active FROM user_rating WHERE user_id = $1", user_id)
            if not row: return

            points, last_active = row['rating_points'], row['last_active']
            now = int(time.time())
            
            if not last_active:
                await db.execute("UPDATE user_rating SET last_active = $1 WHERE user_id = $2", now, user_id)
                return

            days_inactive = (now - last_active) // 86400

            if days_inactive >= 2:
                penalty = (days_inactive - 1) * 50
                points = max(0, points - penalty)
                await db.execute("UPDATE user_rating SET rating_points = $1, last_active = $2 WHERE user_id = $3", points, now, user_id)
            else:
                await db.execute("UPDATE user_rating SET last_active = $1 WHERE user_id = $2", now, user_id)
    except Exception as e:
        logging.error(f"❌ Ошибка в update_user_activity: {e}")

async def get_user_name(user_id: int, default_name: str) -> str:
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            nick = await db.fetchval("SELECT nickname FROM users WHERE user_id = $1", user_id)
            return nick if nick else default_name
    except Exception as e:
        print(f"❌ Ошибка в get_user_name: {e}")
        return default_name