import os
import time
import html
import json
import logging
from aiogram import Router, F, types
from aiogram.types import LabeledPrice, PreCheckoutQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Импортируем пул соединений и функции баланса
from core.database import get_db, add_balance

router = Router()
ADMIN_ID = 1412940726

def fmt(num):
    return f"{int(num):,}".replace(",", " ")

# ==========================================
# 💎 ИНИЦИАЛИЗАЦИЯ БАЗЫ ПЛАТЕЖЕЙ (АНТИ-ДЮП)
# ==========================================
async def init_donate_db():
    pool = await get_db()
    async with pool.acquire() as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS processed_payments (
                charge_id TEXT PRIMARY KEY,
                user_id BIGINT,
                pack_id TEXT,
                timestamp BIGINT
            )
        ''')

# ==========================================
# FSM Состояния для свободного доната
# ==========================================
class DonateStates(StatesGroup):
    waiting_for_stars_amount = State()

# ==========================================
# 💎 РАСШИРЕННЫЙ КОНФИГ ПАКЕТОВ (РЕБАЛАНС 2026)
# ==========================================
# Базовая ставка урезана до: 1 ⭐️ = 20 000 ᴜ (было 30 000 ᴜ)
DONATE_PACKS = {
    "pack_1": {"type": "currency", "stars": 15, "umbrel": 300_000},
    "pack_2": {"type": "currency", "stars": 25, "umbrel": 750_000},   # Повысили
    "pack_3": {"type": "currency", "stars": 50, "umbrel": 2_000_000}, # Повысили
    "pack_4": {"type": "currency", "stars": 150, "umbrel": 8_000_000}, # Повысили
    "pack_5": {"type": "currency", "stars": 500, "umbrel": 40_000_000}, # Повысили
    "pack_6": {"type": "currency", "stars": 1000, "umbrel": 120_000_000}, # Повысили
    "pack_7": {"type": "currency", "stars": 2500, "umbrel": 500_000_000}, # Ровно 500 лямов! 🔥
    
    # VIP пакеты
    "vip_30": {"type": "vip", "stars": 150, "days": 30},
    "vip_inf": {"type": "vip", "stars": 1000, "days": 36500}
}

# ==========================================
# 🎨 БЕЗОПАСНЫЙ СЛОВАРЬ ДЕФОЛТОВ (ДЛЯ ФОЛБЕКА)
# ==========================================
FALLBACK_STRINGS = {
    "dn_menu_body": "💎 <b>Инвестиционный Терминал</b>\n════════════════════\n<i>Поддержка проекта: @umbreliana_support_bot.</i>\n\nДоступные пакеты инвестиций:",
    "dn_btn_free": "💖 Поддержать проект (Любая сумма)",
    "dn_free_prompt": "💖 <b>Спасибо за желание поддержать проект!</b>\n\nНапишите цифрой количество ⭐️ Telegram Stars, которое вы хотите пожертвовать (минимум 1).\n\n<i>Для отмены напишите 'отмена'.</i>",
    "dn_free_cancelled": "Действие отменено.",
    "dn_free_err_zero": "Сумма должна быть больше нуля. Введите число еще раз или 'отмена'.",
    "dn_free_err_max": "Слишком большая сумма за раз. Введите число поменьше.",
    "dn_free_err_nan": "Пожалуйста, введите только целое число (например, 50).",
    "dn_pack_not_found": "❌ Пакет не найден!",
    "dn_perks_sovereign": "👑 <b>Элитный статус: VIP-суверен</b>\n━━━━━━━━━━━━━━━━━━━━\nЭто не просто лицензия. Это ультимативная власть над рынком и легальный чит-код для тех, кто хочет возвышаться над остальными.\n\n<b>Привилегии Суверена:</b>\n1. Доступ к закрытым командам чек [@ник] и чек ферма [ID].\n2. Доступ к Золотой коллекции GPU (те же видеокарты, но -20% цена, +20% доход).\n3. Роскошная графическая панель фермы и элитный именной чек.\n4. Ежедневный бонус увеличен до 300 000 ᴜ.\n5. 100% защита от хакерских атак (команда напасть).\n6. Эксклюзивный дизайн профиля.\n\n🛒 Тариф: <b>{name}</b>",
    "dn_btn_pay_stars": "💳 Оплатить {stars} ⭐️",
    "dn_invoice_title": "Инвестиции в Umbreliana",
    "dn_invoice_desc_currency": "Покупка {amount} UMBREL на твой счет.",
    "dn_invoice_desc_vip": "Приобретение: {name}.",
    "dn_invoice_desc_default": "Инвестиции в Umbreliana.",
    "dn_free_invoice_title": "Поддержка Umbreliana",
    "dn_free_invoice_desc": "Добровольное пожертвование в размере {stars} ⭐️ на развитие проекта. Наград не предусмотрено, только безмерная благодарность Архитектора.",
    "dn_precheckout_err_session": "Ошибка платежной сессии.",
    "dn_precheckout_err_corrupted": "Поврежденные данные платежа.",
    "dn_precheckout_err_mismatch": "Сумма не совпадает.",
    "dn_precheckout_err_missing_pack": "Пакет больше не существует.",
    "dn_deliver_tip_reward": "💖 Архитектор лично благодарит вас за пожертвование в размере <b>{stars} ⭐️</b>. Ваш вклад помогает сети жить.",
    "dn_deliver_tip_log": "Безвозмездное пожертвование (Чаевые)",
    "dn_deliver_tip_pack_name": "Добровольная поддержка",
    "dn_deliver_currency_reward": "На твой счет зачислено <b>{amount} ᴜ</b>.",
    "dn_deliver_currency_log": "{amount} ᴜ",
    "dn_deliver_vip_reward": "👑 Тебе присвоен элитный статус <b>СУВЕРЕН</b> на {days} дней!\nОткрой профиль, чтобы получить новую карту.",
    "dn_deliver_vip_log": "Статус СУВЕРЕН ({days} дн)",
    "dn_success_body": "🎉 <b>ТРАНЗАКЦИЯ УСПЕШНА!</b>\n════════════════════\nКоннор подтвердил получение <b>{stars} ⭐️</b>.\n{reward_text}\n\n<i>Теневой банк благодарит за сотрудничество.</i>",
    "dn_admin_log": "🔔 <b>УСПЕШНАЯ ИНВЕСТИЦИЯ!</b>\n════════════════════\n👤 Агент: <a href='tg://user?id={user_id}'>{name}</a>\n🆔 ID: <code>{user_id}</code>\n💬 Тэг: {username}\n\n📦 Пакет: <b>{pack_name}</b>\n⭐️ Прибыль: <b>+{stars} ⭐️</b>\n💎 Выдано: <b>{reward}</b>\n🧾 Чек: <code>{charge_id}</code>\n════════════════════\n<i>Касса пополнена, Босс.</i>",
    "dn_test_hint": "⚠️ Формат: <code>тест донат [номер]</code>\nПример: <code>тест донат 1</code> или <code>тест донат 7</code>",
    "dn_pack_name_pack_1": "15 ⭐️ — 300 000 ᴜ",
    "dn_pack_name_pack_2": "25 ⭐️ — 600 000 ᴜ (+20%)",
    "dn_pack_name_pack_3": "50 ⭐️ — 1 500 000 ᴜ (+50%)",
    "dn_pack_name_pack_4": "150 ⭐️ — 5 000 000 ᴜ (+66%)",
    "dn_pack_name_pack_5": "500 ⭐️ — 20 000 000 ᴜ (+100%)",
    "dn_pack_name_pack_6": "1000 ⭐️ — 50 000 000 ᴜ (+150%)",
    "dn_pack_name_pack_7": "2500 ⭐️ — 150 000 000 ᴜ (+200%)",
    "dn_pack_name_vip_30": "👑 VIP-суверен (30 дней) — 150 ⭐️",
    "dn_pack_name_vip_inf": "👑 VIP-суверен (НАВСЕГДА) — 1000 ⭐️"
}

def get_str(key: str, _=None, **kwargs) -> str:
    if _:
        return _(key, **kwargs)
    text = FALLBACK_STRINGS.get(key, key)
    if kwargs:
        try: return text.format(**kwargs)
        except: pass
    return text

# ==========================================
# 🛒 МЕНЮ ПОКУПКИ
# ==========================================
@router.message(F.text.lower().in_(["донат", "купить амбрел", "купить амбрелы", "пополнить", "💎 донат", "donate", "buy umbrel", "topup", "💎 donate"]))
async def cmd_donate_menu(message: types.Message, _=None):
    text = get_str("dn_menu_body", _)
    builder = InlineKeyboardBuilder()
    
    for pack_id in DONATE_PACKS.keys():
        localized_pack_name = get_str(f"dn_pack_name_{pack_id}", _)
        builder.button(text=localized_pack_name, callback_data=f"buyxtr:{pack_id}")
    
    builder.button(text=get_str("dn_btn_free", _), callback_data="buyxtr:free_donate")
    builder.adjust(1) 
    await message.reply(text, reply_markup=builder.as_markup(), parse_mode="HTML")

# ==========================================
# 🧾 ГЕНЕРАЦИЯ СЧЕТА (INVOICE)
# ==========================================
@router.callback_query(F.data.startswith("buyxtr:"))
async def process_buy_stars(callback: types.CallbackQuery, state: FSMContext, _=None):
    parts = callback.data.split(":")
    pack_id = parts[1]

    if pack_id == "free_donate":
        await callback.answer()
        msg = await callback.message.answer(get_str("dn_free_prompt", _), parse_mode="HTML")
        await state.set_state(DonateStates.waiting_for_stars_amount)
        await state.update_data(prompt_msg_id=msg.message_id)
        return

    pack = DONATE_PACKS.get(pack_id)
    if not pack:
        return await callback.answer(get_str("dn_pack_not_found", _), show_alert=True)

    localized_name = get_str(f"dn_pack_name_{pack_id}", _)

    # Предосмотр VIP привилегий перед биллингом
    if pack['type'] == 'vip' and len(parts) < 3:
        await callback.answer()
        perks_text = get_str("dn_perks_sovereign", _, name=localized_name)
        
        builder = InlineKeyboardBuilder()
        builder.button(text=get_str("dn_btn_pay_stars", _, stars=pack['stars']), callback_data=f"buyxtr:{pack_id}:pay")
        return await callback.message.answer(perks_text, reply_markup=builder.as_markup(), parse_mode="HTML")

    await callback.answer()
    prices = [LabeledPrice(label=get_str("dn_invoice_title", _), amount=pack['stars'])]

    if pack['type'] == 'currency':
        desc = get_str("dn_invoice_desc_currency", _, amount=fmt(pack['umbrel']))
    elif pack['type'] == 'vip':
        desc = get_str("dn_invoice_desc_vip", _, name=localized_name)
    else:
        desc = get_str("dn_invoice_desc_default", _)

    await callback.message.answer_invoice(
        title=get_str("dn_invoice_title", _),
        description=desc,
        payload=f"donate:{pack_id}:{callback.from_user.id}", 
        provider_token="", 
        currency="XTR",    
        prices=prices
    )

# ==========================================
# ⌨️ ОБРАБОТЧИК ВВОДА СУММЫ СВОБОДНОГО ДОНАТА
# ==========================================
@router.message(DonateStates.waiting_for_stars_amount)
async def process_free_donate_amount(message: types.Message, state: FSMContext, _=None):
    if message.text.lower().strip() in ['отмена', 'cancel', 'назад', 'back']:
        await state.clear()
        return await message.reply(get_str("dn_free_cancelled", _))

    try:
        stars_amount = int(message.text.strip())
        if stars_amount <= 0:
            return await message.reply(get_str("dn_free_err_zero", _))
        if stars_amount > 100000:
            return await message.reply(get_str("dn_free_err_max", _))
    except ValueError:
        return await message.reply(get_str("dn_free_err_nan", _))

    await state.clear()
    prices = [LabeledPrice(label=get_str("dn_free_invoice_title", _), amount=stars_amount)]
    
    await message.answer_invoice(
        title=get_str("dn_free_invoice_title", _),
        description=get_str("dn_free_invoice_desc", _, stars=stars_amount),
        payload=f"donate:tip_{stars_amount}:{message.from_user.id}", 
        provider_token="", 
        currency="XTR",    
        prices=prices
    )

# ==========================================
# 🛡 ПРОВЕРКА ПЕРЕД ОПЛАТОЙ (PRE-CHECKOUT)
# ==========================================
@router.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    payload = pre_checkout_query.invoice_payload
    
    # Пул транслейторов для пре-чекаута
    pool = await get_db()
    async with pool.acquire() as db:
        u_lang = await db.fetchval("SELECT lang FROM users WHERE user_id = $1", pre_checkout_query.from_user.id) or "ru"
    _ = get_translator(u_lang)

    if not payload.startswith("donate:"):
        return await pre_checkout_query.answer(ok=False, error_message=get_str("dn_precheckout_err_session", _))
        
    parts = payload.split(":")
    if len(parts) != 3:
        return await pre_checkout_query.answer(ok=False, error_message=get_str("dn_precheckout_err_corrupted", _))
        
    pack_id = parts[1]
    
    if pack_id.startswith("tip_"):
        try:
            expected_stars = int(pack_id.split("_")[1])
            if pre_checkout_query.total_amount != expected_stars:
                return await pre_checkout_query.answer(ok=False, error_message=get_str("dn_precheckout_err_mismatch", _))
        except ValueError:
            return await pre_checkout_query.answer(ok=False, error_message=get_str("dn_precheckout_err_corrupted", _))
    else:
        if pack_id not in DONATE_PACKS:
            return await pre_checkout_query.answer(ok=False, error_message=get_str("dn_precheckout_err_missing_pack", _))
            
        expected_stars = DONATE_PACKS[pack_id]['stars']
        if pre_checkout_query.total_amount != expected_stars:
             return await pre_checkout_query.answer(ok=False, error_message=get_str("dn_precheckout_err_mismatch", _))

    await pre_checkout_query.answer(ok=True)

# ==========================================
# 🏆 ЕДИНАЯ ФУНКЦИЯ ВЫДАЧИ 
# ==========================================
async def deliver_donate_reward(message: types.Message, user_id: int, pack_id: str, charge_id: str, paid_stars: int):
    pool = await get_db()
    async with pool.acquire() as db:
        u_lang = await db.fetchval("SELECT lang FROM users WHERE user_id = $1", user_id) or "ru"
    _ = get_translator(u_lang)

    # 1. ЗАПИСЬ ЧЕКА В БАЗУ (АНТИ-ДЮП)
    try:
        async with pool.acquire() as db:
            result = await db.execute(
                "INSERT INTO processed_payments (charge_id, user_id, pack_id, timestamp) VALUES ($1, $2, $3, $4) ON CONFLICT(charge_id) DO NOTHING",
                charge_id, user_id, pack_id, int(time.time())
            )
            if result == "INSERT 0 0":
                print(f"⚠️ Дубль платежа заблокирован: {charge_id}")
                return 
    except Exception as e:
        logging.exception(f"❌ Критическая ошибка БД при обработке платежа {charge_id}: {e}")
        try: await message.bot.send_message(chat_id=ADMIN_ID, text=f"🆘 <b>АВАРИЯ БАЗЫ ДАННЫХ ПРИ ДОНАТЕ!</b>\nИгрок {user_id} оплатил {paid_stars} звезд, но база у пала.\nЧек: <code>{charge_id}</code>", parse_mode="HTML")
        except: pass
        return 

    reward_text = ""
    log_reward = ""
    pack_name = ""

    # 2. ЕСЛИ ЭТО СВОБОДНЫЙ ДОНАТ (ЧАЕВЫЕ)
    if pack_id.startswith("tip_"):
        reward_text = get_str("dn_deliver_tip_reward", _, stars=paid_stars)
        log_reward = get_str("dn_deliver_tip_log", _)
        pack_name = get_str("dn_deliver_tip_pack_name", _)
        
    # 3. ЕСЛИ ЭТО СТАНДАРТНЫЙ ПАКЕТ
    else:
        pack = DONATE_PACKS.get(pack_id)
        if not pack: return 
        pack_name = get_str(f"dn_pack_name_{pack_id}", _)
        
        try:
            if pack['type'] == 'currency':
                await add_balance(user_id, pack['umbrel'])
                reward_text = get_str("dn_deliver_currency_reward", _, amount=fmt(pack['umbrel']))
                log_reward = get_str("dn_deliver_currency_log", _, amount=fmt(pack['umbrel']))
            elif pack['type'] == 'vip':
                async with pool.acquire() as db:
                    expire_ts = int(time.time()) + (pack['days'] * 86400)
                    await db.execute('''
                        INSERT INTO user_statuses (user_id, status_id, expire_timestamp) 
                        VALUES ($1, $2, $3)
                        ON CONFLICT (user_id, status_id) 
                        DO UPDATE SET expire_timestamp = GREATEST(user_statuses.expire_timestamp, $4) + $5
                    ''', user_id, 777, expire_ts, int(time.time()), pack['days'] * 86400)
                reward_text = get_str("dn_deliver_vip_reward", _, days=pack['days'])
                log_reward = get_str("dn_deliver_vip_log", _, days=pack['days'])
        except Exception as e:
            logging.exception(f"❌ Ошибка add_balance/status при донате: {e}")
            await message.bot.send_message(chat_id=ADMIN_ID, text=f"🆘 Ошибка выдачи награды! Игрок {user_id} оплатил {paid_stars} звезд. ВЫДАЙ ВРУЧНУЮ!\nЧек: <code>{charge_id}</code>", parse_mode="HTML")
            return

    # 4. УВЕДОМЛЕНИЕ ИГРОКУ
    success_text = get_str("dn_success_body", _, stars=paid_stars, reward_text=reward_text)
    
    if charge_id.startswith("TEST_"):
        await message.reply(f"🔧 <b>СИМУЛЯЦИЯ:</b>\n{success_text}", parse_mode="HTML")
    else:
        await message.reply(success_text, parse_mode="HTML")

    # 5. СЕКРЕТНОЕ УВЕДОМЛЕНИЕ АДМИНУ
    try:
        username = f"@{message.from_user.username}" if message.from_user.username else "Скрыт"
        safe_name = html.escape(message.from_user.first_name)
        
        admin_text = get_str("dn_admin_log", _, user_id=user_id, name=safe_name, username=username, pack_name=pack_name, stars=paid_stars, reward=log_reward, charge_id=charge_id)
        await message.bot.send_message(chat_id=ADMIN_ID, text=admin_text, parse_mode="HTML")
    except Exception as e:
        print(f"Ошибка отправки уведомления админу: {e}")


# ==========================================
# ✅ УСПЕШНАЯ ОПЛАТА ОТ TELEGRAM
# ==========================================
@router.message(F.successful_payment)
async def successful_payment_handler(message: types.Message):
    payment_info = message.successful_payment
    payload = payment_info.invoice_payload
    charge_id = payment_info.telegram_payment_charge_id
    
    print(f"💰 ПОЛУЧЕН ПЛАТЕЖ: payload={payload}, stars={payment_info.total_amount}")
    
    if not payload.startswith("donate:"): return
    parts = payload.split(":")
    if len(parts) != 3: return

    pack_id = parts[1]
    try: 
        payload_user_id = int(parts[2])
    except ValueError: return
        
    user_id = message.from_user.id
    paid_stars = payment_info.total_amount
    
    if not pack_id.startswith("tip_"):
        pack = DONATE_PACKS.get(pack_id)
        if not pack: return 
        if int(paid_stars) != int(pack['stars']): return

    print(f"✅ Платёж валиден. Запускаю выдачу награды для {user_id}...")
    await deliver_donate_reward(message, user_id, pack_id, charge_id, paid_stars)


# ==========================================
# 🔧 БЭКДОР ДЛЯ АДМИНА (ТЕСТИРОВАНИЕ ДОНАТА)
# ==========================================
@router.message(F.text.lower().startswith(("тест донат", "test donate")) & (F.from_user.id == ADMIN_ID))
async def admin_test_donate(message: types.Message, _=None):
    parts = message.text.lower().split()
    if len(parts) < 3:
        return await message.reply(get_str("dn_test_hint", _), parse_mode="HTML")
        
    arg = parts[2]
    pack_mapping = {
        "1": "pack_1", "2": "pack_2", "3": "pack_3",
        "4": "pack_4", "5": "pack_5", "6": "pack_6",
        "7": "pack_7", "8": "vip_30", "9": "vip_inf"
    }
    
    pack_id = pack_mapping.get(arg, arg)
    pack = DONATE_PACKS.get(pack_id)
    
    if not pack:
        return await message.reply(f"❌ Пакет не найден!\nИспользуй цифры <b>от 1 до 9</b>.", parse_mode="HTML")

    user_id = message.from_user.id
    fake_charge_id = f"TEST_CHARGE_{int(time.time())}"
    paid_stars = pack['stars'] 

    await deliver_donate_reward(message, user_id, pack_id, fake_charge_id, paid_stars)


# LOCAL РАСПРЕДЕЛИТЕЛЬ ДЛЯ АСИНХРОННЫХ СЕССИЙ ТРАНЗАКЦИЙ
LOCALES = {}
for l in ["ru", "en"]:
    p = f"locales/{l}.json"
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f: LOCALES[l] = json.load(f)

def get_translator(lang: str):
    t_lang = lang if lang in LOCALES else "ru"
    def translate(key: str, **kwargs) -> str:
        text = LOCALES[t_lang].get(key, LOCALES["ru"].get(key, key))
        if kwargs:
            try: return text.format(**kwargs)
            except: pass
        return text
    return translate