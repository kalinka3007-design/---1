#!/usr/bin/env python3
"""apply_changes.py — улучшения корзины и 4hands через точечные замены."""
import ast
from pathlib import Path


def patch(file, pairs):
    path = Path(file)
    if not path.exists():
        print(f"❌ Файл не найден: {file}")
        return False
    src = path.read_text(encoding="utf-8")
    original = src
    ok = 0
    fail = 0
    for old, new, label in pairs:
        if old not in src:
            print(f"  ❌ {label} — паттерн не найден")
            fail += 1
            continue
        src = src.replace(old, new, 1)
        print(f"  ✅ {label}")
        ok += 1
    if src == original:
        print(f"  ⚠️ {file} не изменён")
        return False
    try:
        ast.parse(src)
    except SyntaxError as e:
        print(f"❌ Синтаксическая ошибка после правки: {e}")
        print("   Файл НЕ сохранён — исходник цел")
        return False
    path.write_text(src, encoding="utf-8")
    print(f"  💾 {file} сохранён (применено {ok}, ошибок {fail})")
    return fail == 0


# ============================================================
# SLOT_FINDER.PY
# ============================================================

SLOT_PATCHES = [
# --- 1. _render_service_pick ---
("""async def _render_service_pick(update, context, s, back_cb, parent_code):
    \"\"\"Промежуточный экран: [🛍️ В корзину] [🔎 Сразу найти время]\"\"\"
    q = update.callback_query
    name = context.user_data.get("slot_master_name", "")

    text = f"✅ {s['name']} — {s['price']}"
    if s.get("duration"):
        text += f" · {_format_duration(s['duration'])}"
    text += "\\n\\nЧто сделать?"

    rows = [
        [InlineKeyboardButton("🛍️ В корзину", callback_data="slot:cart_add")],
        [InlineKeyboardButton("🔎 Сразу найти время", callback_data="slot:direct_find")],
        [InlineKeyboardButton("◀️ К услугам", callback_data=back_cb)],
        [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
    ]
    await safe_edit(q, context, hp(f"📅 Хочу записаться → {name} → {s['name']}", text), kb(*rows))""",
"""async def _render_service_pick(update, context, s, back_cb, parent_code):
    \"\"\"Промежуточный экран: «Только на эту» / «Вместе с другими».\"\"\"
    q = update.callback_query
    name = context.user_data.get("slot_master_name", "")
    mid = context.user_data.get("slot_master_id", "")
    cart_carts = _cart_get(context)
    cart_cart = cart_carts.get(mid, {})
    cart_n = len(cart_cart.get("services", []))
    cart_time = sum((x.get("time") or 0) for x in cart_cart.get("services", []))

    text = f"✅ {s['name']} — {s['price']}"
    if s.get("duration"):
        text += f" · {_format_duration(s['duration'])}"
    text += "\\n\\n"

    at_max = len(cart_carts) >= 2 and mid not in cart_carts

    if at_max:
        text += ("⚠️ У вас уже 2 корзины для разных мастеров — это максимум.\\n\\n"
                 "Завершите одну из них или очистите, чтобы добавить эту услугу.")
        rows = [
            [InlineKeyboardButton("🔎 Только на эту", callback_data="slot:direct_find")],
            [InlineKeyboardButton("🛍️ Открыть корзины", callback_data="slot:cart_view")],
            [InlineKeyboardButton("◀️ К услугам", callback_data=back_cb)],
            [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
        ]
    else:
        if cart_n:
            text += (f"🛍️ В корзине уже {cart_n} {_plural_services(cart_n)}")
            if cart_time:
                text += f" ({_format_duration(cart_time)})"
            text += ".\\n\\n"
        text += "Как хотите записаться?\\n\\n"
        text += "🔎 «Только на эту» — сразу найдём свободное время под одну услугу.\\n\\n"
        text += ("🛍️ «Вместе с другими» — добавим в корзину и поищем общее время "
                 "на все выбранные услуги за один визит.")
        add_label = "🛍️ Вместе с другими" if not cart_n else f"🛍️ Добавить к {cart_n} услугам"
        rows = [
            [InlineKeyboardButton("🔎 Только на эту", callback_data="slot:direct_find")],
            [InlineKeyboardButton(add_label, callback_data="slot:cart_add")],
            [InlineKeyboardButton("◀️ К услугам", callback_data=back_cb)],
            [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
        ]

    await safe_edit(q, context,
                    hp(f"📅 Хочу записаться → {name} → {s['name']}", text),
                    kb(*rows))""",
"_render_service_pick — новый промежуточный экран"),

# --- 2. _cart_add — лимит 2 корзин ---
("""def _cart_add(context, master_id: str, master_name: str, service: dict) -> tuple[bool, str]:
    \"\"\"Добавить услугу. Возвращает (ok, reason).\"\"\"
    carts = _cart_get(context)
    cart = carts.setdefault(master_id, {""",
"""def _cart_add(context, master_id: str, master_name: str, service: dict) -> tuple[bool, str]:
    \"\"\"Добавить услугу. Возвращает (ok, reason).\"\"\"
    carts = _cart_get(context)
    if master_id not in carts and len(carts) >= 2:
        return False, "max_carts"
    cart = carts.setdefault(master_id, {""",
"_cart_add — лимит 2 корзин"),

# --- 3. slot_cart_add_from_state — обработка max_carts ---
("""        if reason == "limit":
            text = (f"⚠️ В корзине уже {CART_MAX_SERVICES} услуги — "
                    f"больше не влезет в один визит.\\n\\n"
                    f"Услугу «{sname}» не добавили.")""",
"""        if reason == "max_carts":
            text = ("⚠️ У вас уже 2 корзины для разных мастеров — это максимум.\\n\\n"
                    "Завершите одну из них или очистите, чтобы добавить эту услугу.")
        elif reason == "limit":
            text = (f"⚠️ В корзине уже {CART_MAX_SERVICES} услуги — "
                    f"больше не влезет в один визит.\\n\\n"
                    f"Услугу «{sname}» не добавили.")""",
"slot_cart_add_from_state — ветка max_carts"),

# --- 4. _render_cart_added — новые кнопки ---
("""    rows = [
        [InlineKeyboardButton(f"🛍️ Корзина ({n_total})", callback_data="slot:cart_view")],
        [InlineKeyboardButton("➕ Добавить ещё",
                               callback_data=f"slot:cart_add_more:{mid}")],
        [InlineKeyboardButton("◀️ К услугам", callback_data=back_cb)],
        [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
    ]
    await safe_edit(q, context, hp("🛍️ Корзина", text), kb(*rows))""",
"""    rows = [
        [InlineKeyboardButton(f"🛍️ Корзина ({n_total})", callback_data="slot:cart_view")],
        [InlineKeyboardButton(f"➕ Добавить ещё {mname}",
                               callback_data=f"slot:cart_add_more:{mid}")],
        [InlineKeyboardButton("◀️ К выбору способа", callback_data="main:booking")],
        [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
    ]
    await safe_edit(q, context, hp("🛍️ Корзина", text), kb(*rows))""",
"_render_cart_added — кнопка с мастером + к выбору способа"),

# --- 5. _cart_render_empty — «как работает» ---
("""    text = ("🛍️ Корзина пуста.\\n\\n"
            "Добавьте услуги из меню и возвращайтесь.")""",
"""    text = ("🛍️ Корзина пуста.\\n\\n"
            "Как это работает: соберите 2–3 услуги одного мастера — "
            "мы найдём общее время, чтобы сделать всё за один визит.")""",
"_cart_render_empty — добавлено объяснение"),

# --- 6. _render_dates_cart — «Ищем окно на всё сразу» ---
('    header = f"👩 {mname}\\n🛍️ {label}"',
 '    header = f"👩 {mname}\\n🛍️ {label}\\nИщем окно на всё сразу."',
 "_render_dates_cart — заголовок"),

# --- 7. slot_cart_time — «Важно:» вместо обычного текста ---
("""    text += ("\\n💰 Стоимость: уточните у администратора при подтверждении.\\n\\n"
             "Нажмите кнопку ниже — откроется чат с администратором, "
             "сообщение с заявкой на все услуги уже будет готово. "
             "Останется только отправить его.")""",
"""    text += ("\\n💰 Стоимость: уточните у администратора при подтверждении.\\n\\n"
             "Важно: кнопка ниже откроет чат с администратором. "
             "Сообщение с заявкой уже готово — нажмите «Отправить» в чате.")""",
"slot_cart_time — подсказка про «Отправить»"),

# --- 8. _cart_render_one — убрать «Убрать последнюю», обрезка, «К выбору способа» ---
("""    rows.append([InlineKeyboardButton("🔎 Найти время",
                                       callback_data=f"slot:cart_find:{mid}")])
    if n_total < CART_MAX_SERVICES:
        rows.append([InlineKeyboardButton("➕ Добавить услугу",
                                           callback_data=f"slot:cart_add_more:{mid}")])
    if n_total >= 2:
        rows.append([InlineKeyboardButton("↩️ Убрать последнюю",
                                           callback_data=f"slot:cart_remove_last:{mid}")])
    rows.append([InlineKeyboardButton("🗑 Очистить корзину",
                                       callback_data=f"slot:cart_clear:{mid}")])
    rows.append([InlineKeyboardButton("◀️ К мастерам", callback_data="slot:start")])
    rows.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])""",
"""    rows.append([InlineKeyboardButton("🔎 Найти время",
                                       callback_data=f"slot:cart_find:{mid}")])
    if n_total < CART_MAX_SERVICES:
        rows.append([InlineKeyboardButton("➕ Добавить услугу",
                                           callback_data=f"slot:cart_add_more:{mid}")])
    rows.append([InlineKeyboardButton("🗑 Очистить корзину",
                                       callback_data=f"slot:cart_clear:{mid}")])
    rows.append([InlineKeyboardButton("◀️ К выбору способа", callback_data="main:booking")])
    rows.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])""",
"_cart_render_one — убрана «Убрать последнюю», «К мастерам» → «К выбору способа»"),

# --- 9. _cart_render_one — обрезка длинных названий ---
("""    for sid in order:
        g = groups[sid]
        if g["count"] == 1:
            label = f"✕ Убрать: {g['name']}"
        else:
            label = f"✕ Убрать одну: {g['name']}"
        cb = f"slot:cart_remove:{mid}:{sid}"
        if len(cb.encode("utf-8")) <= 64:
            rows.append([InlineKeyboardButton(label[:60], callback_data=cb)])""",
"""    for sid in order:
        g = groups[sid]
        short_name = g["name"] if len(g["name"]) <= 35 else g["name"][:32] + "…"
        if g["count"] == 1:
            label = f"✕ Убрать: {short_name}"
        else:
            label = f"✕ Убрать одну: {short_name}"
        cb = f"slot:cart_remove:{mid}:{sid}"
        if len(cb.encode("utf-8")) <= 64:
            rows.append([InlineKeyboardButton(label, callback_data=cb)])""",
"_cart_render_one — обрезка длинных названий"),

# --- 10. _render_4h_list — объяснение фильтра ---
("""    n_dates = len({o["date"] for o in options})
    lines.append("")
    lines.append(f"Найдено вариантов: {len(options)} (на {n_dates} датах)")
    if len(all_opts) < MAX_4H_OPTIONS:
        lines.append(f"Поиск расширен на {context.user_data.get('4h_searched_days', 30)} дней.")
    lines.append("")""",
"""    n_dates = len({o["date"] for o in options})
    lines.append("")
    lines.append(f"Найдено вариантов: {len(options)} (на {n_dates} датах)")
    if len(all_opts) < MAX_4H_OPTIONS:
        lines.append(f"Поиск расширен на {context.user_data.get('4h_searched_days', 30)} дней.")
    if filter_mid:
        lines.append("")
        if reason == "context":
            lines.append("Показываем пары, где участвует этот мастер. "
                         "Нажмите «🔍 Показать все пары», если хотите увидеть других.")
        else:
            lines.append("Показываем пары с этим мастером. "
                         "Нажмите «🔍 Показать все пары», чтобы увидеть всех.")
    lines.append("")""",
"_render_4h_list — объяснение фильтра"),

# --- 11. _render_4h_no_options — «Попробовать 2 часа» ---
("""    elif virtual_code == "4hands_3h":
        body = (
            "⚠️ На ближайшие 37 дней не нашлось времени, когда два мастера "
            "свободны одновременно на 3 часа.\\n\\n"
            "Но есть варианты на 2 часа — их проще совместить."
        )""",
"""    elif virtual_code == "4hands_3h":
        body = (
            "⚠️ На 3 часа не нашлось времени, когда два мастера свободны одновременно.\\n\\n"
            "3 часа — длинный сеанс, два мастера редко свободны одновременно. "
            "На 2 часа найти легче — их проще совместить."
        )""",
"_render_4h_no_options — объяснение почему 3ч труднее"),
]


# ============================================================
# BOT.PY
# ============================================================

BOT_PATCHES = [
# --- 1. Импорт _plural_services ---
("""from slot_finder import (
    slot_callback, SLOT_FINDER_PREFIX,
    _cart_count, _cart_rows,
)""",
"""from slot_finder import (
    slot_callback, SLOT_FINDER_PREFIX,
    _cart_count, _cart_rows, _plural_services,
)""",
"bot.py — импорт _plural_services"),

# --- 2. main:menu с подтверждением ---
("""        if data == "main:menu":
            # Очищаем корзину и 4hands state
            context.user_data.pop("carts", None)
            context.user_data.pop("cart_updated_at", None)
            for k in ("4h_all_options", "4h_virtual", "4h_service_name",
                      "4h_filter_mid", "4h_filter_reason", "4h_context_name",
                      "4h_selected", "4h_searched_days"):
                context.user_data.pop(k, None)
            await show_main_menu(update, context)
            return""",
"""        if data == "main:menu":
            if _cart_count(context) > 0:
                n = _cart_count(context)
                text = (f"🛍️ У вас непустая корзина ({n} {_plural_services(n)}).\\n\\n"
                        "При переходе в главное меню корзина очистится.")
                await safe_edit(query, context, text,
                                kb([InlineKeyboardButton("✅ Да, в главное меню",
                                                          callback_data="main:menu_confirm")],
                                   [InlineKeyboardButton("◀️ Нет, остаться",
                                                          callback_data="slot:cart_view")]))
                return
            await show_main_menu(update, context)
            return
        if data == "main:menu_confirm":
            context.user_data.pop("carts", None)
            context.user_data.pop("cart_updated_at", None)
            for k in ("4h_all_options", "4h_virtual", "4h_service_name",
                      "4h_filter_mid", "4h_filter_reason", "4h_context_name",
                      "4h_selected", "4h_searched_days"):
                context.user_data.pop(k, None)
            await show_main_menu(update, context)
            return""",
"bot.py — main:menu с подтверждением"),
]


if __name__ == "__main__":
    print("=" * 60)
    print("Применение улучшений корзины и 4hands")
    print("=" * 60)

    print("\\n📄 slot_finder.py")
    ok1 = patch("slot_finder.py", SLOT_PATCHES)

    print("\\n📄 bot.py")
    ok2 = patch("bot.py", BOT_PATCHES)

    print("\\n" + "=" * 60)
    if ok1 and ok2:
        print("✅ Все изменения применены")
        print("\\nПроверь синтаксис:")
    else:
        print("⚠️ Часть патчей не применилась — смотри выше")
        import sys
        sys.exit(1)
