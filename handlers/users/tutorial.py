import random
from aiogram import Router, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from core.database import add_balance, get_db
from handlers.syndicate.farms import update_farm, get_farm

router = Router()

def fmt(num):
    return f"{int(num):,}".replace(",", " ")

def get_skip_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="⏭ Пропустить симуляцию", callback_data="tut_skip")
    return builder

# ==========================================
# 🎓 СТАРТ: ВВЕДЕНИЕ
# ==========================================
@router.callback_query(F.data == "tut_start")
async def tut_start(callback: types.CallbackQuery):
    text = (
        "🎓 <b>АКАДЕМИЯ СИНДИКАТА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Никаких нудных лекций. Мы подключили терминал напрямую к твоим базам данных.\n\n"
        "Для начала системе нужно проанализировать, кто ты в этой сети. Твои активы, статус и долги отслеживаются в досье.\n\n"
        "👉 <b>Твоя задача:</b> Нажми на команду ниже, чтобы запросить реальные данные профиля."
    )
    kb = get_skip_kb()
    kb.row(types.InlineKeyboardButton(text="💻 >_ профиль", callback_data="tut_sim_profile"))
    
    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

# ==========================================
# 💻 ПРАКТИКА 1: ПРОФИЛЬ -> ФЕРМА (С ПРОВЕРКОЙ ВЕТЕРАНА)
# ==========================================
@router.callback_query(F.data == "tut_sim_profile")
async def tut_sim_profile(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    pool = await get_db()
    
    async with pool.acquire() as db:
        user_data = await db.fetchrow("SELECT balance, total_bets, total_messages FROM users WHERE user_id = $1", user_id)
        total_gpus = await db.fetchval("SELECT SUM(qty) FROM gpu_batches WHERE user_id = $1", user_id) or 0
    
    farm_data = await get_farm(user_id)
    umc_balance = farm_data.get('umc_balance', 0)
    
    balance = user_data['balance'] if user_data else 0
    total_bets = user_data['total_bets'] if user_data else 0
    total_msgs = user_data['total_messages'] if user_data else 0

    # 🕵️‍♂️ ПРОВЕРКА НА ВЕТЕРАНА
    is_veteran = (balance > 150000) or (total_bets > 5) or (total_gpus > 0) or (total_msgs > 50)
    
    veteran_remark = ""
    if is_veteran:
        phrases = [
            "Погоди-ка... судя по логам, ты тут уже давно. Играл всё это время без инструктажа? Ну ты даёшь.",
            "Стоп. У тебя на счету уже приличные активы. Ты что, с пелёнок умеешь торговать на Теневом рынке? Ладно, продолжаем для галочки.",
            "Анализ досье завершён... Эм, ты уже матёрый Агент. Решил пройти академию ради халявной карточки? Уважаю.",
            "Система в замешательстве. Твоя статистика говорит, что ты явно не новичок. Проверяешь, как работает обучение?",
            "Хах, Архитектор будет смеяться. У тебя уже крутится бизнес, а ты только сейчас открыл базовый туториал."
        ]
        veteran_remark = f"\n\n🤖 <b>КОННОР:</b> <i>«{random.choice(phrases)}»</i>\n"

    text = (
        f"💻 <code>>_ Выполнение: профиль...</code>\n"
        f"<i>[Реальные данные] Баланс: {fmt(balance)} ᴜ | Счёт UMC: {fmt(umc_balance)}</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━{veteran_remark}\n"
        f"✅ <b>ОТЛИЧНО!</b> Так ты всегда сможешь проверить свои ресурсы.\n\n"
        f"Теперь перейдем к заработку. Твой главный актив — это <b>Ферма</b>.\n"
        f"Она добывает не фиат, а криптовалюту <b>UmbrelCoin (UMC)</b>.\n\n"
        f"👉 <b>Твоя задача:</b> Запроси телеметрию своего оборудования."
    )
    kb = get_skip_kb()
    kb.row(types.InlineKeyboardButton(text="💻 >_ ферма", callback_data="tut_sim_farm"))
    
    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

# ==========================================
# 🏭 ПРАКТИКА 2: ФЕРМА -> СБОР
# ==========================================
@router.callback_query(F.data == "tut_sim_farm")
async def tut_sim_farm(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    pool = await get_db()
    async with pool.acquire() as db:
        total_gpus = await db.fetchval("SELECT SUM(qty) FROM gpu_batches WHERE user_id = $1", user_id) or 0

    status = "ONLINE 🟢" if total_gpus > 0 else "OFFLINE ⚪️ (Нет карт)"

    text = (
        f"💻 <code>>_ Выполнение: ферма...</code>\n"
        f"<i>[Реальные данные] Статус: {status} | Оборудования: {total_gpus} шт.</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ <b>ТЕРМИНАЛ ОТКРЫТ!</b> Здесь ты следишь за оборудованием и его температурами.\n\n"
        f"Хранилище фермы заполняется за 4 часа. Не будешь собирать крипту — карты будут работать вхолостую и просто перегреваться.\n\n"
        f"👉 <b>Твоя задача:</b> Изучи протокол инкассации."
    )
    kb = get_skip_kb()
    kb.row(types.InlineKeyboardButton(text="💻 >_ сбор", callback_data="tut_sim_collect"))
    
    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

# ==========================================
# ⚡ ПРАКТИКА 3: СБОР -> БИРЖА
# ==========================================
@router.callback_query(F.data == "tut_sim_collect")
async def tut_sim_collect(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    farm_data = await get_farm(user_id)
    umc_balance = farm_data.get('umc_balance', 0)

    text = (
        f"💻 <code>>_ Выполнение: сбор...</code>\n"
        f"<i>[Телеметрия] На твоём кошельке сейчас {fmt(umc_balance)} UMC.</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ <b>СБОР ИЗУЧЕН!</b>\n\n"
        f"🚨 <b>ВАЖНОЕ ПРАВИЛО:</b> За работу фермы нужно платить фиатом (ᴜ). Если при сборе у тебя не будет фиата на балансе, система автоматически продаст твою крипту со <b>штрафом 20%</b>, чтобы закрыть долг за электричество!\n\n"
        f"Богатые агенты не хранят фиат. Они скупают <b>Акции Синдиката</b>, чтобы получать еженедельные дивиденды.\n\n"
        f"👉 <b>Твоя задача:</b> Открой фондовую биржу."
    )
    kb = get_skip_kb()
    kb.row(types.InlineKeyboardButton(text="💻 >_ биржа", callback_data="tut_sim_exchange"))
    
    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

# ==========================================
# 📈 ПРАКТИКА 4: БИРЖА -> КЕЙСЫ
# ==========================================
@router.callback_query(F.data == "tut_sim_exchange")
async def tut_sim_exchange(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    pool = await get_db()
    async with pool.acquire() as db:
        shares = await db.fetchval("SELECT gold_balance FROM users WHERE user_id = $1", user_id) or 0
        
    text = (
        f"💻 <code>>_ Выполнение: биржа...</code>\n"
        f"<i>[Реальные данные] Твой портфель: {fmt(shares)} Акций Синдиката.</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ <b>БИРЖА ОТКРЫТА!</b> Здесь ты защищаешь капитал от инфляции.\n\n"
        f"Последний урок: <b>Черный Рынок Контейнеров</b>. Здесь можно сорвать джекпот и выбить флагманскую GPU в разы дешевле.\n"
        f"Во вкладке премиума лежат донат-кейсы за <b>Telegram Stars</b> с гарантированным дропом Золотого железа (даёт +20% к доходу).\n\n"
        f"👉 <b>Твоя задача:</b> Завершить инструктаж."
    )
    kb = get_skip_kb()
    kb.row(types.InlineKeyboardButton(text="💻 >_ кейсы (Финал)", callback_data="tut_sim_cases"))
    
    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

# ==========================================
# 🏆 ФИНАЛ: ВЫДАЧА НАГРАДЫ
# ==========================================
@router.callback_query(F.data == "tut_sim_cases")
async def tut_step_cases(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    pool = await get_db()
    async with pool.acquire() as db:
        res = await db.execute("""
            UPDATE users 
            SET tutorial_passed = TRUE 
            WHERE user_id = $1 AND (tutorial_passed IS NULL OR tutorial_passed = FALSE)
        """, user_id) # 👈 ВОТ ОН, ЖИЗНЕННО ВАЖНЫЙ АРГУМЕНТ
        
        # Защита от двойного получения (если UPDATE вернул 0 строк)
        if res == "UPDATE 0":
            return await callback.answer("🤡 Абуз не пройдет! Награда уже была получена.", show_alert=True)

        # Выдаем правильную стартовую карту: gpu_3 (GTX 750 Ti)
        await db.execute("""
            INSERT INTO gpu_batches (user_id, gpu_id, multiplier, qty, condition, was_repaired) 
            VALUES ($1, 'gpu_3', 1.0, 1, 100.0, 0)
        """, user_id)
    
    # Выдаем 50k фиата
    await add_balance(user_id, 50000)
    
    farm_data = await get_farm(user_id)
    await update_farm(user_id, gpu_3=farm_data.get('gpu_3', 0) + 1)
    
    text = (
        "🏆 <b>СИМУЛЯЦИЯ УСПЕШНО ЗАВЕРШЕНА!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Ты готов к выходу в реальную сеть. Твои стартовые гранты зачислены:\n\n"
        "💰 Баланс: <b>+50 000 ᴜ</b>\n"
        "🖥 Оборудование: <b>GTX 750 Ti (1 шт.)</b>\n\n"
        "Напиши <code>ферма</code>, чтобы увидеть своё железо в стойках. Удачи, Агент!"
    )
    await callback.message.edit_text(text, parse_mode="HTML")

# ==========================================
# ⏭ ПРОПУСК ОБУЧЕНИЯ (ОТКАЗ)
# ==========================================
@router.callback_query(F.data == "tut_skip")
async def tut_skip(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    pool = await get_db()
    async with pool.acquire() as db:
        res = await db.execute("""
            UPDATE users 
            SET tutorial_passed = TRUE 
            WHERE user_id = $1 AND (tutorial_passed IS NULL OR tutorial_passed = FALSE)
        """, user_id)
        
        if res == "UPDATE 0":
            return await callback.answer("🤡 Ты уже прошел или пропустил обучение!", show_alert=True)

    await add_balance(user_id, 10000)
    
    try: await callback.message.delete()
    except: pass

    await callback.message.answer(
        "⏭ <b>Боевая симуляция пропущена.</b>\n"
        "На счет зачислено <b>10 000 ᴜ</b> (Утешительный грант).\n\n"
        "<i>Если запутаешься — пиши <code>помощь</code>.</i>",
        parse_mode="HTML"
    )