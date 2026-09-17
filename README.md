# drop-router

**Can a drop cable actually be strung from a terminal to a point?**
Street-graph routing plus a support-chain check with field rules (span, lead-in, street side,
blocking avenues). Born from an idea taken from *Micromouse* maze-solving competitions: first map,
then compute the route you can really travel — never the straight line.

> Straight-line distance says "50 m away, covered". The street says otherwise: an avenue with a
> median you cannot cross, a gap between poles the cable cannot span, a crossing you cannot make twice.
> `drop-router` answers the question the technician will face at the door.

Originally built for FTTH last-mile planning (terminal box → house), the engine knows nothing about
fibre: give it streets, supports, origins and destinations, and it will tell you whether a viable
route exists, which supports it uses and where it fails. The same logic applies to any network that
has to reach a point along the public way.

## How it decides

1. **Map.** Street centrelines become a graph (densified every 5 m, micro-bridges for small gaps).
   Streets flagged `blocking` (dual carriageways with a median) can be followed but never crossed.
2. **Route.** Dijkstra from the terminal along the street axis to each point, capped at `max_route_m`.
3. **Chain.** Supports (poles) within `pole_snap_m` of the route are candidates. A chain must satisfy:
   * every span ≤ `max_span_m` (own or external support, no distinction);
   * the lead-in (last support → point, straight line) ≤ `max_lead_in_m`;
   * the lead-in may leave from a pole **or from the middle of a span** (mid-span derivation);
   * the chain may change street side **once**, towards the point, and never back;
   * own supports are preferred: the search minimises external supports.
4. **Classify.** `installable_own` · `installable_external` (needs at least one external support,
   listed by id) · `not_installable` (with the reason). If the assigned terminal fails, the nearest
   viable alternative terminal within `max_route_m` **of route** is tried.

Every rule is a number in `rules.yaml`; nothing is hard-coded to a country, operator or cable.

## Quick start

```bash
pip install -e .
python examples/synthetic/make_example.py          # builds a synthetic block (no real data)
drop-router run --streets examples/synthetic/streets.gpkg \
                --poles examples/synthetic/poles.csv \
                --terminals examples/synthetic/terminals.csv \
                --points examples/synthetic/points.csv \
                --rules examples/synthetic/rules.yaml --out result.csv
```

Output (`result.csv`) for the synthetic block:

| id | category | route_m | supports | reason |
|---|---|---:|---|---|
| A1_direct | installable_own | 39 | | direct |
| B1_chain | installable_own | 109 | own:S1 | |
| C1_corner | installable_own | 139 | own:S1;own:S2;own:S3 | |
| B2_external | installable_external | 119 | own:S_NE;external:E1 | |
| N7_too_far | not_installable | 222 | | route 222 m > 150 m |
| N6_avenue | not_installable | 15 | | crosses a blocking street |
| E1_alternative | installable_own | 34 | | direct (alternative terminal T1) |

### Inputs

| File | Columns | Notes |
|---|---|---|
| streets (GPKG / GeoJSON / GeoParquet) | `geometry` (LineString), optional `blocking`, `minor` | metric CRS (pass `--crs EPSG:xxxxx` to project). Must be noded at intersections. |
| poles.csv | `id, x, y, kind` | `kind` = `own` or `external` |
| terminals.csv | `id, x, y` | |
| points.csv | `id, terminal_id, x, y` | pre-assigned terminal; alternatives are searched when it fails |
| rules.yaml | `max_span_m, max_lead_in_m, direct_m, max_route_m, pole_snap_m, side_neutral_m` | defaults: 60 / 30 / 30 / 150 / 15 / 1 |

### Python API

```python
from drop_router import StreetGraph, Poles, Rules, DropRouter
router = DropRouter(StreetGraph(streets_gdf), Poles.from_xy("own", ids, xs, ys),
                    Poles.from_xy("external", ids2, xs2, ys2), Rules(max_span_m=60))
result = router.run(terminals_df, points_df)
```

## What this is not

* Not a production system of any company: it is a clean, generic re-implementation of the method.
* Not a substitute for a field survey: it does not see trees, saturated poles or a neighbour who
  refuses the anchor. It gives the realistic ceiling, not a guarantee.
* Quality follows the inputs: a street network that is not topologically connected will not route.

## Tests

```bash
python -m pytest tests          # 7 rule tests: direct, chain, gap, external fill, cross-and-return, single crossing, mid-span
```

## License

MIT.
