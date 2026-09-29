"""
Live market feeds over the Polymarket CLOB websocket.

Each selected market gets its own MarketFeed (books, spread history, trade
tape, websocket thread). Because state lives on the feed object rather than
in module globals, a closing websocket for an old market can never write into
the new market's books, and several browser tabs can watch different markets.

Feeds that nobody has read for IDLE_TIMEOUT seconds are stopped by a reaper.

Market channel: wss://ws-subscriptions-clob.polymarket.com/ws/market
  subscribe   {"type": "market", "assets_ids": [yes, no]}
  events      book | price_change | last_trade_price | tick_size_change
  keepalive   client sends "PING" every 10 s, server answers "PONG"
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from typing import Optional

import websocket  # websocket-client

import api
from net import NetError, describe, record

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
SPREAD_HISTORY_LEN = 3000
TRADE_HISTORY_LEN  = 100
SPREAD_SAMPLE_S    = 0.25
PING_INTERVAL_S    = 10
IDLE_TIMEOUT       = 120
TRADE_POLL_S       = 10     # REST trade polling, only while the websocket is down


# ── OrderBook ─────────────────────────────────────────────────────────────────

class OrderBook:
    """Thread-safe price → size book for one outcome token (sizes in shares)."""

    def __init__(self):
        self._bids: dict = {}
        self._asks: dict = {}
        self._lock = threading.Lock()

    def snapshot(self, bids: list, asks: list) -> None:
        with self._lock:
            self._bids = {float(b["price"]): float(b["size"]) for b in bids if float(b["size"]) > 0}
            self._asks = {float(a["price"]): float(a["size"]) for a in asks if float(a["size"]) > 0}

    def apply(self, side: str, price, size) -> None:
        price, size = float(price), float(size)
        with self._lock:
            book = self._bids if side.upper() == "BUY" else self._asks
            if size <= 0:
                book.pop(price, None)
            else:
                book[price] = size

    def clear(self) -> None:
        with self._lock:
            self._bids.clear()
            self._asks.clear()

    def levels(self, n: int = 12) -> tuple:
        """(bids best→worse, asks best→worse) as [(price, size), ...]."""
        with self._lock:
            bids = sorted(self._bids.items(), reverse=True)[:n]
            asks = sorted(self._asks.items())[:n]
        return bids, asks

    def best(self) -> tuple:
        with self._lock:
            bid = max(self._bids) if self._bids else None
            ask = min(self._asks) if self._asks else None
        return bid, ask

    @property
    def is_empty(self) -> bool:
        with self._lock:
            return not self._bids and not self._asks


# ── MarketFeed ────────────────────────────────────────────────────────────────

class MarketFeed:
    def __init__(self, market: dict):
        self.market = market
        self.yes_token = market["yes_token"]
        self.no_token = market["no_token"]
        self.yes = OrderBook()
        self.no = OrderBook()

        self._lock = threading.Lock()
        self.spread_hist: deque = deque(maxlen=SPREAD_HISTORY_LEN)
        self.trades: deque = deque(maxlen=TRADE_HISTORY_LEN)
        self._trade_keys: set = set()
        self._last_sample = 0.0

        self.version = 0            # bumped on every state change; UI skips redraws if unchanged
        self.connected = False
        self.status = "CONNECTING"
        self.error = ""
        self.msg_count = 0
        self.last_msg = 0.0
        self.tick_size: Optional[float] = market.get("tick_size")
        self.last_access = time.monotonic()

        self._stop = threading.Event()
        self._ws: Optional[websocket.WebSocketApp] = None

    # ---- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True,
                         name=f"feed-{self.market['condition_id'][:10]}").start()

    def stop(self) -> None:
        self._stop.set()
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def _run(self) -> None:
        self._seed()
        threading.Thread(target=self._trade_poller, daemon=True).start()
        backoff = 1.0
        while not self._stop.is_set():
            ws = websocket.WebSocketApp(
                WS_URL,
                on_open=self._on_open,
                on_message=self._on_message,
                on_close=self._on_close,
                on_error=self._on_error,
            )
            self._ws = ws
            started = time.monotonic()
            ws.run_forever(ping_interval=20, ping_timeout=10)
            self._set_connected(False)
            if self._stop.is_set():
                break
            if time.monotonic() - started > 60:
                backoff = 1.0       # connection was healthy; retry fast
            self.status = f"RECONNECT {backoff:.0f}s"
            self._stop.wait(backoff)
            backoff = min(backoff * 2, 30.0)

    def _seed(self) -> None:
        """REST snapshot so panels fill before the websocket book arrives."""
        try:
            for token, book in ((self.yes_token, self.yes), (self.no_token, self.no)):
                data = api.get_orderbook(token)
                book.snapshot(data["bids"], data["asks"])
                if token == self.yes_token and data["tick_size"]:
                    self.tick_size = data["tick_size"]
            self._record_spread(force=True)
        except NetError as exc:
            self.error = str(exc)
        self._refresh_trades_rest()
        self._bump()

    def _refresh_trades_rest(self) -> None:
        try:
            trades = api.get_trades(self.market["condition_id"], self.market["outcomes"])
        except NetError as exc:
            self.error = str(exc)
            return
        self.add_trades(reversed(trades))   # oldest first so newest ends up on top

    def _trade_poller(self) -> None:
        while not self._stop.wait(TRADE_POLL_S):
            if not self.connected:
                self._refresh_trades_rest()

    # ---- websocket callbacks -----------------------------------------------

    def _on_open(self, ws) -> None:
        if ws is not self._ws or self._stop.is_set():
            ws.close()
            return
        ws.send(json.dumps({"type": "market", "assets_ids": [self.yes_token, self.no_token]}))
        self._set_connected(True)
        record("WS", True)

        def pinger():
            while ws is self._ws and self.connected and not self._stop.wait(PING_INTERVAL_S):
                try:
                    ws.send("PING")
                except Exception:
                    return
        threading.Thread(target=pinger, daemon=True).start()

    def _on_message(self, ws, raw: str) -> None:
        if ws is not self._ws or self._stop.is_set():
            return
        if not raw or raw[0] not in "[{":       # "PONG" and other keepalives
            return
        try:
            payload = json.loads(raw)
        except ValueError:
            return
        self.msg_count += 1
        self.last_msg = time.time()
        for ev in payload if isinstance(payload, list) else [payload]:
            if isinstance(ev, dict):
                self.handle_event(ev)

    def _on_close(self, ws, *_) -> None:
        if ws is self._ws:
            self._set_connected(False)

    def _on_error(self, ws, err) -> None:
        if ws is self._ws:
            msg = describe(err) if isinstance(err, Exception) else str(err)
            self.error = f"WS: {msg}"
            record("WS", False, msg)

    def _set_connected(self, value: bool) -> None:
        self.connected = value
        self.status = "LIVE" if value else ("STOPPED" if self._stop.is_set() else "DISCONNECTED")
        self._bump()

    # ---- event handling (public for tests) ---------------------------------

    def _book_for(self, asset: str) -> Optional[OrderBook]:
        if asset == self.yes_token:
            return self.yes
        if asset == self.no_token:
            return self.no
        return None

    def handle_event(self, ev: dict) -> None:
        etype = ev.get("event_type", "")
        if etype == "book":
            book = self._book_for(ev.get("asset_id", ""))
            if book is None:
                return
            book.snapshot(ev.get("bids", []), ev.get("asks", []))
            if book is self.yes:
                self._record_spread()
        elif etype == "price_change":
            touched_yes = False
            for ch in ev.get("price_changes", []):
                book = self._book_for(ch.get("asset_id", ""))
                if book is None or "price" not in ch or "size" not in ch:
                    continue
                book.apply(ch.get("side", ""), ch["price"], ch["size"])
                touched_yes |= book is self.yes
            if touched_yes:
                self._record_spread()
        elif etype == "last_trade_price":
            asset = ev.get("asset_id", "")
            if self._book_for(asset) is None:
                return
            idx = 0 if asset == self.yes_token else 1
            price, size = float(ev.get("price", 0)), float(ev.get("size", 0))
            ts_raw = float(ev.get("timestamp", time.time() * 1000))
            ts = int(ts_raw / 1000) if ts_raw > 1e11 else int(ts_raw)
            self.add_trades([{
                "ts": ts, "side": str(ev.get("side", "")).upper(),
                "outcome": self.market["outcomes"][idx],
                "price": price, "size": size, "notional": price * size,
                "key": f"ws:{asset}:{ts_raw}:{price}:{size}",
            }])
        elif etype == "tick_size_change":
            if ev.get("asset_id") == self.yes_token and ev.get("new_tick_size"):
                self.tick_size = float(ev["new_tick_size"])
        else:
            return
        self._bump()

    def add_trades(self, trades) -> None:
        with self._lock:
            for t in trades:
                if t["key"] in self._trade_keys:
                    continue
                self._trade_keys.add(t["key"])
                self.trades.appendleft(t)
            if len(self._trade_keys) > TRADE_HISTORY_LEN * 4:
                self._trade_keys = {t["key"] for t in self.trades}

    def _record_spread(self, force: bool = False) -> None:
        bid, ask = self.yes.best()
        if bid is None or ask is None or ask <= bid:
            return
        now = time.time()
        point = {"ts": now, "bid": bid, "ask": ask, "mid": (bid + ask) / 2, "spread": ask - bid}
        with self._lock:
            if not force and self.spread_hist and now - self._last_sample < SPREAD_SAMPLE_S:
                self.spread_hist[-1] = point     # throttle by overwriting, never drop the latest state
                return
            self._last_sample = now
            self.spread_hist.append(point)

    def _bump(self) -> None:
        with self._lock:
            self.version += 1

    # ---- reads --------------------------------------------------------------

    def history(self) -> tuple:
        with self._lock:
            return list(self.spread_hist), list(self.trades)


# ── Registry ──────────────────────────────────────────────────────────────────

_feeds: dict = {}
_reg_lock = threading.Lock()
_reaper_started = False


def get_feed(market: dict) -> MarketFeed:
    """Return the running feed for this market, starting one if needed."""
    cid = market["condition_id"]
    with _reg_lock:
        feed = _feeds.get(cid)
        if feed is None or feed.stopped:
            feed = MarketFeed(market)
            _feeds[cid] = feed
            feed.start()
        feed.last_access = time.monotonic()
    _ensure_reaper()
    return feed


def active_feeds() -> list:
    with _reg_lock:
        return [f for f in _feeds.values() if not f.stopped]


def _reap_once(now: Optional[float] = None) -> None:
    now = time.monotonic() if now is None else now
    with _reg_lock:
        idle = [cid for cid, f in _feeds.items() if now - f.last_access > IDLE_TIMEOUT]
        for cid in idle:
            _feeds.pop(cid).stop()


def _ensure_reaper() -> None:
    global _reaper_started
    with _reg_lock:
        if _reaper_started:
            return
        _reaper_started = True

    def loop():
        while True:
            time.sleep(30)
            _reap_once()
    threading.Thread(target=loop, daemon=True, name="feed-reaper").start()
