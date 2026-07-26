#!/usr/bin/env python3
"""CLI: find public people interested in a topic for Panoptes scraping."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.discovery.finder import discover_leads, group_for_scrape, save_leads
from app.web.helpers import EXPORTS_DIR, load_env


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(
        description="Panoptes lead finder — discover public people interested in a topic"
    )
    parser.add_argument("topic", help='Topic / niche, e.g. "appointment setting"')
    parser.add_argument("--company", default="", help="Optional company / product name")
    parser.add_argument(
        "--sources",
        default="web,reddit",
        help="Comma-separated: web,reddit,github",
    )
    parser.add_argument("--max", type=int, default=35, help="Max results per query source")
    parser.add_argument("--no-contacts", action="store_true", help="Skip email/phone/website harvest")
    parser.add_argument("--no-sites", action="store_true", help="Skip website summarization")
    parser.add_argument(
        "--complete-only",
        action="store_true",
        help="Only return leads that have both email and phone",
    )
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Deprecated alias: incomplete leads are now the default",
    )
    parser.add_argument("--target", type=int, default=50, help="How many leads to return")
    parser.add_argument("--json", action="store_true", help="Print leads as JSON")
    args = parser.parse_args()

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    require_complete = bool(args.complete_only) and not args.allow_incomplete

    print(f"Panoptes lead finder")
    print(f"Topic: {args.topic}")
    if args.company:
        print(f"Company: {args.company}")
    print(f"Sources: {', '.join(sources)}")
    print(f"Contact enrichment: {'off' if args.no_contacts else 'on'}")
    print(f"Complete contacts only: {'on' if require_complete else 'off'}")
    print()

    leads = discover_leads(
        args.topic,
        company=args.company,
        sources=sources,
        max_per_query=args.max,
        target_leads=args.target,
        enrich_contacts=not args.no_contacts,
        scrape_sites=not args.no_sites and not args.no_contacts,
        require_complete_contacts=require_complete,
        on_progress=lambda m: print(m),
    )

    files = save_leads(leads, EXPORTS_DIR, topic=args.topic, prefix="discovery")
    groups = group_for_scrape(leads)

    print()
    print(f"Unique leads: {len(leads)}")
    print(f"  with email:   {sum(1 for l in leads if l.get('email'))}")
    print(f"  with phone:   {sum(1 for l in leads if l.get('phone'))}")
    print(f"  with website: {sum(1 for l in leads if l.get('website'))}")
    for platform, users in groups.items():
        print(f"  {platform}: {len(users)} (ready for Panoptes scrape)")
    reddit_n = sum(1 for l in leads if l["platform"] == "reddit")
    if reddit_n:
        print(f"  reddit: {reddit_n} (listed in CSV; no profile scraper)")

    print()
    print("Saved:")
    for label, name in files.items():
        print(f"  [{label}] exports/{name}")

    if args.json:
        print()
        print(json.dumps(leads[:50], indent=2))

    print()
    print("Next: open Panoptes web UI, pick a platform, paste a .txt list, and scrape.")


if __name__ == "__main__":
    main()
