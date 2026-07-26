"""In-memory scrape job runner for the Panoptes web UI."""

from __future__ import annotations

import csv
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from app.web.helpers import EXPORTS_DIR, delay_range, env_get, get_scraper

logger = logging.getLogger(__name__)

_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=2)


def list_jobs() -> list[dict[str, Any]]:
    with _lock:
        return [dict(j) for j in sorted(_jobs.values(), key=lambda x: x["created_at"], reverse=True)]


def get_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def create_job(platform: str, usernames: list[str], enrich: bool = True) -> str:
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "platform": platform,
        "usernames": usernames,
        "enrich": enrich,
        "status": "queued",
        "progress": 0,
        "total": len(usernames),
        "current": None,
        "profiles": [],
        "errors": [],
        "export_file": None,
        "message": "Queued",
        "created_at": time.time(),
        "finished_at": None,
    }
    with _lock:
        _jobs[job_id] = job
    _executor.submit(_run_job, job_id)
    return job_id


def _update(job_id: str, **kwargs) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(kwargs)


def _run_job(job_id: str) -> None:
    job = get_job(job_id)
    if not job:
        return

    platform = job["platform"]
    usernames = job["usernames"]
    enrich = job["enrich"]

    try:
        if platform == "linkedin" and not env_get("LINKEDIN_COOKIE"):
            _update(
                job_id,
                status="failed",
                message="LINKEDIN_COOKIE is not set in .env",
                finished_at=time.time(),
            )
            return

        scraper, platform_delays = get_scraper(platform)
        delays = delay_range(platform_delays)
        _update(job_id, status="running", message="Scraping profiles…")

        profiles: list[dict] = []
        errors: list[dict] = []

        from app.scrapers.stealth import random_delay

        for i, username in enumerate(usernames):
            clean = username.strip().lstrip("@")
            if platform == "linkedin" and "/in/" in clean:
                clean = clean.split("/in/")[-1].rstrip("/")
            if not clean:
                continue

            _update(job_id, progress=i, current=clean, message=f"Scraping @{clean}")

            try:
                profile = scraper(clean)
                if profile:
                    profiles.append(profile)
                else:
                    errors.append({"username": clean, "error": "not found"})
            except RuntimeError as e:
                errors.append({"username": clean, "error": f"rate limited: {e}"})
                _update(job_id, profiles=profiles, errors=errors, message="Rate limited — stopping")
                break
            except Exception as e:
                errors.append({"username": clean, "error": str(e)[:120]})

            if i < len(usernames) - 1:
                random_delay(*delays)

        if enrich and profiles:
            _update(job_id, message="Enriching leads…", progress=len(usernames))
            from app.scrapers.enrichment import LeadEnricher

            hunter_key = env_get("HUNTER_API_KEY") or None
            enricher = LeadEnricher(hunter_api_key=hunter_key)
            profiles = [enricher.enrich_lead(p) for p in profiles]

        export_file = None
        if profiles:
            EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            export_file = f"{platform}_{job_id}_{timestamp}.csv"
            path = EXPORTS_DIR / export_file
            _write_csv(path, profiles)

        _update(
            job_id,
            status="completed",
            progress=len(usernames),
            current=None,
            profiles=profiles,
            errors=errors,
            export_file=export_file,
            message=f"Done — {len(profiles)} profile(s)",
            finished_at=time.time(),
        )
    except Exception as e:
        logger.exception("Job %s failed", job_id)
        _update(job_id, status="failed", message=str(e)[:200], finished_at=time.time())


def _write_csv(path: Path, profiles: list[dict]) -> None:
    flat_rows = []
    for p in profiles:
        flat = {k: v for k, v in p.items() if k not in ("links", "socials")}
        if isinstance(p.get("socials"), dict):
            for platform, handle in p["socials"].items():
                flat[f"social_{platform}"] = handle
        for k, v in list(flat.items()):
            if isinstance(v, (list, dict)):
                flat[k] = str(v)
        flat_rows.append(flat)

    keys: list[str] = []
    seen = set()
    for row in flat_rows:
        for k in row:
            if k not in seen:
                seen.add(k)
                keys.append(k)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(flat_rows)
