# Budapest trip analysis platform

Interactive web tool: filter trips by **area**, **length** and **scenario** (bike direct / bike+train+bike / bike+train+foot) and see the matching trips on a map.

## Run it

```bash
cd platform
python3 -m http.server 8765
# then open http://localhost:8765
```

That's all. **No backend, no database, no build step, no CDN at runtime.**

## Deploy on a Raspberry Pi

```bash
# from your Mac
rsync -av --exclude '*.mjs' "platform/" pi@<pi>:/var/www/trips/

# on the Pi — simplest
cd /var/www/trips && python3 -m http.server 80
```

Or, better, with Caddy (adds gzip + caching, which matters for the 17 MB data file):

```
# /etc/caddy/Caddyfile
:80 {
    root * /var/www/trips
    encode zstd gzip
    file_server
}
```

A Pi Zero can serve this — it only hands over static files. All filtering happens in the visitor's browser.

## How it works

| layer | what |
|---|---|
| `trips_attrs.parquet` | **438,995 trips** (7 days, May 2023) + attributes. 17.6 MB, ZSTD. **Geometry is never stored here** — it always comes from a calculated route. |
| `routed_edges.parquet` | per OSM network edge (road **and** rail, distinguished by `kind`): **how many trips were routed through it**, + geometry — the volume/thickness map |
| `routed_geom.parquet` | the **calculated route** for all 423,958 routed trips |
| `route_len.parquet` | routed length per trip, plus **`on_rail`** — which network that trip's drawn geometry actually follows |
| `rail_mode.parquet` | per-trip rail-corridor proxy read off the **observed pings** (`not_rail` / `rail` / `mixed`) |
| `alt_routes.parquet` | the **alternative path** — routed bike/train/foot legs, one row per leg, keyed `trip|scenario` |
| `alt_summary.parquet` | per trip+scenario: bike/train/foot leg lengths (metres) |
| `alt_stations.parquet` | station id → name, for labelling the station dots |
| `vendor/hyparquet.js` | pure-JS Parquet reader (54 KB) — parses the files in the browser |
| `vendor/maplibre-gl.js` | map rendering |
| `index.html` | the whole app |

The browser downloads the Parquet files once, keeps them in memory as column arrays, and
re-filters on every UI change.

> **Distance bug, fixed 2026-10-14.** Every distance used to come from DuckDB's
> `ST_Distance_Sphere`, which does **not** scale longitude by `cos(latitude)`: at Budapest it
> inflated east–west distances by up to **+48%** and deflated north–south by ~5.5%. It never
> errored. Every trip, `path_m`, `od_m`, and every access/egress threshold inherited it, so
> **bikeability was understated by ~17,000 trips** — worst on the east–west corridors.
> All distances now use the `mdist` macro (`scripts/19_osm_paths.py`), a WGS84 series accurate to
> 0.005% against the EPSG:23700 projection. See `Budapest transport analysis.md` for the full
> audit and the before/after numbers.

## The rail network is PASSENGER lines only (revised 2026-10-26)

The rail graph was first built from every OSM way tagged `railway=*`. **35% of its kilometres were
not a passenger line**: `service=yard` (602 km), `siding` (590), `spur` (513), `crossover` (52),
plus `railway=platform_edge` and `usage=industrial/tourism/...`. Nothing stopped the router using
them, and a visible loop appeared where the M2↔M3 stabling connection sits
(`w324230647`, `service=yard`, *"Kihúzóvágány, az M2 és M3 metróvonal vasúti összeköttetése"* —
OSM's own description says it is a service link, not a public line). In that box the stabling track
was the **only** rail way crossing it; after the filter, the box contains **zero** rail graph edges.

Filter (first match wins, `scripts/56_rail_passenger.py` → `db/rail_passenger.parquet`):

| rule | excludes |
|---|---|
| `railway` ∈ {platform_edge, platform, switch, crossing, level_crossing, signal, buffer_stop, milestone, abandoned, disused, construction, razed, proposed, …} | not a running track |
| `service` ∈ {yard, spur, industrial, slipway} | depot/stabling + freight branch |
| `usage` ∈ {industrial, tourism, military, freight, test, leisure} | not a passenger service |
| everything else (rail / light_rail / subway / tram / narrow_gauge, `usage` main, branch or absent) | **kept** |

Two subtleties, each bought with a debugging session:

1. **`service=siding` and `crossover` must be KEPT.** At a station the through line is routinely
   tagged `service=siding`, and a crossover links parallel tracks. Excluding them (the natural
   extension of the filter) shattered the MÁV network into five pieces — largest component
   **11,732 nodes instead of 48,588** — and made almost every bike+train alternative unroutable,
   because a station pair on two fragments has no route.
2. **Do not keep only the largest connected component.** With depot tracks gone the guided systems
   are *physically separate* — tram, metro, HÉV and MÁV share no passenger track. The graph is
   **114 components / 5,801 contracted edges / 3,976 km** (MÁV 3,347, tram 298, HÉV 194, metro 83,
   narrow-gauge 54). Filtering to the largest would silently discard every system but one (that is
   how it behaved before: the depot tracks were the only thing joining them).

### `on_rail` — the flag the toggles act on

The rail/road legend toggles filter on **which network the drawn geometry follows**
(`route_len.parquet.on_rail`), *not* on the trip's classification. Using the classification was a
bug: a rail-corridor trip that could not be routed on one guided system (its ends sit on different
systems — say tram then metro) keeps its **road** route, and filtering it as "rail" left its segments
on motorway and trunk roads after the road network was hidden.

| on the map | trips |
|---|---|
| routed along tracks (`on_rail = true`) | **42,042** |
| everything else (road routes) | 396,953 |
| — of which rail-corridor trips that fell back to a road route | 10,731 |

Verified: with **road hidden** the volume layer leaves exactly **3,886 features — the rail edges and
nothing else**; with **rail hidden**, exactly **162,389 road edges**.

The bike+train scenarios (`btb`, `btf`) are **not** affected by any of this: they measure distance to
**GTFS station stops**, not to rail ways, so a depot siding was never counted as a station.

## The alternative path (2026-10-26)

Selecting a scenario and (optionally) drawing an area shows, for every matching trip, the route it
*could* have taken instead — routed, never sketched:

- **bike (direct)** — one bike leg, O → D;
- **bike + train + bike** — bike O → station, train station → station, bike station → D;
- **bike + train + foot** — as above, with a dashed foot leg on the far side.

Bike and foot legs run on a **cycling network** built separately from the road network
(`scripts/66_bike_graph.py`): roads **plus** the dedicated `highway=cycleway` / `path` / `footway` /
`pedestrian` ways the road extract omits, costed by time, refusing `bicycle=no`/`private`/
`use_sidepath` and motorways. The train leg runs on the passenger rail graph above; station ends are
drawn as dots and labelled from GTFS (`alt_stations.parquet`).

A leg that cannot be routed is dropped, never invented. Coverage: bike direct 99.9%, bike+train+bike
78%, bike+train+foot 81.5%.

## Pipeline gotcha — DuckDB v2 axis order (2026-10-26)

`uv run --with duckdb` now resolves DuckDB **v2**, which rejects `ST_Transform` on `OGC:CRS84`
geometry unless `SET geometry_always_xy = true` is issued first (it otherwise assumes the source CRS's
native axis order — EPSG:4326 = lat/lon — silently swapping coordinates). `34_rail_mode.py` failed on
this; the fix is one line right after `LOAD spatial;`.

## Columns in `trips_attrs.parquet`

| column | meaning |
|---|---|
| `day_tag` | day of the May week ('08'…'14') |
| `od_m`, `path_m` | straight-line O–D distance / travelled path (metres) |
| `o_lat`,`o_lon`,`d_lat`,`d_lon` | origin and destination coordinates |
| `trip_scope` | `budapest` (both ends in city) / `suburb_bp` (one end each) / `suburb_local` (both ends outside) |
| `o_stn`,`d_stn`, `o_to_stn`, `d_to_stn` | nearest rail station and distance to it (metres) |
| `rail_lvl` | 0 = no rail link, 1 = link with one change, 2 = direct link |
| `bike_direct` | trip ≤ 5 km → could be a bike outright |
| `btb` | origin ≤2.5 km + destination ≤2.5 km from a rail station, rail link exists, trip >8 km → **bike+train+bike** |
| `btf` | origin ≤2.5 km (bike) + destination ≤1.3 km (foot), rail link, trip >8 km → **bike+train+foot** |

## Basemap

Fixed to **Bicyclize Monochrome** (`mapbox://styles/bicyclize/ckwow6vcf8hli15nvze3fvrej`) — the
sidebar basemap chooser has been removed, so there is no basemap switch.

`style.json` is that style pre-converted for MapLibre: every `mapbox://` reference was rewritten to
an absolute `api.mapbox.com` URL carrying your public token. MapLibre cannot speak the `mapbox://`
protocol, so this local conversion is what makes the style usable here.

Three conversions matter, and one of them is easy to get wrong:

| reference | becomes |
|---|---|
| tileset `mapbox://mapbox.mapbox-streets-v8` | `…/v4/mapbox.mapbox-streets-v8.json` |
| glyphs `mapbox://fonts/{stack}/{range}.pbf` | `…/fonts/v1/{stack}/{range}.pbf` |
| sprite `mapbox://sprites/{user}/{style}/{hash}` | `…/styles/v1/{user}/{style}/`**`sprite`** |

The sprite's trailing hash is an internal version stamp, **not** a path segment — keeping it 404s
both `sprite.json` and `sprite.png` and silently drops every sprite icon while the map still draws.
`scripts/17_mapbox_style.py` now probes the sprite URL for reachability as well.

> **Two notes on the Mapbox style.** (1) It embeds your `pk.` token in `style.json`, which is
> public *by design* — but you should set a URL restriction on it in your Mapbox account before
> this goes on the open web. (2) Mapbox's terms cover using their tiles through Mapbox GL JS;
> rendering their tiles with MapLibre is outside that, so for a public site prefer the
> self-hosted option below.

Attribution is rendered bottom-right and updates with the basemap.

> **Tile policy, important for public hosting.** `tile.openstreetmap.org` is run on donated
> servers and its [usage policy](https://operations.osmfoundation.org/policies/tiles/) allows
> only **light, non-commercial use** — it is *not* suitable for a public site with real traffic.
> If this goes on the open web with visitors, switch the default to **OSM light** (CARTO serve
> it free for reasonable volumes) or self-host — see below.

## Paths — calculated routes only

**The app draws nothing but calculated routes.** There is no straight O–D line anywhere in the
code, and no snapped-ping chord either: `tripPts()` is the single geometry accessor and returns
either the trip's routed geometry or `null`. A trip without a route is never drawn *and never
tested* against an area or a clicked segment — it simply drops out, rather than being approximated.

`routed_geom.parquet` holds a route for **every** 438,995 trips, simplified with Douglas-Peucker.
The routes carry ~197 points each, almost all collinear along straight OSM ways, so simplification
keeps only the real turns:

| tolerance | median points/route | all trips on disk |
|---|---|---|
| none | 197 | **1,176 MB** — impossible |
| **30 m (used)** | **15** | **~49 MB** |
| 50 m | 12 | ~31 MB |

15 points = 15 real turns, so the line still follows the streets. Verified by the detour ratio
(routed length ÷ straight-line): median **1.26**, p10 1.09, p90 1.61.

### The routing model, and why it changed

The first build minimised **distance** and ignored **turn restrictions**. That produced routes that
dived down residential streets to save fifty metres, and made turns that are illegal — an illegal
left turn is frequently the *shortest* option, so a distance-minimising router has no reason to
avoid one. Both faults were reported from the map and both were real.

The router now minimises **time** (`len_m ÷ speed(class)`) and **obeys OSM turn restrictions**:

- **Time, not distance.** An arterial is cheaper per metre than a parallel side street, so
  main-road traffic stays on main roads.
- **Turn restrictions are enforced structurally.** The graph is directed, and every junction that
  carries a restriction is split into one copy per incident edge; a forbidden turn simply has no
  arc between the copies. The illegal movement is not expensive — it is *unavailable*.

Measured effect on the same trips:

| | before | after |
|---|---|---|
| minor-road share of routed distance | **20.6%** | **9.8%** |
| …on trips ≥ 10 km | 17.9% | **7.8%** |
| residential streets | 13.5% | **5.0%** |
| median points per route | 15 | 13 |

**Not modelled:** `no_u_turn`. A u-turn is not a connector between copies here — it is traversing
the same edge straight back, which the arc set always permits. U-turns essentially never appear in
an origin–destination shortest path, so the practical effect is nil, but it is not modelled.

**Fixes to the restriction data itself, all found by measurement rather than assumption:**

- A restriction whose `from` way *is* its `to` way is a u-turn. Resolving it naively deletes the
  legitimate through movement, because a way running **through** a junction appears as *two*
  contracted edges — that severed roads at 589 junctions. Such restrictions are now skipped.
- Where a restriction set leaves an approach with **no permitted way out**, the junction is
  impassable. That is always an artefact of over-broad resolution, and it severs everything beyond.
  Six junctions; the road now wins over the restriction.
- Only the **largest connected component** is kept, as the original contraction did. Without it,
  snapping lands in detached fragments and every route to or from one fails (that was 0.5% of trips).
- Resolution is **verified independently**: a `no_left_turn` must resolve to a movement that is
  geometrically a left turn. It does — 1,172 `no_left_turn` at **100% left**, 294 `no_right_turn` at
  **100% right**, straight bans 83–87% straight. Random way→edge matching would sit near 50%.

The old `path_xy` (pings snapped to the nearest way, up to 14 points, straight chords between them —
median gap 746 m, 60% of segments over 500 m) is no longer shipped to the browser at all. It is
still in the database for the rail-corridor proxy below, which needs the *observed* pings rather
than the road route.

How the graph is built (`scripts/21_graph.py` → `23_contract.py` → `25_route_all.py`):

1. Every way coordinate becomes a node; consecutive coordinates become edges. OSM marks junctions by
   *sharing* coordinates, so ways connect at real junctions and stay separate where they merely cross.
2. Keep only the **giant connected component** — points snapped into detached fragments otherwise
   make ~10% of trips unroutable.
3. **Contract degree-2 chains** (~80% of road nodes are shape points, not junctions): 1,050,766
   segments → **308,453 edges / 236,017 nodes**, and Dijkstra drops from 84 ms to ~14 ms per route.
4. Snap each trip's O and D to the nearest *routable* node via a KD-tree (restricting the tree to
   routable nodes takes failures from 7% to 0%), then route.

> **Routing runs at build time on your Mac** — the served platform stays static and Pi-hostable.
> The engine choice affects convenience and route quality, never the runtime architecture.

Network kept: 213,870 drivable road ways + 11,811 rail ways (`motorway`…`service`, plus
`rail`/`light_rail`/`subway`/`tram`), exported to `net.parquet` (18 MB) and stored in `db/osm.duckdb`.

## Flow layer — line thickness = trip volume

The **“Routes on the network”** selector switches how the routing is drawn:

| mode | what you see |
|---|---|
| **Individual trips** ← default | one line per trip, coloured by length band |
| **Flow** | the OSM network itself, each segment with **line width proportional to how many trips use it** |
| **Both** | flow underneath, individual trips on top |

How it's built (`scripts/20_flows.py`): every snapped path vertex is matched back to the OSM way it
sits on (median residual **0.2 m**), then trips are counted **per way as distinct trips** — a trip
that traverses the same way twice counts once. Counts are split by scope (`n_all`, `n_bp`,
`n_sbp`, `n_sl`), so changing the scope filter re-weights the whole map.

Width uses `sqrt` scaling (area perception) from 0.45 px to ~10 px; colour runs
blue → cyan → amber → red as volume rises.

**125,714 of 225,681 ways** carry at least one trip — median 5 trips, busiest 1,663.

Busiest by road class (mean trips per way): **subway 116 · motorway 96 · trunk 94 · tram 54 ·
primary 44 · secondary 38 · tertiary 36**. The map independently picks out the metro corridors and
the radial arterials — a good sanity check that the volume signal is real.

### Filtering, and the legend

A **legend sits top-right of the map**. It is not decoration — it is a filter control, and every
number on the left is recomputed from what it lets through.

**The legend names the colour scheme that is actually on screen.** The map is coloured three
different ways depending on what is showing, so the top of the legend changes with it:

| the map is showing | colour means | key shown |
|---|---|---|
| **Routed volume** (default) | how many trips run along that segment | a blue→amber→red **ramp**, "fewer → more trips"; thickness and opacity carry the same number |
| **Routed sample**, no area | trip **length** | five swatches: ≤2 km, 2–5, 5–8, 8–15, >15 km |
| **an area drawn** or a road clicked | the trip's **role** relative to that area | the role rows themselves are the key |

Two distinct meanings share the same red, which is exactly why the key has to be explicit:
`#d73027` is *the busiest segments* in the volume layer and *trips over 15 km* in the trip layer.

| colour | role (area drawn) |
|---|---|
| `#1F6FB2` blue | starts inside |
| `#2CA25F` green | ends inside |
| `#F2A900` amber | passes through |
| `#8E44AD` purple | both ends inside (counts as starting *and* ending) |

The **Rail corridor / Road** rows deliberately carry **no colour swatch**: they are filters, not a
display style — the map is never coloured by network, so a swatch would imply something untrue.

### Two networks: rail trips are drawn on tracks

Trips classified as *rail corridor* are routed along the **rail graph** (tram / metro / HÉV / rail,
12,139 contracted edges, 4,978 km); everything else is routed along the road graph. Before this they
were all routed on roads, so a tram ride was drawn along whatever streets connected its two ends.

| rail-classified trips | before | after |
|---|---|---|
| route within 30 m of real rail | 44.7% | **89.4%** |
| route on motorway + trunk | 18.2% | **5.2%** |

The `routed_edges` file therefore carries a **`kind`** column (`road` / `rail`), and the legend's two
toggles map one-to-one onto it: hiding *road* removes every road edge from the volume layer, leaving
only tracks. Trips that only *partly* follow a guideway stay on roads — a road route is what they
are — and are reported as a count inside *road* rather than as a third toggle, so the volume layer
stays exact. A rail trip whose ends sit more than **800 m** from any track keeps its road route: it
is not a guideway trip, and routing it from the nearest track would invent a journey.

Rail is treated as **restriction-free** (a tram follows its track, and OSM maps tram turn
restrictions very sparsely) — an honest approximation, not an oversight.

### The volume layer was attached to the wrong geometry

Worth recording because it was invisible. Contraction keeps only the largest connected component,
which leaves **gaps** in the edge ids; the routing engine then indexes edges **positionally**. The
output joined `edge_geo.eid = df_cnt.eid` — comparing an *original* id against a *position*. Because
3,128 dropped-fragment ids sat below the position ceiling, every count from id 35 onward was drawn on
some other edge's line. Fixed by carrying an explicit **position → original id** map and rebuilding
the geometry through it.

**Roles (appear once you draw an area).** Each trip relative to the area is *starting inside*,
*ending inside*, or *passing by* (through traffic only). A trip is shown if it satisfies **any**
checked criterion, so unchecking *start inside* leaves ending + passing-by trips — on the map **and**
in every count, share and feasibility figure on the left. A trip with both ends inside counts as
starting **and** ending, and is drawn in its own colour.

**Click a road → keep only the trips routed along it.** Clicking the network selects the nearest
edge and filters to trips whose route runs along it. Click the same road again to deselect. In a
dense city almost every point is near *some* road, so this is a toggle rather than a
click-empty-space-to-clear.

**The volume layer is filter-aware.** Per-edge counts are stored split by **day × length band**
(a cross-product, so day, length, or both together are exact) plus **scope** as a marginal. Selecting
a day or a length band genuinely thins the network.

> Two honest limitations, surfaced rather than hidden:
> - **Scope combined with day or length cannot be exact** for the volume layer (scope is a separate
>   marginal). It applies scope and the sidebar note says so. The trip view is always exact.
> - A drawn **area** or a **clicked road** hides the volume layer, because its edges are
>   pre-aggregated and cannot be filtered by an arbitrary shape. Both switch the map to the matching
>   trips, which is the point of selecting one.
>
> **Scenario** filtering likewise acts on the trip view (it is not in the splits).

## Area tool

“Draw area” → click the map to place corners → double-click (or “Finish”) to close.

The area is **filled light blue from the third corner onwards** (with a dot on each corner), so you
see the shape you are enclosing *while* you draw it — not only once it's closed.

The app opens showing **all trips**; the area filter is a refinement applied on top. Once an area is
closed, **everything not related to it disappears**: only trips that **start**, **end**, or **pass
through** the area are shown and counted. The panel then breaks those trips down by role
(starts inside → out / outside → ends in / inside → inside / passes through) and by what they could
have been — bike, bike + train + bike, bike + train + foot.

Point-in-polygon and segment-intersection are implemented directly in ~30 lines of JS (no
external geometry library), and the “passes through” test uses the **real snapped path**, not the
straight O→D line.

## Fully offline / self-hosted basemap

For a Pi with no internet, drop the raster tiles and serve a **vector basemap from one
`.pmtiles` file** in this folder (no tile server needed, range requests only):

```js
// in index.html, replace the raster source with:
map.addSource('basemap', {
  type: 'vector', url: 'pmtiles://./budapest.pmtiles'
});
```

Build the extract once with [Protomaps](https://protomaps.com/) (`pmtiles extract` on a
Hungary OSM extract gives a file in the low hundreds of MB) and add `pmtiles.js` to `vendor/`.
Then the whole platform — data, code and basemap — is self-contained on the Pi.

## Caveats

- Trip paths are **snapped to the OSM road/rail network** (median snap 4–5 m), not straight O→D
  lines. They follow the network, but they are *plausible* routes rather than recorded GPS traces —
  the underlying pings are sparse.
- **Trip segmentation** uses stay-point detection; sparse rural pings make long suburban trips approximate.
- Distances are straight-line for filtering (robust); `path_m` is the travelled path.
- The **flow layer** is weighted by scope only (see above).

## Regenerating the data

```bash
# OSM network + snapped paths (needs: osmium-tool, the Hungary extract)
osmium export data/osm/net.osm.pbf -f geojsonseq --add-unique-id=type_id -o data/osm/net.geojsonseq
tr -d '\036' < data/osm/net.geojsonseq > data/osm/net.ndjson   # strip GeoJSONSeq RS bytes
uv run --with duckdb --with pandas python scripts/18_osm_net.py      # -> net, net2, net.parquet
uv run --with duckdb --with pandas python scripts/19_osm_paths.py    # snap paths -> platform table
uv run --with duckdb --with pandas python scripts/20_flows.py        # per-way volumes -> flows.parquet

uv run --with duckdb --with numpy --with pandas python scripts/14_platform_build.py   # trips + attributes
uv run --with duckdb python scripts/15_lean_export.py                                 # slim columns
uv run --with duckdb python scripts/16_browser_export.py                              # browser parquet + summary.json
```

> `--add-unique-id=type_id` is **required**. Without it the GeoJSON carries no `id`, every way is
> unnamed, and the flow aggregation silently collapses to a single "way".

## Tests

```bash
cd platform
node tests/verify.mjs         # trip parquet + filter/polygon logic, reconciled against DuckDB
node tests/verify_flows.mjs   # flow parquet + width/colour scaling
node tests/syntax.mjs         # app syntax + every referenced DOM id exists

# real browser (headless Chrome over CDP) — catches what logic tests cannot:
node tests/probe_browser.mjs http://localhost:8765/ /tmp/app.png   # console errors, 404s, DOM state, screenshot
node tests/probe_polygon.mjs                                      # drives the area tool, screenshots mid-draw + finished
```

The logic tests run the page's own code under Node, which **cannot** catch a silent layer failure,
a 404 or a WebGL problem. `probe_browser.mjs` launches the installed Chrome headless
(`--use-angle=swiftshader` for software WebGL — without it MapLibre fails with
`Failed to initialize WebGL`, which looks like an app bug but isn't), collects exceptions, console
errors and any HTTP ≥ 400, then screenshots the result. Use it before claiming a map change works.
