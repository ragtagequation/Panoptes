#!/usr/bin/env python3
"""CLI: Unanswered Demand Radar — find public asks with silence + first-responder drafts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.demand.radar import run_demand_radar, save_radar_export
from app.demand.store import init_db, save_watch
from app.web.helpers import EXPORTS_DIR, load_env


def main() -> None:
    load_env()
    init_db()
    parser = argparse.ArgumentParser(
        description="Panoptes Demand Radar — unanswered public asks → contacts + drafts"
    )
    parser.add_argument(
        "offer",
        help='Your offer, e.g. "I book sales appointments for dental marketing agencies"',
    )
    parser.add_argument("--niche", default="", help="Niche override if not clear from offer")
    parser.add_argument("--company", default="", help="Optional company / product")
    parser.add_argument("--target", type=int, default=25, help="How many asks to return")
    parser.add_argument("--max-comments", type=int, default=2, help="Max replies to count as unanswered")
    parser.add_argument("--min-silence", type=int, default=55, help="Min silence score 0-100")
    parser.add_argument("--require-contact", action="store_true", help="Only keep email or phone rows")
    parser.add_argument("--only-new", action="store_true", help="Skip asks already seen in local DB")
    parser.add_argument("--no-web", action="store_true", help="Reddit-only hunt")
    parser.add_argument("--no-sites", action="store_true", help="Skip website contact scrape")
    parser.add_argument("--no-deepen", action="store_true", help="Skip Instagram/LinkedIn/social deepen")
    parser.add_argument(
        "--watch",
        type=float,
        metavar="HOURS",
        help="Also save a watch that re-scans every N hours (via web app)",
    )
    parser.add_argument("--json", action="store_true", help="Print leads as JSON")
    args = parser.parse_args()

    print("Panoptes Demand Radar")
    print(f"Offer: {args.offer}")
    if args.niche:
        print(f"Niche: {args.niche}")
    print(f"Unanswered = <={args.max_comments} comments, silence >={args.min_silence}")
    print()

    result = run_demand_radar(
        args.offer,
        niche=args.niche,
        company=args.company,
        target=args.target,
        max_comments=args.max_comments,
        min_silence=args.min_silence,
        require_contact=args.require_contact,
        only_new=args.only_new,
        include_web=not args.no_web,
        scrape_sites=not args.no_sites,
        deepen=not args.no_deepen,
        on_progress=lambda m: print(m),
    )
    leads = result["leads"]
    files = save_radar_export(leads, EXPORTS_DIR, offer=args.offer)
    stats = result["stats"]

    if args.watch is not None:
        import time
        import uuid

        wid = uuid.uuid4().hex[:10]
        save_watch({
            "id": wid,
            "offer": args.offer,
            "niche": args.niche,
            "company": args.company,
            "interval_hours": args.watch,
            "max_comments": args.max_comments,
            "target": args.target,
            "enabled": True,
            "deepen": not args.no_deepen,
            "created_at": time.time(),
        })
        print(f"\nWatch saved: {wid} (every {args.watch}h - run web app to execute)")

    print()
    print(
        f"Done — {stats.get('total', 0)} asks · "
        f"{stats.get('contactable', 0)} contactable · "
        f"{stats.get('zero_replies', 0)} zero-reply · "
        f"avg silence {stats.get('avg_silence', 0)}"
    )
    for name in files.values():
        print(f"  → exports/{name}")

    if args.json:
        print(json.dumps(leads, indent=2, default=str))
    else:
        for i, lead in enumerate(leads[:15], 1):
            q = (lead.get("ask_quote") or "")[:90].replace("\n", " ")
            print(
                f"\n{i}. silence={lead.get('silence_score')} "
                f"comments={lead.get('num_comments')} "
                f"u/{lead.get('username')}"
            )
            print(f"   {q}…")
            print(f"   {lead.get('ask_url')}")
            if lead.get("email") or lead.get("phone"):
                print(f"   contact: {lead.get('email') or '—'} · {lead.get('phone') or '—'}")


if __name__ == "__main__":
    main()
