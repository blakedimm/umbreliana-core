import asyncio
from aiogram import Router, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramForbiddenError

# Подключаем твою базу
from core.database import add_balance 

router = Router()

# --- ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ИГРЫ ---
ADMIN_ID = 1412940726 # Твой ID
game_state = "stopped" # stopped, recruiting, playing
players = {} # user_id -> Имя
choices = {} # user_id -> "green" (мир) или "red" (предатель)
recruitment_msg = None 

PRIZE_POOL = 10000000  # 10 лямов на кону
TINY_PRIZE = 1000000   # Жалкие 1м, если все будут добрыми

# ==========================================
# 🚀 1. ОТКРЫТЬ НАБОР
# ==========================================
@router.message(F.text.lower() == "ивент2")
async def create_button_game(message: types.Message):
    global game_state, players, recruitment_msg
    if message.from_user.id != ADMIN_ID: return 

    if game_state != "stopped":
        return await message.reply("⚠️ Сначала заверши текущую игру!")

    game_state = "recruiting"
    players.clear()
    choices.clear()

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Вступить (Бесплатно)", callback_data="bg_join"))
    builder.row(types.InlineKeyboardButton(text="Отмена", callback_data="bg_cancel"))

    recruitment_msg = await message.answer(
        f"🚨 <b>СОЦИАЛЬНЫЙ ЭКСПЕРИМЕНТ: «КНОПКА ЖАДНОСТИ»</b> 🚨\n\n"
        f"💰 На кону: <b>{PRIZE_POOL:,} ɢ</b>\n"
        f"💸 Участие: <b>БЕСПЛАТНО</b>\n\n"
        f"👥 <b>Участники (0):</b>\n<i>Пока никого нет...</i>\n\n"
        f"<i>Сможете ли вы договориться, или жадность уничтожит всё?</i>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    # 🔥 АВТО-ЗАКРЕП СООБЩЕНИЯ
    try:
        await recruitment_msg.pin(disable_notification=False) # False, чтобы у всех пришло уведомление о закрепе
    except Exception as e:
        print(f"Ошибка закрепа: {e}")

# ==========================================
# 🎮 КНОПКИ НАБОРА
# ==========================================
@router.callback_query(F.data.in_(["bg_join", "bg_cancel"]))
async def bg_join_or_cancel(callback: types.CallbackQuery):
    global game_state, players, recruitment_msg
    action = callback.data

    if action == "bg_cancel":
        if callback.from_user.id != ADMIN_ID:
            return await callback.answer("❌ Только создатель может отменить!", show_alert=True)
        
        game_state = "stopped"
        players.clear()
        try: await callback.message.edit_text("❌ <b>ИГРА ОТМЕНЕНА.</b>", parse_mode="HTML")
        except: pass
        return await callback.answer("Игра отменена.")

    if action == "bg_join":
        if game_state != "recruiting":
            return await callback.answer("⏳ Набор уже закрыт!", show_alert=True)

        user_id = callback.from_user.id
        if user_id in players:
            return await callback.answer("Ты уже в игре!", show_alert=True)

        try:
            # Проверка ЛС
            await callback.bot.send_message(
                user_id, 
                "✅ <b>Ты в игре!</b>\nСкоро здесь появятся кнопки выбора. Готовься сделать выбор.", 
                parse_mode="HTML"
            )
            players[user_id] = callback.from_user.first_name
            await callback.answer("✅ Успешно! Проверь ЛС.", show_alert=True)

            if recruitment_msg:
                player_links = [f"👤 <a href='tg://user?id={uid}'>{name}</a>" for uid, name in players.items()]
                players_list_str = "\n".join(player_links)

                builder = InlineKeyboardBuilder()
                builder.row(types.InlineKeyboardButton(text="Вступить (Бесплатно)", callback_data="bg_join"))
                builder.row(types.InlineKeyboardButton(text="Отмена", callback_data="bg_cancel"))

                try:
                    await recruitment_msg.edit_text(
                        f"🚨 <b>СОЦИАЛЬНЫЙ ЭКСПЕРИМЕНТ: «КНОПКА ЖАДНОСТИ»</b> 🚨\n\n"
                        f"💰 На кону: <b>{PRIZE_POOL:,} ɢ</b>\n"
                        f"👥 <b>Участники ({len(players)}):</b>\n{players_list_str}\n\n",
                        reply_markup=builder.as_markup(),
                        parse_mode="HTML"
                    )
                except: pass

        except TelegramForbiddenError:
            await callback.answer("❌ ОШИБКА: Напиши боту в ЛС /start !", show_alert=True)

# ==========================================
# 🚀 2. СТАРТ РАУНДА (РАЗДАЧА КНОПОК)
# ==========================================
@router.message(F.text.lower() == "раунд2")
async def start_button_round(message: types.Message):
    global game_state, choices
    if message.from_user.id != ADMIN_ID: return
    if len(players) < 2: return await message.reply("Нужно минимум 2 человека!")

    game_state = "playing"
    choices.clear()

    await message.answer(
        f"🤫 <b>ИГРА НАЧАЛАСЬ!</b>\n\n"
        f"Всем участникам в ЛС отправлен выбор.\n"
        f"Договоритесь в чате, или предайте всех. Выбор за вами.",
        parse_mode="HTML"
    )

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🟢 РАЗДЕЛИТЬ", callback_data="bg_choice_green"))
    builder.row(types.InlineKeyboardButton(text="🔴 ЗАБРАТЬ ВСЁ", callback_data="bg_choice_red"))

    for uid in list(players.keys()):
        try:
            await message.bot.send_message(
                uid,
                f"⚖️ <b>ВРЕМЯ ВЫБИРАТЬ</b>\n\n"
                f"🟢 <b>РАЗДЕЛИТЬ:</b> Если ВСЕ нажмут зеленую, вы разделите жалкие <b>{TINY_PRIZE:,} ɢ</b>.\n"
                f"🔴 <b>ЗАБРАТЬ ВСЁ:</b> Если ты ОДИН нажмешь красную, ты заберешь <b>{PRIZE_POOL:,} ɢ</b>. "
                f"Но если красную нажмут двое и больше — <b>ДЕНЬГИ СГОРЯТ</b>.\n\n"
                f"<i>У тебя одна попытка.</i>",
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )
        except: pass 

# ==========================================
# 🎮 ОБРАБОТКА ВЫБОРА В ЛС И ОТЧЕТ АДМИНУ
# ==========================================
@router.callback_query(F.data.startswith("bg_choice_"))
async def process_bg_choice(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user_name = callback.from_user.full_name
    
    # Получаем выбор ("green" или "red")
    choice = callback.data.split("_")[2] 

    if game_state != "playing" or user_id not in players:
        return await callback.answer("Ты не участвуешь или раунд окончен.", show_alert=True)

    if user_id in choices:
        return await callback.answer("❌ Выбор уже сделан! Назад пути нет.", show_alert=True)
    
    # Сохраняем выбор игрока
    choices[user_id] = choice
    
    # --- ЛОГИКА ОТВЕТА ИГРОКУ И ОТЧЕТА АДМИНУ ---
    if choice == "green":
        await callback.answer("🟢 Выбор принят: МИР. Молись, чтобы другие сделали так же.", show_alert=True)
        
        # 🔥 ШПИОНСКИЙ ОТЧЕТ ТЕБЕ В ЛС
        try:
            await callback.bot.send_message(
                ADMIN_ID, 
                f"👤 Игрок <b>{user_name}</b> (<code>{user_id}</code>) нажал 🟢 <b>МИР (Разделить)</b>", 
                parse_mode="HTML"
            )
        except: pass
        
    else:
        await callback.answer("🔴 Выбор принят: ПРЕДАТЕЛЬСТВО. Жди итогов.", show_alert=True)
        
        # 🔥 ШПИОНСКИЙ ОТЧЕТ ТЕБЕ В ЛС
        try:
            await callback.bot.send_message(
                ADMIN_ID, 
                f"🚨 Игрок <b>{user_name}</b> (<code>{user_id}</code>) нажал 🔴 <b>ПРЕДАТЬ ВСЕХ</b>!", 
                parse_mode="HTML"
            )
        except: pass

    # Убираем кнопки у игрока после выбора
    try: await callback.message.edit_reply_markup(reply_markup=None) 
    except: pass

# ==========================================
# 🕵️ ШПИОН-ПАНЕЛЬ: КТО КРЫСА
# ==========================================
@router.message(F.text.lower() == "кто крыса")
async def spy_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    
    # 🧹 Удаляем твое сообщение мгновенно
    try: await message.delete()
    except: pass

    if game_state != "playing":
        return await message.bot.send_message(ADMIN_ID, "Игра не запущена.")

    reds = [players[uid] for uid, c in choices.items() if c == "red"]
    greens = [players[uid] for uid, c in choices.items() if c == "green"]
    unassigned = [name for uid, name in players.items() if uid not in choices]

    text = "🕵️ <b>СВОДКА ПО КРЫСАМ</b>\n════════════════════\n"
    text += f"🔴 <b>ПРЕДАТЕЛИ ({len(reds)}):</b>\n" + ("\n".join([f"🔪 {n}" for n in reds]) if reds else "<i>Пока чисто</i>") + "\n\n"
    text += f"🟢 <b>ДОБРЯКИ ({len(greens)}):</b>\n" + ("\n".join([f"🕊 {n}" for n in greens]) if greens else "<i>Никого</i>") + "\n\n"
    text += f"⏳ <b>ДУМАЮТ ({len(unassigned)}):</b>\n" + ("\n".join([f"🤔 {n}" for n in unassigned]) if unassigned else "<i>Все проголосовали</i>")
    
    await message.bot.send_message(ADMIN_ID, text, parse_mode="HTML")

# ==========================================
# 🚀 3. ИТОГИ РАУНДА (ОБНОВЛЕННАЯ ВЕРСИЯ С КАРМОЙ)
# ==========================================
@router.message(F.text.lower() == "итог2")
async def finish_button_round(message: types.Message):
    global game_state, players
    if message.from_user.id != ADMIN_ID: return
    if game_state != "playing": return await message.reply("Раунд не запущен!")

    countdown_msg = await message.answer("⏳ <b>Анализ честности... 3️⃣</b>", parse_mode="HTML")
    await asyncio.sleep(1)
    await countdown_msg.edit_text("⏳ <b>Анализ честности... 2️⃣</b>", parse_mode="HTML")
    await asyncio.sleep(1)
    await countdown_msg.edit_text("⏳ <b>Анализ честности... 1️⃣</b>", parse_mode="HTML")
    await asyncio.sleep(1)

    red_uids = [uid for uid, c in choices.items() if c == "red"]
    green_uids = [uid for uid, c in choices.items() if c == "green"]
    
    # Все, кто не нажал, по дефолту добряки
    for uid in players.keys():
        if uid not in choices:
            green_uids.append(uid) 

    game_state = "stopped"

    if len(red_uids) == 0:
        # ИСХОД 1: ВСЕ ЧЕСТНЫЕ
        share = TINY_PRIZE // len(players)
        for uid in players.keys():
            add_balance(uid, share)
        
        await countdown_msg.edit_text(
            f"🕊 <b>УТОПИЯ ДОСТИГНУТА!</b>\n\n"
            f"Ни один человек не нажал красную кнопку. Вы доверились друг другу.\n"
            f"💰 Приз за скучную честность: <b>{TINY_PRIZE:,} ɢ</b> разделен между всеми.\n"
            f"💸 Каждый получил по <b>{share:,} ɢ</b>.",
            parse_mode="HTML"
        )

    elif len(red_uids) == 1:
        # ИСХОД 2: ОДИН УДАЧЛИВЫЙ ПРЕДАТЕЛЬ
        winner_id = red_uids[0]
        winner_name = players[winner_id]
        add_balance(winner_id, PRIZE_POOL)
        
        await countdown_msg.edit_text(
            f"🔪 <b>ИДЕАЛЬНОЕ ПРЕСТУПЛЕНИЕ!</b>\n\n"
            f"Только ОДИН человек решился на предательство и сорвал куш.\n"
            f"👑 <a href='tg://user?id={winner_id}'><b>{winner_name}</b></a> забирает все <b>{PRIZE_POOL:,} ɢ</b>.\n"
            f"Остальные остались с носом.",
            parse_mode="HTML"
        )

    else:
        # ИСХОД 3: КАРМИЧЕСКАЯ СПРАВЕДЛИВОСТЬ (ТВОЯ НОВАЯ ФИШКА)
        if len(green_uids) > 0:
            share = PRIZE_POOL // len(green_uids)
            for uid in green_uids:
                add_balance(uid, share)
            
            traitors_list = "\n".join([f"🐀 {players[uid]}" for uid in red_uids])
            
            await countdown_msg.edit_text(
                f"⚖️ <b>МГНОВЕННАЯ КАРМА!</b>\n\n"
                f"Сразу несколько человек (<b>{len(red_uids)}</b>) попытались крысануть и забрать всё себе.\n"
                f"В итоге они аннулировали выигрыши друг друга!\n\n"
                f"🎁 Весь фонд <b>{PRIZE_POOL:,} ɢ</b> переходит честным игрокам!\n"
                f"💸 Каждому добряку выплачено по <b>{share:,} ɢ</b>.\n\n"
                f"Вот список неудачливых предателей, которые спонсировали вашу победу:\n"
                f"{traitors_list}",
                parse_mode="HTML"
            )
        else:
            # Если вообще все нажали красную (редкий случай)
            await countdown_msg.edit_text(
                f"🩸 <b>ПОЛНОЕ УНИЧТОЖЕНИЕ!</b>\n\n"
                f"Абсолютно каждый участник нажал 🔴 КРАСНУЮ кнопку.\n"
                f"Предавать было некого, поэтому <b>{PRIZE_POOL:,} ɢ</b> сгорают впустую.\n"
                f"Вы заслужили это.",
                parse_mode="HTML"
            )

    players.clear()