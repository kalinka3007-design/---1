# slot_finder.py
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, timedelta

from telegram import InlineKeyboardButton, Update
from telegram.ext import ContextTypes

from content import BOOKING, ABONEMENT_SECTIONS, chat_url
from dikidi_client import DikidiClient, DikidiError, service_id_from_url
from utils import kb, hp, safe_edit

import stats_store

log = logging.getLogger(__name__)

SLOT_FINDER_PREFIX = "slot:"
COMPANY_ID = os.getenv("DIKIDI_COMPANY_ID", "1330084")
DAYS_AHEAD = 14
MAX_DATES = 5
MAX_CALLBACK_LEN = 60
MASTER_ORDER = ["Алла", "Мария", "Алёна", "Римма", "Зульфия"]
PREP_SECTIONS = ("epilation", "laser", "depilation")

dikidi = DikidiClient(COMPANY_ID)


# ==============================================
# ИНДЕКСЫ УСЛУГ (sid → сервис + путь)
# ==============================================

def _build_indexes():
    by_id: dict[str, dict] = {}
    path: dict[str, tuple[str, str]] = {}
    for cat_code, cat in BOOKING.items():
        for idx, s in enumerate(cat.get("services", [])):
            sid = service_id_from_url(s.get("url", ""))
            if sid:
                by_id[sid] = s
                path[sid] = (f"srv:{cat_code}:{idx}", cat_code)
        for sub in cat.get("sub", []):
            for idx, s in enumerate(sub.get("services", [])):
                sid = service_id_from_url(s.get("url", ""))
                if sid:
                    by_id[sid] = s
                    path[sid] = (f"srv2:{cat_code}:{sub['code']}:{idx}", cat_code)
            for sub2 in sub.get("sub", []):
                for idx, s in enumerate(sub2.get("services", [])):
                    sid = service_id_from_url(s.get("url", ""))
                    if sid:
                        by_id[sid] = s
                        path[sid] = (f"srv3:{cat_code}:{sub['code']}:{sub2['code']}:{idx}", cat_code)
    return by_id, path


SERVICE_BY_ID, SERVICE_PATH = _build_indexes()


# ==============================================
# ХЕЛПЕРЫ
# ==============================================

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
              "slot_service_booking_cb", "slot_service_parent_code",
              "slot_back_to_services", "slot_day", "slot_selected_time"):
        user_data.pop(k, None)


def _clear_msrv_state(user_data: dict):
    user_data.pop("slot_msrv_sid", None)
    user_data.pop("slot_msrv_back_cb", None)


async def _check_days(sid: str, mid: str) -> list[tuple[date, list]]:
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


async def _masters_for_service(sid: str) -> dict[str, str]:
    try:
        masters = await dikidi.get_masters()
    except DikidiError as e:
        log.warning("masters for service: %s", e)
        return {}

    async def has_service(mid: str) -> bool:
        try:
            cats = await dikidi.get_service_categories(mid)
            for cat in cats.values():
                if sid in cat["services"]:
                    return True
            return False
        except DikidiError as e:
            log.warning("check master %s for service %s: %s", mid, sid, e)
            return False

    results = await asyncio.gather(*(has_service(mid) for mid in masters))
    return {mid: name for (mid, name), ok in zip(masters.items(), results) if ok}


def _prep_and_abonement_rows(sid: str) -> list:
    rows = []
    path = SERVICE_PATH.get(sid)
    if not path:
        return rows
    booking_cb, parent_code = path
    if parent_code in ABONEMENT_SECTIONS:
        cb = f"sub_calc:{booking_cb}"
        if len(cb.encode("utf-8")) <= MAX_CALLBACK_LEN:
            rows.append([InlineKeyboardButton("📦 Узнать про абонемент", callback_data=cb)])
    if parent_code in PREP_SECTIONS:
        cb = f"prep_srv:{parent_code}:{booking_cb}"
        if len(cb.encode("utf-8")) <= MAX_CALLBACK_LEN:
            rows.append([InlineKeyboardButton("📚 Как подготовиться", callback_data=cb)])
    return rows


# ==============================================
# НОВАЯ ВЕТКА: СНАЧАЛА МАСТЕР
# ==============================================

async def slot_show_masters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    _clear_master_state(context.user_data)
    _clear_msrv_state(context.user_data)
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


async def slot_choose_master(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    mid = q.data.split(":", 2)[2]
    name = context.user_data.get("slot_masters", {}).get(mid)
    if not name:
        await slot_show_masters(update, context)
        return

    stats_store.bump("funnel.master")
    stats_store.save()

    context.user_data["slot_master_id"] = mid
    context.user_data["slot_master_name"] = name
    for k in ("slot_path", "slot_service_id", "slot_service_name",
              "slot_service_url", "slot_service_booking_cb",
              "slot_service_parent_code", "slot_back_to_services",
              "slot_day", "slot_selected_time"):
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


async def slot_show_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    code = q.data.split(":", 2)[2]
    tree = context.user_data.get("slot_tree") or {}
    cat = tree.get(code)
    if not cat:
        await _render_categories(update, context)
        return

    stats_store.bump("funnel.category")
    stats_store.bump_category(code)
    stats_store.save()

    context.user_data["slot_path"] = [code]
    name = context.user_data["slot_master_name"]

    rows = []
    if "sub" in cat:
        for sub in cat["sub"]:
            rows.append([InlineKeyboardButton(sub["title"],
                                              callback_data=f"slot:sub:{code}:{sub['code']}")])
    if "services" in cat:
        for i, s in enumerate(cat["services"]):
            rows.append([InlineKeyboardButton(f"{s['name']} — {s['price']}",
                                              callback_data=f"slot:srv:{code}:{i}")])

    rows.append([InlineKeyboardButton("◀️ К категориям", callback_data="slot:back:cats")])
    rows.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])

    hint = "Выберите раздел:" if "sub" in cat else "Выберите услугу:"
    await safe_edit(q, context,
                    hp(f"📅 Хочу записаться → {name} → {cat['title']}",
                       f"{cat['title']}\n\n{hint}"),
                    kb(*rows))


async def slot_show_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split(":")
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
    name = context.user_data.get("slot_master_name")

    if "sub" in sub:
        rows = [[InlineKeyboardButton(sub2["title"],
                                       callback_data=f"slot:sub2:{parent_code}:{sub_code}:{sub2['code']}")]
                for sub2 in sub["sub"]]
        rows.append([InlineKeyboardButton("◀️ К категориям",
                                           callback_data=f"slot:cat:{parent_code}")])
        rows.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])
        await safe_edit(q, context,
                        hp(f"📅 Хочу записаться → {name} → {parent['title']} → {sub['title']}",
                           f"{sub['title']}\n\nВыберите раздел:"),
                        kb(*rows))
        return

    await _render_services(update, context, sub["services"],
                           parent_code=parent_code, sub_code=sub_code,
                           breadcrumb=sub["title"], description=sub.get("description"))


async def slot_show_sub2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split(":")
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


async def _render_services(update, context, services, parent_code,
                           sub_code=None, sub2_code=None, breadcrumb="", description=None):
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

    text = f"{breadcrumb}\n\n"
    if description:
        text += f"{description}\n\n"
    text += "Выберите услугу:"

    await safe_edit(q, context,
                    hp(f"📅 Хочу записаться → {name} → {breadcrumb}", text),
                    kb(*rows))


# ==============================================
# СТАРАЯ ВЕТКА: УСЛУГА ВЫБРАНА → МАСТЕРА ДЛЯ НЕЁ
# ==============================================

async def slot_show_masters_for_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split(":", 3)
    if len(parts) < 4:
        await safe_edit(q, context, "⚠️ Некорректный вызов.")
        return
    sid, back_cb = parts[2], parts[3]

    service = SERVICE_BY_ID.get(sid)
    if not service:
        await safe_edit(q, context, "⚠️ Услуга не найдена.",
                        kb([InlineKeyboardButton("◀️ Назад", callback_data=back_cb)],
                           [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")]))
        return

    stats_store.bump("funnel.masters_for_service")
    stats_store.save()

    context.user_data["slot_msrv_sid"] = sid
    context.user_data["slot_msrv_back_cb"] = back_cb

    filtered = await _masters_for_service(sid)
    if not filtered:
        await safe_edit(q, context,
                        f"⚠️ К сожалению, ни один мастер сейчас не выполняет услугу «{service['name']}».",
                        kb([InlineKeyboardButton("◀️ К услугам", callback_data=back_cb)],
                           [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")]))
        return

    sorted_masters = dict(_sort_masters(filtered))
    context.user_data["slot_msrv_masters"] = sorted_masters

    rows = [[InlineKeyboardButton(n, callback_data=f"slot:msrv_go:{mid}")]
            for mid, n in sorted_masters.items()]
    rows.append([InlineKeyboardButton("◀️ К услугам", callback_data=back_cb)])
    rows.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])

    await safe_edit(q, context,
                    hp(f"📅 Хочу записаться → {service['name']}",
                       f"✅ {service['name']} — {service['price']}\n\n"
                       "Выберите мастера:"),
                    kb(*rows))


async def _msrv_back_render(update, context):
    q = update.callback_query
    sid = context.user_data.get("slot_msrv_sid")
    if not sid:
        await slot_show_masters(update, context)
        return
    service = SERVICE_BY_ID.get(sid)
    if not service:
        await slot_show_masters(update, context)
        return
    filtered = await _masters_for_service(sid)
    sorted_masters = dict(_sort_masters(filtered))
    context.user_data["slot_msrv_masters"] = sorted_masters
    back_cb = context.user_data.get("slot_msrv_back_cb") or "main:booking"

    rows = [[InlineKeyboardButton(n, callback_data=f"slot:msrv_go:{mid}")]
            for mid, n in sorted_masters.items()]
    rows.append([InlineKeyboardButton("◀️ К услугам", callback_data=back_cb)])
    rows.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])
    await safe_edit(q, context,
                    hp(f"📅 Хочу записаться → {service['name']}",
                       f"✅ {service['name']} — {service['price']}\n\nВыберите мастера:"),
                    kb(*rows))


async def slot_msrv_choose_master(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    mid = q.data.split(":", 2)[2]
    sid = context.user_data.get("slot_msrv_sid")
    if not sid:
        await safe_edit(q, context, "⚠️ Сессия устарела. Начни заново.",
                        kb([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")]))
        return

    name = context.user_data.get("slot_msrv_masters", {}).get(mid)
    if not name:
        await _msrv_back_render(update, context)
        return

    service = SERVICE_BY_ID.get(sid)
    path = SERVICE_PATH.get(sid)
    if not service or not path:
        await safe_edit(q, context, "⚠️ Услуга не найдена. Начни заново.",
                        kb([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")]))
        return

    booking_cb, parent_code = path

    context.user_data["slot_master_id"] = mid
    context.user_data["slot_master_name"] = name
    context.user_data["slot_service_id"] = sid
    context.user_data["slot_service_name"] = service["name"]
    context.user_data["slot_service_url"] = service.get("url", "")
    context.user_data["slot_service_booking_cb"] = booking_cb
    context.user_data["slot_service_parent_code"] = parent_code
    context.user_data["slot_back_to_services"] = "slot:msrv_back"

    await _render_dates_from_state(q, context)


# ==============================================
# НОВАЯ ВЕТКА: УСЛУГА ВЫБРАНА
# ==============================================

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

    stats_store.bump("funnel.service")
    stats_store.save()

    path = SERVICE_PATH.get(sid)
    booking_cb = path[0] if path else None
    parent_code = path[1] if path else None

    context.user_data["slot_service_id"] = sid
    context.user_data["slot_service_name"] = s["name"]
    context.user_data["slot_service_url"] = s.get("url", "")
    context.user_data["slot_service_booking_cb"] = booking_cb
    context.user_data["slot_service_parent_code"] = parent_code
    context.user_data["slot_back_to_services"] = back_cb

    await _render_dates_from_state(q, context)


def _parse_service_cb(data: str, context):
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


# ==============================================
# ЭКРАН ДАТ
# ==============================================

async def _render_dates_from_state(q, context):
    sid = context.user_data.get("slot_service_id")
    mid = context.user_data.get("slot_master_id")
    sname = context.user_data.get("slot_service_name", "")
    mname = context.user_data.get("slot_master_name", "")
    back_cb = context.user_data.get("slot_back_to_services") or "slot:back:cats"
    if not sid or not mid:
        await slot_show_masters(None, context)
        return

    service = SERVICE_BY_ID.get(sid) or {"name": sname, "price": ""}
    days = await _check_days(sid, mid)
    await _render_dates(q, context, days, service, mname, back_cb)


async def _render_dates(q, context, days, service, master_name, back_cb):
    sid = service_id_from_url(service.get("url", "")) or context.user_data.get("slot_service_id", "")
    header = f"👩 {master_name}\n✅ {service['name']}"
    if service.get("price"):
        header += f" — {service['price']}"

    is_msrv = (back_cb or "").startswith("slot:msrv")
    back_label = "◀️ К мастерам" if is_msrv else "◀️ К услугам"
    other_master_cb = "slot:msrv_back" if is_msrv else "slot:back:masters"

    stats_store.bump("funnel.dates_shown")
    stats_store.save()

    rows = []
    if not days:
        stats_store.bump("funnel.no_slots_14days")
        stats_store.save()
        text = (
            f"{header}\n\n"
            "⚠️ На ближайшие 14 дней свободных окон нет.\n\n"
            "Можно попробовать другого мастера — у него может быть другое расписание."
        )
        rows.append([InlineKeyboardButton("👩 Выбрать другого мастера",
                                           callback_data=other_master_cb)])
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

    if sid:
        rows.extend(_prep_and_abonement_rows(sid))

    rows.append([InlineKeyboardButton(back_label, callback_data=back_cb)])
    rows.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])

    await safe_edit(q, context,
                    hp(f"📅 Хочу записаться → {master_name} → {service['name']}", text),
                    kb(*rows))


async def slot_back_to_dates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    sid = context.user_data.get("slot_service_id")
    mid = context.user_data.get("slot_master_id")
    if not sid or not mid:
        await slot_show_masters(update, context)
        return
    service = SERVICE_BY_ID.get(sid) or {"name": context.user_data.get("slot_service_name", ""), "price": ""}
    back_cb = context.user_data.get("slot_back_to_services") or "slot:back:cats"
    mname = context.user_data.get("slot_master_name", "")
    days = await _check_days(sid, mid)
    await _render_dates(q, context, days, service, mname, back_cb)


# ==============================================
# ЭКРАН ВРЕМЁН (callback-кнопки → экран подтверждения)
# ==============================================

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

    stats_store.bump("funnel.times_shown")
    stats_store.save()

    context.user_data["slot_day"] = ds

    mname = context.user_data["slot_master_name"]
    sname = context.user_data["slot_service_name"]
    date_str = day.strftime("%d.%m.%Y")

    times = [s.strftime("%H:%M") for s in slots]
    rows = [[InlineKeyboardButton(t, callback_data=f"slot:time:{ds}:{t}")
             for t in times[i:i + 3]]
            for i in range(0, len(times), 3)]

    rows.extend(_prep_and_abonement_rows(sid))
    rows.append([InlineKeyboardButton("◀️ К датам", callback_data="slot:back:dates")])
    rows.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])

    text = (
        f"👩 {mname}\n"
        f"✅ {sname}\n"
        f"📅 {date_str}\n\n"
        "Выберите удобное время:"
    )

    await safe_edit(q, context,
                    hp(f"📅 Хочу записаться → {mname} → {sname}", text),
                    kb(*rows))


# ==============================================
# ЭКРАН ПОДТВЕРЖДЕНИЯ ВРЕМЕНИ
# ==============================================

async def slot_choose_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split(":")   # slot:time:<ISO>:<HH:MM>
    if len(parts) < 5:
        await safe_edit(q, context, "⚠️ Некорректный выбор.")
        return
    ds, t = parts[2], parts[3] + ":" + parts[4]
    try:
        day = date.fromisoformat(ds)
    except ValueError:
        await slot_show_masters(update, context)
        return

    sid = context.user_data.get("slot_service_id")
    mid = context.user_data.get("slot_master_id")
    mname = context.user_data.get("slot_master_name", "")
    sname = context.user_data.get("slot_service_name", "")
    if not sid or not mid or not mname or not sname:
        await safe_edit(q, context, "⚠️ Сессия устарела. Начни заново.",
                        kb([InlineKeyboardButton("🔄 Заново", callback_data="slot:start")],
                           [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")]))
        return

    stats_store.bump("funnel.time_clicked")
    stats_store.save()

    context.user_data["slot_selected_time"] = t
    context.user_data["slot_day"] = ds

    service = SERVICE_BY_ID.get(sid) or {"name": sname, "price": ""}
    date_str = day.strftime("%d.%m.%Y")

    # Готовое сообщение админу
    msg = (
        f"Запишите меня на услугу «{sname}» "
        f"у мастера {mname} на {date_str} в {t}."
    )
    admin_url = chat_url(msg)

    keyboard = [
        [InlineKeyboardButton("📩 Отправить заявку администратору", url=admin_url)],
        [InlineKeyboardButton("◀️ К временам", callback_data=f"slot:date:{ds}")],
        [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
    ]

    text = (
        "✅ Вы выбрали:\n\n"
        f"👩 Мастер: {mname}\n"
        f"💡 Услуга: {service['name']}"
    )
    if service.get("price"):
        text += f" — {service['price']}"
    text += (
        f"\n📅 Дата: {date_str}\n"
        f"⏰ Время: {t}\n\n"
        "Нажмите кнопку ниже — откроется чат с администратором студии, "
        "и сообщение с вашей заявкой уже будет подготовлено. "
        "Останется только отправить его. "
        "Администратор подтвердит запись и свяжется с вами."
    )

    await safe_edit(q, context,
                    hp(f"📅 Хочу записаться → {mname} → {sname} → {t}", text),
                    kb(*keyboard))


# ==============================================
# РОУТЕР
# ==============================================

async def slot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    try:
        await q.answer()
    except Exception:
        pass

    try:
        if data == "slot:start":
            stats_store.bump("funnel.masters_branch")
            stats_store.save()
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
        if data == "slot:msrv_back":
            await _msrv_back_render(update, context)
            return
        if data == "slot:noop":
            return

        if data.startswith("slot:msrv_go:"):
            await slot_msrv_choose_master(update, context)
            return
        if data.startswith("slot:msrv:"):
            await slot_show_masters_for_service(update, context)
            return

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
        if data.startswith("slot:time:"):
            await slot_choose_time(update, context)
            return
        if data.startswith("slot:date:"):
            await slot_show_times(update, context)
            return

        log.warning("unknown slot callback: %s", data)
    except Exception as e:
        log.exception("slot callback error %s: %s", data, e)
