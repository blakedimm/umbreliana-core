import os
import time
from datetime import datetime

from aiogram import Router, types, F

from core.database import (
    get_db, get_user_data, update_user, get_overdue_users,
    mass_forgive_all, mass_unban_all, mass_fine_debtors, mass_execute_all,
    resolve_user_id
)

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

def fmt(num):
    return f"{int(num):,}".replace(",", " ")

async def get_target_id(message: types.Message):
    """Вспомогательная функция для поиска ID в реплаях или тексте"""
    if message.reply_to_message:
        return message.reply_to_message.from_user.id
    parts = message.text.split()
    if len(parts) > 1:
        return await resolve_user_id(parts[1]) 
    return None

# ==========================================
# ⚖️ ИНДИВИДУАЛЬНОЕ ПРАВОСУДИЕ (ДОЛГИ)
# ==========================================

@router.message((F.text.lower().startswith("чекдолг")) & (F.from_user.id == ADMIN_ID))
async def admin_check_debt(message: types.Message):
    target_id = await get_target_id(message)
    if not target_id: return await message.reply("⚠️ Ответь на сообщение или напиши ID.")
        
    user_data = await get_user_data(target_id)
    if not user_data: return await message.reply("❌ Игрок не найден.")

    debt = user_data.get('debt', 0)
    ban_until = user_data.get('ban_until', 0)
    current_time = int(time.time())
    
    status_text = "🟢 Чист"
    if ban_until > current_time:
        status_text = f"🔴 В БАНЕ ещё {(ban_until - current_time) // 3600} ч."
    elif debt > 0:
        status_text = "🟡 На крючке"

    if debt <= 0 and ban_until <= current_time:
        return await message.reply(f"У игрока <code>{target_id}</code> нет долгов. Статус: {status_text}", parse_mode="HTML")
    
    rem = user_data.get('debt_time', 0) - current_time
    time_str = f"{rem // 3600}ч. {(rem % 3600) // 60}мин." if rem > 0 else "ПРОСРОЧЕН 💀"
    if user_data.get('debt_time', 0) == 0: time_str = "Без таймера"

    await message.reply(f"📋 <b>ДОСЬЕ ДОЛЖНИКА:</b> <code>{target_id}</code>\n📉 Долг: <b>{fmt(debt)}</b> UMBREL\n⏳ Таймер: {time_str}\n🚦 Статус: {status_text}", parse_mode="HTML")


@router.message((F.text.lower().startswith("простить")) & (F.from_user.id == ADMIN_ID) & (~F.text.lower().startswith("простить всех")))
async def admin_forgive_debt(message: types.Message):
    target_id = await get_target_id(message)
    if not target_id: return await message.reply("⚠️ Объект не найден.")
    
    await update_user(target_id, debt=0, debt_time=0, ban_until=0)
    await message.reply(f"😇 <b>Амнистия!</b> Долги <code>{target_id}</code> списаны. Бан снят.", parse_mode="HTML")


@router.message((F.text.lower().startswith("казнить")) & (F.from_user.id == ADMIN_ID) & (~F.text.lower().startswith("казнить всех")))
async def admin_execute_debtor(message: types.Message):
    target_id = await get_target_id(message)
    if not target_id: return await message.reply("⚠️ Объект не найден.")
    
    parts = message.text.split()
    # Если передали дни, берем их, иначе по умолчанию 3 дня
    days = int(parts[-1]) if len(parts) > 1 and parts[-1].isdigit() and parts[-1] != str(target_id) else 3
    
    ban_ts = int(time.time()) + (days * 86400)
    await update_user(target_id, balance=0, debt=0, debt_time=0, ban_until=ban_ts)
    await message.reply(f"💀 Игрок <code>{target_id}</code> казнен. Баланс обнулен, бан на <b>{days} дней</b>.", parse_mode="HTML")


# ==========================================
# 🛑 ШТРАФЫ
# ==========================================
@router.message((F.text.lower().startswith("штраф")) & (~F.text.lower().startswith("штраф всем")))
async def admin_add_debt(message: types.Message):
    user_id = message.from_user.id
    if not is_moderator(user_id):
        return

    parts = message.text.split()
    target_id = await get_target_id(message)
    if not target_id or len(parts) < 2: return await message.reply("⚠️ Формат: `штраф [ID] [сумма]`")
        
    # 🔥 ЗАЩИТА АРХИТЕКТОРА 🔥
    if target_id == ADMIN_ID and user_id != ADMIN_ID:
        return await message.reply("🤡 Выписать штраф Архитектору? Система смеется над тобой.")

    amount_str = parts[-1].replace('к', '000').replace('k', '000').replace('м', '000000')
    if not amount_str.isdigit(): return await message.reply("❌ Сумма указана неверно.")
    amount = int(amount_str)
    
    user_data = await get_user_data(target_id)
    new_debt = user_data.get('debt', 0) + amount
    deadline = user_data.get('debt_time', 0)
    if deadline == 0: deadline = int(time.time()) + 86400 
        
    await update_user(target_id, debt=new_debt, debt_time=deadline)
    await message.reply(f"📈 Игроку <code>{target_id}</code> впаян штраф {fmt(amount)} UMBREL.\nОбщий долг: {fmt(new_debt)} UMBREL", parse_mode="HTML")


@router.message((F.text.lower().startswith("срок")) & (F.from_user.id == ADMIN_ID))
async def admin_change_deadline(message: types.Message):
    parts = message.text.split()
    target_id = await get_target_id(message)
    if not target_id or len(parts) < 2 or not parts[-1].isdigit(): 
        return await message.reply("⚠️ Формат: `срок [ID] [часы]`")
    
    hours = int(parts[-1])
    new_deadline = int(time.time()) + (hours * 3600)
    await update_user(target_id, debt_time=new_deadline)
    await message.reply(f"⏳ Для <code>{target_id}</code> установлен новый дедлайн: через <b>{hours} часов</b>.", parse_mode="HTML")


@router.message((F.text.lower() == "список должников") & (F.from_user.id == ADMIN_ID))
async def admin_list_debtors(message: types.Message):
    debtors = await get_overdue_users()
    if not debtors: return await message.reply("🏙 В городе спокойно. Должников нет.")
    text = "🕵️ <b>ОПЕРАТИВНАЯ СВОДКА (Кандидаты на бан):</b>\n" + "".join([f"• <code>{d['id']}</code>\n" for d in debtors])
    await message.reply(text, parse_mode="HTML")


# ==========================================
# 🌍 МАССОВЫЕ КОМАНДЫ ПРАВОСУДИЯ
# ==========================================

@router.message((F.text.lower() == "простить всех") & (F.from_user.id == ADMIN_ID))
async def admin_mass_forgive(message: types.Message):
    affected = await mass_forgive_all()
    await message.reply(f"🕊 <b>КРЕДИТНАЯ АМНИСТИЯ!</b>\nКоннор сжёг все долговые расписки. Прощено должников: <b>{affected}</b>", parse_mode="HTML")


@router.message((F.text.lower() == "разбан всех") & (F.from_user.id == ADMIN_ID))
async def admin_mass_unban(message: types.Message):
    affected = await mass_unban_all()
    await message.reply(f"☀️ <b>ДВЕРИ ОТКРЫТЫ!</b>\nВсе забаненные выпущены на свободу. Разблокировано: <b>{affected}</b>", parse_mode="HTML")


@router.message((F.text.lower().startswith("штраф всем")) & (F.from_user.id == ADMIN_ID))
async def admin_mass_fine(message: types.Message):
    parts = message.text.split()
    if len(parts) < 3: return await message.reply("⚠️ Формат: `штраф всем [сумма]`")
    amount_str = parts[-1].replace('к', '000').replace('k', '000').replace('м', '000000')
    if not amount_str.isdigit(): return await message.reply("❌ Неверный формат суммы")
    
    amount = int(amount_str)
    affected = await mass_fine_debtors(amount)
    await message.reply(f"💸 <b>ГЛОБАЛЬНАЯ ИНФЛЯЦИЯ!</b>\nВсем должникам накинут штраф <b>{fmt(amount)}</b> ᴜ.\nПострадало: <b>{affected}</b>", parse_mode="HTML")


@router.message((F.text.lower().startswith("казнить всех")) & (F.from_user.id == ADMIN_ID))
async def admin_mass_execute(message: types.Message):
    parts = message.text.split()
    days = int(parts[-1]) if len(parts) > 2 and parts[-1].isdigit() else 3
    ban_ts = int(time.time()) + (days * 86400)
    victims_count = await mass_execute_all(ban_ts)
    await message.reply(f"🔥 <b>ОРДЕР 66 ВЫПОЛНЕН.</b>\nЗабанено на {days} дней должников: <b>{victims_count}</b>", parse_mode="HTML")


# ==========================================
# 🔐 СИСТЕМА ДОСТУПОВ (RBAC)
# ==========================================
ADMIN_ID = int(os.getenv("ADMIN_ID", 1412940726))
# Парсим список модераторов из .env (если он пуст, список будет пустым)
MODERATORS = [int(i) for i in os.getenv("MODERATOR_IDS", "").split(",") if i]

def is_moderator(user_id):
    return user_id == ADMIN_ID or user_id in MODERATORS

# ==========================================
# 🛑 БАНЫ И СБРОСЫ (УПРАВЛЕНИЕ УЧЕТКАМИ)
# ==========================================

@router.message(F.text.lower().startswith(("бан", "забанить")))
async def admin_global_ban(message: types.Message):
    user_id = message.from_user.id
    # Проверяем, есть ли права модератора
    if not is_moderator(user_id):
        return

    target_id = await get_target_id(message)
    if not target_id: 
        return await message.reply("⚠️ Объект не найден.")
    
    # 🔥 АБСОЛЮТНАЯ ЗАЩИТА АРХИТЕКТОРА 🔥
    if target_id == ADMIN_ID:
        return await message.reply("🤡 <b>В доступе отказано:</b> Попытка заблокировать Владельца.", parse_mode="HTML")
    
    parts = message.text.split()
    days = 7
    # Логика парсинга дней и причины
    idx = 2 if len(parts) > 1 and parts[1].isdigit() else 1
    if len(parts) > idx and parts[idx].isdigit():
        days = int(parts[idx])
        idx += 1
    reason = " ".join(parts[idx:]).strip()
    
    await update_user(target_id, ban_until=int(time.time()) + days * 86400)
    
    # Динамическая подпись (кто именно выдал бан)
    executor = "Архитектором" if user_id == ADMIN_ID else f"Модератором {message.from_user.first_name}"
    
    await message.reply(
        f"🚫 Игрок <code>{target_id}</code> забанен на {days} дн. {executor}.\n"
        f"Причина: {reason or 'не указана'}", 
        parse_mode="HTML"
    )

@router.message(F.text.lower().startswith("разбан "))
async def admin_universal_unban(message: types.Message):
    # Разбан — только для Архитектора (Модераторы не могут снимать баны)
    if message.from_user.id != ADMIN_ID:
        return

    raw_args = message.text.strip().split()
    if len(raw_args) < 2:
        return await message.reply("⚠️ Укажи цель: <code>разбан @юзер</code>", parse_mode="HTML")

    target_str = raw_args[1]
    target_id = await resolve_user_id(target_str)
    if not target_id:
        return await message.reply("❌ Игрок не найден.")

    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE users SET ban_until = 0, debt = 0, debt_time = 0 WHERE user_id = $1", 
            target_id
        )
    
    # Очистка кэша мидлвейера (иначе бот будет отшибать его еще некоторое время)
    try:
        from core.middlewares import ban_cache
        if target_id in ban_cache:
            del ban_cache[target_id]
    except Exception as e:
        print(f"⚠️ Не удалось очистить кэш бана: {e}")

    await message.reply(f"🕊 <b>АМНИСТИЯ</b>\nИгрок <b>{target_str}</b> полностью разбанен, а его долги обнулены. Палач отозван.", parse_mode="HTML")


@router.message((F.text.lower().startswith("сброс")) & (~F.text.lower().startswith("сброс теста")) & (F.from_user.id == ADMIN_ID))
async def admin_reset_everything(message: types.Message):
    target_id = await get_target_id(message)
    if target_id:
        await update_user(target_id, debt=0, debt_time=0, ban_until=0)
        await message.reply(f"🧹 <b>ПОЛНАЯ ОЧИСТКА:</b> Долги и баны игрока <code>{target_id}</code> аннулированы.", parse_mode="HTML")
    else:
        await message.reply("⚠️ Объект не найден.")


@router.message(F.text.lower().startswith("сброс теста") & (F.from_user.id == ADMIN_ID))
async def admin_reset_exam(message: types.Message):
    target_id = await get_target_id(message)
    if not target_id: return await message.reply("⚠️ Объект не найден.")
    
    pool = await get_db()
    async with pool.acquire() as db:
        # Устанавливаем стартовый рейтинг для повторного прохождения
        await db.execute("UPDATE user_rating SET exam_passed = 0, rating_points = 2500 WHERE user_id = $1", target_id)
    await message.reply(f"🔧 Экзамен для <code>{target_id}</code> успешно сброшен. Агент может пройти тестирование заново.", parse_mode="HTML")