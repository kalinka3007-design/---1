# stats_store.py
"""Единое хранилище статистики для bot.py и slot_finder.py.

Импортируется обоими модулями, чтобы избежать циклических зависимостей.
Сохраняется в stats.json (путь настраивается через STATS_FILE).
"""
from __future__ import annotations

import datetime
import json
import os

MSK = datetime.timezone(datetime.timedelta(hours=3))
STATS_FILE = os.getenv("STATS_FILE", "stats.json")

stats = {
    "starts": 0,
    "clicks": 0,
    "funnel": {
        "main_menu": 0,             # /start, main:menu
        "booking_choice": 0,        # main:booking
        "services_branch": 0,       # book:start_services
        "masters_branch": 0,        # slot:start
        "master": 0,                # slot:master:* (выбрали конкретного мастера)
        "category": 0,              # book:<code> или slot:cat:<code>
        "service": 0,               # srv*/* или slot:srv*
        "masters_for_service": 0,   # slot:msrv:* (старая ветка)
        "dates_shown": 0,           # _render_dates отработал
        "times_shown": 0,           # slot:date:* (показали времена)
        "time_clicked": 0,          # slot:time:* (выбрали конкретное время)
        "no_slots_14days": 0,       # «окон нет за 14 дней»
        # --- 4hands ---
        "4hands_used": 0,           # открыли ветку «4 руки»
        "4hands_completed": 0,      # дошли до подтверждения
        # --- Корзина ---
        "cart_used": 0,             # открыли экран корзины
        "cart_added": 0,            # добавили услугу
        "cart_removed": 0,          # убрали услугу
        "cart_multi_search": 0,     # искали время для 2+ услуг (мультизапрос)
    },
    "categories": {},
    "admin_requests_booking": 0,    # заявки на запись (абонементы)
    "admin_requests_other": 0,      # остальные обращения к админу
    "subscriptions": 0,
    "started_at": datetime.datetime.now(MSK),
}


def bump(path: str, by: int = 1) -> None:
    """bump('starts'), bump('funnel.master'), bump('admin_requests_booking')."""
    parts = path.split(".")
    obj = stats
    for p in parts[:-1]:
        if p not in obj or not isinstance(obj[p], dict):
            obj[p] = {}
        obj = obj[p]
    obj[parts[-1]] = obj.get(parts[-1], 0) + by


def bump_category(code: str, by: int = 1) -> None:
    stats["categories"][code] = stats["categories"].get(code, 0) + by


def save() -> None:
    try:
        payload = dict(stats)
        payload["started_at"] = stats["started_at"].isoformat()
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ Не удалось сохранить статистику: {e}")


def load() -> None:
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        for k in ("starts", "clicks", "subscriptions",
                   "admin_requests_booking", "admin_requests_other"):
            v = saved.get(k)
            if isinstance(v, int) and v >= 0:
                stats[k] = v
        if isinstance(saved.get("funnel"), dict):
            for k in stats["funnel"]:
                v = saved["funnel"].get(k)
                if isinstance(v, int) and v >= 0:
                    stats["funnel"][k] = v
        if isinstance(saved.get("categories"), dict):
            stats["categories"] = {
                str(k): int(v)
                for k, v in saved["categories"].items()
                if isinstance(v, int) and v >= 0
            }
        if saved.get("started_at"):
            stats["started_at"] = datetime.datetime.fromisoformat(saved["started_at"])
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"⚠️ Не удалось загрузить статистику: {e}")


def reset() -> None:
    stats["starts"] = 0
    stats["clicks"] = 0
    for k in stats["funnel"]:
        stats["funnel"][k] = 0
    stats["categories"] = {}
    stats["admin_requests_booking"] = 0
    stats["admin_requests_other"] = 0
    stats["subscriptions"] = 0
    stats["started_at"] = datetime.datetime.now(MSK)
    save()


# Автозагрузка при импорте
load()
