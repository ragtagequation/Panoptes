"""Clustering, demand brief, offer doctor."""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from typing import Any

from app.ai.engine import ai_available, ai_mode, complete_json

logger = logging.getLogger(__name__)

STOP = {
    "the", "and", "for", "with", "that", "this", "have", "has", "had", "are", "was", "were",
    "you", "your", "yours", "any", "all", "one", "two", "but", "not", "can", "cant", "get",
    "got", "how", "who", "what", "when", "where", "why", "does", "did", "doing", "from",
    "into", "out", "our", "ours", "their", "they", "them", "there", "here", "just", "like",
    "really", "would", "could", "should", "need", "needs", "needed", "want", "wants",
    "looking", "look", "help", "someone", "anyone", "anybody", "know", "about", "some",
    "much", "many", "very", "been", "being", "will", "its", "it's", "i'm", "i've", "dont",
    "doesn", "isn", "wasn", "aren", "hasn", "haven", "won", "wouldn", "couldn", "shouldn",
    "also", "than", "then", "them", "these", "those", "over", "under", "more", "most",
    "less", "least", "each", "other", "another", "same", "such", "only", "own", "too",
    "was", "use", "using", "used", "way", "ways", "thing", "things", "make", "makes",
    "made", "new", "old", "good", "bad", "best", "better", "worse", "worst", "please",
    "thanks", "thank", "hey", "hi", "hello", "guys", "everyone", "advice", "recommendations",
    "recommendation", "recommend", "suggestions", "suggestion", "tips", "question",
    # conversational filler that otherwise pollutes cluster labels
    "actually", "already", "nothing", "even", "still", "again", "maybe", "anything",
    "everything", "something", "somebody", "basically", "literally", "currently",
    "trying", "tried", "keeps", "keep", "gets", "getting", "given", "since", "though",
    "because", "before", "after", "around", "without", "within", "while", "against",
}

MIN_TOKEN_LEN = 4

# Consultant-speak that buyers never type. Used by the free offer doctor so it
# only strikes real filler instead of legitimate domain vocabulary.
BUZZWORDS = {
    "synergistic", "synergy", "synergies", "leverage", "leveraging", "omnichannel",
    "paradigm", "paradigms", "holistic", "bespoke", "turnkey", "seamless", "robust",
    "scalable", "innovative", "cutting-edge", "best-in-class", "world-class",
    "next-generation", "disruptive", "empower", "empowering", "unlock", "unlocking",
    "streamline", "streamlined", "optimize", "optimized", "optimizing", "utilize",
    "utilizing", "solutions", "solution-driven", "value-add", "value-added",
    "end-to-end", "full-service", "results-driven", "data-driven", "mission-critical",
    "ecosystem", "framework", "methodology", "transformative", "revolutionary",
    "game-changing", "state-of-the-art", "proactive", "actionable", "granular",
    "bandwidth", "touchpoint", "touchpoints", "ideate", "ideation", "curated",
}


# ── Clustering (free, stdlib only) ────────────────────────────────

def cluster_asks(leads: list[dict[str, Any]], *, max_clusters: int = 6) -> list[dict[str, Any]]:
    """
    Group asks by shared vocabulary using TF-IDF cosine similarity and a
    greedy leader algorithm. No external deps, no API cost.
    """
    docs: list[tuple[int, dict[str, float]]] = []
    for i, lead in enumerate(leads):
        vec = _tfidf_ready_tokens(_text_of(lead))
        if vec:
            docs.append((i, vec))
    if not docs:
        return []

    # idf across the corpus
    df: Counter[str] = Counter()
    for _, toks in docs:
        df.update(set(toks))
    n = len(docs)
    vectors: list[tuple[int, dict[str, float]]] = []
    for idx, toks in docs:
        vec: dict[str, float] = {}
        for term, tf in toks.items():
            # smoothed idf: rare terms still win, but terms shared across the
            # whole corpus keep enough weight to actually pull a cluster together
            idf = math.log(1 + n / (1 + df[term]))
            vec[term] = tf * idf
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        vectors.append((idx, {k: v / norm for k, v in vec.items()}))

    # greedy leader clustering — biggest-first so themes are stable
    threshold = 0.12
    clusters: list[dict[str, Any]] = []
    for idx, vec in vectors:
        best, best_sim = None, 0.0
        for cl in clusters:
            sim = _cosine(vec, cl["_centroid"])
            if sim > best_sim:
                best, best_sim = cl, sim
        if best is not None and best_sim >= threshold:
            best["members"].append(idx)
            _merge_centroid(best, vec)
        else:
            clusters.append({"members": [idx], "_centroid": dict(vec)})

    clusters.sort(key=lambda c: len(c["members"]), reverse=True)
    clusters = clusters[:max_clusters]

    out: list[dict[str, Any]] = []
    for cl in clusters:
        members = cl["members"]
        member_leads = [leads[i] for i in members]
        # Label from raw in-cluster frequency, not the idf centroid: idf
        # deliberately suppresses the domain words that make the best label.
        label_counts: Counter[str] = Counter()
        for ml in member_leads:
            label_counts.update(_tfidf_ready_tokens(_text_of(ml)).keys())
        terms = [t for t, _ in label_counts.most_common(5)]
        if not terms:
            terms = [t for t, _ in sorted(cl["_centroid"].items(), key=lambda kv: -kv[1])[:5]]
        silences = [int(l.get("silence_score") or 0) for l in member_leads]
        out.append({
            "theme": " / ".join(terms[:3]) if terms else "misc",
            "keywords": terms,
            "count": len(members),
            "share": round(100 * len(members) / len(leads), 1) if leads else 0,
            "avg_silence": int(sum(silences) / len(silences)) if silences else 0,
            "contactable": sum(1 for l in member_leads if l.get("email") or l.get("phone")),
            "examples": [
                {
                    "quote": _clip(l.get("ask_quote") or l.get("evidence") or "", 220),
                    "url": l.get("ask_url") or "",
                    "username": l.get("username") or "",
                }
                for l in member_leads[:3]
            ],
        })
    return out


def _merge_centroid(cluster: dict[str, Any], vec: dict[str, float]) -> None:
    c = cluster["_centroid"]
    k = len(cluster["members"])
    for term, val in vec.items():
        c[term] = (c.get(term, 0.0) * (k - 1) + val) / k
    # keep centroids small for speed
    if len(c) > 400:
        cluster["_centroid"] = dict(sorted(c.items(), key=lambda kv: -kv[1])[:200])


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


def _stem(word: str) -> str:
    """Crude suffix stripper so 'appointment/appointments' and 'book/booking' merge."""
    # "business"/"status" are not plurals — stripping the s mangles them
    if word.endswith(("ss", "us", "is")):
        return word
    for suffix in ("ing", "ers", "er", "ies", "ied", "ed", "es", "s"):
        if len(word) - len(suffix) >= 4 and word.endswith(suffix):
            stem = word[: -len(suffix)]
            if suffix == "ies":
                return stem + "y"
            # undo doubled consonant ("setter" -> "set") but never for s/f/z,
            # which would turn "missing" into "mis"
            if (
                suffix in ("ing", "ed", "er", "ers")
                and len(stem) > 3
                and stem[-1] == stem[-2]
                and stem[-1] in "bdglmnprt"
            ):
                return stem[:-1]
            return stem
    return word


def _tfidf_ready_tokens(text: str) -> dict[str, float]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", (text or "").lower())
    counts: Counter[str] = Counter(
        _stem(w) for w in words if w not in STOP and len(w) >= MIN_TOKEN_LEN
    )
    if not counts:
        return {}
    return {w: 1 + math.log(c) for w, c in counts.items()}


# ── Demand brief ──────────────────────────────────────────────────

BRIEF_SYSTEM = (
    "You are a blunt demand analyst. You only make claims the supplied evidence "
    "supports. If the evidence is thin you say so and lower the score. You never "
    "invent quotes or statistics."
)


def demand_brief(
    leads: list[dict[str, Any]],
    offer_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evidence-backed verdict on whether real demand exists."""
    offer_info = offer_info or {}
    stats = compute_signal(leads)
    clusters = cluster_asks(leads)

    base = {
        "stats": stats,
        "clusters": clusters,
        "demand_score": stats["demand_score"],
        "source": ai_mode(),
    }

    if not leads:
        return {
            **base,
            "verdict": "No evidence yet",
            "reasoning": "Run a Demand Radar scan first — there are no asks to analyse.",
            "top_pains": [],
            "voice_of_customer": [],
            "positioning": "",
            "riskiest_assumption": "",
            "next_actions": [],
        }

    if ai_available():
        gen = _brief_generative(leads, offer_info, stats, clusters)
        if gen:
            return {**base, **gen}
    return {**base, **_brief_heuristic(leads, stats, clusters)}


def compute_signal(leads: list[dict[str, Any]]) -> dict[str, Any]:
    """Hard numbers that ground the verdict."""
    n = len(leads)
    if not n:
        return {
            "total": 0, "zero_reply": 0, "contactable": 0, "avg_silence": 0,
            "fresh_7d": 0, "demand_score": 0,
        }
    zero = sum(1 for l in leads if int(l.get("num_comments") or 0) == 0)
    contactable = sum(1 for l in leads if l.get("email") or l.get("phone"))
    silences = [int(l.get("silence_score") or 0) for l in leads]
    avg_sil = int(sum(silences) / len(silences)) if silences else 0
    fresh = sum(
        1 for l in leads
        if l.get("age_days") is not None and int(l.get("age_days") or 999) <= 7
    )

    # volume, silence, freshness and reachability each carry weight
    vol = min(1.0, n / 40)
    sil = avg_sil / 100
    frs = fresh / n
    rch = contactable / n
    score = int(round(100 * (0.35 * vol + 0.3 * sil + 0.2 * frs + 0.15 * rch)))

    return {
        "total": n,
        "zero_reply": zero,
        "contactable": contactable,
        "avg_silence": avg_sil,
        "fresh_7d": fresh,
        "demand_score": max(0, min(100, score)),
    }


def _brief_generative(
    leads: list[dict[str, Any]],
    offer_info: dict[str, Any],
    stats: dict[str, Any],
    clusters: list[dict[str, Any]],
) -> dict[str, Any] | None:
    sample = []
    for l in leads[:28]:
        q = _clip(l.get("ask_quote") or l.get("evidence") or "", 240)
        if q:
            sample.append(f"- ({l.get('num_comments') or 0} replies) {q}")
    if not sample:
        return None

    theme_lines = "\n".join(
        f"- {c['theme']}: {c['count']} asks ({c['share']}%), avg silence {c['avg_silence']}"
        for c in clusters
    )

    prompt = (
        f"OFFER BEING VALIDATED: {offer_info.get('offer') or 'unspecified'}\n"
        f"NICHE: {offer_info.get('niche') or 'unspecified'}\n\n"
        f"HARD NUMBERS: {stats['total']} unanswered asks found, "
        f"{stats['zero_reply']} with zero replies, {stats['fresh_7d']} posted in the last 7 days, "
        f"{stats['contactable']} reachable, average silence score {stats['avg_silence']}/100.\n\n"
        f"CLUSTERS DETECTED:\n{theme_lines or '- none'}\n\n"
        f"RAW ASKS (verbatim):\n" + "\n".join(sample) + "\n\n"
        "Return JSON with keys:\n"
        '  "verdict": <=8 words, e.g. "Real but fragmented demand".\n'
        '  "reasoning": 2-3 sentences citing the numbers above. Be honest if the sample is too small.\n'
        '  "top_pains": array of 3-5 objects {"pain": short label, "evidence": a real verbatim '
        "fragment from the asks above, \"frequency\": rough count as integer}.\n"
        '  "voice_of_customer": array of 3-6 short verbatim phrases buyers actually used '
        "(copy their words exactly — these become ad copy).\n"
        '  "positioning": one sentence describing how to position the offer using their language.\n'
        '  "riskiest_assumption": the single assumption most likely to be wrong.\n'
        '  "next_actions": array of 3-4 concrete next steps, each <=14 words.\n'
    )
    data = complete_json(prompt, system=BRIEF_SYSTEM, max_tokens=2200, temperature=0.3)
    if not data or not data.get("verdict"):
        return None

    pains = []
    for p in data.get("top_pains") or []:
        if isinstance(p, dict) and p.get("pain"):
            pains.append({
                "pain": str(p.get("pain"))[:120],
                "evidence": _clip(str(p.get("evidence") or ""), 200),
                "frequency": _int(p.get("frequency"), 0),
            })
        elif isinstance(p, str):
            pains.append({"pain": p[:120], "evidence": "", "frequency": 0})

    return {
        "verdict": str(data.get("verdict"))[:80],
        "reasoning": str(data.get("reasoning") or "")[:900],
        "top_pains": pains,
        "voice_of_customer": [str(v)[:160] for v in (data.get("voice_of_customer") or [])][:6],
        "positioning": str(data.get("positioning") or "")[:400],
        "riskiest_assumption": str(data.get("riskiest_assumption") or "")[:300],
        "next_actions": [str(a)[:140] for a in (data.get("next_actions") or [])][:4],
    }


def _brief_heuristic(
    leads: list[dict[str, Any]],
    stats: dict[str, Any],
    clusters: list[dict[str, Any]],
) -> dict[str, Any]:
    score = stats["demand_score"]
    if score >= 65:
        verdict = "Strong unanswered demand"
    elif score >= 40:
        verdict = "Real but thin demand"
    elif score >= 20:
        verdict = "Weak signal so far"
    else:
        verdict = "Not enough evidence"

    reasoning = (
        f"Found {stats['total']} asks, {stats['zero_reply']} with zero replies and "
        f"{stats['fresh_7d']} from the last week. Average silence is "
        f"{stats['avg_silence']}/100 and {stats['contactable']} are directly reachable. "
        "Add an OpenAI or Anthropic key for a written analysis of the underlying pains."
    )

    pains = [
        {
            "pain": c["theme"],
            "evidence": c["examples"][0]["quote"] if c["examples"] else "",
            "frequency": c["count"],
        }
        for c in clusters[:5]
    ]

    voc = []
    for lead in leads:
        frag = _best_fragment(lead.get("ask_quote") or lead.get("evidence") or "")
        if frag and frag not in voc:
            voc.append(frag)
        if len(voc) >= 6:
            break

    return {
        "verdict": verdict,
        "reasoning": reasoning,
        "top_pains": pains,
        "voice_of_customer": voc,
        "positioning": (
            f"Lead with the most common theme ({clusters[0]['theme']}) in their own words."
            if clusters else ""
        ),
        "riskiest_assumption": (
            "That these posters have budget — silence may mean low intent, not unmet need."
        ),
        "next_actions": [
            f"Reply publicly to the {stats['zero_reply']} zero-reply asks first",
            "Solve the top ask with the Answer Engine before pitching",
            "Re-scan in 7 days to confirm the demand repeats",
        ],
    }


# ── Offer doctor ──────────────────────────────────────────────────

def offer_doctor(offer: str, leads: list[dict[str, Any]]) -> dict[str, Any]:
    """Rewrite the offer using the vocabulary buyers actually used."""
    offer = (offer or "").strip()
    if not offer:
        return {"error": "Provide an offer to diagnose.", "source": ai_mode()}

    vocab = _corpus_keywords(leads, 18)
    if ai_available() and leads:
        sample = [
            _clip(l.get("ask_quote") or l.get("evidence") or "", 200)
            for l in leads[:20]
        ]
        prompt = (
            f"CURRENT OFFER: {offer}\n\n"
            f"WORDS REAL BUYERS USED (frequency-ranked): {', '.join(vocab)}\n\n"
            "THEIR ACTUAL ASKS:\n" + "\n".join(f"- {s}" for s in sample if s) + "\n\n"
            "Return JSON with keys:\n"
            '  "score": integer 0-100 for how well the current offer matches this demand.\n'
            '  "problems": array of 2-4 specific weaknesses in the current wording.\n'
            '  "rewrite": the offer rewritten in the buyers\' own vocabulary, one or two sentences.\n'
            '  "headline": a 10-word-max headline using their words.\n'
            '  "jargon_to_drop": array of words in the current offer that buyers never used.\n'
            '  "words_to_use": array of 4-8 buyer words the offer should adopt.\n'
        )
        data = complete_json(prompt, system=BRIEF_SYSTEM, max_tokens=1400, temperature=0.4)
        if data and data.get("rewrite"):
            return {
                "score": _int(data.get("score"), 50),
                "problems": [str(p)[:200] for p in (data.get("problems") or [])][:4],
                "rewrite": str(data.get("rewrite"))[:600],
                "headline": str(data.get("headline") or "")[:140],
                "jargon_to_drop": [str(w)[:40] for w in (data.get("jargon_to_drop") or [])][:8],
                "words_to_use": [str(w)[:40] for w in (data.get("words_to_use") or [])][:8],
                "source": ai_mode(),
                "error": "",
            }

    # free path: overlap analysis between offer wording and buyer wording
    offer_words = {
        w for w in re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", offer.lower())
        if w not in STOP and len(w) >= MIN_TOKEN_LEN
    }
    overlap = [w for w in vocab if w in offer_words]
    missing = [w for w in vocab if w not in offer_words][:8]
    score = int(round(100 * len(overlap) / max(1, min(len(vocab), 10))))

    problems = [
        f"Your offer shares {len(overlap)} of the top {len(vocab)} words buyers actually used."
    ]
    if vocab and not overlap:
        problems.append(
            "Zero overlap usually means the stored asks are from a different niche — "
            "run a Demand Radar scan for this offer, then diagnose again."
        )
    problems.append("Buyer vocabulary below is ranked by real frequency — lead with it.")

    return {
        "score": max(0, min(100, score)),
        "problems": problems,
        "rewrite": "",
        "headline": "",
        # Only flag recognised buzzwords. Absence from the corpus alone does not
        # make a word bad — it may simply be the correct domain term.
        "jargon_to_drop": sorted(offer_words & BUZZWORDS)[:8],
        "words_to_use": missing,
        "source": "heuristic",
        "error": "",
    }


def _corpus_keywords(leads: list[dict[str, Any]], n: int) -> list[str]:
    counts: Counter[str] = Counter()
    for lead in leads:
        words = re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", _text_of(lead).lower())
        counts.update(w for w in words if w not in STOP and len(w) >= MIN_TOKEN_LEN)
    return [w for w, _ in counts.most_common(n)]


# ── helpers ───────────────────────────────────────────────────────

def _text_of(lead: dict[str, Any]) -> str:
    return " ".join(
        str(lead.get(k) or "")
        for k in ("ask_quote", "evidence", "what_they_do", "site_title", "context")
    )


def _best_fragment(text: str) -> str:
    """Pick the clause most likely to read like buyer language."""
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if not text:
        return ""
    for part in re.split(r"[.!?\n]", text):
        part = part.strip()
        if 20 <= len(part) <= 120 and re.search(
            r"\b(need|looking|want|recommend|help|struggl|any(one|body)|how do)\b", part, re.I
        ):
            return part
    return _clip(text, 110)


def _clip(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default
