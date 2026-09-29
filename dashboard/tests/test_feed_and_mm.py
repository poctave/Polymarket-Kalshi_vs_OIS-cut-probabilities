from datetime import datetime, timezone

import pytest

import feed
import mm

MARKET = {"condition_id": "0xabc", "question": "Q", "yes_token": "Y", "no_token": "N",
          "outcomes": ["Yes", "No"], "tick_size": 0.01}


def test_orderbook_snapshot_apply_and_best():
    b = feed.OrderBook()
    b.snapshot([{"price": "0.60", "size": "10"}, {"price": "0.61", "size": "5"}, {"price": "0.5", "size": "0"}],
               [{"price": "0.63", "size": "7"}])
    assert b.best() == (0.61, 0.63)
    b.apply("SELL", "0.62", "3")
    b.apply("BUY", "0.61", "0")          # size 0 removes the level
    bids, asks = b.levels()
    assert bids == [(0.60, 10.0)]
    assert asks == [(0.62, 3.0), (0.63, 7.0)]


def test_feed_handles_ws_events_and_ignores_other_assets():
    f = feed.MarketFeed(MARKET)
    f.handle_event({"event_type": "book", "asset_id": "Y",
                    "bids": [{"price": "0.40", "size": "100"}], "asks": [{"price": "0.42", "size": "50"}]})
    f.handle_event({"event_type": "price_change", "price_changes": [
        {"asset_id": "Y", "side": "BUY", "price": "0.41", "size": "20"},
        {"asset_id": "OTHER", "side": "BUY", "price": "0.99", "size": "1"},
    ]})
    assert f.yes.best() == (0.41, 0.42)
    assert f.no.is_empty
    f.handle_event({"event_type": "last_trade_price", "asset_id": "N", "price": "0.58",
                    "size": "10", "side": "SELL", "timestamp": "1790000000123"})
    spreads, trades = f.history()
    assert trades[0]["outcome"] == "No" and trades[0]["ts"] == 1790000000
    assert spreads and spreads[-1]["mid"] == pytest.approx(0.415)


def test_feeds_are_isolated_per_market():
    """Regression: the old global books let a closing socket write into the next market."""
    a = feed.MarketFeed(MARKET)
    b = feed.MarketFeed(dict(MARKET, condition_id="0xdef", yes_token="Y2", no_token="N2"))
    a.handle_event({"event_type": "book", "asset_id": "Y", "bids": [{"price": "0.3", "size": "1"}], "asks": []})
    assert b.yes.is_empty


def test_stale_socket_messages_are_dropped():
    f = feed.MarketFeed(MARKET)
    f._ws = object()                       # current socket
    f._on_message(object(), '{"event_type":"book","asset_id":"Y","bids":[{"price":"0.3","size":"1"}],"asks":[]}')
    assert f.yes.is_empty
    f._on_message(f._ws, "PONG")           # keepalive ignored without error


def test_trade_dedupe():
    f = feed.MarketFeed(MARKET)
    t = {"ts": 1, "side": "BUY", "outcome": "Yes", "price": 0.5, "size": 1, "notional": 0.5, "key": "k"}
    f.add_trades([t, dict(t)])
    assert len(f.history()[1]) == 1


def test_reaper_stops_idle_feeds(monkeypatch):
    monkeypatch.setattr(feed.MarketFeed, "start", lambda self: None)
    f = feed.get_feed(MARKET)
    feed._reap_once(now=f.last_access + feed.IDLE_TIMEOUT + 1)
    assert f.stopped and f not in feed.active_feeds()


def test_reward_band_uses_cents_around_mid():
    market = {"rewards_daily": 30, "rewards_max_spread_c": 3.5, "rewards_min_size": 50}
    bids = [(0.60, 100), (0.58, 40), (0.55, 500)]
    asks = [(0.62, 80), (0.64, 60), (0.70, 900)]
    v = mm.reward_view(market, bids, asks, 0.60, 0.62)
    assert v["mid"] == pytest.approx(0.61)
    assert (v["lo"], v["hi"]) == (pytest.approx(0.575), pytest.approx(0.645))
    assert v["bid_depth"] == 100          # 0.58 level is under min size, 0.55 outside band
    assert v["ask_depth"] == 140
    assert v["book_spread_c"] == pytest.approx(2.0)
    assert not v["two_sided"]
    assert mm.in_band(0.64, v) and not mm.in_band(0.55, v)


def test_reward_view_two_sided_and_none():
    v = mm.reward_view({"rewards_daily": 5, "rewards_max_spread_c": 2}, [(0.04, 100)], [(0.06, 100)], 0.04, 0.06)
    assert v["two_sided"]
    assert mm.reward_view({"rewards_daily": 0, "rewards_max_spread_c": 0}, [], [], None, None) is None


def test_formatters():
    now = datetime(2026, 9, 29, tzinfo=timezone.utc)
    assert mm.fmt_expiry("2026-10-01T12:00:00Z", now) == "2D 12H"
    assert mm.fmt_expiry("2026-09-01T00:00:00Z", now) == "EXPIRED"
    assert mm.fmt_money(1_234_567) == "$1.23M"
    assert mm.fmt_cents(0.625) == "62.5"
    assert mm.cumulative([(0.6, 1), (0.59, 2)]) == [(0.6, 1, 1), (0.59, 2, 3)]
