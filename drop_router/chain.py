"""Support-chain evaluation: can a drop cable be strung from a terminal to a point?

The route is a polyline that follows the street axis (see routing.py). Poles near the route
become candidate supports. The chain must satisfy, for every consecutive pair of supports:

* span  <= rules.max_span_m
* the final segment (last support -> point) <= rules.max_lead_in_m, measured straight-line
* the chain may change street side ONCE, toward the side of the point, and never back
* the lead-in may leave from a pole or from the MIDDLE of a span (mid-span derivation)
* a support beyond the point (up to max_span_m from it) may close the chain

Own poles are preferred: the search minimises the number of external poles used.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree


@dataclass
class Rules:
    max_span_m: float = 60.0          # any support -> next support
    max_lead_in_m: float = 30.0       # last support (or mid-span) -> point
    direct_m: float = 30.0            # terminal -> point with no support at all
    max_route_m: float = 150.0        # total route length terminal -> point
    pole_snap_m: float = 15.0         # pole must be within this distance of the route axis
    side_neutral_m: float = 1.0       # |offset| below this = on the axis, no side


@dataclass
class Poles:
    """Poles of one kind (own or external) with a spatial index aligned to `ids`."""
    kind: str
    ids: np.ndarray
    tree: STRtree

    @classmethod
    def from_xy(cls, kind: str, ids, xs, ys) -> "Poles":
        pts = shapely.points(np.c_[np.asarray(xs, float), np.asarray(ys, float)])
        return cls(kind, np.asarray(ids).astype(str), STRtree(pts))


@dataclass
class ChainResult:
    ok: bool
    supports: list = field(default_factory=list)   # [(kind, id), ...] in order from the terminal
    n_external: int = 0
    n_own: int = 0
    crossings: int = 0
    mid_span: bool = False
    reason: str = ""


def _sides(route: LineString, xy: np.ndarray, neutral_m: float):
    """Chainage and side (+1 / -1 / 0) of points relative to the route direction."""
    if len(xy) == 0:
        return np.zeros(0), np.zeros(0, dtype=int)
    pts = shapely.points(xy)
    ch = shapely.line_locate_point(route, pts)
    L = float(route.length)
    a = shapely.line_interpolate_point(route, np.clip(ch - 0.5, 0, L))
    b = shapely.line_interpolate_point(route, np.clip(ch + 0.5, 0, L))
    tx, ty = shapely.get_x(b) - shapely.get_x(a), shapely.get_y(b) - shapely.get_y(a)
    q = shapely.line_interpolate_point(route, ch)
    vx, vy = xy[:, 0] - shapely.get_x(q), xy[:, 1] - shapely.get_y(q)
    norm = np.hypot(tx, ty)
    norm[norm == 0] = 1.0
    off = (tx * vy - ty * vx) / norm
    return ch, np.where(np.abs(off) < neutral_m, 0, np.sign(off)).astype(int)


def evaluate_chain(route: LineString, terminal: Point, point: Point,
                   pole_sets: list[Poles], rules: Rules) -> ChainResult:
    if route is None or route.is_empty or route.length <= 0:
        return ChainResult(False, reason="no route")

    pos_t, pos_p = float(route.project(terminal)), float(route.project(point))
    sign = 1
    if pos_t > pos_p:
        pos_t, pos_p, sign = pos_p, pos_t, -1
    if pos_p - pos_t <= rules.direct_m:
        return ChainResult(True, reason="direct")

    _, s_tp = _sides(route, np.array([[terminal.x, terminal.y], [point.x, point.y]]), rules.side_neutral_m)
    side_t, side_p = int(s_tp[0]) * sign, int(s_tp[1]) * sign
    px, py = point.x, point.y

    # candidates on the route between terminal and point: (chainage, kind, side, x, y, id)
    buf = route.buffer(rules.pole_snap_m)
    cand = []
    for ps in pole_sets:
        idx = np.asarray(ps.tree.query(buf), dtype=int)
        if idx.size == 0:
            continue
        geoms = ps.tree.geometries.take(idx)
        ok = shapely.distance(route, geoms) <= rules.pole_snap_m
        if not ok.any():
            continue
        xy = shapely.get_coordinates(geoms[ok])
        ch, side = _sides(route, xy, rules.side_neutral_m)
        for c, s, (x, y), pid in zip(ch, side, xy, ps.ids[idx[ok]]):
            if pos_t <= c <= pos_p:
                cand.append((float(c), ps.kind, int(s) * sign, float(x), float(y), str(pid)))
    cand.sort(key=lambda t: t[0])

    # supports beyond the point (within one span of it): for mid-span / closing the chain
    seen = {(round(c[3], 2), round(c[4], 2)) for c in cand}
    extras = []
    pbuf = point.buffer(rules.max_span_m)
    for ps in pole_sets:
        idx = np.asarray(ps.tree.query(pbuf), dtype=int)
        if idx.size == 0:
            continue
        geoms = ps.tree.geometries.take(idx)
        xy = shapely.get_coordinates(geoms)
        _, side = _sides(route, xy, rules.side_neutral_m)
        for (x, y), s, pid in zip(xy, side, ps.ids[idx]):
            if (round(float(x), 2), round(float(y), 2)) in seen or math.hypot(x - px, y - py) > rules.max_span_m:
                continue
            extras.append((ps.kind, int(s) * sign, float(x), float(y), str(pid)))
    if not cand and not extras:
        return ChainResult(False, reason="no supports near the route")

    def d_point(x, y):
        return math.hypot(x - px, y - py)

    def d_span(x1, y1, x2, y2):
        dx, dy = x2 - x1, y2 - y1
        l2 = dx * dx + dy * dy
        t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / l2))
        return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy)), t

    def can_move(side_now, side_new, crossed):
        """(allowed, this move crosses the street)"""
        if side_now == 0 or side_new == 0 or side_now == side_new:
            return True, False
        if crossed or (side_p != 0 and side_new != side_p):
            return False, False
        return True, True

    def done(chain, n_ext, crossed, side_now, mid, extra=None):
        sup = [(cand[i][1], cand[i][5]) for i in chain] + ([extra] if extra else [])
        n_cross = int(crossed) + (0 if side_now in (0, side_p) or side_p == 0 else 1)
        return ChainResult(True, sup, n_ext, len(sup) - n_ext, n_cross, mid)

    heap = [(0, pos_t, side_t, False, [])]
    visited = {}
    while heap:
        n_ext, pos, side_now, crossed, chain = heapq.heappop(heap)
        at_pole = bool(chain)
        if at_pole:
            cx, cy = cand[chain[-1]][3], cand[chain[-1]][4]
            if d_point(cx, cy) <= rules.max_lead_in_m and can_move(side_now, side_p, crossed)[0]:
                return done(chain, n_ext, crossed, side_now, False)
            for kind, e_side, ex, ey, eid in extras:
                if math.hypot(ex - cx, ey - cy) > rules.max_span_m:
                    continue
                ok, cross = can_move(side_now, e_side, crossed)
                if not ok or cross:
                    continue
                side2 = e_side if e_side != 0 else side_now
                if not can_move(side2, side_p, crossed)[0]:
                    continue
                dd, t = d_span(cx, cy, ex, ey)
                direct = d_point(ex, ey) <= rules.max_lead_in_m
                if direct or (0.0 < t < 1.0 and dd <= rules.max_lead_in_m):
                    return done(chain, n_ext + (kind == "external"), crossed, side2, not direct, (kind, eid))
        for i, (c, kind, c_side, x, y, pid) in enumerate(cand):
            if c <= pos or c - pos > rules.max_span_m:
                continue
            ok, cross = can_move(side_now, c_side, crossed)
            if not ok:
                continue
            crossed2 = crossed or cross
            side2 = c_side if c_side != 0 else side_now
            n2 = n_ext + (kind == "external")
            if at_pole and pos < pos_p < c and not cross:
                dd, t = d_span(cand[chain[-1]][3], cand[chain[-1]][4], x, y)
                if 0.0 < t < 1.0 and dd <= rules.max_lead_in_m and can_move(side2, side_p, crossed2)[0]:
                    return done(chain + [i], n2, crossed2, side2, True)
            key = (i, side2, crossed2)
            if key in visited and visited[key] <= n2:
                continue
            visited[key] = n2
            heapq.heappush(heap, (n2, c, side2, crossed2, chain + [i]))
    return ChainResult(False, reason="chain broken: span, lead-in or side rule")
