import asyncio
import random
from aiogram import Router, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramForbiddenError

from core.database import get_balance, add_balance 

router = Router()

# --- ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ИГРЫ ---
ADMIN_ID = 1412940726 # Только ты можешь рулить игрой
game_state = "stopped" # stopped, recruiting, playing
players = {} # user_id -> Имя
choices = {} # user_id -> "red" или "blue"
GROUP_CHAT_ID = None 
recruitment_msg = None # Запоминаем сообщение набора, чтобы его обновлять
PEEK_COST = 100000 
peek_buyers = set() 
sabotage_buyers = set() # Кто купил саботаж
shield_buyers = set()   # Кто купил бункер

SABOTAGE_COST = 200000
SHIELD_COST = 500000
PRIZE_POOL = 10000000

# ==========================================
# 🚀 1. АДМИН: ОТКРЫТЬ НАБОР
# ==========================================
@router.message(F.text.lower() == "ивент")
async def create_game(message: types.Message):
    global game_state, players, GROUP_CHAT_ID, recruitment_msg
    if message.from_user.id != ADMIN_ID: return 

    if game_state != "stopped":
        return await message.reply("⚠️ Сначала заверши или отмени текущую игру!")

    game_state = "recruiting"
    players.clear()
    GROUP_CHAT_ID = message.chat.id 

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Вступить", callback_data="sg_join"))
    builder.row(types.InlineKeyboardButton(text="Отмена", callback_data="sg_cancel"))

    recruitment_msg = await message.answer(
        f"🚨 <b>ОТКРЫТ НАБОР В ИГРУ!</b> 🚨\n\n"
        f"💰 Главный приз: <b>{PRIZE_POOL:,} ᴜ</b>\n"
        f"👥 <b>Участники (0):</b>\n<i>Пока никого нет...</i>\n\n",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

# ==========================================
# 🎮 КНОПКИ НАБОРА: ВСТУПИТЬ / ОТМЕНИТЬ
# ==========================================
@router.callback_query(F.data.in_(["sg_join", "sg_cancel"]))
async def join_or_cancel_game(callback: types.CallbackQuery):
    global game_state, players, recruitment_msg
    action = callback.data

    if action == "sg_cancel":
        if callback.from_user.id != ADMIN_ID:
            return await callback.answer("❌ Только создатель может отменить игру!", show_alert=True)
        
        if game_state != "recruiting":
            return await callback.answer("Уже поздно отменять через эту кнопку.", show_alert=True)

        game_state = "stopped"
        players.clear()
        try:
            await callback.message.edit_text("❌ <b>ИГРА ОТМЕНЕНА АДМИНИСТРАТОРОМ.</b>\nНабор закрыт.", parse_mode="HTML")
        except: pass
        return await callback.answer("Игра отменена.")

    if action == "sg_join":
        if game_state != "recruiting":
            return await callback.answer("⏳ Набор уже закрыт!", show_alert=True)

        user_id = callback.from_user.id
        if user_id in players:
            return await callback.answer("Ты уже в списке смертников!", show_alert=True)

        try:
            await callback.bot.send_message(
                user_id, 
                "✅ <b>Ты успешно зарегистрирован в игре!</b>\nЖди начала раунда, двери появятся прямо здесь.", 
                parse_mode="HTML"
            )
            players[user_id] = callback.from_user.first_name
            await callback.answer("✅ Успешно! Проверь ЛС от бота.", show_alert=True)

            if recruitment_msg:
                player_links = [f"👤 <a href='tg://user?id={uid}'>{name}</a>" for uid, name in players.items()]
                players_list_str = "\n".join(player_links)

                builder = InlineKeyboardBuilder()
                builder.row(types.InlineKeyboardButton(text="Вступить", callback_data="sg_join"))
                builder.row(types.InlineKeyboardButton(text="Отмена", callback_data="sg_cancel"))

                try:
                    await recruitment_msg.edit_text(
                        f"🚨 <b>ОТКРЫТ НАБОР В ИГРУ!</b> 🚨\n\n"
                        f"💰 Главный приз: <b>{PRIZE_POOL:,} ᴜ</b>\n"
                        f"👥 <b>Участники ({len(players)}):</b>\n{players_list_str}\n\n"
                        f"⚠️ <b>ВАЖНО:</b> У вас должен быть открыт диалог со мной в ЛС!\n\n",
                        reply_markup=builder.as_markup(),
                        parse_mode="HTML"
                    )
                except: pass

        except TelegramForbiddenError:
            await callback.answer("❌ ОШИБКА: Перейди в ЛС бота и нажми /start, иначе я не смогу присылать тебе двери!", show_alert=True)

# ==========================================
# 🚀 2. АДМИН: РАЗДАТЬ ДВЕРИ (НАЧАТЬ РАУНД)
# ==========================================
@router.message(F.text.lower() == "раунд")
async def start_round(message: types.Message):
    global game_state, choices, peek_buyers, sabotage_buyers, shield_buyers
    if message.from_user.id != ADMIN_ID: return

    if len(players) < 2:
        return await message.reply("Слишком мало людей для игры (нужно минимум 2).")

    game_state = "playing"
    choices.clear()
    peek_buyers.clear()
    sabotage_buyers.clear() 
    shield_buyers.clear()   

    player_links = [f"<a href='tg://user?id={uid}'>{name}</a>" for uid, name in players.items()]
    players_list_str = ", ".join(player_links)

    await message.answer(
        f"🚪 <b>РАУНД НАЧАЛСЯ!</b>\n"
        f"👥 В игре {len(players)} чел:\n{players_list_str}\n\n"
        f"<i>Всем выжившим отправлены двери в ЛС. Сделайте свой выбор.</i>",
        parse_mode="HTML"
    )

    # 🔥 ОТЧЁТ АДМИНУ В ЛС
    try:
        await message.bot.send_message(
            ADMIN_ID,
            f"🕵️ <b>Раунд запущен!</b>\n"
            f"Начальный шанс взрыва красной: 50%. Ждём донатов от игроков."
        )
    except: pass

    for uid in list(players.keys()):
        try:
            await message.bot.send_message(
                uid,
                "⏳ <b>СДЕЛАЙ ВЫБОР</b>\nУ тебя одна попытка. Какая дверь безопасна?",
                reply_markup=get_pm_keyboard(uid),
                parse_mode="HTML"
            )
        except: pass 

def get_pm_keyboard(user_id):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="🔴 Красная", callback_data="sg_red"),
        types.InlineKeyboardButton(text="🔵 Синяя", callback_data="sg_blue")
    )
    
    peek_text = "👁 Подсмотреть (АКТИВНО)" if user_id in peek_buyers else f"👁 Подсмотреть ({PEEK_COST//1000}k ᴜ)"
    builder.row(types.InlineKeyboardButton(text=peek_text, callback_data="sg_peek"))
    
    sab_text = "☠️ Саботаж (АКТИВНО)" if user_id in sabotage_buyers else f"☠️ Саботаж ({SABOTAGE_COST//1000}k ᴜ)"
    shield_text = "🛡 Бункер (АКТИВНО)" if user_id in shield_buyers else f"🛡 Бункер ({SHIELD_COST//1000}k ᴜ)"
    builder.row(
        types.InlineKeyboardButton(text=sab_text, callback_data="sg_sabotage"),
        types.InlineKeyboardButton(text=shield_text, callback_data="sg_shield")
    )
    return builder.as_markup()

# Функция для расчета текущего шанса (вынесена отдельно для админа)
def calculate_current_chance():
    red_chance = 50 
    for uid, choice in choices.items():
        if uid in sabotage_buyers:
            if choice == "blue": red_chance += 10 
            else: red_chance -= 10 
        if uid in shield_buyers:
            if choice == "red": red_chance -= 10 
            else: red_chance += 10 
    return max(5, min(95, red_chance))

# ==========================================
# 🎮 КНОПКИ В ЛС: ВЫБОР И ПОДГЛЯДЫВАНИЕ
# ==========================================
@router.callback_query(F.data.in_(["sg_red", "sg_blue", "sg_peek", "sg_sabotage", "sg_shield"]))
async def pm_actions(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user_name = callback.from_user.full_name
    action = callback.data.split("_")[1]

    if game_state != "playing" or user_id not in players:
        return await callback.answer("Ты не участвуешь или раунд не активен.", show_alert=True)

    # --- ЛОГИКА ВЫБОРА ДВЕРИ ---
    if action in ["red", "blue"]:
        if user_id in choices:
            return await callback.answer("❌ Ты уже сделал свой выбор! Назад пути нет.", show_alert=True)
        
        choices[user_id] = action
        color = "🔴 Красную" if action == "red" else "🔵 Синюю"
        await callback.answer(f"🤫 Выбор принят: {color}. Жди итогов в группе.", show_alert=True)
        
        # 🔥 ШПИОНСКИЙ ОТЧЕТ АДМИНУ
        try:
            door_icon = "🔴" if action == "red" else "🔵"
            await callback.bot.send_message(
                ADMIN_ID,
                f"👤 {user_name} выбрал {door_icon} дверь!"
            )
        except: pass

        try: await callback.message.edit_reply_markup(reply_markup=get_pm_keyboard(user_id))
        except: pass

    # --- ЛОГИКА РАЗВЕДКИ ---
    elif action == "peek":
        if user_id not in peek_buyers:
            bal = get_balance(user_id)
            if bal < PEEK_COST:
                return await callback.answer(f"❌ Нужно {PEEK_COST} ᴜ для разведки!", show_alert=True)

            add_balance(user_id, -PEEK_COST)
            peek_buyers.add(user_id)

            try: await callback.message.edit_reply_markup(reply_markup=get_pm_keyboard(user_id))
            except: pass

        red_c = sum(1 for c in choices.values() if c == "red")
        blue_c = sum(1 for c in choices.values() if c == "blue")
        unassigned = len(players) - (red_c + blue_c)

        await callback.answer(
            f"👁 РАЗВЕДКА:\n🔴 Выбрали: {red_c}\n🔵 Выбрали: {blue_c}\n⏳ Думают: {unassigned}",
            show_alert=True
        )

    # --- ЛОГИКА САБОТАЖА ---
    elif action == "sabotage":
        if user_id not in choices:
            return await callback.answer("❌ Сначала выбери свою дверь!", show_alert=True)
        
        if user_id not in sabotage_buyers:
            bal = get_balance(user_id)
            if bal < SABOTAGE_COST:
                return await callback.answer(f"❌ Нужно {SABOTAGE_COST} ᴜ для саботажа!", show_alert=True)

            add_balance(user_id, -SABOTAGE_COST)
            sabotage_buyers.add(user_id)

            # 🔥 ШПИОНСКИЙ ОТЧЕТ АДМИНУ
            try:
                current_chance = calculate_current_chance()
                await callback.bot.send_message(
                    ADMIN_ID,
                    f"☠️ {user_name} КУПИЛ САБОТАЖ!\n"
                    f"📊 Шанс взрыва КРАСНОЙ двери теперь: {current_chance}%"
                )
            except: pass

            try: await callback.message.edit_reply_markup(reply_markup=get_pm_keyboard(user_id))
            except: pass

        await callback.answer("☠️ Бомба заложена! Шанс взрыва ЧУЖОЙ двери увеличен на 10%.", show_alert=True)

    # --- ЛОГИКА БУНКЕРА ---
    elif action == "shield":
        if user_id not in choices:
            return await callback.answer("❌ Сначала выбери свою дверь!", show_alert=True)
        
        if user_id not in shield_buyers:
            bal = get_balance(user_id)
            if bal < SHIELD_COST:
                return await callback.answer(f"❌ Нужно {SHIELD_COST} ᴜ для бункера!", show_alert=True)

            add_balance(user_id, -SHIELD_COST)
            shield_buyers.add(user_id)

            # 🔥 ШПИОНСКИЙ ОТЧЕТ АДМИНУ
            try:
                current_chance = calculate_current_chance()
                await callback.bot.send_message(
                    ADMIN_ID,
                    f"🛡 {user_name} КУПИЛ БУНКЕР!\n"
                    f"📊 Шанс взрыва КРАСНОЙ двери теперь: {current_chance}%"
                )
            except: pass

            try: await callback.message.edit_reply_markup(reply_markup=get_pm_keyboard(user_id))
            except: pass

        await callback.answer("🛡 Дверь укреплена! Шанс взрыва ТВОЕЙ двери снижен на 10%.", show_alert=True)

# ==========================================
# 👑 ПУЛЬТ БОГА: РЕАЛЬНОЕ ВРЕМЯ (СКРЫТНЫЙ РЕЖИМ)
# ==========================================
@router.message(F.text.lower() == "инфо ивент")
async def admin_live_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    
    # 🧹 Мгновенно удаляем твоё сообщение из группы, чтобы никто не спалил
    try:
        await message.delete()
    except:
        pass # Если ты написал в ЛС, удалять не обязательно

    if game_state != "playing":
        # Отвечаем строго в ЛС
        return await message.bot.send_message(ADMIN_ID, "Раунд не запущен.")
    
    current_chance = calculate_current_chance()
    red_c = sum(1 for c in choices.values() if c == "red")
    blue_c = sum(1 for c in choices.values() if c == "blue")
    
    text = (
        "🕵️ <b>LIVE-СТАТУС ИВЕНТА</b>\n"
        "════════════════════\n"
        f"📊 <b>Шанс взрыва КРАСНОЙ: {current_chance}%</b>\n"
        f"📊 <b>Шанс взрыва СИНЕЙ: {100 - current_chance}%</b>\n"
        "════════════════════\n"
        f"🔴 В красной: {red_c} чел.\n"
        f"🔵 В синей: {blue_c} чел.\n"
        "════════════════════\n"
        "<i>Данные меняются при каждой покупке щита/бомбы.</i>"
    )
    # 📩 Отправляем результат тебе прямо в личку
    await message.bot.send_message(ADMIN_ID, text, parse_mode="HTML")
    
# ==========================================
# 🚀 3. АДМИН: ИТОГ РАУНДА (ВЗРЫВ)
# ==========================================
@router.message(F.text.lower() == "итог")
async def finish_round(message: types.Message):
    global game_state, players
    if message.from_user.id != ADMIN_ID: return
    if game_state != "playing": return await message.reply("Раунд не запущен!")

    countdown_msg = await message.answer("⏳ <b>Время вышло! Открываем двери... 3️⃣</b>", parse_mode="HTML")
    await asyncio.sleep(1)
    await countdown_msg.edit_text("⏳ <b>Время вышло! Открываем двери... 2️⃣</b>", parse_mode="HTML")
    await asyncio.sleep(1)
    await countdown_msg.edit_text("⏳ <b>Время вышло! Открываем двери... 1️⃣</b>", parse_mode="HTML")
    await asyncio.sleep(1)

    red_chance = calculate_current_chance()

    # Кидаем кубик
    roll = random.randint(1, 100)
    if roll <= red_chance:
        death_door = "red"
    else:
        death_door = "blue"

    safe_door = "blue" if death_door == "red" else "red"
    door_emoji = "🔴 КРАСНАЯ" if death_door == "red" else "🔵 СИНЯЯ"

    survivors = {}
    dead_count = 0

    for uid, name in players.items():
        user_choice = choices.get(uid)
        if user_choice == safe_door:
            survivors[uid] = name
        else:
            dead_count += 1

    players = survivors
    game_state = "recruiting" 

    final_chance = red_chance if death_door == "red" else (100 - red_chance)
    
    text = (
        f"💥 <b>{door_emoji} ДВЕРЬ БЫЛА ЗАМИНИРОВАНА!</b>\n"
        f"📊 <i>С учетом саботажей и бункеров, шанс её взрыва составлял: <b>{final_chance}%</b></i>\n\n"
        f"💀 Погибло в этом раунде: <b>{dead_count}</b>\n"
        f"🏃‍♂️ Осталось выживших: <b>{len(players)}</b>\n\n"
    )

    if len(players) == 1:
        game_state = "stopped"
        winner_id = list(players.keys())[0]
        winner_name = players[winner_id]
        add_balance(winner_id, PRIZE_POOL)
        
        await countdown_msg.edit_text(
            f"{text}🎉🎉🎉 <b>ГРАНД ФИНАЛ!</b> 🎉🎉🎉\n\n"
            f"👑 Чемпионом Смертельной Игры становится <a href='tg://user?id={winner_id}'><b>{winner_name}</b></a>!\n\n"
            f"Его тактика, интуиция и толстый кошелек оказались безупречными.\n"
            f"💰 Он с боем вырывает главный куш: <b>{PRIZE_POOL:,} ᴜ</b>! Наши поздравления!",
            parse_mode="HTML"
        )
    elif len(players) == 0:
        game_state = "stopped"
        await countdown_msg.edit_text(f"{text}☠️ <b>ЖАЛКОЕ ЗРЕЛИЩЕ.</b>\nНикто не выжил. Все участники погибли, а призовой фонд сгорает в огне.", parse_mode="HTML")
    else:
        text += "<i>Админ готовит следующий раунд... Выжившие, не расслабляться!</i>"
        await countdown_msg.edit_text(text, parse_mode="HTML")