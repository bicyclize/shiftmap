# Budapest transport analysis — methods & provenance

## 2026-10-14 — IMPORTANT: distance bug found and fixed; earlier counts change

**Any figure quoted before this date must be re-derived.** A systematic error in every distance
computed by the pipeline inflated east–west distances by up to 48%.

### What was wrong

Every distance used `ST_Distance_Sphere(ST_Point(lon,lat), …)`. DuckDB's `ST_Distance_Sphere`
**does not scale longitude by `cos(latitude)`**, and mis-scales latitude as well. At Budapest
(47.5°N) it inflated the east–west component by up to `1/cos(47.5°) = 1.48×` and deflated the
north–south component by ~5.5%. It never errored, so nothing looked wrong.

Evidence (correlating the stored column against candidate formulas):

| formula | correlation with the stored `od_m` |
|---|---|
| no `cos(lat)` on longitude | **0.9999** |
| correct (with `cos(lat)`) | 0.988 |

Checked directly against the EPSG:23700 projection on real coordinate pairs:

| pair | true (EOV) | old value | error |
|---|---|---|---|
| 7.9 km, mostly E–W | 7,853.9 m | 11,316.3 m | **+44%** |
| 11.1 km, mostly N–S | 11,117.7 m | 10,510.5 m | **−5.5%** |
| 38.8 km, mostly E–W | 38,808.0 m | 50,123.1 m | +29% |

### Blast radius

`ST_Distance_Sphere` appeared at **23 sites across 9 scripts** — not just `od_m`:

- **leg distances** (`d_m`) with a **≥300 m** threshold, which decides *which pings become trips
  at all* → the trip set itself was skewed toward east–west movement;
- `path_m`, `od_m`;
- **station distances** (`o_to_stn`, `d_to_stn`) → the 2.5 km access / 1.3 km egress thresholds;
- `o_to_bp_m`;
- `span_m` used a hardcoded `75000` m/deg for longitude (true value ≈ 75,240 — only 0.3% off, so
  the movement/stay detection was approximately right).

### The fix

A canonical WGS84-series macro, `mdist(lon_a, lat_a, lon_b, lat_b)`, now used everywhere. It matches
the EPSG:23700 projection to **0.005%** and costs only arithmetic (no per-row projection).
`span_m` now uses `111320*cos(radians(lat))` instead of the `75000` constant.

### Effect on the headline numbers (May week, 7 days)

| | before | after |
|---|---|---|
| trips | 440,516 | **438,995** |
| **could be a bike (≤5 km)** | 202,977 | **219,764** (+8.3%) |
| bike + train + bike | 46,149 | 45,512 |
| bike + train + foot | 25,132 | **28,187** |
| median `od_m` | 7,701 m | **6,605 m** |
| median distance to nearest station | 1,409 m | **1,184 m** |
| `od_m` ÷ true distance, E–W | 1.45 | **1.002** |
| `od_m` ÷ true distance, N–S | 0.96 | **1.006** |

**Bikeability was understated by ~17,000 trips.** The bias was worst on east–west corridors — the
Danube-adjacent and radial axes, i.e. the most cycleable parts of the city. The earlier analysis was
systematically prejudiced against its own best case.

Derived outputs regenerated after the fix: `platform` (trips + attributes), `trips_paths.parquet`,
`flows.parquet`. Old data preserved as table `platform_old` and `out/trips_paths_OLD.parquet` for
comparison. Backup copies of the edited scripts are at `scripts/*.py.bal.bak`.

### Not affected

The routing graph is built in **EPSG:23700 metres with `cos(lat)` applied**, so its lengths were
always correct. GTFS rail-connectivity logic uses no distances.

## 2026-10-14 (later) — zero-displacement trips were inflating “could be a bike”

While adding route geometry for every trip, 14,992 trips could not be routed: their origin and
destination snapped to the same network node. They are **loops** — a median displacement of **2 m
over a median travelled path of 41.6 km** (vehicles and round trips that return to where they
started). **40,286 trips (9.2%) have a displacement under 100 m.**

Because `bike_direct` is simply `od_m <= 5000`, every one of those counted as *“could have been a
bike”*. A 2-metre displacement is not a trip that could have been a bike.

| | trips |
|---|---|
| “could be a bike” as previously reported | 219,764 |
| …of which with displacement < 100 m | **40,286 (18%)** |
| **“could be a bike” with a 300 m displacement floor** | **171,940** |

The platform now defaults to a **0.3 km minimum displacement** (visible and adjustable in the UI,
and stated on screen so it is not a silent cut). At that floor: **391,171 trips**,
171,940 bikeable, 45,512 bike+train+bike, 28,187 bike+train+foot.

Net effect of both errors on the headline: the distance bug *understated* bikeability
(202,977 → 219,764); the displacement artefact *overstated* it (→ 171,940).

## Rail-corridor proxy (first pass)

`scripts/34_rail_mode.py` measures, per trip, the share of observed GPS vertices within 25 m of a
railway way.

| mode | trips | share |
|---|---|---|
| not rail | 289,214 | 73.9% |
| **rail corridor** | **52,176** | **13.3%** |
| partly on rail | 49,781 | 12.7% |

Limits, stated in the UI as well as here:

- catches **tram, HÉV and surface rail** well — they have their own guideway;
- **under-detects underground metro** — there is no GPS in the tunnel, so the pings stop at the
  portal and resume after;
- a **bus passenger is indistinguishable from a car user** (a bus route *is* a road route), so the
  label is *rail corridor* / *not rail* and never *transit* / *car*.

## 2026-10-15 — the routes were implausible; both faults were real

Reported from the map: *"main road traffic takes small roads and then turns left where it is illegal
to turn left."* Diagnosis confirmed both halves.

**Cause 1 — cost was pure distance.** `weight = len_m`. A distance-minimising router has no reason to
prefer an arterial, and an illegal left turn is frequently the *shortest* option, so it had no reason
to avoid one either.

**Cause 2 — turn restrictions were not modelled at all.** 5,696 restriction relations exist in the
Budapest bbox; none were in the graph.

Fixed: cost is now **time** (`len_m ÷ speed(class)`) and the graph is **directed with turn
restrictions enforced structurally** — each restricted junction is split into one copy per incident
edge, and a forbidden turn has no arc between the copies. 5,527 restrictions resolved; 3,697 junctions
split; 12,465 copies; 24,932 connectors.

**Measured effect, same trips, same days:**

| | before | after |
|---|---|---|
| minor-road share of routed distance | **20.6%** | **9.8%** |
| …on trips ≥ 10 km | 17.9% | **7.8%** |
| 5–10 km | 29.1% | 15.5% |
| residential streets | 13.5% | **5.0%** |
| detour ratio (median) | 1.20 | 1.26 |
| routed trips | 424,003 | 423,958 |
| median points/route | 15 | 13 |

**Resolution validated independently:** a `no_left_turn` must resolve to a movement that is
geometrically a left turn. It does — 1,172 `no_left_turn` at 100% left, 294 `no_right_turn` at 100%
right, straight bans 83–87% straight. Random way→edge matching would sit near 50%.

**Four data/graph defects found while fixing this**, each of which would have produced silent
rubbish rather than an error:

1. `no_u_turn` resolves as a same-way pair; since a way running through a junction appears as two
   contracted edges, that deleted the legitimate through movement and severed roads at 589 junctions.
2. Six junctions had restriction sets leaving an approach with no permitted way out (impassable).
   The road now wins over the restriction at such junctions.
3. The rebuilt graph had lost the **giant-component filter** the original contraction applied, so
   snapping landed in 126–145 node scraps and every route from them failed — a steady 0.5%.
4. Way ids differ by source (`w1169807620` from osmium vs `1169807620` from Overpass), so the first
   resolver matched **zero** restrictions while appearing to work. Via nodes likewise needed
   nearest-coordinate matching (~8 m), not exact key matching — only 29 of 3,765 matched exactly.

**Not modelled:** `no_u_turn` (a u-turn is traversing the same edge back, not a connector; it
essentially never appears in an O→D shortest path, but it is not modelled). The speed profile is a
modelling choice: it is why motorway/trunk shares rose (15.3→26.0% and 3.7→11.4%), and it should be
tuned if those shares look too high.

## 2026-10-15 (later) — rail trips were drawn on roads, and the volume layer ignored its own legend

Reported from the map: *"when I switch off the road box, segments over the motorway and trunk roads
still show as red… rail corridor trips should go through only rail tracks or tram tracks."*

Three separate defects, all real.

**1. The volume layer never read the legend's toggles.** `curFilter()` — which drives the volume
layer, the red lines — did not include the mode state at all; the toggles only filtered the trip
layer. So unticking *road* could not remove a single red segment.

**2. Rail-classified trips were routed on the ROAD graph.** Every trip was, regardless of
classification, so a tram ride was drawn along whatever streets connected its ends. Measured on the
geometry:

| rail-classified trips | before | after |
|---|---|---|
| route within 30 m of real rail | 44.7% | **89.4%** |
| route on motorway + trunk | 18.2% | **5.2%** |
| route on motorway | 12.6% | **3.7%** |

Fixed by building a rail graph (12,139 contracted edges, 4,978 km: rail 4,305, tram 335,
light_rail 219, subway 119) and routing the 48,504 rail-classified trips along it — 89% of the
resulting route lies within 30 m of real track. The residual 10.6% off-rail is exactly the 6,232
trips (11.4%) whose ends sit more than 800 m from any track: those keep their road route, because
routing them from the nearest track would invent a journey.

The road volume was then corrected by routing those same trips on the road graph and subtracting
their contribution (33,751,247 → 30,961,557 edge-visits). Routing is deterministic, so the
subtraction is exact — the script refuses to write output if any count goes negative.

**3. The volume layer's counts were attached to the WRONG edge geometry.** This one was invisible and
had been wrong since the rebuild. Contraction keeps only the largest connected component, which
leaves gaps in the edge ids; the engine indexes edges positionally. The output then joined
`edge_geo.eid` (original ids, with gaps) against `df_cnt.eid` (positions). Because **3,128**
dropped-fragment ids sit below the position ceiling, every count from id 35 onward was drawn on some
other edge's line. Fixed by carrying an explicit position → original-id map and rebuilding each edge's
geometry through it. It surfaced only because the subtraction needed the counts keyed by position —
without that, the misalignment would have stayed hidden.

**Consequence for the legend:** two toggles now, *rail corridor* and *road*, mapping one-to-one onto
the `kind` column of `routed_edges`. Trips that only partly follow a guideway are drawn on roads (a
road route is what they are) and are reported as a count inside *road* rather than as a third toggle,
so the volume layer stays exact rather than approximate.

**Not modelled:** rail turn restrictions. A tram follows its track and OSM maps tram restrictions
very sparsely, so rail is treated as restriction-free — an honest approximation.

## 2026-10-16 — the rail network contained depot and stabling tracks (the "loop" was real)

> **Superseded 2026-10-26.** The filter below over-excluded `siding` and `crossover`, which
> fragmented the MÁV network and made most bike+train alternatives unroutable. See the next entry
> for the corrected filter and numbers.

Reported from the map: *"i dont think there is a publicly used railway there, thats a loop from one
metro line to another for service use."*

**Correct — and the earlier answer ("no loop, only a density artifact") was wrong.** No route
looped, but the geometry drawn there was real and should never have been in the graph. The rail graph
had been built from every OSM way tagged `railway=*`, with no regard for the tags:

| category | ways | km |
|---|---|---|
| `service=yard` | 2,992 | 602 |
| `service=siding` | 1,851 | 590 |
| `service=spur` | 1,553 | 513 |
| `service=crossover` | 759 | 52 |
| `usage=tourism` / `industrial` / `leisure` | 141 | 49 |
| **non-passenger total** | **7,296** | **1,806 — 35.0% of all rail km** |
| passenger (`rail` main/branch, `tram`, `light_rail`, `subway`, `narrow_gauge`) | 4,515 | 3,354 |

OSM states it outright for the way in the reported box: `w324230647`, `railway=subway`,
**`service=yard`**, description *"Kihúzóvágány, az M2 és M3 metróvonal vasúti összeköttetése"* —
"stabling track, the rail connection between metro lines M2 and M3". It was the **only** rail way
crossing that box; the M2 and M3 passenger ways pass near but not through it. After the filter the
box contains **zero** rail graph edges.

Because the previous entry's rail numbers were computed on this impure graph, they are superseded:
the rail graph is now **726 contracted edges / 3,343 km**, not 12,139 / 4,978 km.

**Two consequences, both easy to get wrong:**

1. **The systems are physically separate.** With service tracks gone there are **94 components** —
   tram, metro, HÉV and MÁV share no passenger track. Keeping only the largest component (the graph's
   standing rule) would silently discard every system but one, which is exactly what the depot tracks
   had been masking. The rail graph must keep all components.
2. **Route each trip on the system that fits both ends best.** Snapping each end to the *nearest*
   track puts the origin on a tram and the destination on a railway as often as not → unreachable.
   Choosing the component minimising `d(o) + d(d)` took rail-routed trips from 22,094 (42%) to
   **39,927 (76.5%)**, with no service track reintroduced. The remaining 12,273 rail-corridor trips
   genuinely span two systems and keep their road route.

**The classifier changed too** — it had measured proximity to *any* railway way, so passing a siding
counted as being on the guideway. It now measures proximity to passenger lines only; distribution
over 438,995 trips: `not_rail` 335,289 · `rail` 52,193 · `mixed` 51,309. The old rail-corridor counts
(52,176 / 49,781) came from a different trip set and a different rail set, so they are not comparable
like-for-like — the classifier was simply rebuilt. `platform/rail_mode.parquet` was also a day stale
(Oct 14 vs Oct 15 geometry) and is now current.

**`on_rail` — the flag the legend toggles act on.** The toggles now filter on which network a trip's
**drawn geometry** follows (`route_len.parquet.on_rail`), not on its classification. Filtering on the
classification was the reported bug: a rail-corridor trip that fell back to a road route was still
treated as rail, so its segments stayed on motorway and trunk roads after the road network was
hidden. Now:

| on the map | trips |
|---|---|
| routed along tracks | **39,927** |
| road routes | 384,031 |
| — of which rail-corridor trips that fell back | 12,273 |

Verified in the browser: **road hidden → the volume layer leaves exactly 563 features, all of them
rail edges** (there are 563 rail edges); **rail hidden → exactly 162,593 road edges**. Road volume
33,751,247 → 31,875,809 edge-visits after subtracting the rail trips' road footprint.

The bike+train scenarios are unaffected throughout — `btb`/`btf` measure distance to **GTFS station
stops**, not to rail ways, so a depot siding was never counted as a station.

## 2026-10-26 — the rail filter over-reached (siding/crossover are load-bearing); alternative paths

**The 16 Oct filter over-reached.** Excluding `service=siding` and `crossover` alongside `yard` and
`spur` shattered the MÁV network. At a station the *through line* is routinely tagged
`service=siding`, so removing it split one system into five — largest component **11,732 nodes
instead of 48,588**. Almost every bike+train alternative became unroutable, because a station pair on
two different fragments has no route. Measured on a 200-trip sample: only **8 of 200** bike+train
trips could be routed.

**Corrected filter:** exclude `yard` (depot/stabling — the M2↔M3 loop) and `spur` (freight branch);
**keep** `siding` and `crossover`. Result: rail graph **5,801 contracted edges / 3,976 km**
(MÁV 3,347, tram 298, HÉV 194, metro 83, narrow-gauge 54), **114 components**, largest 48,588 nodes.
The loop stays gone — the box still contains zero rail graph edges.

**Knock-on improvement to the existing rail layer:** `on_rail` **39,927 → 42,042**; rail edges
carrying traffic **563 → 3,886** (the network is now one piece, so routes span it). Rail-corridor
trips that fell back to a road route dropped from 12,273 to **10,731**. Verified: road hidden → the
volume layer leaves exactly **3,886** rail-edge features; rail hidden → **162,389** road edges.

**Alternative-path feature** (Step 1 of the two-step shift). Selecting a scenario now draws, for
every matching trip, the route it *could* have taken instead: a bike leg on a dedicated cycling
network, a train leg on the passenger rail graph, and (for btf) a dashed foot leg. Stations are
drawn as dots and labelled from GTFS.

The cycling network is new (`scripts/66_bike_graph.py`): roads **plus** the `highway=cycleway` /
`path` / `footway` / `pedestrian` ways the road extract omits, costed by time, refusing
`bicycle=no`/`private`/`use_sidepath` and motorways. 1.16 M segments → 359,061 contracted edges,
one connected component, ~1,830 km of cycling-specific provision (557 cycleway + 687 laned + 475
path + 109 designated).

Coverage (a leg that cannot be routed is dropped, never invented): bike direct **219,464 / 219,764
(99.9%)**, bike+train+bike **35,471 / 45,512 (78%)**, bike+train+foot **22,976 / 28,187 (81.5%)** —
394,805 legs across 277,911 trip-alternatives. New files: `alt_routes.parquet` (25.6 MB),
`alt_summary.parquet`, `alt_stations.parquet`.

**Pipeline gotcha — DuckDB v2 axis order.** `uv run --with duckdb` now resolves DuckDB **v2**, which
refuses `ST_Transform` on `OGC:CRS84` geometry unless `SET geometry_always_xy = true` is issued first
(it otherwise assumes the source CRS's native axis order — EPSG:4326 = lat/lon — silently swapping
coordinates). `34_rail_mode.py` failed on exactly this; the fix is one line after `LOAD spatial;`.

## Routing — complete

Trips are routed along the real OSM road network (not drawn as straight chords between GPS points —
the earlier "paths" were snapped ping vertices joined by straight lines, with a median segment gap
of 746 m and 60% of segments over 500 m, so they cut across the city).

- Graph: 1,050,766 road segments → contracted to **308,453 edges / 236,017 nodes** (giant connected
  component only), built in `db/graph.duckdb`.
- Routing on the contracted graph: ~14 ms per trip; the full set takes **~20 min on 8 processes**.
- Result: **438,995 / 438,995 trips routed, 0 failures.** Median routed length 6.29 km.
- **Verification — detour (routed length ÷ straight line): median 1.20, p10 1.07, p90 1.50**, the
  expected range for a road network. This is the check that exposed the distance bug above.
- **179,530 of 308,453 edges** carry at least one routed trip.

Outputs (all in `platform/`):

| file | contents | size |
|---|---|---|
| `routed_edges.parquet` | per network edge: trip volume, **split by day × length band** (+ scope), and geometry | 12.0 MB |
| `routed_sample.parquet` | 9,631 trips with full routed street geometry | 10.0 MB |
| `route_len.parquet` | routed length for every trip | 1.6 MB |

The day × length splits make the **volume layer filter-aware** — selecting a day or a length band
thins the network down to those trips. Scope is stored as a marginal, so scope combined with day or
length is not exact; the legend states this rather than hiding it.

**Still to do:** the mode classifier (road user vs transit user). Until it lands, every trip routes
on the road network, so metro/tram/rail corridors are represented by road routing. Bike+train
remains a *counterfactual* — the observed population is modelled as either road users or transit
users, with no assumed bike-to-station access.
