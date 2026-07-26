"""Background Demand Radar jobs + watch scheduler."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from app.demand.radar import run_demand_radar, save_radar_export
from app.demand.store import get_watch, list_watches, touch_watch
from app.web.helpers import EXPORTS_DIR

logger = logging.getLogger(__name__)

_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=1)
_watch_started = False
_watch_stop = threading.Event()


def estimate_seconds(
    target: int = 25,
    scrape_sites: bool = True,
    deepen: bool = True,
) -> dict[str, int]:
    n = max(5, min(int(target or 25), 100))
    low = 25 + n * 2
    high = 50 + n * 5
    if scrape_sites:
        low += n * 2
        high += n * 6
    if deepen:
        low += n * 3
        high += n * 8
    return {
        "target": n,
        "estimate_low_seconds": max(30, low),
        "estimate_high_seconds": max(low + 20, high),
    }


def create_radar_job(
    offer: str,
    *,
    niche: str = "",
    company: str = "",
    target: int = 25,
    max_comments: int = 2,
    min_silence: int = 55,
    require_contact: bool = False,
    only_new: bool = False,
    include_web: bool = True,
    scrape_sites: bool = True,
    deepen: bool = True,
) -> str:
    est = estimate_seconds(target, scrape_sites=scrape_sites, deepen=deepen)
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "type": "radar",
        "offer": offer,
        "niche": niche,
        "company": company,
        "target": max(5, min(int(target or 25), 100)),
        "max_comments": max(0, min(int(max_comments), 10)),
        "min_silence": max(0, min(int(min_silence), 100)),
        "require_contact": bool(require_contact),
        "only_new": bool(only_new),
        "include_web": bool(include_web),
        "scrape_sites": bool(scrape_sites),
        "deepen": bool(deepen),
        "estimate_low_seconds": est["estimate_low_seconds"],
        "estimate_high_seconds": est["estimate_high_seconds"],
        "status": "queued",
        "message": "Queued",
        "leads": [],
        "files": {},
        "stats": {},
        "offer_compiled": {},
        "created_at": time.time(),
        "started_at": None,
        "finished_at": None,
        "elapsed_seconds": 0,
    }
    with _lock:
        _jobs[job_id] = job
    _executor.submit(_run, job_id)
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


def _run(job_id: str) -> None:
    job = get_job(job_id)
    if not job:
        return
    started = time.time()
    try:
        _update(job_id, status="running", started_at=started, message="Hunting unanswered demand...")

        def on_progress(msg: str) -> None:
            _update(job_id, message=msg, elapsed_seconds=max(0, int(time.time() - started)))

        result = run_demand_radar(
            job["offer"],
            niche=job.get("niche") or "",
            company=job.get("company") or "",
            target=int(job.get("target") or 25),
            max_comments=int(job.get("max_comments") or 2),
            min_silence=int(job.get("min_silence") or 55),
            require_contact=bool(job.get("require_contact")),
            only_new=bool(job.get("only_new")),
            include_web=bool(job.get("include_web", True)),
            scrape_sites=bool(job.get("scrape_sites", True)),
            deepen=bool(job.get("deepen", True)),
            on_progress=on_progress,
        )
        leads = result.get("leads") or []
        files = save_radar_export(leads, EXPORTS_DIR, offer=job["offer"])
        finished = time.time()
        stats = result.get("stats") or {}
        _update(
            job_id,
            status="completed",
            message=(
                f"Found {stats.get('total', len(leads))} unanswered asks "
                f"({stats.get('contactable', 0)} contactable, "
                f"{stats.get('zero_replies', 0)} zero-reply, "
                f"{stats.get('deepened', 0)} deepened)"
            ),
            leads=leads,
            files=files,
            stats=stats,
            offer_compiled=result.get("offer") or {},
            finished_at=finished,
            elapsed_seconds=max(0, int(finished - started)),
        )
    except Exception as e:
        logger.exception("Radar job %s failed", job_id)
        finished = time.time()
        _update(
            job_id,
            status="failed",
            message=str(e)[:200],
            finished_at=finished,
            elapsed_seconds=max(0, int(finished - started)),
        )


def start_watch_scheduler(poll_seconds: float = 60.0) -> None:
    """Start background loop that re-runs due watches."""
    global _watch_started
    if _watch_started:
        return
    _watch_started = True
    _watch_stop.clear()

    def loop() -> None:
        logger.info("Demand Radar watch scheduler started")
        while not _watch_stop.is_set():
            try:
                _tick_watches()
            except Exception:
                logger.exception("Watch tick failed")
            _watch_stop.wait(poll_seconds)

    threading.Thread(target=loop, name="radar-watch", daemon=True).start()


def _tick_watches() -> None:
    now = time.time()
    for w in list_watches():
        if not w.get("enabled"):
            continue
        interval = float(w.get("interval_hours") or 6) * 3600
        last = w.get("last_run_at") or 0
        if last and (now - float(last)) < interval:
            continue
        wid = w["id"]
        offer = (w.get("offer") or "").strip()
        if not offer:
            continue
        touch_watch(wid)
        logger.info("Watch %s due - starting radar for %s", wid, offer[:60])
        create_radar_job(
            offer,
            niche=w.get("niche") or "",
            company=w.get("company") or "",
            target=int(w.get("target") or 25),
            max_comments=int(w.get("max_comments") or 2),
            only_new=True,
            include_web=True,
            scrape_sites=True,
            deepen=bool(w.get("deepen", 1)),
        )


def run_watch_now(watch_id: str) -> Optional[str]:
    w = get_watch(watch_id)
    if not w:
        return None
    touch_watch(watch_id)
    return create_radar_job(
        w["offer"],
        niche=w.get("niche") or "",
        company=w.get("company") or "",
        target=int(w.get("target") or 25),
        max_comments=int(w.get("max_comments") or 2),
        only_new=True,
        include_web=True,
        scrape_sites=True,
        deepen=bool(w.get("deepen", 1)),
    )
