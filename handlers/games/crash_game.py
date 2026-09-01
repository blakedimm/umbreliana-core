import asyncio
import random
import re
import math
import time
import json
import logging
import os
import html
from aiogram import Router, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest

# Импортируем твои функции из БД
from core.database import get_balance, add_balance, get_db
from handlers.users.quests import process_quest_action

router = Router()
active_flights = {}

# Регулярка расширена под авиация / aviation / crash
AVIATION_PATTERN = re.compile(r"^(?:авиация|aviation|crash)\s+([\dkкmм\s]+)(?:\s+([\d\.]+))?$", re.IGNORECASE)

# --- КОНСТАНТЫ КАЗИНО ---
HOUSE_LIMIT = 0.96          
INSTA_CRASH_PROB = 0.05     
AUTO_CASH_MIN = 1.20        

# ==========================================
# 🛡 ФЕЙЛСЕЙФ СИСТЕМА: РЕЗЕРВНАЯ ЛОКАЛИЗАЦИЯ
# ==========================================
LOCALES = {}
for lang in ["ru", "en"]:
    path = f"locales/{lang}.json"
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                LOCALES[lang] = json.load(f)
        except Exception as e:
            logging.error(f"Ошибка загрузки локали {lang} в авиации: {e}")

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


# --- УТИЛИТЫ ИНТЕРФЕЙСА ---
def fmt(num):
    return f"{int(num):,}".replace(",", " ")

def get_flight_environment(alt, _):
    if alt < 1.5: return _("av_env_1"), "☁️"
    if alt < 3.0: return _("av_env_2"), "🌥"
    if alt < 5.0: return _("av_env_3"), "✨"
    if alt < 10.0: return _("av_env_4"), "🛰"
    return _("av_env_5"), "🌌"

def render_progress_bar(alt):
    filled = min(10, int((alt - 1) * 1.5))
    empty = 10 - filled
    vehicle = "🛸" if alt >= 10 else "🚀" if alt >= 5 else "✈️" if alt >= 2 else "🛫"
    bar = "▰" * filled + vehicle + "▱" * (max(0, empty - 1))
    return f"[{bar}]"

def get_lobby_text(chat_id, _):
    game = active_flights.get(chat_id)
    if not game: return _("av_lobby_err")

    if game['players']:
        lines = []
        for p in game['players'].values():
            auto_txt = _("av_lobby_auto", val=p['auto_cash']) if p.get('auto_cash') else ""
            lines.append(_("av_lobby_row", name=p['name'], bet=fmt(p['bet']), auto=auto_txt))

        players_str = "".join(lines)
        if " ├" in players_str:
            players_str = " └".join(players_str.rsplit(" ├", 1))
    else:
        players_str = _("av_lobby_empty")

    return _("av_lobby_body", bet=fmt(game['bet']), players=players_str)


# ==========================================
# ГЕНЕРАЦИЯ КРАША (МАТЕМАТИЧЕСКОЕ ЯДРО)
# ==========================================
def generate_crash_alt() -> float:
    if random.random() < INSTA_CRASH_PROB:
        return 1.00

    r = random.random()
    crash = HOUSE_LIMIT / (1.0 - min(0.99999, r))

    if crash > 15.0 and random.random() < 0.015:
        crash = random.uniform(20.0, 100.0)

    if crash > 100:
        crash = 100 + math.log(crash - 99) * 15

    return round(max(1.02, crash), 2)


# ==========================================
# 1. КОМАНДА: ОТКРЫТЬ ЛОББИ ПОСАДКИ
# ==========================================
@router.message(F.text.regexp(AVIATION_PATTERN))
async def open_aviation_lobby(message: types.Message, _ = None):
    _ = await resolve_chat_translator(message.chat.id, _)
    match = AVIATION_PATTERN.match(message.text.lower())

    amount_str = match.group(1).replace(" ", "").replace('к', '000').replace('k', '000').replace('м', '000000').replace('m', '000000')
    try: amount = int(amount_str)
    except: return

    if amount <= 0:
        return await message.reply(_("av_err_zero"))

    auto_cash = None
    if match.group(2):
        try:
            auto_cash = float(match.group(2))
            if auto_cash < AUTO_CASH_MIN:
                return await message.reply(_("av_err_auto_min", min=AUTO_CASH_MIN))
        except: pass

    user_id = message.from_user.id
    chat_id = message.chat.id

    if await get_balance(user_id) < amount:
        return await message.reply(_("av_err_no_money", bet=fmt(amount)))

    if chat_id in active_flights:
        return await message.reply(_("av_err_busy"))

    await add_balance(user_id, -amount)

    active_flights[chat_id] = {
        "status": "lobby",
        "creator_id": user_id,
        "bet": amount,
        "players": {
            user_id: {
                "name": html.escape(message.from_user.first_name),
                "bet": amount,
                "cashed_out": False,
                "jump_alt": 1.0,
                "auto_cash": auto_cash
            }
        },
        "crash_alt": 1.0,
        "alt": 1.00
    }

    builder = InlineKeyboardBuilder()
    builder.button(text=_("av_btn_join"), callback_data=f"fly_join_{chat_id}")
    builder.button(text=_("av_btn_leave"), callback_data=f"fly_leave_{chat_id}")
    builder.button(text=_("av_btn_start"), callback_data=f"fly_start_{chat_id}")
    builder.adjust(2, 1)

    await message.answer(get_lobby_text(chat_id, _), reply_markup=builder.as_markup(), parse_mode="HTML")


# ==========================================
# 2. КНОПКА: ВСТУПИТЬ НА БОРТ
# ==========================================
@router.callback_query(F.data.startswith("fly_join_"))
async def join_aviation(callback: types.CallbackQuery, _ = None):
    chat_id = int(callback.data.split("_")[2])
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    user_id = callback.from_user.id
    game = active_flights.get(chat_id)

    if not game or game["status"] != "lobby":
        return await callback.answer(_("av_join_ended"), show_alert=True)
    if user_id in game["players"]:
        return await callback.answer(_("av_join_already"))
    if await get_balance(user_id) < game["bet"]:
        return await callback.answer(_("av_join_no_money"), show_alert=True)

    await add_balance(user_id, -game["bet"])
    game["players"][user_id] = {
        "name": html.escape(callback.from_user.first_name),
        "bet": game["bet"],
        "cashed_out": False,
        "jump_alt": 1.0,
        "auto_cash": None
    }

    try:
        await callback.message.edit_text(
            get_lobby_text(chat_id, _),
            reply_markup=callback.message.reply_markup,
            parse_mode="HTML"
        )
    except: pass
    await callback.answer(_("av_join_success_alert"))


# ==========================================
# 2.5 КОМАНДА: АВТОВЫВОД ДЛЯ ПАССАЖИРОВ
# ==========================================
AUTO_PATTERN = re.compile(r"^(?:авто|auto)\s+([\d\.]+)$", re.IGNORECASE)

@router.message(F.text.regexp(AUTO_PATTERN))
async def set_auto_cashout(message: types.Message, _ = None):
    chat_id = message.chat.id
    _ = await resolve_chat_translator(chat_id, _)
    user_id = message.from_user.id
    game = active_flights.get(chat_id)

    if not game or game["status"] != "lobby": return

    if user_id not in game["players"]:
        return await message.reply(_("av_auto_err_passenger"))

    match = AUTO_PATTERN.match(message.text.lower())
    try:
        auto_val = float(match.group(1))
        if auto_val < AUTO_CASH_MIN:
            return await message.reply(_("av_err_auto_min", min=AUTO_CASH_MIN))
    except:
        return await message.reply(_("av_auto_err_format"), parse_mode="HTML")

    game["players"][user_id]["auto_cash"] = auto_val
    await message.reply(_("av_auto_success", name=message.from_user.first_name, val=auto_val), parse_mode="HTML")


# ==========================================
# 3. КНОПКА: СТАРТ ТУРБИН (ВЗЛЁТ)
# ==========================================
@router.callback_query(F.data.startswith("fly_start_"))
async def start_aviation_flight(callback: types.CallbackQuery, _ = None):
    chat_id = callback.message.chat.id
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    game = active_flights.get(chat_id)

    if not game or game['status'] != 'lobby':
        return await callback.answer(_("av_join_ended"), show_alert=True)

    if callback.from_user.id != game['creator_id']:
        return await callback.answer(_("av_captain_only"), show_alert=True)

    msg = callback.message

    try:
        # --- 3 СЕКУНДЫ ОТСЧЁТА ДО ТЯГИ ---
        for i in range(3, 0, -1):
            try: await msg.edit_text(_("av_countdown", i=i), parse_mode="HTML")
            except: pass
            await asyncio.sleep(1)

        game["crash_alt"] = generate_crash_alt()
        game['status'] = 'flying'
        
        flight_builder = InlineKeyboardBuilder()
        flight_builder.button(text=_("av_btn_jump"), callback_data=f"fly_leave_{chat_id}")

        start_time = time.time()

        if game["crash_alt"] == 1.00:
            game['status'] = 'crashed'
        else:
            game['alt'] = 1.00
            try:
                await msg.edit_text(_("av_flight_started"), reply_markup=flight_builder.as_markup(), parse_mode="HTML")
            except: pass

            last_edit_time = time.time()

            while game['alt'] < game['crash_alt'] and game['status'] == 'flying':
                await asyncio.sleep(0.1)

                from core import bot_state
                if getattr(bot_state, 'IS_SHUTTING_DOWN', False):
                    try: await msg.edit_text(_("av_hard_shutdown"), parse_mode="HTML")
                    except: pass
                    return

                if chat_id not in active_flights or active_flights[chat_id]['status'] != 'flying': break

                # Формула шага высоты
                if game['alt'] < 1.50: step = random.uniform(0.01, 0.02)
                elif game['alt'] < 3.0: step = random.uniform(0.03, 0.05)
                else: step = random.uniform(0.08, 0.15)

                game['alt'] = round(game['alt'] + step, 2)

                # Проверка автовыводов по иксам
                for p_id, p in list(game['players'].items()):
                    if not p['cashed_out'] and p.get('auto_cash') and game['alt'] >= p['auto_cash']:
                        p['cashed_out'] = True
                        p['jump_alt'] = p['auto_cash']
                        win = int(p['bet'] * p['auto_cash'])
                        await add_balance(p_id, win, is_income=True)

                if all(p['cashed_out'] for p in game['players'].values()):
                    game['status'] = 'finished'
                    break

                if game['alt'] >= game['crash_alt']:
                    game['alt'] = game['crash_alt']
                    game['status'] = 'crashed'
                    break

                # Динамическая задержка вывода (HUD Safeguard против RateLimit)
                current_time = time.time()
                current_edit_interval = min(4.0, 2.5 + (game['alt'] / 20))

                if current_time - last_edit_time >= current_edit_interval:
                    env_name, env_emoji = get_flight_environment(game['alt'], _)
                    bar = render_progress_bar(game['alt'])
                    alive_count = sum(1 for p in game['players'].values() if not p['cashed_out'])

                    jumped_players = [p for p in game['players'].values() if p['cashed_out']]
                    jumpers_text = ""
                    if jumped_players:
                        recent = [f"{p['name']} (x{p['jump_alt']:.2f})" for p in jumped_players[-3:]]
                        jumpers_text = _("av_jumped_recent", recent=", ".join(recent))

                    text = _("av_flight_loop_body", emoji=env_emoji, alt=game['alt'], bar=bar, env_name=env_name, alive=alive_count, jumped=jumpers_text)
                    try:
                        await msg.edit_text(text, reply_markup=flight_builder.as_markup(), parse_mode="HTML")
                        last_edit_time = time.time()
                    except TelegramRetryAfter as e:
                        last_edit_time = time.time() + e.retry_after
                    except Exception:
                        last_edit_time = time.time()

        # ==========================================
        # ФИНАЛЬНЫЙ РАПОРТ ОБЛАКА
        # ==========================================
        final_alt = game['crash_alt']
        elapsed = time.time() - start_time
        if elapsed < 2.0: await asyncio.sleep(2.0 - elapsed)

        if game['status'] == 'finished': text_report = _("av_res_finished", alt=final_alt)
        else: text_report = _("av_res_crashed", alt=final_alt)

        from core.database import check_and_apply_cashback

        for p_id, p in game['players'].items():
            await process_quest_action(p_id, "crash_play", 1)
            await process_quest_action(p_id, "any_game_play", 1)

            if p['cashed_out']:
                if p['jump_alt'] >= 2.0: await process_quest_action(p_id, "crash_cashout", 2.0)
                if p['jump_alt'] >= 5.0: await process_quest_action(p_id, "crash_cashout_count", 1)
                text_report += _("av_res_row_win", name=p['name'], win=fmt(p['bet'] * p['jump_alt']), alt=p['jump_alt'])
            else:
                lost_bet = p['bet']
                cashback = await check_and_apply_cashback(p_id, lost_bet)
                if cashback > 0:
                    text_report += _("av_res_row_loss_cb", name=p['name'], lost=fmt(lost_bet), cb=fmt(cashback))
                else:
                    text_report += _("av_res_row_loss", name=p['name'], lost=fmt(lost_bet))

        text_report += "════════════════════"

        try: await msg.edit_text(text_report, parse_mode="HTML")
        except Exception:
            try: await callback.message.answer(text_report, parse_mode="HTML")
            except: pass

    except Exception as e: logging.error(f"Ошибка в полёте: {e}")
    finally:
        if chat_id in active_flights: del active_flights[chat_id]


# ==========================================
# 4. КНОПКА/КОМАНДА: ЭВАКУАЦИЯ С БОРТА
# ==========================================
@router.callback_query(F.data.startswith("fly_leave_"))
async def leave_aviation(callback: types.CallbackQuery, _ = None):
    chat_id = int(callback.data.split("_")[2])
    _ = await resolve_chat_translator(callback.message.chat.id, _)
    game = active_flights.get(chat_id)

    if not game or callback.from_user.id not in game['players']:
        return await callback.answer(_("av_not_in_game"), show_alert=True)

    player = game['players'][callback.from_user.id]

    if game['status'] == 'lobby':
        if callback.from_user.id == game['creator_id']:
            for p_id in list(game["players"].keys()):
                await add_balance(p_id, game["bet"])
            await callback.message.edit_text(_("av_cancel_captain"), parse_mode="HTML")
            if chat_id in active_flights: del active_flights[chat_id]
            return

        await add_balance(callback.from_user.id, game['bet'])
        del game['players'][callback.from_user.id]
        try:
            await callback.message.edit_text(get_lobby_text(chat_id, _), reply_markup=callback.message.reply_markup, parse_mode="HTML")
        except: pass
        await callback.answer(_("av_leave_lobby_alert"))

    elif game['status'] == 'flying':
        if player['cashed_out']: return await callback.answer(_("av_already_jumped"))

        jump_alt = game['alt']
        win = int(player['bet'] * jump_alt)
        await add_balance(callback.from_user.id, win, is_income=True)

        player['cashed_out'] = True
        player['jump_alt'] = jump_alt

        await callback.answer(_("av_jump_success_alert", alt=jump_alt, win=fmt(win)), show_alert=True)