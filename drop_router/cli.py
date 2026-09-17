"""drop-router command line.

    drop-router run --streets streets.gpkg --poles poles.csv --terminals terminals.csv \
                    --points points.csv --rules rules.yaml --out result.csv [--crs EPSG:32718]

poles.csv:     id, x, y, kind            (kind = own | external)
terminals.csv: id, x, y
points.csv:    id, terminal_id, x, y
All coordinates in the metric CRS given by --crs (or already projected).
"""
from __future__ import annotations

import argparse
import sys

import geopandas as gpd
import pandas as pd
import yaml

from .chain import Poles, Rules
from .router import DropRouter
from .streets import StreetGraph


def load_rules(path: str | None) -> Rules:
    if not path:
        return Rules()
    with open(path) as f:
        return Rules(**{k: float(v) for k, v in (yaml.safe_load(f) or {}).items()})


def main(argv=None):
    ap = argparse.ArgumentParser(prog="drop-router")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="classify points")
    run.add_argument("--streets", required=True, help="GPKG/GeoJSON/parquet of street lines")
    run.add_argument("--poles", required=True)
    run.add_argument("--terminals", required=True)
    run.add_argument("--points", required=True)
    run.add_argument("--rules", default=None)
    run.add_argument("--out", default="result.csv")
    run.add_argument("--crs", default=None, help="metric CRS to project streets into (e.g. EPSG:32718)")
    run.add_argument("--no-alternatives", action="store_true")
    a = ap.parse_args(argv)

    streets = gpd.read_parquet(a.streets) if a.streets.endswith(".parquet") else gpd.read_file(a.streets)
    if a.crs:
        streets = streets.to_crs(a.crs)
    if streets.crs is not None and streets.crs.is_geographic:
        sys.exit("streets must be in a metric CRS: pass --crs EPSG:xxxxx")
    poles = pd.read_csv(a.poles)
    own = poles[poles.kind == "own"]; ext = poles[poles.kind == "external"]
    router = DropRouter(StreetGraph(streets),
                        Poles.from_xy("own", own.id, own.x, own.y),
                        Poles.from_xy("external", ext.id, ext.x, ext.y),
                        load_rules(a.rules))
    res = router.run(pd.read_csv(a.terminals), pd.read_csv(a.points), alternatives=not a.no_alternatives)
    res.to_csv(a.out, index=False)
    print(res.category.value_counts().to_string())
    print(f"-> {a.out}")


if __name__ == "__main__":
    main()
