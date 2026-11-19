import base64
import csv
import io
import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db, queue
from .config import settings
from .events import info
from .redis_client import ar, r
from .scheduler import scheduler_is_alive
from .settings_store import all_settings, load_settings, set_settings

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    queue.ensure_group()
    load_settings()
    yield
    try:
        await ar.aclose()
    except Exception:
        pass


app = FastAPI(title="InfoGuia BI", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def valid_basic(header: str | None) -> bool:
    if not header or not header.lower().startswith("basic "):
        return False
    try:
        decoded = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
    except Exception:
        return False
    username, _, password = decoded.partition(":")
    return secrets.compare_digest(username, settings.panel_user) and secrets.compare_digest(
        password, settings.panel_password
    )


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # Excluir rutas públicas de autenticación
    if (path == "/health" or 
        path.startswith("/static/") or 
        path.startswith("/api/control/")):
        return await call_next(request)
    if settings.panel_password and not valid_basic(request.headers.get("authorization")):
        return JSONResponse(
            {"detail": "no autorizado"},
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="infoguia"'},
        )
    return await call_next(request)


def scalar(sql: str, params=None, default=0):
    row = db.query_one(sql, params)
    if not row:
        return default
    value = next(iter(row.values()))
    return default if value is None else value


def current_mode() -> str:
    return r.get("control:mode") or "running"


def collect_stats() -> dict:
    companies = int(scalar("SELECT count(*) FROM company"))
    branches = int(scalar("SELECT count(*) FROM branch"))
    contacts = int(scalar("SELECT count(*) FROM contact"))
    phone = int(scalar("SELECT count(DISTINCT clte) FROM contact WHERE type = 'phone'"))
    whatsapp = int(scalar("SELECT count(DISTINCT clte) FROM contact WHERE type = 'whatsapp'"))
    email = int(scalar("SELECT count(DISTINCT clte) FROM contact WHERE type = 'email'"))
    verified = int(scalar("SELECT count(*) FROM company WHERE verified"))
    changes = int(scalar("SELECT count(*) FROM change_log"))
    products = int(scalar("SELECT count(*) FROM product"))
    seeds = int(scalar("SELECT count(*) FROM seed WHERE enabled"))

    workers_rows = db.query(
        "SELECT * FROM worker WHERE last_seen > now() - interval '2 minutes' ORDER BY id"
    )
    workers = [
        {
            "id": row["id"],
            "hostname": row["hostname"],
            "pid": row["pid"],
            "processed": int(row["processed"] or 0),
            "errors": int(row["errors"] or 0),
            "last_seen": row["last_seen"].isoformat() if row["last_seen"] else "",
        }
        for row in workers_rows
    ]

    categories = db.query(
        """
        SELECT COALESCE(c.name, cc.cat_id::text) AS name, count(*) AS total
        FROM company_category cc
        LEFT JOIN category c ON c.cat_id = cc.cat_id
        GROUP BY 1 ORDER BY total DESC LIMIT 10
        """
    )
    cities = db.query(
        """
        SELECT city, count(*) AS total FROM branch
        WHERE city IS NOT NULL AND city <> ''
        GROUP BY city ORDER BY total DESC LIMIT 10
        """
    )
    activity = db.query(
        """
        SELECT to_char(date_trunc('day', changed_at), 'YYYY-MM-DD') AS day, count(*) AS total
        FROM change_log
        WHERE changed_at > now() - interval '7 days'
        GROUP BY 1 ORDER BY 1
        """
    )
    recent = db.query(
        """
        SELECT clte, name, verified, last_seen FROM company
        ORDER BY last_seen DESC LIMIT 10
        """
    )
    recent_rows = [
        {
            "clte": row["clte"],
            "name": row["name"],
            "verified": row["verified"],
            "last_seen": row["last_seen"].isoformat() if row["last_seen"] else "",
        }
        for row in recent
    ]

    coverages = {
        "labels": ["WhatsApp", "Email", "Teléfono"],
        "values": [whatsapp, email, phone],
    }

    chart = {
        "categories": {
            "labels": [row["name"] for row in categories],
            "values": [int(row["total"]) for row in categories],
        },
        "cities": {
            "labels": [row["city"] for row in cities],
            "values": [int(row["total"]) for row in cities],
        },
        "activity": {
            "labels": [row["day"] for row in activity],
            "values": [int(row["total"]) for row in activity],
        },
        "coverage": coverages,
    }

    return {
        "companies": companies,
        "branches": branches,
        "contacts": contacts,
        "phone": phone,
        "whatsapp": whatsapp,
        "email": email,
        "verified": verified,
        "changes": changes,
        "products": products,
        "seeds": seeds,
        "workers": workers,
        "workers_online": len(workers),
        "scheduler_alive": scheduler_is_alive(),
        "recent": recent_rows,
        "chart": chart,
        "queue": queue.queue_stats(),
        "mode": current_mode(),
        "panel_user": settings.panel_user,
    }


def render(name: str, request: Request, **context):
    return templates.TemplateResponse(request, name, context)


@app.get("/health")
def health():
    try:
        db.query_one("SELECT 1 AS ok")
        r.ping()
        return {"status": "ok"}
    except Exception as exc:
        return JSONResponse({"status": "error", "detail": str(exc)}, status_code=503)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    stats = collect_stats()
    return render("dashboard.html", request, stats=stats, chart=stats["chart"])


@app.get("/queue", response_class=HTMLResponse)
def queue_page(request: Request):
    queue_stats = queue.queue_stats()
    workers_rows = db.query(
        "SELECT * FROM worker WHERE last_seen > now() - interval '2 minutes' ORDER BY id"
    )
    recent_jobs = db.query(
        "SELECT * FROM crawl_url ORDER BY updated_at DESC LIMIT 50"
    )
    
    return render(
        "queue.html",
        request,
        queue_stats=queue_stats,
        workers=workers_rows,
        recent_jobs=recent_jobs,
        stats=collect_stats(),
        mode=current_mode(),
    )


@app.get("/companies", response_class=HTMLResponse)
def companies_page(
    request: Request,
    q: str = "",
    city: str = "",
    category: str = "",
    verified_only: bool = False,
    has_whatsapp: bool = False,
    page: int = 1,
):
    page = max(int(page or 1), 1)
    limit = 50
    offset = (page - 1) * limit

    conditions = []
    params = []

    if q.strip():
        conditions.append("(c.name ILIKE %s OR c.clte::text = %s)")
        params.extend([f"%{q.strip()}%", q.strip()])

    if city.strip():
        conditions.append("EXISTS (SELECT 1 FROM branch b WHERE b.clte = c.clte AND b.city ILIKE %s)")
        params.append(f"%{city}%")

    if category.strip():
        conditions.append("EXISTS (SELECT 1 FROM company_category cc JOIN category cat ON cat.cat_id = cc.cat_id WHERE cc.clte = c.clte AND (cat.name ILIKE %s OR cc.cat_id::text = %s))")
        params.extend([f"%{category}%", category.strip()])

    if verified_only:
        conditions.append("c.verified = true")

    if has_whatsapp:
        conditions.append("EXISTS (SELECT 1 FROM contact ct WHERE ct.clte = c.clte AND ct.type = 'whatsapp')")

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    total = int(scalar(f"SELECT count(*) FROM company c {where}", params))

    rows = db.query(
        f"""
        SELECT
            c.clte,
            c.name,
            c.verified,
            c.rating_pct,
            c.description,
            c.last_seen,
            c.source_url,
            (SELECT count(*) FROM branch b WHERE b.clte = c.clte) AS branches_count,
            (SELECT array_agg(DISTINCT b.city) FROM branch b WHERE b.clte = c.clte AND b.city IS NOT NULL AND b.city != '') AS cities,
            (SELECT array_agg(DISTINCT ct.value_norm) FROM contact ct WHERE ct.clte = c.clte AND ct.type = 'phone') AS phones,
            (SELECT array_agg(DISTINCT ct.value_norm) FROM contact ct WHERE ct.clte = c.clte AND ct.type = 'whatsapp') AS whatsapp_numbers,
            (SELECT array_agg(DISTINCT ct.value_norm) FROM contact ct WHERE ct.clte = c.clte AND ct.type = 'email') AS emails,
            (SELECT array_agg(DISTINCT s.network) FROM social s WHERE s.clte = c.clte) AS social_networks,
            (SELECT array_agg(DISTINCT cat.name) FROM company_category cc JOIN category cat ON cat.cat_id = cc.cat_id WHERE cc.clte = c.clte AND cat.name IS NOT NULL) AS categories,
            (SELECT b.address FROM branch b WHERE b.clte = c.clte ORDER BY b.branch_key LIMIT 1) AS primary_address
        FROM company c
        {where}
        ORDER BY c.last_seen DESC
        LIMIT %s OFFSET %s
        """,
        [*params, limit, offset],
    )

    # Transform rows to match new template expectations
    companies = []
    for row in rows:
        companies.append({
            "clte": row["clte"],
            "name": row["name"],
            "verified": row["verified"],
            "rating_pct": row["rating_pct"],
            "address": row["primary_address"],
            "city": row["cities"][0] if row["cities"] else None,
            "phones": row["phones"] or [],
            "whatsapp": row["whatsapp_numbers"] or [],
            "emails": row["emails"] or [],
            "social_networks": row["social_networks"] or [],
            "categories": row["categories"] or [],
            "has_instagram": "instagram" in (row["social_networks"] or []),
            "has_facebook": "facebook" in (row["social_networks"] or []),
            "has_twitter": "twitter" in (row["social_networks"] or []) or "x.com" in (row["social_networks"] or []),
        })

    cities_list = db.query("SELECT DISTINCT city FROM branch WHERE city IS NOT NULL AND city != '' ORDER BY city")
    categories_list = db.query("SELECT cat_id, name FROM category WHERE name IS NOT NULL ORDER BY name")

    pages = max((total + limit - 1) // limit, 1)

    return render(
        "companies.html",
        request,
        companies=companies,
        q=q,
        selected_city=city,
        selected_category=category,
        verified_only=verified_only,
        has_whatsapp=has_whatsapp,
        current_page=page,
        total_pages=pages,
        total=total,
        cities=[c["city"] for c in cities_list],
        categories=[{"id": c["cat_id"], "name": c["name"]} for c in categories_list],
        stats=collect_stats(),
    )


@app.get("/companies/{clte}", response_class=HTMLResponse)
def company_detail(request: Request, clte: int):
    company = db.query_one("SELECT * FROM company WHERE clte = %s", (clte,))
    if not company:
        raise HTTPException(status_code=404, detail="empresa no encontrada")
    
    branches = db.query("SELECT * FROM branch WHERE clte = %s ORDER BY branch_key", (clte,))
    contacts = db.query("SELECT * FROM contact WHERE clte = %s ORDER BY type, value", (clte,))
    socials = db.query("SELECT * FROM social WHERE clte = %s ORDER BY network", (clte,))
    products = db.query("SELECT * FROM product WHERE clte = %s ORDER BY last_seen DESC LIMIT 200", (clte,))
    
    # Get first branch for address/city
    first_branch = branches[0] if branches else {}
    
    # Extract contact types
    phones = [c["value"] for c in contacts if c["type"] == "phone"]
    whatsapp = [c["value"] for c in contacts if c["type"] == "whatsapp"]
    emails = [c["value"] for c in contacts if c["type"] == "email"]
    
    # Enrich company data for template
    company_data = {
        **company,
        "address": first_branch.get("address"),
        "city": first_branch.get("city"),
        "phones": phones,
        "whatsapp": whatsapp,
        "emails": emails,
        "socials": socials,
        "products": products,
    }
    
    return render(
        "company_detail.html",
        request,
        company=company_data,
        stats=collect_stats(),
    )


@app.get("/queue", response_class=HTMLResponse)
def queue_page(request: Request):
    # Get queue statistics
    queue_stats = {
        "pending": scalar("SELECT count(*) FROM crawl_url WHERE status = 'queued'"),
        "queued": scalar("SELECT count(*) FROM crawl_url WHERE status = 'queued'"),
        "active": scalar("SELECT count(*) FROM crawl_url WHERE status = 'processing'"),
        "done": scalar("SELECT count(*) FROM crawl_url WHERE status = 'done' AND last_fetched_at > CURRENT_DATE"),
        "failed": scalar("SELECT count(*) FROM crawl_url WHERE status = 'failed'"),
    }
    
    # Get active workers
    workers = db.query(
        "SELECT * FROM worker WHERE last_seen > now() - interval '2 minutes' ORDER BY id"
    )
    
    # Get recent jobs
    recent_jobs = db.query(
        """
        SELECT url, kind, status, priority, attempts, updated_at
        FROM crawl_url
        ORDER BY updated_at DESC
        LIMIT 50
        """
    )
    
    return render(
        "queue.html",
        request,
        queue_stats=queue_stats,
        workers=workers,
        recent_jobs=recent_jobs,
        stats=collect_stats(),
        mode=current_mode(),
    )


@app.get("/logs", response_class=HTMLResponse)
def logs_page(request: Request):
    # Get recent logs from Redis
    recent_logs_raw = r.lrange("logs:recent", 0, 49)
    recent_logs = []
    for log_json in recent_logs_raw:
        try:
            log_data = json.loads(log_json)
            recent_logs.append(log_data)
        except (json.JSONDecodeError, TypeError):
            continue
    
    return render("logs.html", request, recent_logs=recent_logs, stats=collect_stats(), mode=current_mode())


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    return render("settings.html", request, s=all_settings(), stats=collect_stats(), mode=current_mode())


@app.post("/api/control/{action}")
def control(action: str):
    mapping = {
        "start": "running",
        "resume": "running",
        "pause": "paused",
        "stop": "stopped",
        "stopping": "stopping",
    }
    if action not in mapping:
        raise HTTPException(status_code=400, detail="acción inválida")
    r.set("control:mode", mapping[action])
    info("control actualizado", mode=mapping[action])
    return {"mode": mapping[action]}


@app.get("/api/stats")
def api_stats():
    return collect_stats()


@app.get("/api/queue/{state}")
def api_queue(state: str):
    if state == "pending":
        return queue.list_pending(200)
    if state == "active":
        return queue.list_active(100)
    if state == "failed":
        return queue.list_dead(100)
    raise HTTPException(status_code=400, detail="estado inválido")


@app.post("/api/queue/retry")
def api_queue_retry():
    requeued = queue.requeue_stale(min_idle_ms=0) + queue.retry_dead()
    info("cola reintentada", requeued=requeued)
    return {"requeued": requeued}


@app.post("/api/queue/purge")
def api_queue_purge():
    queue.purge()
    info("cola purgada")
    return {"ok": True}


@app.post("/api/seeds")
def api_add_seed(
    url: str = Form(...),
    kind: str = Form("listing"),
    interval_seconds: int = Form(86400),
):
    url = url.strip()
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="URL inválida")
    db.execute(
        """
        INSERT INTO seed (url, kind, interval_seconds, enabled, next_run_at)
        VALUES (%s, %s, %s, true, now())
        ON CONFLICT (url) DO UPDATE
        SET enabled = true, interval_seconds = EXCLUDED.interval_seconds
        """,
        (url, kind, interval_seconds),
    )
    info("seed agregada", url=url, kind=kind)
    return RedirectResponse("/queue", status_code=303)


@app.post("/api/seeds/{seed_id}/toggle")
def api_toggle_seed(seed_id: int):
    db.execute("UPDATE seed SET enabled = NOT enabled WHERE id = %s", (seed_id,))
    return RedirectResponse("/queue", status_code=303)


def flag(value: str) -> str:
    return "true" if str(value).strip().lower() in {"on", "true", "1", "yes"} else "false"


@app.post("/api/settings")
def api_settings(
    crawl_rps: float = Form(0.15),
    crawl_burst: int = Form(1),
    daily_cap: int = Form(8000),
    off_peak_only: str = Form("false"),
    off_peak_start: int = Form(0),
    off_peak_end: int = Form(7),
    discovery_enabled: str = Form("false"),
    products_enabled: str = Form("false"),
    max_pages_per_listing: int = Form(30),
):
    set_settings(
        {
            "crawl_rps": crawl_rps,
            "crawl_burst": crawl_burst,
            "daily_cap": daily_cap,
            "off_peak_only": flag(off_peak_only),
            "off_peak_start": off_peak_start,
            "off_peak_end": off_peak_end,
            "discovery_enabled": flag(discovery_enabled),
            "products_enabled": flag(products_enabled),
            "max_pages_per_listing": max_pages_per_listing,
        }
    )
    info("ajustes actualizados")
    return RedirectResponse("/settings", status_code=303)


@app.get("/api/logs/recent")
def api_logs_recent(limit: int = 200):
    items = r.lrange("logs:recent", 0, max(0, limit - 1))
    parsed = []
    for item in items:
        try:
            parsed.append(json.loads(item))
        except Exception:
            continue
    return parsed


@app.get("/api/logs/stream")
async def api_logs_stream(request: Request):
    async def generator():
        pubsub = ar.pubsub()
        await pubsub.subscribe("events")
        try:
            while True:
                if await request.is_disconnected():
                    break
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15)
                if message:
                    yield f"data: {message['data']}\n\n"
                else:
                    yield ": keepalive\n\n"
        finally:
            try:
                await pubsub.unsubscribe("events")
                await pubsub.aclose()
            except Exception:
                pass

    return StreamingResponse(generator(), media_type="text/event-stream")


@app.get("/api/partials/stats", response_class=HTMLResponse)
def partial_stats(request: Request):
    stats = collect_stats()
    return render("partials/stats.html", request, stats=stats, chart=stats["chart"])


@app.get("/api/export/companies.csv")
def export_companies_csv(q: str = "", city: str = "", category: str = "", verified_only: bool = False, has_whatsapp: bool = False):
    conditions = []
    params = []

    if q.strip():
        conditions.append("(c.name ILIKE %s OR c.clte::text = %s)")
        params.extend([f"%{q.strip()}%", q.strip()])

    if city.strip():
        conditions.append("EXISTS (SELECT 1 FROM branch b WHERE b.clte = c.clte AND b.city ILIKE %s)")
        params.append(f"%{city}%")

    if category.strip():
        conditions.append("EXISTS (SELECT 1 FROM company_category cc JOIN category cat ON cat.cat_id = cc.cat_id WHERE cc.clte = c.clte AND (cat.name ILIKE %s OR cc.cat_id::text = %s))")
        params.extend([f"%{category}%", category.strip()])

    if verified_only:
        conditions.append("c.verified = true")

    if has_whatsapp:
        conditions.append("EXISTS (SELECT 1 FROM contact ct WHERE ct.clte = c.clte AND ct.type = 'whatsapp')")

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    def generate():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([
            "clte", "name", "verified", "rating_pct", "address", "city",
            "phones", "whatsapp", "emails", "store_url", "profile_url",
            "first_seen", "last_seen",
        ])
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)

        rows = db.query(
            f"""
            SELECT c.clte, c.name, c.verified, c.rating_pct, c.store_url,
                   c.source_url, c.first_seen, c.last_seen,
                   (SELECT b.address FROM branch b WHERE b.clte = c.clte ORDER BY b.branch_key LIMIT 1) AS address,
                   (SELECT b.city FROM branch b WHERE b.clte = c.clte ORDER BY b.branch_key LIMIT 1) AS city,
                   (SELECT string_agg(DISTINCT b.phones, '; ') FROM branch b WHERE b.clte = c.clte AND b.phones IS NOT NULL AND b.phones <> '') AS phones,
                   (SELECT string_agg(DISTINCT ct.value, '; ') FROM contact ct WHERE ct.clte = c.clte AND ct.type = 'whatsapp') AS whatsapp,
                   (SELECT string_agg(DISTINCT ct.value, '; ') FROM contact ct WHERE ct.clte = c.clte AND ct.type = 'email') AS emails
            FROM company c
            {where}
            ORDER BY c.clte
            """,
            params,
        )
        for row in rows:
            w.writerow([
                row["clte"],
                row["name"],
                row["verified"],
                row["rating_pct"],
                row["address"] or "",
                row["city"] or "",
                row["phones"] or "",
                row["whatsapp"] or "",
                row["emails"] or "",
                row["store_url"] or "",
                row["source_url"] or "",
                row["first_seen"].isoformat() if row["first_seen"] else "",
                row["last_seen"].isoformat() if row["last_seen"] else "",
            ])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    headers = {"Content-Disposition": 'attachment; filename="companies.csv"'}
    return StreamingResponse(generate(), media_type="text/csv", headers=headers)


@app.get("/api/export/companies.json")
def export_companies_json(q: str = "", city: str = "", category: str = "", verified_only: bool = False, has_whatsapp: bool = False):
    conditions = []
    params = []

    if q.strip():
        conditions.append("(c.name ILIKE %s OR c.clte::text = %s)")
        params.extend([f"%{q.strip()}%", q.strip()])

    if city.strip():
        conditions.append("EXISTS (SELECT 1 FROM branch b WHERE b.clte = c.clte AND b.city ILIKE %s)")
        params.append(f"%{city}%")

    if category.strip():
        conditions.append("EXISTS (SELECT 1 FROM company_category cc JOIN category cat ON cat.cat_id = cc.cat_id WHERE cc.clte = c.clte AND (cat.name ILIKE %s OR cc.cat_id::text = %s))")
        params.extend([f"%{category}%", category.strip()])

    if verified_only:
        conditions.append("c.verified = true")

    if has_whatsapp:
        conditions.append("EXISTS (SELECT 1 FROM contact ct WHERE ct.clte = c.clte AND ct.type = 'whatsapp')")

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    companies = db.query(
        f"""
        SELECT c.clte, c.name, c.verified, c.rating_pct, c.description,
               c.store_url, c.source_url, c.first_seen, c.last_seen
        FROM company c
        {where}
        ORDER BY c.clte
        """,
        params,
    )

    clte_list = [c["clte"] for c in companies]
    if not clte_list:
        return {"companies": []}

    branches = db.query(
        "SELECT * FROM branch WHERE clte = ANY(%s) ORDER BY clte, branch_key",
        (clte_list,),
    )
    contacts = db.query(
        "SELECT * FROM contact WHERE clte = ANY(%s) ORDER BY clte, type, value",
        (clte_list,),
    )
    socials = db.query(
        "SELECT * FROM social WHERE clte = ANY(%s) ORDER BY clte, network",
        (clte_list,),
    )

    branches_map: dict[int, list] = {}
    for b in branches:
        branches_map.setdefault(b["clte"], []).append({
            "branch_key": b["branch_key"],
            "urbanization": b["urbanization"],
            "address": b["address"],
            "city": b["city"],
            "phones": b["phones"],
            "whatsapp": b["whatsapp"],
            "email": b["email"],
            "first_seen": b["first_seen"].isoformat() if b["first_seen"] else None,
            "last_seen": b["last_seen"].isoformat() if b["last_seen"] else None,
        })

    contacts_map: dict[int, list] = {}
    for ct in contacts:
        contacts_map.setdefault(ct["clte"], []).append({
            "branch_key": ct["branch_key"],
            "type": ct["type"],
            "value": ct["value"],
            "value_norm": ct["value_norm"],
            "first_seen": ct["first_seen"].isoformat() if ct["first_seen"] else None,
            "last_seen": ct["last_seen"].isoformat() if ct["last_seen"] else None,
        })

    socials_map: dict[int, list] = {}
    for s in socials:
        socials_map.setdefault(s["clte"], []).append({
            "network": s["network"],
            "url": s["url"],
            "first_seen": s["first_seen"].isoformat() if s["first_seen"] else None,
            "last_seen": s["last_seen"].isoformat() if s["last_seen"] else None,
        })

    result = []
    for c in companies:
        result.append({
            "clte": c["clte"],
            "name": c["name"],
            "verified": c["verified"],
            "rating_pct": float(c["rating_pct"]) if c["rating_pct"] else None,
            "description": c["description"],
            "store_url": c["store_url"],
            "source_url": c["source_url"],
            "first_seen": c["first_seen"].isoformat() if c["first_seen"] else None,
            "last_seen": c["last_seen"].isoformat() if c["last_seen"] else None,
            "branches": branches_map.get(c["clte"], []),
            "contacts": contacts_map.get(c["clte"], []),
            "socials": socials_map.get(c["clte"], []),
        })

    return {"companies": result}


@app.get("/api/export/contacts.csv")
def export_contacts_csv(q: str = ""):
    params = []
    where = ""
    if q.strip():
        where = "WHERE co.name ILIKE %s OR co.clte::text = %s"
        params = [f"%{q.strip()}%", q.strip()]

    def generate():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([
            "clte", "company_name", "branch_key", "type",
            "value", "value_norm", "first_seen", "last_seen",
        ])
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)

        rows = db.query(
            f"""
            SELECT ct.clte, co.name AS company_name, ct.branch_key, ct.type,
                   ct.value, ct.value_norm, ct.first_seen, ct.last_seen
            FROM contact ct
            JOIN company co ON co.clte = ct.clte
            {where}
            ORDER BY ct.clte, ct.type, ct.value
            """,
            params,
        )
        for row in rows:
            w.writerow([
                row["clte"],
                row["company_name"],
                row["branch_key"],
                row["type"],
                row["value"],
                row["value_norm"],
                row["first_seen"].isoformat() if row["first_seen"] else "",
                row["last_seen"].isoformat() if row["last_seen"] else "",
            ])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    headers = {"Content-Disposition": 'attachment; filename="contacts.csv"'}
    return StreamingResponse(generate(), media_type="text/csv", headers=headers)


@app.get("/api/export/contacts.json")
def export_contacts_json(q: str = ""):
    params = []
    where = ""
    if q.strip():
        where = "WHERE co.name ILIKE %s OR co.clte::text = %s"
        params = [f"%{q.strip()}%", q.strip()]

    rows = db.query(
        f"""
        SELECT ct.clte, co.name AS company_name, ct.branch_key, ct.type,
               ct.value, ct.value_norm, ct.first_seen, ct.last_seen
        FROM contact ct
        JOIN company co ON co.clte = ct.clte
        {where}
        ORDER BY ct.clte, ct.type, ct.value
        """,
        params,
    )

    contacts = [
        {
            "clte": row["clte"],
            "company_name": row["company_name"],
            "branch_key": row["branch_key"],
            "type": row["type"],
            "value": row["value"],
            "value_norm": row["value_norm"],
            "first_seen": row["first_seen"].isoformat() if row["first_seen"] else None,
            "last_seen": row["last_seen"].isoformat() if row["last_seen"] else None,
        }
        for row in rows
    ]
    return {"contacts": contacts}


@app.get("/api/partials/queue", response_class=HTMLResponse)
def partial_queue(request: Request):
    return render(
        "partials/queue_table.html",
        request,
        q=queue.queue_stats(),
        pending=queue.list_pending(200),
        active=queue.list_active(100),
        dead=queue.list_dead(100),
        seeds=db.query("SELECT * FROM seed ORDER BY id"),
    )
