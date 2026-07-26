"""Identity resolution and profile intelligence."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from typing import Any
from urllib.parse import urlparse

from app.ai.engine import ai_available, ai_mode, complete_json
from app.ai.firmographics import extract_firmographics
from app.ai.intel import analyze_ask
from app.ai.nlp import bag, clip, jaccard
from app.ai.technographics import extract_technographics

SYSTEM = (
    "Write compact prospect dossiers from supplied public facts. "
    "Do not infer protected traits or invent facts. Separate evidence from uncertainty."
)

PLATFORM_WEIGHT = {
    "linkedin": 18,
    "github": 14,
    "youtube": 12,
    "instagram": 10,
    "x": 9,
    "twitter": 9,
    "tiktok": 8,
    "reddit": 7,
    "twitch": 6,
    "pinterest": 5,
    "linktree": 4,
    "facebook": 4,
    "website": 10,
}

HIGH_RISK_EMAIL_PREFIXES = {"info", "hello", "contact", "support", "admin", "sales"}


def resolve_profiles(leads: list[dict[str, Any]], *, limit: int = 100) -> dict[str, Any]:
    records = leads[: max(0, limit)]
    if not records:
        return _empty_landscape()

    parent = list(range(len(records)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    index: dict[str, int] = {}
    keys_by_record: list[set[str]] = []
    for i, lead in enumerate(records):
        keys = _identity_keys(lead)
        keys_by_record.append(keys)
        for key in keys:
            if key in index:
                union(i, index[key])
            else:
                index[key] = i

    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for i, lead in enumerate(records):
        groups[find(i)].append(lead)

    dossiers = [build_profile(group) for group in groups.values()]
    dossiers.sort(
        key=lambda d: (
            -d["priority_score"],
            -d["identity_confidence"],
            -d["completeness"],
        )
    )

    platforms = Counter()
    risk_flags = Counter()
    for dossier in dossiers:
        platforms.update(dossier["platforms"])
        risk_flags.update(dossier["risk_flags"])

    return {
        "profiles": dossiers,
        "resolved_profiles": len(dossiers),
        "source_records": len(records),
        "merged_records": len(records) - len(dossiers),
        "contactable": sum(1 for d in dossiers if d["contact"]["routes"]),
        "high_confidence": sum(1 for d in dossiers if d["identity_confidence"] >= 75),
        "platforms": [{"name": k, "count": v} for k, v in platforms.most_common()],
        "risk_flags": [{"name": k, "count": v} for k, v in risk_flags.most_common()],
        "insight": _landscape_insight(dossiers, len(records)),
    }


def build_profile(records: list[dict[str, Any]]) -> dict[str, Any]:
    records = [r for r in records if isinstance(r, dict)]
    canonical = _canonical_record(records)
    handles = _collect_handles(records)
    platforms = sorted({h["platform"] for h in handles if h["platform"]})
    emails = _unique(
        str(r.get("email") or "").strip().lower()
        for r in records
        if r.get("email")
    )
    phones = _unique(str(r.get("phone") or "").strip() for r in records if r.get("phone"))
    websites = _unique(
        _normalize_url(str(r.get("website") or ""))
        for r in records
        if r.get("website")
    )
    names = _unique(
        str(r.get("full_name") or r.get("site_title") or "").strip()
        for r in records
        if r.get("full_name") or r.get("site_title")
    )

    firm = extract_firmographics(canonical)
    tech = extract_technographics(canonical)
    behavioral = _behavior(records)
    authority = _authority(records, platforms)
    consistency = _consistency(records, names, websites, handles)
    completeness = _completeness(names, handles, emails, phones, websites, firm, tech)
    identity_confidence = _identity_confidence(records, names, websites, handles, emails)
    risks = _risk_flags(records, names, emails, phones, websites, consistency)
    routes = _contact_routes(emails, phones, handles, websites)
    priority = _priority(authority, completeness, identity_confidence, behavioral, routes, risks)
    profile_id = _profile_id(emails, websites, handles, names, canonical)

    return {
        "profile_id": profile_id,
        "display_name": names[0] if names else canonical.get("username") or "Unknown",
        "username": canonical.get("username") or "",
        "records": len(records),
        "platforms": platforms,
        "handles": handles,
        "contact": {
            "emails": emails,
            "phones": phones,
            "websites": websites,
            "routes": routes,
        },
        "firmographics": firm,
        "technographics": tech,
        "behavior": behavioral,
        "authority_score": authority,
        "identity_confidence": identity_confidence,
        "consistency_score": consistency,
        "completeness": completeness,
        "priority_score": priority,
        "risk_flags": risks,
        "summary": _summary(
            names[0] if names else canonical.get("username") or "Unknown",
            platforms,
            firm,
            tech,
            behavioral,
            routes,
        ),
        "evidence": [
            {
                "ask_id": r.get("ask_id") or "",
                "platform": r.get("platform") or r.get("ask_source") or "",
                "quote": clip(r.get("ask_quote") or r.get("evidence") or r.get("bio") or "", 160),
            }
            for r in records[:5]
        ],
    }


def profile_brief(
    records: list[dict[str, Any]],
    *,
    offer: str = "",
) -> dict[str, Any]:
    profile = build_profile(records)
    if not ai_available():
        return profile

    prompt = (
        f"OFFER: {offer or 'unspecified'}\n"
        f"PROFILE: {profile['display_name']}\n"
        f"PLATFORMS: {profile['platforms']}\n"
        f"FIRM: {profile['firmographics']}\n"
        f"TECH: {profile['technographics']['by_category']}\n"
        f"BEHAVIOR: {profile['behavior']}\n"
        f"CONTACT ROUTES: {profile['contact']['routes']}\n"
        f"RISKS: {profile['risk_flags']}\n\n"
        "Return JSON with keys: "
        '{"brief":"<=80 words",'
        '"best_channel":"one route",'
        '"opening":"one help-first opening line",'
        '"avoid":"one specific caution",'
        '"confidence":0-100}'
    )
    data = complete_json(prompt, system=SYSTEM, max_tokens=750, temperature=0.3)
    if not data or not data.get("brief"):
        return profile

    profile["generated"] = {
        "brief": str(data.get("brief") or "")[:600],
        "best_channel": str(data.get("best_channel") or "")[:80],
        "opening": str(data.get("opening") or "")[:300],
        "avoid": str(data.get("avoid") or "")[:250],
        "confidence": _int(data.get("confidence"), 50),
    }
    profile["source"] = ai_mode()
    return profile


def _identity_keys(lead: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    email = str(lead.get("email") or "").strip().lower()
    if email:
        keys.add(f"email:{email}")

    for field in ("website", "profile_url", "deepened_profile_url"):
        domain = _domain(str(lead.get(field) or ""))
        if domain and domain not in {"reddit.com", "instagram.com", "linkedin.com", "x.com", "twitter.com"}:
            keys.add(f"domain:{domain}")

    for handle in _collect_handles([lead]):
        if handle["platform"] and handle["username"]:
            keys.add(f"handle:{handle['platform']}:{handle['username'].lower()}")

    platform = str(lead.get("platform") or "").lower()
    username = _normalize_handle(str(lead.get("username") or ""))
    if platform and username:
        keys.add(f"handle:{platform}:{username}")

    name = _normalize_name(str(lead.get("full_name") or ""))
    owned_domain = _domain(str(lead.get("website") or "")) or _domain(email)
    if name and owned_domain:
        keys.add(f"name-domain:{name}:{owned_domain}")
    return keys


def _canonical_record(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {}
    scored = []
    for record in records:
        score = sum(
            1
            for key in (
                "full_name", "bio", "email", "phone", "website", "what_they_do",
                "site_title", "tech_fingerprint",
            )
            if record.get(key)
        )
        score += len(record.get("linked_handles") or [])
        scored.append((score, record))
    scored.sort(key=lambda x: -x[0])
    base = dict(scored[0][1])
    for _, record in scored[1:]:
        for key in (
            "full_name", "bio", "email", "phone", "website", "what_they_do",
            "site_title", "html_snippet", "tech_fingerprint",
        ):
            if not base.get(key) and record.get(key):
                base[key] = record[key]
    return base


def _collect_handles(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(platform: str, username: str, url: str = "") -> None:
        platform = platform.lower().strip()
        if platform == "twitter":
            platform = "x"
        username = _normalize_handle(username)
        if not platform or not username:
            return
        key = (platform, username.lower())
        if key in seen:
            return
        seen.add(key)
        found.append({"platform": platform, "username": username, "url": url})

    for record in records:
        add(
            str(record.get("platform") or record.get("ask_source") or ""),
            str(record.get("username") or ""),
            str(record.get("profile_url") or ""),
        )
        for item in record.get("linked_handles") or []:
            if isinstance(item, dict):
                add(
                    str(item.get("platform") or ""),
                    str(item.get("username") or ""),
                    str(item.get("url") or ""),
                )
        for field in ("profile_url", "deepened_profile_url"):
            platform, username = _handle_from_url(str(record.get(field) or ""))
            add(platform, username, str(record.get(field) or ""))
    return found


def _behavior(records: list[dict[str, Any]]) -> dict[str, Any]:
    packets = [analyze_ask(r) for r in records]
    intents = Counter(p["intent"] for p in packets)
    stages = Counter(p["buying_stage"] for p in packets)
    urgency = int(sum(p["urgency"] for p in packets) / max(1, len(packets)))
    odds = int(sum(p["reply_odds"] for p in packets) / max(1, len(packets)))
    topics = Counter()
    for record in records:
        topics.update(bag(" ".join(str(record.get(k) or "") for k in ("ask_quote", "evidence", "bio"))))
    return {
        "primary_intent": intents.most_common(1)[0][0] if intents else "unknown",
        "intent_mix": dict(intents),
        "buying_stage": stages.most_common(1)[0][0] if stages else "unknown",
        "stage_mix": dict(stages),
        "avg_urgency": urgency,
        "avg_reply_odds": odds,
        "topics": [term for term, _ in topics.most_common(8)],
        "asks": len(records),
    }


def _authority(records: list[dict[str, Any]], platforms: list[str]) -> int:
    score = sum(PLATFORM_WEIGHT.get(p, 3) for p in platforms)
    followers = 0
    verified = False
    for record in records:
        followers = max(followers, _int(record.get("followers") or record.get("followers_count"), 0))
        verified = verified or bool(record.get("verified") or record.get("is_verified"))
    if followers:
        score += min(35, int(7 * math.log10(max(10, followers))))
    if verified:
        score += 15
    return min(100, score)


def _consistency(
    records: list[dict[str, Any]],
    names: list[str],
    websites: list[str],
    handles: list[dict[str, str]],
) -> int:
    score = 45
    if len(records) > 1:
        score += 15
    if names:
        normalized = [_normalize_name(n) for n in names]
        if len(set(normalized)) == 1:
            score += 15
        elif len(normalized) > 1:
            pair_scores = [
                jaccard(set(a.split()), set(b.split()))
                for i, a in enumerate(normalized)
                for b in normalized[i + 1 :]
            ]
            score += int(10 * (sum(pair_scores) / max(1, len(pair_scores))))
    if websites and len({_domain(w) for w in websites}) == 1:
        score += 15
    handle_names = {h["username"].lower() for h in handles}
    if len(handle_names) == 1 and handle_names:
        score += 10
    elif len(handle_names) > 4:
        score -= 10
    return max(0, min(100, score))


def _completeness(
    names: list[str],
    handles: list[dict[str, str]],
    emails: list[str],
    phones: list[str],
    websites: list[str],
    firm: dict[str, Any],
    tech: dict[str, Any],
) -> int:
    score = 0
    score += 15 if names else 0
    score += min(20, len(handles) * 7)
    score += 18 if emails else 0
    score += 12 if phones else 0
    score += 12 if websites else 0
    score += 13 if firm.get("industry") != "unknown" else 0
    score += 10 if tech.get("stack_size") else 0
    return min(100, score)


def _identity_confidence(
    records: list[dict[str, Any]],
    names: list[str],
    websites: list[str],
    handles: list[dict[str, str]],
    emails: list[str],
) -> int:
    score = 25
    score += 30 if emails else 0
    score += 22 if websites else 0
    score += min(18, len(handles) * 6)
    score += 10 if names else 0
    score += min(10, max(0, len(records) - 1) * 4)
    return min(100, score)


def _risk_flags(
    records: list[dict[str, Any]],
    names: list[str],
    emails: list[str],
    phones: list[str],
    websites: list[str],
    consistency: int,
) -> list[str]:
    flags: list[str] = []
    if not emails and not phones:
        flags.append("no_direct_contact")
    if emails and all(e.split("@", 1)[0] in HIGH_RISK_EMAIL_PREFIXES for e in emails if "@" in e):
        flags.append("generic_email_only")
    if not websites:
        flags.append("no_owned_domain")
    if not names:
        flags.append("identity_name_missing")
    if consistency < 55:
        flags.append("cross_profile_mismatch")
    if any(int(r.get("num_comments") or 0) > 10 for r in records):
        flags.append("crowded_thread")
    return flags


def _contact_routes(
    emails: list[str],
    phones: list[str],
    handles: list[dict[str, str]],
    websites: list[str],
) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    for email in emails:
        prefix = email.split("@", 1)[0]
        quality = 55 if prefix in HIGH_RISK_EMAIL_PREFIXES else 90
        routes.append({"channel": "email", "value": email, "quality": quality})
    for phone in phones:
        routes.append({"channel": "phone", "value": phone, "quality": 82})
    for handle in handles:
        quality = 75 if handle["platform"] in ("linkedin", "x", "instagram") else 58
        routes.append({
            "channel": handle["platform"],
            "value": handle["username"],
            "quality": quality,
        })
    for website in websites:
        routes.append({"channel": "website", "value": website, "quality": 45})
    routes.sort(key=lambda r: -r["quality"])
    return routes


def _priority(
    authority: int,
    completeness: int,
    identity_confidence: int,
    behavior: dict[str, Any],
    routes: list[dict[str, Any]],
    risks: list[str],
) -> int:
    route_quality = routes[0]["quality"] if routes else 0
    score = (
        0.18 * authority
        + 0.18 * completeness
        + 0.20 * identity_confidence
        + 0.18 * behavior["avg_reply_odds"]
        + 0.12 * behavior["avg_urgency"]
        + 0.14 * route_quality
        - min(20, len(risks) * 4)
    )
    return max(0, min(100, int(round(score))))


def _summary(
    name: str,
    platforms: list[str],
    firm: dict[str, Any],
    tech: dict[str, Any],
    behavior: dict[str, Any],
    routes: list[dict[str, Any]],
) -> str:
    firm_part = "/".join(
        p for p in (firm.get("industry"), firm.get("size_band")) if p and p != "unknown"
    ) or "firm unknown"
    stack = [p["product"] for p in (tech.get("products") or [])[:3]]
    route = routes[0]["channel"] if routes else "public reply"
    parts = [
        name,
        firm_part,
        f"{len(platforms)} platform{'s' if len(platforms) != 1 else ''}",
        f"intent {behavior['primary_intent']}",
        f"stage {behavior['buying_stage']}",
        f"best route {route}",
    ]
    if stack:
        parts.append("stack " + ", ".join(stack))
    return " · ".join(parts)


def _landscape_insight(dossiers: list[dict[str, Any]], records: int) -> str:
    if not dossiers:
        return "No profiles resolved."
    top = dossiers[0]
    return (
        f"{records} records resolved into {len(dossiers)} profiles; "
        f"{sum(1 for d in dossiers if d['contact']['routes'])} contactable. "
        f"Top profile: {top['display_name']} (priority {top['priority_score']}, "
        f"identity {top['identity_confidence']})."
    )


def _profile_id(
    emails: list[str],
    websites: list[str],
    handles: list[dict[str, str]],
    names: list[str],
    canonical: dict[str, Any],
) -> str:
    seed = (
        (emails[0] if emails else "")
        or (_domain(websites[0]) if websites else "")
        or (f"{handles[0]['platform']}:{handles[0]['username']}" if handles else "")
        or (names[0] if names else "")
        or str(canonical.get("ask_id") or canonical.get("username") or "unknown")
    )
    return hashlib.sha256(seed.lower().encode("utf-8")).hexdigest()[:16]


def _handle_from_url(url: str) -> tuple[str, str]:
    if not url:
        return "", ""
    try:
        parsed = urlparse(url if "://" in url else "https://" + url)
    except ValueError:
        return "", ""
    host = parsed.netloc.lower().removeprefix("www.")
    platform = {
        "instagram.com": "instagram",
        "linkedin.com": "linkedin",
        "github.com": "github",
        "youtube.com": "youtube",
        "x.com": "x",
        "twitter.com": "x",
        "tiktok.com": "tiktok",
        "reddit.com": "reddit",
        "twitch.tv": "twitch",
        "pinterest.com": "pinterest",
    }.get(host, "")
    segments = [s for s in parsed.path.split("/") if s]
    username = segments[-1] if segments else ""
    if platform == "linkedin" and len(segments) >= 2:
        username = segments[1]
    return platform, _normalize_handle(username)


def _normalize_handle(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "", (value or "").strip().lstrip("@"))[:80]


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (value or "").lower()).strip()


def _normalize_url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if not value.startswith("http"):
        value = "https://" + value
    return value.rstrip("/")


def _domain(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if "@" in value and "://" not in value:
        return value.split("@", 1)[-1].lower()
    if not value.startswith("http"):
        value = "https://" + value
    try:
        return urlparse(value).netloc.lower().removeprefix("www.")
    except ValueError:
        return ""


def _unique(values) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _empty_landscape() -> dict[str, Any]:
    return {
        "profiles": [],
        "resolved_profiles": 0,
        "source_records": 0,
        "merged_records": 0,
        "contactable": 0,
        "high_confidence": 0,
        "platforms": [],
        "risk_flags": [],
        "insight": "No profiles resolved.",
    }
