"""
Polymarket API helpers — read-only, no auth required.

  Gamma  https://gamma-api.polymarket.com   market metadata
  CLOB   https://clob.polymarket.com        orderbook & price history
  Data   https://data-api.polymarket.com    public trade prints

Markets are normalised by parse_market() into flat dicts so the UI never
touches raw Gamma fields. Network failures raise net.NetError and are
recorded in net.health() for the status bar.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Optional

import net
from net import NetError

GAMMA = "https://gamma-api.polymarket.com"
CLOB  = "https://clob.polymarket.com"
DATA  = "https://data-api.polymarket.com"

PAGE_SIZE  = 500
MAX_PAGES  = 40          # up to 20k markets, fetched in 24h-volume order
_CACHE_TTL = 300.0       # seconds


# ── Normalisation ─────────────────────────────────────────────────────────────

def _json_list(raw) -> list:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str) and raw:
        try:
            val = json.loads(raw)
            return val if isinstance(val, list) else []
        except ValueError:
            return []
    return []


def _num(raw, default: float = 0.0) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _opt_num(raw) -> Optional[float]:
    try:
        return None if raw is None or raw == "" else float(raw)
    except (TypeError, ValueError):
        return None


def parse_market(m: dict) -> Optional[dict]:
    """Flatten a Gamma market. Returns None unless it has exactly two CLOB tokens."""
    tokens = _json_list(m.get("clobTokenIds"))
    if len(tokens) != 2:
        return None
    outcomes = _json_list(m.get("outcomes")) or ["Yes", "No"]
    if len(outcomes) != 2:
        outcomes = ["Yes", "No"]

    # Daily reward pool: newer payloads nest it under clobRewards[]
    daily = _num(m.get("rewardsDailyRate"))
    if not daily:
        daily = sum(_num(r.get("rewardsDailyRate")) for r in (m.get("clobRewards") or [])
                    if isinstance(r, dict))

    events = m.get("events") or []
    event_title = events[0].get("title", "") if events and isinstance(events[0], dict) else ""

    return {
        "condition_id":   m.get("conditionId", ""),
        "question":       m.get("question", ""),
        "slug":           m.get("slug", ""),
        "event_title":    event_title,
        "end_date":       m.get("endDate", "") or "",
        "yes_token":      str(tokens[0]),
        "no_token":       str(tokens[1]),
        "outcomes":       [str(o) for o in outcomes],
        "volume_total":   _num(m.get("volumeNum", m.get("volume"))),
        "volume_24h":     _num(m.get("volume24hr")),
        "liquidity":      _num(m.get("liquidityNum", m.get("liquidity"))),
        "best_bid":       _opt_num(m.get("bestBid")),
        "best_ask":       _opt_num(m.get("bestAsk")),
        "last_price":     _opt_num(m.get("lastTradePrice")),
        "day_change":     _opt_num(m.get("oneDayPriceChange")),
        "rewards_daily":  daily,
        "rewards_min_size":     _num(m.get("rewardsMinSize")),
        # Gamma reports max spread in cents (e.g. 3.5 = ±3.5¢ around the midpoint)
        "rewards_max_spread_c": _num(m.get("rewardsMaxSpread")),
        "tick_size":      _num(m.get("orderPriceMinTickSize"), 0.01) or 0.01,
        "min_order_size": _num(m.get("orderMinSize")),
        "neg_risk":       bool(m.get("negRisk")),
    }


def mid_price(market: dict) -> Optional[float]:
    bid, ask = market.get("best_bid"), market.get("best_ask")
    if bid is not None and ask is not None and 0 < bid <= ask:
        return (bid + ask) / 2
    return market.get("last_price")


# ── Market cache ──────────────────────────────────────────────────────────────

_cache: list = []
_cache_ts: float = 0.0
_cache_lock = threading.Lock()
_warming = False


def _fetch_page(offset: int, order: bool = True) -> list:
    params = {"active": "true", "closed": "false", "enableOrderBook": "true",
              "limit": PAGE_SIZE, "offset": offset}
    if order:
        params.update(order="volume24hr", ascending="false")
    data = net.get("GAMMA", f"{GAMMA}/markets", params=params, timeout=15)
    return data if isinstance(data, list) else []


def _warm() -> None:
    global _cache, _cache_ts, _warming
    try:
        seen: set = set()
        result: list = []
        for page in range(MAX_PAGES):
            try:
                rows = _fetch_page(page * PAGE_SIZE)
            except NetError:
                break
            for raw in rows:
                m = parse_market(raw)
                if m and m["condition_id"] not in seen:
                    seen.add(m["condition_id"])
                    result.append(m)
            if len(rows) < PAGE_SIZE:
                break
            # Publish progressively so search works while later pages load
            if page == 0 or page % 5 == 4:
                with _cache_lock:
                    _cache = list(result)
        if result:
            with _cache_lock:
                _cache = result
                _cache_ts = time.monotonic()
    finally:
        with _cache_lock:
            _warming = False


def ensure_cache() -> None:
    """Start a background refresh if the cache is empty or stale."""
    global _warming
    with _cache_lock:
        if _warming or (_cache and time.monotonic() - _cache_ts < _CACHE_TTL):
            return
        _warming = True
    threading.Thread(target=_warm, daemon=True, name="gamma-cache").start()


def cache_status() -> dict:
    with _cache_lock:
        return {"count": len(_cache), "warming": _warming}


def cached_markets() -> list:
    with _cache_lock:
        return list(_cache)


def _set_cache_for_tests(markets: list) -> None:
    global _cache, _cache_ts
    with _cache_lock:
        _cache = list(markets)
        _cache_ts = time.monotonic()


# ── Search ────────────────────────────────────────────────────────────────────

_SLUG_RE = re.compile(r"polymarket\.com/(?:[a-z]{2}/)?(event|market)/([a-z0-9-]+)", re.I)


def parse_lookup(query: str) -> Optional[tuple]:
    """Detect a pasted Polymarket URL or bare slug → (kind, slug)."""
    q = query.strip()
    m = _SLUG_RE.search(q)
    if m:
        return m.group(1).lower(), m.group(2).lower()
    if " " not in q and q.count("-") >= 2 and re.fullmatch(r"[a-z0-9-]+", q.lower()):
        return "any", q.lower()
    return None


def matches(market: dict, terms: list) -> bool:
    hay = " ".join((market["question"], market["event_title"], market["slug"].replace("-", " ")))
    return all(re.search(r"\b" + re.escape(t), hay, re.I) for t in terms)


def lookup_slug(kind: str, slug: str) -> list:
    out: list = []
    if kind in ("market", "any"):
        rows = net.get("GAMMA", f"{GAMMA}/markets", params={"slug": slug}, timeout=10)
        out = [m for m in map(parse_market, rows or []) if m]
    if not out and kind in ("event", "any"):
        events = net.get("GAMMA", f"{GAMMA}/events", params={"slug": slug}, timeout=10)
        for ev in events or []:
            for raw in ev.get("markets", []):
                raw.setdefault("events", [{"title": ev.get("title", "")}])
                m = parse_market(raw)
                if m:
                    out.append(m)
    return out


def search_markets(query: str, limit: int = 40) -> list:
    """
    All-terms keyword search (each term matches a word prefix) over the
    cached market list, sorted by 24h volume. Also accepts a pasted
    Polymarket URL or slug.
    """
    query = (query or "").strip()
    lookup = parse_lookup(query)
    if lookup:
        found = lookup_slug(*lookup)
        if found:
            return found[:limit]

    ensure_cache()
    markets = cached_markets()
    if not markets:
        # Cache still empty: one synchronous page so the first search isn't blank
        markets = [m for m in map(parse_market, _fetch_page(0)) if m]

    terms = query.split()
    hits = [m for m in markets if matches(m, terms)] if terms else markets
    hits.sort(key=lambda m: m["volume_24h"], reverse=True)
    return hits[:limit]


def top_markets(n: int = 20) -> list:
    ensure_cache()
    markets = cached_markets()
    markets.sort(key=lambda m: m["volume_24h"], reverse=True)
    return markets[:n]


# ── Orderbook ─────────────────────────────────────────────────────────────────

def get_orderbook(token_id: str) -> dict:
    data = net.get("CLOB", f"{CLOB}/book", params={"token_id": token_id}, timeout=8)
    return {
        "bids": data.get("bids", []) or [],
        "asks": data.get("asks", []) or [],
        "tick_size": _opt_num(data.get("tick_size")),
        "min_order_size": _opt_num(data.get("min_order_size")),
        "last_trade_price": _opt_num(data.get("last_trade_price")),
    }


# ── Price history ─────────────────────────────────────────────────────────────

# UI range → (CLOB interval, fidelity in minutes). "1m" is one MONTH, "max" is all-time.
HISTORY_RANGES = {
    "1H":  ("1h", 1),
    "6H":  ("6h", 1),
    "1D":  ("1d", 5),
    "1W":  ("1w", 30),
    "1M":  ("1m", 180),
    "MAX": ("max", 720),
}

_hist_cache: dict = {}
_hist_lock = threading.Lock()
_HIST_TTL = 60.0


def get_price_history(token_id: str, range_key: str = "1D") -> list:
    """Return [(unix_ts, price), ...] oldest→newest for one outcome token."""
    interval, fidelity = HISTORY_RANGES.get(range_key, HISTORY_RANGES["1D"])
    key = (token_id, range_key)
    with _hist_lock:
        hit = _hist_cache.get(key)
        if hit and time.monotonic() - hit[0] < _HIST_TTL:
            return hit[1]
    data = net.get("CLOB", f"{CLOB}/prices-history",
                   params={"market": token_id, "interval": interval, "fidelity": fidelity},
                   timeout=12)
    pts = sorted((int(h["t"]), float(h["p"])) for h in data.get("history", [])
                 if "t" in h and "p" in h)
    with _hist_lock:
        _hist_cache[key] = (time.monotonic(), pts)
    return pts


# ── Trades (public prints) ────────────────────────────────────────────────────

def normalize_trade(t: dict, outcomes: list) -> dict:
    price = _num(t.get("price"))
    size  = _num(t.get("size"))
    idx = t.get("outcomeIndex")
    outcome = t.get("outcome") or (outcomes[idx] if isinstance(idx, int) and idx < len(outcomes) else "")
    return {
        "ts":       int(_num(t.get("timestamp"))),
        "side":     str(t.get("side", "")).upper(),
        "outcome":  str(outcome),
        "price":    price,
        "size":     size,
        "notional": price * size,
        "key":      f'{t.get("transactionHash", "")}:{t.get("asset", "")}:{price}:{size}',
    }


def get_trades(condition_id: str, outcomes: list, limit: int = 50) -> list:
    """Most recent public trades for a market, newest first."""
    data = net.get("DATA", f"{DATA}/trades",
                   params={"market": condition_id, "limit": limit}, timeout=8)
    rows = data if isinstance(data, list) else data.get("data", [])
    trades = [normalize_trade(t, outcomes) for t in rows]
    trades.sort(key=lambda t: t["ts"], reverse=True)
    return trades
