import time
import json
import random
from datetime import datetime, timezone, timedelta
from aiogram import Router, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from core.database import get_db, add_balance, get_farm, update_farm
from handlers.users.statuses import has_active_status

router = Router()

def fmt(num):
    return f"{int(num):,}".replace(",", " ")

quests_cooldowns = {}

# ==========================================
# 📋 ПУЛ КВЕСТОВ (КОНФИГ)
# ==========================================
DAILY_QUESTS = {
    "d1": {"desc": "🎰 Сделать 10 спинов в рулетке", "action_type": "roulette_spin", "target": 10, "reward": 50_000},
    "d2": {"desc": "💰 Выиграть 5 000 000 ᴜ в рулетке", "action_type": "roulette_win", "target": 5_000_000, "reward": 150_000},
    "d3": {"desc": "🎲 Поставить на 5 разных чисел в рулетке", "action_type": "roulette_bet_distinct", "target": 5, "reward": 30_000},
    "d4": {"desc": "📥 Собрать прибыль с фермы 3 раза", "action_type": "farm_collect", "target": 3, "reward": 40_000},
    "d5": {"desc": "🛒 Купить 2 любые видеокарты", "action_type": "farm_buy_gpu", "target": 2, "reward": 30_000, "reward_gpu": 5},
    "d6": {"desc": "🔧 Починить 1 видеокарту", "action_type": "farm_repair", "target": 1, "reward": 50_000},
    "d7": {"desc": "📉 Продать 1 видеокарту", "action_type": "farm_sell_gpu", "target": 1, "reward": 30_000},
    "d8": {"desc": "⚡️ Разогнать 1 видеокарту (любой результат)", "action_type": "farm_overclock", "target": 1, "reward": 100_000},
    "d9": {"desc": "💣 Сыграть в мины 5 раз", "action_type": "mines_play", "target": 5, "reward": 80_000},
    "d10": {"desc": "💎 Найти 3 алмаза в минах за одну игру", "action_type": "mines_diamond_streak", "target": 3, "reward": 60_000},
    "d11": {"desc": "🔥 Выиграть в минах с множителем x2.5+", "action_type": "mines_win_mult", "target": 1, "reward": 90_000},
    "d12": {"desc": "✈️ Сыграть в краш 3 раза", "action_type": "crash_play", "target": 3, "reward": 70_000},
    "d13": {"desc": "🪂 Забрать выигрыш в краше на x2.0+", "action_type": "crash_cashout", "target": 1, "reward": 80_000},
    "d14": {"desc": "🏎 Участвовать в гонке 2 раза", "action_type": "race_play", "target": 2, "reward": 50_000},
    "d15": {"desc": "🥇 Занять 1-е место в гонке", "action_type": "race_win", "target": 1, "reward": 120_000},
    "d16": {"desc": "🧨 Сыграть в бомбу 2 раза", "action_type": "bomb_play", "target": 2, "reward": 60_000},
    "d17": {"desc": "🏆 Остаться последним выжившим в бомбе", "action_type": "bomb_survive", "target": 1, "reward": 130_000},
    "d18": {"desc": "🏦 Положить на депозит любую сумму", "action_type": "bank_deposit", "target": 1, "reward": 35_000},
    "d19": {"desc": "💰 Снять с депозита любую сумму", "action_type": "bank_withdraw", "target": 1, "reward": 30_000},
    "d20": {"desc": "💸 Перевести другому игроку 100 000 ᴜ", "action_type": "transfer_send", "target": 100_000, "reward": 45_000},
    "d21": {"desc": "🤝 Получить перевод от другого игрока", "action_type": "transfer_receive", "target": 1, "reward": 20_000},
    "d22": {"desc": "🏴‍☠️ Внести взнос в клан (любую сумму)", "action_type": "clan_contribute", "target": 1, "reward": 20_000},
    "d23": {"desc": "🤖 Взаимодействовать с ботом 20 раз (команды/кнопки)", "action_type": "bot_interaction", "target": 20, "reward": 50_000},
    "d24": {"desc": "🎲 Сыграть в любую игру 15 раз", "action_type": "any_game_play", "target": 15, "reward": 130_000, "reward_case": 2},
    "d25": {"desc": "⚡️ Успешно разогнать 3 видеокарты", "action_type": "farm_overclock_success", "target": 3, "reward": 140_000, "reward_gpu": 6},
}

WEEKLY_QUESTS = {
    "w1": {"desc": "🎰 Сделать 100 спинов в рулетке", "action_type": "roulette_spin", "target": 100, "reward": 1_500_000},
    "w2": {"desc": "💰 Выиграть 50 000 000 ᴜ в рулетке", "action_type": "roulette_win", "target": 50_000_000, "reward": 2_500_000},
    "w3": {"desc": "🎲 Поставить на 50 разных чисел в рулетке", "action_type": "roulette_bet_distinct", "target": 50, "reward": 800_000},
    "w4": {"desc": "📥 Собрать прибыль с фермы 25 раз", "action_type": "farm_collect", "target": 25, "reward": 800_000},
    "w5": {"desc": "🛒 Купить 15 видеокарт", "action_type": "farm_buy_gpu", "target": 15, "reward": 1_200_000},
    "w6": {"desc": "🔧 Починить 10 видеокарт", "action_type": "farm_repair", "target": 10, "reward": 900_000},
    "w7": {"desc": "⚡️ Успешно разогнать 5 видеокарт", "action_type": "farm_overclock_success", "target": 5, "reward": 2_000_000},
    "w8": {"desc": "📉 Продать 20 видеокарт (суммарно)", "action_type": "farm_sell_gpu", "target": 20, "reward": 1_000_000},
    "w9": {"desc": "💣 Сыграть в мины 40 раз", "action_type": "mines_play", "target": 40, "reward": 1_800_000},
    "w10": {"desc": "💎 Найти 20 алмазов в минах", "action_type": "mines_diamond", "target": 20, "reward": 1_800_000},
    "w11": {"desc": "🔥 Выиграть in минах с множителем x10+", "action_type": "mines_win_mult", "target": 10, "reward": 3_000_000},
    "w12": {"desc": "✈️ Сыграть в краш 20 раз", "action_type": "crash_play", "target": 20, "reward": 1_200_000},
    "w13": {"desc": "🪂 Забрать выигрыш в краше на x5+ (5 раз)", "action_type": "crash_cashout_count", "target": 5, "target_value": 5.0, "reward": 2_000_000},
    "w14": {"desc": "🏎 Участвовать в гонке 15 раз", "action_type": "race_play", "target": 15, "reward": 1_000_000},
    "w15": {"desc": "🥇 Победить в гонке 5 раз", "action_type": "race_win", "target": 5, "reward": 1_800_000},
    "w16": {"desc": "💸 Совершить переводы на общую сумму 5 000 000 ᴜ", "action_type": "transfer_send_total", "target": 5_000_000, "reward": 800_000},
}

MONTHLY_QUESTS = {
    "m1": {"desc": "🎰 Сделать 1000 спинов в рулетке", "action_type": "roulette_spin", "target": 1000, "reward": 10_000_000},
    "m2": {"desc": "💰 Выиграть 500 000 000 ᴜ в рулетке", "action_type": "roulette_win", "target": 500_000_000, "reward": 12_500_000},
    "m3": {"desc": "📥 Собрать прибыль с фермы 200 раз", "action_type": "farm_collect", "target": 200, "reward": 10_000_000},
    "m4": {"desc": "🛒 Купить 100 видеокарт", "action_type": "farm_buy_gpu", "target": 100, "reward": 12_000_000},
    "m5": {"desc": "🔧 Починить 50 видеокарт", "action_type": "farm_repair", "target": 50, "reward": 8_000_000},
    "m6": {"desc": "⚡️ Успешно разогнать 30 видеокарт", "action_type": "farm_overclock_success", "target": 30, "reward": 14_000_000},
    "m7": {"desc": "💣 Сыграть в мины 300 раз", "action_type": "mines_play", "target": 300, "reward": 14_000_000},
    "m8": {"desc": "💎 Найти 150 алмазов в минах", "action_type": "mines_diamond", "target": 150, "reward": 12_000_000},
    "m9": {"desc": "✈️ Сыграть в краш 150 раз", "action_type": "crash_play", "target": 150, "reward": 10_000_000},
    "m10": {"desc": "🏎 Участвовать в гонке 100 раз", "action_type": "race_play", "target": 100, "reward": 8_000_000},
    "m11": {"desc": "💸 Совершить переводы на общую сумму 50 000 000 ᴜ", "action_type": "transfer_send_total", "target": 50_000_000, "reward": 5_000_000},
    "m12": {"desc": "🏦 Получить 10 000 000 ᴜ процентов по депозиту", "action_type": "deposit_interest", "target": 10_000_000, "reward": 7_000_000},
}

# Описания Эпических и VIP квестов
EPIC_QUESTS = {
    "e1": {"desc": "🎰 Сделать 10 000 спинов в рулетке за всё время", "action_type": "roulette_spin", "target": 10_000, "reward": 100_000_000},
    "e2": {"desc": "💰 Выиграть 5 000 000 000 ᴜ в рулетке (всего)", "action_type": "roulette_win", "target": 5_000_000_000, "reward": 350_000_000},
    "e3": {"desc": "🏭 Собрать ферму из 10 000 видеокарт", "action_type": "farm_total_gpus", "target": 10_000, "reward": 400_000_000},
    "e4": {"desc": "💎 Найти 1000 алмазов в минах", "action_type": "mines_diamond", "target": 1000, "reward": 200_000_000},
    "e5": {"desc": "⚡️ Успешно разогнать 500 видеокарт", "action_type": "farm_overclock_success", "target": 500, "reward": 300_000_000},
    "e6": {"desc": "🔧 Починить 1000 видеокарт", "action_type": "farm_repair", "target": 1000, "reward": 200_000_000},
    "e7": {"desc": "🏆 Занять 1-е место в гонке 100 раз", "action_type": "race_win", "target": 100, "reward": 250_000_000},
    "e8": {"desc": "🏦 Накопить на депозите 1 000 000 000 ᴜ (максимальная сумма)", "action_type": "deposit_max", "target": 1_000_000_000, "reward": 100_000_000},
    "e9": {"desc": "🏴‍☠️ Создать клан и привести в него 50 игроков", "action_type": "clan_members", "target": 50, "reward": 400_000_000},
    "e10": {"desc": "🎲 Сыграть во все игры (рулетка, мины, краш, гонки, бомба, колесо) 100 раз в каждой", "action_type": "all_games_100", "target": 100, "reward": 1_000_000_000},
}

VIP_QUESTS = {
    "v1": {"desc": "👑 Собрать королевскую прибыль 5 раз", "action_type": "farm_collect", "target": 5, "reward": 5_000_000},
    "v2": {"desc": "💎 Купить 10 любых видеокарт (Оптовая закупка)", "action_type": "farm_buy_gpu", "target": 10, "reward": 15_000_000},
    "v3": {"desc": "🎰 Сделать 50 элитных спинов в рулетке", "action_type": "roulette_spin", "target": 50, "reward": 8_000_000},
    "v4": {"desc": "💣 Обезвредить 15 мин", "action_type": "mines_play", "target": 15, "reward": 10_000_000},
    "v5": {"desc": "🏦 Провернуть переводы на 25 000 000 ᴜ", "action_type": "transfer_send_total", "target": 25_000_000, "reward": 12_000_000}
}

# Словарь для безопасного фолбека
def get_str(key: str, translator=None, **kwargs) -> str:
    if translator and callable(translator):
        return translator(key, **kwargs)
    text = FALLBACK_STRINGS.get(key, key)
    if kwargs:
        try: return text.format(**kwargs)
        except: pass
    return text

# Временный хардкод для обратной совместимости, если мидлварь отключена
FALLBACK_STRINGS = {}

async def init_quests_db():
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_quests (
                user_id BIGINT PRIMARY KEY,
                daily_quests JSONB,
                weekly_quests JSONB,
                daily_reset BIGINT,
                weekly_reset BIGINT
            )
        """)
        await db.execute("""
            ALTER TABLE user_quests 
            ADD COLUMN IF NOT EXISTS monthly_quests JSONB,
            ADD COLUMN IF NOT EXISTS epic_quests JSONB,
            ADD COLUMN IF NOT EXISTS vip_quests JSONB,
            ADD COLUMN IF NOT EXISTS monthly_reset BIGINT,
            ADD COLUMN IF NOT EXISTS vip_reset BIGINT
        """)

def get_next_daily_reset():
    now = datetime.now(timezone.utc)
    next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(next_midnight.timestamp())

def get_next_weekly_reset():
    now = datetime.now(timezone.utc)
    days_ahead = 7 - now.weekday()
    next_monday = (now + timedelta(days=days_ahead)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(next_monday.timestamp())

def get_next_monthly_reset():
    now = datetime.now(timezone.utc)
    if now.month == 12:
        next_month = now.replace(year=now.year+1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        next_month = now.replace(month=now.month+1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return int(next_month.timestamp())

def generate_quests(quest_pool, count):
    if not quest_pool: return {}
    selected_keys = random.sample(list(quest_pool.keys()), min(count, len(quest_pool)))
    return {key: {"progress": 0, "claimed": False} for key in selected_keys}

async def get_or_refresh_quests(user_id: int):
    pool = await get_db()
    current_time = int(time.time())
    
    async with pool.acquire() as db:
        row = await db.fetchrow("SELECT * FROM user_quests WHERE user_id = $1", user_id)
        
        if not row:
            daily = generate_quests(DAILY_QUESTS, 5)
            weekly = generate_quests(WEEKLY_QUESTS, 5)
            monthly = generate_quests(MONTHLY_QUESTS, 5)
            epic = generate_quests(EPIC_QUESTS, 10) 
            vip = generate_quests(VIP_QUESTS, 5)
            
            d_reset = get_next_daily_reset()
            w_reset = get_next_weekly_reset()
            m_reset = get_next_monthly_reset()
            v_reset = get_next_daily_reset()
            
            await db.execute("""
                INSERT INTO user_quests (user_id, daily_quests, weekly_quests, monthly_quests, epic_quests, vip_quests, daily_reset, weekly_reset, monthly_reset, vip_reset)
                VALUES ($1, $2::jsonb, $3::jsonb, $4::jsonb, $5::jsonb, $6::jsonb, $7, $8, $9, $10)
            """, user_id, json.dumps(daily), json.dumps(weekly), json.dumps(monthly), json.dumps(epic), json.dumps(vip), d_reset, w_reset, m_reset, v_reset)
            
            return daily, weekly, monthly, epic, vip, d_reset, w_reset, m_reset, v_reset

        daily = json.loads(row['daily_quests']) if row['daily_quests'] else generate_quests(DAILY_QUESTS, 5)
        weekly = json.loads(row['weekly_quests']) if row['weekly_quests'] else generate_quests(WEEKLY_QUESTS, 5)
        monthly = json.loads(row['monthly_quests']) if row['monthly_quests'] else generate_quests(MONTHLY_QUESTS, 5)
        epic = json.loads(row['epic_quests']) if row['epic_quests'] else generate_quests(EPIC_QUESTS, 10)
        vip = json.loads(row.get('vip_quests', '{}')) if row.get('vip_quests') else generate_quests(VIP_QUESTS, 5)
        
        d_reset = row['daily_reset'] or get_next_daily_reset()
        w_reset = row['weekly_reset'] or get_next_weekly_reset()
        m_reset = row['monthly_reset'] or get_next_monthly_reset()
        v_reset = row.get('vip_reset') or get_next_daily_reset()
        
        needs_update = False
        if current_time >= d_reset: daily, d_reset, needs_update = generate_quests(DAILY_QUESTS, 5), get_next_daily_reset(), True
        if current_time >= w_reset: weekly, w_reset, needs_update = generate_quests(WEEKLY_QUESTS, 5), get_next_weekly_reset(), True
        if current_time >= m_reset: monthly, m_reset, needs_update = generate_quests(MONTHLY_QUESTS, 5), get_next_monthly_reset(), True
        if current_time >= v_reset: vip, v_reset, needs_update = generate_quests(VIP_QUESTS, 5), get_next_daily_reset(), True

        if needs_update or not row.get('vip_quests'):
            await db.execute("""
                UPDATE user_quests 
                SET daily_quests = $1::jsonb, weekly_quests = $2::jsonb, monthly_quests = $3::jsonb, epic_quests = $4::jsonb, vip_quests = $5::jsonb,
                    daily_reset = $6, weekly_reset = $7, monthly_reset = $8, vip_reset = $9
                WHERE user_id = $10
            """, json.dumps(daily), json.dumps(weekly), json.dumps(monthly), json.dumps(epic), json.dumps(vip), d_reset, w_reset, m_reset, v_reset, user_id)

        return daily, weekly, monthly, epic, vip, d_reset, w_reset, m_reset, v_reset

# ==========================================
# 🎮 ГЛАВНОЕ МЕНЮ КВЕСТОВ
# ==========================================
@router.message(F.text.lower().in_(["квесты", "задания", "миссии", "📜 квесты", "quests", "missions", "quest"]))
async def cmd_quests(message: types.Message, _=None):
    await send_quests_menu(message.from_user.id, message, "daily", _=_)

@router.callback_query(F.data.startswith("quests_menu_"))
async def cb_quests_menu(callback: types.CallbackQuery, _=None):
    parts = callback.data.split("_")
    mode = parts[2]
    owner_id = int(parts[3]) if len(parts) > 3 else callback.from_user.id 

    if callback.from_user.id != owner_id:
        return await callback.answer(get_str("qs_alert_foreign_menu", _), show_alert=True)
    
    if mode == "vip":
        is_vip = await has_active_status(owner_id, 777)
        if not is_vip:
            return await callback.answer(get_str("qs_alert_vip_denied", _), show_alert=True)
            
    await send_quests_menu(owner_id, callback.message, mode, is_edit=True, _=_)
    await callback.answer()

async def send_quests_menu(user_id: int, message_obj, mode: str, is_edit=False, _=None):
    daily, weekly, monthly, epic, vip, d_reset, w_reset, m_reset, v_reset = await get_or_refresh_quests(user_id)
    
    if mode == "daily":
        current_quests, quest_pool, reset_time = daily, DAILY_QUESTS, d_reset
        title = get_str("qs_title_daily", _)
    elif mode == "weekly":
        current_quests, quest_pool, reset_time = weekly, WEEKLY_QUESTS, w_reset
        title = get_str("qs_title_weekly", _)
    elif mode == "monthly":
        current_quests, quest_pool, reset_time = monthly, MONTHLY_QUESTS, m_reset
        title = get_str("qs_title_monthly", _)
    elif mode == "epic":
        current_quests, quest_pool, reset_time = epic, EPIC_QUESTS, None
        title = get_str("qs_title_epic", _)
    else:
        current_quests, quest_pool, reset_time = vip, VIP_QUESTS, v_reset
        title = get_str("qs_title_vip", _)
    
    if reset_time:
        time_left = reset_time - int(time.time())
        days, remainder = divmod(time_left, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, _ = divmod(remainder, 60)
        time_str = get_str("qs_time_days", _, days=days, hours=hours, minutes=minutes) if days > 0 else get_str("qs_time_hours", _, hours=hours, minutes=minutes)
    else:
        time_str = get_str("qs_never", _)

    text = get_str("qs_body_header", _, title=title, time_str=time_str)
    builder = InlineKeyboardBuilder()
    completed_all = True

    if not current_quests:
        text += get_str("qs_loading", _)
    else:
        from handlers.syndicate.farms import GPUS
        for q_id, q_data in current_quests.items():
            if q_id not in quest_pool: continue 
            
            config = quest_pool[q_id]
            target = config['target']
            progress = min(q_data['progress'], target) 
            claimed = q_data['claimed']
            
            if not claimed: completed_all = False

            if claimed:
                status_icon = get_str("qs_status_claimed", _)
                progress_text = get_str("qs_text_claimed", _)
            elif progress >= target:
                status_icon = get_str("qs_status_ready", _)
                progress_text = get_str("qs_text_ready", _)
                builder.button(text=get_str("qs_btn_claim_one", _, reward=fmt(config['reward'])), callback_data=f"q_claim_{mode}_{q_id}_{user_id}")
            else:
                status_icon = get_str("qs_status_progress", _)
                t_fmt = fmt(target) if isinstance(target, (int, float)) and target >= 1000 else str(target)
                p_fmt = fmt(progress) if isinstance(progress, (int, float)) and progress >= 1000 else str(round(progress, 1) if isinstance(progress, float) else progress)
                progress_text = get_str("qs_text_progress", _, progress=p_fmt, target=t_fmt)

            rewards_list = [f"<b>{fmt(config['reward'])} ᴜ</b>"]
            
            if "reward_gpu" in config:
                gpu_info = GPUS.get(config['reward_gpu'])
                rewards_list.append(f"{gpu_info['emoji']} {gpu_info['name']}")
            
            if "reward_case" in config:
                from handlers.games.cases_game import CASES 
                case_info = CASES.get(config['reward_case'])
                rewards_list.append(f"📦 {case_info.get('name', 'Кейс')}")

            rewards_str = " + ".join(rewards_list)
            
            # 🔥 Локализация описания квеста: ищет q_desc_id в файле, фолбек на дефолтный конфиг
            localized_desc = get_str(f"q_desc_{q_id}", _)
            if localized_desc == f"q_desc_{q_id}":
                localized_desc = config['desc']

            text += f"{status_icon} {localized_desc}\n├ 🎁 Награда: {rewards_str}\n└ {progress_text}\n\n"

    if completed_all and current_quests:
        text += get_str("qs_completed_all_category", _)

    builder.adjust(1)
    
    can_claim_all = False
    for q_dict, q_pool in [(daily, DAILY_QUESTS), (weekly, WEEKLY_QUESTS), (monthly, MONTHLY_QUESTS), (epic, EPIC_QUESTS), (vip, VIP_QUESTS)]:
        for q_id, q_data in q_dict.items():
            if q_id in q_pool and not q_data['claimed'] and q_data['progress'] >= q_pool[q_id]['target']:
                can_claim_all = True
                break
        if can_claim_all: break

    if can_claim_all:
        builder.row(types.InlineKeyboardButton(text=get_str("qs_btn_claim_all", _), callback_data=f"claim_all_quests_{user_id}"))

    builder.row(
        types.InlineKeyboardButton(text=get_str("qs_btn_nav_daily", _), callback_data=f"quests_menu_daily_{user_id}"),
        types.InlineKeyboardButton(text=get_str("qs_btn_nav_weekly", _), callback_data=f"quests_menu_weekly_{user_id}"),
        types.InlineKeyboardButton(text=get_str("qs_btn_nav_monthly", _), callback_data=f"quests_menu_monthly_{user_id}")
    )
    builder.row(
        types.InlineKeyboardButton(text=get_str("qs_btn_nav_epic", _), callback_data=f"quests_menu_epic_{user_id}"),
        types.InlineKeyboardButton(text=get_str("qs_btn_nav_vip", _), callback_data=f"quests_menu_vip_{user_id}")
    )

    if is_edit:
        await message_obj.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    else:
        await message_obj.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")

# ==========================================
# 🎁 ВЫДАЧА НАГРАДЫ
# ==========================================
@router.callback_query(F.data.startswith("q_claim_"))
async def claim_quest_reward(callback: types.CallbackQuery, _=None):
    user_id = callback.from_user.id
    now = time.time()
    if user_id in quests_cooldowns and (now - quests_cooldowns[user_id] < 1.5):
        return await callback.answer(get_str("qs_alert_cooldown", _), show_alert=True)
    quests_cooldowns[user_id] = now

    parts = callback.data.split("_")
    mode, q_id, owner_id = parts[2], parts[3], int(parts[4])

    if callback.from_user.id != owner_id:
        return await callback.answer(get_str("qs_alert_foreign_reward", _), show_alert=True)

    user_id = owner_id 
    daily, weekly, monthly, epic, vip, d_reset, w_reset, m_reset, v_reset = await get_or_refresh_quests(user_id)
    
    if mode == "daily": current_quests, quest_pool, db_col = daily, DAILY_QUESTS, "daily_quests"
    elif mode == "weekly": current_quests, quest_pool, db_col = weekly, WEEKLY_QUESTS, "weekly_quests"
    elif mode == "monthly": current_quests, quest_pool, db_col = monthly, MONTHLY_QUESTS, "monthly_quests"
    elif mode == "vip": current_quests, quest_pool, db_col = vip, VIP_QUESTS, "vip_quests"
    else: current_quests, quest_pool, db_col = epic, EPIC_QUESTS, "epic_quests"
    
    if q_id not in current_quests or q_id not in quest_pool:
        return await callback.answer(get_str("qs_alert_not_found", _), show_alert=True)
        
    q_data = current_quests[q_id]
    config = quest_pool[q_id]
    
    if q_data['claimed']: return await callback.answer(get_str("qs_alert_already_claimed", _), show_alert=True)
    if q_data['progress'] < config['target']: return await callback.answer(get_str("qs_alert_not_done", _), show_alert=True)

    q_data['claimed'] = True
    reward_money = config['reward']
    extra_text = ""

    from handlers.syndicate.farms import GPUS
    from handlers.games.cases_game import CASES

    await add_balance(user_id, reward_money, is_income=True)

    if "reward_gpu" in config:
        gpu_id = config['reward_gpu']
        farm_data = await get_farm(user_id)
        await update_farm(user_id, **{f"gpu_{gpu_id}": farm_data.get(f"gpu_{gpu_id}", 0) + 1})
        extra_text += get_str("qs_extra_gpu", _, name=GPUS[gpu_id]['name'])

    if "reward_case" in config:
        case_id = config['reward_case']
        c_data = CASES.get(case_id)
        if c_data["tiers"] == "ALL":
            roll = random.randint(1, 100)
            if roll <= 60: drop_pool = [7, 8, 9, 10]
            elif roll <= 85: drop_pool = [11, 12, 13, 21]
            elif roll <= 95: drop_pool = [14, 15, 16]
            else: drop_pool = [17, 18, 19, 20]
            dropped_gpu = random.choice(drop_pool)
        else:
            dropped_gpu = random.choice(c_data["tiers"])
        
        farm_data = await get_farm(user_id)
        await update_farm(user_id, **{f"gpu_{dropped_gpu}": farm_data.get(f"gpu_{dropped_gpu}", 0) + 1})
        extra_text += get_str("qs_extra_case", _, case_name=c_data.get('name', 'Кейс'), gpu_name=GPUS[dropped_gpu]['name'])

    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute(f"UPDATE user_quests SET {db_col} = $1::jsonb WHERE user_id = $2", json.dumps(current_quests), user_id)
        
    await callback.answer(get_str("qs_alert_success", _), show_alert=True)
    
    from core.database import get_user_name
    actual_name = await get_user_name(user_id, callback.from_user.first_name)
    user_mention = f"<a href='tg://user?id={user_id}'>{actual_name}</a>"

    success_msg = get_str("qs_one_success_msg", _, user_mention=user_mention, reward=fmt(reward_money), extra=extra_text)
    await callback.message.answer(success_msg, parse_mode="HTML")
    await send_quests_menu(user_id, callback.message, mode, is_edit=True, _=_)

# ==========================================
# 🎁 ЗАБРАТЬ ВСЕ НАГРАДЫ (КНОПКА И ТЕКСТ)
# ==========================================
@router.message(F.text.lower().in_([
    "забрать все", "забрать всё", "собрать все", "собрать всё", "собрать квесты",
    "claim all", "claim quests", "collect quests"
]))
async def cmd_claim_all_text(message: types.Message, _=None):
    await process_claim_all(message.from_user.id, message, _=_)

@router.callback_query(F.data.startswith("claim_all_quests_"))
async def cb_claim_all_btn(callback: types.CallbackQuery, _=None):
    owner_id = int(callback.data.split("_")[3])
    if callback.from_user.id != owner_id:
        return await callback.answer(get_str("qs_alert_foreign_reward", _), show_alert=True)
    
    now = time.time()
    if owner_id in quests_cooldowns and (now - quests_cooldowns[owner_id] < 2.0):
        return await callback.answer(get_str("qs_alert_cooldown", _), show_alert=True)
    quests_cooldowns[owner_id] = now
    
    await process_claim_all(owner_id, callback.message, is_callback=True, callback_obj=callback, _=_)

async def process_claim_all(user_id: int, message_obj: types.Message, is_callback=False, callback_obj=None, _=None):
    daily, weekly, monthly, epic, vip, d_reset, w_reset, m_reset, v_reset = await get_or_refresh_quests(user_id)
    
    categories = [
        (daily, DAILY_QUESTS, "daily_quests"),
        (weekly, WEEKLY_QUESTS, "weekly_quests"),
        (monthly, MONTHLY_QUESTS, "monthly_quests"),
        (epic, EPIC_QUESTS, "epic_quests"),
        (vip, VIP_QUESTS, "vip_quests")
    ]
    
    total_money = 0
    completed_count = 0
    gpus_to_give = {}
    extra_text_lines = []
    needs_db_update = False
    
    from handlers.syndicate.farms import GPUS
    from handlers.games.cases_game import CASES

    for user_q_dict, q_pool, db_col_name in categories:
        for q_id, q_data in user_q_dict.items():
            if q_id in q_pool and not q_data['claimed'] and q_data['progress'] >= q_pool[q_id]['target']:
                config = q_pool[q_id]
                q_data['claimed'] = True
                needs_db_update = True
                completed_count += 1
                total_money += config['reward']
                
                if "reward_gpu" in config:
                    gpu_id = config['reward_gpu']
                    gpus_to_give[gpu_id] = gpus_to_give.get(gpu_id, 0) + 1
                    extra_text_lines.append(get_str("qs_extra_gpu", _, name=GPUS[gpu_id]['name']))
                
                if "reward_case" in config:
                    case_id = config['reward_case']
                    c_data = CASES.get(case_id)
                    if c_data["tiers"] == "ALL":
                        roll = random.randint(1, 100)
                        if roll <= 60: drop_pool = [7, 8, 9, 10]
                        elif roll <= 85: drop_pool = [11, 12, 13, 21]
                        elif roll <= 95: drop_pool = [14, 15, 16]
                        else: drop_pool = [17, 18, 19, 20]
                        dropped_gpu = random.choice(drop_pool)
                    else:
                        dropped_gpu = random.choice(c_data["tiers"])
                        
                    gpus_to_give[dropped_gpu] = gpus_to_give.get(dropped_gpu, 0) + 1
                    extra_text_lines.append(get_str("qs_extra_case", _, case_name=c_data['name'], gpu_name=GPUS[dropped_gpu]['name']))

    if completed_count == 0:
        if is_callback: return await callback_obj.answer(get_str("qs_all_err_empty_alert", _), show_alert=True)
        else: return await message_obj.reply(get_str("qs_all_err_empty", _))

    await add_balance(user_id, total_money, is_income=True)
    
    if gpus_to_give:
        farm_data = await get_farm(user_id)
        updates = {f"gpu_{gid}": farm_data.get(f"gpu_{gid}", 0) + qty for gid, qty in gpus_to_give.items()}
        await update_farm(user_id, **updates)

    if needs_db_update:
        pool = await get_db()
        async with pool.acquire() as db:
            await db.execute("""
                UPDATE user_quests 
                SET daily_quests = $1::jsonb, weekly_quests = $2::jsonb, monthly_quests = $3::jsonb, epic_quests = $4::jsonb, vip_quests = $5::jsonb
                WHERE user_id = $6
            """, json.dumps(daily), json.dumps(weekly), json.dumps(monthly), json.dumps(epic), json.dumps(vip), user_id)

    if is_callback:
        await callback_obj.answer(get_str("qs_alert_all_success", _, count=completed_count), show_alert=False)
        
    extra_str = "".join(extra_text_lines)
    if extra_str:
        extra_str = get_str("qs_all_extra_title", _, extra=extra_str)

    from core.database import get_user_name
    actual_name = await get_user_name(user_id, message_obj.from_user.first_name if not is_callback else callback_obj.from_user.first_name)
    user_mention = f"<a href='tg://user?id={user_id}'>{actual_name}</a>"

    success_msg = get_str("qs_all_success_msg", _, user_mention=user_mention, count=completed_count, money=fmt(total_money), extra=extra_str)
    
    if is_callback:
        await message_obj.answer(success_msg, parse_mode="HTML")
        await send_quests_menu(user_id, message_obj, "daily", is_edit=True, _=_)
    else:
        await message_obj.reply(success_msg, parse_mode="HTML")

# ==========================================
# 🧠 УНИВЕРСАЛЬНЫЙ ТРИГГЕР (ДАТЧИК ДЕЙСТВИЙ)
# ==========================================
async def process_quest_action(user_id: int, action_type: str, amount: float = 1.0, is_absolute: bool = False):
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            row = await db.fetchrow("SELECT daily_quests, weekly_quests, monthly_quests, epic_quests, vip_quests FROM user_quests WHERE user_id = $1", user_id)
            if not row: return 
            
            quests_data = {
                "daily_quests": (json.loads(row['daily_quests']) if row['daily_quests'] else {}, DAILY_QUESTS),
                "weekly_quests": (json.loads(row['weekly_quests']) if row['weekly_quests'] else {}, WEEKLY_QUESTS),
                "monthly_quests": (json.loads(row['monthly_quests']) if row['monthly_quests'] else {}, MONTHLY_QUESTS),
                "epic_quests": (json.loads(row['epic_quests']) if row['epic_quests'] else {}, EPIC_QUESTS),
                "vip_quests": (json.loads(row.get('vip_quests', '{}')) if row.get('vip_quests') else {}, VIP_QUESTS)
            }
            
            needs_update = False
            for db_col, (user_q_dict, pool_dict) in quests_data.items():
                for q_id, q_data in user_q_dict.items():
                    if q_id in pool_dict and pool_dict[q_id]['action_type'] == action_type:
                        target = pool_dict[q_id]['target']
                        if not q_data['claimed'] and q_data['progress'] < target:
                            if is_absolute:
                                if amount > q_data['progress']:
                                    q_data['progress'] = amount
                                    needs_update = True
                            else:
                                q_data['progress'] += amount
                                needs_update = True

            if needs_update:
                await db.execute("""
                    UPDATE user_quests 
                    SET daily_quests = $1::jsonb, weekly_quests = $2::jsonb, monthly_quests = $3::jsonb, epic_quests = $4::jsonb, vip_quests = $5::jsonb
                    WHERE user_id = $6
                """, 
                json.dumps(quests_data["daily_quests"][0]), 
                json.dumps(quests_data["weekly_quests"][0]), 
                json.dumps(quests_data["monthly_quests"][0]), 
                json.dumps(quests_data["epic_quests"][0]), 
                json.dumps(quests_data["vip_quests"][0]), 
                user_id)
                
    except Exception as e:
        print(f"❌ Ошибка в process_quest_action: {e}")