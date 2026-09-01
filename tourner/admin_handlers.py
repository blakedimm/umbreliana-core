import re
import time
import os
import sys
import psutil
import logging
import asyncio
import json
import html
import subprocess
from datetime import datetime

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram import Router, types, F, Bot
from aiogram.types import FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

# 🔥 ПЛОСКИЕ ИМПОРТЫ
import middlewares
from database import (
    get_db, get_balance, add_balance, get_user_data,
    update_user, resolve_user_id, get_farm, update_farm, DB_URL
)
from farm_game import (
    calculate_farm_state, get_tax_rate, GPUS, COOLING,
    sync_farm_passive, perform_collection
)

router = Router()
ADMIN_ID = int(os.getenv("ADMIN_ID", 1412940726))
logger = logging.getLogger("TourneyAdmin")

class AdminConfirm(StatesGroup):
    waiting_for_stop_confirm = State()

class AdminMenuStates(StatesGroup):
    waiting_for_give = State()
    waiting_for_take = State()
    waiting_for_check = State()
    waiting_for_ban = State()
    waiting_for_unban = State()
    
    waiting_for_check_farm = State()
    waiting_for_give_card = State()
    waiting_for_take_card = State()
    waiting_for_bulk_cards = State()
    waiting_for_repair = State()
    waiting_for_break = State()
    waiting_for_farm_time = State()
    
    waiting_for_reset_user = State()

def fmt(num):
    return f"{int(num):,}".replace(",", " ")

async def rescue_all_assets(bot: Bot):
    print("\n⚠️ ВНИМАНИЕ: Запуск ТОТАЛЬНОГО АТОМАРНОГО протокола спасения турнирных активов!")
    pool = await get_db()
    refunds = []

    try:
        from roulette_game import current_bets, spinning_bets
        for cid in list(current_bets.keys()): 
            for b in current_bets.pop(cid, []): refunds.append((b['user_id'], b['amount'], "Рулетке"))
        for cid in list(spinning_bets.keys()): 
            for b in spinning_bets.pop(cid, []): refunds.append((b['user_id'], b['amount'], "Рулетке"))
    except: pass

    try:
        from mines_game import active_mines
        for uid in list(active_mines.keys()):
            data = active_mines.pop(uid)
            refunds.append((uid, data['bet'], "Минах"))
    except: pass

    db_success = False
    if refunds:
        try:
            async with pool.acquire() as db:
                async with db.transaction():
                    for uid, amount, game_name in refunds:
                        await db.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", amount, uid)
            db_success = True
        except Exception as e:
            print(f"❌ КРИТИЧЕСКАЯ ОШИБКА БД: {e}")
            return 

    if db_success or not refunds:
        user_refunds = {}
        for uid, amount, game_name in refunds:
            if uid not in user_refunds:
                user_refunds[uid] = {'amount': 0, 'games': set()}
            user_refunds[uid]['amount'] += amount
            user_refunds[uid]['games'].add(game_name)

        for uid, data in user_refunds.items():
            games_str = ", ".join(data['games'])
            try: 
                await bot.send_message(
                    uid, 
                    f"⚙️ <b>РЕСТАРТ АРЕНЫ</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Активные сессии в: <b>{games_str}</b> были прерваны.\n"
                    f"💰 На баланс возвращено: <b>{fmt(data['amount'])} ᴜ</b>",
                    parse_mode="HTML"
                )
            except: pass

    print(f"👋 Спасенных активов: {len(refunds)}.")

# ==========================================
# 👑 УЛЬТИМАТИВНАЯ ИНТЕРАКТИВНАЯ АДМИН-ПАНЕЛЬ (UI)
# ==========================================
def get_admin_main_text():
    process = psutil.Process(os.getpid())
    ram_mb = process.memory_info().rss / (1024 * 1024)
    cpu = psutil.cpu_percent()
    return (
        f"⚔️ <b>ТЕРМИНАЛ АРХИТЕКТОРА (АРЕНА)</b>\n"
        f"🖥 Хост: <b>RAM {ram_mb:.1f}MB</b> | <b>CPU {cpu}%</b>\n"
        f"════════════════════\n"
        f"<i>Контроль над турниром активирован.</i>"
    )

def get_admin_kb(section="main"):
    builder = InlineKeyboardBuilder()
    
    if section == "main":
        builder.row(
            types.InlineKeyboardButton(text="💰 Экономика", callback_data="adm_nav_eco"),
            types.InlineKeyboardButton(text="🏭 Фермы (GPU)", callback_data="adm_nav_farm")
        )
        builder.row(types.InlineKeyboardButton(text="⚙️ Система", callback_data="adm_nav_sys"))
        builder.row(types.InlineKeyboardButton(text="❌ Закрыть панель", callback_data="adm_nav_close"))

    elif section == "eco":
        builder.row(
            types.InlineKeyboardButton(text="➕ Выдать ᴜ", callback_data="adm_act_give"),
            types.InlineKeyboardButton(text="➖ Забрать ᴜ", callback_data="adm_act_take")
        )
        builder.row(
            types.InlineKeyboardButton(text="🔎 Досье (Чек)", callback_data="adm_act_check"),
            types.InlineKeyboardButton(text="🧽 Сброс игрока", callback_data="adm_act_reset_user")
        )
        builder.row(types.InlineKeyboardButton(text="📊 Глобальная стата", callback_data="adm_act_global_stats"))
        builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="adm_nav_main"))

    elif section == "farm":
        builder.row(
            types.InlineKeyboardButton(text="🔎 Чек ферму", callback_data="adm_act_check_farm"),
            types.InlineKeyboardButton(text="⏳ Сдвиг времени", callback_data="adm_act_farm_time")
        )
        builder.row(
            types.InlineKeyboardButton(text="➕ Карта", callback_data="adm_act_give_card"),
            types.InlineKeyboardButton(text="➖ Карта", callback_data="adm_act_take_card")
        )
        builder.row(
            types.InlineKeyboardButton(text="📦 Оптом", callback_data="adm_act_bulk_cards"),
            types.InlineKeyboardButton(text="📋 Шпаргалка GPU", callback_data="adm_act_gpu_help")
        )
        builder.row(
            types.InlineKeyboardButton(text="🔧 Чинить", callback_data="adm_act_repair"),
            types.InlineKeyboardButton(text="🔨 Сломать", callback_data="adm_act_break")
        )
        builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="adm_nav_main"))

    elif section == "sys":
        builder.row(
            types.InlineKeyboardButton(text="🚫 Выдать БАН", callback_data="adm_act_ban"),
            types.InlineKeyboardButton(text="🔓 Разбан", callback_data="adm_act_unban")
        )
        builder.row(
            types.InlineKeyboardButton(text="☀️ Разбан всех", callback_data="adm_act_unban_all"),
            types.InlineKeyboardButton(text="🧹 Чистка инвентаря", callback_data="adm_act_clean_inv")
        )
        builder.row(
            types.InlineKeyboardButton(text="📦 Бэкап БД", callback_data="adm_act_backup"),
            types.InlineKeyboardButton(text="🛠 Фикс БД", callback_data="adm_act_fix_db")
        )
        builder.row(types.InlineKeyboardButton(text="🔄 ПЕРЕЗАГРУЗКА", callback_data="adm_act_restart"))
        builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="adm_nav_main"))

    return builder.as_markup()

# --- ВЫЗОВ ПАНЕЛИ ---
@router.message((F.text.lower() == "админ панель") & (F.from_user.id == ADMIN_ID))
async def main_admin_panel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.reply(get_admin_main_text(), reply_markup=get_admin_kb("main"), parse_mode="HTML")

# --- НАВИГАЦИЯ ПО ПАНЕЛИ ---
@router.callback_query(F.data.startswith("adm_nav_") & (F.from_user.id == ADMIN_ID))
async def admin_panel_navigation(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    section = callback.data.replace("adm_nav_", "")
    if section == "close": return await callback.message.delete()
        
    titles = {
        "eco": "💰 <b>УПРАВЛЕНИЕ: ЭКОНОМИКА</b>",
        "farm": "🏭 <b>УПРАВЛЕНИЕ: ФЕРМЫ</b>",
        "sys": "⚙️ <b>УПРАВЛЕНИЕ: СИСТЕМА</b>",
        "main": get_admin_main_text()
    }
    try: await callback.message.edit_text(titles.get(section), reply_markup=get_admin_kb(section), parse_mode="HTML")
    except: pass
    await callback.answer()

# --- ОБРАБОТКА ДЕЙСТВИЙ ---
@router.callback_query(F.data.startswith("adm_act_") & (F.from_user.id == ADMIN_ID))
async def admin_panel_actions(callback: types.CallbackQuery, state: FSMContext):
    action = callback.data.replace("adm_act_", "")
    msg = callback.message
    
    # 1. ПРЯМЫЕ КОМАНДЫ
    if action == "global_stats": await admin_global_stats(msg, callback.bot)
    elif action == "unban_all": await admin_mass_unban(msg)
    elif action == "gpu_help": await admin_farm_help(msg)
    elif action == "backup": await admin_backup(msg)
    elif action == "fix_db": await fix_database_schema(msg)
    elif action == "clean_inv": await clean_ghosts_global(msg)
    elif action == "restart": await cmd_restart_bot(msg)
    
    # 2. КОМАНДЫ С ВВОДОМ ДАННЫХ (Экономика)
    elif action == "give":
        await msg.answer("➕ <b>Выдача UMBREL</b>\nФормат: <code>ID Сумма</code>\n<i>(отмена)</i>", parse_mode="HTML")
        await state.set_state(AdminMenuStates.waiting_for_give)
    elif action == "take":
        await msg.answer("➖ <b>Изъятие UMBREL</b>\nФормат: <code>ID Сумма</code>\n<i>(отмена)</i>", parse_mode="HTML")
        await state.set_state(AdminMenuStates.waiting_for_take)
    elif action == "check":
        await msg.answer("🔎 <b>Поиск досье</b>\nВведите <code>ID</code> или <code>@username</code>\n<i>(отмена)</i>", parse_mode="HTML")
        await state.set_state(AdminMenuStates.waiting_for_check)
    elif action == "reset_user":
        await msg.answer("🧽 <b>Полное обнуление юзера</b>\nВведите <code>ID</code>\n<i>(отмена)</i>", parse_mode="HTML")
        await state.set_state(AdminMenuStates.waiting_for_reset_user)

    # 3. КОМАНДЫ С ВВОДОМ ДАННЫХ (Система / Бан)
    elif action == "ban":
        await msg.answer("🚫 <b>Выдача бана</b>\nФормат: <code>ID Дни Причина</code>\n<i>(отмена)</i>", parse_mode="HTML")
        await state.set_state(AdminMenuStates.waiting_for_ban)
    elif action == "unban":
        await msg.answer("🔓 <b>Разбан</b>\nВведите <code>ID</code>\n<i>(отмена)</i>", parse_mode="HTML")
        await state.set_state(AdminMenuStates.waiting_for_unban)

    # 4. КОМАНДЫ С ВВОДОМ ДАННЫХ (Фермы)
    elif action == "check_farm":
        await msg.answer("🏭 <b>Поиск фермы</b>\nВведите <code>ID</code> или <code>@username</code>\n<i>(отмена)</i>", parse_mode="HTML")
        await state.set_state(AdminMenuStates.waiting_for_check_farm)
    elif action == "give_card":
        await msg.answer("➕ <b>Выдать карту</b>\nФормат: <code>ID Название Количество</code>\n<i>(отмена)</i>", parse_mode="HTML")
        await state.set_state(AdminMenuStates.waiting_for_give_card)
    elif action == "take_card":
        await msg.answer("➖ <b>Забрать карту</b>\nФормат: <code>ID Название Количество</code>\n<i>(отмена)</i>", parse_mode="HTML")
        await state.set_state(AdminMenuStates.waiting_for_take_card)
    elif action == "bulk_cards":
        await msg.answer("📦 <b>Оптом карты</b>\nФормат: <code>ID Карта Кол, Карта Кол...</code>\n<i>(отмена)</i>", parse_mode="HTML")
        await state.set_state(AdminMenuStates.waiting_for_bulk_cards)
    elif action == "repair":
        await msg.answer("🔧 <b>Чинить карты</b>\nФормат: <code>ID Название Кол</code> (или просто ID для фулл ремонта)\n<i>(отмена)</i>", parse_mode="HTML")
        await state.set_state(AdminMenuStates.waiting_for_repair)
    elif action == "break":
        await msg.answer("🔨 <b>Сломать карты</b>\nФормат: <code>ID Название Кол</code>\n<i>(отмена)</i>", parse_mode="HTML")
        await state.set_state(AdminMenuStates.waiting_for_break)
    elif action == "farm_time":
        await msg.answer("⏳ <b>Сдвиг времени фермы</b>\nФормат: <code>ID Часы</code>\n<i>(отмена)</i>", parse_mode="HTML")
        await state.set_state(AdminMenuStates.waiting_for_farm_time)

    await callback.answer()

# --- ЛОВЦЫ СОСТОЯНИЙ ---
async def _cancel_state(message: types.Message, state: FSMContext):
    await state.clear()
    await message.reply("Операция отменена. ↩️")

@router.message(AdminMenuStates.waiting_for_give, F.from_user.id == ADMIN_ID)
async def st_give(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    parts = message.text.split()
    if len(parts) < 2: return await message.reply("❌ Формат: ID Сумма")
    tid = await resolve_user_id(parts[0])
    amt = int(parts[1].replace('к', '000').replace('м', '000000'))
    if tid: 
        await add_balance(tid, amt)
        await message.reply(f"✅ Выдано <b>{fmt(amt)} ᴜ</b> гладиатору <code>{tid}</code>", parse_mode="HTML")
    await state.clear()

@router.message(AdminMenuStates.waiting_for_take, F.from_user.id == ADMIN_ID)
async def st_take(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    parts = message.text.split()
    tid = await resolve_user_id(parts[0])
    amt = int(parts[1].replace('к', '000').replace('м', '000000'))
    if tid:
        bal = await get_balance(tid)
        if bal < amt: amt = bal
        await add_balance(tid, -amt)
        await message.reply(f"🔥 Изъято <b>{fmt(amt)} ᴜ</b> у <code>{tid}</code>", parse_mode="HTML")
    await state.clear()

@router.message(AdminMenuStates.waiting_for_check, F.from_user.id == ADMIN_ID)
async def st_check(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    tid = await resolve_user_id(message.text.strip())
    if tid: 
        message.text = f"чек {tid}"
        await admin_check_info(message)
    await state.clear()

@router.message(AdminMenuStates.waiting_for_reset_user, F.from_user.id == ADMIN_ID)
async def st_reset_user(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    tid = await resolve_user_id(message.text.strip())
    if tid:
        await update_user(tid, balance=0)
        await message.reply(f"🧽 Баланс игрока <code>{tid}</code> обнулен.", parse_mode="HTML")
    await state.clear()

@router.message(AdminMenuStates.waiting_for_ban, F.from_user.id == ADMIN_ID)
async def st_ban(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    parts = message.text.split()
    tid = await resolve_user_id(parts[0])
    if tid:
        message.text = f"бан {tid} " + " ".join(parts[1:])
        await admin_global_ban(message)
    await state.clear()

@router.message(AdminMenuStates.waiting_for_unban, F.from_user.id == ADMIN_ID)
async def st_unban(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    tid = await resolve_user_id(message.text.strip())
    if tid:
        message.text = f"разбан {tid}"
        await admin_universal_unban(message)
    await state.clear()

@router.message(AdminMenuStates.waiting_for_check_farm, F.from_user.id == ADMIN_ID)
async def st_check_farm(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    tid = await resolve_user_id(message.text.strip())
    if tid: await admin_check_farm_logic(tid, message, is_admin=True)
    await state.clear()

@router.message(AdminMenuStates.waiting_for_give_card, F.from_user.id == ADMIN_ID)
async def st_give_card(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    parts = message.text.split()
    tid = await resolve_user_id(parts[0])
    if tid:
        message.text = f"+карта " + " ".join(parts[1:])
        message.reply_to_message = types.Message(message_id=1, date=datetime.now(), chat=message.chat, from_user=types.User(id=tid, is_bot=False, first_name="A"))
        await admin_give_card(message)
    await state.clear()

@router.message(AdminMenuStates.waiting_for_take_card, F.from_user.id == ADMIN_ID)
async def st_take_card(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    parts = message.text.split()
    tid = await resolve_user_id(parts[0])
    if tid:
        message.text = f"-карта " + " ".join(parts[1:])
        message.reply_to_message = types.Message(message_id=1, date=datetime.now(), chat=message.chat, from_user=types.User(id=tid, is_bot=False, first_name="A"))
        await admin_take_card(message)
    await state.clear()

@router.message(AdminMenuStates.waiting_for_bulk_cards, F.from_user.id == ADMIN_ID)
async def st_bulk_cards(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    parts = message.text.split(maxsplit=1)
    tid = await resolve_user_id(parts[0])
    if tid and len(parts) > 1:
        message.text = f"+карта оптом " + parts[1]
        message.reply_to_message = types.Message(message_id=1, date=datetime.now(), chat=message.chat, from_user=types.User(id=tid, is_bot=False, first_name="A"))
        await cmd_admin_bulk_give(message)
    await state.clear()

@router.message(AdminMenuStates.waiting_for_repair, F.from_user.id == ADMIN_ID)
async def st_repair(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    parts = message.text.split()
    tid = await resolve_user_id(parts[0])
    if tid:
        message.text = f"чинить " + " ".join(parts[1:]) if len(parts) > 1 else "чинить"
        message.reply_to_message = types.Message(message_id=1, date=datetime.now(), chat=message.chat, from_user=types.User(id=tid, is_bot=False, first_name="A"))
        await admin_repair_gpu(message)
    await state.clear()

@router.message(AdminMenuStates.waiting_for_break, F.from_user.id == ADMIN_ID)
async def st_break(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    parts = message.text.split()
    tid = await resolve_user_id(parts[0])
    if tid:
        message.text = f"сломать " + " ".join(parts[1:])
        message.reply_to_message = types.Message(message_id=1, date=datetime.now(), chat=message.chat, from_user=types.User(id=tid, is_bot=False, first_name="A"))
        await admin_break_card(message)
    await state.clear()

@router.message(AdminMenuStates.waiting_for_farm_time, F.from_user.id == ADMIN_ID)
async def st_farm_time(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    parts = message.text.split()
    tid = await resolve_user_id(parts[0])
    if tid:
        message.text = f"ферма время {parts[1]}"
        message.reply_to_message = types.Message(message_id=1, date=datetime.now(), chat=message.chat, from_user=types.User(id=tid, is_bot=False, first_name="A"))
        await admin_time_machine(message)
    await state.clear()

# ==========================================
# 🔄 ПЕРЕЗАГРУЗКА БОТА
# ==========================================
@router.message(F.text.lower().in_(["перезагрузка бота", "перезагрузить бота", "перезапуск бота", "рестарт бота"]), F.from_user.id == ADMIN_ID)
async def cmd_restart_bot(message: types.Message):
    msg = await message.answer("⚙️ <b>[□□□□□□] Инициализация протокола рестарта...</b>", parse_mode="HTML")

    await msg.edit_text("⚙️ <b>[■■□□□□] Блокировка новых действий...</b>", parse_mode="HTML")
    middlewares.IS_SHUTTING_DOWN = True

    await msg.edit_text("⚙️ <b>[■■■■□□] Эвакуация активов в БД...</b>", parse_mode="HTML")
    try:
        await rescue_all_assets(message.bot) 
    except Exception as e:
        print(f"❌ ОШИБКА ПРИ ЭВАКУАЦИИ: {e}")

    await msg.edit_text("⚙️ <b>[■■■■■■] АРЕНА ОСТАНОВЛЕНА.</b>\nРазрыв соединений... Рестарт.", parse_mode="HTML")
    
    await message.bot.session.close()
    try:
        from database import db_pool 
        if db_pool: await db_pool.close() 
    except: pass

    os._exit(0)

# ==========================================
# 🔎 КОМАНДА: ЧЕК (ПРОФИЛЬ)
# ==========================================
async def get_target_id(message: types.Message):
    if message.reply_to_message:
        return message.reply_to_message.from_user.id
    parts = message.text.split()
    if len(parts) > 1:
        return await resolve_user_id(parts[1]) 
    return None

@router.message(F.text.lower().startswith("чек") & (~F.text.lower().startswith("чек ферма")))
async def admin_check_info(message: types.Message):
    if message.from_user.id != ADMIN_ID: return

    target_id = await get_target_id(message)
    if not target_id:
        return await message.reply("⚠️ Ответь на сообщение или укажи ID / @username")

    user_data = await get_user_data(target_id)
    if not user_data:
        return await message.reply("❌ Игрок не найден в базе данных турнира.")

    balance = await get_balance(target_id)
    
    try:
        target_user = await message.bot.get_chat(target_id)
        target_name = target_user.first_name
        username = target_user.username or "нет"
    except:
        target_name = f"Гладиатор {target_id}"
        username = "нет"
    
    text = f"""
👁 <b>ДОСЬЕ ГЛАДИАТОРА:</b>
━━━━━━━━━━━━━━━━━━━━
🆔 ID: <code>{target_id}</code>
📛 Имя: <b>{target_name}</b>
🏷 Username: @{username}

💰 <b>КАПИТАЛ:</b>
━━━━━━━━━━━━━━━━━━━━
💵 UMBREL: <b>{fmt(balance)}</b>
"""
    await message.reply(text, parse_mode="HTML")

# ==========================================
# УТИЛИТЫ ФЕРМЫ И БАЗЫ
# ==========================================
def parse_bulk_query(text):
    items = []
    for part in text.split(','):
        part = part.strip()
        if not part: continue
        sub_parts = part.split()
        if len(sub_parts) == 1:
            qty = 1
            search_str = sub_parts[0].lower()
        else:
            qty_str = sub_parts[-1]
            if qty_str.isdigit():
                qty = int(qty_str)
                search_str = " ".join(sub_parts[:-1]).lower()
            else:
                qty = 1
                search_str = " ".join(sub_parts).lower()
        items.append((search_str, qty))
    return items

def find_gpu_universal(search_str):
    for gid, gpu in GPUS.items():
        if re.search(r'\b' + re.escape(search_str) + r'\b', gpu['name'].lower()):
            return gid, gpu
    for gid, gpu in GPUS.items():
        if search_str in gpu['name'].lower():
            return gid, gpu
    return None, None

def find_gpu_by_text(text):
    search_str = text.lower().strip()
    return find_gpu_universal(search_str)

def parse_gpu_command(text, prefix):
    raw_text = text.lower().replace(prefix, "").strip()
    parts = raw_text.split()
    qty = 1
    search_term = raw_text
    if len(parts) > 1 and parts[-1].isdigit():
        qty = int(parts[-1])
        search_term = " ".join(parts[:-1]).strip()
    return search_term, qty

# ==========================================
# УПРАВЛЕНИЕ БАЗОЙ
# ==========================================
PG_DUMP_PATH = r"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe" 

@router.message((F.text.lower() == "бэкап") & (F.from_user.id == ADMIN_ID))
async def admin_backup(message: types.Message):
    msg = await message.reply("⏳ Создаю дамп турнирной базы...")
    backup_file = f"tourney_backup_{datetime.now().strftime('%d_%m_%H_%M')}.sql"
    
    try:
        subprocess.run([PG_DUMP_PATH, DB_URL, '-f', backup_file], check=True)
        await message.reply_document(
            FSInputFile(backup_file), 
            caption=f"📦 Бэкап БД Арены\nВремя: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        if os.path.exists(backup_file): os.remove(backup_file)
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ <b>Ошибка:</b>\n<code>{e}</code>", parse_mode="HTML")

@router.message((F.text.lower() == "фикс бд") & (F.from_user.id == ADMIN_ID))
async def fix_database_schema(message: types.Message):
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute("ALTER TABLE farms ADD COLUMN IF NOT EXISTS last_wear_update BIGINT DEFAULT 0")
    await message.reply("✅ БД обновлена.")

@router.message((F.text.lower() == "чистка инвентаря") & (F.from_user.id == ADMIN_ID))
async def clean_ghosts_global(message: types.Message):
    status_msg = await message.reply("🔄 Зачистка Арены...")
    pool = await get_db()
    async with pool.acquire() as db:
        all_farms = await db.fetch("SELECT * FROM farms")
        fixed = 0
        for farm in all_farms:
            uid = farm['user_id']
            for i in GPUS:
                gid = f"gpu_{i}"
                true_c = farm[gid]
                batch_c = await db.fetchval("SELECT SUM(qty) FROM gpu_batches WHERE user_id = $1 AND gpu_id = $2", uid, gid) or 0
                if true_c != batch_c:
                    await db.execute("DELETE FROM gpu_batches WHERE user_id = $1 AND gpu_id = $2", uid, gid)
                    if true_c > 0:
                        await db.execute("INSERT INTO gpu_batches (user_id, gpu_id, multiplier, qty, condition) VALUES ($1, $2, 1.0, $3, 100.0)", uid, gid, true_c)
                    fixed += 1
    await status_msg.edit_text(f"🧹 Исправлено расхождений: {fixed}")

# ==========================================
# 📊 АДМИН СТАТА (ГЛОБАЛЬНАЯ СВОДКА АРЕНЫ)
# ==========================================
@router.message((F.text.lower() == "админ стата") & (F.from_user.id == ADMIN_ID))
async def admin_global_stats(message: types.Message, bot: Bot):
    wait_msg = await message.reply("⏳ <i>Сканирование поля боя...</i>", parse_mode="HTML")
    pool = await get_db()
    
    async with pool.acquire() as db:
        # 1. Подсчет душ (Живые и Мертвые)
        total_users = await db.fetchval("SELECT COUNT(*) FROM users WHERE user_id != $1", ADMIN_ID) or 0
        
        # is_banned = FALSE (Те, кто сейчас рубится)
        alive_users = await db.fetchval("SELECT COUNT(*) FROM users WHERE user_id != $1 AND is_banned = FALSE", ADMIN_ID) or 0
        
        # is_banned = TRUE (Дезертиры и забаненные)
        dead_users = await db.fetchval("SELECT COUNT(*) FROM users WHERE user_id != $1 AND is_banned = TRUE", ADMIN_ID) or 0
        
        # 2. Экономика (Считаем деньги только у живых, мертвым они ни к чему)
        total_balance = await db.fetchval("SELECT SUM(balance) FROM users WHERE user_id != $1 AND is_banned = FALSE", ADMIN_ID) or 0
        
        # 3. Фермы (Мощность Арены)
        active_farms = await db.fetchval("SELECT COUNT(DISTINCT user_id) FROM gpu_batches WHERE condition > 0") or 0
        total_gpus = await db.fetchval("SELECT SUM(qty) FROM gpu_batches WHERE condition > 0") or 0
        
        # 4. Топ-5 Выживающих (Только живые)
        top_rich = await db.fetch("""
            SELECT nickname, telegram_username, balance, user_id 
            FROM users 
            WHERE user_id != $1 AND is_banned = FALSE 
            ORDER BY balance DESC LIMIT 5
        """, ADMIN_ID)

    # Красивый рендер списка лидеров
    rich_list = ""
    for i, r in enumerate(top_rich, 1):
        name = r['nickname'] or r['telegram_username'] or f"Агент {r['user_id']}"
        prefix = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"<b>{i}.</b>"
        rich_list += f"{prefix} {name}: <b>{fmt(r['balance'])}</b> ᴜ\n"

    if not rich_list:
        rich_list = " └ <i>На Арене никого нет...</i>\n"

    text = (
        f"👁‍🗨 <b>ГЛОБАЛЬНАЯ СВОДКА АРЕНЫ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 <b>Гладиаторы:</b>\n"
        f"├ Всего регистраций: <b>{fmt(total_users)}</b>\n"
        f"├ ⚔️ В игре (Живы): <b>{fmt(alive_users)}</b>\n"
        f"└ 💀 Выбыли (Сбежали): <b>{fmt(dead_users)}</b>\n\n"
        f"💰 <b>Капитал выживших:</b> <b>{fmt(total_balance)} ᴜ</b>\n\n"
        f"🏭 <b>Промышленность:</b>\n"
        f"├ Работающих ферм: <b>{fmt(active_farms)}</b>\n"
        f"└ Видеокарт гудит: <b>{fmt(total_gpus)} шт.</b>\n\n"
        f"🏆 <b>ТОП-5 ВЫЖИВАЮЩИХ:</b>\n{rich_list}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    
    await wait_msg.edit_text(text, parse_mode="HTML")

# ==========================================
# ⚖️ БАН И РАЗБАН
# ==========================================
@router.message(F.text.lower().startswith(("бан", "забанить")) & (F.from_user.id == ADMIN_ID))
async def admin_global_ban(message: types.Message):
    target_id = await get_target_id(message)
    if not target_id: return
    parts = message.text.split()
    days = 7
    idx = 2 if len(parts) > 1 and parts[1].isdigit() else 1
    if len(parts) > idx and parts[idx].isdigit():
        days = int(parts[idx])
        idx += 1
    reason = " ".join(parts[idx:]).strip()
    
    # В турнирной БД просто добавляем колонку, если ее не было (так как мы ее удалили из init_db)
    pool = await get_db()
    async with pool.acquire() as db:
        try: await db.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS ban_until BIGINT DEFAULT 0")
        except: pass
        await db.execute("UPDATE users SET ban_until = $1 WHERE user_id = $2", int(time.time()) + days * 86400, target_id)
        
    await message.reply(f"🚫 Дисквалифицирован на {days} дн. Причина: {reason or 'нарушение правил турнира'}")

@router.message(F.text.lower().startswith(("разбан", "антибан", "-бан")) & (F.from_user.id == ADMIN_ID))
async def admin_universal_unban(message: types.Message):
    target_id = await get_target_id(message)
    if not target_id: return
    
    pool = await get_db()
    async with pool.acquire() as db:
        try: await db.execute("UPDATE users SET ban_until = 0 WHERE user_id = $1", target_id)
        except: pass
    await message.reply(f"🔓 <b>Агент <code>{target_id}</code> возвращен на Арену!</b>", parse_mode="HTML")

@router.message((F.text.lower() == "разбан всех") & (F.from_user.id == ADMIN_ID))
async def admin_mass_unban(message: types.Message):
    pool = await get_db()
    async with pool.acquire() as db:
        try: 
            res = await db.execute("UPDATE users SET ban_until = 0 WHERE ban_until > $1", int(time.time()))
            affected = int(res.split()[-1])
        except: affected = 0
    await message.reply(f"☀️ Все разбанены. Освобождено: <b>{affected}</b>", parse_mode="HTML")

# ==========================================
# 🏭 ФЕРМЫ: АДМИН УПРАВЛЕНИЕ
# ==========================================
@router.message((F.text.lower() == "админ ферма") & (F.from_user.id == ADMIN_ID))
async def admin_farm_help(message: types.Message):
    text = "👑 <b>ШПАРГАЛКА ПО ID ВИДЕОКАРТ:</b>\n════════════════════\n"
    for i, gpu in sorted(GPUS.items(), key=lambda x: x[1]['price']):
        text += f"ID: <b>{i}</b> ➔ {gpu['emoji']} {gpu['name']} | 💰 <b>{fmt(gpu['price'])} ᴜ</b>\n"
    await message.reply(text, parse_mode="HTML")

@router.message(F.text.lower().startswith("+карта оптом ") & (F.from_user.id == ADMIN_ID))
async def cmd_admin_bulk_give(message: types.Message):
    raw_text = message.text.lower().replace("+карта оптом ", "").strip()
    parsed_items = parse_bulk_query(raw_text)
    if not parsed_items: return await message.reply("❌ Ошибка формата.")
        
    target_user = message.reply_to_message.from_user.id if message.reply_to_message else message.from_user.id
    farm_data = await get_farm(target_user)
    
    added_log = []
    updates = {}
    for search_str, qty in parsed_items:
        gid, gpu = find_gpu_universal(search_str)
        if not gpu:
            added_log.append(f"❌ <i>'{search_str}' не найдено</i>")
            continue
        gpu_id_str = f'gpu_{gid}'
        current_count = updates.get(gpu_id_str, farm_data.get(gpu_id_str, 0))
        updates[gpu_id_str] = current_count + qty
        added_log.append(f"✅ {gpu['emoji']} {gpu['name']}: <b>+{qty} шт.</b>")
            
    if updates:
        updates['last_wear_update'] = int(time.time())
        await update_farm(target_user, **updates)
        await sync_farm_passive(target_user, await get_farm(target_user))
        
    await message.reply(f"🚛 <b>ПОСТАВКА!</b>\n" + "\n".join(added_log), parse_mode="HTML")

@router.message(F.text.lower().startswith("+карта ") & (F.from_user.id == ADMIN_ID))
async def admin_give_card(message: types.Message):
    search_term, qty = parse_gpu_command(message.text, "+карта ")
    gpu_num, target_gpu = find_gpu_by_text(search_term)
    if not target_gpu: return await message.reply("❌ Не найдено.")
    
    gpu_id_str = f"gpu_{gpu_num}"
    target_user = message.reply_to_message.from_user.id if message.reply_to_message else message.from_user.id
    farm_data = await get_farm(target_user)
    
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute("INSERT INTO gpu_batches (user_id, gpu_id, multiplier, qty, condition, was_repaired) VALUES ($1, $2, 1.0, $3, 100.0, 0)", target_user, gpu_id_str, qty)

    await update_farm(target_user, **{gpu_id_str: farm_data.get(gpu_id_str, 0) + qty, 'last_wear_update': int(time.time())})
    await message.reply(f"👑 Выдано: <b>{qty}x {target_gpu['name']}</b>")

@router.message(F.text.lower().startswith("-карта ") & (F.from_user.id == ADMIN_ID))
async def admin_take_card(message: types.Message):
    search_term, qty = parse_gpu_command(message.text, "-карта ")
    gpu_num, target_gpu = find_gpu_by_text(search_term)
    if not target_gpu: return await message.reply("❌ Не найдено.")

    gpu_id_str = f"gpu_{gpu_num}"
    target_user = message.reply_to_message.from_user.id if message.reply_to_message else message.from_user.id
    farm_data = await get_farm(target_user)
    current_count = farm_data.get(gpu_id_str, 0)

    if current_count == 0: return await message.reply("У игрока нет таких карт.")
    qty = min(qty, current_count)

    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            batches = await db.fetch("SELECT id, qty FROM gpu_batches WHERE user_id = $1 AND gpu_id = $2 ORDER BY condition ASC", target_user, gpu_id_str)
            left_to_remove = qty
            for batch in batches:
                if left_to_remove <= 0: break
                b_id, b_qty = batch['id'], batch['qty']
                if b_qty <= left_to_remove:
                    await db.execute("DELETE FROM gpu_batches WHERE id = $1", b_id)
                    left_to_remove -= b_qty
                else:
                    await db.execute("UPDATE gpu_batches SET qty = qty - $1 WHERE id = $2", left_to_remove, b_id)
                    left_to_remove = 0

    await update_farm(target_user, **{gpu_id_str: current_count - qty, 'last_collect': int(time.time())})
    await message.reply(f"💥 Изъято: <b>{qty}x {target_gpu['name']}</b>")

async def admin_check_farm_logic(target_id, message_obj, is_edit=False, is_admin=False):
    farm_data = await get_farm(target_id)
    if not farm_data:
        text = "❌ У этого игрока нет фермы."
        return await (message_obj.edit_text(text) if is_edit else message_obj.reply(text))

    income_ph, pending_profit, is_full, total_heat, cooling_capacity, power_ph = await calculate_farm_state(target_id, farm_data)
    cooling_level = farm_data.get('cooling_level', 1)
    
    inventory_lines = []
    pool = await get_db()
    async with pool.acquire() as db:
        for i, gpu in sorted(GPUS.items(), key=lambda x: x[1]['price']):
            count = farm_data.get(f'gpu_{i}', 0)
            if count > 0:
                avg_cond = await db.fetchval("SELECT AVG(condition) FROM gpu_batches WHERE user_id = $1 AND gpu_id = $2 AND condition > 0", target_id, f"gpu_{i}") or 0.0
                hp_emoji = "💚" if avg_cond >= 80 else ("💛" if avg_cond >= 40 else "💔")
                inventory_lines.append(f" ├ {gpu['emoji']} {gpu['name']} (ID:<b>{i}</b>): <b>{count} шт.</b> | {hp_emoji} <b>{avg_cond:.1f}%</b>")
          
    inventory_text = "\n".join(inventory_lines) if inventory_lines else " └ <i>Пусто.</i>"

    text = (
        f"🔎 <b>ДОСЬЕ ФЕРМЫ:</b> <code>{target_id}</code>\n"
        f"════════════════════\n"
        f"⚡️ Доход: <b>{fmt(income_ph)} ᴜ/ч</b>\n"
        f"🔌 Энергия: <b>{fmt(power_ph)} ᴜ/ч</b>\n"
        f"🌡 Тепло: <b>{fmt(total_heat)} / {fmt(cooling_capacity)}</b>\n"
        f"════════════════════\n"
        f"🖥 <b>Оборудование:</b>\n{inventory_text}"
    )

    builder = InlineKeyboardBuilder()
    if is_admin:
        builder.row(types.InlineKeyboardButton(text="🎁 Подарить карту", callback_data=f"adm_gift_list_{target_id}"))
        builder.row(
            types.InlineKeyboardButton(text="📉 Конфискация", callback_data=f"adm_farm_conf_{target_id}"),
            types.InlineKeyboardButton(text="💥 Сжечь всё", callback_data=f"adm_farm_burn_{target_id}")
        )
    
    if is_edit:
        try: await message_obj.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
        except: pass
    else:
        await message_obj.reply(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.message(F.text.lower().startswith("чек ферма") & (F.from_user.id == ADMIN_ID))
async def admin_check_farm_cmd(message: types.Message):
    target_id = await get_target_id(message)
    if not target_id: return await message.reply("⚠️ Укажите ID.")
    await admin_check_farm_logic(target_id, message, is_admin=True)

@router.callback_query(F.data.startswith("adm_farm_back_") & (F.from_user.id == ADMIN_ID))
async def admin_farm_back_btn(callback: types.CallbackQuery):
    target_id = int(callback.data.split("_")[3])
    await admin_check_farm_logic(target_id, callback.message, is_edit=True, is_admin=True)
    await callback.answer()

@router.callback_query(F.data.startswith("adm_gift_list_") & (F.from_user.id == ADMIN_ID))
async def admin_gift_gpu_selection(callback: types.CallbackQuery):
    target_id = int(callback.data.split("_")[3])
    builder = InlineKeyboardBuilder()
    for i, gpu in sorted(GPUS.items(), key=lambda x: x[1]['price']):
        builder.button(text=f"{gpu['emoji']} {gpu['name']}", callback_data=f"adm_do_gift_{target_id}_{i}")
    builder.adjust(2)
    builder.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data=f"adm_farm_back_{target_id}"))
    await callback.message.edit_text("🎁 Какую карту дарим?", reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("adm_do_gift_") & (F.from_user.id == ADMIN_ID))
async def admin_execute_gift(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    target_id, gpu_id = int(parts[3]), int(parts[4])
    farm_data = await get_farm(target_id)
    await update_farm(target_id, **{f'gpu_{gpu_id}': farm_data.get(f'gpu_{gpu_id}', 0) + 1})
    
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute("INSERT INTO gpu_batches (user_id, gpu_id, multiplier, qty, condition, was_repaired) VALUES ($1, $2, 1.0, 1, 100.0, 0)", target_id, f"gpu_{gpu_id}")

    await callback.answer(f"✅ Выдано!", show_alert=True)
    await admin_check_farm_logic(target_id, callback.message, is_edit=True, is_admin=True)

@router.callback_query(F.data.startswith("adm_farm_conf_") & (F.from_user.id == ADMIN_ID))
async def admin_confiscate_farm_btn(callback: types.CallbackQuery):
    target_id = int(callback.data.split("_")[3])
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute("DELETE FROM gpu_batches WHERE user_id = $1", target_id)
    updates = {f'gpu_{i}': 0 for i in range(1, 31)}
    updates['last_collect'] = int(time.time())
    await update_farm(target_id, **updates)
    await callback.message.edit_text("📉 Ферма очищена.")

@router.callback_query(F.data.startswith("adm_farm_burn_") & (F.from_user.id == ADMIN_ID))
async def admin_burn_farm_btn(callback: types.CallbackQuery):
    target_id = int(callback.data.split("_")[3])
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute("UPDATE gpu_batches SET condition = 0.0 WHERE user_id = $1", target_id)
    await callback.message.edit_text("🔥 Карты на ферме уничтожены дотла (0%).")

@router.message(F.text.lower().startswith("чинить") & (F.from_user.id == ADMIN_ID))
async def admin_repair_gpu(message: types.Message):
    target_id = await get_target_id(message)
    if not target_id: return await message.reply("⚠️ Укажите ID.")

    text_raw = message.text.lower().strip()
    pool = await get_db()
    async with pool.acquire() as db:
        if text_raw == "чинить" or (len(text_raw.split()) == 2 and text_raw.split()[1].isdigit()):
            await db.execute("UPDATE gpu_batches SET condition = 100.0, was_repaired = 0 WHERE user_id = $1", target_id)
            stats = await db.fetch("SELECT gpu_id, SUM(qty) as total FROM gpu_batches WHERE user_id = $1 AND condition > 0 GROUP BY gpu_id", target_id)
            reset_updates = {f'gpu_{i}': 0 for i in GPUS}
            await update_farm(target_id, **reset_updates)
            for s in stats:
                await update_farm(target_id, **{s['gpu_id']: s['total']})
            return await message.reply("🔧 Всё восстановлено!")

        search_term, repair_qty = parse_gpu_command(message.text, "чинить ")
        gpu_num, target_gpu = find_gpu_by_text(search_term)
        if not target_gpu: return await message.reply("❌ Не найдено.")
        gpu_id_str = f"gpu_{gpu_num}"

        async with db.transaction():
            broken_batches = await db.fetch("SELECT id, qty, multiplier FROM gpu_batches WHERE user_id = $1 AND gpu_id = $2 AND condition <= 0", target_id, gpu_id_str)
            total_broken = sum(b['qty'] for b in broken_batches)
            if total_broken == 0: return await message.reply("У игрока нет сломанных карт.")

            to_fix = min(repair_qty, total_broken)
            fixed_count = 0
            
            for batch in broken_batches:
                if to_fix <= 0: break
                b_id, b_qty, b_mult = batch['id'], batch['qty'], batch['multiplier']
                
                if b_qty <= to_fix:
                    await db.execute("UPDATE gpu_batches SET condition = 100.0, was_repaired = 0 WHERE id = $1", b_id)
                    to_fix -= b_qty
                    fixed_count += b_qty
                else:
                    await db.execute("UPDATE gpu_batches SET qty = qty - $1 WHERE id = $2", to_fix, b_id)
                    await db.execute("INSERT INTO gpu_batches (user_id, gpu_id, multiplier, qty, condition, was_repaired) VALUES ($1, $2, $3, $4, 100.0, 0)", target_id, gpu_id_str, b_mult, to_fix)
                    fixed_count += to_fix
                    to_fix = 0

        farm_data = await get_farm(target_id)
        await update_farm(target_id, **{gpu_id_str: farm_data.get(gpu_id_str, 0) + fixed_count})
        await message.reply(f"🔧 Исправлено: <b>{fixed_count} шт.</b>")

@router.message(F.text.lower().startswith("сломать ") & (F.from_user.id == ADMIN_ID))
async def admin_break_card(message: types.Message):
    search_term, break_qty = parse_gpu_command(message.text, "сломать ")
    gpu_num, target_gpu = find_gpu_by_text(search_term)
    if not target_gpu: return await message.reply("❌ Не найдено.")
    
    gpu_id_str = f"gpu_{gpu_num}"
    target_id = message.reply_to_message.from_user.id if message.reply_to_message else message.from_user.id
    farm_data = await get_farm(target_id)
    current_active = farm_data.get(gpu_id_str, 0)
    if current_active < break_qty: return await message.reply("Столько нет.")

    pool = await get_db()
    async with pool.acquire() as db:
        async with db.transaction():
            batches = await db.fetch("SELECT id, qty, multiplier, was_repaired FROM gpu_batches WHERE user_id = $1 AND gpu_id = $2 AND condition > 0", target_id, gpu_id_str)
            left_to_break = break_qty
            for batch in batches:
                if left_to_break <= 0: break
                if batch['qty'] <= left_to_break:
                    await db.execute("UPDATE gpu_batches SET condition = 0.0 WHERE id = $1", batch['id'])
                    left_to_break -= batch['qty']
                else:
                    await db.execute("UPDATE gpu_batches SET qty = qty - $1 WHERE id = $2", left_to_break, batch['id'])
                    await db.execute("INSERT INTO gpu_batches (user_id, gpu_id, multiplier, qty, condition, was_repaired) VALUES ($1, $2, $3, $4, 0.0, $5)", target_id, gpu_id_str, batch['multiplier'], left_to_break, batch['was_repaired'])
                    left_to_break = 0

    await update_farm(target_id, **{gpu_id_str: current_active - break_qty})
    await message.reply(f"💥 Сломано: {break_qty} шт.")

@router.message((F.text.lower().startswith("ферма время")) & (F.from_user.id == ADMIN_ID))
async def admin_time_machine(message: types.Message):
    parts = message.text.split()
    if len(parts) < 3: return
    hours = int(parts[2])
    target_user = message.reply_to_message.from_user.id if message.reply_to_message else message.from_user.id
    farm_data = await get_farm(target_user)
    shift = hours * 3600
    new_collect = farm_data.get('last_collect', int(time.time())) - shift
    new_wear = farm_data.get('last_wear_update', int(time.time())) - shift
    await update_farm(target_user, last_collect=new_collect, last_wear_update=new_wear)
    await message.reply(f"⏳ Время сдвинуто на {hours} ч.")