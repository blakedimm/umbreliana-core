import time
import random
import asyncio
import re
from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.database import get_db, get_balance, add_balance

router = Router()

sector_cooldowns = {}

fmt = lambda x: f"{int(x):,}".replace(',', ' ')

# ==========================================
# 📊 НАСТРОЙКИ СЛОЖНОСТИ С ЛИМИТАМИ СТОЛА
# ==========================================
DIFFICULTIES = {
    "easy":   {"name": "🟢 Легкая (5х5)",   "size": 5, "mines": 4, "mult_step": 1.1, "max_bet": 100_000_000},
    "medium": {"name": "🟡 Средняя (4х4)", "size": 4, "mines": 4, "mult_step": 1.3, "max_bet": 1_000_000_000},
    "hard":   {"name": "🔴 ХАРДКОР (3х3)", "size": 3, "mines": 3, "mult_step": 1.6, "max_bet": 10_000_000_000},
    "hell":   {"name": "💀 АД (2х2)",      "size": 2, "mines": 3, "mult_step": 2.5, "max_bet": float('inf')}
}

WHALE_THRESHOLD = 10_000_000  # Порог для "проклятия китов"

ACTIVE_GAMES = {}

# ==========================================
# 🎨 БЕЗОПАСНЫЙ СЛОВАРЬ ДЕФОЛТОВ (ДЛЯ ФОЛБЕКА)
# ==========================================
FALLBACK_STRINGS = {
    "sec_lobby_active_err": "⚠️ В этом чате уже запущена квантовая зона Сектора! Дождитесь окончания.",
    "sec_hint": "👉 Напиши: <code>сектор [ставка]</code> (например: сектор 5кк или сектор все)",
    "sec_err_invalid_bet": "❌ Укажи корректную сумму ставки!",
    "sec_err_zero_bet": "❌ Ваша ставка должна быть больше нуля!",
    "sec_err_max_bet": "🛑 <b>Лимит стола превышен!</b>\nДля создания лобби максимальная ставка: <b>{max_bet} ᴜ</b>.\n<i>Снизь ставку или играй в другие модули!</i>",
    "sec_err_no_money": "💸 У тебя не хватает UMBREL для создания игры со ставкой {bet} ᴜ.",
    "sec_all_in_label": "🔥 [ALL-IN]",
    "sec_lobby_body": "🎲 <b>КВАНТОВЫЙ СЕКТОР: РЕГИСТРАЦИЯ ЛОББИ</b>\n━━━━━━━━━━━━━━━━━━━━\n👑 Организатор: <a href='tg://user?id={user_id}'>{creator_name}</a>\n💰 Ставка входа: <b>{bet} ᴜ</b> {all_in}\n📈 Текущий банк: <b>{bank} ᴜ</b>\n\n👥 <b>Участники ({count}):</b>\n{players_list}",
    "sec_btn_join": "➕ Вступить",
    "sec_btn_start": "🚀 СТАРТ",
    "sec_btn_cancel": "❌ Отмена",
    "sec_join_closed": "❌ Регистрация уже закрыта!",
    "sec_join_already": "Вы уже в игре!",
    "sec_join_no_money": "Недостаточно денег для входа!",
    "sec_join_success": "Вы успешно вошли в игру!",
    "sec_err_creator_diff": "🛑 Только создатель лобби меняет сложность!",
    "sec_err_diff_limit": "🛑 Невозможно выбрать этот режим!\nСтавка лобби превышает лимит сложности {name} ({limit} ᴜ).",
    "sec_diff_selected": "Выбрана сложность: {name}",
    "sec_err_creator_cancel": "🛑 Отменить лобби может только создатель!",
    "sec_lobby_disbanded": "❌ <b>Квантовое лобби распущено создателем. Ставки возвращены.</b>",
    "sec_err_creator_start": "🛑 Только создатель может запустить старт!",
    "sec_round_body": "🟩 <b>СЕКТОР: РАУНД {round}</b>\n━━━━━━━━━━━━━━━━━━━━\n⚙️ Сложность: {diff_name}\n🏛 Налог Синдиката: <b>10%</b>\n💰 Призовой фонд: <b>{bank} ᴜ</b>\n\nℹ️ <i>Количество мин: {mines}</i>\n\n📝 <b>Выбор игроков:</b>\n{player_status}",
    "sec_status_selecting": "├ {name} ➔ ⏳ Выбирает...\n",
    "sec_status_thinking": "├ {name} ➔ ⏳ Выбирает сектор...\n",
    "sec_status_picked": "├ {name} ➔ 🎯 Выбрал <b>[{r}-{c}]</b>\n",
    "sec_pick_cooldown": "⏳ Не части!",
    "sec_pick_err_not_in": "Вы не участвуете или выбыли из игры!",
    "sec_pick_accepted": "Принято: сектор {r}-{c}!",
    "sec_scan_init": "📡 <b>СЕКТОР: Инициализация протоколов сканирования...</b>",
    "sec_anomaly_detected": "💥 <b>СЕКТОР: ОБНАРУЖЕНЫ АНОМАЛИИ! Взрыв секторов...</b>",
    "sec_final_render": "📊 <b>СЕКТОР: Сведение координатной сетки и тепловых сигнатур...</b>",
    "sec_report_annihilated": "💥 <b>{name}</b> встал на сектор [{r}-{c}] и <b>АННИГИЛИРОВАЛ!</b>",
    "sec_report_survived": "✅ <b>{name}</b> успешно прошел в сектор [{r}-{c}] (Множитель: <b>x{mult}</b>)",
    "sec_all_dead": "☠️ <b>КАТАСТРОФА В СЕКТОРЕ</b>\n━━━━━━━━━━━━━━━━━━━━\n💣 Аномальные ловушки: <b>{mines_str}</b>\n\n{reports}\n\n🛑 <b>Все участники погибли. Вся касса {bank} ᴜ уходит Синдикату!</b>",
    "sec_round_results": "🛰 <b>СЕКТОР: РЕЗУЛЬТАТЫ РАУНДА {round}</b>\n━━━━━━━━━━━━━━━━━━━━\n💣 Ловушки раунда: <b>{mines_str}</b>\n\n{reports}\n\n💰 Касса на кону: <b>{bank} ᴜ</b>\n⚠️ <i>У вас есть всего 30 секунд. Заберите кэш или рискуйте дальше!</i>",
    "sec_btn_cashout": "💵 ЗАБРАТЬ КЭШ",
    "sec_btn_next_round": "⏭ СЛЕДУЮЩИЙ РАУНД ({voted}/{total})",
    "sec_cashout_err_already": "Вы уже забрали деньги или выбыли!",
    "sec_cashout_success": "🎉 УСПЕШНЫЙ ВЫВОД: +{win} ᴜ (x{mult})!",
    "sec_next_err_not_in": "Вы не в игре!",
    "sec_next_success": "Вы подтвердили участие в следующем раунде!",
    "sec_game_over": "🏁 <b>Игра «СЕКТОР» завершена.</b>",
    "sec_lobby_timeout": "⏳ <b>Лобби закрыто по таймауту (10 минут бездействия).</b>",
    "sec_round_timeout": "⏰ <b>Время вышло! Система автоматически зафиксировала прибыль всех выживших (30 сек бездействия).</b>",
    "sec_player_disqualified": "⏰ {name} не выбрал сектор за 30 секунд и выбывает. Ставка возвращена.",
    "sec_all_skipped": "⏳ Все участники пропустили выбор сектора. Игра отменена.",
    "sec_refresh_body": "🛰 <b>СЕКТОР: РАУНД {round}</b>\n━━━━━━━━━━━━━━━━━━━━\n{cashed_section}⏳ <b>Текущие решения:</b>\n{alive_section}\n⚠️ <i>Всего 30 секунд на размышления, затем авто-вывод прибыли!</i>",
    "sec_refresh_cashed_title": "🏆 <b>Забрали кэш:</b>\n",
    "sec_refresh_cashed_row": "├ {name} ➔ <b>{win} ᴜ</b> (x{mult})\n",
    "sec_refresh_alive_row": "├ {name} ➔ {status}\n",
    "sec_refresh_status_ready": "🟩 Готов к разгону",
    "sec_refresh_status_thinking": "<i>думает...</i>"
}

def get_str(key: str, _=None, **kwargs) -> str:
    if _:
        return _(key, **kwargs)
    text = FALLBACK_STRINGS.get(key, key)
    if kwargs:
        try: return text.format(**kwargs)
        except: pass
    return text

def cancel_timeout(chat_id):
    game = ACTIVE_GAMES.get(chat_id)
    if not game: return
    for task_key in ("timeout_task", "round_timer"):
        task = game.get(task_key)
        if task:
            task.cancel()
            game[task_key] = None

# ==========================================
# ⚙️ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И АНИМАЦИЯ СЕТОК
# ==========================================
def get_lobby_markup(chat_id: int, creator_id: int, diff_type: str, _=None):
    builder = InlineKeyboardBuilder()
    builder.button(text=get_str("sec_btn_join", _), callback_data=f"sec_join_{chat_id}")
    builder.button(text=f"⚙️ {DIFFICULTIES[diff_type]['name']}", callback_data=f"sec_diff_{chat_id}")
    builder.button(text=get_str("sec_btn_start", _), callback_data=f"sec_start_{chat_id}")
    builder.button(text=get_str("sec_btn_cancel", _), callback_data=f"sec_cancel_{chat_id}")
    builder.adjust(1, 1, 2)
    return builder.as_markup()

def get_grid_markup(chat_id: int, size: int):
    builder = InlineKeyboardBuilder()
    for r in range(1, size + 1):
        for c in range(1, size + 1):
            builder.button(text=f"{r}-{c}", callback_data=f"sec_pick_{r}_{c}_{chat_id}")
    builder.adjust(size)
    return builder.as_markup()

def get_animated_grid_markup(size: int, frame_type: str, mines: set = None, player_choices: list = None):
    builder = InlineKeyboardBuilder()
    for r in range(1, size + 1):
        for c in range(1, size + 1):
            cell = (r, c)
            if frame_type == "scan":
                builder.button(text="🔹", callback_data="sec_void")
            elif frame_type == "mines":
                icon = "💥" if cell in mines else "⬛"
                builder.button(text=icon, callback_data="sec_void")
            elif frame_type == "final":
                if cell in mines:
                    icon = "💀" if cell in player_choices else "💥"
                else:
                    icon = "🛡" if cell in player_choices else "🟩"
                builder.button(text=icon, callback_data="sec_void")
    builder.adjust(size)
    return builder.as_markup()

async def safe_edit_or_send(bot, chat_id, game, text, reply_markup=None):
    try:
        await bot.edit_message_text(
            text=text, chat_id=chat_id, message_id=game["msg_id"],
            reply_markup=reply_markup, parse_mode="HTML"
        )
    except Exception:
        try:
            msg = await bot.send_message(chat_id, text=text, reply_markup=reply_markup, parse_mode="HTML")
            game["msg_id"] = msg.message_id
        except Exception:
            pass

# ==========================================
# 🤝 ШАГ 1: ИНИЦИАЦИЯ ИГРЫ И ЛОББИ
# ==========================================
@router.message(F.text.lower().startswith(("сектор", "sector")))
async def cmd_sector_start(message: types.Message, state: FSMContext = None, _=None):
    if state:
        current_state = await state.get_state()
        if current_state is not None: await state.clear()
        
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    if chat_id in ACTIVE_GAMES:
        return message.reply(get_str("sec_lobby_active_err", _))

    raw_text = message.text.lower().strip()
    raw_text = raw_text.replace("сектор", "").replace("sector", "").strip()
    
    if not raw_text:
        return await message.reply(get_str("sec_hint", _), parse_mode="HTML")

    user_balance = await get_balance(user_id)
    bet = 0

    if raw_text in ["все", "всё", "на все", "all", "allin", "all-in"]:
        bet = user_balance
    else:
        bet_str = raw_text.replace('к', '000').replace('k', '000').replace('м', '000000').replace('m', '000000').replace(' ', '')
        if not bet_str.isdigit() or int(bet_str) <= 0:
            return await message.reply(get_str("sec_err_invalid_bet", _))
        bet = int(bet_str)

    if bet <= 0:
        return await message.reply(get_str("sec_err_zero_bet", _))
    
    if bet > DIFFICULTIES["medium"]["max_bet"]:
        return await message.reply(get_str("sec_err_max_bet", _, max_bet=fmt(DIFFICULTIES["medium"]["max_bet"])), parse_mode="HTML")

    if user_balance < bet:
        return await message.reply(get_str("sec_err_no_money", _, bet=fmt(bet)))

    ACTIVE_GAMES[chat_id] = {
        "creator": user_id, "status": "lobby", "bet": bet, "difficulty": "medium",
        "round": 1, "bank": bet, "msg_id": None,
        "players": {user_id: {"name": message.from_user.first_name, "choice": None, "state": "alive", "mult": 1.0}}
    }
    
    await add_balance(user_id, -bet)
    
    all_in_tag = get_str("sec_all_in_label", _) if bet == user_balance else ""
    text = get_str("sec_lobby_body", _, user_id=user_id, creator_name=message.from_user.first_name, bet=fmt(bet), all_in=all_in_tag, bank=fmt(bet), count=1, players_list=f"└ {message.from_user.first_name}\n")
    
    msg = await message.answer(text, reply_markup=get_lobby_markup(chat_id, user_id, "medium", _), parse_mode="HTML")
    ACTIVE_GAMES[chat_id]["msg_id"] = msg.message_id
    ACTIVE_GAMES[chat_id]["timeout_task"] = asyncio.create_task(lobby_timeout_logic(message.bot, chat_id, _))

# ==========================================
# 🕹 ОБРАБОТЧИКИ КНОПОК ЛОББИ
# ==========================================
@router.callback_query(F.data.startswith("sec_join_"))
async def callback_sector_join(callback: types.CallbackQuery, _=None):
    chat_id = int(callback.data.split("_")[-1])
    user_id = callback.from_user.id
    
    if chat_id not in ACTIVE_GAMES or ACTIVE_GAMES[chat_id]["status"] != "lobby":
        return await callback.answer(get_str("sec_join_closed", _), show_alert=True)
        
    game = ACTIVE_GAMES[chat_id]
    if user_id in game["players"]:
        return await callback.answer(get_str("sec_join_already", _), show_alert=True)
        
    if await get_balance(user_id) < game["bet"]:
        return await callback.answer(get_str("sec_join_no_money", _), show_alert=True)
        
    await add_balance(user_id, -game["bet"])
    game["players"][user_id] = {"name": callback.from_user.first_name, "choice": None, "state": "alive", "mult": 1.0}
    game["bank"] += game["bet"]
    
    players_list = "\n".join([f"├ {p['name']}" for p in game["players"].values()])
    text = get_str("sec_lobby_body", _, user_id=game['creator'], creator_name=game['players'][game['creator']]['name'], bet=fmt(game['bet']), all_in="", bank=fmt(game['bank']), count=len(game['players']), players_list=players_list)
    
    await callback.message.edit_text(text, reply_markup=get_lobby_markup(chat_id, game["creator"], game["difficulty"], _), parse_mode="HTML")
    await callback.answer(get_str("sec_join_success", _))

@router.callback_query(F.data.startswith("sec_diff_"))
async def callback_sector_difficulty(callback: types.CallbackQuery, _=None):
    chat_id = int(callback.data.split("_")[-1])
    user_id = callback.from_user.id
    game = ACTIVE_GAMES.get(chat_id)
    if not game: return
    if user_id != game["creator"]:
        return await callback.answer(get_str("sec_err_creator_diff", _), show_alert=True)
        
    diff_modes = ["easy", "medium", "hard", "hell"]
    current_index = diff_modes.index(game["difficulty"])
    next_diff = diff_modes[(current_index + 1) % 4]
    
    if game["bet"] > DIFFICULTIES[next_diff]["max_bet"]:
        return await callback.answer(get_str("sec_err_diff_limit", _, name=DIFFICULTIES[next_diff]["name"], limit=fmt(DIFFICULTIES[next_diff]["max_bet"])), show_alert=True)

    game["difficulty"] = next_diff
    players_list = "\n".join([f"├ {p['name']}" for p in game["players"].values()])
    text = get_str("sec_lobby_body", _, user_id=game['creator'], creator_name=game['players'][game['creator']]['name'], bet=fmt(game['bet']), all_in="", bank=fmt(game['bank']), count=len(game['players']), players_list=players_list)
    
    await callback.message.edit_text(text, reply_markup=get_lobby_markup(chat_id, user_id, next_diff, _), parse_mode="HTML")
    await callback.answer(get_str("sec_diff_selected", _, name=DIFFICULTIES[next_diff]["name"]))

@router.callback_query(F.data.startswith("sec_cancel_"))
async def callback_sector_cancel(callback: types.CallbackQuery, _=None):
    chat_id = int(callback.data.split("_")[-1])
    user_id = callback.from_user.id
    game = ACTIVE_GAMES.get(chat_id)
    if not game: return
    if user_id != game["creator"]:
        return await callback.answer(get_str("sec_err_creator_cancel", _), show_alert=True)
    
    cancel_timeout(chat_id)
    for pid in game["players"]: await add_balance(pid, game["bet"])
    ACTIVE_GAMES.pop(chat_id, None)
    await callback.message.edit_text(get_str("sec_lobby_disbanded", _), parse_mode="HTML")

# ==========================================
# 🏁 ШАГ 2: ИГРОВОЙ ЦИКЛ (СЕТКА)
# ==========================================
@router.callback_query(F.data.startswith("sec_start_"))
async def callback_sector_start_game(callback: types.CallbackQuery, _=None):
    chat_id = int(callback.data.split("_")[-1])
    user_id = callback.from_user.id
    game = ACTIVE_GAMES.get(chat_id)
    if not game: return
    if user_id != game["creator"]:
        return await callback.answer(get_str("sec_err_creator_start", _), show_alert=True)
    
    cancel_timeout(chat_id)
    game["status"] = "playing"
    await start_new_round(callback.bot, chat_id, _)
    await callback.answer()

async def start_new_round(bot, chat_id, _=None):
    game = ACTIVE_GAMES[chat_id]
    diff = DIFFICULTIES[game["difficulty"]]
    
    tax = int(game["bank"] * 0.10)
    game["bank"] -= tax
    
    for p in game["players"].values():
        if p["state"] == "alive": p["choice"] = None
            
    player_status = ""
    for p in game["players"].values():
        if p["state"] == "alive":
            player_status += get_str("sec_status_selecting", _, name=p['name'])
            
    text = get_str("sec_round_body", _, round=game['round'], diff_name=diff['name'], bank=fmt(game['bank']), mines=diff['mines'] + (game['round'] - 1), player_status=player_status)
    
    cancel_timeout(chat_id)
    game["round_timer"] = asyncio.create_task(round_selection_timeout(bot, chat_id, _))
    await safe_edit_or_send(bot, chat_id, game, text, reply_markup=get_grid_markup(chat_id, diff["size"]))

async def refresh_game_message(bot, chat_id, _=None):
    game = ACTIVE_GAMES.get(chat_id)
    if not game: return
    
    cashed_players = [p for p in game["players"].values() if p["state"] == "cashed"]
    alive_players = [p for p in game["players"].values() if p["state"] == "alive"]
    voted_next_count = len([p for p in alive_players if p.get("choice") == "voted_next"])
    
    cashed_section = ""
    if cashed_players:
        cashed_section += get_str("sec_refresh_cashed_title", _)
        for p in cashed_players:
            cashed_section += get_str("sec_refresh_cashed_row", _, name=p['name'], win=fmt(p.get('win_amount', 0)), mult=p['mult'])
        cashed_section += "\n"
        
    alive_section = ""
    for p in alive_players:
        status_str = get_str("sec_refresh_status_ready", _) if p.get("choice") == "voted_next" else get_str("sec_refresh_status_thinking", _)
        alive_section += get_str("sec_refresh_alive_row", _, name=p['name'], status=status_str)
        
    text = get_str("sec_refresh_body", _, round=game['round'], cashed_section=cashed_section, alive_section=alive_section)
    
    builder = InlineKeyboardBuilder()
    builder.button(text=get_str("sec_btn_cashout", _), callback_data=f"sec_cashout_{chat_id}")
    builder.button(text=get_str("sec_btn_next_round", _, voted=voted_next_count, total=len(alive_players)), callback_data=f"sec_next_{chat_id}")
    builder.adjust(1)
    await safe_edit_or_send(bot, chat_id, game, text, builder.as_markup())

@router.callback_query(F.data.startswith("sec_pick_"))
async def callback_sector_pick_cell(callback: types.CallbackQuery, _=None):
    parts = callback.data.split("_")
    r, c, chat_id = int(parts[2]), int(parts[3]), int(parts[-1])
    user_id = callback.from_user.id
    
    now = time.time()
    if sector_cooldowns.get(user_id, 0) > now - 1.0:
        return await callback.answer(get_str("sec_pick_cooldown", _), show_alert=False)
    sector_cooldowns[user_id] = now
    
    game = ACTIVE_GAMES.get(chat_id)
    if not game or game["status"] != "playing": return
    if user_id not in game["players"] or game["players"][user_id]["state"] != "alive":
        return await callback.answer(get_str("sec_pick_err_not_in", _), show_alert=True)
        
    player = game["players"][user_id]
    player["choice"] = (r, c)
    await callback.answer(get_str("sec_pick_accepted", _, r=r, c=c), show_alert=False)
    
    diff = DIFFICULTIES[game["difficulty"]]
    all_picked = True
    
    player_status = ""
    for p_id, p in game["players"].items():
        if p["state"] == "alive":
            if p["choice"]:
                player_status += get_str("sec_status_picked", _, name=p['name'], r=p['choice'][0], c=p['choice'][1])
            else:
                player_status += get_str("sec_status_thinking", _, name=p['name'])
                all_picked = False
                
    if all_picked:
        cancel_timeout(chat_id)
        await detonate_round(callback.bot, chat_id, _)
    else:
        text = get_str("sec_round_body", _, round=game['round'], diff_name=diff['name'], bank=fmt(game['bank']), mines=diff['mines'] + (game['round'] - 1), player_status=player_status)
        await safe_edit_or_send(callback.bot, chat_id, game, text, reply_markup=get_grid_markup(chat_id, diff["size"]))

# ==========================================
# 🧠 ГЕНЕРАТОР "ПРОКЛЯТЫХ" МИН
# ==========================================
def generate_weighted_mines(size, num_mines, player_choices, bet):
    all_cells = [(r, c) for r in range(1, size + 1) for c in range(1, size + 1)]
    weights = {cell: 1 for cell in all_cells}
    if bet >= WHALE_THRESHOLD:
        curse_multiplier = 3 + (bet // (WHALE_THRESHOLD * 2))
        for choice in player_choices:
            if choice in weights: weights[choice] = curse_multiplier
    weighted_pool = []
    for cell, weight in weights.items(): weighted_pool.extend([cell] * weight)
    mines = set()
    while len(mines) < num_mines:
        mines.add(random.choice(weighted_pool))
    return mines

# ==========================================
# 💥 ШАГ 3: КИНЕМАТОГРАФИЧЕСКИЙ ВЗРЫВ ПОЛЯ
# ==========================================
async def detonate_round(bot, chat_id, _=None):
    game = ACTIVE_GAMES[chat_id]
    diff = DIFFICULTIES[game["difficulty"]]
    if not game or game["status"] != "playing": return
    
    game["status"] = "detonating"
    base_mines = diff["mines"] + (game["round"] - 1)
    current_mines_count = min(diff["size"] * diff["size"] - 1, base_mines)
    
    player_choices = [p["choice"] for p in game["players"].values() if p["state"] == "alive" and p["choice"]]
    mines = generate_weighted_mines(diff["size"], current_mines_count, player_choices, game["bet"])

    try:
        await bot.edit_message_text(text=get_str("sec_scan_init", _), chat_id=chat_id, message_id=game["msg_id"], reply_markup=get_animated_grid_markup(diff["size"], "scan"), parse_mode="HTML")
    except: pass
    await asyncio.sleep(1.5)

    try:
        await bot.edit_message_text(text=get_str("sec_anomaly_detected", _), chat_id=chat_id, message_id=game["msg_id"], reply_markup=get_animated_grid_markup(diff["size"], "mines", mines=mines), parse_mode="HTML")
    except: pass
    await asyncio.sleep(1.8)

    try:
        await bot.edit_message_text(text=get_str("sec_final_render", _), chat_id=chat_id, message_id=game["msg_id"], reply_markup=get_animated_grid_markup(diff["size"], "final", mines=mines, player_choices=player_choices), parse_mode="HTML")
    except: pass
    await asyncio.sleep(1.2)

    report_lines = []
    survivors_count = 0
    
    for pid, p in game["players"].items():
        if p["state"] != "alive": continue
        if p["choice"] in mines:
            p["state"] = "dead"
            report_lines.append(get_str("sec_report_annihilated", _, name=p['name'], r=p['choice'][0], c=p['choice'][1]))
        else:
            p["mult"] = round(p["mult"] * diff["mult_step"], 2)
            survivors_count += 1
            report_lines.append(get_str("sec_report_survived", _, name=p['name'], r=p['choice'][0], c=p['choice'][1], mult=p['mult']))

    mines_str = ", ".join([f"[{m[0]}-{m[1]}]" for m in mines])
    
    if survivors_count == 0:
        text = get_str("sec_all_dead", _, mines_str=mines_str, reports="\n".join(report_lines), bank=fmt(game['bank']))
        await safe_edit_or_send(bot, chat_id, game, text)
        ACTIVE_GAMES.pop(chat_id, None)
    else:
        game["status"] = "cashing"
        game["timeout_task"] = asyncio.create_task(round_timeout_logic(bot, chat_id, _))
        alive_players = [p for p in game["players"].values() if p["state"] == "alive"]
        
        text = get_str("sec_round_results", _, round=game['round'], mines_str=mines_str, reports="\n".join(report_lines), bank=fmt(game['bank']))
        
        builder = InlineKeyboardBuilder()
        builder.button(text=get_str("sec_btn_cashout", _), callback_data=f"sec_cashout_{chat_id}")
        builder.button(text=get_str("sec_btn_next_round", _, voted=0, total=len(alive_players)), callback_data=f"sec_next_{chat_id}")
        builder.adjust(1)
        await safe_edit_or_send(bot, chat_id, game, text, builder.as_markup())

# ==========================================
# 💵 ШАГ 4: ВЫБОР ДАЛЬНЕЙШЕЙ СУДЬБЫ
# ==========================================
@router.callback_query(F.data.startswith("sec_cashout_"))
async def callback_sector_cashout(callback: types.CallbackQuery, _=None):
    chat_id = int(callback.data.split("_")[-1])
    user_id = callback.from_user.id
    game = ACTIVE_GAMES.get(chat_id)
    if not game or game["status"] != "cashing": return
    if user_id not in game["players"] or game["players"][user_id]["state"] != "alive":
        return await callback.answer(get_str("sec_cashout_err_already", _), show_alert=True)
        
    player = game["players"][user_id]
    win_amount = int(game["bet"] * player["mult"])
    player["state"] = "cashed"
    player["win_amount"] = win_amount
    
    await add_balance(user_id, win_amount)
    await refresh_game_message(callback.bot, chat_id, _)
    await callback.answer(get_str("sec_cashout_success", _, win=fmt(win_amount), mult=player['mult']), show_alert=True)
    await check_session_next_step(callback.bot, chat_id, _)

@router.callback_query(F.data.startswith("sec_next_"))
async def callback_sector_next_round(callback: types.CallbackQuery, _=None):
    chat_id = int(callback.data.split("_")[-1])
    user_id = callback.from_user.id
    game = ACTIVE_GAMES.get(chat_id)
    if not game or game["status"] != "cashing": return
    if user_id not in game["players"] or game["players"][user_id]["state"] != "alive":
        return await callback.answer(get_str("sec_next_err_not_in", _), show_alert=True)
        
    player = game["players"][user_id]
    player["choice"] = "voted_next"
    await callback.answer(get_str("sec_next_success", _), show_alert=False)
    await check_session_next_step(callback.bot, chat_id, _)

async def check_session_next_step(bot, chat_id, _=None):
    game = ACTIVE_GAMES.get(chat_id)
    if not game or game["status"] != "cashing": return
        
    still_alive = [p for p in game["players"].values() if p["state"] == "alive"]
    not_voted = [p for p in still_alive if p["choice"] != "voted_next"]
    
    if not_voted:
        await refresh_game_message(bot, chat_id, _)
        return
        
    cancel_timeout(chat_id)
    if not still_alive:
        await bot.send_message(chat_id, get_str("sec_game_over", _), parse_mode="HTML")
        ACTIVE_GAMES.pop(chat_id, None)
        return
        
    game["round"] += 1
    game["status"] = "playing"
    await start_new_round(bot, chat_id, _)

@router.callback_query(F.data == "sec_void")
async def cb_sector_void(callback: types.CallbackQuery): await callback.answer()

# ==========================================
# ⏳ ТАЙМАУТЫ АВТОЗАВЕРШЕНИЯ
# ==========================================
async def lobby_timeout_logic(bot, chat_id, _=None):
    await asyncio.sleep(600)
    game = ACTIVE_GAMES.get(chat_id)
    if game and game["status"] == "lobby":
        for pid in game["players"]: await add_balance(pid, game["bet"])
        try: await bot.send_message(chat_id, get_str("sec_lobby_timeout", _), parse_mode="HTML")
        except: pass
        ACTIVE_GAMES.pop(chat_id, None)

async def round_timeout_logic(bot, chat_id, _=None):
    await asyncio.sleep(30)
    game = ACTIVE_GAMES.get(chat_id)
    if game and game["status"] == "cashing":
        for pid, p in game["players"].items():
            if p["state"] == "alive":
                win_amount = int(game["bet"] * p["mult"])
                p["state"] = "cashed"
                p["win_amount"] = win_amount
                await add_balance(pid, win_amount)
        try: await bot.send_message(chat_id, get_str("sec_round_timeout", _), parse_mode="HTML")
        except: pass
        ACTIVE_GAMES.pop(chat_id, None)

async def round_selection_timeout(bot, chat_id, _=None):
    await asyncio.sleep(30)
    game = ACTIVE_GAMES.get(chat_id)
    if not game or game["status"] != "playing": return

    quitters = [pid for pid, p in game["players"].items() if p["state"] == "alive" and p["choice"] is None]
    for pid in quitters:
        game["players"][pid]["state"] = "dead"
        await add_balance(pid, game["bet"])
        try: await bot.send_message(chat_id, get_str("sec_player_timeout", _, name=game['players'][pid]['name']))
        except: pass

    alive_with_choice = [p for p in game["players"].values() if p["state"] == "alive" and p["choice"] is not None]
    if alive_with_choice:
        cancel_timeout(chat_id)
        await detonate_round(bot, chat_id, _)
    else:
        try: await bot.send_message(chat_id, get_str("sec_all_timeout", _))
        except: pass
        ACTIVE_GAMES.pop(chat_id, None)