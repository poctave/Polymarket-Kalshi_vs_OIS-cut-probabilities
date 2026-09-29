"""
Fed-path maths. Pure functions, no I/O.

Rate moves are SIGNED throughout: negative = cut, positive = hike.

FFF (30-day fed funds futures, CBOT ZQ) implied path, CME FedWatch style:
  A ZQ contract settles on the month's average EFFR, so R_m = 100 - price.
  Walking meetings in date order with `pre` = rate going into the meeting
  (today's EFFR for the first one):
    - the new rate takes effect the day after the decision (day D), so the
      month averages D days at `pre` and N-D days at `post`:
          post = (N*R_m - D*pre) / (N - D)
    - when the meeting is in the last week of the month (N-D < 7), that
      division amplifies noise, so if the next month has no meeting we take
      post = R_{m+1} instead.
    - post becomes `pre` for the next meeting.
  The expected move is split across the two neighbouring 25bp outcomes
  (e.g. +12.5bp → 50% hold / 50% hike 25).

Prediction markets quote each outcome bucket directly. By linearity of
expectation, per-meeting expected moves can be summed into a cumulative path
even though each market is a marginal.
"""

from __future__ import annotations

import calendar
import math
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Optional

BUCKETS = ("CUT50", "CUT25", "HOLD", "HIKE25", "HIKE50")
BUCKET_BPS = {"CUT50": -50, "CUT25": -25, "HOLD": 0, "HIKE25": 25, "HIKE50": 50}
BUCKET_LABEL = {"CUT50": "CUT 50+", "CUT25": "CUT 25", "HOLD": "HOLD",
                "HIKE25": "HIKE 25", "HIKE50": "HIKE 50+"}

_MONTH_CODES = "FGHJKMNQUVXZ"
LATE_MONTH_DAYS = 7


def zq_ticker(year: int, month: int) -> str:
    """Yahoo symbol for the CBOT 30-day fed funds future, e.g. (2026, 10) → ZQV26.CBT."""
    return f"ZQ{_MONTH_CODES[month - 1]}{year % 100:02d}.CBT"


def next_month(year: int, month: int) -> tuple:
    return (year + 1, 1) if month == 12 else (year, month + 1)


@dataclass
class ImpliedMeeting:
    date: date
    pre: float                 # % rate going into the meeting
    post: float                # % rate after the meeting
    method: str                # "AVG" | "NEXT"
    delta_bp: float = 0.0
    cum_bp: float = 0.0        # vs today's EFFR
    dist: dict = field(default_factory=dict)


def step_distribution(delta_bp: float) -> dict:
    """Split an expected move across the two nearest 25bp steps → bucket probabilities."""
    steps = delta_bp / 25.0
    lo = math.floor(steps)
    frac = steps - lo
    dist = {b: 0.0 for b in BUCKETS}
    for n_steps, p in ((lo, 1.0 - frac), (lo + 1, frac)):
        if p <= 1e-12:
            continue
        bps = max(-50, min(50, n_steps * 25))
        bucket = next(b for b, v in BUCKET_BPS.items() if v == bps)
        dist[bucket] += p
    return dist


def implied_path(effr: float, meetings: list,
                 zq_rate: Callable[[int, int], Optional[float]]) -> list:
    """
    effr     today's effective fed funds rate, %
    meetings future decision dates, ascending
    zq_rate  (year, month) → implied average rate % (100 - price) or None
    Stops at the first meeting whose contracts are unavailable.
    """
    meeting_months = {(d.year, d.month) for d in meetings}
    out: list = []
    pre = effr
    for d in meetings:
        n = calendar.monthrange(d.year, d.month)[1]
        after = n - d.day
        r_m = zq_rate(d.year, d.month)
        ny, nm = next_month(d.year, d.month)
        next_free = (ny, nm) not in meeting_months
        r_n = zq_rate(ny, nm) if next_free else None

        if after < LATE_MONTH_DAYS and r_n is not None:
            post, method = r_n, "NEXT"
        elif r_m is not None and after > 0:
            post, method = (n * r_m - d.day * pre) / after, "AVG"
        elif r_n is not None:
            post, method = r_n, "NEXT"
        else:
            break

        delta_bp = (post - pre) * 100
        out.append(ImpliedMeeting(
            date=d, pre=pre, post=post, method=method,
            delta_bp=delta_bp, cum_bp=(post - effr) * 100,
            dist=step_distribution(delta_bp),
        ))
        pre = post
    return out


def normalize(buckets: dict) -> dict:
    """Scale quoted bucket prices so they sum to 1 (removes the overround)."""
    quoted = {b: p for b, p in buckets.items() if p is not None}
    total = sum(quoted.values())
    if total <= 0:
        return {}
    return {b: p / total for b, p in quoted.items()}


def expected_bp(probs: dict) -> Optional[float]:
    if not probs:
        return None
    return sum(p * BUCKET_BPS[b] for b, p in probs.items())


def direction_probs(probs: dict) -> dict:
    return {
        "cut":  probs.get("CUT50", 0) + probs.get("CUT25", 0),
        "hold": probs.get("HOLD", 0),
        "hike": probs.get("HIKE25", 0) + probs.get("HIKE50", 0),
    }


def biggest_gap(model: dict, venue_raw: dict) -> Optional[dict]:
    """
    Largest |model − venue| across buckets the venue quotes AND the model
    assigns probability to. The step-split only speaks about the two outcomes
    adjacent to the expected move, so it has no view on tails; comparing a
    tail quote against its 0% would manufacture fake "rich" signals.
    venue_raw holds unnormalised prices (what you would pay for YES).
    edge_pp > 0 → venue is CHEAP relative to the FFF-implied probability.
    """
    best = None
    for b, price in venue_raw.items():
        if price is None or model.get(b, 0) <= 0:
            continue
        edge = (model[b] - price) * 100
        if best is None or abs(edge) > abs(best["edge_pp"]):
            best = {"bucket": b, "price": price, "model": model[b], "edge_pp": edge}
    return best
