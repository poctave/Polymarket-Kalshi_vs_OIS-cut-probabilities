"""
FFF / OIS vs Polymarket — WIRP Data Layer
==========================================

Computes two curves (like Bloomberg WIRP):
  - FFF WIRP:  cumulative expected 25bps cuts implied by ZQ futures proxy contracts
  - PM WIRP:   cumulative expected 25bps cuts implied by Polymarket per-meeting markets

FFF WIRP formula (direct, no per-meeting probability needed):
    WIRP_FFF(M) = (EFFR - post_M_rate) / 0.25
where post_M_rate = futures rate of the first no-meeting ZQ month AFTER meeting M.

Per-meeting P(cut) for the table uses the adjacent-contract diff / FedWatch formula.
"""

import re
import sys
import json
import time
import threading
from datetime import date
from typing import Optional

import yfinance as yf

# Reuse existing Polymarket API helpers (api.py lives in parent dashboard/ folder)
sys.path.insert(0, __file__.rsplit("/", 2)[0])
import api


# ── FOMC Calendar ──────────────────────────────────────────────────────────────

FOMC_MEETINGS = [
    # proxy_ticker: first no-meeting ZQ month AFTER this meeting (for WIRP)
    # next_ticker:  used for late-month meetings (days_after ≤ 3) to compute per-meeting P(cut)
    # prev_ticker:  no-meeting month BEFORE meeting (chains expected EFFR for distant meetings)
    {
        "date": date(2026, 3, 19), "ticker": "ZQH26.CBT", "month_days": 31, "meeting_day": 19,
        "label": "Mar 2026", "month": "march",
        "proxy_ticker": "ZQK26.CBT",  # May
        "next_ticker": None, "prev_ticker": None,
    },
    {
        "date": date(2026, 4, 30), "ticker": "ZQJ26.CBT", "month_days": 30, "meeting_day": 30,
        "label": "Apr 2026", "month": "april",
        "proxy_ticker": "ZQK26.CBT",  # May
        "next_ticker": "ZQK26.CBT", "prev_ticker": None,
    },
    {
        "date": date(2026, 6, 18), "ticker": "ZQM26.CBT", "month_days": 30, "meeting_day": 18,
        "label": "Jun 2026", "month": "june",
        "proxy_ticker": "ZQQ26.CBT",  # Aug
        "next_ticker": None, "prev_ticker": "ZQK26.CBT",
    },
    {
        "date": date(2026, 7, 30), "ticker": "ZQN26.CBT", "month_days": 31, "meeting_day": 30,
        "label": "Jul 2026", "month": "july",
        "proxy_ticker": "ZQQ26.CBT",  # Aug
        "next_ticker": "ZQQ26.CBT", "prev_ticker": None,
    },
    {
        "date": date(2026, 9, 17), "ticker": "ZQU26.CBT", "month_days": 30, "meeting_day": 17,
        "label": "Sep 2026", "month": "september",
        "proxy_ticker": "ZQX26.CBT",  # Nov
        "next_ticker": None, "prev_ticker": "ZQQ26.CBT",
    },
    {
        "date": date(2026, 10, 29), "ticker": "ZQV26.CBT", "month_days": 31, "meeting_day": 29,
        "label": "Oct 2026", "month": "october",
        "proxy_ticker": "ZQX26.CBT",  # Nov
        "next_ticker": "ZQX26.CBT", "prev_ticker": None,
    },
    {
        "date": date(2026, 12, 16), "ticker": "ZQZ26.CBT", "month_days": 31, "meeting_day": 16,
        "label": "Dec 2026", "month": "december",
        "proxy_ticker": "ZQF27.CBT",  # Jan 2027
        "next_ticker": None, "prev_ticker": "ZQX26.CBT",
    },
]

_CACHE_TTL = 60.0  # seconds


# ── EFFR ───────────────────────────────────────────────────────────────────────

_EFFR_FALLBACK = 3.64
_effr_cache: dict = {"rate": None, "ts": 0.0}
_effr_lock = threading.Lock()


def get_current_effr() -> float:
    """Fetch latest EFFR from FRED CSV (no API key). 60-min TTL."""
    with _effr_lock:
        c = _effr_cache
        if c["rate"] and time.monotonic() - c["ts"] < 3600:
            return c["rate"]

    try:
        import requests as _req
        r = _req.get(
            "https://fred.stlouisfed.org/graph/fredgraph.csv?id=EFFR",
            timeout=8,
        )
        r.raise_for_status()
        last_line = [ln for ln in r.text.strip().split("\n") if ln][-1]
        rate = float(last_line.split(",")[1])
        with _effr_lock:
            _effr_cache["rate"] = rate
            _effr_cache["ts"] = time.monotonic()
        return rate
    except Exception:
        return _EFFR_FALLBACK


# ── ZQ Price Cache ─────────────────────────────────────────────────────────────

_zq_cache: dict = {}
_zq_lock = threading.Lock()


def _fetch_zq_price(ticker: str) -> Optional[float]:
    """Fetch ZQ futures last price via yfinance with 60s TTL cache."""
    with _zq_lock:
        cached = _zq_cache.get(ticker)
        if cached and time.monotonic() - cached["ts"] < _CACHE_TTL:
            return cached["price"]

    try:
        price = float(yf.Ticker(ticker).fast_info.last_price)
        with _zq_lock:
            _zq_cache[ticker] = {"price": price, "ts": time.monotonic()}
        return price
    except Exception:
        try:
            hist = yf.Ticker(ticker).history(period="1d", interval="1m")
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
                with _zq_lock:
                    _zq_cache[ticker] = {"price": price, "ts": time.monotonic()}
                return price
        except Exception:
            pass
        return None


# ── Per-Meeting FedWatch Probability ──────────────────────────────────────────

def _per_meeting_p_cut(
    zq_price: float,
    effr: float,
    meeting_day: int,
    month_days: int,
    next_ticker: Optional[str],
    prev_ticker: Optional[str],
) -> Optional[float]:
    """
    Compute per-meeting P(cut) using the appropriate two-contract diff or
    chained-EFFR FedWatch formula depending on meeting position in month.
    """
    days_after = month_days - meeting_day

    if days_after <= 3 and next_ticker:
        # Meeting is near end of month — use next-month contract as post-meeting rate
        next_price = _fetch_zq_price(next_ticker)
        if next_price is not None:
            pre_rate  = 100.0 - zq_price
            post_rate = 100.0 - next_price
            return max(0.0, min(1.0, (pre_rate - post_rate) / 0.25))

    # Standard FedWatch formula; use prev no-meeting contract as EFFR for distant meetings
    if prev_ticker:
        prev_price = _fetch_zq_price(prev_ticker)
        effr_used = (100.0 - prev_price) if prev_price else effr
    else:
        effr_used = effr

    futures_rate = 100.0 - zq_price
    if days_after <= 0:
        post_rate = futures_rate
    else:
        post_rate = (futures_rate * month_days - effr_used * meeting_day) / days_after

    p_cut  = max(0.0, min(1.0, (effr_used - post_rate) / 0.25))
    return p_cut


# ── Kalshi Fed Meeting Markets ─────────────────────────────────────────────────

# Map meeting label → Kalshi ticker prefix (KXFEDDECISION series)
_KALSHI_PREFIX = {
    "Mar 2026": "KXFEDDECISION-26MAR",
    "Apr 2026": "KXFEDDECISION-26APR",
    "Jun 2026": "KXFEDDECISION-26JUN",
    "Jul 2026": "KXFEDDECISION-26JUL",
    "Sep 2026": "KXFEDDECISION-26SEP",
    "Oct 2026": "KXFEDDECISION-26OCT",
    "Dec 2026": "KXFEDDECISION-26DEC",
}

_kalshi_cache: dict = {"data": None, "ts": 0.0}
_kalshi_lock = threading.Lock()
_KALSHI_API  = "https://api.elections.kalshi.com/trade-api/v2"


def _get_kalshi_probs() -> dict:
    """
    Fetch per-meeting cut probabilities from Kalshi KXFEDDECISION series.
    Prices are in cents (0-100); divide by 100 to get probability.
    Uses last_price; falls back to mid of yes_bid/yes_ask.

    Returns dict keyed by meeting label:
        {"Mar 2026": {"p_cut_25": 0.02, "p_cut_50": 0.01, "p_cut": 0.03}, ...}
    """
    with _kalshi_lock:
        c = _kalshi_cache
        if c["data"] and time.monotonic() - c["ts"] < _CACHE_TTL:
            return dict(c["data"])

    try:
        import requests as _req
        r = _req.get(
            f"{_KALSHI_API}/markets",
            params={"series_ticker": "KXFEDDECISION", "limit": 200},
            timeout=10,
        )
        r.raise_for_status()
        markets = r.json().get("markets", [])
    except Exception:
        return {}

    # Index by ticker
    by_ticker = {m["ticker"]: m for m in markets}

    def _price(ticker: str) -> Optional[float]:
        m = by_ticker.get(ticker)
        if not m:
            return None
        lp = m.get("last_price")
        if lp is not None:
            return float(lp) / 100.0
        bid = m.get("yes_bid")
        ask = m.get("yes_ask")
        if bid is not None and ask is not None:
            return (float(bid) + float(ask)) / 200.0
        return None

    result = {}
    for label, prefix in _KALSHI_PREFIX.items():
        p25 = _price(f"{prefix}-C25")
        p50 = _price(f"{prefix}-C26")  # C26 = cut >25bps (i.e. 50+)
        p_cut = None
        if p25 is not None and p50 is not None:
            p_cut = p25 + p50
        elif p25 is not None:
            p_cut = p25
        elif p50 is not None:
            p_cut = p50
        result[label] = {"p_cut_25": p25, "p_cut_50": p50, "p_cut": p_cut}

    with _kalshi_lock:
        _kalshi_cache["data"] = result
        _kalshi_cache["ts"]   = time.monotonic()

    return result


# ── Polymarket Fed Market Matching ─────────────────────────────────────────────

# Direct event slugs for 2026 FOMC meetings on Polymarket gamma API
_PM_EVENT_SLUGS = {
    "Mar 2026": "fed-decision-in-march-885",
    "Apr 2026": "fed-decision-in-april",
    "Jun 2026": "fed-decision-in-june-825",
    # Jul/Sep/Oct/Dec: only 2025 versions exist on PM; use Kalshi for those
}

_GAMMA_API = "https://gamma-api.polymarket.com"
_pm_cache: dict = {"data": None, "ts": 0.0}
_pm_lock  = threading.Lock()

_CUT_50_RE    = re.compile(r"decrease.*?50\+?\s*bps?|50\+?\s*bps?.*?decrease", re.IGNORECASE)
_CUT_25_RE    = re.compile(r"decrease.*?25\s*bps?|25\s*bps?.*?decrease", re.IGNORECASE)
_NO_CHANGE_RE = re.compile(r"no\s+change", re.IGNORECASE)


def _get_fed_pm_probs() -> dict:
    """
    Fetch Polymarket Fed rate decision markets by direct event slug.

    Returns dict keyed by meeting label:
        {"Mar 2026": {"p_cut": float|None, "p_cut_25": float|None,
                      "p_cut_50": float|None, "p_no_change": float|None}, ...}
    """
    with _pm_lock:
        c = _pm_cache
        if c["data"] and time.monotonic() - c["ts"] < _CACHE_TTL:
            return dict(c["data"])

    try:
        import requests as _req
    except ImportError:
        return {}

    result: dict = {}

    for label, slug in _PM_EVENT_SLUGS.items():
        try:
            r = _req.get(f"{_GAMMA_API}/events", params={"slug": slug}, timeout=8)
            r.raise_for_status()
            events = r.json()
            if not events:
                continue
            markets = events[0].get("markets", [])
        except Exception:
            continue

        p_cut_25 = p_cut_50 = p_no_change = None

        for m in markets:
            q = m.get("question", "")
            try:
                ltp = float(m.get("lastTradePrice") or 0) or None
            except (ValueError, TypeError):
                ltp = None
            if ltp is None:
                continue

            # Skip resolved markets (LTP=1.0 means already settled)
            if ltp >= 0.99:
                continue

            if _CUT_50_RE.search(q) and p_cut_50 is None:
                p_cut_50 = ltp
            elif _CUT_25_RE.search(q) and p_cut_25 is None:
                p_cut_25 = ltp
            elif _NO_CHANGE_RE.search(q) and p_no_change is None:
                p_no_change = ltp

        if p_cut_25 is not None and p_cut_50 is not None:
            p_cut_total = p_cut_25 + p_cut_50
        elif p_cut_25 is not None:
            p_cut_total = p_cut_25
        elif p_cut_50 is not None:
            p_cut_total = p_cut_50
        elif p_no_change is not None:
            p_cut_total = 1.0 - p_no_change
        else:
            p_cut_total = None

        result[label] = {
            "p_cut": p_cut_total,
            "p_cut_25": p_cut_25,
            "p_cut_50": p_cut_50,
            "p_no_change": p_no_change,
        }

    with _pm_lock:
        _pm_cache["data"] = result
        _pm_cache["ts"]   = time.monotonic()

    return result


# ── WIRP Curve ─────────────────────────────────────────────────────────────────

_wirp_cache: dict = {"data": None, "ts": 0.0}
_wirp_lock  = threading.Lock()


def get_wirp_curve(force: bool = False) -> list[dict]:
    """
    WIRP-style curve: cumulative expected 25bps cuts by each FOMC meeting.

    FFF WIRP  = (EFFR - post_meeting_rate) / 0.25
                where post_meeting_rate comes from the first no-meeting ZQ month
                after each meeting (proxy_ticker).

    PM WIRP   = accumulated expected rate change from Polymarket per-meeting data:
                E[cuts at M] = P_M(cut25)*1 + P_M(cut50+)*2
                cumulated from March to December.

    Returns list of dicts (one per meeting):
        {
            "label":     "Mar 2026",
            "date":      date(2026, 3, 19),
            "zq_price":  96.36,
            "fff_cuts":  0.12,   # expected cumulative 25bps cuts by this meeting (FFF)
            "pm_cuts":   0.01,   # expected cumulative 25bps cuts by this meeting (PM)
            "gap":       0.11,   # fff_cuts - pm_cuts (+ = FFF more dovish than PM)
            # Per-meeting breakdown (for the table)
            "fff_p_cut": 0.026,
            "pm_p_cut":  0.010,
            "edge_pp":   1.6,
            "signal":    "—",
        }
    """
    with _wirp_lock:
        if not force and _wirp_cache["data"] and time.monotonic() - _wirp_cache["ts"] < _CACHE_TTL:
            return list(_wirp_cache["data"])

    effr         = get_current_effr()
    kalshi_data  = _get_kalshi_probs()   # all 2026 meetings
    pm_data      = _get_fed_pm_probs()   # Polymarket: Mar/Apr only

    kalshi_cumulative  = 0.0
    pm_cumulative      = 0.0
    rows = []

    for meeting in FOMC_MEETINGS:
        label    = meeting["label"]
        ticker   = meeting["ticker"]
        proxy    = meeting["proxy_ticker"]

        # ── ZQ price & WIRP FFF ──────────────────────────────────────────────
        zq_price    = _fetch_zq_price(ticker)
        proxy_price = _fetch_zq_price(proxy) if proxy else None

        if proxy_price is not None:
            post_rate = 100.0 - proxy_price
            fff_cuts  = max(0.0, (effr - post_rate) / 0.25)
        else:
            fff_cuts = None

        # ── Per-meeting P(cut) for table ─────────────────────────────────────
        if zq_price is not None:
            fff_p_cut = _per_meeting_p_cut(
                zq_price, effr,
                meeting["meeting_day"], meeting["month_days"],
                meeting.get("next_ticker"), meeting.get("prev_ticker"),
            )
        else:
            fff_p_cut = None

        # ── WIRP Kalshi ───────────────────────────────────────────────────────
        k = kalshi_data.get(label, {})
        if k.get("p_cut") is not None:
            k25 = k.get("p_cut_25") or 0.0
            k50 = k.get("p_cut_50") or 0.0
            kalshi_cumulative += k25 * 1.0 + k50 * 2.0
            kalshi_cuts  = round(kalshi_cumulative, 4)
            kalshi_p_cut = k["p_cut"]
        else:
            kalshi_cuts  = None
            kalshi_p_cut = None

        # ── WIRP Polymarket ───────────────────────────────────────────────────
        pm = pm_data.get(label, {})
        if pm.get("p_cut") is not None:
            p25 = pm.get("p_cut_25") or 0.0
            p50 = pm.get("p_cut_50") or 0.0
            if p25 == 0.0 and p50 == 0.0:
                p25 = pm["p_cut"]
            pm_cumulative += p25 * 1.0 + p50 * 2.0
            polymarket_cuts  = round(pm_cumulative, 4)
            polymarket_p_cut = pm["p_cut"]
        else:
            polymarket_cuts  = None
            polymarket_p_cut = None

        # ── Primary prediction market ref = Kalshi (fallback Polymarket) ─────
        pm_p_cut = kalshi_p_cut if kalshi_p_cut is not None else polymarket_p_cut
        pm_cuts  = kalshi_cuts  if kalshi_cuts  is not None else polymarket_cuts

        # ── Edge & signal (FFF vs Kalshi) ─────────────────────────────────────
        if fff_p_cut is not None and pm_p_cut is not None:
            edge_pp = (fff_p_cut - pm_p_cut) * 100.0
        else:
            edge_pp = None

        if edge_pp is None:
            signal = "N/A"
        elif abs(edge_pp) < 3:
            signal = "—"
        elif abs(edge_pp) < 8:
            signal = "WATCH"
        elif edge_pp >= 8:
            signal = "BUY"
        else:
            signal = "SELL"

        gap = round(fff_cuts - kalshi_cuts, 4) if (fff_cuts is not None and kalshi_cuts is not None) else None

        rows.append({
            "label":           label,
            "date":            meeting["date"],
            "zq_price":        zq_price,
            "fff_cuts":        fff_cuts,
            "kalshi_cuts":     kalshi_cuts,
            "polymarket_cuts": polymarket_cuts,
            "pm_cuts":         pm_cuts,       # primary ref (Kalshi or PM)
            "gap":             gap,
            "fff_p_cut":       fff_p_cut,
            "kalshi_p_cut":    kalshi_p_cut,
            "polymarket_p_cut": polymarket_p_cut,
            "pm_p_cut":        pm_p_cut,
            "edge_pp":         edge_pp,
            "signal":          signal,
        })

    with _wirp_lock:
        _wirp_cache["data"] = rows
        _wirp_cache["ts"]   = time.monotonic()

    return rows


# ── Legacy alias for arb table ─────────────────────────────────────────────────

def get_arb_table(force: bool = False) -> list[dict]:
    """Alias: returns WIRP rows (same fields as old get_arb_table + WIRP extras)."""
    return get_wirp_curve(force=force)


if __name__ == "__main__":
    print(f"EFFR: {get_current_effr():.2f}%")
    print()
    rows = get_wirp_curve()
    for r in rows:
        fff_c = f"{r['fff_cuts']:.2f}" if r["fff_cuts"] is not None else "N/A"
        pm_c  = f"{r['pm_cuts']:.2f}"  if r["pm_cuts"]  is not None else "N/A"
        gap   = f"{r['gap']:+.2f}"     if r["gap"]       is not None else "N/A"
        fff_p = f"{r['fff_p_cut']*100:.1f}%" if r["fff_p_cut"] is not None else "N/A"
        pm_p  = f"{r['pm_p_cut']*100:.1f}%"  if r["pm_p_cut"]  is not None else "N/A"
        print(f"{r['label']:12} | FFF cuts={fff_c:5} | PM cuts={pm_c:5} | gap={gap:6} | "
              f"FFF P↓={fff_p:7} | PM P↓={pm_p:7} | {r['signal']}")
