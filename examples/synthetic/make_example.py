"""Builds a synthetic city block (no real data) that reproduces the reference scenarios.

Street axes in local metres. Kerb = 5 m from the axis, sidewalk poles at 6.5 m, house doors at 12.5 m.
Run:  python make_example.py   ->  streets.gpkg, poles.csv, terminals.csv, points.csv, rules.yaml
"""
import os
import geopandas as gpd
import pandas as pd
import yaml
from shapely.geometry import LineString

HERE = os.path.dirname(os.path.abspath(__file__))
CRS = "EPSG:32718"   # any metric CRS; the coordinates are local metres

streets = gpd.GeoDataFrame({
    "name": ["Calle Norte", "Av. Sur (dual carriageway)", "Calle Oeste", "Calle Este"],
    "blocking": [False, True, False, False],
    "geometry": [LineString([(0, 25), (240, 25)]), LineString([(0, 112), (240, 112)]),
                 LineString([(40, 0), (40, 176)]), LineString([(170, 0), (170, 176)])],
}, crs=CRS)
streets.to_file(f"{HERE}/streets.gpkg", driver="GPKG")

# sidewalk lines on the block side: Calle Norte y=31.5 · Calle Oeste x=46.5 · Calle Este x=163.5
poles = [
    ("own", "S1", 70, 31.5), ("own", "S2", 50, 31.5),            # chain west of the terminal (spans 50 / 20 m)
    ("own", "S_corner", 47.5, 32.5), ("own", "S3", 46.5, 78),    # turning the NW corner
    ("own", "S_NE", 162.5, 32.5),                                # NE corner pole
    ("external", "E1", 163.5, 80),                               # electric pole on Calle Este: fills the gap
    ("own", "S_enfrente", 80, 18.5), ("external", "E_enfrente", 100, 18.5),  # opposite sidewalk: never used to cross and return
]
pd.DataFrame(poles, columns=["kind", "id", "x", "y"]).to_csv(f"{HERE}/poles.csv", index=False)

terminals = pd.DataFrame([("T1", 120, 31.5), ("T_av", 100, 118.5)], columns=["id", "x", "y"])
terminals.to_csv(f"{HERE}/terminals.csv", index=False)

points = pd.DataFrame([
    ("A1_direct",     "T1", 102, 37.5),   # 18 m along the same sidewalk            -> installable_own (direct)
    ("B1_chain",      "T1", 52, 37.5),    # T1 -> S1 -> S2 -> door                  -> installable_own
    ("C1_corner",     "T1", 52.5, 70),    # turns the corner: S2 -> S_corner -> S3  -> installable_own
    ("B2_external",   "T1", 157.5, 78),   # east side: S_NE -> E1 (electric) -> door -> installable_external
    ("N7_too_far",    "T1", 52.5, 150),   # route > 150 m                            -> not_installable
    ("N6_avenue",     "T_av", 100, 103.5),  # terminal across the blocking avenue   -> not_installable
    ("E1_alternative", "T_av", 104, 37.5),  # assigned to T_av, but T1 is reachable -> alternative terminal
], columns=["id", "terminal_id", "x", "y"])
points.to_csv(f"{HERE}/points.csv", index=False)

yaml.safe_dump({"max_span_m": 60, "max_lead_in_m": 30, "direct_m": 30, "max_route_m": 150,
                "pole_snap_m": 15, "side_neutral_m": 1.0}, open(f"{HERE}/rules.yaml", "w"))
print("example written to", HERE)
