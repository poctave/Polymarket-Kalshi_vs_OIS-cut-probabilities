"""
Data sources for the FED page: FRED (EFFR), Yahoo (CBOT ZQ futures),
Kalshi (meeting calendar + outcome prices) and Polymarket (outcome prices).

Everything returns plain dicts keyed by (year, month) of the meeting so the
sources can be joined without caring about exact day conventions.
"""

from __future__ import annotations

import calendar
import concurrent.futures
import re
import threading
import time
from datetime import date, datetime
from typing import Optional

import api
import net
from fed.model import zq_ticker

FRED_EFFR = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=EFFR"
KALSHI    = "https://api.elections.kalshi.com/trade-api/v2"
SERIES    = "KXFEDDECISION"

# Fallback when Kalshi is unreachable: FOMC decision days (second day of each meeting).
# 2026 from federalreserve.gov; 2027 from Kalshi strike dates (Sep 2026).
FALLBACK_MEETINGS = [
    date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2026, 6, 17),
    date(2026, 7, 29), date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9),
    date(2027, 1, 27), date(2027, 3, 17), date(2027, 4, 28), date(2027, 6, 9),
    date(2027, 7, 28), date(2027, 9, 15), date(2027, 10, 27), date(2027, 12, 8),
]

KALSHI_SUFFIX = {"C26": "CUT50", "C25": "CUT25", "H0": "HOLD", "H25": "HIKE25", "H26": "HIKE50"}


# ── EFFR (FRED) ───────────────────────────────────────────────────────────────

def parse_fred_csv(text: str) -> Optional[tuple]:
    """Last numeric observation → (rate %, 'YYYY-MM-DD'). FRED marks gaps with '.'."""
    for line in reversed(text.strip().splitlines()[1:]):
        parts = line.split(",")
        if len(parts) == 2:
            try:
                return float(parts[1]), parts[0]
            except ValueError:
                continue
    return None


def get_effr() -> Optional[tuple]:
    try:
        return parse_fred_csv(net.get("FRED", FRED_EFFR, timeout=10, as_text=True))
    except net.NetError:
        return None


# ── ZQ futures (Yahoo) ────────────────────────────────────────────────────────

_zq_cache: dict = {}
_zq_lock = threading.Lock()
_ZQ_TTL = 300.0


def _fetch_zq(ticker: str) -> Optional[float]:
    import yfinance as yf   # slow import; only needed here
    try:
        price = float(yf.Ticker(ticker).fast_info.last_price)
        if price != price or price <= 0:    # NaN / missing
            return None
        return price
    except Exception:
        return None


def get_zq_rates(months: list) -> dict:
    """{(year, month): implied avg rate %} for months with a quote."""
    now = time.monotonic()
    todo = []
    with _zq_lock:
        for ym in months:
            hit = _zq_cache.get(ym)
            if not hit or now - hit[0] > _ZQ_TTL:
                todo.append(ym)
    if todo:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
            prices = dict(zip(todo, ex.map(lambda ym: _fetch_zq(zq_ticker(*ym)), todo)))
        with _zq_lock:
            for ym, p in prices.items():
                _zq_cache[ym] = (time.monotonic(), p)
        got = sum(p is not None for p in prices.values())
        net.record("CME", got > 0, "" if got else "NO ZQ QUOTES")
    with _zq_lock:
        return {ym: 100.0 - _zq_cache[ym][1] for ym in months
                if ym in _zq_cache and _zq_cache[ym][1] is not None}


# ── Kalshi ────────────────────────────────────────────────────────────────────

def kalshi_price(m: dict) -> Optional[float]:
    """Mid of the YES bid/ask in dollars; falls back to last trade, then legacy cent fields."""
    def dollars(key):
        v = m.get(f"{key}_dollars")
        if v not in (None, ""):
            try:
                return float(v)
            except ValueError:
                return None
        v = m.get(key)                       # legacy integer cents
        return float(v) / 100.0 if isinstance(v, (int, float)) else None

    bid, ask, last = dollars("yes_bid"), dollars("yes_ask"), dollars("last_price")
    if bid is not None and ask is not None and 0 < ask and bid <= ask:
        return (bid + ask) / 2
    return last


def _kalshi_paged(path: str, key: str, params: dict) -> list:
    out, cursor = [], None
    for _ in range(10):
        p = dict(params, limit=200)
        if cursor:
            p["cursor"] = cursor
        data = net.get("KALSHI", f"{KALSHI}/{path}", params=p, timeout=12)
        out.extend(data.get(key, []))
        cursor = data.get("cursor")
        if not cursor:
            break
    return out


def parse_kalshi(events: list, markets: list, today: date) -> dict:
    """{(y, m): {"date": date, "event": ticker, "buckets": {bucket: price}}} for future meetings."""
    result: dict = {}
    for ev in events:
        try:
            d = datetime.fromisoformat(ev["strike_date"].replace("Z", "+00:00")).date()
        except (KeyError, ValueError):
            continue
        if d < today:
            continue
        result[(d.year, d.month)] = {"date": d, "event": ev.get("event_ticker", ""), "buckets": {}}
    by_event = {v["event"]: v for v in result.values()}
    for m in markets:
        ev = by_event.get(m.get("event_ticker", ""))
        if ev is None or m.get("status") in ("settled", "finalized"):
            continue
        bucket = KALSHI_SUFFIX.get(m.get("ticker", "").rsplit("-", 1)[-1])
        if bucket:
            ev["buckets"][bucket] = kalshi_price(m)
    return result


def get_kalshi(today: date) -> Optional[dict]:
    try:
        events = _kalshi_paged("events", "events", {"series_ticker": SERIES})
        markets = _kalshi_paged("markets", "markets", {"series_ticker": SERIES, "status": "open"})
    except net.NetError:
        return None
    return parse_kalshi(events, markets, today)


# ── Polymarket ────────────────────────────────────────────────────────────────

_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_PM_MEETING_RE = re.compile(
    r"\bafter\s+(?:the\s+)?(" + "|".join(_MONTHS) + r")\s*(\d{4})?\s+meeting", re.I)
_PM_RULES = [
    ("CUT50",  re.compile(r"decrease.*?\b50\+?\s*bps?", re.I)),
    ("CUT25",  re.compile(r"decrease.*?\b25\s*bps?", re.I)),
    ("HIKE50", re.compile(r"increase.*?\b50\+?\s*bps?", re.I)),
    ("HIKE25", re.compile(r"increase.*?\b25\+?\s*bps?", re.I)),
    ("HOLD",   re.compile(r"\bno change\b", re.I)),
]


def classify_pm_question(question: str, end_date: str = "") -> Optional[tuple]:
    """'Fed decreases interest rates by 25 bps after October 2026 meeting?' → ((2026, 10), 'CUT25')."""
    if "fed" not in question.lower() and "interest rate" not in question.lower():
        return None
    m = _PM_MEETING_RE.search(question)
    if not m:
        return None
    month = _MONTHS[m.group(1).lower()]
    year = int(m.group(2)) if m.group(2) else (int(end_date[:4]) if end_date[:4].isdigit() else None)
    if year is None:
        return None
    for bucket, rx in _PM_RULES:
        if rx.search(question):
            return (year, month), bucket
    return None


def parse_polymarket(markets: list) -> dict:
    """{(y, m): {bucket: price}} from normalised api markets."""
    out: dict = {}
    for mkt in markets:
        hit = classify_pm_question(mkt["question"], mkt.get("end_date", ""))
        if not hit:
            continue
        ym, bucket = hit
        price = api.mid_price(mkt)
        if price is not None:
            out.setdefault(ym, {}).setdefault(bucket, price)
    return out


def get_polymarket() -> Optional[dict]:
    """Fed decision markets found in the shared Gamma market cache (None while unavailable)."""
    api.ensure_cache()
    markets = api.cached_markets()
    if not markets:
        return None
    return parse_polymarket(markets)
