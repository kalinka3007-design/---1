# slot_finder.py
from __future__ import annotations

import asyncio
import logging
import os
import time as _time
from collections import defaultdict
from datetime import date, datetime, time as dtime, timedelta
from itertools import combinations

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

# 4hands
FOUR_HANDS_EXCLUDED = ("алла",)
DAYS_4H_INITIAL = 30
DAYS_4H_EXTENDED = 37
MAX_4H_OPTIONS = 12
FOUR_HANDS_INTERVALS = [
    (dtime(10, 0), dtime(13, 0)),
    (dtime(13, 0), dtime(17, 0)),
    (dtime(17, 0), dtime(21, 0)),
]

# Корзина
CART_MAX_SERVICES = 3
CART_TTL_SECONDS = 30 * 60

RU_WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

dikidi = DikidiClient(COMPANY_ID)


# ==============================================
# ИНДЕКСЫ УСЛУГ
# ==============================================

def _build_indexes():
    by_id: dict[str, dict] = {}
    path: dict[str, tuple[str, str]] = {}
    for cat_code, cat in BOOKING.items():
        for idx, s in enumerate(cat.get("services", [])):
            if s.get("virtual"):
                continue
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


def _build_virtual_index():
    out = {}
    for cat in BOOKING.values():
        for s in cat.get("services", []):
            if s.get("virtual"):
                out[s["virtual"]] = s
    return out


VIRTUAL_SERVICES = _build_virtual_index()


# ==============================================
# ХЕЛПЕРЫ — форматирование
# ==============================================

def _format_ru_date(d) -> str:
    """date | str(ISO) → 'пт 18.10'"""
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return f"{RU_WEEKDAYS[d.weekday()]} {d.strftime('%d.%m')}"


def _format_duration(minutes) -> str:
    if not minutes:
        return ""
    minutes = int(minutes)
    h, m = divmod(minutes, 60)
    if m == 0:
        return f"{h} ч"
    if h == 0:
        return f"{m} мин"
    return f"{h} ч {m} мин"


# ==============================================
# ХЕЛПЕРЫ — мастера/услуги
# ==============================================

def _sort_masters(masters: dict[str, str]):
    def key(kv):
        _, name = kv
        idx = next((i for i, n in enumerate(MASTER_ORDER) if n.lower() in name.lower()), 999)
        return (idx, name.lower())
    return sorted(masters.items(), key=key)


def _is_excluded_from_4h(name: str) -> bool:
    n = (name or "").lower()
    return any(x in n for x in FOUR_HANDS_EXCLUDED)


def _filter_node(node: dict, dikidi_ids: set[str]) -> dict | None:
    new = dict(node)
    if "services" in node:
        services = [
            s for s in node["services"]
            if not s.get("virtual")
            and service_id_from_url(s.get("url", "")) in dikidi_ids
        ]
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


def _clear_4h_state(user_data: dict):
    for k in ("4h_all_options", "4h_virtual", "4h_service_name",
              "4h_filter_mid", "4h_filter_reason", "4h_context_name",
              "4h_selected", "4h_searched_days"):
        user_data.pop(k, None)


# ==============================================
# ХЕЛПЕРЫ — поиск слотов
# ==============================================

async def _check_days(service_ids, master_id, days_ahead=DAYS_AHEAD):
    """Возвращает (found_days, had_error). service_ids: str | list[str]."""
    today = date.today()
    had_error = False

    async def check(day):
        nonlocal had_error
        try:
            slots = await dikidi.available_slots(service_ids, master_id, day)
            return (day, slots) if slots else None
        except DikidiError as e:
            log.warning("slot check %s %s: %s", service_ids, day, e)
            had_error = True
            return None

    results = await asyncio.gather(
        *(check(today + timedelta(days=i)) for i in range(days_ahead))
    )
    found = [r for r in results if r]
    found.sort(key=lambda x: x[0])
    return found[:MAX_DATES], had_error


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
# КОРЗИНА — низкоуровневые хелперы
# ==============================================

def _cart_get(context) -> dict:
    """Вернуть carts dict, с TTL-очисткой."""
    carts = context.user_data.get("carts")
    if not isinstance(carts, dict):
        return {}
    ts = context.user_data.get("cart_updated_at")
    if ts and _time.time() - ts > CART_TTL_SECONDS:
        # устарело
        context.user_data.pop("carts", None)
        context.user_data.pop("cart_updated_at", None)
        return {}
    return carts


def _cart_touch(context):
    context.user_data["cart_updated_at"] = _time.time()


def _cart_count(context) -> int:
    carts = _cart_get(context)
    return sum(len(c.get("services", [])) for c in carts.values())


def _cart_add(context, master_id: str, master_name: str, service: dict) -> tuple[bool, str]:
    """Добавить услугу. Возвращает (ok, reason)."""
    carts = _cart_get(context)
    cart = carts.setdefault(master_id, {
        "master_name": master_name,
        "services": [],
    })
    # Лимит
    if len(cart["services"]) >= CART_MAX_SERVICES:
        return False, "limit"
    # Дубли (только для электро разрешены)
    sid = service["service_id"]
    parent_cat = service.get("parent_code", "")
    is_electro = parent_cat == "epilation"
    if not is_electro:
        if any(s["service_id"] == sid for s in cart["services"]):
            return False, "dup"
    cart["services"].append({
        "service_id": sid,
        "name": service["name"],
        "price": service.get("price", ""),
        "time": service.get("time"),          # минуты или None
        "parent_code": parent_cat,
    })
    context.user_data["carts"] = carts
    _cart_touch(context)
    stats_store.bump("funnel.cart_added")
    stats_store.save()
    return True, ""


def _cart_remove(context, master_id: str, service_id: str) -> bool:
    carts = _cart_get(context)
    cart = carts.get(master_id)
    if not cart:
        return False
    for i, s in enumerate(cart["services"]):
        if s["service_id"] == service_id:
            cart["services"].pop(i)
            break
    else:
        return False
    if not cart["services"]:
        carts.pop(master_id, None)
    context.user_data["carts"] = carts
    _cart_touch(context)
    stats_store.bump("funnel.cart_removed")
    stats_store.save()
    return True


def _cart_remove_last(context, master_id: str) -> bool:
    carts = _cart_get(context)
    cart = carts.get(master_id)
    if not cart or not cart["services"]:
        return False
    cart["services"].pop()
    if not cart["services"]:
        carts.pop(master_id, None)
    context.user_data["carts"] = carts
    _cart_touch(context)
    stats_store.bump("funnel.cart_removed")
    stats_store.save()
    return True


def _cart_clear(context, master_id: str | None = None):
    if master_id is None:
        context.user_data.pop("carts", None)
    else:
        carts = _cart_get(context)
        carts.pop(master_id, None)
        context.user_data["carts"] = carts
    context.user_data.pop("cart_updated_at", None)


def _cart_normalize(cart: dict) -> tuple[list[str], str | None]:
    """
    Группирует дубли в электро и суммирует длительности.
    Возвращает (sids_for_dikidi, error).
    Если точной услуги под сумму нет — пытается разложить на несколько
    (например 5×30 = 2ч + 30мин).
    """
    services = cart.get("services", [])
    if not services:
        return [], "empty"

    # Группировка по sid
    groups: dict[str, dict] = {}
    for s in services:
        sid = s["service_id"]
        if sid not in groups:
            groups[sid] = {
                "name": s["name"],
                "time": s.get("time") or 0,
                "count": 0,
                "parent_code": s.get("parent_code", ""),
            }
        groups[sid]["count"] += 1

    # Плоский список sid (без дублей)
    result: list[str] = []
    for sid, g in groups.items():
        total_min = g["time"] * g["count"]
        # Если это не электро — просто добавляем sid (там дублей нет)
        if g["parent_code"] != "epilation":
            result.append(sid)
            continue
        # Для электро — нормализуем по известным длительностям
        if g["count"] == 1:
            result.append(sid)
            continue
        # Ищем услугу с точной длительностью
        mapped = _map_electro_duration(total_min)
        if mapped is None:
            return [], f"no_match_{total_min}"
        result.extend(mapped)

    return result, None


def _map_electro_duration(total_min: int) -> list[str] | None:
    """Раскладывает суммарную длительность в список sid'ов известных услуг."""
    # Доступные длительности в BOOKING (по порядку убывания)
    known = []
    for s in BOOKING["epilation"]["services"]:
        if s.get("virtual"):
            continue
        if s.get("duration"):
            sid = service_id_from_url(s.get("url", ""))
            if sid:
                known.append((s["duration"], sid))
    known.sort(reverse=True)   # 180, 120, 90, 60, 30

    result = []
    rest = total_min
    for dur, sid in known:
        while rest >= dur:
            result.append(sid)
            rest -= dur
    if rest != 0:
        return None
    return result


def _cart_rows(context) -> list:
    """Кнопка «🛍️ Корзина (N)», если не пуста."""
    n = _cart_count(context)
    if not n:
        return []
    return [[InlineKeyboardButton(f"🛍️ Корзина ({n})", callback_data="slot:cart_view")]]


# ==============================================
# 4HANDS — поиск и рендер
# ==============================================

async def _4h_search_range(base_sid: str, masters: dict[str, str],
                            days_from: int = 0, days_to: int = None) -> tuple[list[dict], bool]:
    """Возвращает (options, had_error)."""
    if days_to is None:
        days_to = days_from + DAYS_4H_INITIAL

    today = date.today()
    d_start = today + timedelta(days=days_from)
    d_end = today + timedelta(days=days_to)
    had_error = False

    # Шаг 1: get_dates для всех мастеров параллельно
    async def fetch_dates(mid):
        nonlocal had_error
        try:
            return (mid, await dikidi.get_dates(base_sid, mid, d_start, d_end))
        except DikidiError as e:
            log.warning("4h get_dates %s: %s", mid, e)
            had_error = True
            return (mid, [])

    master_dates_list = await asyncio.gather(*(fetch_dates(mid) for mid in masters))
    master_dates = dict(master_dates_list)

    # Шаг 2: собираем нужные (master, date)
    pairs = list(combinations(masters.keys(), 2))
    needed: set[tuple[str, str]] = set()
    for mid_a, mid_b in pairs:
        common = set(master_dates.get(mid_a, [])) & set(master_dates.get(mid_b, []))
        for d in common:
            needed.add((mid_a, d))
            needed.add((mid_b, d))

    if not needed:
        return [], had_error

    # Шаг 3: available_slots параллельно
    async def fetch_slots(mid, date_str):
        nonlocal had_error
        try:
            day = date.fromisoformat(date_str)
            return ((mid, date_str), await dikidi.available_slots(base_sid, mid, day))
        except (DikidiError, ValueError) as e:
            log.warning("4h slots %s %s: %s", mid, date_str, e)
            had_error = True
            return ((mid, date_str), [])

    slot_results = await asyncio.gather(
        *(fetch_slots(mid, d) for mid, d in needed)
    )
    master_slots = dict(slot_results)

    # Шаг 4: пересечение
    options = []
    for mid_a, mid_b in pairs:
        common_dates = set(master_dates.get(mid_a, [])) & set(master_dates.get(mid_b, []))
        for date_str in common_dates:
            times_a = {t.strftime("%H:%M") for t in master_slots.get((mid_a, date_str), [])}
            times_b = {t.strftime("%H:%M") for t in master_slots.get((mid_b, date_str), [])}
            for t in sorted(times_a & times_b):
                options.append({
                    "mid_a": mid_a, "name_a": masters[mid_a],
                    "mid_b": mid_b, "name_b": masters[mid_b],
                    "date": date_str, "time": t,
                })

    return options, had_error


def _diversify_slots(options: list[dict]) -> list[dict]:
    """
    ≤2 на (pair, date, interval)
    ≤3 на (pair, date)
    """
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for opt in options:
        key = (opt["mid_a"], opt["mid_b"], opt["date"])
        groups[key].append(opt)

    result: list[dict] = []
    for key, group in groups.items():
        intervals: dict[str, list[dict]] = {"early": [], "mid": [], "late": [], "outside": []}
        for opt in group:
            t = dtime.fromisoformat(opt["time"])
            if dtime(10, 0) <= t < dtime(13, 0):
                intervals["early"].append(opt)
            elif dtime(13, 0) <= t < dtime(17, 0):
                intervals["mid"].append(opt)
            elif dtime(17, 0) <= t < dtime(21, 0):
                intervals["late"].append(opt)
            else:
                intervals["outside"].append(opt)

        for k in intervals:
            intervals[k].sort(key=lambda o: o["time"])
            if len(intervals[k]) > 2:
                intervals[k] = [intervals[k][0], intervals[k][-1]]

        picked: list[dict] = []
        order = ["early", "mid", "late", "outside"]
        while len(picked) < 3:
            progress = False
            for name in order:
                if len(picked) >= 3:
                    break
                if intervals[name]:
                    picked.append(intervals[name].pop(0))
                    progress = True
            if not progress:
                break
        result.extend(picked)

    return result


async def _4h_search(base_sid: str) -> tuple[list[dict], str | None, int]:
    """Возвращает (options, error, days_searched)."""
    masters = await _masters_for_service(base_sid)
    masters = {mid: name for mid, name in masters.items()
               if not _is_excluded_from_4h(name)}
    if len(masters) < 2:
        return [], "not_enough_masters", 0

    options, err1 = await _4h_search_range(base_sid, masters,
                                            days_from=0, days_to=DAYS_4H_INITIAL)
    options = _diversify_slots(options)
    days = DAYS_4H_INITIAL

    if len(options) < MAX_4H_OPTIONS:
        extra, err2 = await _4h_search_range(base_sid, masters,
                                              days_from=DAYS_4H_INITIAL,
                                              days_to=DAYS_4H_EXTENDED)
        extra = _diversify_slots(extra)
        seen = {(o["mid_a"], o["mid_b"], o["date"], o["time"]) for o in options}
        for opt in extra:
            k = (opt["mid_a"], opt["mid_b"], opt["date"], opt["time"])
            if k not in seen:
                options.append(opt)
                seen.add(k)
        days = DAYS_4H_EXTENDED

    options.sort(key=lambda o: (o["date"], o["time"]))
    options = options[:MAX_4H_OPTIONS]
    had_error = err1 or (locals().get("err2") or False)
    return options, None, days


def _get_filterable_masters(context) -> dict[str, str]:
    opts = context.user_data.get("4h_all_options", [])
    seen: dict[str, str] = {}
    for o in opts:
        seen[o["mid_a"]] = o["name_a"]
        seen[o["mid_b"]] = o["name_b"]
    return seen


def _get_filtered_options(context) -> list[dict]:
    opts = context.user_data.get("4h_all_options", [])
    mid = context.user_data.get("4h_filter_mid")
    if mid:
        return [o for o in opts if mid in (o["mid_a"], o["mid_b"])]
    return opts


async def slot_4h_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split(":", 2)
    if len(parts) < 3:
        await safe_edit(q, context, "⚠️ Некорректный вызов.")
        return
    virtual_code = parts[2]
    service = VIRTUAL_SERVICES.get(virtual_code)
    if not service:
        await safe_edit(q, context, "⚠️ Услуга не найдена.")
        return

    stats_store.bump("funnel.4hands_used")
    stats_store.save()

    options, error, days = await _4h_search(service["base_service_id"])

    if error == "not_enough_masters":
        await _render_4h_no_options(update, context, virtual_code, "not_enough_masters")
        return
    if not options:
        await _render_4h_no_options(update, context, virtual_code, "no_slots")
        return

    context.user_data["4h_all_options"] = options
    context.user_data["4h_virtual"] = virtual_code
    context.user_data["4h_service_name"] = service["name"]
    context.user_data["4h_searched_days"] = days

    # Автофильтр по контекстному мастеру (из новой ветки)
    ctx_mid = context.user_data.get("slot_master_id")
    ctx_name = context.user_data.get("slot_master_name")
    if ctx_mid and any(ctx_mid in (o["mid_a"], o["mid_b"]) for o in options):
        context.user_data["4h_filter_mid"] = ctx_mid
        context.user_data["4h_filter_reason"] = "context"
        context.user_data["4h_context_name"] = ctx_name
    else:
        context.user_data["4h_filter_mid"] = None
        context.user_data["4h_filter_reason"] = None
        context.user_data["4h_context_name"] = None

    await _render_4h_list(update, context)


async def _render_4h_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    options = _get_filtered_options(context)
    all_opts = context.user_data.get("4h_all_options", [])
    service_name = context.user_data.get("4h_service_name", "")
    filter_mid = context.user_data.get("4h_filter_mid")
    reason = context.user_data.get("4h_filter_reason")
    ctx_name = context.user_data.get("4h_context_name", "")

    lines = [f"🤝 {service_name}", ""]
    if filter_mid and reason == "context":
        lines.append(f"👩 Мастер: {ctx_name}")
    elif filter_mid:
        fname = next((o["name_a"] if o["mid_a"] == filter_mid else o["name_b"]
                     for o in all_opts if filter_mid in (o["mid_a"], o["mid_b"])), "")
        lines.append(f"👩 Фильтр: только с {fname}")

    n_dates = len({o["date"] for o in options})
    lines.append("")
    lines.append(f"Найдено вариантов: {len(options)} (на {n_dates} датах)")
    if len(all_opts) < MAX_4H_OPTIONS:
        lines.append(f"Поиск расширен на {context.user_data.get('4h_searched_days', 30)} дней.")
    lines.append("")

    for i, o in enumerate(options, 1):
        lines.append(f"{i}. {o['name_a']} + {o['name_b']} — {_format_ru_date(o['date'])} в {o['time']}")

    rows = []
    for i in range(0, len(options), 3):
        row = [InlineKeyboardButton(str(j + 1), callback_data=f"slot:4h_pick:{j}")
               for j in range(i, min(i + 3, len(options)))]
        rows.append(row)

    if reason == "context":
        rows.append([InlineKeyboardButton("🔍 Показать все пары",
                                          callback_data="slot:4h_filter:all")])
    else:
        filterable = _get_filterable_masters(context)
        if len(filterable) >= 2:
            names = list(filterable.items())
            for i in range(0, len(names), 2):
                row = [InlineKeyboardButton(f"👩 {name}",
                                             callback_data=f"slot:4h_filter:{mid}")
                       for mid, name in names[i:i + 2]]
                rows.append(row)
            if filter_mid:
                rows.append([InlineKeyboardButton("🔍 Показать все пары",
                                                  callback_data="slot:4h_filter:all")])

    back_cb = "slot:back:cats" if context.user_data.get("slot_tree") else "book:start_services"
    rows.append([InlineKeyboardButton("◀️ К выбору длительности", callback_data=back_cb)])
    rows.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])

    await safe_edit(q, context, hp(f"🤝 {service_name}", "\n".join(lines)), kb(*rows))


async def slot_4h_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split(":", 2)
    mid = parts[2] if len(parts) > 2 else "all"
    if mid == "all":
        context.user_data["4h_filter_mid"] = None
    else:
        context.user_data["4h_filter_mid"] = mid
    context.user_data["4h_filter_reason"] = None
    await _render_4h_list(update, context)


async def slot_4h_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try:
        idx = int(q.data.split(":", 2)[2])
    except (ValueError, IndexError):
        await _render_4h_list(update, context)
        return
    options = _get_filtered_options(context)
    if idx >= len(options):
        await _render_4h_list(update, context)
        return
    context.user_data["4h_selected"] = options[idx]
    await _render_4h_confirm(update, context)


async def _render_4h_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    opt = context.user_data.get("4h_selected")
    service_name = context.user_data.get("4h_service_name", "")
    if not opt:
        await _render_4h_list(update, context)
        return

    stats_store.bump("funnel.4hands_completed")
    stats_store.save()

    day = date.fromisoformat(opt["date"]).strftime("%d.%m.%Y")

    msg = (
        f"Запишите меня на {service_name.lower()} "
        f"у мастеров {opt['name_a']} и {opt['name_b']} "
        f"на {day} в {opt['time']}."
    )
    admin_url = chat_url(msg)

    text = (
        "✅ Вы выбрали:\n\n"
        f"🤝 Услуга: {service_name}\n"
        f"👩 Мастера: {opt['name_a']} и {opt['name_b']}\n"
        f"📅 Дата: {day}\n"
        f"⏰ Время: {opt['time']}\n\n"
        "💰 Стоимость: уточните у администратора при подтверждении.\n\n"
        "Нажмите кнопку ниже — откроется чат с администратором студии, "
        "и сообщение с вашей заявкой уже будет подготовлено. "
        "Останется только отправить его. "
        "Администратор подтвердит запись и свяжется с вами."
    )

    keyboard = [
        [InlineKeyboardButton("📩 Отправить заявку администратору", url=admin_url)],
        [InlineKeyboardButton("◀️ К вариантам", callback_data="slot:4h_back:list")],
        [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
    ]

    await safe_edit(q, context,
                    hp(f"🤝 {service_name} → {opt['name_a']} + {opt['name_b']}", text),
                    kb(*keyboard))


async def _render_4h_no_options(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                 virtual_code: str, reason: str):
    q = update.callback_query
    service = VIRTUAL_SERVICES.get(virtual_code, {})
    sname = service.get("name", "Электроэпиляция в 4 руки")

    msg = f"Здравствуйте! Хочу записаться на {sname.lower()}. Подскажите, как это можно организовать."
    admin_url = chat_url(msg)

    if reason == "not_enough_masters":
        body = (
            "⚠️ Сейчас недостаточно мастеров, которые выполняют эту услугу.\n\n"
            "Напишите администратору — он подскажет, как организовать процедуру."
        )
    elif virtual_code == "4hands_3h":
        body = (
            "⚠️ На ближайшие 37 дней не нашлось времени, когда два мастера "
            "свободны одновременно на 3 часа.\n\n"
            "Но есть варианты на 2 часа — их проще совместить."
        )
    else:
        body = (
            "⚠️ На ближайшие 37 дней нет подходящих вариантов.\n\n"
            "Напишите администратору — он подскажет, как организовать процедуру."
        )

    rows = []
    if virtual_code == "4hands_3h" and reason == "no_slots":
        rows.append([InlineKeyboardButton("🤝 Показать варианты на 2 часа",
                                          callback_data="slot:4h_start:4hands_2h")])
    rows.append([InlineKeyboardButton("💬 Написать администратору", url=admin_url)])
    back_cb = "slot:back:cats" if context.user_data.get("slot_tree") else "book:start_services"
    rows.append([InlineKeyboardButton("◀️ К выбору длительности", callback_data=back_cb)])
    rows.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])

    await safe_edit(q, context, hp(f"🤝 {sname}", body), kb(*rows))


# ==============================================
# ВЕТКА «СНАЧАЛА МАСТЕР»
# ==============================================

async def slot_show_masters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    _clear_master_state(context.user_data)
    _clear_msrv_state(context.user_data)
    _clear_4h_state(context.user_data)
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
    rows.extend(_cart_rows(context))
    rows.append([InlineKeyboardButton("◀️ К выбору способа", callback_data="main:booking")])
    rows.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])
    await safe_edit(q, context,
                    hp("📅 Хочу записаться → Мастера", "👩 Выбери специалиста:"),
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
    _clear_4h_state(context.user_data)

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


async def _render_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    tree = context.user_data.get("slot_tree")
    if not tree:
        await slot_show_masters(update, context)
        return
    name = context.user_data.get("slot_master_name", "")
    rows = [[InlineKeyboardButton(cat["title"], callback_data=f"slot:cat:{code}")]
            for code, cat in tree.items()]
    rows.extend(_cart_rows(context))
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
    is_excluded = _is_excluded_from_4h(name)

    rows = []
    if "sub" in cat:
        for sub in cat["sub"]:
            rows.append([InlineKeyboardButton(sub["title"],
                                              callback_data=f"slot:sub:{code}:{sub['code']}")])
    if "services" in cat:
        for i, s in enumerate(cat["services"]):
            rows.append([InlineKeyboardButton(f"{s['name']} — {s['price']}",
                                              callback_data=f"slot:srv:{code}:{i}")])
    # Виртуальные услуги 4hands (только для не-исключённых)
    if not is_excluded:
        for s in BOOKING.get(code, {}).get("services", []):
            if s.get("virtual"):
                cb = f"slot:4h_start:{s['virtual']}"
                if len(cb.encode("utf-8")) <= MAX_CALLBACK_LEN:
                    rows.append([InlineKeyboardButton(
                        f"🤝 {s['name']}", callback_data=cb
                    )])

    rows.extend(_cart_rows(context))
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
        rows.extend(_cart_rows(context))
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
        label = f"{s['name']} — {s['price']}"
        if s.get("duration"):
            label += f" · {_format_duration(s['duration'])}"
        rows.append([InlineKeyboardButton(label, callback_data=cb)])

    # Виртуальные 4hands — только если категория epilation и мастер не исключён
    if parent_code == "epilation" and not _is_excluded_from_4h(name):
        for s in BOOKING.get("epilation", {}).get("services", []):
            if s.get("virtual"):
                cb = f"slot:4h_start:{s['virtual']}"
                if len(cb.encode("utf-8")) <= MAX_CALLBACK_LEN:
                    rows.append([InlineKeyboardButton(f"🤝 {s['name']}", callback_data=cb)])

    if sub_code and sub2_code:
        back_cb = f"slot:sub:{parent_code}:{sub_code}"
    elif sub_code:
        back_cb = f"slot:cat:{parent_code}"
    else:
        back_cb = "slot:back:cats"

    rows.extend(_cart_rows(context))
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
# СТАРАЯ ВЕТКА: УСЛУГА → МАСТЕРА ДЛЯ НЕЁ
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
                       f"✅ {service['name']} — {service['price']}\n\nВыберите мастера:"),
                    kb(*rows))


async def _msrv_back_render(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
# НОВАЯ ВЕТКА: УСЛУГА → 14 ДНЕЙ
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

    # Сохраняем в state и ведём на промежуточный экран (cart_pick)
    context.user_data["slot_service_id"] = sid
    context.user_data["slot_service_name"] = s["name"]
    context.user_data["slot_service_url"] = s.get("url", "")
    context.user_data["slot_service_booking_cb"] = booking_cb
    context.user_data["slot_service_parent_code"] = parent_code
    context.user_data["slot_back_to_services"] = back_cb
    # Время и цена — для корзины
    context.user_data["slot_service_time"] = s.get("duration")
    context.user_data["slot_service_price"] = s.get("price", "")

    await _render_service_pick(update, context, s, back_cb, parent_code)


async def _render_service_pick(update, context, s, back_cb, parent_code):
    """Промежуточный экран: [🛍️ В корзину] [🔎 Сразу найти время]"""
    q = update.callback_query
    name = context.user_data.get("slot_master_name", "")

    text = f"✅ {s['name']} — {s['price']}"
    if s.get("duration"):
        text += f" · {_format_duration(s['duration'])}"
    text += "\n\nЧто сделать?"

    rows = [
        [InlineKeyboardButton("🛍️ В корзину", callback_data="slot:cart_add")],
        [InlineKeyboardButton("🔎 Сразу найти время", callback_data="slot:direct_find")],
        [InlineKeyboardButton("◀️ К услугам", callback_data=back_cb)],
        [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
    ]
    await safe_edit(q, context, hp(f"📅 Хочу записаться → {name} → {s['name']}", text), kb(*rows))


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
# ЭКРАН ДАТ (общий)
# ==============================================

async def _render_dates_from_state(q, context, from_cart: bool = False):
    sid = context.user_data.get("slot_service_id")
    mid = context.user_data.get("slot_master_id")
    sname = context.user_data.get("slot_service_name", "")
    mname = context.user_data.get("slot_master_name", "")
    back_cb = context.user_data.get("slot_back_to_services") or "slot:back:cats"
    if not sid or not mid:
        await slot_show_masters(None, context)
        return

    service = SERVICE_BY_ID.get(sid) or {"name": sname, "price": ""}
    days, had_error = await _check_days(sid, mid)
    await _render_dates(q, context, days, service, mname, back_cb,
                        from_cart=from_cart, had_error=had_error)


async def _render_dates(q, context, days, service, master_name, back_cb,
                        from_cart: bool = False, had_error: bool = False,
                        cart_sids: list[str] | None = None,
                        cart_label: str | None = None):
    sid = service_id_from_url(service.get("url", "")) or context.user_data.get("slot_service_id", "")
    header = f"👩 {master_name}\n✅ {service['name']}"
    if service.get("price"):
        header += f" — {service['price']}"
    if cart_label:
        header = f"👩 {master_name}\n🛍️ {cart_label}"

    is_msrv = (back_cb or "").startswith("slot:msrv")
    back_label = "◀️ К мастерам" if is_msrv else "◀️ К услугам"
    other_master_cb = "slot:msrv_back" if is_msrv else "slot:back:masters"

    stats_store.bump("funnel.dates_shown")
    stats_store.save()

    rows = []
    if had_error and not days:
        text = (f"{header}\n\n"
                "⚠️ Не удалось получить расписание.\n\n"
                "Попробуйте ещё раз через минуту.")
        retry_cb = "slot:cart_find" if from_cart else "slot:back:dates"
        rows.append([InlineKeyboardButton("🔄 Повторить", callback_data=retry_cb)])
        rows.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])
        await safe_edit(q, context,
                        hp(f"📅 Хочу записаться → {master_name} → {service['name']}", text),
                        kb(*rows))
        return

    if not days:
        stats_store.bump("funnel.no_slots_14days")
        stats_store.save()
        if from_cart:
            text = (f"{header}\n\n"
                    "⚠️ На ближайшие 14 дней нет окон на такой объём.\n\n"
                    "Возможно, мастер сможет продлить день — уточните у администратора.")
            admin_msg = f"Здравствуйте! Хочу записаться на {cart_label or 'несколько услуг'}. Подскажите, есть ли варианты."
            admin_url = chat_url(admin_msg)
            rows.append([InlineKeyboardButton("💬 Написать администратору", url=admin_url)])
            rows.append([InlineKeyboardButton("◀️ К корзине", callback_data="slot:cart_view")])
        else:
            text = (f"{header}\n\n"
                    "⚠️ На ближайшие 14 дней свободных окон нет.\n\n"
                    "Можно попробовать другого мастера — у него может быть другое расписание.")
            rows.append([InlineKeyboardButton("👩 Выбрать другого мастера",
                                               callback_data=other_master_cb)])
            rows.append([InlineKeyboardButton(back_label, callback_data=back_cb)])
        rows.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])
        await safe_edit(q, context,
                        hp(f"📅 Хочу записаться → {master_name} → {service['name']}", text),
                        kb(*rows))
        return

    rows = [[InlineKeyboardButton(_format_ru_date(d),
                                   callback_data=f"slot:date:{d.isoformat()}")]
            for d, _ in days]
    if len(days) < MAX_DATES:
        text = (f"{header}\n\nВыберите дату:\n\n"
                "На ближайшие 14 дней больше окон нет.")
    else:
        text = f"{header}\n\nВыберите дату:"

    if from_cart and cart_sids:
        # «Найти время» — использует нормализованные sid из state
        pass
    elif sid:
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
    days, had_error = await _check_days(sid, mid)
    await _render_dates(q, context, days, service, mname, back_cb, had_error=had_error)


# ==============================================
# ЭКРАН ВРЕМЁН
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

    text = (f"👩 {mname}\n✅ {sname}\n📅 {date_str}\n\nВыберите удобное время:")

    await safe_edit(q, context,
                    hp(f"📅 Хочу записаться → {mname} → {sname}", text),
                    kb(*rows))


async def slot_choose_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split(":")
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

    msg = (f"Запишите меня на услугу «{sname}» у мастера {mname} "
           f"на {date_str} в {t}.")
    admin_url = chat_url(msg)

    text = (f"✅ Вы выбрали:\n\n"
            f"👩 Мастер: {mname}\n"
            f"💡 Услуга: {service['name']}")
    if service.get("price"):
        text += f" — {service['price']}"
    text += (f"\n📅 Дата: {date_str}\n"
             f"⏰ Время: {t}\n\n"
             "💰 Стоимость: уточните у администратора при подтверждении.\n\n"
             "Нажмите кнопку ниже — откроется чат с администратором студии, "
             "и сообщение с вашей заявкой уже будет подготовлено. "
             "Останется только отправить его. "
             "Администратор подтвердит запись и свяжется с вами.")

    keyboard = [
        [InlineKeyboardButton("📩 Отправить заявку администратору", url=admin_url)],
        [InlineKeyboardButton("◀️ К временам", callback_data=f"slot:date:{ds}")],
        [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
    ]

    await safe_edit(q, context,
                    hp(f"📅 Хочу записаться → {mname} → {sname} → {t}", text),
                    kb(*keyboard))
    # ==============================================
# ХЕЛПЕРЫ — плюрализация
# ==============================================

def _plural_services(n: int) -> str:
    if n == 1:
        return "услуга"
    if n in (2, 3, 4):
        return "услуги"
    return "услуг"


def _parse_price_int(price_str) -> int:
    if not price_str:
        return 0
    s = str(price_str).replace(" ", "").replace("\u00a0", "")
    digits = ""
    for ch in s:
        if ch.isdigit():
            digits += ch
        else:
            break
    return int(digits) if digits else 0


# ==============================================
# КОРЗИНА — рендер
# ==============================================

async def _cart_render_empty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    text = ("🛍️ Корзина пуста.\n\n"
            "Добавьте услуги из меню и возвращайтесь.")
    rows = [
        [InlineKeyboardButton("👩 К выбору мастера", callback_data="slot:start")],
        [InlineKeyboardButton("📋 К выбору услуги", callback_data="book:start_services")],
        [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
    ]
    await safe_edit(q, context, hp("🛍️ Корзина", text), kb(*rows))


async def _cart_render_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать корзины: 0 — пусто, 1 — сразу открыть, 2+ — список."""
    q = update.callback_query
    carts = _cart_get(context)
    if not carts:
        await _cart_render_empty(update, context)
        return
    if len(carts) == 1:
        mid = next(iter(carts.keys()))
        await _cart_render_one(update, context, mid)
        return

    stats_store.bump("funnel.cart_used")
    stats_store.save()

    lines = ["🛍️ Ваши корзины", ""]
    rows = []
    for mid, cart in carts.items():
        n = len(cart.get("services", []))
        total_time = sum((s.get("time") or 0) for s in cart["services"])
        total_price = sum(_parse_price_int(s.get("price", "")) for s in cart["services"])
        line = f"👩 {cart.get('master_name', 'Мастер')} — {n} {_plural_services(n)}"
        if total_time:
            line += f" · {_format_duration(total_time)}"
        if total_price:
            line += f" · {total_price} ₽"
        lines.append(line)
        rows.append([InlineKeyboardButton(
            f"👩 {cart.get('master_name', 'Мастер')}",
            callback_data=f"slot:cart_view:{mid}"
        )])

    rows.append([InlineKeyboardButton("🗑 Очистить всё", callback_data="slot:cart_clear_all")])
    rows.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])

    await safe_edit(q, context, hp("🛍️ Корзины", "\n".join(lines)), kb(*rows))


async def _cart_render_one(update: Update, context: ContextTypes.DEFAULT_TYPE, mid: str):
    """Корзина конкретного мастера (с группировкой дублей)."""
    q = update.callback_query
    carts = _cart_get(context)
    cart = carts.get(mid)
    if not cart:
        await _cart_render_all(update, context)
        return

    stats_store.bump("funnel.cart_used")
    stats_store.save()

    mname = cart.get("master_name", "Мастер")
    services = cart.get("services", [])
    n_total = len(services)

    # Группировка по sid
    groups: dict[str, dict] = {}
    order: list[str] = []
    for s in services:
        sid = s["service_id"]
        if sid not in groups:
            groups[sid] = {
                "name": s["name"],
                "price": s.get("price", ""),
                "time": s.get("time") or 0,
                "count": 0,
            }
            order.append(sid)
        groups[sid]["count"] += 1

    lines = [f"🛍️ Корзина — {mname} ({n_total} из {CART_MAX_SERVICES})", ""]
    total_time = 0
    total_price = 0
    for sid in order:
        g = groups[sid]
        total_time += g["time"] * g["count"]
        total_price += _parse_price_int(g["price"]) * g["count"]
        if g["count"] == 1:
            line = f"• {g['name']}"
            if g["time"]:
                line += f" · {_format_duration(g['time'])}"
            if g["price"]:
                line += f" · {g['price']}"
        else:
            line = f"• {g['count']} × {g['name']}"
            if g["time"]:
                line += f" — {_format_duration(g['time'] * g['count'])}"
        lines.append(line)

    lines.append("")
    if total_time:
        lines.append(f"⏱ Общая длительность: {_format_duration(total_time)}")
    if total_price:
        lines.append(f"💰 Сумма: {total_price} ₽")

    # Кнопки «✕ Убрать» — по группам
    rows = []
    for sid in order:
        g = groups[sid]
        if g["count"] == 1:
            label = f"✕ Убрать: {g['name']}"
        else:
            label = f"✕ Убрать одну: {g['name']}"
        cb = f"slot:cart_remove:{mid}:{sid}"
        if len(cb.encode("utf-8")) <= 64:
            rows.append([InlineKeyboardButton(label[:60], callback_data=cb)])

    rows.append([InlineKeyboardButton("🔎 Найти время",
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
    rows.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])

    await safe_edit(q, context, hp(f"🛍️ Корзина — {mname}", "\n".join(lines)), kb(*rows))


async def _render_cart_added(update: Update, context: ContextTypes.DEFAULT_TYPE,
                              mid: str, back_cb: str):
    q = update.callback_query
    carts = _cart_get(context)
    cart = carts.get(mid) or {"master_name": context.user_data.get("slot_master_name", ""),
                              "services": []}
    mname = cart.get("master_name", "Мастер")
    n_total = _cart_count(context)

    text = f"✅ Услуга добавлена в корзину {mname}."
    if len(carts) > 1:
        text += "\n\nℹ️ У вас несколько корзин:\n"
        for m_id, c in carts.items():
            cnt = len(c.get("services", []))
            text += f"• {c.get('master_name', 'Мастер')} — {cnt} {_plural_services(cnt)}\n"

    rows = [
        [InlineKeyboardButton(f"🛍️ Корзина ({n_total})", callback_data="slot:cart_view")],
        [InlineKeyboardButton("➕ Добавить ещё",
                               callback_data=f"slot:cart_add_more:{mid}")],
        [InlineKeyboardButton("◀️ К услугам", callback_data=back_cb)],
        [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
    ]
    await safe_edit(q, context, hp("🛍️ Корзина", text), kb(*rows))


# ==============================================
# КОРЗИНА — добавление
# ==============================================

async def slot_cart_add_from_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Кнопка «В корзину» на промежуточном экране. Всё из state."""
    q = update.callback_query
    mid = context.user_data.get("slot_master_id")
    mname = context.user_data.get("slot_master_name")
    sid = context.user_data.get("slot_service_id")
    sname = context.user_data.get("slot_service_name")
    time_val = context.user_data.get("slot_service_time")
    price_val = context.user_data.get("slot_service_price", "")
    parent_code = context.user_data.get("slot_service_parent_code", "")
    back_cb = context.user_data.get("slot_back_to_services") or "slot:back:cats"

    if not (mid and sid and sname):
        await safe_edit(q, context, "⚠️ Сессия устарела. Начни заново.",
                        kb([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")]))
        return

    ok, reason = _cart_add(context, mid, mname, {
        "service_id": sid, "name": sname, "price": price_val,
        "time": time_val, "parent_code": parent_code,
    })

    if not ok:
        if reason == "limit":
            text = (f"⚠️ В корзине уже {CART_MAX_SERVICES} услуги — "
                    f"больше не влезет в один визит.\n\n"
                    f"Услугу «{sname}» не добавили.")
        elif reason == "dup":
            text = f"⚠️ Услуга «{sname}» уже в корзине."
        else:
            text = "⚠️ Не удалось добавить услугу."
        rows = [
            [InlineKeyboardButton("🛍️ Корзина", callback_data="slot:cart_view")],
            [InlineKeyboardButton("◀️ К услугам", callback_data=back_cb)],
            [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
        ]
        await safe_edit(q, context, hp("🛍️ Корзина", text), kb(*rows))
        return

    await _render_cart_added(update, context, mid, back_cb)


async def slot_cart_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Из старой ветки — «В корзину» на карточке услуги. Мастера ещё нет."""
    q = update.callback_query
    parts = q.data.split(":", 2)
    if len(parts) < 3:
        await safe_edit(q, context, "⚠️ Некорректный вызов.")
        return
    sid = parts[2]
    service = SERVICE_BY_ID.get(sid)
    if not service:
        await safe_edit(q, context, "⚠️ Услуга не найдена.",
                        kb([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")]))
        return

    filtered = await _masters_for_service(sid)
    if not filtered:
        await safe_edit(q, context,
                        f"⚠️ К сожалению, ни один мастер сейчас не выполняет услугу «{service['name']}».",
                        kb([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")]))
        return

    sorted_masters = dict(_sort_masters(filtered))
    context.user_data["cart_pending_service"] = {
        "service_id": sid, "name": service["name"],
        "price": service.get("price", ""),
        "time": service.get("duration"),
    }

    rows = [[InlineKeyboardButton(n, callback_data=f"slot:cart_add_to:{sid}:{mid}")]
            for mid, n in sorted_masters.items()]
    rows.append([InlineKeyboardButton("◀️ К услугам", callback_data="book:start_services")])
    rows.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])

    await safe_edit(q, context,
                    hp(f"🛍️ В корзину → {service['name']}",
                       f"У какого мастера добавить «{service['name']}»?\n\n"
                       f"Выберите мастера:"),
                    kb(*rows))


async def slot_cart_add_to(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split(":")
    if len(parts) < 4:
        await safe_edit(q, context, "⚠️ Некорректный вызов.")
        return
    sid, mid = parts[2], parts[3]

    service = SERVICE_BY_ID.get(sid)
    if not service:
        await safe_edit(q, context, "⚠️ Услуга не найдена.")
        return

    try:
        masters = await dikidi.get_masters()
    except DikidiError:
        masters = {}
    mname = masters.get(mid, "Мастер")

    path = SERVICE_PATH.get(sid)
    parent_code = path[1] if path else ""

    ok, reason = _cart_add(context, mid, mname, {
        "service_id": sid, "name": service["name"],
        "price": service.get("price", ""),
        "time": service.get("duration"),
        "parent_code": parent_code,
    })
    context.user_data.pop("cart_pending_service", None)

    if not ok:
        if reason == "limit":
            text = (f"⚠️ В корзине уже {CART_MAX_SERVICES} услуги — "
                    f"больше не влезет в один визит.")
        elif reason == "dup":
            text = f"⚠️ Услуга «{service['name']}» уже в корзине."
        else:
            text = "⚠️ Не удалось добавить услугу."
        rows = [
            [InlineKeyboardButton("🛍️ Корзина", callback_data="slot:cart_view")],
            [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
        ]
        await safe_edit(q, context, hp("🛍️ Корзина", text), kb(*rows))
        return

    await _render_cart_added(update, context, mid, "book:start_services")


# ==============================================
# КОРЗИНА — просмотр / удаление
# ==============================================

async def slot_cart_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _cart_render_all(update, context)


async def slot_cart_view_master(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split(":")
    if len(parts) < 3:
        await _cart_render_all(update, context)
        return
    await _cart_render_one(update, context, parts[2])


async def slot_cart_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split(":")
    if len(parts) < 4:
        await _cart_render_all(update, context)
        return
    mid, sid = parts[2], parts[3]
    _cart_remove(context, mid, sid)
    await _cart_render_one(update, context, mid)


async def slot_cart_remove_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split(":")
    if len(parts) < 3:
        await _cart_render_all(update, context)
        return
    mid = parts[2]
    _cart_remove_last(context, mid)
    await _cart_render_one(update, context, mid)


async def slot_cart_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать подтверждение очистки одной корзины."""
    q = update.callback_query
    parts = q.data.split(":")
    if len(parts) < 3:
        await _cart_render_all(update, context)
        return
    mid = parts[2]
    cart = _cart_get(context).get(mid)
    if not cart:
        await _cart_render_all(update, context)
        return

    n = len(cart.get("services", []))
    total_price = sum(_parse_price_int(s.get("price", "")) for s in cart["services"])

    text = f"🛍️ Точно очистить корзину {cart.get('master_name', 'Мастер')}?\n\n"
    text += f"Услуг: {n}"
    if total_price:
        text += f" · Сумма: {total_price} ₽"

    rows = [
        [InlineKeyboardButton("✅ Да, очистить",
                               callback_data=f"slot:cart_clear_yes:{mid}")],
        [InlineKeyboardButton("◀️ Нет, оставить",
                               callback_data=f"slot:cart_view:{mid}")],
    ]
    await safe_edit(q, context, hp("🛍️ Корзина", text), kb(*rows))


async def slot_cart_clear_yes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split(":")
    if len(parts) < 3:
        return
    _cart_clear(context, parts[2])
    await _cart_render_all(update, context)


async def slot_cart_clear_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    carts = _cart_get(context)
    if not carts:
        await _cart_render_empty(update, context)
        return
    total_n = sum(len(c.get("services", [])) for c in carts.values())
    text = f"🛍️ Точно очистить все корзины?\n\nУслуг всего: {total_n}"

    rows = [
        [InlineKeyboardButton("✅ Да, очистить всё",
                               callback_data="slot:cart_clear_all_yes")],
        [InlineKeyboardButton("◀️ Нет, оставить",
                               callback_data="slot:cart_view")],
    ]
    await safe_edit(q, context, hp("🛍️ Корзины", text), kb(*rows))


async def slot_cart_clear_all_yes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _cart_clear(context, None)
    await _cart_render_all(update, context)


# ==============================================
# КОРЗИНА — «добавить услугу» → дерево мастера
# ==============================================

async def slot_cart_add_more(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split(":")
    if len(parts) < 3:
        await slot_show_masters(update, context)
        return
    mid = parts[2]

    carts = _cart_get(context)
    cart = carts.get(mid) or {}
    mname = cart.get("master_name")
    if not mname:
        try:
            masters = await dikidi.get_masters()
            mname = masters.get(mid, "Мастер")
        except DikidiError:
            mname = "Мастер"

    context.user_data["slot_master_id"] = mid
    context.user_data["slot_master_name"] = mname

    try:
        dikidi_cats = await dikidi.get_service_categories(mid)
    except DikidiError as e:
        log.warning("cart add_more cats: %s", e)
        await safe_edit(q, context, "⚠️ Не удалось загрузить услуги мастера.",
                        kb([InlineKeyboardButton("🛍️ К корзине",
                                                   callback_data=f"slot:cart_view:{mid}")],
                           [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")]))
        return

    dikidi_ids: set[str] = set()
    for cat in dikidi_cats.values():
        dikidi_ids.update(cat["services"].keys())

    filtered = _filter_booking(BOOKING, dikidi_ids)
    if not filtered:
        await safe_edit(q, context,
                        f"⚠️ У мастера {mname} пока нет доступных услуг.",
                        kb([InlineKeyboardButton("🛍️ К корзине",
                                                   callback_data=f"slot:cart_view:{mid}")],
                           [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")]))
        return

    context.user_data["slot_tree"] = filtered
    context.user_data["slot_path"] = []
    await _render_categories(update, context)


# ==============================================
# КОРЗИНА — поиск времени
# ==============================================

async def slot_cart_find(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split(":")
    if len(parts) >= 3:
        mid = parts[2]
    else:
        mid = context.user_data.get("slot_master_id")

    if not mid:
        await safe_edit(q, context, "⚠️ Сессия устарела. Начни заново.",
                        kb([InlineKeyboardButton("🛍️ К корзине",
                                                   callback_data="slot:cart_view")],
                           [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")]))
        return

    cart = _cart_get(context).get(mid)
    if not cart or not cart.get("services"):
        await safe_edit(q, context, "⚠️ Корзина пуста.",
                        kb([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")]))
        return

    sids, error = _cart_normalize(cart)
    if error:
        if error.startswith("no_match_"):
            try:
                total_min = int(error.split("_")[-1])
            except ValueError:
                total_min = 0
            await _render_cart_unsupported(update, context, mid, total_min)
            return
        await safe_edit(q, context, "⚠️ Не удалось обработать корзину.",
                        kb([InlineKeyboardButton("🛍️ К корзине",
                                                   callback_data=f"slot:cart_view:{mid}")],
                           [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")]))
        return

    stats_store.bump("funnel.cart_multi_search")
    stats_store.save()

    mname = cart.get("master_name", "Мастер")
    total_time = sum((s.get("time") or 0) for s in cart["services"])
    n = len(cart["services"])
    label = f"{n} {_plural_services(n)}"
    if total_time:
        label += f" · {_format_duration(total_time)}"

    days, had_error = await _check_days(sids, mid)
    await _render_dates_cart(q, context, mid, sids, days, label, mname, had_error)


async def _render_dates_cart(q, context, mid, sids, days, label, mname, had_error):
    context.user_data["slot_master_id"] = mid
    context.user_data["slot_master_name"] = mname
    context.user_data["slot_cart_sids"] = sids
    context.user_data["slot_cart_label"] = label

    header = f"👩 {mname}\n🛍️ {label}"

    stats_store.bump("funnel.dates_shown")
    stats_store.save()

    if had_error and not days:
        text = (f"{header}\n\n"
                "⚠️ Не удалось получить расписание.\n\n"
                "Попробуйте ещё раз через минуту.")
        rows = [
            [InlineKeyboardButton("🔄 Повторить", callback_data="slot:cart_find")],
            [InlineKeyboardButton("🛍️ К корзине", callback_data=f"slot:cart_view:{mid}")],
            [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
        ]
        await safe_edit(q, context, hp(f"📅 Хочу записаться → {mname} → {label}", text), kb(*rows))
        return

    if not days:
        stats_store.bump("funnel.no_slots_14days")
        stats_store.save()
        admin_msg = (f"Здравствуйте! Хочу записаться на {label.lower()} "
                     f"у мастера {mname}. Подскажите, есть ли варианты.")
        admin_url = chat_url(admin_msg)
        text = (f"{header}\n\n"
                "⚠️ На ближайшие 14 дней нет окон на такой объём.\n\n"
                "Возможно, мастер сможет продлить день — уточните у администратора.")
        rows = [
            [InlineKeyboardButton("💬 Написать администратору", url=admin_url)],
            [InlineKeyboardButton("🛍️ К корзине", callback_data=f"slot:cart_view:{mid}")],
            [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
        ]
        await safe_edit(q, context, hp(f"📅 Хочу записаться → {mname} → {label}", text), kb(*rows))
        return

    rows = [[InlineKeyboardButton(_format_ru_date(d),
                                   callback_data=f"slot:cart_date:{d.isoformat()}")]
            for d, _ in days]

    if len(days) < MAX_DATES:
        text = (f"{header}\n\nВыберите дату:\n\n"
                "На ближайшие 14 дней больше окон нет.")
    else:
        text = f"{header}\n\nВыберите дату:"

    rows.append([InlineKeyboardButton("🛍️ К корзине", callback_data=f"slot:cart_view:{mid}")])
    rows.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])

    await safe_edit(q, context, hp(f"📅 Хочу записаться → {mname} → {label}", text), kb(*rows))


async def _render_cart_unsupported(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                     mid: str, total_min: int):
    q = update.callback_query
    msg = (f"Здравствуйте! Хочу записаться на {_format_duration(total_min)} "
           f"электроэпиляции. Нужно подобрать окно — такой услуги в записи нет.")
    admin_url = chat_url(msg)
    text = (f"⚠️ Не удаётся подобрать услугу.\n\n"
            f"В корзине: {_format_duration(total_min)} электроэпиляции.\n"
            f"Услуги такой длительности в записи нет.\n\n"
            f"Напишите администратору — он подберёт удобное время.")
    rows = [
        [InlineKeyboardButton("💬 Написать администратору", url=admin_url)],
        [InlineKeyboardButton("🛍️ К корзине", callback_data=f"slot:cart_view:{mid}")],
        [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
    ]
    await safe_edit(q, context, hp("🛍️ Корзина", text), kb(*rows))


# ==============================================
# КОРЗИНА — экран дат и времён
# ==============================================

async def slot_cart_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split(":", 2)
    if len(parts) < 3:
        await slot_show_masters(update, context)
        return
    ds = parts[2]
    try:
        day = date.fromisoformat(ds)
    except ValueError:
        await slot_show_masters(update, context)
        return

    sids = context.user_data.get("slot_cart_sids")
    mid = context.user_data.get("slot_master_id")
    mname = context.user_data.get("slot_master_name", "")
    label = context.user_data.get("slot_cart_label", "")

    if not sids or not mid:
        await safe_edit(q, context, "⚠️ Сессия устарела.",
                        kb([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")]))
        return

    try:
        slots = await dikidi.available_slots(sids, mid, day)
    except DikidiError as e:
        log.warning("cart times %s: %s", day, e)
        await safe_edit(q, context, "⚠️ Не удалось получить расписание.",
                        kb([InlineKeyboardButton("🛍️ К корзине",
                                                   callback_data=f"slot:cart_view:{mid}")],
                           [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")]))
        return

    if not slots:
        await safe_edit(q, context, f"На {day.strftime('%d.%m.%Y')} окон не осталось.",
                        kb([InlineKeyboardButton("🛍️ К корзине",
                                                   callback_data=f"slot:cart_view:{mid}")],
                           [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")]))
        return

    stats_store.bump("funnel.times_shown")
    stats_store.save()

    date_str = day.strftime("%d.%m.%Y")
    times = [s.strftime("%H:%M") for s in slots]
    rows = [[InlineKeyboardButton(t, callback_data=f"slot:cart_time:{ds}:{t}")
             for t in times[i:i + 3]]
            for i in range(0, len(times), 3)]
    rows.append([InlineKeyboardButton("🛍️ К корзине", callback_data=f"slot:cart_view:{mid}")])
    rows.append([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")])

    text = (f"👩 {mname}\n🛍️ {label}\n📅 {date_str}\n\n"
            "Выберите удобное время:")
    await safe_edit(q, context, hp(f"📅 Хочу записаться → {mname} → {label}", text), kb(*rows))


async def slot_cart_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split(":")
    if len(parts) < 5:
        return
    ds, t = parts[2], parts[3] + ":" + parts[4]
    try:
        day = date.fromisoformat(ds)
    except ValueError:
        return

    mid = context.user_data.get("slot_master_id")
    mname = context.user_data.get("slot_master_name", "")
    cart = _cart_get(context).get(mid) or {}
    services = cart.get("services", [])

    if not services or not mid:
        await safe_edit(q, context, "⚠️ Корзина пуста.",
                        kb([InlineKeyboardButton("🏠 В начало", callback_data="main:menu")]))
        return

    stats_store.bump("funnel.time_clicked")
    stats_store.save()

    date_str = day.strftime("%d.%m.%Y")

    # Сообщение админу
    lines = [f"Запишите меня на услуги у мастера {mname} на {date_str} в {t}:"]
    total_time = 0
    for i, s in enumerate(services, 1):
        line = f"{i}. {s['name']}"
        if s.get("time"):
            line += f" ({_format_duration(s['time'])})"
            total_time += s["time"]
        lines.append(line)
    if total_time:
        lines.append(f"Общая длительность: {_format_duration(total_time)}.")
    admin_url = chat_url("\n".join(lines))

    # Сообщение клиенту
    text = (f"✅ Вы выбрали:\n\n"
            f"👩 Мастер: {mname}\n"
            f"📅 Дата: {date_str}\n"
            f"⏰ Время: {t}\n\n"
            f"🛍️ Услуги:\n")
    total_time = 0
    for i, s in enumerate(services, 1):
        text += f"{i}. {s['name']}"
        if s.get("time"):
            text += f" — {_format_duration(s['time'])}"
            total_time += s["time"]
        text += "\n"
    if total_time:
        text += f"\n⏱ Общая длительность: {_format_duration(total_time)}\n"

    text += ("\n💰 Стоимость: уточните у администратора при подтверждении.\n\n"
             "Нажмите кнопку ниже — откроется чат с администратором, "
             "сообщение с заявкой на все услуги уже будет готово. "
             "Останется только отправить его.")

    keyboard = [
        [InlineKeyboardButton("📩 Отправить заявку администратору", url=admin_url)],
        [InlineKeyboardButton("◀️ К временам", callback_data=f"slot:cart_date:{ds}")],
        [InlineKeyboardButton("🏠 В начало", callback_data="main:menu")],
    ]
    await safe_edit(q, context,
                    hp(f"📅 Хочу записаться → {mname} → {t}", text),
                    kb(*keyboard))


# ==============================================
# ДОПОЛНИТЕЛЬНЫЕ ОБРАБОТЧИКИ
# ==============================================

async def slot_direct_find(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """«Сразу найти время» из промежуточного экрана — обычная ветка."""
    await _render_dates_from_state(update.callback_query, context)


async def slot_4h_back_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _render_4h_list(update, context)


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
        # ---------- ТОЧНЫЕ ----------
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
        if data == "slot:cart_view":
            await slot_cart_view(update, context)
            return
        if data == "slot:cart_add":
            await slot_cart_add_from_state(update, context)
            return
        if data == "slot:cart_find":
            await slot_cart_find(update, context)
            return
        if data == "slot:cart_clear_all":
            await slot_cart_clear_all(update, context)
            return
        if data == "slot:cart_clear_all_yes":
            await slot_cart_clear_all_yes(update, context)
            return
        if data == "slot:4h_back:list":
            await slot_4h_back_list(update, context)
            return
        if data == "slot:direct_find":
            await slot_direct_find(update, context)
            return

        # ---------- 4HANDS ----------
        if data.startswith("slot:4h_pick:"):
            await slot_4h_pick(update, context)
            return
        if data.startswith("slot:4h_filter:"):
            await slot_4h_filter(update, context)
            return
        if data.startswith("slot:4h_start:"):
            await slot_4h_start(update, context)
            return

        # ---------- MSRV ----------
        if data.startswith("slot:msrv_go:"):
            await slot_msrv_choose_master(update, context)
            return
        if data.startswith("slot:msrv:"):
            await slot_show_masters_for_service(update, context)
            return

        # ---------- КОРЗИНА ----------
        if data.startswith("slot:cart_view:"):
            await slot_cart_view_master(update, context)
            return
        if data.startswith("slot:cart_add_to:"):
            await slot_cart_add_to(update, context)
            return
        if data.startswith("slot:cart_add_more:"):
            await slot_cart_add_more(update, context)
            return
        if data.startswith("slot:cart_remove_last:"):
            await slot_cart_remove_last(update, context)
            return
        if data.startswith("slot:cart_remove:"):
            await slot_cart_remove(update, context)
            return
        if data.startswith("slot:cart_clear_yes:"):
            await slot_cart_clear_yes(update, context)
            return
        if data.startswith("slot:cart_clear:"):
            await slot_cart_clear(update, context)
            return
        if data.startswith("slot:cart_find:"):
            await slot_cart_find(update, context)
            return
        if data.startswith("slot:cart_date:"):
            await slot_cart_date(update, context)
            return
        if data.startswith("slot:cart_time:"):
            await slot_cart_time(update, context)
            return
        if data.startswith("slot:cart_add:"):
            await slot_cart_add(update, context)
            return

        # ---------- ОСНОВНАЯ НАВИГАЦИЯ ----------
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



