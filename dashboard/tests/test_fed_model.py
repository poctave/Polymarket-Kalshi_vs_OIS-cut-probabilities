from datetime import date

import pytest

from fed import model


def test_zq_ticker_month_codes():
    assert model.zq_ticker(2026, 10) == "ZQV26.CBT"
    assert model.zq_ticker(2027, 1) == "ZQF27.CBT"
    assert model.zq_ticker(2026, 12) == "ZQZ26.CBT"


@pytest.mark.parametrize("delta,expected", [
    (0.0,   {"HOLD": 1.0}),
    (12.5,  {"HOLD": 0.5, "HIKE25": 0.5}),
    (-10.0, {"CUT25": 0.4, "HOLD": 0.6}),
    (30.0,  {"HIKE25": 0.8, "HIKE50": 0.2}),
    (-80.0, {"CUT50": 1.0}),          # beyond ±50 collapses into the tail bucket
])
def test_step_distribution(delta, expected):
    dist = model.step_distribution(delta)
    assert sum(dist.values()) == pytest.approx(1.0)
    for b in model.BUCKETS:
        assert dist[b] == pytest.approx(expected.get(b, 0.0))


def test_implied_path_late_meeting_uses_next_month_and_hikes_are_signed():
    # Sep-2026 snapshot: EFFR 3.88, ZQX26 95.995 → Nov 4.005, ZQZ26 95.85 → Dec 4.15
    zq = {(2026, 10): 3.89, (2026, 11): 4.005, (2026, 12): 4.15, (2027, 1): 4.225}
    path = model.implied_path(3.88, [date(2026, 10, 28), date(2026, 12, 9)], lambda y, m: zq.get((y, m)))

    oct_, dec = path
    assert oct_.method == "NEXT"                  # 3 days after the meeting → use Nov
    assert oct_.post == pytest.approx(4.005)
    assert oct_.delta_bp == pytest.approx(12.5)   # a hike, not clipped to zero
    assert oct_.dist["HIKE25"] == pytest.approx(0.5)

    assert dec.method == "AVG"                    # 22 days after → day-weighted Dec contract
    assert dec.pre == pytest.approx(4.005)
    assert dec.post == pytest.approx((31 * 4.15 - 9 * 4.005) / 22)
    assert dec.cum_bp == pytest.approx((dec.post - 3.88) * 100)


def test_implied_path_cut_scenario():
    # Mid-month meeting, contract implies 10bp lower average over the month
    zq = {(2026, 6): 3.80}
    (jun,) = model.implied_path(3.90, [date(2026, 6, 15)], lambda y, m: zq.get((y, m)))
    # 15 days at 3.90, 15 days at post: 30*3.80 = 15*3.90 + 15*post → post 3.70
    assert jun.post == pytest.approx(3.70)
    assert jun.delta_bp == pytest.approx(-20.0)
    assert jun.dist["CUT25"] == pytest.approx(0.8)


def test_implied_path_stops_when_contracts_missing():
    path = model.implied_path(3.9, [date(2026, 6, 15), date(2026, 7, 29)], lambda y, m: None)
    assert path == []


def test_late_meeting_does_not_use_next_month_if_it_also_has_a_meeting():
    zq = {(2026, 1): 3.9, (2026, 2): 3.7}
    meetings = [date(2026, 1, 28), date(2026, 2, 20)]
    first = model.implied_path(3.9, meetings, lambda y, m: zq.get((y, m)))[0]
    assert first.method == "AVG"


def test_normalize_and_expected():
    probs = model.normalize({"HOLD": 0.52, "HIKE25": 0.46, "HIKE50": 0.01, "CUT25": 0.01, "CUT50": None})
    assert sum(probs.values()) == pytest.approx(1.0)
    assert model.expected_bp(probs) == pytest.approx((0.46 * 25 + 0.01 * 50 - 0.01 * 25) / 1.0)
    assert model.expected_bp({}) is None


def test_biggest_gap_sign_means_cheap():
    fff = {"HOLD": 0.5, "HIKE25": 0.5, "CUT25": 0.0, "CUT50": 0.0, "HIKE50": 0.0}
    gap = model.biggest_gap(fff, {"HOLD": 0.52, "HIKE25": 0.40})
    assert gap["bucket"] == "HIKE25"
    assert gap["edge_pp"] == pytest.approx(10.0)   # venue 40¢ vs model 50% → cheap


def test_biggest_gap_ignores_tails_the_model_cannot_price():
    fff = model.step_distribution(9.1)             # HOLD / HIKE25 only
    gap = model.biggest_gap(fff, {"CUT25": 0.18, "HOLD": 0.54, "HIKE25": 0.22})
    assert gap["bucket"] in ("HOLD", "HIKE25")     # never the 0% CUT25 tail
