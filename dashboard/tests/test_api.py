import json

import pytest

import api
import net


def raw_market(**kw):
    m = {
        "conditionId": "0xabc", "question": "Will the Fed hike rates in December?",
        "slug": "fed-hike-december", "endDate": "2026-12-10T00:00:00Z",
        "clobTokenIds": json.dumps(["111", "222"]), "outcomes": json.dumps(["Yes", "No"]),
        "volume": "123456.7", "volume24hr": 5000, "liquidity": "8000",
        "bestBid": 0.61, "bestAsk": 0.63, "lastTradePrice": 0.62,
        "rewardsMinSize": 50, "rewardsMaxSpread": 3.5,
        "clobRewards": [{"rewardsDailyRate": 25}, {"rewardsDailyRate": 5}],
        "orderPriceMinTickSize": 0.01, "events": [{"title": "Fed December decision"}],
    }
    m.update(kw)
    return m


def test_parse_market_normalises_fields():
    m = api.parse_market(raw_market())
    assert (m["yes_token"], m["no_token"]) == ("111", "222")
    assert m["volume_total"] == pytest.approx(123456.7)
    assert m["volume_24h"] == 5000
    assert m["rewards_daily"] == 30               # summed from clobRewards
    assert m["rewards_max_spread_c"] == 3.5        # cents, not dollars
    assert m["event_title"] == "Fed December decision"
    assert api.mid_price(m) == pytest.approx(0.62)


def test_parse_market_rejects_non_binary():
    assert api.parse_market(raw_market(clobTokenIds=json.dumps(["1", "2", "3"]))) is None
    assert api.parse_market(raw_market(clobTokenIds="")) is None


def test_top_level_daily_rate_wins():
    assert api.parse_market(raw_market(rewardsDailyRate=12))["rewards_daily"] == 12


def test_search_matches_all_terms_as_word_prefixes():
    a = api.parse_market(raw_market())
    b = api.parse_market(raw_market(conditionId="0xdef", question="Bitcoin above 150k on Friday?",
                                    slug="btc-150k", volume24hr=9000, events=[]))
    api._set_cache_for_tests([a, b])
    assert [m["condition_id"] for m in api.search_markets("fed dec")] == ["0xabc"]
    assert [m["condition_id"] for m in api.search_markets("bitcoin")] == ["0xdef"]
    assert api.search_markets("ederal") == []       # prefix match, not substring
    assert [m["condition_id"] for m in api.search_markets("")] == ["0xdef", "0xabc"]   # by 24h vol


@pytest.mark.parametrize("q,expected", [
    ("https://polymarket.com/event/fed-decision-in-october", ("event", "fed-decision-in-october")),
    ("https://polymarket.com/market/will-btc-hit-150k", ("market", "will-btc-hit-150k")),
    ("fed-decision-in-october", ("any", "fed-decision-in-october")),
    ("fed october", None),
])
def test_parse_lookup(q, expected):
    assert api.parse_lookup(q) == expected


def test_history_ranges_use_month_and_max_correctly():
    assert api.HISTORY_RANGES["1M"][0] == "1m"
    assert api.HISTORY_RANGES["MAX"][0] == "max"
    assert api.HISTORY_RANGES["1H"][1] == 1          # 1-minute fidelity for the 1h view


def test_normalize_trade_from_data_api():
    t = api.normalize_trade({"side": "BUY", "price": 0.62, "size": 100, "timestamp": 1790000000,
                             "outcomeIndex": 1, "transactionHash": "0x1", "asset": "222"}, ["Yes", "No"])
    assert t["outcome"] == "No"
    assert t["notional"] == pytest.approx(62.0)
    assert t["ts"] == 1790000000


def test_net_describe_flags_anj_block():
    import requests
    exc = requests.exceptions.SSLError("hostname 'clob.polymarket.com' doesn't match either of '*.anj.fr', 'anj.fr'")
    assert net.describe(exc) == "BLOCKED BY ISP DNS (ANJ)"
