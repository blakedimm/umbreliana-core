import asyncio
import random
import time
from aiogram import Router, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from core.database import get_balance, add_balance

from handlers.users.quests import process_quest_action

router = Router()

# Состояния гонок: {chat_id: {status, bet, creator_id, created_at, message_id, players: {uid: {name, emoji, dist}}}}
active_races = {}
# Список болидов
CAR_EMOJIS = ["🏎️", "🏍️", "🚜", "🐎", "🚲", "🚀", "🛸", "🛹", "🏃", "🦖"]

# ==========================================
# 🎨 БЕЗОПАСНЫЙ СЛОВАРЬ ДЕФОЛТОВ (ДЛЯ ФОЛБЕКА)
# ==========================================
FALLBACK_STRINGS = {
    "rc_auto_cancel": "❌ <b>Гонка отменена автоматически!</b>\nПрошло 20 минут, а заезд так и не стартовал. Все ставки возвращены на баланс.",
    "rc_btn_join": "Вступить",
    "rc_btn_leave": "Покинуть",
    "rc_btn_start": "Старт",
    "rc_btn_cancel": "Отмена",
    "rc_err_creator_leave": "⚠️ Ты организатор! Чтобы выйти, отмени заезд кнопкой «Отмена».",
    "rc_lobby_body": "🏁 <b>Гонки</b>\n\n💰 Ставка: <b>{bet}</b> UMBREL\n👥 Участники: {names}",
    "rc_leave_success": "🚪 Ты покинул лобби. Ставка возвращена.",
    "rc_err_min_bet": "❌ Минимальная ставка в гонках — 100 UMBREL",
    "rc_err_no_money": "❌ У тебя не хватает UMBREL!",
    "rc_err_already_active": "⚠️ В этом чате уже готовится заезд!",
    "rc_alert_not_creator": "Только создатель может отменить заезд!",
    "rc_alert_already_started": "Гонка уже началась, тормозить поздно!",
    "rc_cancel_success": "❌ <b>Заезд отменен создателем.</b>\nВсе ставки возвращены на баланс.",
    "rc_alert_cancel": "Гонка успешно отменена",
    "rc_alert_already_in": "Ты уже в болиде!",
    "rc_alert_max_players": "Максимум 10 участников!",
    "rc_alert_no_money": "Мало UMBREL!",
    "rc_alert_late_leave": "Гонка уже началась, поздно ливать!",
    "rc_alert_not_in": "Ты и так не участвуешь!",
    "rc_alert_creator_btn_leave": "Ты организатор! Жми «Отмена» для закрытия лобби.",
    "rc_alert_leave_success": "Ты успешно покинул болид!",
    "rc_alert_wait_creator": "Запустить может организатор! Либо подожди еще {time} сек.",
    "rc_alert_min_players": "Нужно минимум 2 гонщика!",
    "rc_countdown": "🏁 <b>ГОНКИ: ПРИГОТОВИТЬСЯ!</b>\n\n{lights} Старт через: <b>{i}</b>",
    "rc_timeout": "⏱ <b>Время вышло!</b>\nДвигатели заглохли. Заезд отменен, ставки возвращены.",
    "rc_track_header": "🏁 <b>ЗАЕЗД ИДЕТ! БОЛЕЕМ ЗА СВОИХ!</b>\n\n",
    "rc_track_winner": "\n🏆 <b>Победитель: {name}!</b>\n💰 Выигрыш: <b>{win}</b> UMBREL\n",
    "rc_track_cashback": "🍀 <b>{name}</b> получил кешбэк: +{cb} ᴜ\n"
}

def get_str(key: str, _=None, **kwargs) -> str:
    """Умный распределитель строк локализации с защитой сессии"""
    if _:
        return _(key, **kwargs)
    text = FALLBACK_STRINGS.get(key, key)
    if kwargs:
        try: return text.format(**kwargs)
        except: pass
    return text

# ==========================================
# 🕒 АВТО-ОТМЕНА ГОНКИ (20 МИНУТ)
# ==========================================
async def auto_cancel_race(chat_id: int, message: types.Message, _=None):
    """Отменяет гонку, если она висит в лобби больше 20 минут"""
    await asyncio.sleep(1200)
    race = active_races.get(chat_id)
    
    if race and race["status"] == "lobby":
        for p_id in race["players"]:
            await add_balance(p_id, race["bet"])
        
        del active_races[chat_id]
        try:
            await message.edit_text(get_str("rc_auto_cancel", _), parse_mode="HTML")
        except:
            pass

# ==========================================
# 🛠 ГЕНЕРАТОР КЛАВИАТУРЫ ЛОББИ
# ==========================================
def get_lobby_keyboard(chat_id: int, _=None):
    builder = InlineKeyboardBuilder()
    builder.button(text=get_str("rc_btn_join", _), callback_data=f"race_join_{chat_id}")
    builder.button(text=get_str("rc_btn_leave", _), callback_data=f"race_leave_{chat_id}")
    builder.button(text=get_str("rc_btn_start", _), callback_data=f"race_start_{chat_id}")
    builder.button(text=get_str("rc_btn_cancel", _), callback_data=f"race_cancel_{chat_id}")
    builder.adjust(2, 2)
    return builder.as_markup()

# ==========================================
# 🚪 КОМАНДА: ПОКИНУТЬ ЛОББИ (ТЕКСТОМ)
# ==========================================
@router.message(F.text.lower().in_(["покинуть", "leave"]))
async def leave_race_lobby_text(message: types.Message, _=None):
    chat_id = message.chat.id
    race = active_races.get(chat_id)
    if not race or race["status"] != "lobby": return

    user_id = message.from_user.id
    if user_id not in race["players"]: return

    if user_id == race["creator_id"]:
        return await message.reply(get_str("rc_err_creator_leave", _))

    # Фикс Race-Condition: сначала стираем, потом платим
    del race["players"][user_id]
    await add_balance(user_id, race["bet"])
    
    names = ", ".join([p["name"] for p in race["players"].values()])
    msg_id = race.get("message_id")
    
    if msg_id:
        try:
            fmt_bet = f"{race['bet']:,}".replace(',', ' ')
            await message.bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=get_str("rc_lobby_body", _, bet=fmt_bet, names=names),
                reply_markup=get_lobby_keyboard(chat_id, _),
                parse_mode="HTML"
            )
        except:
            pass
            
    await message.reply(get_str("rc_leave_success", _))

# ==========================================
# 🏁 СОЗДАНИЕ ЛОББИ
# ==========================================
@router.message(F.text.lower().startswith(("гонки", "races", "гонка", "race")))
async def create_race_lobby(message: types.Message, _=None):
    parts = message.text.split()
    if len(parts) < 2: return
    try:
        bet = int(parts[1])
    except: return

    if bet < 100:
        await message.reply(get_str("rc_err_min_bet", _))
        return
    if await get_balance(message.from_user.id) < bet:
        await message.reply(get_str("rc_err_no_money", _))
        return

    chat_id = message.chat.id
    if chat_id in active_races:
        await message.reply(get_str("rc_err_already_active", _))
        return

    await add_balance(message.from_user.id, -bet)
    
    active_races[chat_id] = {
        "status": "lobby",
        "bet": bet,
        "creator_id": message.from_user.id,
        "created_at": time.time(),
        "players": {
            message.from_user.id: {
                "name": message.from_user.first_name,
                "emoji": random.choice(CAR_EMOJIS),
                "dist": 0
            }
        }
    }

    fmt_bet = f"{bet:,}".replace(',', ' ')
    sent_msg = await message.answer(
        get_str("rc_lobby_body", _, bet=fmt_bet, names=message.from_user.first_name),
        reply_markup=get_lobby_keyboard(chat_id, _),
        parse_mode="HTML"
    )
    
    active_races[chat_id]["message_id"] = sent_msg.message_id
    asyncio.create_task(auto_cancel_race(chat_id, sent_msg, _))

# ==========================================
# 🎛 ОБРАБОТКА КНОПОК
# ==========================================
@router.callback_query(F.data.startswith("race_"))
async def handle_race_clicks(callback: types.CallbackQuery, _=None):
    data = callback.data.split("_")
    action, chat_id = data[1], int(data[2])
    race = active_races.get(chat_id)
    if not race: return

    # --- ОТМЕНА ---
    if action == "cancel":
        if callback.from_user.id != race["creator_id"]:
            return await callback.answer(get_str("rc_alert_not_creator", _), show_alert=True)

        if race["status"] != "lobby":
            return await callback.answer(get_str("rc_alert_already_started", _), show_alert=True)

        for p_id in race["players"]:
            await add_balance(p_id, race["bet"])
        
        del active_races[chat_id]
        await callback.message.edit_text(get_str("rc_cancel_success", _), parse_mode="HTML")
        return await callback.answer(get_str("rc_alert_cancel", _))

    # --- ВСТУПЛЕНИЕ ---
    if action == "join":
        if callback.from_user.id in race["players"]:
            return await callback.answer(get_str("rc_alert_already_in", _), show_alert=True)
            
        if len(race["players"]) >= 10:
            return await callback.answer(get_str("rc_alert_max_players", _), show_alert=True)
            
        if await get_balance(callback.from_user.id) < race["bet"]:
            return await callback.answer(get_str("rc_alert_no_money", _), show_alert=True)

        await add_balance(callback.from_user.id, -race["bet"])
        
        used_emojis = [p["emoji"] for p in race["players"].values()]
        available = [e for e in CAR_EMOJIS if e not in used_emojis]
        emoji = random.choice(available) if available else "🚗"

        race["players"][callback.from_user.id] = {
            "name": callback.from_user.first_name,
            "emoji": emoji,
            "dist": 0
        }
        
        names = ", ".join([p["name"] for p in race["players"].values()])
        fmt_bet = f"{race['bet']:,}".replace(',', ' ')
        await callback.message.edit_text(
            get_str("rc_lobby_body", _, bet=fmt_bet, names=names),
            reply_markup=get_lobby_keyboard(chat_id, _),
            parse_mode="HTML"
        )

    # --- ПОКИНУТЬ КНОПКОЙ ---
    elif action == "leave":
        if race["status"] != "lobby":
            return await callback.answer(get_str("rc_alert_already_started", _), show_alert=True)
            
        if callback.from_user.id not in race["players"]:
            return await callback.answer(get_str("rc_alert_not_in", _), show_alert=True)
            
        if callback.from_user.id == race["creator_id"]:
            return await callback.answer(get_str("rc_alert_creator_btn_leave", _), show_alert=True)

        del race["players"][callback.from_user.id]
        await add_balance(callback.from_user.id, race["bet"])
        
        names = ", ".join([p["name"] for p in race["players"].values()])
        fmt_bet = f"{race['bet']:,}".replace(',', ' ')
        await callback.message.edit_text(
            get_str("rc_lobby_body", _, bet=fmt_bet, names=names),
            reply_markup=get_lobby_keyboard(chat_id, _),
            parse_mode="HTML"
        )
        await callback.answer(get_str("rc_alert_leave_success", _))

    # --- СТАРТ ГОНКИ ---
    elif action == "start":
        if callback.from_user.id != race["creator_id"]:
            time_passed = time.time() - race.get("created_at", 0)
            if time_passed < 20:
                time_left = int(20 - time_passed)
                return await callback.answer(get_str("rc_alert_wait_creator", _, time=time_left), show_alert=True)
                
        if len(race["players"]) < 2:
            return await callback.answer(get_str("rc_alert_min_players", _), show_alert=True)
        
        race["status"] = "racing"
        asyncio.create_task(start_the_race(chat_id, callback.message, _))

# ==========================================
# 🏎️ ДВИЖОК ГОНКИ
# ==========================================
async def start_the_race(chat_id, message: types.Message, _=None):
    race = active_races.get(chat_id)
    if not race: return
    
    finish_dist = 25 
    try: await message.pin(disable_notification=True)
    except: pass
    
    # --- 🚦 ОБРАТНЫЙ ОТСЧЕТ ---
    for i in range(3, 0, -1):
        lights = "🔴" if i == 3 else "🟡" if i == 2 else "🟢"
        try:
            await message.edit_text(get_str("rc_countdown", _, lights=lights, i=i), parse_mode="HTML")
        except: pass
        await asyncio.sleep(1)

    race["status"] = "racing"
    ticks = 0 
    
    try:
        while race["status"] == "racing":
            ticks += 1
            if ticks > 40:
                await message.edit_text(get_str("rc_timeout", _), parse_mode="HTML")
                for p_id in race["players"]:
                    await add_balance(p_id, race["bet"])
                break

            track_text = get_str("rc_track_header", _)
            winner = None
            winner_id = None

            for p_id, data in race["players"].items():
                boost = random.randint(1, 4)
                data["dist"] += boost
                
                speed_fx = " 🔥" if boost == 4 else (" 💨" if boost == 3 else "")

                before = "." * data["dist"]
                after = "." * max(0, finish_dist - data["dist"])
                track_text += f"<code>{before}</code>{data['emoji']}<code>{after}</code> | <b>{data['name']}</b>{speed_fx}\n"
                
                if data["dist"] >= finish_dist:
                    if not winner or data["dist"] > winner["dist"]:
                        winner = data
                        winner_id = p_id
            
            if winner:
                race["status"] = "finished"
                total_bank = race["bet"] * len(race["players"])
                win_amount = int(total_bank * 0.9)
                await add_balance(winner_id, win_amount, is_income=True) 

                await process_quest_action(winner_id, "race_win", 1)
                for p_id in race["players"].keys():
                    await process_quest_action(p_id, "race_play", 1)
                    await process_quest_action(p_id, "any_game_play", 1)
                
                fmt_win = f"{win_amount:,}".replace(',', ' ')
                track_text += get_str("rc_track_winner", _, name=winner['name'], win=fmt_win)
                
                try:
                    from core.database import check_and_apply_cashback
                    cashback_lines = []
                    for loser_id, loser_data in race["players"].items():
                        if loser_id != winner_id: 
                            cashback = await check_and_apply_cashback(loser_id, race["bet"])
                            if cashback > 0:
                                fmt_cb = f"{cashback:,}".replace(',', ' ')
                                cashback_lines.append(get_str("rc_track_cashback", _, name=loser_data['name'], cb=fmt_cb))
                    
                    if cashback_lines:
                        track_text += "\n" + "".join(cashback_lines)
                except Exception as e:
                    print(f"Ошибка кешбэка в гонках: {e}")
                
                try: await message.unpin()
                except: pass
                
                await message.edit_text(track_text, parse_mode="HTML")
                break 
            
            try: await message.edit_text(track_text, parse_mode="HTML")
            except: pass 
            
            await asyncio.sleep(1.5) 

    finally:
        if chat_id in active_races:
            del active_races[chat_id]

@router.message(F.chat.type.in_({"group", "supergroup"}))
async def clean_chat_during_race(message: types.Message):
    chat_id = message.chat.id
    is_race = chat_id in active_races and active_races[chat_id].get("status") == "racing"
    
    if is_race:
        text = message.text.lower() if message.text else ""
        commands = ("гонки", "races", "ассоциация", "бомба", "мины", "баланс", "б", "отмена", "cancel", "покинуть", "leave", "/")
        
        if any(text.startswith(cmd) for cmd in commands):
            return 
            
        try:
            await message.delete() 
        except:
            pass