"""Per-ask intent, urgency, stage, reply odds."""

from __future__ import annotations

import math
import re
from typing import Any

from app.ai.nlp import bag, clip, tokenize

# Seeded class exemplars — expanded at score time into a soft NB posterior.
INTENT_SEEDS: dict[str, list[str]] = {
    "hire": [
        "looking to hire freelancer agency contractor vendor consultant expert specialist",
        "need someone who can build manage run for us recommend a good agency",
        "seeking freelancers for hire open to agencies",
    ],
    "recommend": [
        "anyone recommend suggest best alternative vs which tool software platform",
        "what do you use instead of looking for recommendations tips",
        "best options for comparing tools recommendations needed",
    ],
    "debug": [
        "not working broken error failing fails bug issue wont work cant get",
        "keeps crashing throws exception broken after update site down",
        "debugging why does this fail mysterious error",
    ],
    "howto": [
        "how do i how can i how to struggling stuck advice tips guide tutorial",
        "steps to learn process for getting started with",
        "whats the right way to approach this problem",
    ],
    "price": [
        "how much does it cost pricing budget affordable cheap expensive quote",
        "whats the price range monthly fee worth the money roi",
        "looking for pricing options cost estimate",
    ],
    "switch": [
        "switching from migrating away leaving current vendor canceling",
        "fed up with our current tool replacing looking for replacement",
        "moving off competitor want something better",
    ],
}

STAGE_PATTERNS: list[tuple[str, re.Pattern[str], float]] = [
    ("decision", re.compile(
        r"\b(ready to (buy|hire|start)|this week|asap|urgent|budget approved|"
        r"need (it|this|someone) (by|before)|closing soon|decision by)\b", re.I), 0.9),
    ("consideration", re.compile(
        r"\b(comparing|vs\.?|versus|shortlist|demo|trial|evaluate|evaluating|"
        r"options|alternatives|which (one|tool)|recommend)\b", re.I), 0.7),
    ("post_purchase", re.compile(
        r"\b(already (bought|hired|using|paid)|our current|we use|we'?re using|"
        r"migrate|migration|switch(ing)? from)\b", re.I), 0.65),
    ("awareness", re.compile(
        r"\b(is (there|it) (a|any)|does anyone|has anyone|curious|wondering|"
        r"thinking about|exploring|researching)\b", re.I), 0.5),
]

URGENCY_LEX = {
    "asap": 3.0, "urgent": 3.0, "immediately": 2.8, "today": 2.5, "tonight": 2.4,
    "deadline": 2.6, "desperate": 3.0, "struggling": 2.0, "stuck": 1.8,
    "frustrated": 2.2, "losing": 2.0, "bleeding": 2.4, "crisis": 2.8,
    "emergency": 3.0, "critical": 2.4, "broken": 1.6, "failing": 1.8,
    "can't": 1.2, "cannot": 1.2, "won't": 1.0, "please": 0.6, "help": 0.8,
    "dying": 2.2, "hemorrhaging": 2.6, "burning": 1.8, "week": 0.8, "tomorrow": 2.0,
}

FRUST_LEX = {
    "useless": 2.0, "terrible": 1.8, "awful": 1.8, "hate": 1.6, "scam": 2.2,
    "ripoff": 2.0, "waste": 1.6, "annoyed": 1.4, "frustrated": 2.0, "fed up": 2.2,
    "sick of": 2.0, "nightmare": 1.8, "garbage": 1.8, "broken": 1.2,
}

PRICE_RE = re.compile(
    r"(?:\$|usd\s*)(\d[\d,]*(?:\.\d+)?)\s*(k|m)?|"
    r"(\d[\d,]*(?:\.\d+)?)\s*(dollars?|usd|eur|euros?|gbp|pounds?)|"
    r"budget\s*(?:of|is|around|~)?\s*\$?\s*(\d[\d,]*(?:\.\d+)?)\s*(k|m)?",
    re.I,
)
TIMELINE_RE = re.compile(
    r"\b(today|tonight|tomorrow|this week|next week|this month|next month|"
    r"in \d+\s*(?:days?|weeks?|months?)|by (?:monday|friday|end of)\b|"
    r"asap|immediately|urgent)\b",
    re.I,
)


def analyze_ask(lead: dict[str, Any]) -> dict[str, Any]:
    """Full intelligence packet for one ask."""
    text = _text(lead)
    intent = classify_intent(text)
    urgency = score_urgency(text)
    sentiment = score_sentiment(text)
    stage = classify_stage(text)
    budget = extract_budget(text)
    timeline = extract_timeline(text)
    reply_odds = estimate_reply_odds(lead, urgency, stage, intent)

    return {
        "intent": intent["label"],
        "intent_confidence": intent["confidence"],
        "intent_scores": intent["scores"],
        "urgency": urgency["score"],
        "urgency_label": urgency["label"],
        "urgency_signals": urgency["signals"],
        "sentiment": sentiment["score"],
        "sentiment_label": sentiment["label"],
        "buying_stage": stage["stage"],
        "buying_stage_confidence": stage["confidence"],
        "budget_signal": budget,
        "timeline_signal": timeline,
        "reply_odds": reply_odds,
        "priority_score": _priority(lead, urgency["score"], stage, intent, reply_odds),
    }


def analyze_many(leads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for lead in leads:
        packet = analyze_ask(lead)
        packet["ask_id"] = lead.get("ask_id") or ""
        packet["username"] = lead.get("username") or ""
        packet["quote"] = clip(lead.get("ask_quote") or lead.get("evidence") or "", 180)
        out.append(packet)
    out.sort(key=lambda p: -int(p.get("priority_score") or 0))
    return out


# Hard lexical priors — when these fire, boost the class before softmax.
INTENT_PRIORS: dict[str, re.Pattern[str]] = {
    "hire": re.compile(
        r"\b(hir(e|ing)|looking to (hire|find)|need (a |an )?(freelancer|agency|contractor|setter|va|assistant)|"
        r"for hire|seeking (a |an )?(freelancer|agency)|open to agencies)\b", re.I),
    "switch": re.compile(
        r"\b(switch(ing)? from|migrat(e|ing)|leaving (our|my)|replacing (our|my)|fed up with (our|my)|"
        r"move off|cancel(l)?ing)\b", re.I),
    "debug": re.compile(
        r"\b(not working|broken|error|failing|fails|bug|crash|throws|down|won't work|can't get)\b", re.I),
    "price": re.compile(
        r"\b(how much|pricing|budget|cost|afford|quote|roi|price range|\$\d)\b", re.I),
    "recommend": re.compile(
        r"\b(recommend|suggest|best |vs\.?|versus|alternative|which (tool|one|agency)|comparing)\b", re.I),
    "howto": re.compile(
        r"\b(how (do|can|to)|struggling|stuck|tips|guide|steps to|getting started)\b", re.I),
}


def classify_intent(text: str) -> dict[str, Any]:
    """Soft multinomial NB over seeded class documents + lexical prior boosts."""
    q = bag(text)
    if not q and not (text or "").strip():
        return {"label": "howto", "confidence": 0.2, "scores": {}}

    scores: dict[str, float] = {}
    for label, seeds in INTENT_SEEDS.items():
        centroid: dict[str, float] = {}
        for seed in seeds:
            for t, c in bag(seed).items():
                centroid[t] = centroid.get(t, 0.0) + c
        total = sum(centroid.values()) + len(centroid)
        ll = 0.0
        for term, tf in q.items():
            p = (centroid.get(term, 0.0) + 0.5) / total
            ll += tf * math.log(p)
        scores[label] = ll / max(1, sum(q.values()) or 1)

    # Lexical prior boosts — decisive when language is unambiguous
    for label, pattern in INTENT_PRIORS.items():
        if pattern.search(text or ""):
            scores[label] = scores.get(label, -10.0) + 1.8

    mx = max(scores.values()) if scores else 0.0
    exps = {k: math.exp(v - mx) for k, v in scores.items()}
    z = sum(exps.values()) or 1.0
    probs = {k: round(v / z, 3) for k, v in exps.items()}
    label = max(probs, key=probs.get)  # type: ignore[arg-type]
    return {
        "label": label,
        "confidence": round(probs[label], 3),
        "scores": probs,
    }


def score_urgency(text: str) -> dict[str, Any]:
    low = (text or "").lower()
    score = 0.0
    signals: list[str] = []
    for word, w in URGENCY_LEX.items():
        if word in low:
            score += w
            signals.append(word)
    # Punctuation / caps as intensity amplifiers
    bangs = (text or "").count("!")
    if bangs:
        score += min(2.0, bangs * 0.4)
        signals.append(f"{bangs}x!")
    caps = sum(1 for w in (text or "").split() if len(w) > 3 and w.isupper())
    if caps >= 2:
        score += min(1.5, caps * 0.3)
        signals.append("ALLCAPS")
    # Normalize to 0-100
    norm = int(min(100, round(score * 12)))
    if norm >= 70:
        label = "critical"
    elif norm >= 45:
        label = "high"
    elif norm >= 20:
        label = "moderate"
    else:
        label = "low"
    return {"score": norm, "label": label, "signals": signals[:8]}


def score_sentiment(text: str) -> dict[str, Any]:
    low = (text or "").lower()
    score = 0.0
    for phrase, w in FRUST_LEX.items():
        if phrase in low:
            score -= w
    # Mild positive cues
    for phrase in ("excited", "grateful", "thanks in advance", "appreciate", "hopeful"):
        if phrase in low:
            score += 1.2
    # Map roughly to -100..100 then label
    mapped = int(max(-100, min(100, round(score * 18))))
    if mapped <= -40:
        label = "frustrated"
    elif mapped <= -10:
        label = "negative"
    elif mapped >= 25:
        label = "positive"
    else:
        label = "neutral"
    return {"score": mapped, "label": label}


def classify_stage(text: str) -> dict[str, Any]:
    for stage, pattern, conf in STAGE_PATTERNS:
        if pattern.search(text or ""):
            return {"stage": stage, "confidence": conf}
    return {"stage": "awareness", "confidence": 0.35}


def extract_budget(text: str) -> dict[str, Any] | None:
    m = PRICE_RE.search(text or "")
    if not m:
        if re.search(r"\b(no budget|tight budget|bootstrapped|cheap)\b", text or "", re.I):
            return {"amount": None, "raw": "tight/no budget", "band": "low"}
        if re.search(r"\b(enterprise|unlimited budget|money is no object)\b", text or "", re.I):
            return {"amount": None, "raw": "enterprise", "band": "high"}
        return None
    groups = [g for g in m.groups() if g]
    raw = m.group(0)
    # Parse first numeric
    num = None
    for g in m.groups():
        if g and re.match(r"^\d", g):
            try:
                num = float(g.replace(",", ""))
                break
            except ValueError:
                continue
    mult = 1.0
    if any(g and g.lower() == "k" for g in m.groups() if g):
        mult = 1_000
    elif any(g and g.lower() == "m" for g in m.groups() if g):
        mult = 1_000_000
    amount = int(num * mult) if num is not None else None
    band = "unknown"
    if amount is not None:
        if amount < 500:
            band = "low"
        elif amount < 5000:
            band = "mid"
        else:
            band = "high"
    return {"amount": amount, "raw": raw.strip(), "band": band}


def extract_timeline(text: str) -> str | None:
    m = TIMELINE_RE.search(text or "")
    return m.group(0) if m else None


def estimate_reply_odds(
    lead: dict[str, Any],
    urgency: dict[str, Any],
    stage: dict[str, Any],
    intent: dict[str, Any],
) -> int:
    """
    Lightweight logistic-style reply-likelihood (0-100).
    Trained conceptually on: silence + contactability + urgency + stage.
    """
    z = -0.4
    silence = int(lead.get("silence_score") or 0) / 100
    z += 0.9 * silence
    if lead.get("email") or lead.get("phone"):
        z += 0.7
    if lead.get("website"):
        z += 0.25
    z += 0.6 * (urgency.get("score", 0) / 100)
    stage_w = {
        "decision": 1.1, "consideration": 0.6, "post_purchase": 0.4, "awareness": 0.15,
    }
    z += stage_w.get(stage.get("stage", ""), 0.15)
    intent_w = {"hire": 0.8, "price": 0.5, "switch": 0.7, "recommend": 0.35, "howto": 0.25, "debug": 0.3}
    z += intent_w.get(intent.get("label", ""), 0.2) * float(intent.get("confidence") or 0.5)
    age = lead.get("age_days")
    if age is not None:
        try:
            a = int(age)
            if a <= 2:
                z += 0.5
            elif a <= 7:
                z += 0.25
            elif a > 30:
                z -= 0.4
        except Exception:
            pass
    # sigmoid
    p = 1 / (1 + math.exp(-z))
    return int(round(100 * p))


def _priority(
    lead: dict[str, Any],
    urgency_score: int,
    stage: dict[str, Any],
    intent: dict[str, Any],
    reply_odds: int,
) -> int:
    silence = int(lead.get("silence_score") or 0)
    stage_boost = {"decision": 20, "consideration": 12, "post_purchase": 8, "awareness": 0}
    intent_boost = {"hire": 15, "switch": 12, "price": 8, "recommend": 5, "debug": 4, "howto": 3}
    contact = 15 if (lead.get("email") or lead.get("phone")) else 0
    raw = (
        0.35 * silence
        + 0.25 * urgency_score
        + 0.20 * reply_odds
        + stage_boost.get(stage.get("stage", ""), 0)
        + intent_boost.get(intent.get("label", ""), 0)
        + contact
    )
    return int(max(0, min(100, round(raw))))


def _text(lead: dict[str, Any]) -> str:
    return " ".join(
        str(lead.get(k) or "")
        for k in ("ask_quote", "evidence", "what_they_do", "site_title", "context")
    )
