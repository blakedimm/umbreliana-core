import psutil
import os
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

router = Router()
# ==========================================
# 🔐 СИСТЕМНЫЕ ПЕРЕМЕННЫЕ И ДОСТУПЫ (RBAC)
# ==========================================
ADMIN_ID = int(os.getenv("ADMIN_ID", 1412940726))

# Достаем список модераторов из .env и чистим от пробелов
MODERATORS = [int(i.strip()) for i in os.getenv("MODERATORS", "").split(",") if i.strip()]

def is_moderator(user_id):
    """Проверяет, является ли пользователь Создателем или Модератором"""
    return user_id == ADMIN_ID or user_id in MODERATORS

# ==========================================
# 🧠 МАШИНА СОСТОЯНИЙ (FSM)
# ==========================================
class AdminMenuStates(StatesGroup):
    waiting_for_stop_confirm = State()
    waiting_for_give = State()
    waiting_for_take = State()
    waiting_for_check = State()
    waiting_for_ban = State()
    waiting_for_unban = State()
    waiting_for_integrity = State()
    waiting_for_add_status = State()
    waiting_for_rem_status = State()
    waiting_for_check_debt = State()
    waiting_for_fine = State()
    waiting_for_mass_fine = State()
    waiting_for_deadline = State()
    waiting_for_execute = State()
    waiting_for_forgive = State()
    waiting_for_check_farm = State()
    waiting_for_audit_farm = State()
    waiting_for_give_card = State()
    waiting_for_take_card = State()
    waiting_for_bulk_cards = State()
    waiting_for_repair = State()
    waiting_for_break = State()
    waiting_for_farm_time = State()
    waiting_for_rollback = State()
    waiting_for_reset_user = State()
    waiting_for_reset_exam = State()
    waiting_for_delete_clan = State()
    waiting_for_change_boss = State()

# ==========================================
# 🎨 ГЕНЕРАТОРЫ ИНТЕРФЕЙСА
# ==========================================
def get_admin_main_text():
    process = psutil.Process(os.getpid())
    ram_mb = process.memory_info().rss / (1024 * 1024)
    cpu = psutil.cpu_percent()
    return (
        f"👑 <b>ГЛАВНЫЙ ТЕРМИНАЛ АРХИТЕКТОРА</b>\n"
        f"🖥 Хост: <b>RAM {ram_mb:.1f}MB</b> | <b>CPU {cpu}%</b>\n"
        f"════════════════════\n"
        f"<i>Доступ открыт, Коннор ожидает указаний.</i>"
    )

def get_admin_kb(section="main"):
    builder = InlineKeyboardBuilder()
    if section == "main":
        builder.row(types.InlineKeyboardButton(text="💰 Экономика", callback_data="adm_nav_eco"), types.InlineKeyboardButton(text="⚖️ Правосудие", callback_data="adm_nav_law"))
        builder.row(types.InlineKeyboardButton(text="🏭 Фермы (GPU)", callback_data="adm_nav_farm"), types.InlineKeyboardButton(text="⚙️ Система", callback_data="adm_nav_sys"))
        builder.row(types.InlineKeyboardButton(text="🏴‍☠️ Синдикаты", callback_data="adm_nav_clan"))
        builder.row(types.InlineKeyboardButton(text="❌ Закрыть панель", callback_data="adm_nav_close"))
    elif section == "eco":
        builder.row(types.InlineKeyboardButton(text="➕ Выдать ᴜ", callback_data="adm_act_give"), types.InlineKeyboardButton(text="➖ Забрать ᴜ", callback_data="adm_act_take"))
        builder.row(types.InlineKeyboardButton(text="🔎 Чек досье", callback_data="adm_act_check"), types.InlineKeyboardButton(text="🧬 На вшивость", callback_data="adm_act_integrity"))
        builder.row(types.InlineKeyboardButton(text="👑 +Статус", callback_data="adm_act_add_status"), types.InlineKeyboardButton(text="🗑 -Статус", callback_data="adm_act_rem_status"))
        builder.row(types.InlineKeyboardButton(text="📊 Админ стата", callback_data="adm_act_global_stats"), types.InlineKeyboardButton(text="💸 Переводы", callback_data="adm_act_tx_stats"))
        builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="adm_nav_main"))
    elif section == "law":
        builder.row(types.InlineKeyboardButton(text="🔎 Чек долг", callback_data="adm_act_check_debt"), types.InlineKeyboardButton(text="📋 Должники", callback_data="adm_act_debtors"))
        builder.row(types.InlineKeyboardButton(text="💸 Штраф", callback_data="adm_act_fine"), types.InlineKeyboardButton(text="⏳ Изменить срок", callback_data="adm_act_deadline"))
        builder.row(types.InlineKeyboardButton(text="💀 Казнить", callback_data="adm_act_execute"), types.InlineKeyboardButton(text="😇 Простить", callback_data="adm_act_forgive"))
        builder.row(types.InlineKeyboardButton(text="🚫 Выдать БАН", callback_data="adm_act_ban"), types.InlineKeyboardButton(text="🔓 Разбан", callback_data="adm_act_unban"))
        builder.row(types.InlineKeyboardButton(text="🌍 Масс. Штраф", callback_data="adm_act_mass_fine"), types.InlineKeyboardButton(text="🌍 Масс. Казнь", callback_data="adm_act_mass_execute"))
        builder.row(types.InlineKeyboardButton(text="🕊 Простить всех", callback_data="adm_act_forgive_all"), types.InlineKeyboardButton(text="☀️ Разбан всех", callback_data="adm_act_unban_all"))
        builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="adm_nav_main"))
    elif section == "farm":
        builder.row(types.InlineKeyboardButton(text="🔎 Чек ферму", callback_data="adm_act_check_farm"), types.InlineKeyboardButton(text="🧠 ИИ-Аудит", callback_data="adm_act_audit_farm"))
        builder.row(types.InlineKeyboardButton(text="➕ Карта", callback_data="adm_act_give_card"), types.InlineKeyboardButton(text="➖ Карта", callback_data="adm_act_take_card"))
        builder.row(types.InlineKeyboardButton(text="📦 Карта оптом", callback_data="adm_act_bulk_cards"), types.InlineKeyboardButton(text="⏳ Сдвиг времени", callback_data="adm_act_farm_time"))
        builder.row(types.InlineKeyboardButton(text="🔧 Чинить", callback_data="adm_act_repair"), types.InlineKeyboardButton(text="🔨 Сломать", callback_data="adm_act_break"))
        builder.row(types.InlineKeyboardButton(text="📋 Шпаргалка GPU", callback_data="adm_act_gpu_help"), types.InlineKeyboardButton(text="📊 Топ видюх", callback_data="adm_act_gpu_stats"))
        builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="adm_nav_main"))
    elif section == "sys":
        builder.row(types.InlineKeyboardButton(text="📦 Бэкап БД", callback_data="adm_act_backup"), types.InlineKeyboardButton(text="📂 Логи", callback_data="adm_act_logs"))
        builder.row(types.InlineKeyboardButton(text="🎛 Модули", callback_data="adm_act_modules"), types.InlineKeyboardButton(text="🛠 Фикс БД", callback_data="adm_act_fix_db"))
        builder.row(types.InlineKeyboardButton(text="🧹 Чистка инвентаря", callback_data="adm_act_clean_inv"), types.InlineKeyboardButton(text="🎓 Сброс экзамена", callback_data="adm_act_reset_exam"))
        builder.row(types.InlineKeyboardButton(text="⏪ Откат времени", callback_data="adm_act_rollback"), types.InlineKeyboardButton(text="🧽 Полный сброс", callback_data="adm_act_reset_user"))
        builder.row(types.InlineKeyboardButton(text="🔄 ПЕРЕЗАГРУЗКА", callback_data="adm_act_restart"))
        builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="adm_nav_main"))
    elif section == "clan":
        builder.row(types.InlineKeyboardButton(text="💥 Снести клан", callback_data="adm_act_del_clan"), types.InlineKeyboardButton(text="👑 Сменить босса", callback_data="adm_act_change_boss"))
        builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="adm_nav_main"))

    return builder.as_markup()

# ==========================================
# 🎮 НАВИГАЦИЯ И ВЫЗОВЫ
# ==========================================
@router.message((F.text.lower() == "админ панель") & (F.from_user.id == ADMIN_ID))
async def main_admin_panel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.reply(get_admin_main_text(), reply_markup=get_admin_kb("main"), parse_mode="HTML")

@router.callback_query(F.data.startswith("adm_nav_") & (F.from_user.id == ADMIN_ID))
async def admin_panel_navigation(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    section = callback.data.replace("adm_nav_", "")
    if section == "close": return await callback.message.delete()
        
    titles = {
        "eco": "💰 <b>УПРАВЛЕНИЕ: ЭКОНОМИКА</b>", "law": "⚖️ <b>УПРАВЛЕНИЕ: ПРАВОСУДИЕ</b>",
        "farm": "🏭 <b>УПРАВЛЕНИЕ: ФЕРМЫ</b>", "sys": "⚙️ <b>УПРАВЛЕНИЕ: СИСТЕМА</b>",
        "clan": "🏴‍☠️ <b>УПРАВЛЕНИЕ: СИНДИКАТЫ</b>", "main": get_admin_main_text()
    }
    try: await callback.message.edit_text(titles.get(section), reply_markup=get_admin_kb(section), parse_mode="HTML")
    except: pass
    await callback.answer()

@router.callback_query(F.data.startswith("adm_act_") & (F.from_user.id == ADMIN_ID))
async def admin_panel_actions(callback: types.CallbackQuery, state: FSMContext):
    action = callback.data.replace("adm_act_", "")
    msg = callback.message
    
    # 1. ПРЯМЫЕ КОМАНДЫ (Мы просим админа ввести их текстом, чтобы избежать циклических импортов функций)
    direct_commands = {
        "global_stats": "админ стата", "tx_stats": "стата переводов", "whale_stats": "стата китов",
        "debtors": "список должников", "forgive_all": "простить всех", "unban_all": "разбан всех",
        "mass_execute": "казнить всех", "gpu_help": "админ ферма", "gpu_stats": "видюхи",
        "backup": "бэкап", "logs": "логи", "modules": "статус модулей", "fix_db": "фикс бд",
        "clean_inv": "чистка инвентаря", "restart": "перезагрузка бота"
    }
    
    if action in direct_commands:
        await msg.answer(f"👉 <i>Для выполнения нажми или отправь:</i>\n<code>{direct_commands[action]}</code>", parse_mode="HTML")
        return await callback.answer()

    # 2. КОМАНДЫ С ВВОДОМ ДАННЫХ (Переводим в FSM стейт)
    state_map = {
        "give": (AdminMenuStates.waiting_for_give, "➕ <b>Выдача UMBREL</b>\nФормат: <code>ID Сумма</code>"),
        "take": (AdminMenuStates.waiting_for_take, "➖ <b>Изъятие UMBREL</b>\nФормат: <code>ID Сумма</code>"),
        "check": (AdminMenuStates.waiting_for_check, "🔎 <b>Поиск досье</b>\nВведите <code>ID</code> или <code>@username</code>"),
        "integrity": (AdminMenuStates.waiting_for_integrity, "🧬 <b>Проверка на вшивость</b>\nВведите <code>ID</code> или <code>@username</code>"),
        "add_status": (AdminMenuStates.waiting_for_add_status, "👑 <b>Выдать статусы</b>\nФормат: <code>ID Статус1 Статус2</code> (0-5)"),
        "rem_status": (AdminMenuStates.waiting_for_rem_status, "🗑 <b>Снять статусы</b>\nФормат: <code>ID Статус1 Статус2</code>"),
        "check_debt": (AdminMenuStates.waiting_for_check_debt, "🔎 <b>Досье должника</b>\nВведите <code>ID</code>"),
        "fine": (AdminMenuStates.waiting_for_fine, "💸 <b>Штраф игроку</b>\nФормат: <code>ID Сумма</code>"),
        "mass_fine": (AdminMenuStates.waiting_for_mass_fine, "🌍 <b>Штраф ВСЕМ должникам</b>\nВведите <code>Сумму</code>"),
        "deadline": (AdminMenuStates.waiting_for_deadline, "⏳ <b>Срок долга</b>\nФормат: <code>ID Часы</code>"),
        "execute": (AdminMenuStates.waiting_for_execute, "💀 <b>Казнить игрока</b>\nФормат: <code>ID Дни_Бана</code>"),
        "forgive": (AdminMenuStates.waiting_for_forgive, "😇 <b>Простить игрока</b>\nВведите <code>ID</code>"),
        "ban": (AdminMenuStates.waiting_for_ban, "🚫 <b>Выдача бана</b>\nФормат: <code>ID Дни Причина</code>"),
        "unban": (AdminMenuStates.waiting_for_unban, "🔓 <b>Разбан</b>\nВведите <code>ID</code>"),
        "check_farm": (AdminMenuStates.waiting_for_check_farm, "🏭 <b>Поиск фермы</b>\nВведите <code>ID</code> или <code>@username</code>"),
        "audit_farm": (AdminMenuStates.waiting_for_audit_farm, "🧠 <b>ИИ-Аудит фермы</b>\nВведите <code>ID</code> или <code>@username</code>"),
        "give_card": (AdminMenuStates.waiting_for_give_card, "➕ <b>Выдать карту</b>\nФормат: <code>ID Название Количество</code>"),
        "take_card": (AdminMenuStates.waiting_for_take_card, "➖ <b>Забрать карту</b>\nФормат: <code>ID Название Количество</code>"),
        "bulk_cards": (AdminMenuStates.waiting_for_bulk_cards, "📦 <b>Оптом карты</b>\nФормат: <code>ID Карта Кол, Карта Кол...</code>"),
        "repair": (AdminMenuStates.waiting_for_repair, "🔧 <b>Чинить карты</b>\nФормат: <code>ID Название Кол</code> (или просто ID для фулл ремонта)"),
        "break": (AdminMenuStates.waiting_for_break, "🔨 <b>Сломать карты</b>\nФормат: <code>ID Название Кол</code>"),
        "farm_time": (AdminMenuStates.waiting_for_farm_time, "⏳ <b>Сдвиг времени фермы</b>\nФормат: <code>ID Часы</code>"),
        "rollback": (AdminMenuStates.waiting_for_rollback, "⏪ <b>Глобальный откат</b>\nВведите время: <code>3ч 1м 20с</code> или секунды."),
        "reset_user": (AdminMenuStates.waiting_for_reset_user, "🧽 <b>Сброс долгов юзера</b>\nВведите <code>ID</code>"),
        "reset_exam": (AdminMenuStates.waiting_for_reset_exam, "🎓 <b>Сброс экзамена</b>\nВведите <code>ID</code>"),
        "del_clan": (AdminMenuStates.waiting_for_delete_clan, "💥 <b>Снести клан</b>\nВведите <code>ID клана</code>"),
        "change_boss": (AdminMenuStates.waiting_for_change_boss, "👑 <b>Смена босса</b>\nФормат: <code>ID_клана ID_игрока</code>")
    }

    if action in state_map:
        target_state, text = state_map[action]
        await msg.answer(f"{text}\n<i>(напиши 'отмена' для отмены)</i>", parse_mode="HTML")
        await state.set_state(target_state)

    await callback.answer()

# ==========================================
# 🎣 ЛОВЦЫ СОСТОЯНИЙ (ПЕРЕАДРЕСАЦИЯ В ТЕКСТОВЫЕ КОМАНДЫ)
# ==========================================
async def _cancel_state(message: types.Message, state: FSMContext):
    await state.clear()
    await message.reply("Операция отменена. ↩️")

# Экономика
@router.message(AdminMenuStates.waiting_for_give, F.from_user.id == ADMIN_ID)
async def st_give(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    message.text = f"выдать {message.text.strip()}"
    await state.clear()
    from .economy_ops import admin_add_money
    await admin_add_money(message)

@router.message(AdminMenuStates.waiting_for_take, F.from_user.id == ADMIN_ID)
async def st_take(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    message.text = f"забрать {message.text.strip()}"
    await state.clear()
    from .economy_ops import admin_take_money
    await admin_take_money(message)

@router.message(AdminMenuStates.waiting_for_check, F.from_user.id == ADMIN_ID)
async def st_check(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    message.text = f"чек {message.text.strip()}"
    await state.clear()
    from .economy_ops import admin_check_info
    await admin_check_info(message)

@router.message(AdminMenuStates.waiting_for_integrity, F.from_user.id == ADMIN_ID)
async def st_integ(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    message.text = f"проверка на вшивость {message.text.strip()}"
    await state.clear()
    from .economy_ops import admin_integrity_check
    await admin_integrity_check(message)

@router.message(AdminMenuStates.waiting_for_add_status, F.from_user.id == ADMIN_ID)
async def st_add_stat(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    parts = message.text.split()
    message.text = f"+статус {parts[0]} " + " ".join(parts[1:])
    await state.clear()
    from .economy_ops import admin_add_status
    await admin_add_status(message)

@router.message(AdminMenuStates.waiting_for_rem_status, F.from_user.id == ADMIN_ID)
async def st_rem_stat(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    parts = message.text.split()
    message.text = f"-статус {parts[0]} " + " ".join(parts[1:])
    await state.clear()
    from .economy_ops import admin_remove_status
    await admin_remove_status(message)

# Правосудие
@router.message(AdminMenuStates.waiting_for_check_debt, F.from_user.id == ADMIN_ID)
async def st_check_debt(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    message.text = f"чекдолг {message.text.strip()}"
    await state.clear()
    from .justice_ops import admin_check_debt
    await admin_check_debt(message)

@router.message(AdminMenuStates.waiting_for_fine, F.from_user.id == ADMIN_ID)
async def st_fine(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    parts = message.text.split()
    message.text = f"штраф {parts[0]} {parts[1]}"
    await state.clear()
    from .justice_ops import admin_add_debt
    await admin_add_debt(message)

@router.message(AdminMenuStates.waiting_for_mass_fine, F.from_user.id == ADMIN_ID)
async def st_mass_fine(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    message.text = f"штраф всем {message.text.strip()}"
    await state.clear()
    from .justice_ops import admin_mass_fine
    await admin_mass_fine(message)

@router.message(AdminMenuStates.waiting_for_deadline, F.from_user.id == ADMIN_ID)
async def st_deadline(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    parts = message.text.split()
    message.text = f"срок {parts[0]} {parts[1]}"
    await state.clear()
    from .justice_ops import admin_change_deadline
    await admin_change_deadline(message)

@router.message(AdminMenuStates.waiting_for_execute, F.from_user.id == ADMIN_ID)
async def st_execute(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    parts = message.text.split()
    days = parts[1] if len(parts) > 1 else "3"
    message.text = f"казнить {parts[0]} {days}"
    await state.clear()
    from .justice_ops import admin_execute_debtor
    await admin_execute_debtor(message)

@router.message(AdminMenuStates.waiting_for_forgive, F.from_user.id == ADMIN_ID)
async def st_forgive(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    message.text = f"простить {message.text.strip()}"
    await state.clear()
    from .justice_ops import admin_forgive_debt
    await admin_forgive_debt(message)

@router.message(AdminMenuStates.waiting_for_ban, F.from_user.id == ADMIN_ID)
async def st_ban(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    parts = message.text.split()
    message.text = f"бан {parts[0]} " + " ".join(parts[1:])
    await state.clear()
    from .justice_ops import admin_global_ban
    await admin_global_ban(message)

@router.message(AdminMenuStates.waiting_for_unban, F.from_user.id == ADMIN_ID)
async def st_unban(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    message.text = f"разбан {message.text.strip()}"
    await state.clear()
    from .justice_ops import admin_universal_unban
    await admin_universal_unban(message)

# Фермы
@router.message(AdminMenuStates.waiting_for_check_farm, F.from_user.id == ADMIN_ID)
async def st_check_farm(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    message.text = f"чек ферма {message.text.strip()}"
    await state.clear()
    from .farm_ops import admin_check_farm_cmd
    await admin_check_farm_cmd(message)

@router.message(AdminMenuStates.waiting_for_audit_farm, F.from_user.id == ADMIN_ID)
async def st_audit_farm(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    message.text = f"оценка фермы {message.text.strip()}"
    await state.clear()
    from .farm_ops import cmd_farm_audit
    await cmd_farm_audit(message)

@router.message(AdminMenuStates.waiting_for_give_card, F.from_user.id == ADMIN_ID)
async def st_give_card(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    parts = message.text.split()
    message.text = f"+карта " + " ".join(parts[1:])
    message.reply_to_message = types.Message(message_id=1, date=message.date, chat=message.chat, from_user=types.User(id=int(parts[0]), is_bot=False, first_name="A"))
    await state.clear()
    from .farm_ops import admin_give_card
    await admin_give_card(message)

@router.message(AdminMenuStates.waiting_for_take_card, F.from_user.id == ADMIN_ID)
async def st_take_card(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    parts = message.text.split()
    message.text = f"-карта " + " ".join(parts[1:])
    message.reply_to_message = types.Message(message_id=1, date=message.date, chat=message.chat, from_user=types.User(id=int(parts[0]), is_bot=False, first_name="A"))
    await state.clear()
    from .farm_ops import admin_take_card
    await admin_take_card(message)

@router.message(AdminMenuStates.waiting_for_bulk_cards, F.from_user.id == ADMIN_ID)
async def st_bulk_cards(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    parts = message.text.split(maxsplit=1)
    message.text = f"+карта оптом " + parts[1]
    message.reply_to_message = types.Message(message_id=1, date=message.date, chat=message.chat, from_user=types.User(id=int(parts[0]), is_bot=False, first_name="A"))
    await state.clear()
    from .farm_ops import cmd_admin_bulk_give
    await cmd_admin_bulk_give(message)

@router.message(AdminMenuStates.waiting_for_repair, F.from_user.id == ADMIN_ID)
async def st_repair(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    parts = message.text.split()
    message.text = f"чинить " + " ".join(parts[1:]) if len(parts) > 1 else "чинить"
    message.reply_to_message = types.Message(message_id=1, date=message.date, chat=message.chat, from_user=types.User(id=int(parts[0]), is_bot=False, first_name="A"))
    await state.clear()
    from .farm_ops import admin_repair_gpu
    await admin_repair_gpu(message)

@router.message(AdminMenuStates.waiting_for_break, F.from_user.id == ADMIN_ID)
async def st_break(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    parts = message.text.split()
    message.text = f"сломать " + " ".join(parts[1:])
    message.reply_to_message = types.Message(message_id=1, date=message.date, chat=message.chat, from_user=types.User(id=int(parts[0]), is_bot=False, first_name="A"))
    await state.clear()
    from .farm_ops import admin_break_card
    await admin_break_card(message)

@router.message(AdminMenuStates.waiting_for_farm_time, F.from_user.id == ADMIN_ID)
async def st_farm_time(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    parts = message.text.split()
    message.text = f"ферма время {parts[1]}"
    message.reply_to_message = types.Message(message_id=1, date=message.date, chat=message.chat, from_user=types.User(id=int(parts[0]), is_bot=False, first_name="A"))
    await state.clear()
    from .farm_ops import admin_time_machine
    await admin_time_machine(message)

# Система
@router.message(AdminMenuStates.waiting_for_rollback, F.from_user.id == ADMIN_ID)
async def st_rollback(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    message.text = f"откатить {message.text.strip()}"
    await state.clear()
    from .system_ops import cmd_admin_rollback
    await cmd_admin_rollback(message)

@router.message(AdminMenuStates.waiting_for_reset_user, F.from_user.id == ADMIN_ID)
async def st_reset_user(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    message.text = f"сброс {message.text.strip()}"
    await state.clear()
    from .justice_ops import admin_reset_everything
    await admin_reset_everything(message)

@router.message(AdminMenuStates.waiting_for_reset_exam, F.from_user.id == ADMIN_ID)
async def st_reset_exam(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    message.text = f"сброс теста {message.text.strip()}"
    await state.clear()
    from .justice_ops import admin_reset_exam
    await admin_reset_exam(message)

@router.message(AdminMenuStates.waiting_for_delete_clan, F.from_user.id == ADMIN_ID)
async def st_del_clan(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    message.text = f"снести клан {message.text.strip()}"
    await state.clear()
    from .system_ops import admin_delete_clan
    await admin_delete_clan(message)

@router.message(AdminMenuStates.waiting_for_change_boss, F.from_user.id == ADMIN_ID)
async def st_change_boss(message: types.Message, state: FSMContext):
    if message.text.lower() == 'отмена': return await _cancel_state(message, state)
    message.text = f"сменить босса {message.text.strip()}"
    await state.clear()
    from .system_ops import admin_change_clan_boss
    await admin_change_clan_boss(message)