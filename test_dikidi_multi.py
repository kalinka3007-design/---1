import json
import re
import urllib.request
from datetime import date, timedelta
from urllib.parse import urlencode

BASE_URL = "https://beauty.dikidi.net"
COMPANY_ID = "1330084"
TIMEOUT = 30.0


def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "MintGlow-Test/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_masters() -> dict:
    d = get_json(f"{BASE_URL}/ru/ajax/newrecord/to_master_get_masters/?company_id={COMPANY_ID}")
    return {
        str(k): str(v.get("username") or v.get("name") or k)
        for k, v in (d.get("masters") or {}).items() if isinstance(v, dict)
    }


def get_categories(master_id: str) -> dict:
    q = urlencode({"lang": "ru", "company": COMPANY_ID, "master": master_id, "share": ""})
    d = get_json(f"{BASE_URL}/mobile/ajax/newrecord/company_services/?{q}")
    return d.get("data", {}).get("list", {})


def get_dates(service_ids, master_id, date_from, date_to):
    parts = [f"services_id[]={sid}" for sid in service_ids]
    parts += [f"company_id={COMPANY_ID}", f"master_id={master_id}",
              f"date_from={date_from}", f"date_to={date_to}"]
    return get_json(f"{BASE_URL}/en/ajax/newrecord/get_dates_true/?" + "&".join(parts))


def get_times(service_ids, master_id, target_date):
    parts = [f"services_id[]={sid}" for sid in service_ids]
    parts += [f"company_id={COMPANY_ID}", f"master_id={master_id}",
              f"date={target_date}", "is_show_all_times=0"]
    return get_json(f"{BASE_URL}/ru/ajax/newrecord/get_masters/?" + "&".join(parts))


def parse_dates(d):
    raw = d.get("dates_true") or []
    if not isinstance(raw, list):
        return []
    return sorted({m.group(0) for x in raw if (m := re.search(r"\d{4}-\d{2}-\d{2}", str(x)))})


def parse_times(d, master_id):
    times = (d.get("times") or {}).get(str(master_id)) or []
    return [str(x) for x in times] if isinstance(times, list) else []


def choose_pair():
    masters = get_masters()
    print(f"Мастеров: {len(masters)}")
    for mid, name in masters.items():
        cats = get_categories(mid)
        for cid, cat in cats.items():
            if not isinstance(cat, dict):
                continue
            services = [s for s in cat.get("services", []) if isinstance(s, dict) and s.get("id")]
            if len(services) >= 2:
                sid_a, sid_b = str(services[0]["id"]), str(services[1]["id"])
                print(f"\n✅ Мастер: {name} (mid={mid})")
                print(f"   Категория: {cat.get('name') or cat.get('title')}")
                print(f"   Услуга A: {sid_a} — {services[0]['name']}")
                print(f"   Услуга B: {sid_b} — {services[1]['name']}")
                print(f"   Ключи в услуге A: {list(services[0].keys())}")
                return mid, name, sid_a, sid_b, services[0]
    return None, None, None, None, None


def main():
    print("=" * 70)
    print("ТЕСТ DiKidi: мультизапрос по нескольким услугам")
    print("=" * 70)

    mid, mname, sid_a, sid_b, service_a = choose_pair()
    if not mid:
        print("❌ Не нашли мастера с 2+ услугами.")
        return

    print("\n" + "=" * 70)
    print("ТЕСТ 0: длительность в объекте услуги")
    print("=" * 70)
    duration_keys = [k for k in service_a.keys()
                     if "dur" in k.lower() or "time" in k.lower() or "length" in k.lower()]
    if duration_keys:
        print(f"✅ Ключи: {duration_keys}")
        for k in duration_keys:
            print(f"   {k} = {service_a[k]}")
    else:
        print("⚠️ Ключей с длительностью нет.")
        print(f"   Объект: {json.dumps(service_a, ensure_ascii=False)[:400]}")

    print("\n" + "=" * 70)
    print("ТЕСТ 1: get_dates_true — один vs два")
    print("=" * 70)
    today = date.today()
    df, dt = today.isoformat(), (today + timedelta(days=14)).isoformat()
    print(f"Диапазон: {df} — {dt}\n")

    print(f"[A] только {sid_a}:")
    try:
        dates_a = parse_dates(get_dates([sid_a], mid, df, dt))
        print(f"    dates: {dates_a or '(пусто)'}")
    except Exception as e:
        print(f"    ❌ {e}"); dates_a = []

    print(f"\n[B] только {sid_b}:")
    try:
        dates_b = parse_dates(get_dates([sid_b], mid, df, dt))
        print(f"    dates: {dates_b or '(пусто)'}")
    except Exception as e:
        print(f"    ❌ {e}"); dates_b = []

    print(f"\n[A+B]:")
    try:
        d_ab = get_dates([sid_a, sid_b], mid, df, dt)
        print(f"    RAW: {json.dumps(d_ab, ensure_ascii=False)[:600]}")
        dates_ab = parse_dates(d_ab)
        print(f"    dates: {dates_ab or '(пусто)'}")
    except Exception as e:
        print(f"    ❌ {e}"); dates_ab = []

    print("\n" + "-" * 70)
    print(f"ВЫВОД: A={len(dates_a)}, B={len(dates_b)}, A+B={len(dates_ab)}")
    if not dates_ab:
        print("⚠️ A+B пуст — API не поддерживает мультизапрос")
    elif dates_ab == sorted(set(dates_a) & set(dates_b)):
        print("✅ A+B = пересечение — мультизапрос работает")
    else:
        print("❓ Смотри raw")

    test_date = None
    for d in dates_ab:
        if d in dates_a and d in dates_b:
            test_date = d; break
    if not test_date and dates_ab:
        test_date = dates_ab[0]

    if test_date:
        print("\n" + "=" * 70)
        print(f"ТЕСТ 2: get_times для {test_date}")
        print("=" * 70)

        print(f"\n[A] {sid_a}:")
        try:
            times_a = parse_times(get_times([sid_a], mid, test_date), mid)
            print(f"    times ({len(times_a)}): {times_a[:25]}")
        except Exception as e:
            print(f"    ❌ {e}"); times_a = []

        print(f"\n[B] {sid_b}:")
        try:
            times_b = parse_times(get_times([sid_b], mid, test_date), mid)
            print(f"    times ({len(times_b)}): {times_b[:25]}")
        except Exception as e:
            print(f"    ❌ {e}"); times_b = []

        print(f"\n[A+B]:")
        try:
            t_ab = get_times([sid_a, sid_b], mid, test_date)
            print(f"    RAW: {json.dumps(t_ab, ensure_ascii=False)[:600]}")
            times_ab = parse_times(t_ab, mid)
            print(f"    times ({len(times_ab)}): {times_ab[:25]}")
        except Exception as e:
            print(f"    ❌ {e}"); times_ab = []

        print("\n" + "-" * 70)
        print(f"ВЫВОД: A={len(times_a)}, B={len(times_b)}, A+B={len(times_ab)}")
        if not times_ab:
            print("⚠️ A+B пуст — мультизапрос не работает")
        elif times_ab == sorted(set(times_a) & set(times_b)):
            print("⚠️ A+B = пересечение — длительности не суммируются")
        elif len(times_ab) < len(times_a) and len(times_ab) < len(times_b):
            print("✅ A+B меньше A и B — API учитывает суммарную длительность!")
        else:
            print("❓ Смотри raw")

    print("\n" + "=" * 70)
    print("ГОТОВО. Пришли этот вывод.")
    print("=" * 70)


if __name__ == "__main__":
    main()
