import re
import random
import json
import logging
import os
from aiogram import Router, types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Импорты ядра
from core.database import get_balance, add_balance
from handlers.users.statuses import has_active_status
from handlers.users.quests import process_quest_action

router = Router()

active_mines = {}
mines_start_lock = set()

ADMIN_ID = 1412940726

# Настройки режимов (привязаны к твоим ключам локализации строк)
DIFFICULTIES = {
    'легкий': {'bombs': 4, 'mult': 0.1, 'emoji': '🟢', 'lang_key': 'mn_diff_easy'},
    'средний': {'bombs': 6, 'mult': 0.2, 'emoji': '🟡', 'lang_key': 'mn_diff_medium'},
    'сложный': {'bombs': 11, 'mult': 0.5, 'emoji': '🔴', 'lang_key': 'mn_diff_hard'},
    'эксперт': {'bombs': 16, 'mult': 1.2, 'emoji': '💀', 'lang_key': 'mn_diff_expert'},
    'безумец': {'bombs': 20, 'mult': 3.0, 'emoji': '😈', 'lang_key': 'mn_diff_insane'},
    'ебанутый': {'bombs': 24, 'mult': 24.0, 'emoji': '☢️', 'lang_key': 'mn_diff_madman'}
}

# Английские алиасы для парсинга текстовых команд
DIFF_ALIASES = {
    'easy': 'легкий', 'medium': 'средний', 'hard': 'сложный',
    'expert': 'эксперт', 'insane': 'безумец', 'psycho': 'ебанутый', 'crazy': 'ебанутый'
}

# Глобальный макрос форматирования чисел
fmt = lambda x: f"{int(x):,}".replace(',', ' ')

# ==========================================
# 🛡 ДВИЖОК ЛОКАЛИЗАЦИИ ИЗ СЕССИИ И ПАМЯТИ
# ==========================================
LOCALES = {}
for lang in ["ru", "en"]:
    path = f"locales/{lang}.json"
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                LOCALES[lang] = json.load(f)
        except Exception as e:
            logging.error(f"Ошибка загрузки локали {lang} в минах: {e}")

def get_translator(lang: str):
    target_lang = lang if lang in LOCALES else "ru"
    def translate(key: str, **kwargs) -> str:
        text = LOCALES[target_lang].get(key, LOCALES["ru"].get(key, key))
        if kwargs:
            try: return text.format(**kwargs)
            except: pass
        return text
    return translate

async def resolve_chat_translator(chat_id: int, default__ = None):
    try:
        pool = await get_db()
        async with pool.acquire() as db:
            chat_lang = await db.fetchval("SELECT lang FROM chats WHERE chat_id = $1", chat_id)
            if chat_lang: return get_translator(chat_lang)
    except: pass
    return default__ if default__ else get_translator("ru")


# ==========================================
# 🎮 ГЕНЕРАТОР СЕТКИ ЯЧЕЕК (ЯЗЫК ЧАТА)
# ==========================================
def get_mines_keyboard(user_id, game_over=False, _ = None):
    if not _: _ = get_translator("ru")
    game = active_mines[user_id]
    builder = InlineKeyboardBuilder()

    # Сетка 5х5
    for i in range(25):
        if game['opened'][i] or game_over:
            text = "💣" if game['mines'][i] == 1 else "💎"
            cb_data = "ignore"
        else:
            text = "✖️"
            cb_data = f"mine_step_{user_id}_{i}"
        builder.button(text=text, callback_data=cb_data)

    builder.adjust(5)

    # Кнопки под сеткой
    if not game_over:
        current_multiplier = 1.0 + (game['step'] * game['mult_step'])
        if game['step'] > 0:
            builder.row(types.InlineKeyboardButton(
                text=_("mn_btn_take", mult=current_multiplier), 
                callback_data=f"mine_take_{user_id}"
            ))
        else:
            builder.row(types.InlineKeyboardButton(
                text=_("mn_btn_cancel_0"), 
                callback_data=f"mine_cancel_{user_id}"
            ))

    return builder.as_markup()


# ==========================================
# 🕹 ОБРАБОТКА НАЖАТИЙ (КЛИКИ)
# ==========================================
@router.callback_query(F.data.startswith("mine_"))
async def process_mine_click(callback: types.CallbackQuery, _ = None):
    data = callback.data.split("_")
    action = data[1]
    owner_id = int(data[2])
    
    # Подгружаем язык чата, где открыто поле
    _ = await resolve_chat_translator(callback.message.chat.id, _)

    if callback.from_user.id != owner_id:
        return await callback.answer(_("mn_not_owner"), show_alert=True)

    if owner_id in mines_start_lock:
        return await callback.answer(_("mn_processing"), show_alert=False)
    
    mines_start_lock.add(owner_id)

    try:
        if owner_id not in active_mines:
            return await callback.answer(_("mn_game_over"), show_alert=True)

        game = active_mines[owner_id]
        fmt_bet = fmt(game['bet'])
        current_multiplier = 1.0 + (game['step'] * game['mult_step'])

        # --- ОТМЕНА/СБРОС ---
        if action == "cancel":
            if game['step'] == 0:
                await add_balance(owner_id, game['bet'])
                await callback.message.edit_text(_("mn_action_cancelled", bet=fmt_bet), parse_mode="HTML")
            else:
                await callback.message.edit_text(_("mn_action_lost", bet=fmt_bet), parse_mode="HTML")
            del active_mines[owner_id]
            return

        # --- КЭШАУТ (ЗАБРАТЬ) ---
        elif action == "take":
            win_amount = int(game['bet'] * current_multiplier)
            if current_multiplier >= 2.5: await process_quest_action(owner_id, "mines_win_mult", 1)
            if current_multiplier >= 10.0: await process_quest_action(owner_id, "mines_win_mult", 1)

            await add_balance(owner_id, win_amount, is_income=True)
            fmt_win = fmt(win_amount)
            kb = get_mines_keyboard(owner_id, game_over=True, _=_)
            del active_mines[owner_id]

            await callback.message.edit_text(_("mn_win_msg", diff=game['diff_display'], win=fmt_win, mult=current_multiplier), reply_markup=kb, parse_mode="HTML")
            return

        # --- ХОД ПО ЯЧЕЙКЕ ---
        elif action == "step":
            index = int(data[3])
            if game['opened'][index]:
                return await callback.answer(_("mn_already_opened"))

            game['opened'][index] = True
            if game['mines'][index] == 1:
                # ВЗРЫВ
                kb = get_mines_keyboard(owner_id, game_over=True, _=_)
                lost_bet = game['bet'] 
                del active_mines[owner_id]
                
                from core.database import check_and_apply_cashback
                cashback = await check_and_apply_cashback(owner_id, lost_bet)
                cb_text = f"\n🍀 <b>Rebate:</b> +{fmt(cashback)} ᴜ" if cashback > 0 else ""

                await callback.message.edit_text(_("mn_boom_msg", diff=game['diff_display'], bet=fmt_bet, cb=cb_text), reply_markup=kb, parse_mode="HTML")
            else:
                game['step'] += 1
                await process_quest_action(owner_id, "mines_diamond", 1)
                if game['step'] == 3: await process_quest_action(owner_id, "mines_diamond_streak", 1)
                    
                new_multiplier = 1.0 + (game['step'] * game['mult_step'])
                await callback.message.edit_text(_("mn_diamond_found", diff=game['diff_display'], mult=new_multiplier), reply_markup=get_mines_keyboard(owner_id, _=_), parse_mode="HTML")
    finally:
        if owner_id in mines_start_lock: mines_start_lock.remove(owner_id)


# ==========================================
# 💣 СТАРТ ИНИЦИАЛИЗАЦИИ ИГРЫ (ЯЗЫК ЧАТА)
# ==========================================
@router.message(F.text.regexp(re.compile(r"^\s*(?:мины|mines)\s+(.+)$", re.IGNORECASE)))
async def play_mines(message: types.Message, _ = None):
    chat_id = message.chat.id
    _ = await resolve_chat_translator(chat_id, _)
    user_id = message.from_user.id

    if user_id in mines_start_lock: return 
    if user_id in active_mines: return await message.reply(_("mn_err_active"), parse_mode="HTML")

    match = re.match(r"^\s*(?:мины|mines)\s+(.+)$", message.text, re.IGNORECASE)
    args_text = match.group(1).lower()
    parts = args_text.split()
    
    amount_str = None
    diff_key = 'средний' 
    is_all_in = False
    
    for part in parts:
        if part in DIFFICULTIES: diff_key = part 
        elif part in DIFF_ALIASES: diff_key = DIFF_ALIASES[part] 
        elif re.match(r"^\d+[kкmм]*$", part) and not is_all_in: amount_str = part 
        elif part in ["все", "всё", "all", "allin"]: is_all_in = True

    if not amount_str and not is_all_in: return

    mines_start_lock.add(user_id)

    try:
        current_balance = await get_balance(user_id)
        if is_all_in: amount = current_balance
        else:
            amount_str = amount_str.replace('к', '000').replace('k', '000').replace('м', '000000').replace('m', '000000')
            amount = int(amount_str)

        if amount <= 0: return await message.reply(_("mn_err_exploit"))

        # Лимиты сложности
        DIFFICULTY_LIMITS = {
            "легкий": 100_000_000, "средний": 1_000_000_000, "сложный": 10_000_000_000,
            "эксперт": 50_000_000_000, "безумец": 500_000_000_000, "ебанутый": float('inf')
        }
        max_bet = DIFFICULTY_LIMITS.get(diff_key, 1_000_000_000)
        
        if amount > max_bet and max_bet != float('inf'):
            return await message.reply(_("mn_err_limit", diff=_(DIFFICULTIES[diff_key]['lang_key']), max_bet=fmt(max_bet)), parse_mode="HTML")

        if current_balance < amount: return await message.reply(_("mn_err_no_money"))

        await add_balance(user_id, -amount)

        config = DIFFICULTIES[diff_key]
        bombs_count = config['bombs']
        if await has_active_status(user_id, 3): bombs_count = max(1, bombs_count - 1) 

        mines_positions = [1] * bombs_count + [0] * (25 - bombs_count)
        random.shuffle(mines_positions)

        diff_display_text = f"{config['emoji']} " + _(config['lang_key'])

        active_mines[user_id] = {
            'bet': amount, 'mines': mines_positions, 'opened': [False] * 25, 'step': 0,
            'mult_step': config['mult'], 'diff_name': diff_key, 'diff_display': diff_display_text, 'chat_id': chat_id
        }
        
        await process_quest_action(user_id, "mines_play", 1)
        await process_quest_action(user_id, "any_game_play", 1)

        all_in_text = _("mn_all_in_badge") if is_all_in else ""
        game_msg = await message.reply(_("mn_start_success", diff=diff_display_text, bombs=bombs_count, bet=fmt(amount), all_in=all_in_text), reply_markup=get_mines_keyboard(user_id, _=_), parse_mode="HTML")
        active_mines[user_id]['message_id'] = game_msg.message_id

    except Exception as e:
        logging.error(f"Ошибка при старте мин: {e}")
        if user_id in active_mines:
            await add_balance(user_id, amount)
            del active_mines[user_id]
        await message.reply(_("mn_start_failed"))
    finally:
        if user_id in mines_start_lock: mines_start_lock.remove(user_id)


# ==========================================
# 👑 АДМИН-МЕНЕДЖМЕНТ (ТАКТИЧЕСКИЙ СНОС)
# ==========================================
@router.message((F.text.lower().startswith(("отмена мин", "cancel mines"))) & (F.from_user.id == ADMIN_ID))
async def admin_cancel_mines(message: types.Message, _ = None):
    # Принудительный админский снос берет язык текущего чата
    _ = await resolve_chat_translator(message.chat.id, _)
    target_id, target_name = None, "Operative"

    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        target_name = message.reply_to_message.from_user.first_name
    else:
        parts = message.text.split()
        if len(parts) > 2 and parts[2].isdigit():
            target_id = int(parts[2])
            target_name = f"ID:{target_id}"

    if not target_id: return await message.reply(_("mn_admin_usage"), parse_mode="HTML")
    if target_id not in active_mines: return await message.reply(_("mn_admin_not_found", name=target_name), parse_mode="HTML")

    game = active_mines[target_id]
    bet = game['bet']
    
    if game.get('message_id') and game.get('chat_id'):
        try: await message.bot.edit_message_text(chat_id=game['chat_id'], message_id=game['message_id'], text=_("mn_admin_forced_text"), reply_markup=None, parse_mode="HTML")
        except: pass

    await add_balance(target_id, bet)
    del active_mines[target_id]
    
    await message.reply(_("mn_admin_success", name=target_name, bet=fmt(bet)), parse_mode="HTML")


# ==========================================
# 🚀 ШАТДАУН-СОХРАНЕНИЕ
# ==========================================
async def safe_cashout_all(bot):
    if not active_mines: return
    for user_id, game in list(active_mines.items()):
        try:
            bet, steps, mult_step = game['bet'], game['step'], game['mult_step']
            current_multiplier = 1.0 + (steps * mult_step)
            win_amount = int(bet * current_multiplier)

            await add_balance(user_id, win_amount, is_income=True)
            
            if game.get('chat_id') and game.get('message_id'):
                try:
                    _ = await resolve_chat_translator(game['chat_id'])
                    await bot.edit_message_text(chat_id=game['chat_id'], message_id=game['message_id'], text=_("mn_shutdown_title", win=fmt(win_amount)), reply_markup=None, parse_mode="HTML")
                except: pass
            del active_mines[user_id]
        except Exception as e:
            print(f"Ошибка спасения мин для {user_id}: {e}")


# ==========================================
# 🛑 ЭКСТРЕННАЯ ОТМЕНА ДЛЯ ЮЗЕРА
# ==========================================
@router.message(F.text.lower().in_(["отменить мины", "cancel mines", "abort mines"]))
async def force_cancel_my_mines(message: types.Message, _ = None):
    chat_id = message.chat.id
    _ = await resolve_chat_translator(chat_id, _)
    user_id = message.from_user.id
    
    if user_id not in active_mines:
        return await message.reply(_("mn_user_cancel_none"))
        
    game = active_mines[user_id]
    bet = game.get('bet', 0)
    if bet > 0: await add_balance(user_id, bet)
        
    try:
        if 'chat_id' in game and 'message_id' in game:
            await message.bot.edit_message_text(chat_id=game['chat_id'], message_id=game['message_id'], text=_("mn_user_cancel_board"), reply_markup=None, parse_mode="HTML")
    except: pass

    del active_mines[user_id]
    await message.reply(_("mn_user_cancel_success", bet=fmt(bet)), parse_mode="HTML")


# ==========================================
# 📊 СПРАВОЧНОЕ ИНФО-МЕНЮ РЕЖИМОВ СЛОЖНОСТИ
# ==========================================
@router.message(F.text.lower().strip().in_([
    "мины", "мины режимы", "режимы мин", "мины лимиты", "лимиты мин", "мины сложность", "сложность мин",
    "mines", "mines modes", "mines limits", "mines difficulty"
]))
async def cmd_mines_modes(message: types.Message, _ = None):
    # Подгружаем индивидуальную локаль написавшего юзера (из middleware)
    _ = message.conf.get("_", get_translator("ru")) if hasattr(message, 'conf') else get_translator("ru")
    await message.reply(_("mn_help_text"), parse_mode="HTML")