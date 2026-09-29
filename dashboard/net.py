"""
Shared HTTP layer with per-source health tracking.

Every outbound request goes through get(), which records success or a short,
human-readable failure reason per source (GAMMA, CLOB, DATA, KALSHI, ...).
The status bar renders these, so a failing API is visible instead of silently
producing empty panels.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

import requests

SESSION = requests.Session()
SESSION.headers.update({"Accept": "application/json", "User-Agent": "pm-terminal/2.0"})

_health: dict = {}
_lock = threading.Lock()


class NetError(Exception):
    """Raised by get() after the failure has been recorded in the health table."""


def describe(exc: BaseException) -> str:
    """Map a requests exception to a short status-bar message."""
    text = str(exc)
    if "anj.fr" in text:
        # French ISPs answer blocked hosts with the ANJ (gambling regulator) page
        return "BLOCKED BY ISP DNS (ANJ)"
    if isinstance(exc, requests.exceptions.SSLError):
        return "SSL ERROR"
    if isinstance(exc, requests.exceptions.Timeout):
        return "TIMEOUT"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "NO CONNECTION"
    if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None:
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, ValueError):
        return "BAD RESPONSE"
    return type(exc).__name__.upper()


def record(source: str, ok: bool, msg: str = "") -> None:
    with _lock:
        _health[source] = {"ok": ok, "msg": msg, "ts": time.time()}


def health() -> dict:
    with _lock:
        return {k: dict(v) for k, v in _health.items()}


def get(source: str, url: str, params: Optional[dict] = None,
        timeout: float = 10, as_text: bool = False) -> Any:
    try:
        r = SESSION.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.text if as_text else r.json()
    except Exception as exc:
        msg = describe(exc)
        record(source, False, msg)
        raise NetError(f"{source}: {msg}") from exc
    record(source, True)
    return data
