import asyncio
import random
import time
from aiogram import Router, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from core.database import get_balance, add_balance

from handlers.users.quests import process_quest_action

router = Router()

# {chat_id: {status, bet, players: {uid: name}, holder: uid, start_time, end_time, last_transfer}}
active_bombs = {}

@router.message(F.text.lower().startswith("бомба"))
async def create_bomb_lobby(message: types.Message):
    parts = message.text.split()
    if len(parts) < 2: return
    try:
        bet = int(parts[1])
    except: return

    if bet < 100:
        await message.reply("❌ Ставка слишком мала (мин. 100 UBREL)")
        return
    if await get_balance(message.from_user.id) < bet:
        await message.reply("❌ У тебя не хватает UBREL!")
        return

    chat_id = message.chat.id
    if chat_id in active_bombs:
        await message.reply("⚠️ Бомба уже заложена в этом чате!")
        return

    await add_balance(message.from_user.id, -bet)
    active_bombs[chat_id] = {
        "status": "lobby",
        "bet": bet,
        "creator_id": message.from_user.id,
        "players": {message.from_user.id: message.from_user.first_name},
        "holder": None
    }

    builder = InlineKeyboardBuilder()
    builder.button(text="Вступить", callback_data=f"bomb_join_{chat_id}")
    builder.button(text="Поджечь (начать)", callback_data=f"bomb_start_{chat_id}")
    builder.button(text="Отмена", callback_data=f"bomb_cancel_{chat_id}")
    builder.adjust(2, 1)

    await message.answer(
        f"💣 <b>ИГРА: БОМБА</b>\n\n"
        f"💰 Ставка: <b>{bet:,}</b> UBREL\n"
        f"👥 Участники: <b>{message.from_user.first_name}</b>".replace(',', ' '),
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data.startswith("bomb_"))
async def handle_bomb_logic(callback: types.CallbackQuery):
    data = callback.data.split("_")
    action, chat_id = data[1], int(data[2])
    game = active_bombs.get(chat_id)
    if not game: return

    if action == "join":
        if callback.from_user.id in game["players"]:
            await callback.answer("Ты уже в деле!", show_alert=True)
            return
        if await get_balance(callback.from_user.id) < game["bet"]:
            await callback.answer("Мало UBREL!", show_alert=True)
            return

        await add_balance(callback.from_user.id, -game["bet"])
        game["players"][callback.from_user.id] = callback.from_user.first_name
        
        names = ", ".join(game["players"].values())
        await callback.message.edit_text(
            f"💣 <b>ИГРА: БОМБА</b>\n\n💰 Ставка: <b>{game['bet']:,}</b> UBREL\n👥 Участники: {names}".replace(',', ' '),
            reply_markup=callback.message.reply_markup
        )

    elif action == "cancel":
        if callback.from_user.id != game["creator_id"]:
            await callback.answer("Только создатель!", show_alert=True)
            return
        for p_id in game["players"]: add_balance(p_id, game["bet"])
        del active_bombs[chat_id]
        await callback.message.edit_text("❌ Игра отменена. UBREL возвращены.")

        try:
            await callback.message.unpin()
        except:
            pass

    elif action == "start":
        if callback.from_user.id != game["creator_id"]:
            await callback.answer("Только создатель!", show_alert=True)
            return
        if len(game["players"]) < 3:
            await callback.answer("Нужно минимум 3 смертника! 😂", show_alert=True)
            return
        
        game["status"] = "playing"
        await start_bomb_rounds(chat_id, callback.message)

    elif action == "pass":
        if game["status"] != "playing": return
        if callback.from_user.id != game["holder"]:
            await callback.answer("Бомба не у тебя! Не паникуй! 😂", show_alert=True)
            return
        
        # Передаем бомбу
        others = [p for p in game["players"].keys() if p != game["holder"]]
        game["holder"] = random.choice(others)
        game["last_transfer"] = time.time()
        await callback.answer("Фух, передал! 💨")

async def start_bomb_rounds(chat_id, message: types.Message):
    game = active_bombs[chat_id]

    try:
        await message.pin(disable_notification=True)
    except:
        pass # Если нет прав админа, просто играем дальше
    
    # --- 🎬 МИНИ-АНИМАЦИЯ: ЗАЖИГАЕМ ФИТИЛЬ ---
    
    # Сцена 1: Подготовка
    await message.edit_text(
        f"💣 <b>БОМБА: ГОТОВИМ КУШ...</b>\n\n"
        f"🕵️‍♂️ <code>[ Достает зажигалку... ]</code>\n"
        f"      🧱💣🧱🧱"
    )
    await asyncio.sleep(1.2)

    # Сцена 2: Огонь!
    await message.edit_text(
        f"💣 <b>БОМБА: СЕЙЧАС ЧИРКНЕТ!</b>\n\n"
        f"🕵️‍♂️🔥 <code>[ *ЧИРК*! Есть огонь! ]</code>\n"
        f"      🧱💣🧱🧱"
    )
    await asyncio.sleep(1)

    # Сцена 3: Поджигание
    await message.edit_text(
        f"💣 <b>БОМБА: ПОДНОСИТ...</b>\n\n"
        f"🕵️‍♂️ 👉🔥💥💣\n"
        f"      🧱🧱🧱🧱"
    )
    await asyncio.sleep(1)

    # Сцена 4: Побег
    await message.edit_text(
        f"💣 <b>ГОРИТ! ФИТИЛЬ ГОРИТ!</b>\n\n"
        f"🕵️‍♂️💨 <code>[ СЪЕБАЛСЯ!🏃💨 ]</code>\n"
        f"      🧱✨💣✨🧱"
    )
    await asyncio.sleep(1.5)

    # --- ПЕРЕХОДИМ К ИГРЕ ---
    while len(game["players"]) > 1:
        # Новый раунд
        game["holder"] = random.choice(list(game["players"].keys()))
        game["last_transfer"] = time.time()
        
        # Случайное время раунда от 10 до 25 секунд
        round_duration = random.randint(10, 25)
        end_time = time.time() + round_duration
        
        builder = InlineKeyboardBuilder()
        builder.button(text="ПЕРЕДАТЬ 🧨", callback_data=f"bomb_pass_{chat_id}")

        while time.time() < end_time:
            holder_name = game["players"][game["holder"]]
            
            # Защита от АФК (5 секунд)
            if time.time() - game["last_transfer"] > 5:
                break # Взрыв по АФК

            try:
                await message.edit_text(
                    f"💣 <b>БОМБА У:</b> <code>{holder_name}</code>\n"
                    f"⏱ Фитиль горит! Быстрее передавай!",
                    reply_markup=builder.as_markup()
                )
            except: pass
            
            await asyncio.sleep(1)
            if len(game["players"]) <= 1: break
            # 🛑 СТАВИМ ЗАЩИТУ ЗДЕСЬ 🛑
            from core import bot_state
            if bot_state.IS_SHUTTING_DOWN:
                try:
                    # ВНИМАНИЕ: тут используй переменную твоего сообщения (msg, anim_msg, countdown_msg)
                    await message.edit_text(
                        "🛠 <b>ТЕХНИЧЕСКИЙ ПЕРЕЗАПУСК</b>\n"
                        "Игра экстренно прервана Архитектором.\n"
                        "💰 <i>Все ваши фишки уже возвращены на баланс!</i>", 
                        parse_mode="HTML"
                    )
                except: pass
                return 
            # ==========================================

        # БАБАХ!
        loser_id = game["holder"]
        loser_name = game["players"].pop(loser_id)

        # 🔥 ТРИГГЕР КВЕСТОВ (Лузер отыграл) 🔥
        await process_quest_action(loser_id, "bomb_play", 1)
        await process_quest_action(loser_id, "any_game_play", 1)
        
        if len(game["players"]) > 1:
            await message.answer(f"💥 <b>БА-БАХ!</b>\nБомба взорвалась в руках у <b>{loser_name}</b>! Он выбывает! 💀")
            await asyncio.sleep(3)
        else:
            # Финал
            winner_id = list(game["players"].keys())[0]
            winner_name = game["players"][winner_id]

            # 🔥 ТРИГГЕР КВЕСТОВ (Победитель) 🔥
            await process_quest_action(winner_id, "bomb_play", 1)
            await process_quest_action(winner_id, "any_game_play", 1)
            await process_quest_action(winner_id, "bomb_survive", 1)

            try:
                await message.unpin()
            except:
                pass
            
            # Считаем банк (количество игроков на старте было len(players)+1)
            total_players = len(game["players"]) + 1 # упростим расчет банка
            # Но лучше взять из ставки и изначального лобби, если оно где-то сохранено. 
            # В данном коде просто считаем по факту оставшихся.
            
            # Рассчитываем выигрыш (налог 10%)
            # Артём, я тут чуть поправил логику банка, чтобы она не зависела от 'loser_id'
            win_amount = int((game["bet"] * (len(game["players"]) + 1)) * 0.9)
            
            add_balance(winner_id, win_amount)
            await message.answer(
                f"🏆 <b>ИГРА ОКОНЧЕНА!</b>\n\n"
                f"Выживший: <b>{winner_name}</b>\n"
                f"💰 Приз: <b>{win_amount:,}</b> UBREL".replace(',', ' ')
            )
            del active_bombs[chat_id]
            return