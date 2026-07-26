"""Temporal demand forecast — is this pain growing, flat, or dying?

Fits a simple linear trend on daily ask volume + silence, then projects
7/14/30-day forward counts. No ML framework required; OLS on a 1-feature
time index is enough to catch rising niches before competitors do.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from typing import Any


def forecast_demand(leads: list[dict[str, Any]], *, horizon_days: int = 14) -> dict[str, Any]:
    if not leads:
        return {
            "trend": "unknown",
            "slope_per_day": 0.0,
            "projected_7d": 0,
            "projected_14d": 0,
            "projected_30d": 0,
            "series": [],
            "confidence": 0,
            "insight": "No asks to forecast from.",
        }

    now = time.time()
    # Bucket by age_days when present; otherwise treat as "today"
    by_day: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for lead in leads:
        age = lead.get("age_days")
        try:
            day = int(age) if age is not None else 0
        except Exception:
            day = 0
        day = max(0, min(90, day))  # clamp
        by_day[day].append(lead)

    # Build series oldest → newest (day 90 → day 0)
    max_day = max(by_day.keys()) if by_day else 0
    series = []
    xs: list[float] = []
    ys: list[float] = []
    for d in range(max_day, -1, -1):
        bucket = by_day.get(d, [])
        count = len(bucket)
        avg_sil = (
            int(sum(int(l.get("silence_score") or 0) for l in bucket) / count)
            if count else 0
        )
        # x = time index where larger = more recent
        x = float(max_day - d)
        series.append({
            "age_days": d,
            "count": count,
            "avg_silence": avg_sil,
            "t": int(x),
        })
        xs.append(x)
        ys.append(float(count))

    slope, intercept, r2 = _ols(xs, ys)
    # Project forward from "today" (x = max_day)
    x_now = float(max_day)

    def project(days_ahead: int) -> int:
        y = intercept + slope * (x_now + days_ahead)
        # cumulative expected new asks over the window ≈ mean daily * days
        # Use slope to adjust the recent daily rate
        recent = ys[-7:] if len(ys) >= 7 else ys
        base_rate = (sum(recent) / len(recent)) if recent else 0.0
        adj = max(0.0, base_rate + slope * (days_ahead / 2))
        return int(max(0, round(adj * days_ahead)))

    # Trend label
    if len(ys) < 3:
        trend = "insufficient_data"
    elif slope > 0.08 and r2 > 0.15:
        trend = "rising"
    elif slope < -0.08 and r2 > 0.15:
        trend = "falling"
    else:
        trend = "flat"

    conf = int(max(0, min(100, round(100 * max(0.0, r2) * min(1.0, len(ys) / 14)))))

    insight = {
        "rising": (
            f"Demand is rising (~{slope:+.2f} asks/day). "
            f"Expect ~{project(7)} new asks in 7 days if the trend holds — move first."
        ),
        "falling": (
            f"Demand is cooling ({slope:+.2f} asks/day). "
            "Harvest the remaining high-silence asks now; don't over-invest in this niche."
        ),
        "flat": (
            f"Demand is steady. Project ~{project(14)} asks over the next 2 weeks — "
            "good for a recurring watch, not a land-grab."
        ),
        "insufficient_data": "Need more dated asks before a trend is trustworthy.",
        "unknown": "No signal.",
    }[trend]

    return {
        "trend": trend,
        "slope_per_day": round(slope, 4),
        "r_squared": round(r2, 3),
        "projected_7d": project(7),
        "projected_14d": project(14),
        "projected_30d": project(30),
        "series": series[-30:],  # last 30 day-buckets
        "confidence": conf,
        "insight": insight,
        "ask_count": len(leads),
    }


def _ols(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    n = len(xs)
    if n < 2:
        return 0.0, (ys[0] if ys else 0.0), 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den = sum((x - mean_x) ** 2 for x in xs) or 1.0
    slope = num / den
    intercept = mean_y - slope * mean_x
    # R²
    ss_tot = sum((y - mean_y) ** 2 for y in ys) or 1.0
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    r2 = max(0.0, 1.0 - ss_res / ss_tot)
    return slope, intercept, r2
