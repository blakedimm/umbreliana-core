import re
import random
from aiogram import Router, types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder

# 🔥 ПЛОСКИЕ ИМПОРТЫ
from database import get_balance, add_balance

# Создаем отдельный роутер для игры
router = Router()

# Локальное хранилище для активных игр
active_mines = {}
mines_start_lock = set()

ADMIN_ID = 1412940726

# Настройки режимов
DIFFICULTIES = {
    'легкий': {'bombs': 3, 'mult': 0.1, 'emoji': '🟢'},
    'средний': {'bombs': 5, 'mult': 0.2, 'emoji': '🟡'},
    'сложный': {'bombs': 10, 'mult': 0.5, 'emoji': '🔴'},
    'эксперт': {'bombs': 15, 'mult': 1.2, 'emoji': '💀'},
    'безумец': {'bombs': 20, 'mult': 3.0, 'emoji': '😈'},
    'ебанутый': {'bombs': 24, 'mult': 24.0, 'emoji': '☢️'}
}

# 1. Генерация клавиатуры
def get_mines_keyboard(user_id, game_over=False):
    game = active_mines[user_id]
    builder = InlineKeyboardBuilder()

    # Сетка ячеек
    for i in range(25):
        if game['opened'][i] or game_over:
            text = "💣" if game['mines'][i] == 1 else "💎"
            cb_data = "ignore"
        else:
            text = "✖️"
            cb_data = f"mine_step_{user_id}_{i}"
        builder.button(text=text, callback_data=cb_data)

    builder.adjust(5)

    # Кнопки управления под сеткой
    if not game_over:
        if game['step'] > 0:
            builder.row(types.InlineKeyboardButton(
                text="💰 Забрать выигрыш", 
                callback_data=f"mine_take_{user_id}"
            ))
        else:
            builder.row(types.InlineKeyboardButton(
                text="❌ Отменить", 
                callback_data=f"mine_cancel_{user_id}"
            ))

    return builder.as_markup()

# 2. Обработка нажатий
@router.callback_query(F.data.startswith("mine_"))
async def process_mine_click(callback: types.CallbackQuery):
    data = callback.data.split("_")
    action = data[1]
    owner_id = int(data[2])

    if callback.from_user.id != owner_id:
        await callback.answer("Эу, куда лезешь, это чужое поле!", show_alert=True)
        return

    if owner_id not in active_mines:
        await callback.answer("Игра уже завершена.")
        return

    game = active_mines[owner_id]
    fmt_bet = f"{game['bet']:,}".replace(',', ' ')
    
    # Считаем множитель на основе сложности
    current_multiplier = 1.0 + (game['step'] * game['mult_step'])

    # --- ЛОГИКА ОТМЕНЫ ---
    if action == "cancel":
        if game['step'] == 0:
            await add_balance(owner_id, game['bet'])
            await callback.message.edit_text(f"❌ <b>Игра отменена.</b>\nСтавка <b>{fmt_bet}</b> UMBREL возвращена.", parse_mode="HTML")
        else:
            await callback.message.edit_text(f"❌ <b>Игра завершена.</b>\nСтавка <b>{fmt_bet}</b> UMBREL сгорела.", parse_mode="HTML")
        del active_mines[owner_id]
        return

    # --- ЛОГИКА "ЗАБРАТЬ" ---
    elif action == "take":
        win_amount = int(game['bet'] * current_multiplier)
        await add_balance(owner_id, win_amount, is_income=True)
        
        fmt_win = f"{win_amount:,}".replace(',', ' ')

        kb = get_mines_keyboard(owner_id, game_over=True)
        del active_mines[owner_id]

        await callback.message.edit_text(
            f"🎉 Вы вовремя остановились!\nРежим: {game['diff_name']}\nВыигрыш: <b>{fmt_win}</b> UMBREL (x{current_multiplier:.2f})", 
            reply_markup=kb,
            parse_mode="HTML"
        )
        return

    # --- ЛОГИКА КЛИКА ПО КЛЕТКЕ ---
    elif action == "step":
        index = int(data[3])
        if game['opened'][index]:
            await callback.answer("Уже открыто!")
            return

        game['opened'][index] = True
        if game['mines'][index] == 1:
            # ВЗРЫВ
            kb = get_mines_keyboard(owner_id, game_over=True)
            lost_bet = game['bet'] 
            del active_mines[owner_id]
            
            await callback.message.edit_text(
                f"💥 БУМ! Вы подорвались на мине.\nРежим: {game['diff_name']}\nСтавка <b>{fmt_bet}</b> UMBREL сгорела.", 
                reply_markup=kb,
                parse_mode="HTML"
            )
        else:
            # АЛМАЗ
            game['step'] += 1
            new_multiplier = 1.0 + (game['step'] * game['mult_step'])
            kb = get_mines_keyboard(owner_id)
            await callback.message.edit_text(
                f"💎 Алмаз найден!\nРежим: {game['diff_name']}\nМножитель: <b>x{new_multiplier:.2f}</b>\nПродолжаем или забираем?", 
                reply_markup=kb,
                parse_mode="HTML"
            )

# 3. Умный запуск игры (понимает любой порядок слов)
@router.message(lambda msg: msg.text and "мины" in msg.text.lower().split() and "отменить" not in msg.text.lower())
async def play_mines(message: types.Message):
    user_id = message.from_user.id

    # 🔥 1. ЖЕЛЕЗНЫЙ ЗАМОК: Отбиваем спам-клики
    if user_id in mines_start_lock:
        return 
        
    # 🔥 2. ПРОВЕРКА АКТИВНОЙ ИГРЫ
    if user_id in active_mines:
        return await message.reply("⚠️ У тебя уже есть активная игра! Если кнопки пропали, напиши: <code>отменить мины</code>", parse_mode="HTML")

    parts = message.text.lower().split()
    if len(parts) < 2 or len(parts) > 3: return
        
    parts.remove("мины")
    amount_str = None
    diff_key = 'средний' 
    
    for part in parts:
        if part in DIFFICULTIES: diff_key = part 
        elif re.match(r"^\d+[kкmм]*$", part): amount_str = part 
            
    if not amount_str: return

    amount_str = amount_str.replace('к', '000').replace('k', '000').replace('м', '000000').replace('m', '000000')
    try: amount = int(amount_str)
    except ValueError: return

    if amount <= 0:
        return await message.reply("⚠️ Ставка должна быть больше 0 UMBREL!")

    # 🔥 ЗАКРЫВАЕМ ЗАМОК (Начинаем тяжелую транзакцию)
    mines_start_lock.add(user_id)

    try:
        if await get_balance(user_id) < amount:
            return await message.reply("❌ Недостаточно UMBREL!")

        await add_balance(user_id, -amount)

        config = DIFFICULTIES[diff_key]
        bombs_count = config['bombs']
        mult_step = config['mult']
        emoji = config['emoji']
        diff_name = f"{emoji} {diff_key.capitalize()}"

        mines_positions = [1] * bombs_count + [0] * (25 - bombs_count)
        random.shuffle(mines_positions)

        active_mines[user_id] = {
            'bet': amount, 
            'mines': mines_positions,
            'opened': [False] * 25, 
            'step': 0,
            'mult_step': mult_step,
            'diff_name': diff_name
        }

        kb = get_mines_keyboard(user_id)
        fmt_amount = f"{amount:,}".replace(',', ' ')
        
        game_msg = await message.reply(
            f"💣 Игра началась!\nРежим: <b>{diff_name}</b> ({bombs_count} мин)\nСтавка: <b>{fmt_amount}</b> UMBREL", 
            reply_markup=kb,
            parse_mode="HTML"
        )

        active_mines[user_id]['message_id'] = game_msg.message_id
        active_mines[user_id]['chat_id'] = message.chat.id

    except Exception as e:
        import logging
        logging.error(f"Ошибка при старте мин: {e}")
        if user_id in active_mines:
            await add_balance(user_id, amount)
            del active_mines[user_id]
        await message.reply("⚠️ Ошибка создания поля. Ставка возвращена.")
    finally:
        # 🔥 СНИМАЕМ ЗАМОК
        if user_id in mines_start_lock:
            mines_start_lock.remove(user_id)

# ==========================================
# 👑 АДМИН-ПАНЕЛЬ: ПРИНУДИТЕЛЬНАЯ ОТМЕНА МИН
# ==========================================
@router.message((F.text.lower().startswith("отмена мин")) & (F.from_user.id == ADMIN_ID))
async def admin_cancel_mines(message: types.Message):
    target_id = None
    target_name = "Игрок"

    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        target_name = message.reply_to_message.from_user.first_name
    else:
        parts = message.text.split()
        if len(parts) > 2 and parts[2].isdigit():
            target_id = int(parts[2])
            target_name = f"ID:{target_id}"

    if not target_id:
        await message.reply("⚠️ Ответь на сообщение игрока командой <code>отмена мин</code> или напиши <code>отмена мин [ID]</code>", parse_mode="HTML")
        return

    if target_id not in active_mines:
        await message.reply(f"У <b>{target_name}</b> сейчас нет активных игр в мины.", parse_mode="HTML")
        return

    game = active_mines[target_id]
    bet = game['bet']
    game_msg_id = game.get('message_id')
    game_chat_id = game.get('chat_id')
    
    if game_msg_id and game_chat_id:
        try:
            await message.bot.edit_message_text(
                chat_id=game_chat_id,
                message_id=game_msg_id,
                text=f"🛑 <b>Игра принудительно отменена администратором.</b>\nСтавка возвращена.",
                reply_markup=None,
                parse_mode="HTML"
            )
        except: pass

    await add_balance(target_id, bet)
    del active_mines[target_id]
    
    fmt_bet = f"{bet:,}".replace(',', ' ')
    await message.reply(
        f"🚓 <b>ОФШОР НАКРЫТ!</b>\n"
        f"Игра пользователя <b>{target_name}</b> принудительно закрыта.\n"
        f"Спрятанная ставка <b>{fmt_bet}</b> UMBREL возвращена ему на баланс.\n"
        f"<i>Минное поле деактивировано!</i>", 
        parse_mode="HTML"
    )

async def safe_cashout_all(bot):
    """Авто-выплата всех активных игр в минах при выключении."""
    if not active_mines:
        return

    from database import add_balance
    
    for user_id, game in list(active_mines.items()):
        try:
            bet = game['bet']
            steps = game['step']
            mult_step = game['mult_step']
            chat_id = game.get('chat_id')
            msg_id = game.get('message_id')
            
            current_multiplier = 1.0 + (steps * mult_step)
            win_amount = int(bet * current_multiplier)

            await add_balance(user_id, win_amount, is_income=True)
            
            if chat_id and msg_id:
                try:
                    text = (
                        f"⚙️ <b>СИСТЕМНОЕ ОБНОВЛЕНИЕ</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"Турнирная Арена ушла на перезагрузку. Твоя игра завершена автоматически.\n"
                        f"💰 Выигрыш <b>{win_amount:,} ᴜ</b> зачислен на баланс!".replace(',', ' ')
                    )
                    await bot.edit_message_text(
                        chat_id=chat_id, 
                        message_id=msg_id, 
                        text=text, 
                        reply_markup=None, 
                        parse_mode="HTML"
                    )
                except: pass
            
            del active_mines[user_id]
            
        except Exception as e:
            print(f"Ошибка спасения мин для {user_id}: {e}")

# ==========================================
# 🛑 ЭКСТРЕННАЯ ОТМЕНА ЗАВИСШЕЙ ИГРЫ (ДЛЯ ИГРОКА)
# ==========================================
@router.message(F.text.lower() == "отменить мины")
async def force_cancel_my_mines(message: types.Message):
    user_id = message.from_user.id
    
    if user_id not in active_mines:
        return await message.reply("У тебя нет активных игр в мины.")
        
    game = active_mines[user_id]
    bet = game.get('bet', 0)
    
    if bet > 0:
        await add_balance(user_id, bet)
        
    try:
        if 'chat_id' in game and 'message_id' in game:
            await message.bot.edit_message_text(
                chat_id=game['chat_id'],
                message_id=game['message_id'],
                text="🛑 <b>Игра отменена пользователем.</b>",
                reply_markup=None,
                parse_mode="HTML"
            )
    except: pass 

    del active_mines[user_id]
    
    fmt_bet = f"{bet:,}".replace(',', ' ')
    await message.reply(
        f"♻️ <b>САПЕР ОТОЗВАН</b>\n"
        f"Твоя зависшая игра отменена. <b>{fmt_bet} ᴜ</b> возвращено на баланс.",
        parse_mode="HTML"
    )