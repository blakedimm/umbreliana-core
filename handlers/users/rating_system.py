import time
import asyncio
import random
import re
import math
from aiogram import Router, F, types
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.database import get_db, analyze_player_strategy, update_user_activity, get_balance, add_balance

router = Router()
ADMIN_ID = 1412940726

def fmt(num):
    return f"{int(num):,}".replace(",", " ")

async def change_rating(user_id: int, amount: int):
    """Меняет рейтинг игрока (в плюс или минус), не выходя за лимиты 0-5000"""
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute(
            """
            UPDATE user_rating 
            SET rating_points = GREATEST(0, LEAST(5000, rating_points + $1)) 
            WHERE user_id = $2
            """,
            amount, user_id
        )

# ==========================================
# 📊 МАТЕМАТИКА РАНГОВ (E1 -> A100)
# ==========================================
def get_rank_info(points):
    points = max(0, min(5000, points))
    if points >= 4000:
        letter = "A"
        sub_val = (points - 4000) // 10
    elif points >= 3000:
        letter = "B"
        sub_val = (points - 3000) // 10
    elif points >= 2000:
        letter = "C"
        sub_val = (points - 2000) // 10
    elif points >= 1000:
        letter = "D"
        sub_val = (points - 1000) // 10
    else:
        letter = "E"
        sub_val = points // 10
    
    # Исправление для границы А100
    sub_val = min(100, int(sub_val))
    return letter, sub_val

def get_rank_string(points):
    letter, val = get_rank_info(points)
    return f"{letter}{val}"

# ==========================================
# 📋 ВОПРОСЫ ЭКЗАМЕНА (С ПОДВОХАМИ)
# ==========================================
QUESTIONS = [
    {
        "q": "Как часто можно получать ежедневный бонус?",
        "options": ["А) Каждые 12 часов", "Б) Раз в сутки", "В) Каждые 6 часов", "Г) Неограниченно"],
        "correct": 1,  # Б) Раз в сутки
        "points": 100
    },
    {
        "q": "Что делает лицензия «Техник»?",
        "options": ["А) Удваивает доход фермы", "Б) Делает электричество бесплатным", "В) Убирает налог на прибыль", "Г) Защищает от пожара"],
        "correct": 1,  # Б) Делает электричество бесплатным
        "points": 150
    },
    {
        "q": "Что происходит с залогом (5%), если снять лот с Теневого рынка до продажи?",
        "options": ["А) Залог возвращается полностью", "Б) Залог сгорает безвозвратно", "В) Возвращается половина залога", "Г) Залог переходит покупателю"],
        "correct": 1,  # Б) Залог сгорает
        "points": 150
    },
    {
        "q": "Что случается с фермой, если температура превысила охлаждение (Тепло > Охлаждение)?",
        "options": ["А) Ферма отключается", "Б) Сгорает одна карта мгновенно", "В) Ускоряется износ и появляется шанс пожара при сборе", "Г) Налог на прибыль увеличивается вдвое"],
        "correct": 2,  # В) Ускоряется износ...
        "points": 150
    },
    {
        "q": "Какое наказание ждёт игрока, если он не вернул кредит в срок и у него на балансе 0?",
        "options": ["А) Баланс уходит в минус", "Б) Блокировка всех игр на 1-3 дня и обнуление долга", "В) Удаление аккаунта", "Г) Коллекторы забирают случайные видеокарты"],
        "correct": 1,  # Б) Блокировка...
        "points": 150
    },
    {
        "q": "Сколько раз можно отремонтировать одну и ту же видеокарту?",
        "options": ["А) Неограниченно", "Б) 2 раза", "В) Только 1 раз", "Г) 5 раз"],
        "correct": 2,  # В) Только 1 раз
        "points": 150
    },
    {
        "q": "Что делает глобальное событие «Вторжение ИИ»?",
        "options": ["А) Цены на рынке падают на 50%", "Б) Случайные 20% видеокарт всех игроков ломаются", "В) Налог на прибыль становится 100%", "Г) Все кланы теряют половину общака"],
        "correct": 1,  # Б) 20% карт ломаются
        "points": 200
    },
    {
        "q": "Может ли игрок со статусом «Архитектор Сети» быть взломан другими игроками?",
        "options": ["А) Да, если у взломщика шанс больше 50%", "Б) Нет, он неприкасаем", "В) Только босс клана может его взломать", "Г) Да, но штраф за взлом — 50% от баланса"],
        "correct": 1,  # Б) Нет, неприкасаем
        "points": 150
    },
    {
        "q": "Через какое время склад фермы переполняется и майнинг останавливается (без лицензий)?",
        "options": ["А) 1 час", "Б) 12 часов", "В) 4 часа", "Г) Не переполняется"],
        "correct": 2,  # В) 4 часа
        "points": 150
    },
    {
        "q": "Что происходит, если у клана недостаточно средств в общаке для оплаты аренды Империи при сборе?",
        "options": ["А) Аренда уходит в долг клану", "Б) Клан банкротится, все бизнесы Империи удаляются", "В) Бизнесы продолжают работать, но доход не начисляется", "Г) Недостающая сумма списывается с участников"],
        "correct": 1,  # Б) Банкротство и удаление бизнесов
        "points": 150
    }
]

class ExamFSM(StatesGroup):
    answering = State()

# ==========================================
# 🏁 ИНИЦИАЦИЯ ЭКЗАМЕНА (ГРУППА / ЛС)
# ==========================================
@router.message(F.text.lower() == "тестирование")
async def cmd_exam_start(message: types.Message):
    user_id = message.from_user.id
    
    pool = await get_db()
    async with pool.acquire() as db:
        passed = await db.fetchval("SELECT exam_passed FROM user_rating WHERE user_id = $1", user_id)
        if passed == 1:
            return await message.reply("🚫 <b>ОШИБКА ДОСТУПА.</b>\nКвалификация пройдена. Твой статус закреплен.")

    text = (
        "🧬 <b>СИСТЕМА СОЦИАЛЬНОГО РЕЙТИНГА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Добро пожаловать в систему оценки агентов Амбрелианы. "
        "Для получения полного доступа необходимо пройти квалификацию.\n\n"
        "📊 <b>КАК РАБОТАЕТ ОЦЕНКА:</b>\n"
        "Твой статус состоит из буквы (от <b>A</b> до <b>E</b>) и цифры (от <b>0</b> до <b>100</b>).\n"
        "• <b>A</b> — Высшая элита (Отлично)\n"
        "• <b>B</b> — Продвинутый (Выше среднего)\n"
        "• <b>C</b> — Гражданин (Средний)\n"
        "• <b>D</b> — Рискованный (Ниже среднего)\n"
        "• <b>E</b> — Угроза (Слабо)\n\n"
        "Изначально тебе выдается базовый уровень <b>C50</b>. Отвечая на 10 каверзных вопросов, ты будешь получать или терять баллы. Правильные ответы мы не покажем — только итоговый результат.\n\n"
        "После экзамена рейтинг становится <b>динамическим</b>: твоя стратегия заработка, победы и поражения будут двигать тебя вверх или вниз. А если исчезнешь из сети на пару дней — статус начнет падать.\n\n"
        "💎 <b>БОНУСЫ РАНГА А (Ежедневно):</b>\n"
        "└ <b>A100:</b> +100 000 ᴜ\n"
        "└ <b>A90 - A99:</b> +50 000 ᴜ\n"
        "└ <b>A0 - A89:</b> +30 000 ᴜ\n\n"
        "⚠️ <b>ВНИМАНИЕ:</b> Экзамен сдается <u>ОДИН РАЗ</u>.\n"
        "<i>Ты готов подтвердить свой уровень доступа?</i>"
    )
    
    builder = InlineKeyboardBuilder()
    if message.chat.type != "private":
        # Кнопка жестко ведет в ЛС бота по твоему юзернейму
        builder.button(text="🚀 НАЧАТЬ В ЛС", url="https://t.me/umbreliana_bot?start=exam")
    else:
        builder.button(text="🚀 ПОДТВЕРДИТЬ", callback_data="exam_confirm")
    
    await message.reply(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "exam_confirm")
async def exam_confirm(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("🔄 <i>Запуск зашифрованного канала...</i>", parse_mode="HTML")
    await asyncio.sleep(1)
    await state.set_state(ExamFSM.answering)
    await state.update_data(current_q=0, score=2500, wrong_answers=[]) 
    await send_exam_question(callback.message, 0)

async def send_exam_question(message: types.Message, q_index: int):
    q_data = QUESTIONS[q_index]
    builder = InlineKeyboardBuilder()
    opts = q_data['options'].copy()
    for i, opt in enumerate(opts):
        builder.button(text=opt, callback_data=f"ans_{i}")
    builder.adjust(1)
    await message.edit_text(f"<b>ВОПРОС #{q_index+1}/10</b>\n\n{q_data['q']}", reply_markup=builder.as_markup(), parse_mode="HTML")

# ==========================================
# 👤 КОМАНДА: ОБЩИЙ СТАТУС
# ==========================================

@router.message(F.text.lower().startswith("общий статус"))
async def cmd_show_rating(message: types.Message):
    target_id = message.from_user.id
    target_name = message.from_user.first_name

    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        target_name = message.reply_to_message.from_user.first_name
    else:
        parts = message.text.split()
        if len(parts) > 2 and parts[2].isdigit():
            target_id = int(parts[2])
            target_name = f"ID: {target_id}"

    # 1. Деградация (если давно не играл)
    await update_user_activity(target_id) 

    # 2. ИИ-Скан профиля
    strategy_modifier, verdict = await analyze_player_strategy(target_id)

    pool = await get_db()
    async with pool.acquire() as db:
        row = await db.fetchrow("SELECT rating_points, exam_passed FROM user_rating WHERE user_id = $1", target_id)

        if not row or row['exam_passed'] == 0:
            return await message.reply("⚠️ Пользователь не прошел <code>тестирование</code>.", parse_mode="HTML")

        base_points = row['rating_points']
        # Применяем вердикт ИИ к очкам (ограничиваем 0-5000)
        final_points = max(0, min(5000, base_points + strategy_modifier))
        
        if final_points != base_points:
            await db.execute("UPDATE user_rating SET rating_points = $1 WHERE user_id = $2", final_points, target_id)

    rank_str = get_rank_string(final_points)
    letter, val = get_rank_info(final_points)
    
    # 🔥 ДИНАМИЧЕСКИЙ ВИЗУАЛ ЗАВИСИМО ОТ РАНГА
    themes = {
        "A": {"title": "👑 [ ВЫСШАЯ ЭЛИТА ]", "fill": "🟪", "empty": "🤍", "frame": "✨"},
        "B": {"title": "🎖 [ ПРОДВИНУТЫЙ АГЕНТ ]", "fill": "🟦", "empty": "▫️", "frame": "💠"},
        "C": {"title": "🔰 [ ГРАЖДАНИН СЕТИ ]", "fill": "🟩", "empty": "▪️", "frame": "🔹"},
        "D": {"title": "⚠️ [ ГРУППА РИСКА ]", "fill": "🟨", "empty": "⬛️", "frame": "🔸"},
        "E": {"title": "☣️ [ КРИТИЧЕСКАЯ УГРОЗА ]", "fill": "🟥", "empty": "⬛️", "frame": "🩸"}
    }
    
    theme = themes.get(letter, themes["C"])

    # 🔥 УМНЫЙ ПРОГРЕСС-БАР
    # math.ceil гарантирует, что 3% даст 1 закрашенный кубик, а не 0
    filled_blocks = math.ceil(val / 10) if val > 0 else 0
    if val == 100: filled_blocks = 10
    
    empty_blocks = 10 - filled_blocks
    progress_bar = (theme["fill"] * filled_blocks) + (theme["empty"] * empty_blocks)
    
    bonus_text = ""
    if letter == "A":
        bonus = 100000 if val == 100 else (50000 if val >= 90 else 30000)
        bonus_text = f"\n{theme['frame']} Ежедневный грант: <b>{fmt(bonus)}</b> ᴜ"

    # Сборка красивого отчета
    await message.reply(
        f"{theme['title']}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Пользователь: <b>{target_name}</b>\n"
        f"🏆 Статус: <b>{rank_str}</b>\n"
        f"📈 Прогресс: [{progress_bar}] {val}%\n"
        f"🔹 Очки системы: <code>{final_points}</code> / 5000"
        f"{bonus_text}\n\n"
        f"👁‍🗨 <b>Вердикт:</b>\n"
        f"{verdict}",
        parse_mode="HTML"
    )

@router.callback_query(ExamFSM.answering, F.data.startswith("ans_"))
async def handle_answer(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    q_index, score = data['current_q'], data['score']
    wrong_answers = data.get('wrong_answers', []) # Достаем список ошибок
    
    ans_index = int(callback.data.split("_")[1])
    q_data = QUESTIONS[q_index]
    
    if ans_index == q_data['correct']:
        score += q_data['points']
    else:
        score -= 75
        # 🔥 ЗАПИСЫВАЕМ ОШИБКУ: какой вопрос и что ответил
        wrong_answers.append({
            "question": q_data['q'],
            "chosen": q_data['options'][ans_index],
            "correct": q_data['options'][q_data['correct']]
        })

    if q_index + 1 < len(QUESTIONS):
        # 🔥 ОБНОВЛЯЕМ ДАННЫЕ (включая список ошибок)
        await state.update_data(current_q=q_index+1, score=score, wrong_answers=wrong_answers)
        await send_exam_question(callback.message, q_index+1)
    else:
        # --- ФИНАЛ ТЕСТА ---
        rank = get_rank_string(score)
        user = callback.from_user
        
        # 1. Формируем отчет для Архитектора (Тёмы)
        report = (
            f"📨 <b>ОТЧЕТ ПО КАНДИДАТУ</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 Агент: <b>{user.first_name}</b> (ID: <code>{user.id}</code>)\n"
            f"🏆 Итоговый ранг: <b>{rank}</b> ({score} очков)\n\n"
        )
        
        if wrong_answers:
            report += "❌ <b>ДОПУЩЕННЫЕ ОШИБКИ:</b>\n"
            for i, w in enumerate(wrong_answers, 1):
                report += (
                    f"<b>{i}.</b> {w['question']}\n"
                    f"└ Ответил: <i>{w['chosen']}</i>\n"
                    f"└ Верно: <b>{w['correct']}</b>\n\n"
                )
        else:
            report += "🌟 <b>ИДЕАЛЬНЫЙ РЕЗУЛЬТАТ!</b> Ошибок нет.\n"

        # 2. Отправляем Коннору команду доставить отчет в твой ЛС
        try:
            await callback.bot.send_message(ADMIN_ID, report, parse_mode="HTML")
        except Exception as e:
            print(f"Ошибка отправки отчета админу: {e}")

        await state.clear()
        
        pool = await get_db()
        async with pool.acquire() as db:
            await db.execute("""
                INSERT INTO user_rating (user_id, rating_points, exam_passed, last_active) 
                VALUES ($1, $2, 1, $3)
                ON CONFLICT(user_id) DO UPDATE SET 
                    rating_points = EXCLUDED.rating_points, 
                    exam_passed = 1, 
                    last_active = EXCLUDED.last_active
            """, user.id, score, int(time.time()))

        await callback.message.edit_text(f"🏁 <b>ЭКЗАМЕН ОКОНЧЕН.</b>\nТвой начальный статус: <b>{rank}</b>\nРазвивайся или деградируй.", parse_mode="HTML")