import asyncio
import random
import re
from aiogram import Router, F, types
from aiogram.types import FSInputFile

from core.database import get_balance, add_balance, add_wheel_history, get_wheel_history
from handlers.users.quests import process_quest_action

router = Router()

# Память для active-вращений
active_wheels = {}

# 🔥 Обновленная регулярка: поддерживает и "колесо", и "wheel" + k/m суффиксы на обоих языках
WHEEL_PATTERN = re.compile(r"^(?:колесо|wheel)\s+(\d+[kкmм]*)\s+(?:x|х)?\s*(2|5|10|50)\s*(?:x|х)?\s*$", re.IGNORECASE)

# ==========================================
# 🎨 БЕЗОПАСНЫЙ СЛОВАРЬ ДЕФОЛТОВ (ДЛЯ ДРУГИХ ИГРОКОВ)
# ==========================================
FALLBACK_STRINGS = {
    "wh_lobby_closed_err": "🚨 <b>ОШИБКА: ЛОББИ ЗАКРЫТО</b>",
    "wh_history_empty": "<code>[ ДАННЫЕ ЗАСЕКРЕЧЕНЫ ]</code>",
    "wh_zero": "ЗЕРО",
    "wh_lobby_row": "{num} <b>{name}</b> — <code>{bet}</code> ᴜ на <b>x{target}</b>\n",
    "wh_lobby_body": "🌑 <b>ТЕНЕВОЕ КОЛЕСО СИНДИКАТА</b>\n━━━━━━━━━━━━━━━━━━━━\n📜 <b>ИСТОРИЯ:</b> [ {history} ]\n━━━━━━━━━━━━━━━━━━━━\n👑 Хост стола: <b>{creator_name}</b>\n💎 Пул раунда: <code>{total_bank}</code> ᴜ\n\n👥 <b>СТАВКИ АГЕНТОВ:</b>\n{player_list}━━━━━━━━━━━━━━━━━━━━\n🕹 <b>ВСТУПИТЬ:</b> <code>колесо [сумма] [икс]</code>\n🚀 <b>СТАРТ:</b> написать <b>гоу</b>",
    "wh_err_no_money": "❌ Недостаточно UMBREL для ставки.",
    "wh_err_already_in": "⚠️ Ты уже в игре, жди запуска!",
    "wh_err_host_only": "👨‍✈️ Только хост стола может дать команду <b>гоу</b>!",
    "wh_anim_start": "🌑 <b>Механизм запущен. Жребий брошен...</b>",
    "wh_anim_text_1": "🌑 Механизм запущен...",
    "wh_anim_text_2": "🌘 Сектора мелькают...",
    "wh_anim_text_3": "🌗 Колесо замедляется...",
    "wh_hard_shutdown": "🛠 <b>ТЕХНИЧЕСКИЙ ПЕРЕЗАПУСК</b>\nИгра экстренно прервана Архитектором.\n💰 <i>Все фишки уже возвращены на баланс!</i>",
    "wh_res_header": "🏁 <b>СЕКТОР: {res_text} {res_emoji}</b>\n━━━━━━━━━━━━━━━━━━━━\n",
    "wh_res_row_win": "✅ <b>{name}</b> забрал <code>{win}</code> ᴜ\n",
    "wh_res_row_loss": "❌ <b>{name}</b> сжег <code>{bet}</code> ᴜ\n",
    "wh_res_winners_title": "🤑 <b>БАНК СОРВАН:</b>\n",
    "wh_res_losers_title": "💀 <b>ЛИКВИДИРОВАНЫ:</b>\n",
    "wh_res_all_loss": "⚫️ Теневой пул забрал всё...",
    "wh_error_hint": "🌑 <b>ТЕНЕВОЕ КОЛЕСО</b>\nФормат: <code>колесо [ставка] [икс]</code>\nДоступные иксы: 2, 5, 10, 50"
}

def get_str(key: str, _=None, **kwargs) -> str:
    """Умный распределитель локализации с защитой от пустой сессии"""
    if _:
        return _(key, **kwargs)
    text = FALLBACK_STRINGS.get(key, key)
    if kwargs:
        try: return text.format(**kwargs)
        except: pass
    return text

# ==========================================
# 🎨 ДИЗАЙН И ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================

async def get_history_display(_=None):
    """Стильная дорожка последних игр ТЕКСТОМ из базы данных"""
    recent = await get_wheel_history(5)
    if not recent:
        return get_str("wh_history_empty", _)
    
    items = []
    for res in recent:
        if res > 0: 
            items.append(f"x{res}") 
        else: 
            items.append("⚫️")
    
    return " | ".join(items)

async def build_lobby_text(chat_id, _=None):
    """Божественная нуарная верстка лобби Синдиката"""
    game = active_wheels.get(chat_id)
    if not game: return get_str("wh_lobby_closed_err", _)
    
    total_bank = sum(p['bet'] for p in game['players'].values())
    history = await get_history_display(_)
    
    player_list = ""
    sorted_players = sorted(game['players'].items(), key=lambda x: x[1]['bet'], reverse=True)
    
    for i, (p_id, p_data) in enumerate(sorted_players, 1):
        fmt_bet = f"{p_data['bet']:,}".replace(',', ' ')
        num = ["❶", "❷", "❸", "❹", "❺"][i-1] if i <= 5 else f"{i}."
        player_list += get_str("wh_lobby_row", _, num=num, name=p_data['name'], bet=fmt_bet, target=p_data['target'])

    return get_str("wh_lobby_body", _, history=history, creator_name=game['creator_name'], total_bank=f"{total_bank:,}".replace(',', ' '), player_list=player_list)

async def update_lobby_message(chat_id, bot, _=None):
    """Обновляет старое сообщение лобби новым списком игроков"""
    game = active_wheels.get(chat_id)
    if not game or not game['lobby_msg_id']: return
    try:
        new_text = await build_lobby_text(chat_id, _)
        await bot.edit_message_text(chat_id=chat_id, message_id=game['lobby_msg_id'], text=new_text, parse_mode="HTML")
    except Exception:
        pass

# ==========================================
# 1. ОБРАБОТКА КОМАНДЫ "КОЛЕСО / WHEEL"
# ==========================================
@router.message(F.text.regexp(WHEEL_PATTERN))
async def start_crazy_wheel(message: types.Message, _=None):
    match = WHEEL_PATTERN.match(message.text.lower())
    amount_str = match.group(1).replace('к', '000').replace('k', '000').replace('м', '000000').replace('m', '000000')
    bet_amount = int(amount_str)
    target_mult = int(match.group(2))

    user_id = message.from_user.id
    chat_id = message.chat.id

    if await get_balance(user_id) < bet_amount:
        return await message.reply(get_str("wh_err_no_money", _))

    if chat_id in active_wheels:
        game = active_wheels[chat_id]
        if user_id in game['players']:
             return await message.reply(get_str("wh_err_already_in", _))
        
        await add_balance(user_id, -bet_amount)
        game['players'][user_id] = {'name': message.from_user.first_name, 'bet': bet_amount, 'target': target_mult}
        
        await update_lobby_message(chat_id, message.bot, _)
        try: await message.delete()
        except: pass
        return

    await add_balance(user_id, -bet_amount)
    active_wheels[chat_id] = {
        'creator_id': user_id,
        'creator_name': message.from_user.first_name,
        'players': {user_id: {'name': message.from_user.first_name, 'bet': bet_amount, 'target': target_mult}},
        'status': 'lobby',
        'lobby_msg_id': None
    }

    lobby_text = await build_lobby_text(chat_id, _)
    sent_msg = await message.answer(lobby_text, parse_mode="HTML")
    active_wheels[chat_id]['lobby_msg_id'] = sent_msg.message_id

# ==========================================
# 2. КОМАНДА ЗАПУСКА "ГОУ / GO"
# ==========================================
@router.message(F.text.lower().in_(["гоу", "go"]))
async def manual_start_wheel(message: types.Message, _=None):
    chat_id = message.chat.id
    game = active_wheels.get(chat_id)

    if not game or game['status'] != 'lobby': return 

    if message.from_user.id != game['creator_id']:
        await message.reply(get_str("wh_err_host_only", _))
        return

    game['status'] = 'spinning'
    await spin_the_wheel(chat_id, message.bot, _)

# ==========================================
# 3. ЛОГИКА ВРАЩЕНИЯ И ПОДСЧЕТА
# ==========================================
async def spin_the_wheel(chat_id, bot, _=None):
    game = active_wheels.get(chat_id)
    if not game: return

    try: await bot.delete_message(chat_id, game['lobby_msg_id'])
    except: pass

    animation_file = FSInputFile("wheel.gif") 
    try:
        gif_msg = await bot.send_animation(
            chat_id=chat_id,
            animation=animation_file,
            caption=get_str("wh_anim_start", _),
            parse_mode="HTML"
        )
        await asyncio.sleep(4) 
        await gif_msg.delete()
    except Exception:
        msg = await bot.send_message(chat_id, get_str("wh_anim_text_1", _))
        await asyncio.sleep(1)
        await msg.edit_text(get_str("wh_anim_text_2", _))
        await asyncio.sleep(1)
        await msg.edit_text(get_str("wh_anim_text_3", _))
        await asyncio.sleep(1.5)
        await msg.delete()
        
    from core import bot_state
    if bot_state.IS_SHUTTING_DOWN:
        try:
            await bot.send_message(chat_id, get_str("wh_hard_shutdown", _), parse_mode="HTML")
        except: pass
        return 

    del active_wheels[chat_id]

    r = random.random() * 100
    if r < 1.5: res = 50
    elif r < 9.5: res = 10
    elif r < 27.5: res = 5
    elif r < 71.5: res = 2
    else: res = 0 

    await add_wheel_history(res)

    res_text = f"x{res}" if res > 0 else get_str("wh_zero", _)
    res_emoji = {50: "🟣", 10: "🔵", 5: "🟢", 2: "⚪️", 0: "⚫️"}[res]

    final_text = get_str("wh_res_header", _, res_text=res_text, res_emoji=res_emoji)
    winners, losers = [], []

    for p_id, p_data in game['players'].items():
        await process_quest_action(p_id, "any_game_play", 1)
        await process_quest_action(p_id, "all_games_100", 1)

        if p_data['target'] == res:
            win_sum = p_data['bet'] * res
            await add_balance(p_id, win_sum, is_income=True)
            winners.append(get_str("wh_res_row_win", _, name=p_data['name'], win=f"{win_sum:,}".replace(',', ' ')))
        else:
            losers.append(get_str("wh_res_row_loss", _, name=p_data['name'], bet=f"{p_data['bet']:,}".replace(',', ' ')))

    if winners:
        final_text += get_str("wh_res_winners_title", _) + "".join(winners) + "\n"
    if losers:
        final_text += get_str("wh_res_losers_title", _) + "".join(losers)
    if not winners and not losers:
        final_text += get_str("wh_res_all_loss", _)

    await bot.send_message(chat_id, final_text, parse_mode="HTML")

# Подсказка при ошибке
@router.message(F.text.lower().startswith(("колесо", "wheel")))
async def wheel_error_hint(message: types.Message, _=None):
    if message.chat.id in active_wheels: return
    await message.reply(get_str("wh_error_hint", _), parse_mode="HTML")