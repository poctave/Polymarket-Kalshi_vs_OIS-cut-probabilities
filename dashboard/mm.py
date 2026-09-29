"""
Market-making calculations shared by the BOOK page. Pure functions, no I/O.

Liquidity rewards (Polymarket CLOB):
  - An order scores only if it rests within max_spread (quoted in CENTS) of the
    midpoint and is at least min_size shares.
  - When the midpoint is below 0.10 or above 0.90, quotes must be two-sided
    to score fully.
  So eligibility is about where *your* quotes sit relative to the mid, not
  about the market's own bid-ask spread.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def mid_of(bid: Optional[float], ask: Optional[float]) -> Optional[float]:
    if bid is None or ask is None or ask < bid:
        return None
    return (bid + ask) / 2


def reward_view(market: dict, bids: list, asks: list,
                bid: Optional[float], ask: Optional[float]) -> Optional[dict]:
    """Reward band and depth resting inside it. None if the market pays no rewards."""
    daily = market.get("rewards_daily") or 0.0
    max_c = market.get("rewards_max_spread_c") or 0.0
    if not daily and not max_c:
        return None
    min_size = market.get("rewards_min_size") or 0.0
    mid = mid_of(bid, ask)
    view = {"daily": daily, "max_spread_c": max_c, "min_size": min_size,
            "mid": mid, "lo": None, "hi": None,
            "bid_depth": 0.0, "ask_depth": 0.0, "two_sided": False,
            "book_spread_c": (ask - bid) * 100 if (bid is not None and ask is not None) else None}
    if mid is None or not max_c:
        return view
    band = max_c / 100.0
    lo, hi = mid - band, mid + band
    # Levels are aggregated across makers, so min_size is applied per level (approximation)
    view.update(
        lo=lo, hi=hi,
        bid_depth=sum(s for p, s in bids if p >= lo - 1e-9 and s >= min_size),
        ask_depth=sum(s for p, s in asks if p <= hi + 1e-9 and s >= min_size),
        two_sided=mid < 0.10 or mid > 0.90,
    )
    return view


def in_band(price: float, view: Optional[dict]) -> bool:
    return bool(view and view.get("lo") is not None
                and view["lo"] - 1e-9 <= price <= view["hi"] + 1e-9)


def cumulative(levels: list) -> list:
    """[(price, size)] best→worse → [(price, size, running_total)]."""
    out, total = [], 0.0
    for p, s in levels:
        total += s
        out.append((p, s, total))
    return out


def fmt_expiry(end_date: str, now: Optional[datetime] = None) -> str:
    if not end_date:
        return "--"
    try:
        end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
    except ValueError:
        return end_date[:10]
    secs = (end - (now or datetime.now(timezone.utc))).total_seconds()
    if secs <= 0:
        return "EXPIRED"
    d, rem = divmod(int(secs), 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d}D {h:02d}H"
    if h:
        return f"{h}H {m:02d}M"
    return f"{m}M"


def fmt_money(v: Optional[float]) -> str:
    if v is None:
        return "--"
    a = abs(v)
    if a >= 1e9:
        return f"${v / 1e9:.2f}B"
    if a >= 1e6:
        return f"${v / 1e6:.2f}M"
    if a >= 1e4:
        return f"${v / 1e3:.1f}K"
    return f"${v:,.0f}"


def fmt_cents(p: Optional[float], decimals: int = 1) -> str:
    return "--" if p is None else f"{p * 100:.{decimals}f}"


def price_decimals(tick: Optional[float]) -> int:
    """Cent decimals for a tick size. Minimum 1 so mids like 62.5¢ render."""
    return 1 if (not tick or tick >= 0.001) else 2
