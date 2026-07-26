"""Background discovery jobs for the Panoptes web UI."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from app.discovery.finder import discover_leads, group_for_scrape, save_leads
from app.web.helpers import EXPORTS_DIR

logger = logging.getLogger(__name__)

_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=1)


def estimate_seconds(
    target_leads: int,
    *,
    sources: Optional[list[str]] = None,
    enrich_contacts: bool = True,
    scrape_sites: bool = True,
    require_complete_contacts: bool = False,
) -> dict[str, int]:
    """Rough wall-clock estimate for the UI."""
    target = max(10, min(int(target_leads or 50), 300))
    src = {s.lower() for s in (sources or ["reddit", "web", "github"])}

    low = 12
    high = 20
    if "reddit" in src:
        low += 10 + int(target * 0.25)
        high += 20 + int(target * 0.45)
    if "web" in src:
        low += 8 + int(target * 0.1)
        high += 25 + int(target * 0.25)
    if "github" in src:
        low += 6 + int(target * 0.08)
        high += 15 + int(target * 0.18)
    if enrich_contacts:
        low += int(target * 0.2)
        high += int(target * 0.5)
        if scrape_sites:
            site_n = min(max(target * (3 if require_complete_contacts else 1), 10), 80)
            low += int(site_n * (1.0 if require_complete_contacts else 0.5))
            high += int(site_n * (2.4 if require_complete_contacts else 1.2))

    return {
        "target_leads": target,
        "estimate_low_seconds": max(15, low),
        "estimate_high_seconds": max(low + 10, high),
    }


def create_discovery_job(
    topic: str,
    *,
    company: str = "",
    sources: Optional[list[str]] = None,
    max_per_query: int = 30,
    target_leads: int = 50,
    enrich_contacts: bool = True,
    scrape_sites: bool = True,
    require_complete_contacts: bool = False,
) -> str:
    src = sources or ["reddit", "web", "github"]
    target = max(10, min(int(target_leads or 50), 300))
    # Complete-contact mode implies enrichment
    if require_complete_contacts:
        enrich_contacts = True
        scrape_sites = True
    est = estimate_seconds(
        target,
        sources=src,
        enrich_contacts=enrich_contacts,
        scrape_sites=scrape_sites,
        require_complete_contacts=require_complete_contacts,
    )
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "type": "discovery",
        "topic": topic,
        "company": company,
        "sources": src,
        "target_leads": target,
        "enrich_contacts": bool(enrich_contacts),
        "scrape_sites": bool(scrape_sites),
        "require_complete_contacts": bool(require_complete_contacts),
        "estimate_low_seconds": est["estimate_low_seconds"],
        "estimate_high_seconds": est["estimate_high_seconds"],
        "status": "queued",
        "message": "Queued",
        "leads": [],
        "files": {},
        "by_platform": {},
        "stats": {},
        "created_at": time.time(),
        "started_at": None,
        "finished_at": None,
        "elapsed_seconds": 0,
    }
    with _lock:
        _jobs[job_id] = job
    _executor.submit(_run, job_id, max_per_query)
    return job_id


def get_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        out = dict(job)
        started = out.get("started_at") or out.get("created_at")
        if out.get("finished_at"):
            out["elapsed_seconds"] = max(0, int(out["finished_at"] - started))
        elif started:
            out["elapsed_seconds"] = max(0, int(time.time() - started))
        return out


def list_jobs() -> list[dict[str, Any]]:
    with _lock:
        return [dict(j) for j in sorted(_jobs.values(), key=lambda x: x["created_at"], reverse=True)]


def _update(job_id: str, **kwargs) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(kwargs)


def _run(job_id: str, max_per_query: int) -> None:
    job = get_job(job_id)
    if not job:
        return
    started = time.time()
    try:
        _update(job_id, status="running", started_at=started, message="Searching public sources…")

        def on_progress(msg: str) -> None:
            _update(job_id, message=msg, elapsed_seconds=max(0, int(time.time() - started)))

        target = int(job.get("target_leads") or 50)
        enrich = bool(job.get("enrich_contacts", True))
        scrape = bool(job.get("scrape_sites", True))
        require_complete = bool(job.get("require_complete_contacts", False))
        leads = discover_leads(
            job["topic"],
            company=job.get("company") or "",
            sources=job.get("sources"),
            max_per_query=max_per_query,
            target_leads=target,
            enrich_contacts=enrich,
            scrape_sites=scrape,
            require_complete_contacts=require_complete,
            on_progress=on_progress,
        )
        files = save_leads(leads, EXPORTS_DIR, topic=job["topic"], prefix="discovery")
        by_platform = group_for_scrape(leads)
        stats = {
            "total": len(leads),
            "with_email": sum(1 for l in leads if l.get("email")),
            "with_phone": sum(1 for l in leads if l.get("phone")),
            "with_website": sum(1 for l in leads if l.get("website")),
            "target_leads": target,
            "require_complete_contacts": require_complete,
            "enrich_contacts": enrich,
        }
        finished = time.time()

        if require_complete:
            msg = (
                f"Found {stats['total']} / {target} complete leads "
                f"(email + phone; {stats['with_website']} with websites)"
            )
        elif enrich:
            msg = (
                f"Found {stats['total']} / {target} leads "
                f"({stats['with_email']} emails, {stats['with_phone']} phones)"
            )
        else:
            msg = f"Found {stats['total']} / {target} leads (no contact enrichment)"

        _update(
            job_id,
            status="completed",
            message=msg,
            leads=leads,
            files=files,
            by_platform=by_platform,
            stats=stats,
            finished_at=finished,
            elapsed_seconds=max(0, int(finished - started)),
        )
    except Exception as e:
        logger.exception("Discovery job %s failed", job_id)
        finished = time.time()
        _update(
            job_id,
            status="failed",
            message=str(e)[:200],
            finished_at=finished,
            elapsed_seconds=max(0, int(finished - started)),
        )
