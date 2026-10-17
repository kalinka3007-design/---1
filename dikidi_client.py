# dikidi_client.py
from __future__ import annotations

import re
import time
from datetime import date, datetime
from typing import Any, Union
from urllib.parse import urlencode

import httpx

BASE_URL = "https://beauty.dikidi.net"

# ==============================================
# КЭШ
# ==============================================
# masters      — 30 минут
# cats:<mid>   — 30 минут
# slots:<sids>:<mid>:<iso>  — 5 минут
MASTERS_TTL = 1800
CATS_TTL = 1800
SLOTS_TTL = 300

_CACHE: dict[str, tuple[Any, float]] = {}

ServiceIds = Union[str, list[str]]


def _cache_get(key: str, ttl: float):
    item = _CACHE.get(key)
    if not item:
        return None
    value, ts = item
    if time.monotonic() - ts > ttl:
        _CACHE.pop(key, None)
        return None
    return value


def _cache_put(key: str, value: Any) -> None:
    _CACHE[key] = (value, time.monotonic())


def clear_cache() -> None:
    _CACHE.clear()


def _normalize_sids(service_ids: ServiceIds) -> list[str]:
    """Приводит одиночный ID или список к списку строк."""
    if isinstance(service_ids, str):
        return [service_ids]
    return [str(x) for x in service_ids]


# ==============================================
# КЛИЕНТ
# ==============================================

class DikidiError(RuntimeError):
    pass


class DikidiClient:
    def __init__(self, company_id: str, timeout: float = 15.0):
        if not company_id or not company_id.isdigit():
            raise ValueError("DIKIDI_COMPANY_ID must be numeric")
        self.company_id = company_id
        self.timeout = timeout

    async def _get_json(self, url: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as c:
                r = await c.get(url, headers={"User-Agent": "MintGlow-Telegram/1.0"})
                r.raise_for_status()
                data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise DikidiError(f"Ошибка запроса DiKidi: {e}") from e
        if not isinstance(data, dict):
            raise DikidiError("DiKidi вернул неожиданный формат данных")
        return data

    async def get_masters(self) -> dict[str, str]:
        cached = _cache_get("masters", MASTERS_TTL)
        if cached is not None:
            return cached
        d = await self._get_json(
            f"{BASE_URL}/ru/ajax/newrecord/to_master_get_masters/?company_id={self.company_id}"
        )
        raw = d.get("masters")
        if not isinstance(raw, dict):
            raise DikidiError("В ответе DiKidi нет списка мастеров")
        result = {
            str(k): str(v.get("username") or v.get("name") or f"Мастер {k}")
            for k, v in raw.items()
            if isinstance(v, dict)
        }
        _cache_put("masters", result)
        return result

    async def get_service_categories(self, master_id: str) -> dict[str, dict[str, Any]]:
        key = f"cats:{master_id}"
        cached = _cache_get(key, CATS_TTL)
        if cached is not None:
            return cached

        q = urlencode({"lang": "ru", "company": self.company_id, "master": master_id, "share": ""})
        d = await self._get_json(f"{BASE_URL}/mobile/ajax/newrecord/company_services/?{q}")
        raw = d.get("data", {}).get("list", {})
        if not isinstance(raw, dict):
            raise DikidiError("В ответе DiKidi нет списка услуг")
        out: dict[str, dict[str, Any]] = {}
        for i, (rid, cat) in enumerate(raw.items(), 1):
            if not isinstance(cat, dict):
                continue
            services: dict[str, dict[str, Any]] = {}
            raw_services = cat.get("services", [])
            if isinstance(raw_services, list):
                for s in raw_services:
                    if isinstance(s, dict) and s.get("id") is not None and s.get("name"):
                        sid = str(s["id"])
                        services[sid] = {
                            "id": sid,
                            "name": str(s["name"]),
                            "time": s.get("time"),          # длительность в минутах (может быть None)
                            "price": s.get("price") or s.get("cost"),
                        }
            if services:
                cid = str(cat.get("id", rid))
                if cid in out:
                    cid = f"{cid}_{i}"
                out[cid] = {
                    "name": str(cat.get("name") or cat.get("title") or f"Категория {i}"),
                    "services": services,
                }
        if not out:
            raise DikidiError("Для специалиста не найдены услуги")
        _cache_put(key, out)
        return out

    async def get_services(self, master_id: str) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for cat in (await self.get_service_categories(master_id)).values():
            out.update(cat["services"])
        return out

    async def get_dates(
        self,
        service_ids: ServiceIds,
        master_id: str,
        date_from: date,
        date_to: date,
    ) -> list[str]:
        sids = _normalize_sids(service_ids)
        params: list[tuple[str, str]] = [
            ("company_id", self.company_id),
            ("master_id", master_id),
            ("date_from", date_from.isoformat()),
            ("date_to", date_to.isoformat()),
        ]
        for sid in sids:
            params.append(("services_id[]", sid))
        q = urlencode(params)
        d = await self._get_json(f"{BASE_URL}/en/ajax/newrecord/get_dates_true/?{q}")
        raw = d.get("dates_true")
        if not isinstance(raw, list):
            if "dates_true" not in d:
                raise DikidiError("В ответе DiKidi нет dates_true")
            return []
        return [m.group(0) for x in raw if (m := re.search(r"\d{4}-\d{2}-\d{2}", str(x)))]

    async def get_times(
        self,
        target_date: str,
        service_ids: ServiceIds,
        master_id: str,
    ) -> list[str]:
        sids = _normalize_sids(service_ids)
        params: list[tuple[str, str]] = [
            ("company_id", self.company_id),
            ("date", target_date),
            ("master_id", master_id),
            ("is_show_all_times", "0"),
        ]
        for sid in sids:
            params.append(("services_id[]", sid))
        q = urlencode(params)
        d = await self._get_json(f"{BASE_URL}/ru/ajax/newrecord/get_masters/?{q}")
        raw = d.get("times", {}).get(str(master_id), [])
        return [str(x) for x in raw] if isinstance(raw, list) else []

    async def available_slots(
        self,
        service_ids: ServiceIds,
        master_id: str,
        target_date: date,
    ) -> list[datetime]:
        sids = _normalize_sids(service_ids)
        # Ключ кэша: порядок sid не важен
        key = f"slots:{','.join(sorted(sids))}:{master_id}:{target_date.isoformat()}"
        cached = _cache_get(key, SLOTS_TTL)
        if cached is not None:
            return cached

        dates = await self.get_dates(sids, master_id, target_date, target_date)
        slots: list[datetime] = []
        for ds in dates:
            for raw in await self.get_times(ds, sids, master_id):
                m = re.search(r"(\d{4}-\d{2}-\d{2})[ T].*?(\d{2}):(\d{2})", raw)
                if not m:
                    m = re.search(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}):(\d{2})", raw)
                if m:
                    try:
                        dt = datetime.strptime(
                            f"{m.group(1)} {m.group(2)}:{m.group(3)}",
                            "%Y-%m-%d %H:%M",
                        )
                        if dt.date() == target_date:
                            slots.append(dt)
                    except ValueError:
                        pass
        result = sorted(set(slots))
        _cache_put(key, result)
        return result


def service_id_from_url(url: str) -> str | None:
    """https://dkd.su/1330084/s/21047026 → '21047026'"""
    m = re.search(r"/s/(\d+)", url or "")
    return m.group(1) if m else None


def booking_url(company_id: str) -> str:
    return f"{BASE_URL}/ru/record/{company_id}"
