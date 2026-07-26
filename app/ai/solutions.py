"""Help-first solutions for unanswered asks."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.ai.engine import ai_available, ai_mode, complete_json
from app.ai.intel import analyze_ask

logger = logging.getLogger(__name__)

SYSTEM = (
    "You are a senior practitioner who answers strangers' unanswered questions "
    "with genuinely useful, specific help. You never bluff. If the question is "
    "ambiguous you state the assumption you made. You give concrete steps, real "
    "tool names, and realistic time/cost estimates. Adapt tone to their urgency "
    "and buying stage — decision-stage buyers get a scoped next step, awareness "
    "buyers get a clarifying framework."
)

MAX_QUOTE = 900


def solve_ask(lead: dict[str, Any], offer_info: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Produce a solution for one public ask.

    Returns a dict with: diagnosis, assumption, steps[], deliverable,
    time_estimate, difficulty, helpful_note, confidence, source.
    """
    offer_info = offer_info or {}
    quote = _quote(lead)
    if not quote:
        return _empty("No ask text available to solve.")

    if ai_available():
        out = _solve_generative(lead, offer_info, quote)
        if out:
            return out
    return _solve_heuristic(lead, offer_info, quote)


def solve_many(
    leads: list[dict[str, Any]],
    offer_info: dict[str, Any] | None = None,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Solve the top N asks. Kept small — each one is an LLM round trip."""
    out: list[dict[str, Any]] = []
    for lead in leads[: max(0, limit)]:
        try:
            sol = solve_ask(lead, offer_info)
        except Exception as e:
            logger.debug("solve failed: %s", e)
            sol = _empty(f"Solver error: {e}")
        sol["ask_id"] = lead.get("ask_id") or ""
        sol["username"] = lead.get("username") or ""
        out.append(sol)
    return out


def _solve_generative(
    lead: dict[str, Any],
    offer_info: dict[str, Any],
    quote: str,
) -> dict[str, Any] | None:
    intel = analyze_ask(lead)
    prompt = (
        "Someone posted this publicly and got no useful reply. Solve it for real.\n\n"
        f"THEIR ASK:\n\"\"\"{quote}\"\"\"\n\n"
        f"Where posted: {lead.get('context') or lead.get('platform') or 'public forum'}\n"
        f"About them: {lead.get('what_they_do') or lead.get('site_title') or 'unknown'}\n"
        f"Detected intent={intel['intent']} ({intel['intent_confidence']}), "
        f"stage={intel['buying_stage']}, urgency={intel['urgency_label']}, "
        f"sentiment={intel['sentiment_label']}, "
        f"budget={intel.get('budget_signal')}, timeline={intel.get('timeline_signal')}\n"
        f"My expertise (context only — do NOT pitch it): {offer_info.get('offer') or 'general'}\n\n"
        "Return JSON with exactly these keys:\n"
        '  "diagnosis": 1-2 sentences naming the real underlying problem.\n'
        '  "assumption": the main assumption you had to make (or "none").\n'
        '  "steps": array of 3-6 objects {"do": short imperative, "how": one concrete sentence}.\n'
        '  "deliverable": a ready-to-use artifact as a string — a checklist, template, '
        "config, formula, or code snippet they can copy. Use \\n for newlines.\n"
        '  "time_estimate": realistic time for them to do it, e.g. "2-3 hours".\n'
        '  "difficulty": one of "easy", "moderate", "hard".\n'
        '  "helpful_note": <=90 words. Answer their question first with the single most '
        "useful insight above. Mention you can help further only in the last sentence, "
        "softly. No hype, no emojis, no 'Hope this helps'.\n"
        '  "confidence": integer 0-100 for how well you can actually solve this.\n'
    )
    data = complete_json(prompt, system=SYSTEM, max_tokens=2000, temperature=0.35)
    if not data:
        return None

    steps = []
    for s in data.get("steps") or []:
        if isinstance(s, dict) and (s.get("do") or s.get("how")):
            steps.append({"do": str(s.get("do") or "").strip(), "how": str(s.get("how") or "").strip()})
        elif isinstance(s, str) and s.strip():
            steps.append({"do": s.strip(), "how": ""})
    if not steps:
        return None

    out = {
        "diagnosis": str(data.get("diagnosis") or "").strip(),
        "assumption": str(data.get("assumption") or "").strip(),
        "steps": steps,
        "deliverable": str(data.get("deliverable") or "").strip(),
        "time_estimate": str(data.get("time_estimate") or "").strip(),
        "difficulty": (str(data.get("difficulty") or "moderate").strip().lower() or "moderate"),
        "helpful_note": str(data.get("helpful_note") or "").strip(),
        "confidence": _clamp_int(data.get("confidence"), 60),
        "source": ai_mode(),
        "intel": intel,
        "error": "",
    }
    return out


# ── Free heuristic path ───────────────────────────────────────────

# Intent → playbook (driven by Naive-Bayes classifier, not brittle regex alone)
INTENT_PLANS: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "recommend": (
        "They are choosing between options and lack a decision framework.",
        [
            ("Write down your 3 hard constraints", "Budget ceiling, must-have integration, and deadline — options that miss any are out."),
            ("Shortlist to 3 candidates", "Anything beyond 3 stalls the decision; rank by the constraint that costs most to get wrong."),
            ("Run a 30-minute trial on real data", "Use your own messiest sample, not the vendor demo data."),
            ("Pick the reversible option", "When two score close, choose the one you can migrate off cheapest."),
        ],
    ),
    "debug": (
        "This reads as a debugging problem where the failure hasn't been isolated yet.",
        [
            ("Reproduce it reliably", "Find the smallest input that still fails; intermittent bugs hide a state dependency."),
            ("Bisect the pipeline", "Disable half the moving parts; whichever half still breaks holds the cause."),
            ("Read the first error, not the last", "Later errors are usually cascade noise from the first failure."),
            ("Diff against a known-good state", "Compare config/versions with an environment where it works."),
        ],
    ),
    "hire": (
        "They need to buy expertise and lack a way to screen it.",
        [
            ("Write the outcome, not the role", "Describe the result you want in one sentence with a number in it."),
            ("Ask for one comparable result", "Request a specific past example matching your situation, with the metric."),
            ("Pay for a small scoped test", "A tiny paid trial predicts the real engagement far better than interviews."),
            ("Define the handoff up front", "Agree who owns accounts, assets, and passwords before work starts."),
        ],
    ),
    "howto": (
        "They have a process gap and need a concrete starting sequence.",
        [
            ("Name the measurable goal", "Turn the vague aim into one number and a date."),
            ("Find the current bottleneck", "Measure where time or money actually leaks today before changing anything."),
            ("Change one variable", "Fix the bottleneck alone so you can attribute the result."),
            ("Set a review date", "Book a check-in to keep or kill the change on evidence."),
        ],
    ),
    "price": (
        "They are price-shopping and need outcome-tied bands, not a feature list.",
        [
            ("Define the outcome worth paying for", "Put a dollar value on the problem before you compare vendors."),
            ("Ask for price bands by scope", "Starter / core / done-for-you — three numbers beat one opaque quote."),
            ("Demand the kill-criteria", "What result in 30 days means keep vs cancel? Write it down."),
            ("Prefer reversible spend", "Pilot price first; never lock annual until the pilot metric clears."),
        ],
    ),
    "switch": (
        "They want to leave a current vendor and fear migration cost.",
        [
            ("Inventory what you must keep", "Data, workflows, integrations — list the non-negotiables."),
            ("Price the cutover explicitly", "Migration hours + downtime risk should be a line item, not a surprise."),
            ("Run a parallel week", "Old and new side-by-side on one real workflow before you cut over."),
            ("Set a rollback date", "If metric X isn't hit by day Y, you revert — no sunk-cost trap."),
        ],
    ),
}

GENERIC_PLAN = (
    "The ask is under-specified, so the first move is to narrow it.",
    [
        ("Restate the problem in one sentence", "Force clarity on what success looks like before choosing tactics."),
        ("List what you have already tried", "This eliminates dead ends and reveals the untested assumption."),
        ("Take the smallest reversible step", "Prefer the action you can undo cheaply if it's wrong."),
        ("Measure, then decide", "Set the metric before acting so the outcome isn't a judgement call."),
    ],
)


def _solve_heuristic(
    lead: dict[str, Any],
    offer_info: dict[str, Any],
    quote: str,
) -> dict[str, Any]:
    intel = analyze_ask(lead)
    diagnosis, plan = INTENT_PLANS.get(intel["intent"], GENERIC_PLAN)

    # Stage-aware time estimate
    if intel["buying_stage"] == "decision":
        time_est, difficulty = "30-90 minutes", "easy"
    elif intel["urgency"] >= 70:
        time_est, difficulty = "1-2 hours", "moderate"
    else:
        time_est, difficulty = "1-3 hours", "moderate"

    keywords = _keywords(quote, 6)
    checklist = "\n".join(f"[ ] {do} — {how}" for do, how in plan)
    urgency_bit = (
        f" Given the {intel['urgency_label']} urgency"
        + (f" and {intel['timeline_signal']} timeline" if intel.get("timeline_signal") else "")
        + ", start with step 1 today."
        if intel["urgency"] >= 45 else ""
    )
    note = (
        f"On \"{_clip(quote, 90)}\" — the part that usually decides this is: "
        f"{plan[0][1]}{urgency_bit} "
        f"Happy to share the full checklist I use for {keywords[0] if keywords else 'this'}."
    )

    # Confidence rises with intent certainty + contactability
    conf = 32 + int(20 * float(intel.get("intent_confidence") or 0))
    if lead.get("email") or lead.get("phone"):
        conf += 6
    if intel.get("budget_signal"):
        conf += 4

    return {
        "diagnosis": diagnosis,
        "assumption": "Generated without a language model — add an OpenAI or Anthropic key for a tailored solution.",
        "steps": [{"do": do, "how": how} for do, how in plan],
        "deliverable": checklist,
        "time_estimate": time_est,
        "difficulty": difficulty,
        "helpful_note": note,
        "confidence": min(72, conf),
        "source": "heuristic",
        "intel": intel,
        "error": "",
    }


# ── helpers ───────────────────────────────────────────────────────

STOP = {
    "the", "and", "for", "with", "that", "this", "have", "has", "are", "was", "you", "your",
    "any", "one", "but", "not", "can", "get", "got", "how", "who", "what", "does", "did",
    "from", "into", "out", "our", "their", "they", "them", "there", "here", "just", "like",
    "really", "would", "could", "should", "need", "needs", "want", "wants", "looking", "help",
    "someone", "anyone", "know", "about", "some", "much", "very", "been", "being", "will",
}


def _keywords(text: str, n: int) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", (text or "").lower())
    counts: dict[str, int] = {}
    for w in words:
        if w in STOP or len(w) < 4:
            continue
        counts[w] = counts.get(w, 0) + 1
    return [w for w, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))][:n]


def _quote(lead: dict[str, Any]) -> str:
    raw = (lead.get("ask_quote") or lead.get("evidence") or lead.get("bio") or "").strip()
    return re.sub(r"\s+", " ", raw)[:MAX_QUOTE]


def _clip(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _clamp_int(value: Any, default: int) -> int:
    try:
        return max(0, min(100, int(value)))
    except Exception:
        return default


def _empty(reason: str) -> dict[str, Any]:
    return {
        "diagnosis": "",
        "assumption": "",
        "steps": [],
        "deliverable": "",
        "time_estimate": "",
        "difficulty": "",
        "helpful_note": "",
        "confidence": 0,
        "source": ai_mode(),
        "error": reason,
    }
