from datetime import date

import pytest

from fed import monitor, sources


def test_parse_fred_skips_missing_values():
    csv = "observation_date,EFFR\n2026-09-24,3.88\n2026-09-25,3.88\n2026-09-28,.\n"
    assert sources.parse_fred_csv(csv) == (3.88, "2026-09-25")
    assert sources.parse_fred_csv("observation_date,EFFR\n") is None


def test_kalshi_price_uses_dollar_fields():
    # Shape of the live API in Sep 2026: cent fields gone, *_dollars strings present
    m = {"last_price": None, "yes_bid": None, "yes_ask": None,
         "last_price_dollars": "0.4600", "yes_bid_dollars": "0.4500", "yes_ask_dollars": "0.4700"}
    assert sources.kalshi_price(m) == pytest.approx(0.46)
    assert sources.kalshi_price({"last_price_dollars": "0.13", "yes_bid_dollars": "0",
                                 "yes_ask_dollars": "0"}) == pytest.approx(0.13)
    assert sources.kalshi_price({"yes_bid": 20, "yes_ask": 24}) == pytest.approx(0.22)   # legacy cents


def test_parse_kalshi_filters_past_and_maps_buckets():
    events = [
        {"event_ticker": "KXFEDDECISION-26SEP", "strike_date": "2026-09-16T18:00:00Z"},
        {"event_ticker": "KXFEDDECISION-26OCT", "strike_date": "2026-10-28T18:00:00Z"},
    ]
    markets = [
        {"ticker": "KXFEDDECISION-26OCT-H25", "event_ticker": "KXFEDDECISION-26OCT", "status": "active",
         "yes_bid_dollars": "0.46", "yes_ask_dollars": "0.46"},
        {"ticker": "KXFEDDECISION-26OCT-C26", "event_ticker": "KXFEDDECISION-26OCT", "status": "active",
         "yes_bid_dollars": "0.00", "yes_ask_dollars": "0.01"},
        {"ticker": "KXFEDDECISION-26SEP-H25", "event_ticker": "KXFEDDECISION-26SEP", "status": "finalized",
         "yes_bid_dollars": "0.88", "yes_ask_dollars": "0.00"},
    ]
    out = sources.parse_kalshi(events, markets, today=date(2026, 9, 29))
    assert list(out) == [(2026, 10)]
    assert out[(2026, 10)]["date"] == date(2026, 10, 28)
    assert out[(2026, 10)]["buckets"] == {"HIKE25": pytest.approx(0.46), "CUT50": pytest.approx(0.005)}


@pytest.mark.parametrize("q,expected", [
    ("Fed decreases interest rates by 50+ bps after October 2026 meeting?", ((2026, 10), "CUT50")),
    ("Fed decreases interest rates by 25 bps after October 2026 meeting?", ((2026, 10), "CUT25")),
    ("No change in Fed interest rates after December 2026 meeting?", ((2026, 12), "HOLD")),
    ("Fed increases interest rates by 25+ bps after December 2026 meeting?", ((2026, 12), "HIKE25")),
    ("Fed increases interest rates by 50+ bps after the January meeting?", ((2027, 1), "HIKE50")),
    ("Will Bitcoin hit $150k in October 2026?", None),
])
def test_classify_pm_question(q, expected):
    assert sources.classify_pm_question(q, end_date="2027-01-27T00:00:00Z") == expected


def test_build_rows_joins_sources_and_flags_gaps():
    meetings = [date(2026, 10, 28), date(2026, 12, 9)]
    zq = {(2026, 10): 3.89, (2026, 11): 4.005, (2026, 12): 4.15, (2027, 1): 4.225}
    kalshi = {
        (2026, 10): {"date": meetings[0], "buckets": {"HOLD": 0.62, "HIKE25": 0.36, "CUT25": 0.01, "CUT50": 0.005, "HIKE50": 0.005}},
        (2026, 12): {"date": meetings[1], "buckets": {"HOLD": 0.22, "HIKE25": 0.75, "HIKE50": 0.03}},
    }
    rows = monitor.build_rows(date(2026, 9, 29), 3.88, meetings, zq, kalshi, poly=None)

    oct_, dec = rows
    assert oct_["days"] == 29
    assert oct_["fff_bp"] == pytest.approx(12.5)
    assert oct_["gap"]["venue"] == "KALSHI"
    assert oct_["gap"]["bucket"] in ("HIKE25", "HOLD")
    assert abs(oct_["gap"]["edge_pp"]) == pytest.approx(14.0)   # 50% model vs 36¢ / 62¢ → flagged
    assert oct_["flag"] is True
    assert dec["kalshi_cum"] == pytest.approx(oct_["kalshi_bp"] + dec["kalshi_bp"])
    assert dec["poly_cum"] is None


def test_flags_limited_to_near_meetings():
    meetings = [date(2026, 10, 28), date(2026, 12, 9), date(2027, 1, 27)]
    zq = {(2026, 10): 3.89, (2026, 11): 4.005, (2026, 12): 4.155, (2027, 1): 4.225, (2027, 2): 4.345}
    far = {"date": meetings[2], "buckets": {"HOLD": 0.9, "HIKE25": 0.1}}   # huge gap vs model
    rows = monitor.build_rows(date(2026, 9, 29), 3.88, meetings, zq, {(2027, 1): far}, None)
    assert abs(rows[2]["gap"]["edge_pp"]) > monitor.GAP_FLAG_PP
    assert rows[2]["flag"] is False
