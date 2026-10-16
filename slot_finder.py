# slot_finder.py
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, timedelta

from telegram import InlineKeyboardButton, Update
from telegram.ext import ContextTypes

from content import BOOKING, chat_url
from dikidi_client import DikidiClient, DikidiError, service_id_from_url
from utils import kb, hp, safe_edit

log = logging.getLogger(__name__)

SLOT_FINDER_PREFIX = "slot:"
COMPANY_ID = os.getenv("DIKIDI_COMPANY_ID", "1330084")
DAYS_AHEAD = 14          # сколько дней сканируем
MAX_DATES = 5            # сколько дат максимум показываем
MASTER_ORDER = ["Алла", "Мария", "Алёна", "Римма", "Зульфия"]

dikidi = DikidiClient(COMPANY_ID)


# ---------- хелперы ----------

def _sort_masters(masters: dict[str, str]):
    def key(kv):
        _, name = kv
        idx = next((i for i, n in enumerate(MASTER_ORDER) if n.lower() in name.lower()), 999)
        return (idx, name.lower())
    return sorted(masters.items(), key=key)


def _filter_node(node: dict, dikidi_ids: set[str]) -> dict | None:
    new = dict(node)
    if "services" in node:
        services = [s for s in node["services"]
                    if service_id_from_url(s.get("url", "")) in dikidi_ids]
        if services:
            new["services"] = services
        else:
            new.pop("services", None)
    if "sub" in node:
        subs = []
        for sub in node["sub"]:
            filtered = _filter_node(sub, dikidi_ids)
            if filtered:
                subs.append(filtered)
        if subs:
            new["sub"] = subs
        else:
            new.pop("sub", None)
    if "services" not in new and "sub" not in new:
        return None
    return new


def _filter_booking(booking: dict, dikidi_ids: set[str]) -> dict:
    result = {}
    for cat_code, cat in booking.items():
        filtered = _filter_node(cat, dikidi_ids)
        if filtered:
            result[cat_code] = filtered
    return result


def _clear_master_state(user_data: dict):
    for k in ("slot_master_id", "slot_master_name", "slot_tree", "slot_path",
              "slot_service_id", "slot_service_name", "slot_service_url",
              "slot_back_to_services", "slot_day"):
        user_data.pop(k, None)


async def _check_days(sid: str, mid: str) -> list[tuple[date, list]]:
    """Сканирует DAYS_AHEAD дней, возвращает до MAX_DATES дат, где есть окна,
    отсортированных по возрастанию."""
    today = date.today()

    async def check(day: date):
        try:
            slots = await dikidi.available_slots(sid, mid, day)
            return (day, slots) if slots else None
        except DikidiError as e:
            log.warning("slot check %s %s: %s", sid, day, e)
            return None

    results = await asyncio.gather(*(check(today + timedelta(days=i)) for i in range(DAYS_AHEAD)))
    found = [r for r in results if r]
    found.sort(key=lambda x: x[0])
    return found[:MAX_DATES]


# ---------- мастера ----------

async def slot_show_masters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    _clear_master_state(context.user_data)
    try:
        masters = await dikidi.get_masters()
    except DikidiError as e:
        log.warning("slot masters: %s", e)
        await safe_edit(q, context,
                        "⚠️ Не удалось загрузить мастеров из DiKidi.",
                        kb([InlineKeyboardButton("🔄 Повторить", callback_data="slot:start")],
                           [InlineKeyboardButton("◀️ К выбору способа", callback_data="main:booking")],
                           [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")]))
        return
    context.user_data["slot_masters"] = dict(_sort_masters(masters))
    rows = [[InlineKeyboardButton(n, callback_data=f"slot:master:{mid}")]
            for mid, n in context.user_data["slot_masters"].items()]
    rows.append([InlineKeyboardButton("◀️ К выбору способа", callback_data="main:booking")])
    rows.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])
    await safe_edit(q, context,
                    hp("📅 Хочу записаться → Мастера",
                       "👩 Выбери специалиста:"),
                    kb(*rows))


# ---------- мастер выбран → фильтр BOOKING ----------

async def slot_choose_master(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    mid = q.data.split(":", 2)[2]
    name = context.user_data.get("slot_masters", {}).get(mid)
    if not name:
        await slot_show_masters(update, context)
        return

    context.user_data["slot_master_id"] = mid
    context.user_data["slot_master_name"] = name
    for k in ("slot_path", "slot_service_id", "slot_service_name",
              "slot_service_url", "slot_back_to_services", "slot_day"):
        context.user_data.pop(k, None)

    try:
        dikidi_cats = await dikidi.get_service_categories(mid)
    except DikidiError as e:
        log.warning("slot cats for %s: %s", mid, e)
        await safe_edit(q, context, "⚠️ Не удалось загрузить услуги мастера.",
                        kb([InlineKeyboardButton("🔄 Повторить", callback_data=f"slot:master:{mid}")],
                           [InlineKeyboardButton("◀️ К мастерам", callback_data="slot:back:masters")],
                           [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")]))
        return

    dikidi_ids: set[str] = set()
    for cat in dikidi_cats.values():
        dikidi_ids.update(cat["services"].keys())

    filtered = _filter_booking(BOOKING, dikidi_ids)
    if not filtered:
        await safe_edit(q, context,
                        f"⚠️ У мастера {name} пока нет доступных услуг.",
                        kb([InlineKeyboardButton("◀️ К мастерам", callback_data="slot:back:masters")],
                           [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")]))
        return

    context.user_data["slot_tree"] = filtered
    context.user_data["slot_path"] = []
    await _render_categories(update, context)


async def _render_categories(update, context):
    q = update.callback_query
    tree = context.user_data.get("slot_tree")
    if not tree:
        await slot_show_masters(update, context)
        return
    name = context.user_data.get("slot_master_name", "")
    rows = [[InlineKeyboardButton(cat["title"], callback_data=f"slot:cat:{code}")]
            for code, cat in tree.items()]
    rows.append([InlineKeyboardButton("◀️ К мастерам", callback_data="slot:back:masters")])
    rows.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])
    await safe_edit(q, context,
                    hp(f"📅 Хочу записаться → {name}",
                       f"👩 {name}\n\nВыберите тип услуги:"),
                    kb(*rows))


# ---------- категория ----------

async def slot_show_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    code = q.data.split(":", 2)[2]
    tree = context.user_data.get("slot_tree") or {}
    cat = tree.get(code)
    if not cat:
        await _render_categories(update, context)
        return

    context.user_data["slot_path"] = [code]
    name = context.user_data["slot_master_name"]

    if "sub" in cat:
        rows = [[InlineKeyboardButton(sub["title"],
                                       callback_data=f"slot:sub:{code}:{sub['code']}")]
                for sub in cat["sub"]]
        rows.append([InlineKeyboardButton("◀️ К категориям", callback_data="slot:back:cats")])
        rows.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])
        await safe_edit(q, context,
                        hp(f"📅 Хочу записаться → {name} → {cat['title']}",
                           f"{cat['title']}\n\nВыберите раздел:"),
                        kb(*rows))
        return

    await _render_services(update, context, cat["services"],
                           parent_code=code, breadcrumb=cat["title"])


# ---------- подкатегория ----------

async def slot_show_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split(":")   # slot:sub:<parent>:<sub>
    parent_code, sub_code = parts[2], parts[3]
    tree = context.user_data.get("slot_tree") or {}
    parent = tree.get(parent_code)
    if not parent or "sub" not in parent:
        await _render_categories(update, context)
        return
    sub = next((s for s in parent["sub"] if s["code"] == sub_code), None)
    if not sub:
        await _render_categories(update, context)
        return

    context.user_data["slot_path"] = [parent_code, sub_code]
    name = context.user_data["slot_master_name"]

    if "sub" in sub:
        rows = [[InlineKeyboardButton(sub2["title"],
                                       callback_data=f"slot:sub2:{parent_code}:{sub_code}:{sub2['code']}")]
                for sub2 in sub["sub"]]
        rows.append([InlineKeyboardButton("◀️ Назад", callback_data=f"slot:cat:{parent_code}")])
        rows.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])
        await safe_edit(q, context,
                        hp(f"📅 Хочу записаться → {name} → {parent['title']} → {sub['title']}",
                           f"{sub['title']}\n\nВыберите раздел:"),
                        kb(*rows))
        return

    await _render_services(update, context, sub["services"],
                           parent_code=parent_code, sub_code=sub_code,
                           breadcrumb=sub["title"])


async def slot_show_sub2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split(":")   # slot:sub2:<parent>:<sub>:<sub2>
    parent_code, sub_code, sub2_code = parts[2], parts[3], parts[4]
    tree = context.user_data.get("slot_tree") or {}
    try:
        parent = tree[parent_code]
        sub = next(s for s in parent["sub"] if s["code"] == sub_code)
        sub2 = next(s for s in sub["sub"] if s["code"] == sub2_code)
    except (KeyError, StopIteration):
        await _render_categories(update, context)
        return

    context.user_data["slot_path"] = [parent_code, sub_code, sub2_code]
    await _render_services(update, context, sub2["services"],
                           parent_code=parent_code, sub_code=sub_code,
                           sub2_code=sub2_code, breadcrumb=sub2["title"])


# ---------- список услуг ----------

async def _render_services(update, context, services, parent_code,
                           sub_code=None, sub2_code=None, breadcrumb=""):
    q = update.callback_query
    name = context.user_data["slot_master_name"]

    rows = []
    for idx, s in enumerate(services):
        if sub_code and sub2_code:
            cb = f"slot:srv3:{parent_code}:{sub_code}:{sub2_code}:{idx}"
        elif sub_code:
            cb = f"slot:srv2:{parent_code}:{sub_code}:{idx}"
        else:
            cb = f"slot:srv:{parent_code}:{idx}"
        rows.append([InlineKeyboardButton(f"{s['name']} — {s['price']}", callback_data=cb)])

    if sub_code and sub2_code:
        back_cb = f"slot:sub:{parent_code}:{sub_code}"
    elif sub_code:
        back_cb = f"slot:cat:{parent_code}"
    else:
        back_cb = "slot:back:cats"
    rows.append([InlineKeyboardButton("◀️ Назад", callback_data=back_cb)])
    rows.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])

    await safe_edit(q, context,
                    hp(f"📅 Хочу записаться → {name} → {breadcrumb}",
                       f"{breadcrumb}\n\nВыберите услугу:"),
                    kb(*rows))


# ---------- услуга выбрана → 14 дней → 5 дат ----------

async def slot_choose_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    s, back_cb = _parse_service_cb(q.data, context)
    if not s:
        await _render_categories(update, context)
        return

    sid = service_id_from_url(s.get("url", ""))
    if not sid:
        await safe_edit(q, context, "⚠️ У этой услуги нет онлайн-записи DiKidi.",
                        kb([InlineKeyboardButton("◀️ Назад", callback_data=back_cb)],
                           [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")]))
        return

    context.user_data["slot_service_id"] = sid
    context.user_data["slot_service_name"] = s["name"]
    context.user_data["slot_service_url"] = s["url"]
    context.user_data["slot_back_to_services"] = back_cb

    name = context.user_data["slot_master_name"]
    mid = context.user_data["slot_master_id"]

    days = await _check_days(sid, mid)
    await _render_dates(q, context, days, s, name, back_cb)


async def _render_dates(q, context, days, service, master_name, back_cb):
    header = f"👩 {master_name}\n✅ {service['name']} — {service['price']}"

    if not days:
        # 0 дат за 14 дней
        text = (
            f"{header}\n\n"
            "⚠️ На ближайшие 14 дней свободных окон нет.\n\n"
            "Можно попробовать другого мастера — "
            "у него может быть другое расписание."
        )
        rows = [
            [InlineKeyboardButton("👩 Выбрать другого мастера",
                                   callback_data="slot:back:masters")],
            [InlineKeyboardButton("◀️ К услугам", callback_data=back_cb)],
            [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
        ]
    else:
        rows = [[InlineKeyboardButton(d.strftime("%a %d.%m"),
                                       callback_data=f"slot:date:{d.isoformat()}")]
                for d, _ in days]

        if len(days) < MAX_DATES:
            text = (
                f"{header}\n\nВыберите дату:\n\n"
                "На ближайшие 14 дней больше окон нет."
            )
        else:
            text = f"{header}\n\nВыберите дату:"

        rows.append([InlineKeyboardButton("◀️ К услугам", callback_data=back_cb)])
        rows.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])

    await safe_edit(q, context,
                    hp(f"📅 Хочу записаться → {master_name} → {service['name']}",
                       text),
                    kb(*rows))


def _parse_service_cb(data: str, context):
    """slot:srv:<code>:<idx> | slot:srv2:<p>:<s>:<idx> | slot:srv3:<p>:<s>:<s2>:<idx>
    Возвращает (service_dict, back_callback)."""
    parts = data.split(":")
    tree = context.user_data.get("slot_tree") or {}
    try:
        if parts[1] == "srv" and len(parts) == 4:
            code, idx = parts[2], int(parts[3])
            cat = tree.get(code)
            if cat and "services" in cat:
                return cat["services"][idx], f"slot:cat:{code}"
        elif parts[1] == "srv2" and len(parts) == 5:
            parent_code, sub_code, idx = parts[2], parts[3], int(parts[4])
            parent = tree[parent_code]
            sub = next(s for s in parent["sub"] if s["code"] == sub_code)
            return sub["services"][idx], f"slot:sub:{parent_code}:{sub_code}"
        elif parts[1] == "srv3" and len(parts) == 6:
            parent_code, sub_code, sub2_code, idx = parts[2], parts[3], parts[4], int(parts[5])
            parent = tree[parent_code]
            sub = next(s for s in parent["sub"] if s["code"] == sub_code)
            sub2 = next(s for s in sub["sub"] if s["code"] == sub2_code)
            return sub2["services"][idx], f"slot:sub2:{parent_code}:{sub_code}:{sub2_code}"
    except (KeyError, IndexError, ValueError, StopIteration):
        return None, ""
    return None, ""


# ---------- дата выбрана → времена (URL-кнопки) ----------

async def slot_show_times(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    ds = q.data.split(":", 2)[2]
    try:
        day = date.fromisoformat(ds)
    except ValueError:
        await slot_show_masters(update, context)
        return

    sid = context.user_data.get("slot_service_id")
    mid = context.user_data.get("slot_master_id")
    if not sid or not mid:
        await safe_edit(q, context, "⚠️ Сессия устарела. Начни заново.",
                        kb([InlineKeyboardButton("🔄 Заново", callback_data="slot:start")],
                           [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")]))
        return

    try:
        slots = await dikidi.available_slots(sid, mid, day)
    except DikidiError as e:
        log.warning("slot times %s: %s", day, e)
        await safe_edit(q, context, "⚠️ Не удалось получить расписание.",
                        kb([InlineKeyboardButton("◀️ К датам", callback_data="slot:back:dates")],
                           [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")]))
        return

    if not slots:
        await safe_edit(q, context, f"На {day.strftime('%d.%m.%Y')} окон не осталось.",
                        kb([InlineKeyboardButton("◀️ К датам", callback_data="slot:back:dates")],
                           [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")]))
        return

    mname = context.user_data["slot_master_name"]
    sname = context.user_data["slot_service_name"]
    date_str = day.strftime("%d.%m.%Y")

    def make_url(t: str) -> str:
        msg = (
            f"Запишите меня на услугу «{sname}» "
            f"у мастера {mname} на {date_str} в {t}."
        )
        return chat_url(msg)

    times = [s.strftime("%H:%M") for s in slots]
    rows = [[InlineKeyboardButton(t, url=make_url(t)) for t in times[i:i + 3]]
            for i in range(0, len(times), 3)]

    rows.append([InlineKeyboardButton("◀️ К датам", callback_data="slot:back:dates")])
    rows.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])

    text = (
        f"👩 {mname}\n"
        f"✅ {sname}\n"
        f"📅 {date_str}\n\n"
        "Свободное время:\n\n"
        "Нажмите на время — откроется чат с администратором "
        "и готовым сообщением для записи.\n"
        "Ожидайте подтверждения."
    )

    await safe_edit(q, context,
                    hp(f"📅 Хочу записаться → {mname} → {sname}", text),
                    kb(*rows))


# ---------- back к датам ----------

async def slot_back_to_dates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    sid = context.user_data.get("slot_service_id")
    mid = context.user_data.get("slot_master_id")
    sname = context.user_data.get("slot_service_name")
    if not sid or not mid or not sname:
        await slot_show_masters(update, context)
        return

    days = await _check_days(sid, mid)
    service = {"name": sname, "price": ""}
    back_cb = context.user_data.get("slot_back_to_services") or "slot:back:cats"
    name = context.user_data["slot_master_name"]

    await _render_dates(q, context, days, service, name, back_cb)


# ---------- роутер ----------

async def slot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    try:
        await q.answer()
    except Exception:
        pass

    try:
        # точные
        if data == "slot:start":
            await slot_show_masters(update, context)
            return
        if data == "slot:back:masters":
            await slot_show_masters(update, context)
            return
        if data == "slot:back:cats":
            await _render_categories(update, context)
            return
        if data == "slot:back:dates":
            await slot_back_to_dates(update, context)
            return
        if data == "slot:noop":
            return

        # префиксные
        if data.startswith("slot:master:"):
            await slot_choose_master(update, context)
            return
        if data.startswith("slot:cat:"):
            await slot_show_category(update, context)
            return
        if data.startswith("slot:sub2:"):
            await slot_show_sub2(update, context)
            return
        if data.startswith("slot:sub:"):
            await slot_show_sub(update, context)
            return
        if data.startswith("slot:srv"):
            await slot_choose_service(update, context)
            return
        if data.startswith("slot:date:"):
            await slot_show_times(update, context)
            return

        log.warning("unknown slot callback: %s", data)
    except Exception as e:
        log.exception("slot callback error %s: %s", data, e)
