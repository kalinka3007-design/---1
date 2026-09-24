import os
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler, CommandHandler,
    CallbackQueryHandler, filters, ContextTypes
)

# Импорт всего контента из отдельного файла
from content import (
    BOOKING, MASTERS, PREP_TEXTS, AFTER_TEXTS, PROMO_TEXTS, FAQ_TEXTS,
    DIKIDI_URL,
    URL_BONUS_BALANCE, URL_CERTIFICATE, URL_SUBSCRIPTION,
    URL_FRIEND, URL_REVIEW, URL_PAYMENT, URL_TRANSFER, URL_CANCEL,
    URL_LATE, URL_SAME_DAY, URL_QUESTION,
    URL_REVIEW_YANDEX, URL_REVIEW_Zoon, URL_REVIEW_2GIS, URL_REVIEW_GOOGLE,
    URL_MAPS_YANDEX, URL_MAPS_GOOGLE, URL_ENTRANCE_PHOTO, URL_CLIENT_REVIEWS,
    URL_TELEGRAM_CHANNEL, URL_INSTAGRAM, URL_VK,
    PHONE_DISPLAY, PHONE_TEL, URL_WHATSAPP, URL_MAX,
)

# ==============================================
# ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ
# ==============================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN должен быть задан!")

ADMIN_ID = int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID else None

# ==============================================
# УТИЛИТЫ
# ==============================================

def hp(path: str, text: str) -> str:
    """Добавляет хлебные крошки к тексту."""
    return f"🏠 → {path}\n\n{text}"


NAV = [
    [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
]


def kb(*rows):
    """Собирает клавиатуру из переданных строк."""
    return InlineKeyboardMarkup(list(rows))


# ==============================================
# УВЕДОМЛЕНИЯ АДМИНУ
# ==============================================

async def notify_admin(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       tag: str = "", extra: str = ""):
    """Отправляет уведомление админу с пометкой."""
    if not ADMIN_ID:
        print("⚠️ ADMIN_CHAT_ID не задан")
        return False

    user = update.effective_user
    username = f"@{user.username}" if user.username else user.first_name or "без имени"

    header = f"🔔 {tag}" if tag else "🔔 Новое сообщение"

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"{header}\n\n"
                f"👤 Клиент: {username}\n"
                f"🆔 ID: {user.id}\n"
                f"{extra}\n\n"
                f"➡️ Ответить: /reply {user.id} [текст]"
            )
        )
        print(f"✅ Уведомление отправлено: {tag}")
        return True
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")
        return False


async def notify_admin_button(update: Update, context: ContextTypes.DEFAULT_TYPE, tag: str):
    """Уведомление при нажатии кнопки."""
    if not ADMIN_ID:
        return
    query = update.callback_query
    user = query.from_user
    username = f"@{user.username}" if user.username else user.first_name or "без имени"

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"🔔 {tag}\n\n"
                f"👤 Клиент: {username}\n"
                f"🆔 ID: {user.id}\n\n"
                f"➡️ Ответить: /reply {user.id} [текст]"
            )
        )
    except Exception as e:
        print(f"❌ Ошибка: {e}")


async def reply_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_ID:
        await update.message.reply_text("Администратор не настроен.")
        return
    if update.effective_user.id != ADMIN_ID:
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
    return kb(
        [InlineKeyboardButton("📅 Записаться на процедуру", callback_data="main:booking")],
        [InlineKeyboardButton("📚 Подготовка к процедуре",  callback_data="main:prep")],
        [InlineKeyboardButton("💆 Уход после процедуры",    callback_data="main:after")],
        [InlineKeyboardButton("📋 Прайс-лист",              callback_data="main:price")],
        [InlineKeyboardButton("🎁 Акции и бонусы",          callback_data="main:promo")],
        [InlineKeyboardButton("ℹ️ О студии",                callback_data="main:about")],
        [InlineKeyboardButton("✍️ Задать вопрос",           callback_data="main:ask")],
    )


MAIN_TEXT = (
    "👋 Добро пожаловать в MintGlow!\n\n"
    "Выберите, что вас интересует:\n\n"
    "💡 Не нашли нужное? Нажмите «✍️ Задать вопрос»."
)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(MAIN_TEXT, reply_markup=main_menu_keyboard())


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.edit_message_text(MAIN_TEXT, reply_markup=main_menu_keyboard())
    else:
        await update.message.reply_text(MAIN_TEXT, reply_markup=main_menu_keyboard())


# ==============================================
# УНИВЕРСАЛЬНЫЙ ОБРАБОТЧИК
# ==============================================

async def universal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    print(f"🔘 {data}")

    try:
        await query.answer()
    except Exception as e:
        print(f"⚠️ answer: {e}")

    # ГЛАВНОЕ МЕНЮ
    if data == "main:menu":
        await show_main_menu(update, context)
        return

    if data == "main:close":
        await query.edit_message_text("❌ Меню закрыто. Чтобы вернуться — напишите /start.")
        return

    # --- РАЗДЕЛЫ ГЛАВНОГО МЕНЮ ---
    if data == "main:booking":
        await show_booking(update, context)
        return

    if data == "main:prep":
        await show_prep_menu(update, context)
        return

    if data == "main:after":
        await show_after_menu(update, context)
        return

    if data == "main:price":
        await show_price_menu(update, context)
        return

    if data == "main:promo":
        await show_promo_menu(update, context)
        return

    if data == "main:about":
        await show_about_menu(update, context)
        return

    if data == "main:ask":
        await show_ask(update, context)
        return

    # --- FAQ / АКЦИИ / УВЕДОМЛЕНИЯ ---
    if data.startswith("faq:"):
        await faq_callback(update, context)
        return

    if data.startswith("promo:"):
        await promo_callback(update, context)
        return

    # Уведомления-триггеры
    triggers = {
        "notify:subscription": "📦 АБОНЕМЕНТ",
        "notify:certificate": "🎁 СЕРТИФИКАТ",
        "notify:bonus":       "💰 БАЛАНС БОНУСОВ",
        "notify:friend":      "👯 ПРИВЕДИ ПОДРУГУ",
        "notify:review":      "⭐ ОТЗЫВ",
        "notify:payment":     "💳 ОПЛАТА",
        "notify:transfer":    "🔄 ПЕРЕНОС",
        "notify:cancel":      "❌ ОТМЕНА",
        "notify:late":        "⏰ ОПОЗДАНИЕ",
        "notify:same_day":    "📅 ЗАПИСЬ ДЕНЬ В ДЕНЬ",
        "notify:question":    "✍️ ВОПРОС",
    }
    if data in triggers:
        await notify_admin_button(update, context, triggers[data])
        return

    # --- ЗАПИСЬ ---
    if data.startswith(("book:", "sub:", "sub2:", "srv:", "srv2:", "srv3:")):
        await booking_callback(update, context)
        return

    # --- МАСТЕРА ---
    if data.startswith("master:"):
        await master_callback(update, context)
        return

    # --- ПОДГОТОВКА / УХОД / ПРАЙС ---
    if data.startswith("prep:"):
        await prep_callback(update, context)
        return

    if data.startswith("after:"):
        await after_callback(update, context)
        return

    if data.startswith("price:"):
        await price_callback(update, context)
        return

    # --- О СТУДИИ ---
    if data.startswith("about:"):
        await about_callback(update, context)
        return

    print(f"⚠️ Неизвестный callback: {data}")


# ==============================================
# 1. ЗАПИСЬ
# ==============================================

async def show_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    keyboard = []
    for code, cat in BOOKING.items():
        keyboard.append([InlineKeyboardButton(cat["title"], callback_data=f"book:{code}")])
    keyboard.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])
    keyboard.append([InlineKeyboardButton("❌ Закрыть", callback_data="main:close")])
    await query.edit_message_text(
        hp("📅 Запись", "📅 Запись онлайн\n\nВыберите направление:"),
        reply_markup=kb(*keyboard)
    )


async def booking_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data.startswith("book:"):
        code = data.split(":", 1)[1]
        cat = BOOKING.get(code)
        if not cat:
            await query.edit_message_text("⚠️ Раздел не найден.")
            return

        # Категория с подкатегориями
        if "sub" in cat:
            keyboard = []
            for sub in cat["sub"]:
                keyboard.append([InlineKeyboardButton(sub["title"], callback_data=f"sub:{code}:{sub['code']}")])

            # Дополнительные кнопки для лазера/депиляции
            extra = []
            if code == "laser":
                extra.append([InlineKeyboardButton("📚 Как подготовиться к лазерной эпиляции",
                                                   callback_data="prep:laser")])
            elif code == "depilation":
                extra.append([InlineKeyboardButton("📚 Как подготовиться к депиляции",
                                                   callback_data="prep:depilation")])

            extra.append([InlineKeyboardButton("◀️ Назад", callback_data="main:booking")])
            await query.edit_message_text(
                hp(f"📅 Запись → {cat['title']}",
                   f"{cat['title']}\n\nВыберите категорию:"),
                reply_markup=kb(*(keyboard + extra))
            )
            return

        # Простая категория (электроэпиляция)
        keyboard = []
        for i, s in enumerate(cat["services"]):
            keyboard.append([InlineKeyboardButton(f"{s['name']} — {s['price']}",
                                                  callback_data=f"srv:{code}:{i}")])
        keyboard.append([InlineKeyboardButton("📚 Как подготовиться к электроэпиляции",
                                              callback_data="prep:epilation")])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="main:booking")])
        await query.edit_message_text(
            hp(f"📅 Запись → {cat['title']}",
               f"{cat['title']}\n\nВыберите длительность:"),
            reply_markup=kb(*keyboard)
        )
        return

    # sub:parent:sub_code
    if data.startswith("sub:"):
        parts = data.split(":")
        parent_code, sub_code = parts[1], parts[2]
        parent = BOOKING[parent_code]
        sub = next((s for s in parent["sub"] if s["code"] == sub_code), None)
        if not sub:
            await query.edit_message_text("⚠️ Подкатегория не найдена.")
            return

        # Подкатегория с подподкатегориями
        if "sub" in sub:
            keyboard = []
            for s2 in sub["sub"]:
                keyboard.append([InlineKeyboardButton(s2["title"], callback_data=f"sub2:{parent_code}:{sub_code}:{s2['code']}")])
            keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data=f"book:{parent_code}")])
            await query.edit_message_text(
                hp(f"📅 Запись → {parent['title']} → {sub['title']}",
                   f"{sub['title']}\n\nВыберите:"),
                reply_markup=kb(*keyboard)
            )
            return

        # Подкатегория со списком услуг
        keyboard = []
        for i, s in enumerate(sub["services"]):
            keyboard.append([InlineKeyboardButton(f"{s['name']} — {s['price']}",
                                                  callback_data=f"srv2:{parent_code}:{sub_code}:{i}")])

        extra = []
        # Кнопка абонемента для лазера и коррекции фигуры
        if parent_code == "laser":
            extra.append([InlineKeyboardButton("💬 Узнать про абонементы", url=URL_SUBSCRIPTION)])
        elif parent_code == "body":
            extra.append([InlineKeyboardButton("💬 Узнать про абонементы", url=URL_SUBSCRIPTION)])

        extra.append([InlineKeyboardButton("◀️ Назад", callback_data=f"book:{parent_code}")])

        await query.edit_message_text(
            hp(f"📅 Запись → {parent['title']} → {sub['title']}",
               f"{sub['title']}\n\nВыберите:"),
            reply_markup=kb(*(keyboard + extra))
        )
        return

    # sub2:parent:sub:sub2
    if data.startswith("sub2:"):
        parts = data.split(":")
        parent_code, sub_code, sub2_code = parts[1], parts[2], parts[3]
        parent = BOOKING[parent_code]
        sub = next(s for s in parent["sub"] if s["code"] == sub_code)
        sub2 = next(s for s in sub["sub"] if s["code"] == sub2_code)

        keyboard = []
        for i, s in enumerate(sub2["services"]):
            keyboard.append([InlineKeyboardButton(f"{s['name']} — {s['price']}",
                                                  callback_data=f"srv3:{parent_code}:{sub_code}:{sub2_code}:{i}")])

        extra = []
        if parent_code == "laser":
            extra.append([InlineKeyboardButton("💬 Узнать про абонементы", url=URL_SUBSCRIPTION)])

        extra.append([InlineKeyboardButton("◀️ Назад", callback_data=f"sub:{parent_code}:{sub_code}")])

        await query.edit_message_text(
            hp(f"📅 Запись → {parent['title']} → {sub2['title']}",
               f"{sub2['title']}\n\nВыберите:"),
            reply_markup=kb(*(keyboard + extra))
        )
        return

    # srv:code:idx — простая категория
    if data.startswith("srv:") and data.count(":") == 2:
        parts = data.split(":")
        code, idx = parts[1], int(parts[2])
        s = BOOKING[code]["services"][idx]
        await show_service_result(query, s, f"book:{code}", code)
        return

    # srv2:parent:sub:idx
    if data.startswith("srv2:"):
        parts = data.split(":")
        parent_code, sub_code, idx = parts[1], parts[2], int(parts[3])
        parent = BOOKING[parent_code]
        sub = next(s for s in parent["sub"] if s["code"] == sub_code)
        s = sub["services"][idx]
        await show_service_result(query, s, f"sub:{parent_code}:{sub_code}", parent_code)
        return

    # srv3:parent:sub:sub2:idx
    if data.startswith("srv3:"):
        parts = data.split(":")
        parent_code, sub_code, sub2_code, idx = parts[1], parts[2], parts[3], int(parts[4])
        parent = BOOKING[parent_code]
        sub = next(s for s in parent["sub"] if s["code"] == sub_code)
        sub2 = next(s for s in sub["sub"] if s["code"] == sub2_code)
        s = sub2["services"][idx]
        await show_service_result(query, s, f"sub2:{parent_code}:{sub_code}:{sub2_code}", parent_code)
        return


async def show_service_result(query, service, back_callback, parent_code):
    """Экран с результатом — ссылка на DiKidi."""
    text_lines = [
        f"✅ {service['name']} — {service['price']}",
        "",
    ]

    # Дополнительная информация для комплексов
    duration = service.get("duration")
    if duration:
        text_lines.append(f"⏱ Длительность: {duration}")

    # Состав комплекса (из названия в скобках)
    if "(" in service["name"] and ")" in service["name"]:
        inside = service["name"][service["name"].find("(")+1:service["name"].rfind(")")]
        if inside:
            text_lines.append("")
            text_lines.append("Состав:")
            text_lines.append(f"• {inside}")

    text_lines.append("")
    text_lines.append("Нажмите «Открыть календарь записи».")
    text_lines.append("")
    text_lines.append("📲 Если при подтверждении DiKidi попросит код «в приложении», но приложения у вас нет или код не пришёл — нажмите в окне DiKidi «Не пришёл код» → подтвердите, что вы не бот (капча «Я не бот»).")
    text_lines.append("")
    text_lines.append(f"Контакты: {PHONE_DISPLAY} (Telegram / WhatsApp / МАХ)")

    keyboard = [
        [InlineKeyboardButton("📅 Открыть календарь записи", url=service["url"])],
    ]

    # Кнопка подготовки для родительской категории
    prep_map = {
        "epilation": "prep:epilation",
        "laser":     "prep:laser",
        "depilation":"prep:depilation",
    }
    if parent_code in prep_map:
        keyboard.append([InlineKeyboardButton("📚 Как подготовиться", callback_data=prep_map[parent_code])])

    # Абонемент — над "Назад"
    if parent_code in ("laser", "body"):
        keyboard.append([InlineKeyboardButton("💬 Узнать про абонементы", url=URL_SUBSCRIPTION)])

    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data=back_callback)])
    keyboard.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])
    keyboard.append([InlineKeyboardButton("❌ Закрыть", callback_data="main:close")])

    await query.edit_message_text(
        hp("📅 Запись → услуга", "\n".join(text_lines)),
        reply_markup=kb(*keyboard)
    )


# ==============================================
# 2. ПОДГОТОВКА
# ==============================================

async def show_prep_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    keyboard = [
        [InlineKeyboardButton("⚡ Электроэпиляция", callback_data="prep:epilation")],
        [InlineKeyboardButton("💡 Лазерная эпиляция", callback_data="prep:laser")],
        [InlineKeyboardButton("🌿 Депиляция", callback_data="prep:depilation")],
        [InlineKeyboardButton("◀️ Назад", callback_data="main:menu")],
    ]
    await query.edit_message_text(
        hp("📚 Подготовка", "📚 Подготовка к процедуре\n\nВыберите тип:"),
        reply_markup=kb(*keyboard)
    )


async def prep_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    code = query.data.split(":", 1)[1]
    text = PREP_TEXTS.get(code, "Информация недоступна.")

    titles = {
        "epilation": "электроэпиляции",
        "laser": "лазерной эпиляции",
        "depilation": "депиляции",
    }
    after_title = titles.get(code, "процедуры")

    keyboard = [
        [InlineKeyboardButton(f"💆 Уход после {after_title}", callback_data=f"after:{code}")],
        [InlineKeyboardButton("◀️ Назад", callback_data="main:prep")],
        [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
    ]
    await query.edit_message_text(
        hp(f"📚 Подготовка → {after_title}", text),
        reply_markup=kb(*keyboard)
    )


# ==============================================
# 3. УХОД
# ==============================================

async def show_after_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    keyboard = [
        [InlineKeyboardButton("⚡ Электроэпиляция", callback_data="after:epilation")],
        [InlineKeyboardButton("💡 Лазерная эпиляция", callback_data="after:laser")],
        [InlineKeyboardButton("🌿 Депиляция", callback_data="after:depilation")],
        [InlineKeyboardButton("◀️ Назад", callback_data="main:menu")],
    ]
    await query.edit_message_text(
        hp("💆 Уход", "💆 Уход после процедуры\n\nВыберите тип:"),
        reply_markup=kb(*keyboard)
    )


async def after_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    code = query.data.split(":", 1)[1]
    text = AFTER_TEXTS.get(code, "Информация недоступна.")

    titles = {
        "epilation": "электроэпиляции",
        "laser": "лазерной эпиляции",
        "depilation": "депиляции",
    }
    prep_title = titles.get(code, "процедуры")

    keyboard = [
        [InlineKeyboardButton(f"📚 Подготовка к {prep_title}", callback_data=f"prep:{code}")],
        [InlineKeyboardButton("◀️ Назад", callback_data="main:after")],
        [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
    ]
    await query.edit_message_text(
        hp(f"💆 Уход → {prep_title}", text),
        reply_markup=kb(*keyboard)
    )


# ==============================================
# 4. ПРАЙС-ЛИСТ
# ==============================================

async def show_price_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    keyboard = [
        [InlineKeyboardButton("⚡ Электроэпиляция", callback_data="price:epilation")],
        [InlineKeyboardButton("💡 Лазерная эпиляция", callback_data="price:laser")],
        [InlineKeyboardButton("🌿 Депиляция", callback_data="price:depilation")],
        [InlineKeyboardButton("🔸 Коррекция фигуры", callback_data="price:body")],
        [InlineKeyboardButton("🔹 Косметология", callback_data="price:cosmetology")],
        [InlineKeyboardButton("◀️ Назад", callback_data="main:menu")],
    ]
    await query.edit_message_text(
        hp("📋 Прайс-лист", "📋 Прайс-лист MintGlow\n\nВыберите раздел:"),
        reply_markup=kb(*keyboard)
    )


async def price_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    code = query.data.split(":", 1)[1]

    texts = {
        "epilation": (
            "⚡ Электроэпиляция\n\n"
            "📌 Минимальная запись — 30 минут.\n"
            "📌 Цена одинаковая для всех зон — от 60 ₽/мин.\n"
            "📌 Все расходники включены в стоимость, кроме отдельных случаев (уточняйте у мастера/администратора).\n\n"
            "• 30 минут — от 1 800 ₽\n"
            "• 1 час — от 3 600 ₽\n"
            "• 1,5 часа — от 5 400 ₽\n"
            "• 2 часа — от 7 200 ₽\n"
            "• 3 часа — от 10 800 ₽\n\n"
            "📌 Точная стоимость зависит от мастера и отображается при создании записи в DiKidi."
        ),
        "laser": (
            "💡 Лазерная эпиляция\n\n"
            "Комплексы:\n"
            "• Комплекс 1 — от 2 850 ₽ (подмышки + бикини глубокое)\n"
            "• Комплекс 2 — от 5 225 ₽ (подмышки + бикини глубокое + голени)\n"
            "• Комплекс 3 — от 6 175 ₽ (подмышки + бикини глубокое + ноги полностью)\n"
            "• Комплекс 4 — от 8 500 ₽ (подмышки + бикини глубокое + ноги полностью + руки полностью)\n"
            "• Комплекс 5 — от 9 500 ₽ (всё тело)\n\n"
            "Отдельные зоны:\n"
            "• Верхняя губа — от 800 ₽\n"
            "• Бакенбарды — от 800 ₽\n"
            "• Подбородок — от 800 ₽\n"
            "• Лицо полностью — от 2 000 ₽\n"
            "• Шея — от 1 000 ₽\n"
            "• Декольте — от 2 000 ₽\n"
            "• Подмышки — от 1 000 ₽\n"
            "• Руки выше локтя — от 2 000 ₽\n"
            "• Руки полностью — от 2 500 ₽\n"
            "• Линия живота — от 1 000 ₽\n"
            "• Живот полностью — от 2 000 ₽\n"
            "• Поясница — от 1 000 ₽\n"
            "• Ягодицы — от 2 000 ₽\n"
            "• Бёдра — от 2 500 ₽\n"
            "• Голени — от 2 500 ₽\n"
            "• Ноги полностью — от 3 500 ₽\n"
            "• Бикини классическое — от 1 000 ₽\n"
            "• Бикини глубокое — от 2 000 ₽\n"
            "• Пальцы ног — от 800 ₽\n\n"
            "🎁 Скидка на абонемент:\n"
            "• 5 процедур — 5%\n"
            "• 10 процедур — 15%"
        ),
        "depilation": (
            "🌿 Депиляция (воск)\n\n"
            "Комплексы:\n"
            "• Мини — от 2 500 ₽\n"
            "• Стандарт — от 3 000 ₽\n"
            "• Максимум — от 3 500 ₽\n\n"
            "Отдельные зоны:\n"
            "• Лицо полностью — от 1 200 ₽\n"
            "• Бикини классическое — от 1 500 ₽\n"
            "• Глубокое бикини — от 2 000 ₽\n"
            "• Подмышки — от 800 ₽\n"
            "• Руки до локтя — от 800 ₽\n"
            "• Руки полностью — от 1 200 ₽\n"
            "• Ноги до колена — от 1 200 ₽\n"
            "• Ноги полностью — от 1 800 ₽\n"
            "• Бедро (выше колена) — от 1 000 ₽\n"
            "• Ягодицы — от 1 000 ₽"
        ),
        "body": (
            "🔸 Коррекция фигуры\n\n"
            "Комплексы:\n"
            "• Комплекс 2в1 — от 4 500 ₽ / 60 мин\n"
            "• Комплекс 3в1 — от 6 750 ₽ / 90 мин\n\n"
            "Отдельные процедуры:\n"
            "• Сфера тела (60 мин) — от 4 500 ₽\n"
            "• Сфера тела (30 мин) — от 3 000 ₽\n"
            "• Микроволны (30 мин) — от 3 000 ₽\n"
            "• Горячий вакуум (30 мин) — от 3 000 ₽\n"
            "• Индиба (30 мин) — от 1 500 ₽\n\n"
            "🎁 Скидка на абонемент:\n"
            "• 5 процедур — 5%\n"
            "• 10 процедур — 15%"
        ),
        "cosmetology": (
            "🔹 Косметология и уход за лицом\n\n"
            "Чистки:\n"
            "• Комбинированная (105 мин) — от 5 000 ₽\n"
            "• УЗ-чистка (90 мин) — от 4 000 ₽\n"
            "• Механическая (90 мин) — от 4 000 ₽\n\n"
            "Уходы:\n"
            "• Line Repair (60 мин) — от 4 000 ₽\n"
            "• Line Repair + массаж (90 мин) — от 5 000 ₽\n"
            "• Unstress (60 мин) — от 3 600 ₽\n"
            "• Unstress + массаж (90 мин) — от 4 500 ₽\n"
            "• Bio Phyto (60 мин) — от 3 500 ₽\n"
            "• Bio Phyto + массаж (90 мин) — от 4 500 ₽\n"
            "• Карбокситерапия (60 мин) — от 3 500 ₽\n"
            "• Карбокситерапия + массаж (90 мин) — от 4 500 ₽\n"
            "• Comodex (60 мин) — от 3 700 ₽\n"
            "• Дарсонваль (30 мин) — от 1 000 ₽\n\n"
            "Пилинги:\n"
            "• Rose de Mer (75 мин) — от 4 000 ₽\n"
            "• Миндальный (75 мин) — от 3 500 ₽\n\n"
            "Аппаратные массажи:\n"
            "• Сфера для лица (30 мин) — от 3 000 ₽\n"
            "• Комплекс для лица — от 4 000 ₽\n\n"
            "Ручной массаж:\n"
            "• Массаж лица по маске/крему (30 мин) — от 2 000 ₽\n"
            "• Маска для лица (30 мин) — от 500 ₽"
        ),
    }

    text = texts.get(code, "Информация недоступна.")

    keyboard = [
        [InlineKeyboardButton("📅 Записаться", callback_data="main:booking")],
    ]

    # Кнопка подготовки для соответствующих разделов
    prep_map = {
        "epilation": "prep:epilation",
        "laser":     "prep:laser",
        "depilation":"prep:depilation",
    }
    if code in prep_map:
        keyboard.append([InlineKeyboardButton("📚 Как подготовиться", callback_data=prep_map[code])])

    # Абонемент — над "Назад"
    if code in ("laser", "body"):
        keyboard.append([InlineKeyboardButton("💬 Узнать про абонементы", url=URL_SUBSCRIPTION)])

    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="main:price")])

    await query.edit_message_text(
        hp(f"📋 Прайс → {code}", text),
        reply_markup=kb(*keyboard)
    )


# ==============================================
# 5. АКЦИИ И БОНУСЫ
# ==============================================

async def show_promo_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    keyboard = [
        [InlineKeyboardButton("🎮 Игра «Идеальный визит»", callback_data="promo:game")],
        [InlineKeyboardButton("✨ Знакомство с мастером", callback_data="promo:new")],
        [InlineKeyboardButton("📦 Абонементы", callback_data="promo:subscriptions")],
        [InlineKeyboardButton("💰 Мои бонусы", callback_data="promo:bonus")],
        [InlineKeyboardButton("🎁 Подарочный сертификат", callback_data="promo:certificate")],
        [InlineKeyboardButton("👯 Приведи подругу", callback_data="promo:friend")],
        [InlineKeyboardButton("📢 Другие акции", callback_data="promo:other")],
        [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
    ]
    await query.edit_message_text(
        hp("🎁 Акции и бонусы",
           "🎁 Акции и бонусы\n\n💡 Не нашли нужное? Нажмите «✍️ Задать вопрос»."),
        reply_markup=kb(*keyboard)
    )


async def promo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    code = query.data.split(":", 1)[1]

    text = PROMO_TEXTS.get(code, "Информация недоступна.")

    # Клавиатура зависит от раздела
    if code == "game":
        keyboard = [
            [InlineKeyboardButton("💬 Узнать количество бонусов", url=URL_BONUS_BALANCE)],
            [InlineKeyboardButton("📅 Записаться", callback_data="main:booking")],
            [InlineKeyboardButton("◀️ Назад", callback_data="main:promo")],
        ]
    elif code == "new":
        keyboard = [
            [InlineKeyboardButton("📅 Записаться на электроэпиляцию", callback_data="book:epilation")],
            [InlineKeyboardButton("◀️ Назад", callback_data="main:promo")],
        ]
    elif code == "subscriptions":
        keyboard = [
            [InlineKeyboardButton("💬 Узнать про абонементы", url=URL_SUBSCRIPTION)],
            [InlineKeyboardButton("◀️ Назад", callback_data="main:promo")],
        ]
    elif code == "bonus":
        keyboard = [
            [InlineKeyboardButton("💬 Узнать баланс бонусов", url=URL_BONUS_BALANCE)],
            [InlineKeyboardButton("◀️ Назад", callback_data="main:promo")],
        ]
    elif code == "certificate":
        keyboard = [
            [InlineKeyboardButton("💬 Купить сертификат", url=URL_CERTIFICATE)],
            [InlineKeyboardButton("◀️ Назад", callback_data="main:promo")],
        ]
    elif code == "friend":
        keyboard = [
            [InlineKeyboardButton("💬 Сообщить администратору", url=URL_FRIEND)],
            [InlineKeyboardButton("◀️ Назад", callback_data="main:promo")],
        ]
    elif code == "other":
        keyboard = [
            [InlineKeyboardButton("📢 Открыть Telegram-канал", url=URL_TELEGRAM_CHANNEL)],
            [InlineKeyboardButton("◀️ Назад", callback_data="main:promo")],
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("◀️ Назад", callback_data="main:promo")],
        ]

    await query.edit_message_text(
        hp(f"🎁 Акции → {code}", text),
        reply_markup=kb(*keyboard)
    )


# ==============================================
# 6. О СТУДИИ
# ==============================================

async def show_about_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    keyboard = [
        [InlineKeyboardButton("👩‍🎨 Наши мастера",           callback_data="about:masters")],
        [InlineKeyboardButton("📍 Как добраться",            callback_data="about:route")],
        [InlineKeyboardButton("⭐ Оставить отзыв",           callback_data="about:review")],
        [InlineKeyboardButton("📢 Мы в соцсетях",            callback_data="about:social")],
        [InlineKeyboardButton("❓ Ответы про запись и оплату", callback_data="about:faq")],
        [InlineKeyboardButton("📖 Отзывы клиентов",          callback_data="about:client_reviews")],
        [InlineKeyboardButton("🏠 В начало",                 callback_data="main:menu")],
    ]
    await query.edit_message_text(
        hp("ℹ️ О студии", "ℹ️ О студии\n\nВыберите раздел:"),
        reply_markup=kb(*keyboard)
    )


async def about_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data.split(":", 1)[1]

    # --- Мастера ---
    if data == "masters":
        keyboard = []
        for code, m in MASTERS.items():
            keyboard.append([InlineKeyboardButton(m["title"], callback_data=f"master:{code}")])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="main:about")])
        await query.edit_message_text(
            hp("ℹ️ О студии → Наши мастера",
               "👩‍🎨 Наши мастера\n\nВыберите мастера:"),
            reply_markup=kb(*keyboard)
        )
        return

    # --- Как добраться ---
    if data == "route":
        text = (
            "📍 Адрес\n"
            "Москва, Ленинградское шоссе, 9к1\n"
            "м. Войковская, последний вагон из центра, выход 4\n"
            "3 минуты пешком\n\n"
            "🚶 Как найти\n"
            "Вход со стороны Ленинградского шоссе (дублёр), посередине дома.\n"
            "Вывеска «СТУДИЯ ЭПИЛЯЦИИ».\n\n"
            "Ориентиры: рядом с магазином «ВинЛаб» и композицией из красных цветов и листьев у входа.\n\n"
            "Далее по коридору."
        )
        keyboard = [
            [InlineKeyboardButton("📸 Фото входа", url=URL_ENTRANCE_PHOTO)],
            [InlineKeyboardButton("🗺 Яндекс.Карты", url=URL_MAPS_YANDEX)],
            [InlineKeyboardButton("🗺 Google Maps", url=URL_MAPS_GOOGLE)],
            [InlineKeyboardButton("◀️ Назад", callback_data="main:about")],
        ]
        await query.edit_message_text(
            hp("ℹ️ О студии → Как добраться", text),
            reply_markup=kb(*keyboard)
        )
        return

    # --- Оставить отзыв ---
    if data == "review":
        text = (
            "⭐ Ваше мнение очень важно!\n\n"
            "За отзыв начисляем 300 бонусов,\n"
            "за отзыв с фото — 400 бонусов.\n\n"
            "Оставить отзыв:\n\n"
            "После того как вы оставили отзыв — нажмите кнопку ниже, "
            "и отправьте скриншот, чтобы администратор начислил бонусы."
        )
        keyboard = [
            [InlineKeyboardButton("Яндекс Карты", url=URL_REVIEW_YANDEX),
             InlineKeyboardButton("2ГИС", url=URL_REVIEW_2GIS)],
            [InlineKeyboardButton("Zoon", url=URL_REVIEW_Zoon),
             InlineKeyboardButton("Google", url=URL_REVIEW_GOOGLE)],
            [InlineKeyboardButton("💬 Сообщить об отзыве", url=URL_REVIEW)],
            [InlineKeyboardButton("◀️ Назад", callback_data="main:about")],
        ]
        await query.edit_message_text(
            hp("ℹ️ О студии → Оставить отзыв", text),
            reply_markup=kb(*keyboard)
        )
        return

    # --- Соцсети ---
    if data == "social":
        text = (
            "📢 Мы в соцсетях\n\n"
            "• Telegram-канал — акции и горящие места\n"
            "• Instagram — фото, отзывы, истории\n"
            "• VK — новости студии"
        )
        keyboard = [
            [InlineKeyboardButton("✈️ Telegram-канал", url=URL_TELEGRAM_CHANNEL)],
            [InlineKeyboardButton("📸 Instagram", url=URL_INSTAGRAM)],
            [InlineKeyboardButton("🅥 VK", url=URL_VK)],
            [InlineKeyboardButton("◀️ Назад", callback_data="main:about")],
        ]
        await query.edit_message_text(
            hp("ℹ️ О студии → Соцсети", text),
            reply_markup=kb(*keyboard)
        )
        return

    # --- FAQ ---
    if data == "faq":
        keyboard = [
            [InlineKeyboardButton("Как можно оплатить?", callback_data="faq:pay")],
            [InlineKeyboardButton("Как отменить или перенести запись?", callback_data="faq:cancel")],
            [InlineKeyboardButton("Что делать, если опаздываю?", callback_data="faq:late")],
            [InlineKeyboardButton("Можно ли записаться день в день?", callback_data="faq:same_day")],
            [InlineKeyboardButton("Как связаться с администратором?", callback_data="faq:contact")],
            [InlineKeyboardButton("◀️ Назад", callback_data="main:about")],
        ]
        await query.edit_message_text(
            hp("ℹ️ О студии → Ответы про запись и оплату",
               "❓ Ответы про запись и оплату\n\nВыберите вопрос:"),
            reply_markup=kb(*keyboard)
        )
        return

    # --- Отзывы клиентов ---
    if data == "client_reviews":
        text = (
            "📖 Отзывы клиентов\n\n"
            "Читайте реальные отзывы о студии MintGlow на Яндекс.Картах."
        )
        keyboard = [
            [InlineKeyboardButton("📖 Читать отзывы", url=URL_CLIENT_REVIEWS)],
            [InlineKeyboardButton("◀️ Назад", callback_data="main:about")],
        ]
        await query.edit_message_text(
            hp("ℹ️ О студии → Отзывы клиентов", text),
            reply_markup=kb(*keyboard)
        )
        return


async def master_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    code = query.data.split(":", 1)[1]
    m = MASTERS.get(code)
    if not m:
        await query.edit_message_text("⚠️ Мастер не найден.")
        return

    keyboard = [
        [InlineKeyboardButton("📅 Записаться", url=DIKIDI_URL)],
        [InlineKeyboardButton("◀️ К списку мастеров", callback_data="about:masters")],
        [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
    ]
    await query.edit_message_text(
        hp(f"ℹ️ О студии → Мастера → {m['title']}", m["card"]),
        reply_markup=kb(*keyboard)
    )


# ==============================================
# FAQ
# ==============================================

async def faq_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    code = query.data.split(":", 1)[1]

    # Контакт — отдельный экран
    if code == "contact":
        text = (
            f"📞 {PHONE_DISPLAY}\n"
            f"(нажмите, чтобы позвонить)"
        )
        keyboard = [
            [InlineKeyboardButton("📞 Позвонить", url=PHONE_TEL)],
            [InlineKeyboardButton("✈️ Telegram", url=URL_QUESTION)],
            [InlineKeyboardButton("💬 WhatsApp", url=URL_WHATSAPP)],
            [InlineKeyboardButton("📱 МАХ", url=URL_MAX)],
            [InlineKeyboardButton("◀️ Назад", callback_data="about:faq")],
        ]
        await query.edit_message_text(
            hp("ℹ️ О студии → FAQ → Связь", text),
            reply_markup=kb(*keyboard)
        )
        return

    # Тексты
    text = FAQ_TEXTS.get(code, "Информация недоступна.")

    # Клавиатура
    if code == "cancel":
        keyboard = [
            [InlineKeyboardButton("🔄 Перенести запись", url=URL_TRANSFER)],
            [InlineKeyboardButton("❌ Отменить запись", url=URL_CANCEL)],
            [InlineKeyboardButton("◀️ Назад", callback_data="about:faq")],
        ]
    elif code == "pay":
        keyboard = [
            [InlineKeyboardButton("💬 Написать администратору", url=URL_PAYMENT)],
            [InlineKeyboardButton("◀️ Назад", callback_data="about:faq")],
        ]
    elif code == "late":
        keyboard = [
            [InlineKeyboardButton("💬 Написать администратору", url=URL_LATE)],
            [InlineKeyboardButton("◀️ Назад", callback_data="about:faq")],
        ]
    elif code == "same_day":
        keyboard = [
            [InlineKeyboardButton("💬 Написать администратору", url=URL_SAME_DAY)],
            [InlineKeyboardButton("◀️ Назад", callback_data="about:faq")],
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("◀️ Назад", callback_data="about:faq")],
        ]

    await query.edit_message_text(
        hp(f"ℹ️ О студии → FAQ", text),
        reply_markup=kb(*keyboard)
    )


# ==============================================
# 7. ЗАДАТЬ ВОПРОС
# ==============================================

async def show_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text = (
        "✍️ Задать вопрос администратору\n\n"
        "Перейдите в чат со студией — администратор ответит в ближайшее время."
    )
    keyboard = [
        [InlineKeyboardButton("💬 Написать администратору", url=URL_QUESTION)],
        [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
    ]
    await query.edit_message_text(
        hp("✍️ Задать вопрос", text),
        reply_markup=kb(*keyboard)
    )


# ==============================================
# ОБРАБОТКА ТЕКСТА
# ==============================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    text_lower = user_text.lower()

    # Ключевые слова → разделы
    if any(k in text_lower for k in ["записаться", "запись", "запишите"]):
        keyboard = []
        for code, cat in BOOKING.items():
            keyboard.append([InlineKeyboardButton(cat["title"], callback_data=f"book:{code}")])
        keyboard.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])
        await update.message.reply_text(
            hp("📅 Запись", "📅 Запись онлайн\n\nВыберите направление:"),
            reply_markup=kb(*keyboard)
        )
        return

    if any(k in text_lower for k in ["подготовка", "подготовиться"]):
        keyboard = [
            [InlineKeyboardButton("⚡ Электроэпиляция", callback_data="prep:epilation")],
            [InlineKeyboardButton("💡 Лазерная эпиляция", callback_data="prep:laser")],
            [InlineKeyboardButton("🌿 Депиляция", callback_data="prep:depilation")],
            [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
        ]
        await update.message.reply_text(
            hp("📚 Подготовка", "📚 Подготовка к процедуре\n\nВыберите тип:"),
            reply_markup=kb(*keyboard)
        )
        return

    if any(k in text_lower for k in ["уход", "после процедуры"]):
        keyboard = [
            [InlineKeyboardButton("⚡ Электроэпиляция", callback_data="after:epilation")],
            [InlineKeyboardButton("💡 Лазерная эпиляция", callback_data="after:laser")],
            [InlineKeyboardButton("🌿 Депиляция", callback_data="after:depilation")],
            [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
        ]
        await update.message.reply_text(
            hp("💆 Уход", "💆 Уход после процедуры\n\nВыберите тип:"),
            reply_markup=kb(*keyboard)
        )
        return

    if any(k in text_lower for k in ["акции", "скидки", "бонусы"]):
        await show_promo_menu_from_message(update, context)
        return

    if any(k in text_lower for k in ["цена", "прайс", "стоимость"]):
        keyboard = [
            [InlineKeyboardButton("⚡ Электроэпиляция", callback_data="price:epilation")],
            [InlineKeyboardButton("💡 Лазерная эпиляция", callback_data="price:laser")],
            [InlineKeyboardButton("🌿 Депиляция", callback_data="price:depilation")],
            [InlineKeyboardButton("🔸 Коррекция фигуры", callback_data="price:body")],
            [InlineKeyboardButton("🔹 Косметология", callback_data="price:cosmetology")],
            [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
        ]
        await update.message.reply_text(
            hp("📋 Прайс-лист", "📋 Прайс-лист MintGlow\n\nВыберите раздел:"),
            reply_markup=kb(*keyboard)
        )
        return

    # Всё остальное — уведомляем админа
    sent = await notify_admin(update, context, tag="", extra=f"💬 Сообщение: {user_text}")

    if sent:
        text = (
            "✍️ Я передал ваш вопрос администратору. "
            "Он ответит в ближайшее время.\n\n"
            "Если срочно — напишите напрямую:"
        )
    else:
        text = (
            "✍️ Ваш вопрос будет передан администратору.\n\n"
            "Если срочно — напишите напрямую:"
        )

    keyboard = [
        [InlineKeyboardButton("💬 Написать администратору", url=URL_QUESTION)],
        [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
    ]
    await update.message.reply_text(text, reply_markup=kb(*keyboard))


async def show_promo_menu_from_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🎮 Игра «Идеальный визит»", callback_data="promo:game")],
        [InlineKeyboardButton("✨ Знакомство с мастером", callback_data="promo:new")],
        [InlineKeyboardButton("📦 Абонементы", callback_data="promo:subscriptions")],
        [InlineKeyboardButton("💰 Мои бонусы", callback_data="promo:bonus")],
        [InlineKeyboardButton("🎁 Подарочный сертификат", callback_data="promo:certificate")],
        [InlineKeyboardButton("👯 Приведи подругу", callback_data="promo:friend")],
        [InlineKeyboardButton("📢 Другие акции", callback_data="promo:other")],
        [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
    ]
    await update.message.reply_text(
        hp("🎁 Акции и бонусы", "🎁 Акции и бонусы\n\nВыберите раздел:"),
        reply_markup=kb(*keyboard)
    )


# ==============================================
# ЗАПУСК
# ==============================================

def run_bot():
    print("⏳ Ожидание 5 секунд перед запуском...")
    time.sleep(5)

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("reply", reply_to_user))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(universal_callback))

    print("✅ Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
