"""Panoptes FastAPI web application."""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import __version__
from app.demand.store import (
    delete_watch,
    init_db,
    list_leads,
    list_watches,
    save_watch,
    update_outcome,
)
from app.providers import provider_status
from app.scrapers.stealth import proxy_status, test_proxy
from app.web.helpers import (
    EXPORTS_DIR,
    PLATFORM_SCRAPERS,
    ROOT,
    delay_range,
    env_get,
    load_env,
    update_env,
)
from app.web import discovery_jobs as discovery_store
from app.web import jobs as job_store
from app.web import radar_jobs as radar_store

load_env()
logging.basicConfig(level=logging.WARNING, format="%(name)s: %(message)s")

STATIC_DIR = ROOT / "static"
TEMPLATES_DIR = ROOT / "templates"
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
init_db()
radar_store.start_watch_scheduler()

app = FastAPI(title="Panoptes", version=__version__, docs_url="/api/docs")

_cors = env_get("PANOPTES_CORS_ORIGINS", default="*")
_origins = [o.strip() for o in _cors.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _require_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(default=None),
) -> None:
    """Optional API key gate. If PANOPTES_API_KEY is unset, all requests pass."""
    expected = (env_get("PANOPTES_API_KEY") or "").strip()
    if not expected:
        return
    path = request.url.path
    if path in ("/", "/api/health") or path.startswith("/static"):
        return
    provided = (x_api_key or "").strip()
    if provided != expected:
        raise HTTPException(401, "Invalid or missing X-API-Key")


class ScrapeRequest(BaseModel):
    platform: str
    usernames: list[str] = Field(min_length=1)
    enrich: bool = True


class SettingsUpdate(BaseModel):
    linkedin_cookie: Optional[str] = None
    hunter_api_key: Optional[str] = None
    apollo_api_key: Optional[str] = None
    firecrawl_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    google_places_api_key: Optional[str] = None
    proxy: Optional[str] = None
    proxy_file: Optional[str] = None
    free_proxy: Optional[bool] = None
    delay_min: Optional[float] = None
    delay_max: Optional[float] = None


class DiscoverRequest(BaseModel):
    topic: str = Field(min_length=2)
    company: str = ""
    sources: list[str] = Field(default_factory=lambda: ["reddit", "web", "github"])
    max_per_query: int = Field(default=30, ge=5, le=100)
    target_leads: int = Field(default=50, ge=10, le=300)
    enrich_contacts: bool = True
    scrape_sites: bool = True
    require_complete_contacts: bool = False


class RadarRequest(BaseModel):
    offer: str = Field(min_length=3)
    niche: str = ""
    company: str = ""
    target: int = Field(default=25, ge=5, le=100)
    max_comments: int = Field(default=2, ge=0, le=10)
    min_silence: int = Field(default=55, ge=0, le=100)
    require_contact: bool = False
    only_new: bool = False
    include_web: bool = True
    scrape_sites: bool = True
    deepen: bool = True


class OutcomeRequest(BaseModel):
    outcome: str = Field(min_length=1)
    status: Optional[str] = None


class WatchRequest(BaseModel):
    offer: str = Field(min_length=3)
    niche: str = ""
    company: str = ""
    interval_hours: float = Field(default=6, ge=0.25, le=168)
    max_comments: int = Field(default=2, ge=0, le=10)
    target: int = Field(default=25, ge=5, le=100)
    enabled: bool = True
    deepen: bool = True
    id: Optional[str] = None


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    index_path = TEMPLATES_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(404, "UI template missing")
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "name": "Panoptes",
        "version": __version__,
        "proxy": proxy_status(),
        "platforms": list(PLATFORM_SCRAPERS.keys()),
        "features": ["demand_radar", "discover", "scrape", "watch"],
        "api_key_required": bool((env_get("PANOPTES_API_KEY") or "").strip()),
        "providers": provider_status(),
    }


@app.get("/api/settings", dependencies=[Depends(_require_api_key)])
def get_settings() -> dict[str, Any]:
    from app.providers import key_preview, provider_status

    dmin, dmax = delay_range()
    secrets = {
        "linkedin_cookie": env_get("LINKEDIN_COOKIE"),
        "hunter_api_key": env_get("HUNTER_API_KEY"),
        "apollo_api_key": env_get("APOLLO_API_KEY"),
        "firecrawl_api_key": env_get("FIRECRAWL_API_KEY"),
        "openai_api_key": env_get("OPENAI_API_KEY"),
        "anthropic_api_key": env_get("ANTHROPIC_API_KEY"),
        "google_places_api_key": env_get("GOOGLE_PLACES_API_KEY"),
    }
    return {
        **{f"{k}_set": bool(v) for k, v in secrets.items()},
        **{f"{k}_preview": key_preview(v) for k, v in secrets.items()},
        "providers": provider_status(),
        "proxy": env_get("PANOPTES_PROXY"),
        "proxy_file": env_get("PANOPTES_PROXY_FILE"),
        "free_proxy": env_get("PANOPTES_FREE_PROXY", default="false").lower()
        in ("1", "true", "yes"),
        "proxy_status": proxy_status(),
        "delay_min": dmin,
        "delay_max": dmax,
        "api_key_set": bool((env_get("PANOPTES_API_KEY") or "").strip()),
        "cors_origins": _origins,
    }


@app.put("/api/settings", dependencies=[Depends(_require_api_key)])
def put_settings(body: SettingsUpdate) -> dict[str, Any]:
    mapping = {
        "linkedin_cookie": "LINKEDIN_COOKIE",
        "hunter_api_key": "HUNTER_API_KEY",
        "apollo_api_key": "APOLLO_API_KEY",
        "firecrawl_api_key": "FIRECRAWL_API_KEY",
        "openai_api_key": "OPENAI_API_KEY",
        "anthropic_api_key": "ANTHROPIC_API_KEY",
        "google_places_api_key": "GOOGLE_PLACES_API_KEY",
    }
    data = body.model_dump(exclude_unset=True)
    for field, env_key in mapping.items():
        if field in data and data[field] is not None:
            update_env(env_key, str(data[field]).strip())
    if body.proxy is not None:
        update_env("PANOPTES_PROXY", body.proxy.strip())
    if body.proxy_file is not None:
        update_env("PANOPTES_PROXY_FILE", body.proxy_file.strip())
    if body.free_proxy is not None:
        update_env("PANOPTES_FREE_PROXY", "true" if body.free_proxy else "false")
    if body.delay_min is not None:
        update_env("PANOPTES_DELAY_MIN", str(body.delay_min))
    if body.delay_max is not None:
        update_env("PANOPTES_DELAY_MAX", str(body.delay_max))
    return get_settings()


@app.post("/api/proxy/test", dependencies=[Depends(_require_api_key)])
def proxy_test() -> dict[str, Any]:
    ok = test_proxy()
    return {"ok": ok, "status": proxy_status()}


# ── Demand Radar ──────────────────────────────────────────────

@app.post("/api/radar", dependencies=[Depends(_require_api_key)])
def start_radar(body: RadarRequest) -> dict[str, Any]:
    offer = body.offer.strip()
    if not offer:
        raise HTTPException(400, "offer is required")
    job_id = radar_store.create_radar_job(
        offer,
        niche=(body.niche or "").strip(),
        company=(body.company or "").strip(),
        target=body.target,
        max_comments=body.max_comments,
        min_silence=body.min_silence,
        require_contact=body.require_contact,
        only_new=body.only_new,
        include_web=body.include_web,
        scrape_sites=body.scrape_sites,
        deepen=body.deepen,
    )
    job = radar_store.get_job(job_id) or {}
    return {
        "job_id": job_id,
        "target": job.get("target", body.target),
        "estimate_low_seconds": job.get("estimate_low_seconds"),
        "estimate_high_seconds": job.get("estimate_high_seconds"),
    }


@app.get("/api/radar/estimate", dependencies=[Depends(_require_api_key)])
def radar_estimate(
    target: int = 25,
    scrape_sites: bool = True,
    deepen: bool = True,
) -> dict[str, Any]:
    return radar_store.estimate_seconds(target, scrape_sites=scrape_sites, deepen=deepen)


@app.get("/api/radar/leads", dependencies=[Depends(_require_api_key)])
def radar_leads(limit: int = 200, offer: str = "") -> dict[str, Any]:
    leads = list_leads(limit=min(limit, 500), offer=offer.strip())
    return {"leads": leads, "count": len(leads)}


@app.post("/api/radar/outcome/{ask_id}", dependencies=[Depends(_require_api_key)])
def radar_outcome(ask_id: str, body: OutcomeRequest) -> dict[str, Any]:
    ok = update_outcome(ask_id, body.outcome.strip(), status=body.status)
    if not ok:
        raise HTTPException(404, "Ask not found")
    return {"ok": True, "ask_id": ask_id, "outcome": body.outcome, "status": body.status}


@app.get("/api/radar/watches", dependencies=[Depends(_require_api_key)])
def radar_watches() -> dict[str, Any]:
    return {"watches": list_watches()}


@app.post("/api/radar/watches", dependencies=[Depends(_require_api_key)])
def create_watch(body: WatchRequest) -> dict[str, Any]:
    wid = (body.id or "").strip() or uuid.uuid4().hex[:10]
    save_watch({
        "id": wid,
        "offer": body.offer.strip(),
        "niche": (body.niche or "").strip(),
        "company": (body.company or "").strip(),
        "interval_hours": body.interval_hours,
        "max_comments": body.max_comments,
        "target": body.target,
        "enabled": body.enabled,
        "deepen": body.deepen,
        "created_at": time.time(),
    })
    return {"id": wid, "watches": list_watches()}


@app.delete("/api/radar/watches/{watch_id}", dependencies=[Depends(_require_api_key)])
def remove_watch(watch_id: str) -> dict[str, Any]:
    if not delete_watch(watch_id):
        raise HTTPException(404, "Watch not found")
    return {"ok": True, "watches": list_watches()}


@app.post("/api/radar/watches/{watch_id}/run", dependencies=[Depends(_require_api_key)])
def run_watch(watch_id: str) -> dict[str, Any]:
    job_id = radar_store.run_watch_now(watch_id)
    if not job_id:
        raise HTTPException(404, "Watch not found")
    return {"job_id": job_id}


@app.get("/api/radar/{job_id}", dependencies=[Depends(_require_api_key)])
def get_radar_job(job_id: str) -> dict[str, Any]:
    job = radar_store.get_job(job_id)
    if not job:
        raise HTTPException(404, "Radar job not found")
    return job


# ── Discover (business contacts) ───────────────────────────────

@app.post("/api/discover", dependencies=[Depends(_require_api_key)])
def start_discover(body: DiscoverRequest) -> dict[str, Any]:
    topic = body.topic.strip()
    if not topic:
        raise HTTPException(400, "topic is required")
    sources = [s.lower().strip() for s in body.sources if s.strip()]
    allowed = {"reddit", "web", "github"}
    sources = [s for s in sources if s in allowed] or ["reddit", "web", "github"]
    job_id = discovery_store.create_discovery_job(
        topic,
        company=(body.company or "").strip(),
        sources=sources,
        max_per_query=body.max_per_query,
        target_leads=body.target_leads,
        enrich_contacts=body.enrich_contacts,
        scrape_sites=body.scrape_sites,
        require_complete_contacts=body.require_complete_contacts,
    )
    job = discovery_store.get_job(job_id) or {}
    return {
        "job_id": job_id,
        "target_leads": job.get("target_leads", body.target_leads),
        "estimate_low_seconds": job.get("estimate_low_seconds"),
        "estimate_high_seconds": job.get("estimate_high_seconds"),
    }


@app.get("/api/discover/estimate", dependencies=[Depends(_require_api_key)])
def discover_estimate(
    target_leads: int = 50,
    reddit: bool = True,
    web: bool = True,
    github: bool = True,
    enrich_contacts: bool = True,
    scrape_sites: bool = True,
    require_complete_contacts: bool = False,
) -> dict[str, Any]:
    sources = []
    if reddit:
        sources.append("reddit")
    if web:
        sources.append("web")
    if github:
        sources.append("github")
    return discovery_store.estimate_seconds(
        target_leads,
        sources=sources or ["reddit", "web", "github"],
        enrich_contacts=enrich_contacts,
        scrape_sites=scrape_sites,
        require_complete_contacts=require_complete_contacts,
    )


@app.get("/api/discover/{job_id}", dependencies=[Depends(_require_api_key)])
def get_discover_job(job_id: str) -> dict[str, Any]:
    job = discovery_store.get_job(job_id)
    if not job:
        raise HTTPException(404, "Discovery job not found")
    return job


@app.post("/api/scrape", dependencies=[Depends(_require_api_key)])
def start_scrape(body: ScrapeRequest) -> dict[str, Any]:
    platform = body.platform.lower().strip()
    if platform not in PLATFORM_SCRAPERS:
        raise HTTPException(400, f"Unsupported platform: {platform}")

    usernames = []
    for u in body.usernames:
        for part in str(u).replace(",", "\n").splitlines():
            cleaned = part.strip().lstrip("@")
            if cleaned:
                usernames.append(cleaned)

    if not usernames:
        raise HTTPException(400, "No usernames provided")

    if platform == "linkedin" and not env_get("LINKEDIN_COOKIE"):
        raise HTTPException(400, "LinkedIn requires LINKEDIN_COOKIE in Settings / .env")

    job_id = job_store.create_job(platform, usernames, enrich=body.enrich)
    return {"job_id": job_id}


@app.get("/api/jobs", dependencies=[Depends(_require_api_key)])
def list_jobs() -> list[dict[str, Any]]:
    jobs = job_store.list_jobs()
    light = []
    for j in jobs:
        light.append({
            "id": j["id"],
            "platform": j["platform"],
            "status": j["status"],
            "progress": j["progress"],
            "total": j["total"],
            "message": j["message"],
            "export_file": j["export_file"],
            "profile_count": len(j.get("profiles") or []),
            "error_count": len(j.get("errors") or []),
            "created_at": j["created_at"],
            "finished_at": j["finished_at"],
        })
    return light


@app.get("/api/jobs/{job_id}", dependencies=[Depends(_require_api_key)])
def get_job(job_id: str) -> dict[str, Any]:
    job = job_store.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@app.get("/api/exports", dependencies=[Depends(_require_api_key)])
def list_exports() -> list[dict[str, Any]]:
    if not EXPORTS_DIR.exists():
        return []
    files = []
    paths = list(EXPORTS_DIR.glob("*.csv")) + list(EXPORTS_DIR.glob("*.txt"))
    for path in sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True):
        files.append({
            "name": path.name,
            "size": path.stat().st_size,
            "modified": path.stat().st_mtime,
        })
    return files


@app.get("/api/exports/{filename}", dependencies=[Depends(_require_api_key)])
def download_export(filename: str) -> FileResponse:
    safe = Path(filename).name
    path = EXPORTS_DIR / safe
    if not path.exists() or path.suffix.lower() not in {".csv", ".txt"}:
        raise HTTPException(404, "Export not found")
    media = "text/csv" if path.suffix.lower() == ".csv" else "text/plain"
    return FileResponse(path, filename=safe, media_type=media)


@app.delete("/api/exports/{filename}", dependencies=[Depends(_require_api_key)])
def delete_export(filename: str) -> dict[str, str]:
    safe = Path(filename).name
    path = EXPORTS_DIR / safe
    if not path.exists():
        raise HTTPException(404, "Export not found")
    path.unlink()
    return {"status": "deleted", "name": safe}
