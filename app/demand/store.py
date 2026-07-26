"""SQLite store for Demand Radar leads, outcomes, and watch configs."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from app.web.helpers import ROOT

DB_PATH = ROOT / "data" / "panoptes_demand.db"


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS leads (
                ask_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                offer TEXT,
                status TEXT DEFAULT 'new',
                outcome TEXT,
                updated_at REAL
            );
            CREATE TABLE IF NOT EXISTS watches (
                id TEXT PRIMARY KEY,
                offer TEXT NOT NULL,
                niche TEXT,
                company TEXT,
                interval_hours REAL DEFAULT 6,
                max_comments INTEGER DEFAULT 2,
                target INTEGER DEFAULT 25,
                enabled INTEGER DEFAULT 1,
                deepen INTEGER DEFAULT 1,
                last_run_at REAL,
                created_at REAL
            );
            CREATE TABLE IF NOT EXISTS seen_asks (
                ask_id TEXT PRIMARY KEY,
                first_seen_at REAL
            );
            """
        )
        # Additive migration — never wipe existing rows
        cols = {r[1] for r in conn.execute("PRAGMA table_info(watches)").fetchall()}
        if "deepen" not in cols:
            conn.execute("ALTER TABLE watches ADD COLUMN deepen INTEGER DEFAULT 1")


def upsert_leads(leads: list[dict[str, Any]], offer: str = "") -> int:
    init_db()
    n = 0
    with _conn() as conn:
        for lead in leads:
            ask_id = lead.get("ask_id")
            if not ask_id:
                continue
            conn.execute(
                """
                INSERT INTO leads (ask_id, payload, offer, status, outcome, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(ask_id) DO UPDATE SET
                    payload=excluded.payload,
                    offer=excluded.offer,
                    updated_at=excluded.updated_at
                """,
                (
                    ask_id,
                    json.dumps(lead),
                    offer,
                    lead.get("status") or "new",
                    lead.get("outcome"),
                    time.time(),
                ),
            )
            conn.execute(
                "INSERT OR IGNORE INTO seen_asks (ask_id, first_seen_at) VALUES (?, ?)",
                (ask_id, time.time()),
            )
            n += 1
    return n


def list_leads(limit: int = 200, offer: str = "") -> list[dict[str, Any]]:
    init_db()
    with _conn() as conn:
        if offer:
            rows = conn.execute(
                "SELECT payload, status, outcome FROM leads WHERE offer=? ORDER BY updated_at DESC LIMIT ?",
                (offer, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT payload, status, outcome FROM leads ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    out = []
    for r in rows:
        lead = json.loads(r["payload"])
        lead["status"] = r["status"]
        lead["outcome"] = r["outcome"]
        out.append(lead)
    return out


def update_outcome(ask_id: str, outcome: str, status: Optional[str] = None) -> bool:
    init_db()
    with _conn() as conn:
        cur = conn.execute(
            """
            UPDATE leads SET outcome=?, status=COALESCE(?, status), updated_at=?
            WHERE ask_id=?
            """,
            (outcome, status, time.time(), ask_id),
        )
        return cur.rowcount > 0


def is_seen(ask_id: str) -> bool:
    init_db()
    with _conn() as conn:
        row = conn.execute("SELECT 1 FROM seen_asks WHERE ask_id=?", (ask_id,)).fetchone()
    return bool(row)


def filter_new_asks(asks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [a for a in asks if a.get("ask_id") and not is_seen(a["ask_id"])]


def save_watch(watch: dict[str, Any]) -> str:
    init_db()
    wid = watch["id"]
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO watches (id, offer, niche, company, interval_hours, max_comments, target, enabled, deepen, last_run_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                offer=excluded.offer,
                niche=excluded.niche,
                company=excluded.company,
                interval_hours=excluded.interval_hours,
                max_comments=excluded.max_comments,
                target=excluded.target,
                enabled=excluded.enabled,
                deepen=excluded.deepen
            """,
            (
                wid,
                watch.get("offer") or "",
                watch.get("niche") or "",
                watch.get("company") or "",
                float(watch.get("interval_hours") or 6),
                int(watch.get("max_comments") or 2),
                int(watch.get("target") or 25),
                1 if watch.get("enabled", True) else 0,
                1 if watch.get("deepen", True) else 0,
                watch.get("last_run_at"),
                watch.get("created_at") or time.time(),
            ),
        )
    return wid


def list_watches() -> list[dict[str, Any]]:
    init_db()
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM watches ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_watch(watch_id: str) -> dict[str, Any] | None:
    init_db()
    with _conn() as conn:
        row = conn.execute("SELECT * FROM watches WHERE id=?", (watch_id,)).fetchone()
    return dict(row) if row else None


def touch_watch(watch_id: str) -> None:
    init_db()
    with _conn() as conn:
        conn.execute("UPDATE watches SET last_run_at=? WHERE id=?", (time.time(), watch_id))


def delete_watch(watch_id: str) -> bool:
    init_db()
    with _conn() as conn:
        cur = conn.execute("DELETE FROM watches WHERE id=?", (watch_id,))
        return cur.rowcount > 0
