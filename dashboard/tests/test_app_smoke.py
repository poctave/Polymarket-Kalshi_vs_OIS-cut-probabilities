"""
Drive the Dash callbacks through the real /_dash-update-component endpoint,
fully offline: network-facing pieces are stubbed.
"""

import json
from datetime import date

import pytest

import api
import feed

MARKET = {
    "condition_id": "0xsmoke", "question": "Will the Fed hike in December?", "slug": "fed-hike-dec",
    "event_title": "Fed December", "end_date": "2026-12-10T00:00:00Z",
    "yes_token": "Y", "no_token": "N", "outcomes": ["Yes", "No"],
    "volume_total": 1e6, "volume_24h": 5e4, "liquidity": 2e4,
    "best_bid": 0.61, "best_ask": 0.63, "last_price": 0.62, "day_change": 0.03,
    "rewards_daily": 30.0, "rewards_min_size": 50.0, "rewards_max_spread_c": 3.5,
    "tick_size": 0.01, "min_order_size": 5, "neg_risk": False,
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api, "ensure_cache", lambda: None)
    monkeypatch.setattr(feed.MarketFeed, "start", lambda self: None)
    monkeypatch.setattr(api, "get_price_history", lambda token, rk="1D": [(1790000000, 0.60), (1790003600, 0.62)])
    api._set_cache_for_tests([MARKET])
    import app as app_module
    return app_module.app.server.test_client()


def _deps(client):
    return json.loads(client.get("/_dash-dependencies").data)


def call(client, output_contains, inputs, state=None):
    dep = next(d for d in _deps(client) if output_contains in d["output"])
    outputs = [dict(zip(("id", "property"), o.rsplit(".", 1))) for o in dep["output"].strip(".").split("...")]
    values = dict(inputs, **(state or {}))

    def pack(items):
        return [{"id": i["id"], "property": i["property"], "value": values.get(f'{i["id"]}.{i["property"]}')}
                for i in items]

    payload = {"output": dep["output"], "outputs": outputs if len(outputs) > 1 else outputs[0],
               "inputs": pack(dep["inputs"]), "state": pack(dep["state"]),
               "changedPropIds": list(inputs)}
    return client.post("/_dash-update-component", json=payload)


def test_index_and_layout(client):
    assert client.get("/").status_code == 200
    layout = client.get("/_dash-layout").data.decode()
    assert "tape" in layout and "fkey-book" in layout


def test_route_both_pages(client):
    for path, marker in (("/", "cmd-go"), ("/fed", "fed-chart")):
        r = call(client, "page.children", {"url.pathname": path})
        assert r.status_code == 200 and marker in r.data.decode()


def test_book_refresh_renders_live_feed(client):
    f = feed.get_feed(MARKET)
    f.handle_event({"event_type": "book", "asset_id": "Y",
                    "bids": [{"price": "0.61", "size": "120"}, {"price": "0.60", "size": "300"}],
                    "asks": [{"price": "0.63", "size": "80"}]})
    f.handle_event({"event_type": "last_trade_price", "asset_id": "Y", "price": "0.62",
                    "size": "2000", "side": "BUY", "timestamp": "1790000000000"})
    r = call(client, "sec-header.children", {"tick.n_intervals": 1, "sel-market.data": MARKET},
             {"book-state.data": {}})
    assert r.status_code == 200, r.data[:500]
    body = r.data.decode()
    assert "61.0" in body and "63.0" in body            # bid / ask in cents
    assert "SCORING BAND" in body and "\\u25c6" in body  # rewards panel + in-band marker

    # Same version again → no redraw
    state = json.loads(body)["response"]["book-state"]["data"]
    r2 = call(client, "sec-header.children", {"tick.n_intervals": 2, "sel-market.data": MARKET},
              {"book-state.data": state})
    assert r2.status_code == 204


def test_book_refresh_without_market(client):
    r = call(client, "sec-header.children", {"tick.n_intervals": 1, "sel-market.data": None},
             {"book-state.data": {}})
    assert r.status_code == 200 and "NO SECURITY LOADED" in r.data.decode()


def test_search_and_price_chart(client):
    r = call(client, "search-results.data", {"cmd.n_submit": 1, "cmd-go.n_clicks": 0},
             {"cmd.value": "fed december"})
    assert r.status_code == 200 and "0xsmoke" in r.data.decode()
    r = call(client, "price-chart.figure", {"hist-range.value": "1D", "tick-slow.n_intervals": 1,
                                            "sel-market.data": MARKET})
    assert r.status_code == 200 and "LIVE MID" in r.data.decode()


def test_status_bar(client):
    r = call(client, "statusbar.children", {"clock-tick.n_intervals": 1}, {"sel-market.data": MARKET})
    assert r.status_code == 200 and "GAMMA" in r.data.decode()


def test_fed_page_renders_snapshot(client, monkeypatch):
    from fed import monitor
    rows = monitor.build_rows(
        date(2026, 9, 29), 3.88, [date(2026, 10, 28), date(2026, 12, 9)],
        {(2026, 10): 3.89, (2026, 11): 4.005, (2026, 12): 4.15, (2027, 1): 4.225},
        {(2026, 10): {"date": date(2026, 10, 28), "buckets": {"HOLD": 0.62, "HIKE25": 0.36}}}, None)
    data = {"as_of": 1790000000, "effr": 3.88, "effr_date": "2026-09-28", "calendar_source": "KALSHI",
            "poly_available": False, "rows": rows}
    import pages.fed as fed_page
    monkeypatch.setattr(fed_page, "snapshot", lambda: {"data": data, "loading": False, "error": ""})
    r = call(client, "fed-chart.figure", {"fed-tick.n_intervals": 1})
    assert r.status_code == 200
    body = r.data.decode()
    assert "28-OCT-26" in body and "CHEAP" in body
