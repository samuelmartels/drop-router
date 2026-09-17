from shapely.geometry import LineString, Point

from drop_router import Poles, Rules, evaluate_chain

ROUTE = LineString([(0, 0), (200, 0)])   # street axis, west -> east
R = Rules()


def own(*pts):
    return Poles.from_xy("own", [f"o{i}" for i in range(len(pts))], [p[0] for p in pts], [p[1] for p in pts])


def ext(*pts):
    return Poles.from_xy("external", [f"e{i}" for i in range(len(pts))], [p[0] for p in pts], [p[1] for p in pts])


def test_direct_within_30m():
    res = evaluate_chain(ROUTE, Point(10, 6), Point(30, 6), [own(), ext()], R)
    assert res.ok and res.reason == "direct"


def test_chain_of_own_poles():
    res = evaluate_chain(ROUTE, Point(0, 6), Point(120, 12), [own((50, 6), (100, 6)), ext()], R)
    assert res.ok and res.n_own == 2 and res.n_external == 0 and res.crossings == 0


def test_gap_over_60m_breaks_chain():
    res = evaluate_chain(ROUTE, Point(0, 6), Point(120, 12), [own((50, 6)), ext()], R)
    assert not res.ok


def test_external_pole_fills_gap_same_side():
    res = evaluate_chain(ROUTE, Point(0, 6), Point(120, 12), [own((50, 6)), ext((100, 6))], R)
    assert res.ok and res.n_external == 1


def test_cross_and_come_back_is_rejected():
    # the only pole that could fill the gap is on the other side of the street
    res = evaluate_chain(ROUTE, Point(0, 6), Point(120, 12), [own((50, 6)), ext((100, -6))], R)
    assert not res.ok


def test_single_crossing_toward_the_point_is_allowed():
    # terminal and poles on the north side, point on the south side: chain, then the lead-in crosses once
    res = evaluate_chain(ROUTE, Point(0, 6), Point(100, -8), [own((50, 6), (100, 6)), ext()], R)
    assert res.ok and res.crossings == 1


def test_mid_span_lead_in():
    # point sits in front of the middle of a 56 m span; 34 m from each pole, 8 m from the span
    res = evaluate_chain(ROUTE, Point(0, 6), Point(78, -8), [own((50, 6), (106, 6)), ext()], Rules(max_lead_in_m=30))
    assert res.ok and res.mid_span
