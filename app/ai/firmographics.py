"""Public firmographics from lead text, site copy, and domain cues."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any
from urllib.parse import urlparse

INDUSTRY_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("dental", re.compile(r"\b(dental|dentist|orthodont|oral surg)\b", re.I)),
    ("healthcare", re.compile(r"\b(clinic|hospital|physician|medical|healthcare|patient)\b", re.I)),
    ("saas", re.compile(r"\b(saas|software|platform|b2b software|api)\b", re.I)),
    ("agency", re.compile(r"\b(agency|marketing firm|creative studio|consulting)\b", re.I)),
    ("ecommerce", re.compile(r"\b(ecommerce|e-commerce|shopify|online store|dtc|direct[- ]to[- ]consumer)\b", re.I)),
    ("real_estate", re.compile(r"\b(real estate|realtor|property|brokerage|listing)\b", re.I)),
    ("legal", re.compile(r"\b(law firm|attorney|lawyer|legal counsel)\b", re.I)),
    ("finance", re.compile(r"\b(fintech|accounting|bookkeep|cpa|wealth|insurance)\b", re.I)),
    ("construction", re.compile(r"\b(roofing|contractor|construction|hvac|plumbing|electrician)\b", re.I)),
    ("education", re.compile(r"\b(school|university|edtech|course|coaching|tutor)\b", re.I)),
    ("hospitality", re.compile(r"\b(hotel|restaurant|cafe|hospitality|salon|spa)\b", re.I)),
    ("logistics", re.compile(r"\b(logistics|freight|shipping|warehouse|supply chain)\b", re.I)),
]

SIZE_PATTERNS: list[tuple[str, re.Pattern[str], int, int]] = [
    ("solo", re.compile(r"\b(solo|just me|one[- ]person|freelancer|independent)\b", re.I), 1, 1),
    ("micro", re.compile(r"\b(small team|team of ([2-9]|1[0-2])|([2-9]|1[0-2]) (people|employees|staff))\b", re.I), 2, 12),
    ("smb", re.compile(r"\b((1[3-9]|[2-4]\d) (people|employees|staff)|small business|smb)\b", re.I), 13, 49),
    ("midmarket", re.compile(r"\b(([5-9]\d|[1-9]\d{2}) (people|employees|staff)|mid[- ]?market|series [abc])\b", re.I), 50, 499),
    ("enterprise", re.compile(r"\b(enterprise|fortune\s*500|1000\+?\s*employees|global team)\b", re.I), 500, 10000),
]

EMP_COUNT_RE = re.compile(
    r"\b(\d{1,5})\s*(?:\+|plus)?\s*(employees?|staff|people|team members?)\b",
    re.I,
)

GEO_RE = re.compile(
    r"\b(?:in|based in|from|serving|located in)\s+"
    r"([A-Z][a-zA-Z]+(?:[\s-][A-Z][a-zA-Z]+){0,2})"
    r"(?:,\s*([A-Z]{2}|[A-Z][a-zA-Z]+))?",
)

REVENUE_RE = re.compile(
    r"\$\s?(\d+(?:\.\d+)?)\s*(k|m|b|million|thousand|billion)?\s*(?:arr|mrr|revenue|\/yr|a year)?",
    re.I,
)

ORG_TYPE_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("agency", re.compile(r"\b(agency|studio|consultancy|consulting firm)\b", re.I)),
    ("clinic", re.compile(r"\b(clinic|practice|dental office)\b", re.I)),
    ("saas", re.compile(r"\b(saas|platform|software company)\b", re.I)),
    ("ecommerce", re.compile(r"\b(store|shop|brand|dtc)\b", re.I)),
    ("marketplace", re.compile(r"\b(marketplace|two[- ]sided)\b", re.I)),
    ("nonprofit", re.compile(r"\b(nonprofit|non[- ]profit|ngo|501c)\b", re.I)),
    ("local_services", re.compile(r"\b(local|home services|contractor)\b", re.I)),
]


def extract_firmographics(lead: dict[str, Any]) -> dict[str, Any]:
    text = _corpus(lead)
    industry, industry_hits = _industry(text)
    size_band, emp_lo, emp_hi, emp_n = _size(text)
    geo = _geo(text, lead)
    revenue = _revenue(text)
    org_type = _org_type(text)
    domain = _domain(lead.get("website") or lead.get("email") or "")

    confidence = 18
    if industry_hits:
        confidence += min(35, 12 * industry_hits)
    if size_band != "unknown":
        confidence += 18
    if geo.get("region"):
        confidence += 12
    if revenue:
        confidence += 10
    if lead.get("website") or lead.get("site_title"):
        confidence += 8
    confidence = min(92, confidence)

    return {
        "industry": industry,
        "industry_confidence": round(min(1.0, industry_hits / 3), 2) if industry_hits else 0.0,
        "org_type": org_type,
        "size_band": size_band,
        "employees_low": emp_lo,
        "employees_high": emp_hi,
        "employees_mentioned": emp_n,
        "geo": geo,
        "revenue_signal": revenue,
        "domain": domain,
        "is_b2b": org_type in ("saas", "agency", "marketplace") or industry in ("saas", "agency", "finance", "logistics"),
        "confidence": confidence,
        "signals": _signal_list(industry, size_band, org_type, geo, revenue),
    }


def firmographic_landscape(leads: list[dict[str, Any]]) -> dict[str, Any]:
    packets = [extract_firmographics(l) for l in leads]
    industries = Counter(p["industry"] for p in packets if p["industry"] != "unknown")
    sizes = Counter(p["size_band"] for p in packets if p["size_band"] != "unknown")
    orgs = Counter(p["org_type"] for p in packets if p["org_type"] != "unknown")
    regions = Counter(
        (p["geo"].get("region") or "").lower()
        for p in packets
        if p["geo"].get("region")
    )
    return {
        "analysed": len(packets),
        "industries": [{"name": k, "count": v, "share": round(100 * v / max(1, len(packets)), 1)} for k, v in industries.most_common(8)],
        "size_bands": [{"name": k, "count": v} for k, v in sizes.most_common()],
        "org_types": [{"name": k, "count": v} for k, v in orgs.most_common()],
        "regions": [{"name": k, "count": v} for k, v in regions.most_common(8)],
        "b2b_share": round(100 * sum(1 for p in packets if p["is_b2b"]) / max(1, len(packets)), 1),
        "avg_confidence": int(sum(p["confidence"] for p in packets) / max(1, len(packets))),
    }


def _industry(text: str) -> tuple[str, int]:
    scored: list[tuple[int, str]] = []
    for label, pat in INDUSTRY_RULES:
        hits = len(pat.findall(text))
        if hits:
            scored.append((hits, label))
    if not scored:
        return "unknown", 0
    scored.sort(reverse=True)
    return scored[0][1], scored[0][0]


def _size(text: str) -> tuple[str, int | None, int | None, int | None]:
    m = EMP_COUNT_RE.search(text)
    if m:
        n = int(m.group(1))
        band = (
            "solo" if n <= 1 else
            "micro" if n <= 12 else
            "smb" if n <= 49 else
            "midmarket" if n <= 499 else
            "enterprise"
        )
        return band, n, n, n
    for band, pat, lo, hi in SIZE_PATTERNS:
        if pat.search(text):
            return band, lo, hi, None
    return "unknown", None, None, None


def _geo(text: str, lead: dict[str, Any]) -> dict[str, Any]:
    m = GEO_RE.search(text[:800])
    if m:
        city = m.group(1)
        region = m.group(2) or city
        return {"city": city, "region": region, "raw": m.group(0)}
    # TLD hint
    host = _domain(lead.get("website") or "")
    tld_map = {".uk": "UK", ".au": "Australia", ".ca": "Canada", ".de": "Germany", ".in": "India"}
    for suf, name in tld_map.items():
        if host.endswith(suf):
            return {"city": "", "region": name, "raw": f"tld:{suf}"}
    return {"city": "", "region": "", "raw": ""}


def _revenue(text: str) -> dict[str, Any] | None:
    m = REVENUE_RE.search(text)
    if not m:
        if re.search(r"\b(bootstrapped|pre[- ]revenue)\b", text, re.I):
            return {"amount": None, "band": "pre_revenue", "raw": "bootstrapped/pre-revenue"}
        return None
    num = float(m.group(1))
    unit = (m.group(2) or "").lower()
    mult = 1.0
    if unit in ("k", "thousand"):
        mult = 1_000
    elif unit in ("m", "million"):
        mult = 1_000_000
    elif unit in ("b", "billion"):
        mult = 1_000_000_000
    amount = int(num * mult)
    band = "micro" if amount < 100_000 else "smb" if amount < 2_000_000 else "growth" if amount < 20_000_000 else "scale"
    return {"amount": amount, "band": band, "raw": m.group(0)}


def _org_type(text: str) -> str:
    for label, pat in ORG_TYPE_RULES:
        if pat.search(text):
            return label
    return "unknown"


def _domain(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if "@" in value and "://" not in value:
        return value.split("@", 1)[-1].lower()
    if not value.startswith("http"):
        value = "https://" + value
    try:
        host = urlparse(value).netloc.lower().removeprefix("www.")
        return host
    except Exception:
        return ""


def _signal_list(industry, size, org, geo, revenue) -> list[str]:
    out = []
    if industry != "unknown":
        out.append(f"industry:{industry}")
    if size != "unknown":
        out.append(f"size:{size}")
    if org != "unknown":
        out.append(f"org:{org}")
    if geo.get("region"):
        out.append(f"geo:{geo['region']}")
    if revenue:
        out.append(f"revenue:{revenue.get('band')}")
    return out


def _corpus(lead: dict[str, Any]) -> str:
    return " ".join(
        str(lead.get(k) or "")
        for k in (
            "ask_quote", "evidence", "what_they_do", "site_title", "context",
            "bio", "full_name", "username",
        )
    )
