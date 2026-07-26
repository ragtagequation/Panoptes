"""Competitor Vacuum + Do-Nothing share.

Market-entry research notes that tools map named competitors but miss the
'do nothing' alternative that often holds more share than any vendor.
This module sizes three slices of every ask corpus:

  named_failure  — buyer named a tool/agency that failed them (vacuum)
  status_quo     — living with the pain / DIY / 'just dealing with it'
  greenfield     — asking with no incumbent mentioned at all
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.ai.nlp import clip

# Verb that indicates dissatisfaction, then a nearby vendor name.
# Proper nouns stay case-sensitive; known SaaS brands match case-insensitively.
_FAIL_VERBS = (
    r"\b(?:tried|using|used|switched from|leaving|fed up with|hate|"
    r"didn't work|doesn'?t work|failed|cancelled|canceling|waste of)\b"
)
_KNOWN_VENDORS = (
    r"hubspot|salesforce|mailchimp|zapier|notion|airtable|intercom|zendesk|"
    r"calendly|apollo|instantly|lemlist|outreach|salesloft|klaviyo|shopify|"
    r"wordpress|wix|squarespace"
)
FAIL_KNOWN = re.compile(
    _FAIL_VERBS + r".{0,48}?\b(?P<known>" + _KNOWN_VENDORS + r")\b",
    re.I,
)
FAIL_PROPER = re.compile(
    _FAIL_VERBS + r".{0,48}?(?P<proper>\b[A-Z][a-zA-Z0-9][\w.-]{1,28}\b)",
)

# Words that look Proper but are not vendors
NOT_VENDORS = {
    "asap", "roi", "mvp", "seo", "crm", "sms", "api", "url", "http", "https",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "june", "july", "august",
    "september", "october", "november", "december", "budget", "google", "ads",
    "our", "the", "anyone", "looking", "need", "how",
}

STATUS_QUO_PAT = re.compile(
    r"\b(just (deal|dealing|live|living) with|do(ing)? it myself|diy|"
    r"manual(ly)?|spreadsheet|in[- ]house|no budget|can'?t afford|"
    r"been (putting|putting) off|status quo|as is)\b",
    re.I,
)

VENDORISH = re.compile(
    r"\b([A-Z][a-z]+(?:[A-Z][a-z]+)+|[A-Z]{2,}[a-z]*|"
    r"hubspot|salesforce|mailchimp|zapier|notion|airtable|intercom|zendesk|"
    r"calendly|apollo|instantly|lemlist|klaviyo|shopify|wordpress|wix)\b"
)


def analyze_vacuum(leads: list[dict[str, Any]]) -> dict[str, Any]:
    if not leads:
        return {
            "slices": {},
            "failed_vendors": [],
            "vacuum_asks": [],
            "do_nothing_share": 0,
            "insight": "No asks to analyse.",
        }

    slices = Counter()
    failed: Counter[str] = Counter()
    vacuum_asks: list[dict[str, Any]] = []
    status_asks: list[dict[str, Any]] = []

    for lead in leads:
        text = _text(lead)
        vendors = []
        for m in list(FAIL_KNOWN.finditer(text)) + list(FAIL_PROPER.finditer(text)):
            name = (m.groupdict().get("known") or m.groupdict().get("proper") or "").strip(".,)(")
            if len(name) >= 2 and name.lower() not in NOT_VENDORS:
                low = name.lower()
                if low not in vendors:
                    vendors.append(low)
                    failed[low] += 1

        is_status = bool(STATUS_QUO_PAT.search(text))
        has_vendor = bool(vendors) or bool(
            VENDORISH.search(text) and FAIL_KNOWN.search(text)
        )

        if vendors:
            slices["named_failure"] += 1
            vacuum_asks.append({
                "ask_id": lead.get("ask_id") or "",
                "username": lead.get("username") or "",
                "quote": clip(lead.get("ask_quote") or lead.get("evidence") or "", 180),
                "failed_vendors": vendors[:3],
                "silence_score": int(lead.get("silence_score") or 0),
            })
        elif is_status:
            slices["status_quo"] += 1
            status_asks.append({
                "ask_id": lead.get("ask_id") or "",
                "quote": clip(lead.get("ask_quote") or lead.get("evidence") or "", 160),
            })
        else:
            slices["greenfield"] += 1

    n = len(leads)
    shares = {k: round(100 * v / n, 1) for k, v in slices.items()}
    do_nothing = shares.get("status_quo", 0.0)

    top_failed = [
        {"vendor": v, "mentions": c, "opportunity": _counter(v)}
        for v, c in failed.most_common(8)
    ]

    insight = (
        f"Do-nothing / status-quo holds {do_nothing}% of asks — often bigger than any named rival. "
        f"Competitor vacuum: {shares.get('named_failure', 0)}% named a tool that failed them"
        + (f" (top: {top_failed[0]['vendor']})" if top_failed else "")
        + f". Greenfield (no incumbent): {shares.get('greenfield', 0)}%."
    )

    return {
        "slices": shares,
        "counts": dict(slices),
        "do_nothing_share": do_nothing,
        "failed_vendors": top_failed,
        "vacuum_asks": sorted(vacuum_asks, key=lambda a: -a["silence_score"])[:10],
        "status_quo_asks": status_asks[:5],
        "ask_count": n,
        "insight": insight,
    }


def _counter(vendor: str) -> str:
    return (
        f"Lead with a migration plan off {vendor} — own the cutover risk, "
        "cite one comparable switch with a metric."
    )


def _text(lead: dict[str, Any]) -> str:
    return " ".join(str(lead.get(k) or "") for k in ("ask_quote", "evidence", "context"))
