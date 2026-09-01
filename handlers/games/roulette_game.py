import asyncio
import logging
import re
import random
import time        
import os
import html
import json
from aiogram import Router, types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import FSInputFile

# Импортируем функции БД
from core.database import check_and_apply_cashback, get_db, get_balance, add_balance, save_spin_to_db, load_history_from_db
from handlers.users.quests import process_quest_action

router = Router()

ADMIN_ID = 1412940726

current_bets = {}
last_round_bets = {}
is_spinning = set()
roulette_history = {}
spinning_bets = {}
chat_roulette_cooldown = {}
round_start_time = {}
last_spin_time = {}
cached_roulette_gif_id = None

# 🔥 ПАМЯТЬ КАЗИНО (Запоминаем 10 последних профитов и ставок)
player_recent_10 = {} 

RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}

# ==========================================
# 🌐 МУЛЬТИЯЗЫЧНЫЙ ДВИЖОК ДЛЯ ИГРОВЫХ ЗОН (ВАРИАНТ А)
# ==========================================
LOCALES = {}
for lang in ["ru", "en"]:
    path = f"locales/{lang}.json"
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                LOCALES[lang] = json.load(f)
        except Exception as e:
            logging.error(f"Ошибка загрузки локали {lang} в рулетке: {e}")

def get_translator(lang: str):
    """Фабрика функций перевода"""
    target_lang = lang if lang in LOCALES else "ru"
    def translate(key: str, **kwargs) -> str:
        text = LOCALES[target_lang].get(key, LOCALES["ru"].get(key, key))
        if kwargs:
            try: return text.format(**kwargs)
            except: pass
        return text
    return translate

async def resolve_chat_translator(chat_id: int, default__ = None):
    """Определяет язык игрового узла (чата) и выдает нужный пакет строк"""
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            # Запрос к таблице конфигурации чатов (если она есть)
            chat_lang = await db.fetchval("SELECT lang FROM chats WHERE chat_id = $1", chat_id)
            if chat_lang:
                return get_translator(chat_lang)
    except:
        pass # Если таблицы чатов нет — плавно падаем на дефолт чата или RU
    return default__ if default__ else get_translator("ru")


# ==========================================
# 🗄 ИНИЦИАЛИЗАЦИЯ И СИСТЕМНАЯ ЛОГИКА
# ==========================================
async def init_roulette():
    global roulette_history
    roulette_history = await load_history_from_db()

async def init_history_db():
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_game_history (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                is_win INTEGER,
                timestamp BIGINT
            )
        """)

def check_if_win(target, res_num):
    if target.isdigit(): return int(target) == res_num
    if target in ["красное", "red", "к"]: return res_num in RED_NUMBERS
    if target in ["черное", "black", "ч"]: return res_num not in RED_NUMBERS and res_num != 0
    is_even = (res_num % 2 == 0) and (res_num != 0)
    if target in ["even", "четное", "чет", "евен"]: return is_even
    if target in ["odd", "нечетное", "нечет", "одд"]: return not is_even and res_num != 0
    if "-" in target:
        try:
            start_n, end_n = map(int, target.split("-"))
            return start_n <= res_num <= end_n
        except ValueError: return False
    return False

def calculate_win(amount, target, res_num):
    if not check_if_win(target, res_num): return 0
    if target in ["красное", "red", "к", "черное", "black", "ч", "even", "четное", "чет", "евен", "odd", "нечетное", "нечет", "одд"]:
        return amount * 2
    elif target == "0" or target.isdigit():
        return amount * 36
    elif "-" in target:
        try:
            start_n, end_n = map(int, target.split("-"))
            numbers_count = end_n - start_n + 1
            if numbers_count > 0: return int(amount * (36 / numbers_count))
        except ValueError: pass
    return 0

def generate_smart_roulette_result(current_bets: list, payouts: list, user_cache: dict, player_memories: dict) -> int:
    total_pool = sum(bet['amount'] for bet in current_bets)
    safe_outcomes = [p for p in payouts if p['payout'] <= max(total_pool * 2.5, 50_000_000)]
    if not safe_outcomes:
        payouts.sort(key=lambda x: x['payout'])
        safe_outcomes = payouts[:3]

    weights = {p['num']: 10.0 for p in safe_outcomes}
    if 0 in weights: weights[0] = 2.0 

    max_possible_payout = max(p['payout'] for p in payouts)
    if max_possible_payout > total_pool * 0.7 and total_pool > 1_000_000:
        if 0 in weights: weights[0] *= random.uniform(2.0, 4.0) 

    for b in current_bets:
        uid = b['user_id']
        amount = b['amount']
        target = b['target']
        
        u_data = user_cache.get(uid, {})
        balance = max(u_data.get('balance', 1), 1)
        is_lucky = u_data.get('is_lucky', False)
        wins_streak = u_data.get('wins_count', 0)
        loses_streak = u_data.get('loses_count', 0)
        
        history_10 = player_memories.get(uid, [])
        net_10 = sum(h['net'] for h in history_10) if history_10 else 0
        grid_bet = sum(h['bet'] for h in history_10) / len(history_10) if history_10 else amount
        aggressiveness = min(amount / balance, 1.0)
        
        is_fake_loser = (net_10 < 0) and (amount > grid_bet * 3)
        is_greedy = (net_10 > 0 and amount > grid_bet * 1.5) or (aggressiveness > 0.3) or (wins_streak >= 3)
        is_desperate = (net_10 < 0 and loses_streak >= 3 and not is_fake_loser and aggressiveness < 0.2)
        luck_modifier = random.uniform(1.1, 1.4) if is_lucky else 1.0

        for num in weights.keys():
            if calculate_win(amount, target, num) > 0:
                if is_fake_loser: weights[num] *= random.uniform(0.3, 0.5)
                elif is_greedy: weights[num] *= min(random.uniform(0.1, 0.3) * luck_modifier, 1.0)
                elif is_desperate: weights[num] *= random.uniform(1.5, 3.5) * luck_modifier
                else: weights[num] *= random.uniform(0.8, 1.2)

    numbers = list(weights.keys())
    w = list(weights.values())
    if sum(w) <= 0.1: return random.choice(numbers)
    return random.choices(numbers, weights=w, k=1)[0]
    
def fmt(num): return f"{int(num):,}".replace(",", " ")
def get_roulette_color(num): return "🟢" if num == 0 else ("🔴" if num in RED_NUMBERS else "⚫️")

# ==========================================
# 🔥 АНИМАЦИЯ КРУЧЕНИЯ
# ==========================================
async def spin_with_animation(message: types.Message, result_number: int, players_count: int = 1, _ = None):
    current_dir = os.path.dirname(os.path.abspath(__file__))
    gif_path = os.path.join(current_dir, "..", "..", "assets", "media", "roulette.gif")

    tape = [random.randint(0, 36) for _ in range(10)] + [result_number] + [random.randint(0, 36) for _ in range(2)]
    start_window = tape[0:5]
    start_str = " ".join([f"[{get_roulette_color(n)} {n:2}]" for n in start_window])
    stage_1 = _("rl_spin_started", tape=start_str)

    global cached_roulette_gif_id
    msg = None

    try:
        animation_payload = cached_roulette_gif_id if cached_roulette_gif_id else FSInputFile(gif_path)
        msg = await message.answer_animation(animation=animation_payload, caption=stage_1, parse_mode="HTML")
        if not cached_roulette_gif_id and msg:
            if msg.animation: cached_roulette_gif_id = msg.animation.file_id
            elif msg.document: cached_roulette_gif_id = msg.document.file_id
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after + 0.5)
        try:
            animation_payload = cached_roulette_gif_id if cached_roulette_gif_id else FSInputFile(gif_path)
            msg = await message.answer_animation(animation=animation_payload, caption=stage_1, parse_mode="HTML")
        except: pass
    except Exception as e:
        logging.error(f"Ошибка отправки гифки: {e}")

    await asyncio.sleep(2.0)

    mid_window = tape[5:10]
    mid_str = " ".join([f"[{get_roulette_color(n)} {n:2}]" for n in mid_window])
    stage_2 = _("rl_spin_slowing", tape=mid_str)

    if msg:
        try: await msg.edit_caption(caption=stage_2, parse_mode="HTML")
        except TelegramRetryAfter as e: await asyncio.sleep(e.retry_after + 0.5)
        except: pass

    await asyncio.sleep(1.0)

    final_window = tape[8:13]
    final_str = ""
    for idx, n in enumerate(final_window):
        color = get_roulette_color(n)
        if idx == 2: final_str += f" <b>►[{color} {n:2}]◄</b> "
        else: final_str += f" [{color} {n:2}] "
        
    final_stage = _("rl_spin_stopped", tape=final_str)

    if msg:
        retry_count = 0
        while retry_count < 3:
            try:
                await msg.edit_caption(caption=final_stage, parse_mode="HTML")
                break
            except TelegramRetryAfter as e:
                retry_count += 1
                await asyncio.sleep(e.retry_after + 0.5)
            except Exception:
                try:
                    await message.answer(final_stage, parse_mode="HTML")
                    break
                except: break
        try: await msg.delete()
        except: pass

# ==========================================
# 🎰 ПРИЁМ СТАВОК (ЯЗЫК ЧАТА)
# ==========================================
BET_PATTERN = re.compile(r"^(вс[её]|all|\d+[kкmм]*)\s+(.+)$", re.IGNORECASE | re.DOTALL)
VALID_BET_WORDS = {
    "красное", "red", "к", "черное", "black", "ч", 
    "0", "odd", "even", "четное", "нечетное", "чет", "нечет", "евен", "одд"
}

@router.message(F.text.regexp(BET_PATTERN))
async def place_roulette_bet(message: types.Message, _ = None):
    chat_id = message.chat.id
    # 🔥 ЖЕСТКАЯ ПРИВЯЗКА К ЯЗЫКУ ТЕКУЩЕЙ ГРУППЫ
    _ = await resolve_chat_translator(chat_id, _)

    clean_text = message.text.lower().replace('\xa0', ' ')
    match = BET_PATTERN.match(clean_text)
    amount_str = match.group(1).replace('к', '000').replace('k', '000').replace('м', '000000').replace('m', '000000')
    
    is_all_in = amount_str in ["все", "всё", "all"]
    targets_raw = match.group(2).replace(",", " ").split() 
    valid_targets = []
    
    for t in targets_raw:
        if t in ["на", "on"]: continue
        if t in VALID_BET_WORDS: valid_targets.append(t)
        elif t.isdigit() and 0 <= int(t) <= 36:
            if (int(t) == 0 and len(t) > 1) or (int(t) > 0 and t.startswith('0')): return
            valid_targets.append(t)
        elif re.match(r"^\d{1,2}-\d{1,2}$", t):
            start_n, end_n = map(int, t.split("-"))
            if start_n >= end_n or end_n > 36: return 
            valid_targets.append(t)
        else: return 
            
    if not valid_targets: return 

    if chat_id in is_spinning:
        msg = await message.reply(_("rl_table_closed"), parse_mode="HTML")
        await asyncio.sleep(3); await msg.delete()
        return

    user_id = message.from_user.id
    current_balance = await get_balance(user_id)

    if is_all_in:
        if current_balance <= 0: return await message.reply(_("rl_zero_balance"))
        amount = current_balance // len(valid_targets)
        if amount <= 0: return await message.reply(_("rl_insufficient_split"))
    else:
        try: amount = int(amount_str)
        except ValueError: return
        if amount <= 0: return

    if chat_id not in current_bets or not current_bets[chat_id]: 
        current_bets[chat_id] = []
        round_start_time[chat_id] = time.time()
        
    name = html.escape(message.from_user.first_name)
    await process_quest_action(user_id, "roulette_bet_distinct", len(valid_targets))

    user_bets_count = sum(1 for b in current_bets[chat_id] if b['user_id'] == user_id)
    if user_bets_count + len(valid_targets) > 200:
        return await message.reply(_("rl_personal_limit", current=user_bets_count))

    if len(current_bets[chat_id]) + len(valid_targets) > 1500:
        return await message.reply(_("rl_table_limit", current=len(current_bets[chat_id])))

    total_bet = amount * len(valid_targets)
    if current_balance < total_bet: return await message.reply(_("rl_insufficient_funds"))

    await add_balance(user_id, -total_bet)
    all_in_text = _("rl_all_in_badge") if is_all_in else ""
    
    for t in valid_targets:
        if t in ["к", "красное", "red"]: display_target = "🔴"
        elif t in ["ч", "черное", "black"]: display_target = "⚫️"
        elif t in ["even", "четное", "чет", "евен"]: display_target = _("rl_display_even")
        elif t in ["odd", "нечетное", "нечет", "одд"]: display_target = _("rl_display_odd")
        else: display_target = t
            
        current_bets[chat_id].append({
            'user_id': user_id, 'name': name, 'amount': amount, 
            'target': t, 'display': display_target
        })

    if len(valid_targets) <= 10:
        reply_lines = []
        for t in valid_targets:
            if t in ["к", "красное", "red"]: d = "🔴"
            elif t in ["ч", "черное", "black"]: d = "⚫️"
            elif t in ["even", "четное", "чет", "евен"]: d = _("rl_display_even")
            elif t in ["odd", "нечетное", "нечет", "одд"]: d = _("rl_display_odd")
            else: d = t
            reply_lines.append(_("rl_bet_accepted_single", name=name, amount=fmt(amount), target=d, all_in=all_in_text))
        await message.answer("\n".join(reply_lines), parse_mode="HTML")
    else:
        await message.answer(_("rl_bet_accepted_multi", name=name, count=len(valid_targets), amount=fmt(amount), all_in=all_in_text, total=fmt(total_bet)), parse_mode="HTML")

# ==========================================
# 🎰 ДВИЖОК СТАТИСТИКИ И ИТОГОВЫХ ЛОГОВ (ЯЗЫК ЧАТА)
# ==========================================
@router.message(F.text.lower().in_(["отмена", "отменить", "cancel", "abort"]))
async def cancel_all_user_bets(message: types.Message, _ = None):
    chat_id = message.chat.id
    _ = await resolve_chat_translator(chat_id, _)
    user_id = message.from_user.id

    if chat_id in is_spinning:
        msg = await message.reply(_("rl_cancel_late"), parse_mode="HTML")
        await asyncio.sleep(3); await msg.delete()
        return
    
    if chat_id in current_bets:
        user_bets = [b for b in current_bets[chat_id] if b['user_id'] == user_id]
        if user_bets:
            total_refund = sum(b['amount'] for b in user_bets)
            await add_balance(user_id, total_refund)
            current_bets[chat_id] = [b for b in current_bets[chat_id] if b['user_id'] != user_id]
            return await message.reply(_("rl_cancel_success", amount=fmt(total_refund)), parse_mode="HTML")
            
    await message.reply(_("rl_cancel_none"))

# ==========================================
# 🎰 ПРОСМОТР СТАВОК РУЛЕТКИ (SAFE CHUNKING)
# ==========================================
@router.message(F.text.lower().in_(["ставки", "bets", "all bets"]))
async def show_bets(message: types.Message, _ = None):
    chat_id = message.chat.id
    _ = await resolve_chat_translator(chat_id, _)
    
    bets = current_bets.get(chat_id)
    if not bets:
        return await message.reply(_("rl_no_bets_chat"), parse_mode="HTML")
        
    title = _("rl_current_bets_title")
    lines = []
    total_pool_sum = 0
    
    for b in bets:
        amount = b.get('amount', 0)
        total_pool_sum += amount
        
        # 🔥 Защита от HTML-инъекций и битых символов в никах
        safe_name = html.escape(str(b.get('name', 'Агент')))
        safe_display = html.escape(str(b.get('display', '')))
        
        lines.append(f"• <b>{safe_name}</b>: {fmt(amount)} ᴜ на <code>{safe_display}</code>")

    # 🛡 ДИНАМИЧЕСКАЯ УПАКОВКА В ЧАНКИ (ЛИМИТ TELEGRAM 4096 СИМВОЛОВ)
    MAX_CHUNK_LEN = 3800
    chunks = []
    current_chunk = [title]
    current_len = len(title)

    for line in lines:
        line_len = len(line) + 1  # Учитываем \n
        if current_len + line_len > MAX_CHUNK_LEN:
            chunks.append("\n".join(current_chunk))
            current_chunk = [line]
            current_len = line_len
        else:
            current_chunk.append(line)
            current_len += line_len

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    # 🚀 ОПТИМИЗАЦИЯ ВЫВОДА
    if len(chunks) > 3:
        # Если ставок критически много — выводим 1-й чанк и сводку, чтобы не забивать чат флудом
        summary = (
            f"\n\n📊 <b>ИТОГО В ПУЛЕ:</b> <b>{fmt(total_pool_sum)} ᴜ</b> ({len(bets)} шт.)\n"
            f"⚠️ <i>Список слишком длинный. Показано первых {len(lines[:len(chunks[0].splitlines())-1])} ставок.</i>"
        )
        await message.reply(chunks[0] + summary, parse_mode="HTML")
    else:
        # Если чанков 1-3 — отправляем их по очереди
        for i, chunk_text in enumerate(chunks):
            if i == len(chunks) - 1:
                chunk_text += f"\n\n💰 <b>Общий пул ставок:</b> <b>{fmt(total_pool_sum)} ᴜ</b>"
            await message.reply(chunk_text, parse_mode="HTML")


# ==========================================
# 🧠 БЕЗОПАСНАЯ СОРТИРОВКА ЦЕЛЕЙ РУЛЕТКИ
# ==========================================
def sort_roulette_targets(targets):
    """
    Сортирует цели рулетки по группам:
    1. Диапазоны (1-12, 13-24) — по возрастанию первого числа.
    2. Числа (0, 1, 2... 36) — по возрастанию.
    3. Слова (red, black, even...) — по алфавиту.
    """
    ranges, numbers, words = [], [], []
    
    for t in targets:
        t_str = str(t).strip()
        if '-' in t_str:
            parts = t_str.split('-')
            # Валидация строго формата "X-Y", где X и Y — числа
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                ranges.append((int(parts[0]), t_str))
            else:
                words.append(t_str)
        elif t_str.isdigit():
            numbers.append(int(t_str))
        else:
            words.append(t_str)
            
    # Сортировка каждой группы
    ranges.sort(key=lambda x: x[0])
    numbers.sort()
    words.sort()
    
    return [r[1] for r in ranges] + [str(n) for n in numbers] + words

@router.message(F.text.lower().in_(["го", "go", "spin", "крутить"]))
async def spin_roulette(message: types.Message, _ = None):
    chat_id = message.chat.id
    # 🔥 Фиксируем язык группы перед броском шарика!
    _ = await resolve_chat_translator(chat_id, _)
    user_id = message.from_user.id 

    if chat_id in is_spinning: return 
    if chat_id not in current_bets or not current_bets[chat_id]:
        return await message.reply(_("rl_no_active_bets"))

    unique_players = len(set(b['user_id'] for b in current_bets[chat_id]))
    if unique_players == 1: required_delay = 15 
    elif unique_players <= 3: required_delay = 20 
    else: required_delay = 25 

    elapsed_time = time.time() - round_start_time.get(chat_id, 0)
    time_left = int(required_delay - elapsed_time)

    if time_left > 0:
        now = time.time()
        if now - chat_roulette_cooldown.get(chat_id, 0) > 4:
            chat_roulette_cooldown[chat_id] = now
            return await message.reply(_("rl_croupier_accepting", players=unique_players, time=time_left), parse_mode="HTML")
        return 
        
    round_start_time.pop(chat_id, None)
    if not any(bet['user_id'] == user_id for bet in current_bets[chat_id]): return 

    is_spinning.add(chat_id)

    try:
        round_bets = current_bets[chat_id].copy()
        spinning_bets[chat_id] = round_bets
        current_bets[chat_id] = []

        user_ids = list(set(b['user_id'] for b in round_bets))
        user_cache = {}
        
        pool = await get_db()
        async with pool.acquire() as db:
            rows = await db.fetch("SELECT user_id, balance FROM users WHERE user_id = ANY($1::bigint[])", user_ids)
            for row in rows:
                user_cache[row['user_id']] = {'balance': row['balance'], 'is_lucky': False, 'is_arch': False, 'wins_count': 0, 'loses_count': 0}

            rows = await db.fetch("SELECT user_id FROM user_statuses WHERE status_id = 4 AND expire_timestamp > $1 AND user_id = ANY($2::bigint[])", int(time.time()), user_ids)
            for row in rows:
                if row['user_id'] in user_cache: user_cache[row['user_id']]['is_arch'] = True

            query = """
                SELECT user_id, SUM(is_win) as wins_count, SUM(CASE WHEN is_win = 0 THEN 1 ELSE 0 END) as loses_count
                FROM (
                    SELECT user_id, is_win, ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY timestamp DESC) as rn
                    FROM user_game_history WHERE user_id = ANY($1::bigint[])
                ) sub WHERE rn <= 5 GROUP BY user_id
            """
            rows = await db.fetch(query, user_ids)
            for row in rows:
                uid = row['user_id']
                if uid in user_cache: 
                    user_cache[uid]['wins_count'] = row['wins_count'] or 0
                    user_cache[uid]['loses_count'] = row['loses_count'] or 0

            rows = await db.fetch("SELECT user_id FROM user_statuses WHERE status_id = 3 AND expire_timestamp > $1 AND user_id = ANY($2::bigint[])", int(time.time()), user_ids)
            for row in rows:
                if row['user_id'] in user_cache: user_cache[row['user_id']]['is_lucky'] = True

        payouts = []
        for num in range(37):
            num_payout = sum(calculate_win(b['amount'], b['target'], num) for b in round_bets)
            payouts.append({'num': num, 'payout': num_payout})

        result_number = None
        admin_bets = [b for b in round_bets if b['user_id'] == ADMIN_ID]
        if admin_bets and random.random() < 0.0:
            lucky_bet = random.choice(admin_bets)
            target = lucky_bet['target']
            if target.isdigit(): result_number = int(target)
            elif target in ["к", "red", "красное"]: result_number = random.choice(list(RED_NUMBERS))
            elif target in ["ч", "black", "черное"]: result_number = random.choice([n for n in range(1, 37) if n not in RED_NUMBERS])
            elif target in ["even", "четное", "чет", "евен"]: result_number = random.choice([n for n in range(1, 37) if n % 2 == 0])
            elif target in ["odd", "нечетное", "нечет", "одд"]: result_number = random.choice([n for n in range(1, 37) if n % 2 != 0])
            elif target == "0": result_number = 0

        if result_number is None:
            result_number = generate_smart_roulette_result(round_bets, payouts, user_cache, player_recent_10)

        await spin_with_animation(message, result_number, len(user_ids), _)

        from core import bot_state
        if bot_state.IS_SHUTTING_DOWN:
            try: await message.answer(_("rl_hard_shutdown"), parse_mode="HTML")
            except: pass

        log_emoji = "🟢" if result_number == 0 else ("🔴" if result_number in RED_NUMBERS else "⚫️")
        res_text = f"{result_number}{log_emoji}"
        
        if chat_id not in roulette_history: roulette_history[chat_id] = []
        roulette_history[chat_id].insert(0, res_text)
        if len(roulette_history[chat_id]) > 10: roulette_history[chat_id].pop()

        await save_spin_to_db(chat_id, res_text)

        winners_text, bet_lines, history_records = [], [], []
        is_compact = len(round_bets) > 10 
        total_pool = sum(b['amount'] for b in round_bets)
        
        if is_compact:
            bet_lines.append(_("rl_total_bets_count", count=len(round_bets)))
            bet_lines.append(_("rl_total_table_pool", pool=fmt(total_pool)))
            
        user_round_data = {}
        for bet in round_bets:
            u_id = bet['user_id']
            name = bet['name']
            amount = bet['amount']
            target = bet['target']
            display = bet['display']
            
            mention = f'<a href="tg://user?id={u_id}">{name}</a>'
            if not is_compact: 
                bet_lines.append(f"👤 {mention}: <b>{fmt(amount)} ᴜ</b> на <b>{display}</b>")
            
            if u_id not in user_round_data: 
                user_round_data[u_id] = {'name': mention, 'win': 0, 'cb': 0, 'targets': {}, 'won_targets': {}, 'has_win': False, 'total_bet': 0}
            
            user_round_data[u_id]['total_bet'] += amount
            if display not in user_round_data[u_id]['targets']: user_round_data[u_id]['targets'][display] = 0
            user_round_data[u_id]['targets'][display] += amount
            
            win = calculate_win(amount, target, result_number)
            if win > 0:
                user_round_data[u_id]['has_win'] = True
                if display not in user_round_data[u_id]['won_targets']: user_round_data[u_id]['won_targets'][display] = 0
                user_round_data[u_id]['won_targets'][display] += amount
                await add_balance(u_id, win) 
                user_round_data[u_id]['win'] += win
            else:
                cashback = await check_and_apply_cashback(u_id, amount)
                if cashback > 0: user_round_data[u_id]['cb'] += cashback

        winners_list, jackpot_lines = [], []
        for u_id, data in user_round_data.items():
            is_win = 1 if data['has_win'] else 0
            history_records.append((u_id, is_win, int(time.time())))

            await process_quest_action(u_id, "roulette_spin", 1)
            if data['win'] > 0: await process_quest_action(u_id, "roulette_win", data['win'])

            try:
                from core.database import change_rating
                if is_win == 1: await change_rating(u_id, 1)
                else: await change_rating(u_id, -2)
            except: pass

            net_profit = (data['win'] + data['cb']) - data['total_bet']
            if u_id not in player_recent_10: player_recent_10[u_id] = []
            player_recent_10[u_id].append({'net': net_profit, 'bet': data['total_bet']})
            if len(player_recent_10[u_id]) > 10: player_recent_10[u_id].pop(0)

            if is_compact:
                sorted_targets = sort_roulette_targets(list(data['targets'].keys()))
                targets_formatted = [f"<b>{t}</b>" for t in sorted_targets]
                targets_str = ", ".join(targets_formatted[:10]) + f" ...и ещё {len(targets_formatted) - 10}" if len(targets_formatted) > 10 else ", ".join(targets_formatted)
                cb_text = _("rl_cashback_badge", amount=fmt(data['cb'])) if data['cb'] > 0 else ""
                winners_text.append(_("rl_compact_row", name=data['name'], bet=fmt(data['total_bet']), targets=targets_str, cb=cb_text))

            if data['has_win']:
                sorted_won = sort_roulette_targets(list(data['won_targets'].keys()))
                won_formatted = [f"<b>{t}</b>" for t in sorted_won]
                won_str = ", ".join(won_formatted[:10]) + f" ...и ещё {len(won_formatted) - 10}" if len(won_formatted) > 10 else ", ".join(won_formatted)
                
                if is_compact: winners_list.append(_("rl_compact_win_row", name=data['name'], win=fmt(data['win']), won=won_str))
                else: winners_list.append(_("rl_normal_win_row", name=data['name'], won=won_str, win=fmt(data['win'])))

        async with pool.acquire() as db:
            jackpot_pool = await db.fetchval("SELECT pool FROM roulette_jackpot WHERE id = 1") or 0
            for u_id, data in user_round_data.items():
                is_win = 1 if data['has_win'] else 0
                net_profit = (data['win'] + data['cb']) - data['total_bet']

                await db.execute("""
                    INSERT INTO user_roulette_stats (user_id, total_spins, total_wins, biggest_bet, biggest_win, win_streak)
                    VALUES ($1, 1, $2, $3, $4, $2) ON CONFLICT (user_id) DO UPDATE SET
                        total_spins = user_roulette_stats.total_spins + 1,
                        total_wins = user_roulette_stats.total_wins + $2,
                        biggest_bet = GREATEST(user_roulette_stats.biggest_bet, $3),
                        biggest_win = GREATEST(user_roulette_stats.biggest_win, $4),
                        win_streak = CASE WHEN $2 = 1 THEN user_roulette_stats.win_streak + 1 ELSE 0 END
                """, u_id, is_win, data['total_bet'], data['win'])

                if result_number == 0 and "0" in data['targets']:
                    if random.random() < 0.05 and jackpot_pool > 100_000:
                        await add_balance(u_id, jackpot_pool)
                        await db.execute("UPDATE roulette_jackpot SET pool = 0 WHERE id = 1")
                        await db.execute("UPDATE user_roulette_stats SET jackpots_won = jackpots_won + 1 WHERE user_id = $1", u_id)
                        jackpot_lines.append(_("rl_jackpot_win", name=data['name'], pool=fmt(jackpot_pool)))
                        jackpot_pool = 0

                if net_profit < 0:
                    tax_to_jackpot = int(abs(net_profit) * 0.01)
                    await db.execute("UPDATE roulette_jackpot SET pool = LEAST(500000000, pool + $1) WHERE id = 1", tax_to_jackpot)

            await db.executemany("INSERT INTO user_game_history (user_id, is_win, timestamp) VALUES ($1, $2, $3)", history_records)

        header = _("rl_result_header", result=result_number, emoji=log_emoji)
        inner_lines = ["━━━━━━━━━━━━━━━━━━━━"]

        if is_compact:
            inner_lines.append(_("rl_total_bets_count", count=len(round_bets)))
            inner_lines.append(_("rl_total_table_pool", pool=fmt(total_pool)))
            if winners_text: inner_lines += [""] + winners_text
            if winners_list: inner_lines += [""] + winners_list
        else:
            inner_lines += bet_lines
            if winners_list: inner_lines += [""] + winners_list

        if jackpot_lines: inner_lines += [""] + jackpot_lines
        inner_lines.append("━━━━━━━━━━━━━━━━━━━━")

        game_report_content = "\n".join(inner_lines)
        messages_to_send = []
        current_msg = header + game_report_content

        if len(current_msg) > 3900: messages_to_send = [header, game_report_content]
        else:
            messages_to_send.append(current_msg)
            last_round_bets[chat_id] = round_bets

        builder = InlineKeyboardBuilder()
        builder.button(text=_("rl_btn_repeat"), callback_data=f"roul_repeat_{chat_id}")
        builder.button(text=_("rl_btn_double"), callback_data=f"roul_double_{chat_id}")
        builder.adjust(2)

        for i in range(len(messages_to_send) - 1):
            retry = 0
            while retry < 3:
                try:
                    await message.answer(messages_to_send[i], parse_mode="HTML")
                    await asyncio.sleep(0.5)
                    break
                except TelegramRetryAfter as e:
                    retry += 1
                    await asyncio.sleep(e.retry_after + 0.5)
                except: break

        retry = 0
        while retry < 3:
            try:
                await message.answer(messages_to_send[-1], reply_markup=builder.as_markup(), parse_mode="HTML")
                break
            except TelegramRetryAfter as e:
                retry += 1
                await asyncio.sleep(e.retry_after + 0.5)
            except: break

    except Exception as e: logging.error(f"Ошибка в рулетке: {e}")
    finally:
        is_spinning.discard(chat_id)
        spinning_bets.pop(chat_id, None)

# ==========================================
# 🔄 КНОПКИ ПОВТОРОВ (ЯЗЫК ЧАТА)
# ==========================================
@router.callback_query(F.data.startswith("roul_"))
async def process_roulette_buttons(callback: types.CallbackQuery, _ = None):
    data = callback.data.split("_")
    action, chat_id = data[1], int(data[2])
    # 🔥 Кнопки работают строго на языке группы
    _ = await resolve_chat_translator(chat_id, _)
    
    user_id = callback.from_user.id
    name = html.escape(callback.from_user.first_name)
    
    if chat_id in is_spinning: return await callback.answer(_("rl_btn_spinning"), show_alert=True)
    if chat_id not in last_round_bets: return await callback.answer(_("rl_btn_lost_data"), show_alert=True)

    user_last_bets = [b for b in last_round_bets[chat_id] if b['user_id'] == user_id]
    if not user_last_bets: return await callback.answer(_("rl_btn_not_participated"), show_alert=True)
    
    current_table_count = len(current_bets.get(chat_id, []))
    if current_table_count + len(user_last_bets) > 1500: return await callback.answer(_("rl_btn_limit_overflow"), show_alert=True)

    multiplier = 2 if action == "double" else 1
    total_needed = sum(b['amount'] for b in user_last_bets) * multiplier

    if await get_balance(user_id) < total_needed: return await callback.answer(_("rl_btn_no_money", total=total_needed), show_alert=True)
    await add_balance(user_id, -total_needed)
    
    if chat_id not in current_bets or not current_bets[chat_id]:
        current_bets[chat_id] = []
        round_start_time[chat_id] = time.time() 
        
    for b in user_last_bets:
        new_amt = b['amount'] * multiplier
        current_bets[chat_id].append({
            'user_id': user_id, 'name': name, 'amount': new_amt, 
            'target': b['target'], 'display': b['display']
        })

    await callback.answer(_("rl_btn_accepted_alert"))
    act_text = _("rl_action_doubled") if multiplier == 2 else _("rl_action_repeated")
    await callback.message.answer(_("rl_btn_broadcast_action", name=name, action=act_text, amount=fmt(total_needed)), parse_mode="HTML")

# ==========================================
# 📊 СТАТИСТИКА И ИСТОРИЯ (ИНДИВИДУАЛЬНО)
# ==========================================
@router.message(F.text.lower().in_(["лог", "log", "history"]))
async def show_roulette_log(message: types.Message, _ = None):
    chat_id = message.chat.id
    _ = await resolve_chat_translator(chat_id, _)
    history = roulette_history.get(chat_id, [])
    if not history: return await message.reply(_("rl_log_empty"))
    await message.reply(f"\n\n" + "\n".join(history), parse_mode="HTML")

@router.message(F.text.lower().in_(["опыт рулетка", "опыт рулетки", "стата рулетка", "мой опыт", "roulette stats", "my stats", "my experience"]))
async def cmd_roulette_experience(message: types.Message, _ = None):
    # 👤 Личная статистика пишется на языке, который заинжектил L10nMiddleware (язык юзера)
    user_id = message.from_user.id
    from core.database import get_user_name
    name = await get_user_name(user_id, message.from_user.first_name)
    
    pool = await get_db()
    async with pool.acquire() as db:
        stats = await db.fetchrow("SELECT * FROM user_roulette_stats WHERE user_id = $1", user_id)

    if not stats: return await message.reply(_("rl_stats_empty"))

    win_rate = (stats['total_wins'] / stats['total_spins'] * 100) if stats['total_spins'] > 0 else 0
    achievements = []
    if stats['jackpots_won'] > 0: achievements.append(_("rl_ach_jackpot"))
    if stats['win_streak'] >= 5: achievements.append(_("rl_ach_streak"))
    if stats['biggest_win'] >= 100_000_000: achievements.append(_("rl_ach_highroller"))
    if stats['total_spins'] >= 1000: achievements.append(_("rl_ach_veteran"))
    
    ach_text = "\n".join([f"├ {a}" for a in achievements]) if achievements else _("rl_ach_none")

    await message.reply(
        _("rl_stats_main", name=name, spins=stats['total_spins'], wins=stats['total_wins'], rate=win_rate, streak=stats['win_streak'], max_bet=fmt(stats['biggest_bet']), max_win=fmt(stats['biggest_win']), achievements=ach_text),
        parse_mode="HTML"
    )

@router.message(F.text.lower().strip().in_(["очистить джекпот", "clear jackpot"]))
async def admin_clear_jackpot(message: types.Message, _ = None):
    if message.from_user.id != ADMIN_ID: return
    _ = await resolve_chat_translator(message.chat.id, _)
        
    pool = await get_db()
    async with pool.acquire() as db:
        try:
            await db.execute("UPDATE jackpot SET amount = 0")
            await db.execute("UPDATE roulette_jackpot SET pool = 0 WHERE id = 1")
            await message.reply(_("rl_admin_clear_jackpot"), parse_mode="HTML")
        except Exception as e:
            await message.reply(f"❌ Error: {e}")