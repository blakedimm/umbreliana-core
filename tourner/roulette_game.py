import asyncio
import logging
import re
import random
import time        
import html
from aiogram import Router, types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramRetryAfter

# 🔥 ПЛОСКИЕ ИМПОРТЫ
from database import get_db, get_balance, add_balance

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

RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}

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
        await db.execute('''
            CREATE TABLE IF NOT EXISTS roulette_history (
                id SERIAL PRIMARY KEY, chat_id BIGINT, result TEXT
            )
        ''')

async def save_spin_to_db(chat_id, result_text):
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute("INSERT INTO roulette_history (chat_id, result) VALUES ($1, $2)", chat_id, result_text)

async def load_history_from_db():
    pool = await get_db()
    async with pool.acquire() as db:
        rows = await db.fetch("SELECT chat_id, result FROM roulette_history ORDER BY id DESC LIMIT 500")
            
    history_dict = {}
    for row in rows:
        chat_id, result = row['chat_id'], row['result']
        if chat_id not in history_dict:
            history_dict[chat_id] = []
        if len(history_dict[chat_id]) < 10:
            history_dict[chat_id].append(result)
    return history_dict

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

# ==========================================
# 🔥 УМНЫЙ КРУПЬЕ 
# ==========================================
def generate_smart_roulette_result(current_bets: list, payouts: list) -> int:
    total_pool = sum(bet['amount'] for bet in current_bets)
    weights = [100.0] * 37 
    
    blacks = {2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35}

    for p in payouts:
        if p['payout'] > max(total_pool * 2, 10_000_000):
            weights[p['num']] = 35.0 

    for bet in current_bets:
        amount = bet['amount']
        target = str(bet['target']).lower()
        
        impact = min(amount / 5000.0, 0.95) 

        if target.isdigit():
            num = int(target)
            if weights[num] > 35.0: weights[num] *= (1.0 - impact)
        elif "-" in target: 
            try:
                start_n, end_n = map(int, target.split("-"))
                for i in range(start_n, end_n + 1):
                    if 0 <= i <= 36 and weights[i] > 35.0: weights[i] *= 0.01 
            except: pass
        elif target in ["красное", "red", "к"]:
            for r in RED_NUMBERS: 
                if weights[r] > 35.0: weights[r] *= (1.0 - impact)
        elif target in ["черное", "black", "ч"]:
            for b in blacks: 
                if weights[b] > 35.0: weights[b] *= (1.0 - impact)
        elif target in ["even", "четное", "чет", "евен"]:
            for i in range(2, 37, 2): 
                if weights[i] > 35.0: weights[i] *= (1.0 - impact)
        elif target in ["odd", "нечетное", "нечет", "одд"]:
            for i in range(1, 37, 2): 
                if weights[i] > 35.0: weights[i] *= (1.0 - impact)

    if sum(weights) <= 0: return random.randint(0, 36)
    return random.choices(range(37), weights=weights, k=1)[0]
    
def fmt(num): return f"{int(num):,}".replace(",", " ")

# ==========================================
# 🔥 АНИМАЦИЯ РУЛЕТКИ
# ==========================================
def get_roulette_color(num):
    if num == 0: return "🟢"
    return "🔴" if num in RED_NUMBERS else "⚫️"

async def spin_with_animation(message: types.Message, result_number: int, players_count: int = 1):
    tape = [random.randint(0, 36) for _ in range(15)] + [result_number] + [random.randint(0, 36) for _ in range(2)]
    
    stages = []
    for step in range(4):
        start_idx = step * 3  
        window = tape[start_idx : start_idx + 5]
        formatted = " ".join([f"[{get_roulette_color(n)} {n:2}]" for n in window])
        stages.append(f"🎰 <b>Колесо быстро крутится...</b>\n\n{formatted}")
        
    window = tape[11:16]
    formatted = " ".join([f"[{get_roulette_color(n)} {n:2}]" for n in window])
    stages.append(f"🎰 <b>Шарик замедляется...</b>\n\n{formatted}")
    
    final_window = tape[13:18] 
    final_str = ""
    for idx, n in enumerate(final_window):
        color = get_roulette_color(n)
        if idx == 2: final_str += f" <b>►[{color} {n:2}]◄</b> "
        else: final_str += f" [{color} {n:2}] "
            
    final_stage = f"🎯 <b>СТАВКИ СЫГРАЛИ!</b>\n\n{final_str}"

    try: msg = await message.answer(stages[0], parse_mode="HTML")
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after + 0.5)
        try: msg = await message.answer(stages[0], parse_mode="HTML")
        except: return
    except: return

    flood_hit = False
    for text in stages[1:]:
        if flood_hit: break
        await asyncio.sleep(1.3)
        try: await msg.edit_text(text, parse_mode="HTML")
        except TelegramRetryAfter as e:
            flood_hit = True
            await asyncio.sleep(e.retry_after + 0.5)
        except: pass

    if not flood_hit: await asyncio.sleep(1.5)
        
    retry_count = 0
    while retry_count < 3:
        try:
            await msg.edit_text(final_stage, parse_mode="HTML")
            break
        except TelegramRetryAfter as e:
            retry_count += 1
            await asyncio.sleep(e.retry_after + 0.5)
        except Exception:
            try: 
                await message.answer(final_stage, parse_mode="HTML")
                break
            except: break

    if flood_hit:
        retry_count = 0
        while retry_count < 3:
            try:
                await msg.edit_text(f"🎯 <b>СТАВКИ СЫГРАЛИ!</b>\n\n{final_str}", parse_mode="HTML")
                break
            except TelegramRetryAfter as e:
                retry_count += 1
                await asyncio.sleep(e.retry_after + 0.5)
            except Exception:
                try: 
                    await message.answer(f"🎯 <b>СТАВКИ СЫГРАЛИ!</b>\n\n{final_str}", parse_mode="HTML")
                    break
                except: break

# ==========================================
# 🎰 СТАВКИ
# ==========================================
BET_PATTERN = re.compile(r"^(\d+[kкmм]*)\s+(.+)$", re.IGNORECASE | re.DOTALL)

@router.message(F.text.regexp(BET_PATTERN))
async def place_roulette_bet(message: types.Message):
    chat_id = message.chat.id

    if chat_id in is_spinning:
        msg = await message.reply("⏳ <b>Стол закрыт!</b> Шарик уже крутится.", parse_mode="HTML")
        await asyncio.sleep(3); await msg.delete()
        return

    clean_text = message.text.lower().replace('\xa0', ' ')
    match = BET_PATTERN.match(clean_text)
    
    amount_str = match.group(1).replace('к', '000').replace('k', '000').replace('м', '000000').replace('m', '000000')
    try: amount = int(amount_str)
    except ValueError: return

    if amount <= 0: return await message.reply("⚠️ Ставка должна быть больше 0 UMBREL!")

    targets_raw = match.group(2).split() 
    
    if chat_id not in current_bets or not current_bets[chat_id]: 
        current_bets[chat_id] = []
        round_start_time[chat_id] = time.time()
        
    user_id = message.from_user.id
    name = html.escape(message.from_user.first_name)

    valid_targets = []
    for t in targets_raw:
        if t in ["красное", "red", "к", "черное", "black", "ч", "0", "odd", "even", "четное", "нечетное", "чет", "нечет", "евен", "одд"]:
            valid_targets.append(t)
        elif t.isdigit() and 0 <= int(t) <= 36:
            valid_targets.append(t)
        elif re.match(r"^\d{1,2}-\d{1,2}$", t):
            start_n, end_n = map(int, t.split("-"))
            if start_n >= end_n or end_n > 36: continue
            valid_targets.append(t)

    if not valid_targets: return 

    user_bets_count = sum(1 for b in current_bets[chat_id] if b['user_id'] == user_id)
    if user_bets_count + len(valid_targets) > 200:
        return await message.reply(f"❌ Личный лимит исчерпан! (Уже {user_bets_count}/200)")

    if len(current_bets[chat_id]) + len(valid_targets) > 1500:
        return await message.reply(f"❌ Лимит стола исчерпан! (Уже {len(current_bets[chat_id])}/1500)")

    total_bet = amount * len(valid_targets)
    if await get_balance(user_id) < total_bet:
        return await message.reply("❌ Недостаточно средств!")

    await add_balance(user_id, -total_bet)
    
    for t in valid_targets:
        if t in ["к", "красное", "red"]: display_target = "КРАСНОЕ"
        elif t in ["ч", "черное", "black"]: display_target = "ЧЕРНОЕ"
        elif t in ["even", "четное", "чет", "евен"]: display_target = "ЧЕТНОЕ"
        elif t in ["odd", "нечетное", "нечет", "одд"]: display_target = "НЕЧЕТНОЕ"
        else: display_target = t
            
        current_bets[chat_id].append({
            'user_id': user_id, 'name': name, 'amount': amount, 
            'target': t, 'display': display_target
        })

    if len(valid_targets) <= 10:
        reply_lines = []
        for t in valid_targets:
            if t == "к": d = "КРАСНОЕ"
            elif t == "ч": d = "ЧЕРНОЕ"
            else: d = t.upper() if t in ['black', 'red', 'odd', 'even', 'красное', 'черное'] else t
            reply_lines.append(f"✅ Ставка: {name} <b>{fmt(amount)}</b> ᴜ на <b>{d}</b>")
        await message.answer("\n".join(reply_lines), parse_mode="HTML")
    else:
        await message.answer(f"✅ <b>{name}</b>, принято <b>{len(valid_targets)}</b> ставок по {fmt(amount)} ᴜ!\n💰 Общая сумма: <b>{fmt(total_bet)}</b> ᴜ.", parse_mode="HTML")
        
@router.message(F.text.lower().in_(["отмена", "отменить"]))
async def cancel_all_user_bets(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    if chat_id in is_spinning:
        msg = await message.reply("⏳ <b>Поздно!</b> Колесо уже крутится.", parse_mode="HTML")
        await asyncio.sleep(3); await msg.delete()
        return
    
    if chat_id in current_bets:
        user_bets = [b for b in current_bets[chat_id] if b['user_id'] == user_id]
        
        if user_bets:
            total_refund = sum(b['amount'] for b in user_bets)
            await add_balance(user_id, total_refund)
            current_bets[chat_id] = [b for b in current_bets[chat_id] if b['user_id'] != user_id]
            return await message.reply(f"❌ <b>Все ваши ставки отменены!</b>\nНа баланс возвращено: <b>{fmt(total_refund)}</b> ᴜ.", parse_mode="HTML")
            
    await message.reply("У вас нет активных ставок в этом раунде.")

@router.message(F.text.lower() == "ставки")
async def show_bets(message: types.Message):
    chat_id = message.chat.id
    if chat_id not in current_bets or not current_bets[chat_id]:
        return await message.reply("В этом чате пока нет ставок.")
        
    text = "Ставки текущего раунда:\n"
    for b in current_bets[chat_id]: text += f"• {b['name']} {fmt(b['amount'])} ᴜ на {b['display']}\n"
    await message.reply(text)

# ==========================================
# 🎰 ДВИЖОК РУЛЕТКИ (КРУТИТЬ - КОМАНДА "ГО")
# ==========================================
@router.message(F.text.lower() == "го")
async def spin_roulette(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id 

    if chat_id in is_spinning: return 
    if chat_id not in current_bets or not current_bets[chat_id]:
        return await message.reply("В этом чате нет активных ставок! Сначала сделайте ставку.")

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
            return await message.reply(
                f"⏳ <b>Крупье еще принимает ставки!</b>\n"
                f"👥 Игроков за столом: <b>{unique_players}</b>\n"
                f"🎰 Колесо запустится через <b>{time_left} сек.</b>", 
                parse_mode="HTML"
            )
        return 
        
    round_start_time.pop(chat_id, None)

    if not any(bet['user_id'] == user_id for bet in current_bets[chat_id]): return 

    is_spinning.add(chat_id)

    try:
        round_bets = current_bets[chat_id].copy()
        spinning_bets[chat_id] = round_bets
        current_bets[chat_id] = []

        user_ids = list(set(b['user_id'] for b in round_bets))

        # На турнире нет читов админа, всё честно
        result_number = None 
        
        payouts = []
        for num in range(37):
            num_payout = sum(calculate_win(b['amount'], b['target'], num) for b in round_bets)
            payouts.append({'num': num, 'payout': num_payout})
            
        # 🔥 ВЫЗОВ УМНОГО КРУПЬЕ (Система Вегаса)
        if result_number is None:
            result_number = generate_smart_roulette_result(round_bets, payouts)

        await spin_with_animation(message, result_number, len(user_ids))

        if result_number == 0: log_emoji = "🟢"
        elif result_number in RED_NUMBERS: log_emoji = "🔴"
        else: log_emoji = "⚫️"
        res_text = f"{result_number}{log_emoji}"
        
        if chat_id not in roulette_history: roulette_history[chat_id] = []
        roulette_history[chat_id].insert(0, res_text)
        if len(roulette_history[chat_id]) > 10: roulette_history[chat_id].pop()

        await save_spin_to_db(chat_id, res_text)

        winners_text = []
        bet_lines = []
        history_records = []
        
        is_compact = len(round_bets) > 10 
        total_pool = sum(b['amount'] for b in round_bets)
        
        if is_compact:
            bet_lines.append(f"👥 <b>Сделано ставок:</b> {len(round_bets)}")
            bet_lines.append(f"💰 <b>Общий пул:</b> {fmt(total_pool)} ᴜ")
            
        user_round_data = {} 

        for bet in round_bets:
            u_id = bet['user_id']
            name = bet['name']
            amount = bet['amount']
            target = bet['target']
            display = bet['display']
            
            mention = f'<a href="tg://user?id={u_id}">{name}</a>'
            
            if not is_compact: bet_lines.append(f"👤 {mention} {fmt(amount)} ᴜ на {display}")
            if u_id not in user_round_data: user_round_data[u_id] = {'name': mention, 'win': 0, 'targets': [], 'has_win': False, 'total_bet': 0}
            
            user_round_data[u_id]['total_bet'] += amount
            win = calculate_win(amount, target, result_number)

            if win > 0:
                user_round_data[u_id]['has_win'] = True
                await add_balance(u_id, win) 
                user_round_data[u_id]['win'] += win
                user_round_data[u_id]['targets'].append(display)

        for u_id, data in user_round_data.items():
            is_win = 1 if data['has_win'] else 0
            history_records.append((u_id, is_win, int(time.time())))

            net_profit = data['win'] - data['total_bet']
            if data['targets']:
                unique_targets = list(set(data['targets']))
                if len(unique_targets) > 10:
                    targets_str = ", ".join(unique_targets[:10]) + f" ...и ещё {len(unique_targets) - 10}"
                else: targets_str = ", ".join(unique_targets)
            else: targets_str = "Мимо"

            if is_compact:
                if net_profit > 0: winners_text.append(f"✅ <b>{data['name']}</b>: Чистая прибыль +{fmt(net_profit)} ᴜ (Сыграло: {targets_str})")
                elif net_profit < 0: winners_text.append(f"💀 <b>{data['name']}</b>: Убыток за раунд -{fmt(abs(net_profit))} ᴜ")
                else: winners_text.append(f"⚖️ <b>{data['name']}</b>: Вышел в ноль (Сыграло: {targets_str})")
            else:
                if net_profit > 0: winners_text.append(f"✅ {data['name']} вышел в плюс на <b>{fmt(net_profit)}</b> ᴜ! (Сыграло: {targets_str})")
                elif net_profit < 0: winners_text.append(f"💀 {data['name']} потерял <b>{fmt(abs(net_profit))}</b> ᴜ за этот спин.")
                else: winners_text.append(f"⚖️ {data['name']} остался при своих (0 ᴜ).")

        pool = await get_db()
        async with pool.acquire() as db:
            await db.executemany(
                "INSERT INTO user_game_history (user_id, is_win, timestamp) VALUES ($1, $2, $3)", history_records
            )

        header = f"<b>Результат: {result_number}</b> {log_emoji}\n"
        all_lines = bet_lines + [""] + winners_text if winners_text else bet_lines

        messages_to_send = []
        current_msg = header
        
        for line in all_lines:
            if len(current_msg) + len(line) + 2 > 3900:
                messages_to_send.append(current_msg)
                current_msg = line
            else: current_msg += "\n" + line
        messages_to_send.append(current_msg)

        last_round_bets[chat_id] = round_bets 
        
        builder = InlineKeyboardBuilder()
        builder.button(text="Повторить", callback_data=f"roul_repeat_{chat_id}")
        builder.button(text="Удвоить", callback_data=f"roul_double_{chat_id}")
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
            except Exception as e: break

    except Exception as e: logging.error(f"Ошибка в рулетке: {e}")
    finally:
        is_spinning.discard(chat_id)
        spinning_bets.pop(chat_id, None)

@router.callback_query(F.data.startswith("roul_"))
async def process_roulette_buttons(callback: types.CallbackQuery):
    data = callback.data.split("_")
    action = data[1]
    chat_id = int(data[2])
    user_id = callback.from_user.id
    name = html.escape(callback.from_user.first_name)
    
    if chat_id in is_spinning: return await callback.answer("⏳ Колесо уже крутится! Дождись остановки.", show_alert=True)
    if chat_id not in last_round_bets: return await callback.answer("❌ Данные раунда утеряны.", show_alert=True)

    user_last_bets = [b for b in last_round_bets[chat_id] if b['user_id'] == user_id]
    if not user_last_bets: return await callback.answer("⚠️ Вы не участвовали в прошлом раунде!", show_alert=True)
    
    current_table_count = len(current_bets.get(chat_id, []))
    if current_table_count + len(user_last_bets) > 1500: return await callback.answer(f"❌ Лимит стола (1500) будет превышен!", show_alert=True)

    multiplier = 2 if action == "double" else 1
    total_needed = sum(b['amount'] for b in user_last_bets) * multiplier

    if await get_balance(user_id) < total_needed: return await callback.answer(f"❌ Недостаточно UMBREL! Нужно {total_needed}", show_alert=True)

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

    await callback.answer("✅ Ставка принята!")
    fmt_sum = f"{total_needed:,}".replace(',', ' ')
    act_text = "удвоил" if multiplier == 2 else "повторил"
    await callback.message.answer(f"🎲 <b>{name}</b> {act_text} прошлую ставку: <b>{fmt_sum}</b> ᴜ!", parse_mode="HTML")

@router.message(F.text.lower() == "лог")
async def show_roulette_log(message: types.Message):
    chat_id = message.chat.id
    history = roulette_history.get(chat_id, [])
    if not history: return await message.reply("🎰 В этом чате рулетка еще не крутилась. Лог пуст!")
    log_text = "\n".join(history)
    await message.reply(f"\n\n{log_text}", parse_mode="HTML")