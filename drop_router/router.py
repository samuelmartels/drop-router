"""End-to-end: terminals + points + poles + streets -> classification per point."""
from __future__ import annotations

from dataclasses import asdict

import networkx as nx
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

from .chain import ChainResult, Poles, Rules, evaluate_chain
from .streets import StreetGraph

CATEGORIES = ("installable_own", "installable_external", "not_installable")


def _category(res: ChainResult) -> str:
    if not res.ok:
        return "not_installable"
    return "installable_external" if res.n_external > 0 else "installable_own"


class DropRouter:
    def __init__(self, streets: StreetGraph, own: Poles, external: Poles, rules: Rules | None = None):
        self.g = streets
        self.pole_sets = [own, external]
        self.rules = rules or Rules()

    def _route(self, src_node: int, dst_node: int, paths: dict, dists: dict):
        if dst_node not in paths:
            return None, None
        return self.g.path_line(paths[dst_node]), dists[dst_node]

    def evaluate_one(self, terminal: Point, point: Point, paths: dict, dists: dict,
                     snap_t: float, terminal_id: str) -> dict:
        r = self.rules
        n_p, snap_p = self.g.nearest_node(point)
        line, d = self._route(None, n_p, paths, dists)
        out = {"terminal": terminal_id, "route_m": None, "category": "not_installable", "reason": "",
               "supports": "", "n_own": 0, "n_external": 0, "crossings": 0, "mid_span": False}
        if line is not None and line.is_empty and d is not None:      # terminal and point snap to the same node
            line, d = LineString([terminal, point]), 0.0
        if line is None or line.is_empty:
            out["reason"] = "no route on the street graph within max_route_m"
            return out
        total = d + snap_t + snap_p
        out["route_m"] = round(total, 1)
        if total > r.max_route_m:
            out["reason"] = f"route {total:.0f} m > {r.max_route_m:.0f} m"
            return out
        full = LineString([terminal.coords[0], *line.coords, point.coords[0]])
        if self.g.crosses_blocking(full) or self.g.crosses_blocking(LineString([terminal, point])):
            out["reason"] = "crosses a blocking street"
            return out
        res = evaluate_chain(line, terminal, point, self.pole_sets, r)
        out.update(category=_category(res), reason=res.reason,
                   supports=";".join(f"{k}:{i}" for k, i in res.supports),
                   n_own=res.n_own, n_external=res.n_external, crossings=res.crossings, mid_span=res.mid_span)
        return out

    def run(self, terminals: pd.DataFrame, points: pd.DataFrame, alternatives: bool = True) -> pd.DataFrame:
        """terminals: id, x, y   ·   points: id, terminal_id, x, y  (metric CRS, same as streets)."""
        r = self.rules
        term_pts = {str(t.id): Point(t.x, t.y) for t in terminals.itertuples()}
        term_nodes = {tid: self.g.nearest_node(p) for tid, p in term_pts.items()}
        term_tree = STRtree(list(term_pts.values())); term_ids = list(term_pts.keys())
        rows = []
        for tid, grp in points.groupby(points.terminal_id.astype(str)):
            if tid not in term_pts:
                for p in grp.itertuples():
                    rows.append({"id": str(p.id), "terminal": tid, "category": "not_installable", "reason": "unknown terminal"})
                continue
            n_t, snap_t = term_nodes[tid]
            dists, paths = nx.single_source_dijkstra(self.g.G, n_t, cutoff=r.max_route_m + 100, weight="weight")
            for p in grp.itertuples():
                pt = Point(p.x, p.y)
                row = {"id": str(p.id)} | self.evaluate_one(term_pts[tid], pt, paths, dists, snap_t, tid)
                row["alternative_terminal"] = ""
                if row["category"] == "not_installable" and alternatives:
                    n_p, snap_p = self.g.nearest_node(pt)
                    d_from, p_from = nx.single_source_dijkstra(self.g.G, n_p, cutoff=r.max_route_m + 50, weight="weight")
                    best = None
                    for k in term_tree.query(pt.buffer(r.max_route_m)):
                        alt_id = term_ids[int(k)]
                        if alt_id == tid:
                            continue
                        n_a, snap_a = term_nodes[alt_id]
                        if n_a not in p_from:
                            continue
                        alt = self.evaluate_one(term_pts[alt_id], pt,
                                                {n_p: p_from[n_a][::-1]}, {n_p: d_from[n_a]}, snap_a, alt_id)
                        if alt["category"] != "not_installable" and (best is None or alt["route_m"] < best["route_m"]):
                            best = alt
                    if best:
                        row.update(best); row["alternative_terminal"] = best["terminal"]; row["terminal"] = tid
                rows.append(row)
        return pd.DataFrame(rows)

    def rules_dict(self) -> dict:
        return asdict(self.rules)
