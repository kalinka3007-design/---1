import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler, CommandHandler,
    CallbackQueryHandler, filters, ContextTypes
)

# ==============================================
# ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ
# ==============================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN должен быть задан!")
if not ADMIN_CHAT_ID:
    print("⚠️ ADMIN_CHAT_ID не задан. Уведомления администратору не будут работать.")

STUDIO_CHAT_URL = "https://t.me/MintGlow_9k1"

# ==============================================
# СТРУКТУРА МЕНЮ ЗАПИСИ
# ==============================================
BOOKING = {
    "epilation": {
        "title": "⚡ Электроэпиляция",
        "services": [
            {"name": "30 минут",  "price": "1 800 ₽",  "url": "https://dkd.su/1330084/s/21047026"},
            {"name": "1 час",     "price": "3 600 ₽",  "url": "https://dkd.su/1330084/s/21047085"},
            {"name": "1,5 часа",  "price": "5 400 ₽",  "url": "https://dkd.su/1330084/s/21047127"},
            {"name": "2 часа",    "price": "7 200 ₽",  "url": "https://dkd.su/1330084/s/21047155"},
            {"name": "3 часа",    "price": "10 800 ₽", "url": "https://dkd.su/1330084/s/21047192"},
        ]
    },
    "laser": {
        "title": "💡 Лазерная эпиляция",
        "sub": [
            {"code": "laser_complex", "title": "🧩 Комплексы", "services": [
                {"name": "Комплекс 1 (подмышки + бикини глубокое)",         "price": "2 850 ₽ / 40 мин", "url": "https://dkd.su/1330084/s/20815111"},
                {"name": "Комплекс 2 (руки до локтя + голени)",             "price": "5 225 ₽ / 1:20",   "url": "https://dkd.su/1330084/s/20815089"},
                {"name": "Комплекс 3 (руки полностью + ноги до колена)",    "price": "6 175 ₽ / 1:30",   "url": "https://dkd.su/1330084/s/20815076"},
                {"name": "Комплекс 4 (ноги полностью + подмышки)",          "price": "8 500 ₽ / 2 ч",    "url": "https://dkd.su/1330084/s/20815070"},
                {"name": "Комплекс 5 (всё тело)",                           "price": "9 500 ₽ / 2:30",   "url": "https://dkd.su/1330084/s/20815056"},
            ]},
            {"code": "laser_zones", "title": "🎯 Отдельные зоны", "sub": [
                {"code": "laser_face", "title": "👤 Лицо", "services": [
                    {"name": "Верхняя губа",   "price": "800 ₽",   "url": "https://dkd.su/1330084/s/20897184"},
                    {"name": "Бакенбарды",     "price": "800 ₽",   "url": "https://dkd.su/1330084/s/20897177"},
                    {"name": "Подбородок",     "price": "800 ₽",   "url": "https://dkd.su/1330084/s/20815139"},
                    {"name": "Лицо полностью", "price": "2 000 ₽", "url": "https://dkd.su/1330084/s/23455286"},
                ]},
                {"code": "laser_bikini", "title": "👙 Бикини", "services": [
                    {"name": "Бикини классическое", "price": "1 000 ₽", "url": "https://dkd.su/1330084/s/20897160"},
                    {"name": "Бикини глубокое",     "price": "2 000 ₽", "url": "https://dkd.su/1330084/s/20897105"},
                ]},
                {"code": "laser_up", "title": "⬆️ Пояс вверх", "services": [
                    {"name": "Шея",            "price": "1 000 ₽", "url": "https://dkd.su/1330084/s/20897123"},
                    {"name": "Декольте",        "price": "2 000 ₽", "url": "https://dkd.su/1330084/s/20897094"},
                    {"name": "Подмышки",        "price": "1 000 ₽", "url": "https://dkd.su/1330084/s/20820217"},
                    {"name": "Руки выше локтя", "price": "2 000 ₽", "url": "https://dkd.su/1330084/s/20897068"},
                    {"name": "Руки полностью",  "price": "2 500 ₽", "url": "https://dkd.su/1330084/s/20897028"},
                    {"name": "Линия живота",    "price": "1 000 ₽", "url": "https://dkd.su/1330084/s/20897143"},
                    {"name": "Живот полностью", "price": "2 000 ₽", "url": "https://dkd.su/1330084/s/20897082"},
                ]},
                {"code": "laser_down", "title": "⬇️ Пояс вниз", "services": [
                    {"name": "Поясница",             "price": "1 000 ₽", "url": "https://dkd.su/1330084/s/20897133"},
                    {"name": "Ягодицы",              "price": "2 000 ₽", "url": "https://dkd.su/1330084/s/20897060"},
                    {"name": "Бёдра",                "price": "2 500 ₽", "url": "https://dkd.su/1330084/s/20897054"},
                    {"name": "Голени (вкл. колени)", "price": "2 500 ₽", "url": "https://dkd.su/1330084/s/20897037"},
                    {"name": "Ноги полностью",       "price": "3 500 ₽", "url": "https://dkd.su/1330084/s/20897004"},
                    {"name": "Пальцы ног",           "price": "800 ₽",   "url": "https://dkd.su/1330084/s/20897168"},
                ]},
            ]},
        ]
    },
    "depilation": {
        "title": "🌿 Депиляция (воск / шугаринг)",
        "sub": [
            {"code": "dep_complex", "title": "🧩 Комплексы", "services": [
                {"name": "Мини (подмышки + глубокое бикини)", "price": "2 500 ₽", "url": "https://dkd.su/1330084/s/23455370"},
                {"name": "Стандарт (+ ноги до колена)",       "price": "3 000 ₽", "url": "https://dkd.su/1330084/s/23455376"},
                {"name": "Максимум (+ ноги полностью)",       "price": "3 500 ₽", "url": "https://dkd.su/1330084/s/23455391"},
            ]},
            {"code": "dep_zones", "title": "🎯 Зоны по отдельности", "sub": [
                {"code": "dep_face", "title": "👤 Лицо", "services": [
                    {"name": "Лицо полностью", "price": "1 200 ₽", "url": "https://dkd.su/1330084/s/23455286"},
                ]},
                {"code": "dep_bikini", "title": "👙 Бикини", "services": [
                    {"name": "Бикини классическое",    "price": "1 500 ₽", "url": "https://dkd.su/1330084/s/20820206"},
                    {"name": "Глубокое бикини (воск)", "price": "2 000 ₽", "url": "https://dkd.su/1330084/s/20820195"},
                ]},
                {"code": "dep_up", "title": "⬆️ Пояс вверх", "services": [
                    {"name": "Подмышки",       "price": "800 ₽",   "url": "https://dkd.su/1330084/s/20820217"},
                    {"name": "Руки до локтя",  "price": "800 ₽",   "url": "https://dkd.su/1330084/s/20820101"},
                    {"name": "Руки полностью", "price": "1 200 ₽", "url": "https://dkd.su/1330084/s/20820113"},
                ]},
                {"code": "dep_down", "title": "⬇️ Пояс вниз", "services": [
                    {"name": "Ноги до колена",                  "price": "1 200 ₽", "url": "https://dkd.su/1330084/s/20820123"},
                    {"name": "Ноги полностью",                  "price": "1 800 ₽", "url": "https://dkd.su/1330084/s/20820125"},
                    {"name": "Депиляция воском: бедро (выше колена)", "price": "1 000 ₽", "url": "https://dkd.su/1330084/s/20820116"},
                    {"name": "Ягодицы",                         "price": "1 000 ₽", "url": "https://dkd.su/1330084/s/20820091"},
                ]},
            ]},
        ]
    },
    "body": {
        "title": "🔸 Коррекция фигуры",
        "sub": [
            {"code": "body_complex", "title": "🧩 Комплексы", "services": [
                {"name": "Комплекс 2в1 (Сфера + на выбор)",   "price": "4 500 ₽ / 60 мин", "url": "https://dkd.su/1330084/s/20814494"},
                {"name": "Комплекс 3в1 (Сфера + 2 на выбор)", "price": "6 750 ₽ / 90 мин", "url": "https://dkd.su/1330084/s/20814500"},
            ]},
            {"code": "body_single", "title": "🎯 Отдельные процедуры", "services": [
                {"name": "Сфера тела (30 мин)",     "price": "3 000 ₽", "url": "https://dkd.su/1330084/s/20814508"},
                {"name": "Сфера тела (60 мин)",     "price": "4 500 ₽", "url": "https://dkd.su/1330084/s/20814598"},
                {"name": "Микроволны (30 мин)",     "price": "3 000 ₽", "url": "https://dkd.su/1330084/s/20814656"},
                {"name": "Горячий вакуум (30 мин)", "price": "3 000 ₽", "url": "https://dkd.su/1330084/s/20814603"},
                {"name": "Индиба (30 мин)",         "price": "1 500 ₽", "url": "https://dkd.su/1330084/s/21546214"},
            ]},
        ]
    },
    "cosmetology": {
        "title": "🔹 Косметология и уход за лицом",
        "sub": [
            {"code": "cos_clean", "title": "🧼 Чистки", "services": [
                {"name": "Комбинированная чистка (105 мин)", "price": "5 000 ₽", "url": "https://dkd.su/1330084/s/20814462"},
                {"name": "УЗ-чистка (90 мин)",               "price": "4 000 ₽", "url": "https://dkd.su/1330084/s/20814456"},
                {"name": "Механическая чистка (90 мин)",     "price": "4 000 ₽", "url": "https://dkd.su/1330084/s/20814450"},
            ]},
            {"code": "cos_care", "title": "💧 Уходы", "sub": [
                {"code": "care_line", "title": "Line Repair", "services": [
                    {"name": "Уход Line Repair (60 мин)",          "price": "4 000 ₽", "url": "https://dkd.su/1330084/s/21586852"},
                    {"name": "Уход Line Repair + массаж (90 мин)", "price": "5 000 ₽", "url": "https://dkd.su/1330084/s/21586883"},
                ]},
                {"code": "care_unstress", "title": "Unstress", "services": [
                    {"name": "Уход Unstress (60 мин)",          "price": "3 600 ₽", "url": "https://dkd.su/1330084/s/20814430"},
                    {"name": "Уход Unstress + массаж (90 мин)", "price": "4 500 ₽", "url": "https://dkd.su/1330084/s/20814424"},
                ]},
                {"code": "care_bio", "title": "Bio Phyto", "services": [
                    {"name": "Уход Bio Phyto (60 мин)",          "price": "3 500 ₽", "url": "https://dkd.su/1330084/s/20814410"},
                    {"name": "Уход Bio Phyto + массаж (90 мин)", "price": "4 500 ₽", "url": "https://dkd.su/1330084/s/20814400"},
                ]},
                {"code": "care_carbo", "title": "Карбокситерапия", "services": [
                    {"name": "Карбокситерапия (60 мин)",          "price": "3 500 ₽", "url": "https://dkd.su/1330084/s/20814346"},
                    {"name": "Карбокситерапия + массаж (90 мин)", "price": "4 500 ₽", "url": "https://dkd.su/1330084/s/20814331"},
                ]},
                {"code": "care_comodex", "title": "Comodex", "services": [
                    {"name": "Уход Comodex (60 мин)", "price": "3 700 ₽", "url": "https://dkd.su/1330084/s/20814372"},
                ]},
                {"code": "care_darson", "title": "Дарсонваль", "services": [
                    {"name": "Дарсонваль (30 мин)", "price": "1 000 ₽", "url": "https://dkd.su/1330084/s/21587051"},
                ]},
            ]},
            {"code": "cos_peel", "title": "🍃 Пилинги", "services": [
                {"name": "Пилинг Rose de Mer (75 мин)", "price": "4 000 ₽", "url": "https://dkd.su/1330084/s/20814310"},
                {"name": "Миндальный пилинг (75 мин)",  "price": "3 500 ₽", "url": "https://dkd.su/1330084/s/20814302"},
            ]},
            {"code": "cos_appar", "title": "🌀 Аппаратные массажи для лица", "services": [
                {"name": "Сфера для лица (30 мин)",           "price": "3 000 ₽", "url": "https://dkd.su/1330084/s/20814482"},
                {"name": "Комплекс для лица (сфера + маска)", "price": "4 000 ₽", "url": "https://dkd.su/1330084/s/20814477"},
            ]},
            {"code": "cos_manual", "title": "💧 Массаж лица (ручной) / Маска", "services": [
                {"name": "Массаж лица по маске/крему (30 мин)", "price": "2 000 ₽", "url": "https://dkd.su/1330084/s/20814274"},
                {"name": "Маска для лица (30 мин)",             "price": "500 ₽",   "url": "https://dkd.su/1330084/s/21587113"},
            ]},
        ]
    },
}

# ==============================================
# ТЕКСТЫ ПОДГОТОВКИ
# ==============================================
PREP_TEXTS = {
    "epilation": (
        "⚡ Подготовка к электроэпиляции:\n\n"
        "1. За 2–3 дня не загорать и не посещать солярий.\n"
        "2. За сутки — без алкоголя и кофеина.\n"
        "3. В день процедуры не наносить кремы, лосьоны, дезодоранты.\n"
        "4. Длина волос не менее 5–7 мм.\n"
        "5. Свободная одежда.\n"
        "6. Аппликационная анестезия за 1–2 часа до сеанса.\n"
        "7. Душ перед процедурой, без скрабов.\n"
        "8. Сообщить мастеру о заболеваниях и противопоказаниях."
    ),
    "laser": (
        "💡 Подготовка к лазерной эпиляции:\n\n"
        "1. За 1–2 дня обязательно побрить зону (длина волос 1–2 мм).\n"
        "2. За 2–3 недели не выдёргивать волосы (воск, шугаринг, эпилятор).\n"
        "3. За 2–3 недели не загорать и не посещать солярий.\n"
        "4. За 4–5 дней отказаться от пилингов, скрабов, ретиноидов.\n"
        "5. В день процедуры не наносить кремы, лосьоны, дезодоранты.\n"
        "6. Свободная одежда.\n"
        "7. Душ перед процедурой, без скрабов.\n"
        "8. Сообщить мастеру о заболеваниях."
    ),
    "depilation": (
        "🌿 Подготовка к депиляции:\n\n"
        "• Для воска длина волос 5–7 мм.\n"
        "• Для шугаринга — по рекомендации мастера.\n"
        "• За сутки не использовать скрабы и масла."
    ),
}

# ==============================================
# ТЕКСТЫ УХОДА
# ==============================================
AFTER_TEXTS = {
    "epilation": (
        "⚡ Уход после электроэпиляции:\n\n"
        "• Первые сутки: без сауны, бани, бассейна, горячей ванны.\n"
        "• 2–3 дня: без интенсивных нагрузок.\n"
        "• 3–4 дня: без кремов, лосьонов, дезодорантов, скрабов.\n"
        "• Неделю: без загара и солярия.\n"
        "• Носить свободную одежду из хлопка или льна.\n"
        "• Уход: хлоргексидин → циндол/неотанин → пантенол/бепантен.\n"
        "• Тест на аллергию за 2–4 часа до применения."
    ),
    "laser": (
        "💡 Уход после лазерной эпиляции:\n\n"
        "• Душ разрешён.\n"
        "• Избегать ванны, бассейна, бани, сауны минимум неделю.\n"
        "• Эффект проявляется в течение 1–2 недель — волосы выпадают.\n"
        "• Не выдёргивать волосы между сеансами."
    ),
    "depilation": (
        "🌿 Уход после депиляции:\n\n"
        "• Не загорать 24 часа.\n"
        "• Не ходить в баню/сауну.\n"
        "• Использовать увлажняющие средства без спирта и отдушек."
    ),
}

# ==============================================
# УВЕДОМЛЕНИЯ АДМИНИСТРАТОРУ
# ==============================================

async def notify_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_CHAT_ID:
        return
    user = update.effective_user
    username = f"@{user.username}" if user.username else user.first_name
    text = update.message.text

    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=(
            f"🔔 Новое сообщение от клиента\n\n"
            f"Клиент: {username} (ID: {user.id})\n"
            f"Сообщение: {text}\n\n"
            f"Ответьте через /reply {user.id} [текст]"
        )
    )


async def reply_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_CHAT_ID:
        await update.message.reply_text("Администратор не настроен.")
        return
    if str(update.effective_user.id) != ADMIN_CHAT_ID:
        await update.message.reply_text("У вас нет прав.")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Использование: /reply [user_id] [текст]")
        return
    try:
        user_id = int(args[0])
        text = " ".join(args[1:])
        await context.bot.send_message(chat_id=user_id, text=f"Администратор: {text}")
        await update.message.reply_text(f"✅ Отправлено пользователю {user_id}.")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")


# ==============================================
# ГЛАВНОЕ МЕНЮ
# ==============================================

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Записаться на процедуру", callback_data="main:booking")],
        [InlineKeyboardButton("📚 Подготовка к процедуре",  callback_data="main:prep")],
        [InlineKeyboardButton("💆 Уход после процедуры",    callback_data="main:after")],
        [InlineKeyboardButton("🎁 Акции и предложения",     callback_data="main:promo")],
        [InlineKeyboardButton("✍️ Задать вопрос",           callback_data="main:ask")],
    ])


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Добро пожаловать в студию MintGlow!\n\nВыберите, что вас интересует:",
        reply_markup=main_menu_keyboard()
    )


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "👋 Добро пожаловать в студию MintGlow!\n\nВыберите, что вас интересует:"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=main_menu_keyboard())
    else:
        await update.message.reply_text(text, reply_markup=main_menu_keyboard())


# ==============================================
# ГЛАВНЫЙ CALLBACK
# ==============================================

async def main_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "main:menu":
        await show_main_menu(update, context)
        return

    if data == "main:close":
        await query.edit_message_text("❌ Меню закрыто. Чтобы вернуться — напишите /start.")
        return

    if data == "main:booking":
        keyboard = []
        for code, cat in BOOKING.items():
            keyboard.append([InlineKeyboardButton(cat["title"], callback_data=f"book:{code}")])
        keyboard.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])
        keyboard.append([InlineKeyboardButton("❌ Закрыть", callback_data="main:close")])
        await query.edit_message_text(
            "📅 Запись онлайн\n\nВыберите направление:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data == "main:prep":
        keyboard = [
            [InlineKeyboardButton("⚡ Электроэпиляция",   callback_data="prep:epilation")],
            [InlineKeyboardButton("💡 Лазерная эпиляция", callback_data="prep:laser")],
            [InlineKeyboardButton("🌿 Депиляция",         callback_data="prep:depilation")],
            [InlineKeyboardButton("🏠 В начало",          callback_data="main:menu")],
        ]
        await query.edit_message_text(
            "📚 Подготовка к процедуре\n\nВыберите тип:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data == "main:after":
        keyboard = [
            [InlineKeyboardButton("⚡ Электроэпиляция",   callback_data="after:epilation")],
            [InlineKeyboardButton("💡 Лазерная эпиляция", callback_data="after:laser")],
            [InlineKeyboardButton("🌿 Депиляция",         callback_data="after:depilation")],
            [InlineKeyboardButton("🏠 В начало",          callback_data="main:menu")],
        ]
        await query.edit_message_text(
            "💆 Уход после процедуры\n\nВыберите тип:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data == "main:promo":
        keyboard = [
            [InlineKeyboardButton("🎮 Игра «Идеальный визит»", callback_data="promo:game")],
            [InlineKeyboardButton("✨ Знакомство с мастером",  callback_data="promo:new")],
            [InlineKeyboardButton("📢 Другие акции",           callback_data="promo:other")],
            [InlineKeyboardButton("🏠 В начало",               callback_data="main:menu")],
        ]
        await query.edit_message_text(
            "🎁 Акции и предложения\n\nВыберите раздел:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data == "main:ask":
        text = (
            "✍️ Задать вопрос администратору\n\n"
            "Перейдите в чат со студией — администратор ответит в ближайшее время."
        )
        keyboard = [
            [InlineKeyboardButton("💬 Написать администратору", url=STUDIO_CHAT_URL)],
            [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return


# ==============================================
# МЕНЮ ЗАПИСИ
# ==============================================

async def booking_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("book:"):
        code = data.split(":", 1)[1]
        cat = BOOKING.get(code)
        if not cat:
            await query.edit_message_text("⚠️ Раздел не найден.")
            return
        if "sub" in cat:
            keyboard = []
            for sub in cat["sub"]:
                keyboard.append([InlineKeyboardButton(sub["title"], callback_data=f"sub:{code}:{sub['code']}")])
            keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="main:booking")])
            keyboard.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])
            await query.edit_message_text(
                f"{cat['title']}\n\nВыберите категорию:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        keyboard = []
        for i, s in enumerate(cat["services"]):
            keyboard.append([InlineKeyboardButton(f"{s['name']} — {s['price']}", callback_data=f"srv:{code}:{i}")])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="main:booking")])
        await query.edit_message_text(
            f"{cat['title']}\n\nВыберите услугу:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data.startswith("sub:"):
        parts = data.split(":")
        parent_code, sub_code = parts[1], parts[2]
        parent = BOOKING.get(parent_code)
        sub = next((s for s in parent.get("sub", []) if s["code"] == sub_code), None)
        if not sub:
            await query.edit_message_text("⚠️ Подкатегория не найдена.")
            return
        if "sub" in sub:
            keyboard = []
            for s2 in sub["sub"]:
                keyboard.append([InlineKeyboardButton(s2["title"], callback_data=f"sub2:{parent_code}:{sub_code}:{s2['code']}")])
            keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data=f"book:{parent_code}")])
            await query.edit_message_text(
                f"{parent['title']} → {sub['title']}\n\nВыберите:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        keyboard = []
        for i, s in enumerate(sub["services"]):
            keyboard.append([InlineKeyboardButton(f"{s['name']} — {s['price']}", callback_data=f"srv2:{parent_code}:{sub_code}:{i}")])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data=f"book:{parent_code}")])
        await query.edit_message_text(
            f"{parent['title']} → {sub['title']}\n\nВыберите услугу:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data.startswith("sub2:"):
        parts = data.split(":")
        parent_code, sub_code, sub2_code = parts[1], parts[2], parts[3]
        parent = BOOKING[parent_code]
        sub = next(s for s in parent["sub"] if s["code"] == sub_code)
        sub2 = next(s for s in sub["sub"] if s["code"] == sub2_code)
        keyboard = []
        for i, s in enumerate(sub2["services"]):
            keyboard.append([InlineKeyboardButton(f"{s['name']} — {s['price']}", callback_data=f"srv3:{parent_code}:{sub_code}:{sub2_code}:{i}")])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data=f"sub:{parent_code}:{sub_code}")])
        await query.edit_message_text(
            f"{parent['title']} → {sub['title']} → {sub2['title']}\n\nВыберите услугу:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data.startswith("srv:") and data.count(":") == 2:
        parts = data.split(":")
        code, idx = parts[1], int(parts[2])
        s = BOOKING[code]["services"][idx]
        await show_service_result(query, s, f"book:{code}")
        return

    if data.startswith("srv2:"):
        parts = data.split(":")
        parent_code, sub_code, idx = parts[1], parts[2], int(parts[3])
        parent = BOOKING[parent_code]
        sub = next(s for s in parent["sub"] if s["code"] == sub_code)
        s = sub["services"][idx]
        await show_service_result(query, s, f"sub:{parent_code}:{sub_code}")
        return

    if data.startswith("srv3:"):
        parts = data.split(":")
        parent_code, sub_code, sub2_code, idx = parts[1], parts[2], parts[3], int(parts[4])
        parent = BOOKING[parent_code]
        sub = next(s for s in parent["sub"] if s["code"] == sub_code)
        sub2 = next(s for s in sub["sub"] if s["code"] == sub2_code)
        s = sub2["services"][idx]
        await show_service_result(query, s, f"sub2:{parent_code}:{sub_code}:{sub2_code}")
        return


async def show_service_result(query, service, back_callback):
    text = (
        f"✅ {service['name']} — {service['price']}\n\n"
        f"Нажмите «Открыть календарь записи».\n\n"
        f"📲 Если при подтверждении DiKidi попросит код «в приложении», "
        f"но приложения у вас нет или код не пришёл — нажмите в окне "
        f"DiKidi «Не пришёл код» → подтвердите, что вы не бот (капча «Я не бот»).\n\n"
        f"Контакты: +7 916 758 51 41 (Telegram / WhatsApp / МАХ)"
    )
    keyboard = [
        [InlineKeyboardButton("📅 Открыть календарь записи", url=service["url"])],
        [InlineKeyboardButton("◀️ Назад", callback_data=back_callback)],
        [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
        [InlineKeyboardButton("❌ Закрыть", callback_data="main:close")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


# ==============================================
# ПОДГОТОВКА / УХОД / АКЦИИ
# ==============================================

async def prep_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    code = query.data.split(":", 1)[1]
    text = PREP_TEXTS.get(code, "Информация недоступна.")
    keyboard = [
        [InlineKeyboardButton("◀️ Назад", callback_data="main:prep")],
        [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def after_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    code = query.data.split(":", 1)[1]
    text = AFTER_TEXTS.get(code, "Информация недоступна.")
    keyboard = [
        [InlineKeyboardButton("◀️ Назад", callback_data="main:after")],
        [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def promo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    code = query.data.split(":", 1)[1]

    if code == "game":
        text = (
            "🎮 Игра «Идеальный визит»\n\n"
            "Начисляем:\n"
            "• 5% от чека — за визит без опозданий и отмен\n"
            "• +300 бонусов — за каждый отзыв (Яндекс, 2ГИС, Google, Zoon)\n"
            "• +100 бонусов — если отзыв с фото\n\n"
            "Тратим:\n"
            "• 1 бонус = 1 ₽\n"
            "• До 50% от чека на любые услуги\n\n"
            "❌ Бонусы НЕ действуют на:\n"
            "• Электроэпиляцию\n"
            "• Депиляцию воском и шугаринг\n"
            "• Покупку абонементов\n\n"
            "Не суммируются со скидками и акциями.\n\n"
            "🔥 Сгорают:\n"
            "• При опоздании >5 минут\n"
            "• При отмене или переносе менее чем за 48 часов\n\n"
            "✅ Исключения:\n"
            "• Перенос за 48+ часов — сохраняются\n"
            "• Перенос по инициативе студии — сохраняются + 500 бонусов\n\n"
            "🎁 Призы за накопление:\n"
            "• 3 000 — подарок\n"
            "• 5 000 — сюрприз\n"
            "• 10 000 — особый приз\n\n"
            "📊 Чтобы узнать количество бонусов — перейдите в чат с администратором "
            "и напишите «Бонусы» + ваше имя и последние 4 цифры номера телефона. "
            "Администратор ответит вам в чате."
        )
        keyboard = [
            [InlineKeyboardButton("💬 Узнать количество бонусов", url=STUDIO_CHAT_URL)],
            [InlineKeyboardButton("📅 Записаться", callback_data="main:booking")],
            [InlineKeyboardButton("◀️ Назад", callback_data="main:promo")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if code == "new":
        text = (
            "✨ Акция «Знакомство с мастером»\n\n"
            "Действует, когда в студии появляется новый мастер.\n\n"
            "Сейчас акция для мастера Зульфии:\n"
            "🎉 Скидка 20% на электроэпиляцию — 48 ₽/мин вместо 60 ₽/мин.\n"
            "📅 Действует до конца сентября."
        )
        keyboard = [
            [InlineKeyboardButton("📅 Записаться на электроэпиляцию", callback_data="book:epilation")],
            [InlineKeyboardButton("◀️ Назад", callback_data="main:promo")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if code == "other":
        text = (
            "📢 Другие акции\n\n"
            "Следите за акциями и предложениями в наших каналах и соцсетях:\n\n"
            "• Telegram-канал: https://t.me/elektroepil_mint\n"
            "• Instagram: @mintglow_voika\n"
            "• VK: https://vk.com/sugar_voikovskaya\n\n"
            "Там мы публикуем:\n"
            "• «Охота на окошки» — скидки до 20% на горящие места\n"
            "• Новые акции и спецпредложения\n"
            "• Анонсы новых мастеров"
        )
        keyboard = [
            [InlineKeyboardButton("📢 Открыть Telegram-канал", url="https://t.me/elektroepil_mint")],
            [InlineKeyboardButton("◀️ Назад", callback_data="main:promo")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return


# ==============================================
# ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ (без GigaChat)
# ==============================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text

    # Ключевые слова — отправляем в нужные меню
    text_lower = user_text.lower()

    if any(k in text_lower for k in ["записаться", "запись", "хочу записаться", "запишите меня"]):
        keyboard = []
        for code, cat in BOOKING.items():
            keyboard.append([InlineKeyboardButton(cat["title"], callback_data=f"book:{code}")])
        keyboard.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])
        await update.message.reply_text(
            "📅 Запись онлайн\n\nВыберите направление:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if any(k in text_lower for k in ["подготовка", "как подготовиться", "подготовиться"]):
        keyboard = [
            [InlineKeyboardButton("⚡ Электроэпиляция",   callback_data="prep:epilation")],
            [InlineKeyboardButton("💡 Лазерная эпиляция", callback_data="prep:laser")],
            [InlineKeyboardButton("🌿 Депиляция",         callback_data="prep:depilation")],
            [InlineKeyboardButton("🏠 В начало",          callback_data="main:menu")],
        ]
        await update.message.reply_text("📚 Подготовка к процедуре\n\nВыберите тип:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if any(k in text_lower for k in ["уход", "уход после", "что делать после"]):
        keyboard = [
            [InlineKeyboardButton("⚡ Электроэпиляция",   callback_data="after:epilation")],
            [InlineKeyboardButton("💡 Лазерная эпиляция", callback_data="after:laser")],
            [InlineKeyboardButton("🌿 Депиляция",         callback_data="after:depilation")],
            [InlineKeyboardButton("🏠 В начало",          callback_data="main:menu")],
        ]
        await update.message.reply_text("💆 Уход после процедуры\n\nВыберите тип:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if any(k in text_lower for k in ["акции", "скидки", "бонусы", "идеальный визит"]):
        keyboard = [
            [InlineKeyboardButton("🎮 Игра «Идеальный визит»", callback_data="promo:game")],
            [InlineKeyboardButton("✨ Знакомство с мастером",  callback_data="promo:new")],
            [InlineKeyboardButton("📢 Другие акции",           callback_data="promo:other")],
            [InlineKeyboardButton("🏠 В начало",               callback_data="main:menu")],
        ]
        await update.message.reply_text("🎁 Акции и предложения\n\nВыберите раздел:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # Всё остальное — уведомляем администратора и даём кнопку возврата в чат
    await notify_admin(update, context)
    keyboard = [
        [InlineKeyboardButton("💬 Написать администратору", url=STUDIO_CHAT_URL)],
        [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
    ]
    await update.message.reply_text(
        "✍️ Я передал ваш вопрос администратору. Он ответит в ближайшее время.\n\n"
        "Если срочно — напишите напрямую:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ==============================================
# ЗАПУСК БОТА
# ==============================================

def run_bot():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("reply", reply_to_user))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.add_handler(CallbackQueryHandler(main_callback,    pattern="^main:"))
    app.add_handler(CallbackQueryHandler(booking_callback, pattern="^(book:|sub:|sub2:|srv:|srv2:|srv3:)"))
    app.add_handler(CallbackQueryHandler(prep_callback,    pattern="^prep:"))
    app.add_handler(CallbackQueryHandler(after_callback,   pattern="^after:"))
    app.add_handler(CallbackQueryHandler(promo_callback,   pattern="^promo:"))

    print("✅ Бот запущен!")
    app.run_polling()
