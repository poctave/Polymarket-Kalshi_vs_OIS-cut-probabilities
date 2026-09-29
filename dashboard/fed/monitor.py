"""
FED monitor: joins FFF-implied, Kalshi and Polymarket views per FOMC meeting.

snapshot() never blocks: it returns the last computed result and kicks off a
background refresh when that result is older than REFRESH_S.
"""

from __future__ import annotations

import threading
import time
from datetime import date, datetime, timezone
from typing import Optional

from fed import model, sources

REFRESH_S = 300.0
HORIZON = 8           # meetings shown
GAP_FLAG_PP = 8.0     # |edge| that gets highlighted
FLAG_MEETINGS = 2     # beyond this, chained-futures error and term premium swamp the signal


def build_rows(today: date, effr: Optional[float], meetings: list, zq: dict,
               kalshi: Optional[dict], poly: Optional[dict]) -> list:
    path = model.implied_path(effr, meetings, lambda y, m: zq.get((y, m))) if effr is not None else []
    implied = {(im.date.year, im.date.month): im for im in path}

    rows = []
    k_cum = p_cum = 0.0
    k_ok = p_ok = True       # cumulative sums are only valid while every earlier meeting is quoted
    for i, d in enumerate(meetings):
        ym = (d.year, d.month)
        im = implied.get(ym)

        k_raw = (kalshi or {}).get(ym, {}).get("buckets", {})
        k_probs = model.normalize(k_raw)
        k_exp = model.expected_bp(k_probs)
        k_ok = k_ok and k_exp is not None
        k_cum = k_cum + k_exp if k_ok else k_cum

        p_raw = (poly or {}).get(ym, {})
        p_probs = model.normalize(p_raw) if len(p_raw) >= 2 else {}
        p_exp = model.expected_bp(p_probs)
        p_ok = p_ok and p_exp is not None
        p_cum = p_cum + p_exp if p_ok else p_cum

        gaps = []
        if im:
            for venue, raw in (("KALSHI", k_raw), ("POLY", p_raw)):
                g = model.biggest_gap(im.dist, raw)
                if g:
                    g["venue"] = venue
                    gaps.append(g)
        top_gap = max(gaps, key=lambda g: abs(g["edge_pp"]), default=None)

        rows.append({
            "date": d,
            "days": (d - today).days,
            "zq_rate": zq.get(ym),
            "method": im.method if im else None,
            "fff_bp": im.delta_bp if im else None,
            "fff_cum": im.cum_bp if im else None,
            "fff_dist": im.dist if im else {},
            "kalshi_bp": k_exp,
            "kalshi_cum": k_cum if k_ok else None,
            "kalshi_probs": k_probs,
            "kalshi_raw": k_raw,
            "poly_bp": p_exp,
            "poly_cum": p_cum if p_ok else None,
            "poly_probs": p_probs,
            "poly_raw": p_raw,
            "gap": top_gap,
            "flag": bool(i < FLAG_MEETINGS and top_gap and abs(top_gap["edge_pp"]) >= GAP_FLAG_PP),
        })
    return rows


def compute(today: Optional[date] = None) -> dict:
    today = today or datetime.now(timezone.utc).date()
    effr = sources.get_effr()
    kalshi = sources.get_kalshi(today)

    if kalshi:
        meetings = sorted(v["date"] for v in kalshi.values())
    else:
        meetings = [d for d in sources.FALLBACK_MEETINGS if d >= today]
    meetings = meetings[:HORIZON]

    months = set()
    for d in meetings:
        months.add((d.year, d.month))
        months.add((d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1))
    zq = sources.get_zq_rates(sorted(months))
    poly = sources.get_polymarket()

    return {
        "as_of": time.time(),
        "effr": effr[0] if effr else None,
        "effr_date": effr[1] if effr else None,
        "calendar_source": "KALSHI" if kalshi else "FALLBACK",
        "poly_available": poly is not None,
        "rows": build_rows(today, effr[0] if effr else None, meetings, zq, kalshi, poly),
    }


_state: dict = {"data": None, "ts": 0.0, "running": False, "error": ""}
_lock = threading.Lock()


def _refresh() -> None:
    try:
        data = compute()
        with _lock:
            _state.update(data=data, ts=time.monotonic(), error="")
    except Exception as exc:        # keep the last good snapshot on screen
        with _lock:
            _state["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        with _lock:
            _state["running"] = False


def snapshot(force: bool = False) -> dict:
    with _lock:
        stale = force or _state["data"] is None or time.monotonic() - _state["ts"] > REFRESH_S
        if stale and not _state["running"]:
            _state["running"] = True
            threading.Thread(target=_refresh, daemon=True, name="fed-refresh").start()
        return {"data": _state["data"], "loading": _state["running"], "error": _state["error"]}
