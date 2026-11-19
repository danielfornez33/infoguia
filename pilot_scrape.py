#!/usr/bin/env python3
import json
import random
import time

import httpx
from app.adapters import get_adapter_for_url
from app.anomaly import analyze_response
from app.parsers import digits
from app.robots import can_fetch

BASE = "https://infoguia.com"
UA = "InfoGuiaPilot/0.1 (+contacto@example.com)"
LISTING = BASE + "/ct.asp"
PARAMS = {"key": "repuestos-caracas", "cat": "738", "ciud": "41"}
PAGES = 5
TARGET = 100
PROFILE_LIMIT = 20
MIN_DELAY = 5.0
MAX_DELAY = 8.0
OUT = "pilot_results.json"

session = httpx.Client(
    headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "es-VE,es;q=0.9",
    },
    timeout=30,
    follow_redirects=True,
)


def fetch(url: str, retries: int = 2):
    if not can_fetch(url):
        return None, {"url": url, "status": "robots-disallow", "seconds": 0.0}
    for attempt in range(retries + 1):
        time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
        started = time.time()
        try:
            resp = session.get(url)
        except httpx.RequestError as exc:
            if attempt < retries:
                time.sleep(30 * (attempt + 1))
                continue
            return None, {"url": url, "status": "error", "error": str(exc), "seconds": time.time() - started}
        elapsed = round(time.time() - started, 3)
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
            wait = resp.headers.get("Retry-After")
            time.sleep(float(wait) if wait and wait.isdigit() else 60 * (attempt + 1))
            continue
        if resp.status_code != 200:
            return None, {"url": url, "status": resp.status_code, "seconds": elapsed}
        anomaly = analyze_response(resp.text, "listing")
        if anomaly.captcha_detected:
            return None, {"url": url, "status": "captcha", "seconds": elapsed}
        return resp, {"url": url, "status": resp.status_code, "seconds": elapsed}
    return None, {"url": url, "status": "exhausted", "seconds": 0.0}


def mask(value: str) -> str:
    d = digits(value)
    return (d[:4] + "*" * max(0, len(d) - 6) + d[-2:]) if len(d) >= 6 else "***"


def main():
    adapter = get_adapter_for_url(LISTING)

    companies: dict[str, dict] = {}
    requests_log: list[dict] = []
    for page in range(1, PAGES + 1):
        params = dict(PARAMS)
        if page > 1:
            params["p"] = str(page)
        listing_url = LISTING + "?" + "&".join(f"{k}={v}" for k, v in params.items())
        resp, meta = fetch(listing_url)
        requests_log.append(meta)
        if resp is None:
            print(f"listing p{page}: {meta}")
            continue
        data = adapter.parse_listing(resp.text, listing_url)
        rows = data["companies"]
        print(f"listing p{page}: {len(rows)} fichas, HTTP {resp.status_code}, {meta['seconds']}s")
        for row in rows:
            key = row["clte"] or row["profile_url"]
            if key in companies:
                companies[key]["appearances"] += 1
                continue
            row["appearances"] = 1
            companies[key] = row
            if len(companies) >= TARGET:
                break
        if len(companies) >= TARGET:
            break

    selected = list(companies.values())[:TARGET]
    profiles: list[dict] = []
    for row in selected[:PROFILE_LIMIT]:
        resp, meta = fetch(row["profile_url"])
        requests_log.append(meta)
        if resp is None or resp.status_code != 200:
            print(f"profile {row['clte']}: {meta}")
            continue
        profiles.append(adapter.parse_profile(resp.text, row["profile_url"]))

    total = len(selected)
    with_whatsapp = sum(1 for r in selected if r["whatsapp"])
    with_phone = sum(1 for r in selected if r["phones"])
    with_address = sum(1 for r in selected if r["address"])
    with_schedule = sum(1 for r in selected if r["schedule"])
    with_rating = sum(1 for r in selected if r["rating_pct"])
    verified = sum(1 for r in selected if r["verified"])
    with_desc = sum(1 for r in selected if r["description"])
    with_store = sum(1 for r in selected if r["store_url"])
    whatsapp_counts = [len(r["whatsapp"]) for r in selected]
    profile_whatsapp = sum(1 for p in profiles if any(b["whatsapp"] for b in p["branches"]))
    profile_email = sum(1 for p in profiles if any(b["email"] for b in p["branches"]))
    branch_counts = [len(p["branches"]) for p in profiles]
    socials = sum(1 for p in profiles if p["socials"])
    products = [len(p["products"]) for p in profiles]

    summary = {
        "empresas_listado": total,
        "perfiles_consultados": len(profiles),
        "peticiones": len(requests_log),
        "http_200": sum(1 for r in requests_log if r["status"] == 200),
        "http_otros": [r for r in requests_log if r["status"] != 200],
        "segundos_peticion_promedio": round(
            sum(r["seconds"] for r in requests_log if isinstance(r["seconds"], (int, float)))
            / max(1, len(requests_log)), 2),
        "cobertura_listado": {
            "con_whatsapp": with_whatsapp,
            "pct_whatsapp": round(100 * with_whatsapp / max(1, total), 1),
            "con_telefono": with_phone,
            "pct_telefono": round(100 * with_phone / max(1, total), 1),
            "con_direccion": with_address,
            "con_horario": with_schedule,
            "con_rating": with_rating,
            "verificadas": verified,
            "con_descripcion": with_desc,
            "con_tienda": with_store,
            "whatsapp_promedio_por_empresa": round(
                sum(whatsapp_counts) / max(1, len(whatsapp_counts)), 2),
        },
        "cobertura_perfil": {
            "con_whatsapp": profile_whatsapp,
            "pct_whatsapp": round(100 * profile_whatsapp / max(1, len(profiles)), 1),
            "con_email": profile_email,
            "pct_email": round(100 * profile_email / max(1, len(profiles)), 1),
            "con_redes": socials,
            "sedes_promedio": round(sum(branch_counts) / max(1, len(branch_counts)), 2),
            "productos_promedio": round(sum(products) / max(1, len(products)), 2),
        },
        "muestra_redactada": [
            {
                "name": r["name"],
                "address": r["address"],
                "phones": [mask(p) for p in r["phones"]],
                "whatsapp": [mask(w) for w in r["whatsapp"]],
                "rating_pct": r["rating_pct"],
                "verified": r["verified"],
            }
            for r in selected[:5]
        ],
    }

    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump({"summary": summary, "companies": selected, "profiles": profiles,
                   "requests": requests_log}, handle, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
