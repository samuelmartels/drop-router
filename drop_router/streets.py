"""Street network -> routable graph.

Input: a GeoDataFrame of street centrelines in a METRIC CRS. Optional boolean columns:
* ``blocking``  – the street can never be crossed (e.g. dual carriageway with a median)
* ``minor``     – footpaths / service ways that do not count as streets

Lines are densified every ``step_m`` metres so that terminals, poles and points snap close
to the axis; nodes closer than ``bridge_m`` are joined so that small digitising gaps do not
break the graph. The nodes must be topologically connected at intersections beforehand
(most OSM extracts are; if not, node the network first, e.g. with ``shapely.node``).
"""
from __future__ import annotations

import math

import networkx as nx
import numpy as np
import shapely
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree


class StreetGraph:
    def __init__(self, gdf, step_m: float = 5.0, bridge_m: float = 12.0):
        self.gdf = gdf.reset_index(drop=True)
        self.geoms = self.gdf.geometry.values
        self.blocking = (self.gdf["blocking"].fillna(False).astype(bool).values if "blocking" in self.gdf
                         else np.zeros(len(self.gdf), dtype=bool))
        self.minor = (self.gdf["minor"].fillna(False).astype(bool).values if "minor" in self.gdf
                      else np.zeros(len(self.gdf), dtype=bool))
        self.street_tree = STRtree(self.geoms)
        self.G = nx.Graph()
        coord_id, coords, edges = {}, [], []

        def nid(x, y):
            key = (round(x, 3), round(y, 3))
            if key not in coord_id:
                coord_id[key] = len(coords)
                coords.append(key)
            return coord_id[key]

        for si, geom in enumerate(self.geoms):
            parts = geom.geoms if geom.geom_type == "MultiLineString" else [geom]
            for seg in parts:
                if seg.is_empty or seg.length == 0:
                    continue
                n = max(1, int(math.ceil(seg.length / step_m)))
                pts = [seg.interpolate(d) for d in np.linspace(0, seg.length, n + 1)]
                prev = nid(pts[0].x, pts[0].y)
                for p in pts[1:]:
                    cur = nid(p.x, p.y)
                    if cur != prev:
                        (x1, y1), (x2, y2) = coords[prev], coords[cur]
                        edges.append((prev, cur, math.hypot(x2 - x1, y2 - y1), si))
                    prev = cur
        for i, (x, y) in enumerate(coords):
            self.G.add_node(i, x=x, y=y)
        for u, v, w, si in edges:
            if not self.G.has_edge(u, v) or w < self.G[u][v]["weight"]:
                self.G.add_edge(u, v, weight=w, street=si)
        self.coords = coords
        self.node_pts = shapely.points(np.array(coords))
        self.node_tree = STRtree(self.node_pts)
        for i, p in enumerate(self.node_pts):                       # micro-bridges
            for j in self.node_tree.query(p.buffer(bridge_m)):
                j = int(j)
                if j != i and not self.G.has_edge(i, j):
                    d = float(p.distance(self.node_pts[j]))
                    if 0 < d <= bridge_m:
                        self.G.add_edge(i, j, weight=d, street=-1)

    def nearest_node(self, pt: Point):
        i = int(self.node_tree.nearest(pt))
        return i, float(pt.distance(self.node_pts[i]))

    def path_line(self, path) -> LineString:
        seq = []
        for n in path:
            xy = self.coords[n]
            if not seq or xy != seq[-1]:
                seq.append(xy)
        return LineString(seq) if len(seq) >= 2 else LineString()

    def crosses_blocking(self, line: LineString, eps: float = 2.0) -> bool:
        """Does the line cross a blocking street (other than the streets it runs along)?"""
        if line.is_empty:
            return False
        idx = np.asarray(self.street_tree.query(line.buffer(2)), dtype=int)
        if idx.size == 0:
            return False
        geoms = self.geoms[idx]
        corridor = line.buffer(1.5)
        along = shapely.length(shapely.intersection(corridor, geoms)) > 3.0
        for k in range(len(idx)):
            if along[k] or not self.blocking[idx[k]]:
                continue
            inter = shapely.intersection(line, geoms[k])
            if inter.is_empty:
                continue
            pts = [g for g in shapely.get_parts(inter) if g.geom_type == "Point"]
            ends = (Point(line.coords[0]), Point(line.coords[-1]))
            if any(p.distance(ends[0]) > eps and p.distance(ends[1]) > eps for p in pts):
                return True
        return False
