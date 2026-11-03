"""Build the BIKE network -> db/graph.duckdb tgbike_nodes / tgbike_edges.

The car network cannot be reused as a bike network: net2 holds only road classes, so the
`highway=cycleway` / `path` / `footway` / `pedestrian` ways that make up most of Budapest's actual
cycling provision are absent from it entirely (checked: 0 of 108,562 have geometry in `geo`). Those
are exported straight from the OSM extract instead.

Network = road ways (with per-way cycling speed, `bicycle=no`/motorway excluded)
        + cycleway / path / footway / pedestrian ways (own geometry, own speed).

Cost is TIME (len_m / speed), not distance: a bike route should trade a longer, calmer way for a
short fast one. Node identity is the 6-dp coordinate, so the two geometry sources join wherever they
share a node — which is how a separate cycleway attaches to the street it runs beside.
"""
import duckdb, json, math, os, subprocess, collections
import numpy as np

D = ("/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/"
     "Transport analysis")
os.chdir(D)
GEOSEQ = "/tmp/bikepaths.geojsonseq"
LAT0 = math.radians(47.5)
M_LON = 111320.0 * math.cos(LAT0)
M_LAT = 110540.0

EXTRA_SPEED = {"cycleway": 19.0, "path": 14.0, "footway": 8.0, "pedestrian": 8.0}
KEYS = {}

def key(lon, lat):
    k = (round(lon, 6), round(lat, 6))
    v = KEYS.get(k)
    if v is None:
        v = len(KEYS)
        KEYS[k] = v
    return v

seg_u, seg_v, seg_len, seg_spd, seg_infra = [], [], [], [], []

def add_way(coords, speed, infra):
    """coords: [[lon,lat], ...]"""
    if len(coords) < 2 or speed <= 0:
        return
    a = key(coords[0][0], coords[0][1])
    for j in range(1, len(coords)):
        b = key(coords[j][0], coords[j][1])
        if a == b:
            a = b
            continue
        dl = (coords[j][0] - coords[j - 1][0]) * M_LON
        dt = (coords[j][1] - coords[j - 1][1]) * M_LAT
        seg_u.append(a); seg_v.append(b)
        seg_len.append(math.hypot(dl, dt)); seg_spd.append(speed); seg_infra.append(infra)
        a = b

# ---- 1. separate bike/pedestrian ways, straight from the extract ----
n_extra = 0
for line in open(GEOSEQ, encoding="utf-8", errors="replace"):
    line = line.strip("\x1e\n")
    if not line or '"w' not in line[:40]:
        continue
    try:
        f = json.loads(line)
    except Exception:
        continue
    if not str(f.get("id", "")).startswith("w"):
        continue
    g = f.get("geometry") or {}
    hw = (f.get("properties") or {}).get("highway")
    if hw not in EXTRA_SPEED:
        continue
    cs = g.get("coordinates")
    if cs is None:
        continue
    parts = [cs] if g.get("type") == "LineString" else cs
    for part in parts:
        add_way(part, EXTRA_SPEED[hw], hw)
    n_extra += 1
print(f"separate cycle/pedestrian ways added: {n_extra:,}", flush=True)

# ---- 2. the road network, with per-way cycling speed ----
con = duckdb.connect(f"{D}/db/osm.duckdb", read_only=True)
rows = con.execute("""
  SELECT g.way_id, g.xy, b.speed, b.infra, b.allowed
  FROM geo g JOIN net2 n USING (way_id)
  JOIN bike_ways b USING (way_id)
  WHERE n.kind='road' AND b.allowed
""").fetchall()
print(f"rideable road ways: {len(rows):,}", flush=True)
sample_xy = rows[0][1]
print("  xy sample type:", type(sample_xy).__name__,
      "first elem:", type(sample_xy[0]).__name__ if len(sample_xy) else "-", flush=True)

def xy_to_coords(xy):
    """geo.xy is either a flat [lon,lat,lon,lat,...] array or a list of points."""
    if len(xy) == 0:
        return []
    e0 = xy[0]
    if isinstance(e0, (int, float)):
        return [[xy[i], xy[i + 1]] for i in range(0, len(xy) - 1, 2)]
    if isinstance(e0, dict):
        return [[p.get("lon", p.get("x")), p.get("lat", p.get("y"))] for p in xy]
    return [[p[0], p[1]] for p in xy]          # tuple / list of pairs

n_road = 0
for way_id, xy, speed, infra, allowed in rows:
    cs = xy_to_coords(xy)
    add_way(cs, float(speed), infra or "none")
    n_road += 1
print(f"road ways added: {n_road:,}", flush=True)

# ---- 3. dedupe, largest component, contract ----
E = len(seg_u)
print(f"raw nodes {len(KEYS):,} | raw segments {E:,}", flush=True)
edges = {}
for i in range(E):
    a, b = seg_u[i], seg_v[i]
    k = (a, b) if a < b else (b, a)
    cur = edges.get(k)
    ln, sp, inf = seg_len[i], seg_spd[i], seg_infra[i]
    if cur is None or ln / sp < cur[0] / cur[1]:
        edges[k] = (ln, sp, inf)
print(f"unique undirected segments: {len(edges):,}", flush=True)

parent = {}
def find(x):
    r = x
    while parent[r] != r: r = parent[r]
    while parent[x] != r: parent[x], x = r, parent[x]
    return r
for a, b in edges:
    parent.setdefault(a, a); parent.setdefault(b, b)
for a, b in edges:
    ra, rb = find(a), find(b)
    if ra != rb: parent[ra] = rb
comp = collections.Counter(find(n) for n in parent)
big, big_n = comp.most_common(1)[0]
before = len(edges)
edges = {k: v for k, v in edges.items() if find(k[0]) == big}
print(f"largest component {big_n:,}/{len(parent):,} nodes; segments {before:,} -> {len(edges):,}", flush=True)

used = set()
for a, b in edges:
    used.add(a); used.add(b)
deg = collections.Counter()
adj = collections.defaultdict(list)
for (a, b), v in edges.items():
    deg[a] += 1; deg[b] += 1
    adj[a].append((b, v)); adj[b].append((a, v))
keep = {n for n in used if deg[n] != 2}
if not keep:
    keep = {next(iter(used))}
seen = set()
cedges = []
for s in keep:
    for nxt, v in adj[s]:
        ek = (s, nxt) if s < nxt else (nxt, s)
        if ek in seen:
            continue
        chain = [s, nxt]
        seen.add(ek)
        prev, cur = s, nxt
        ln = v[0]; sp = v[1]; inf = v[2]
        while cur not in keep:
            nbrs = [x for x in adj[cur] if x[0] != prev]
            if not nbrs:
                break
            nx, vv = nbrs[0]
            ek2 = (cur, nx) if cur < nx else (nx, cur)
            if ek2 in seen:
                break
            seen.add(ek2)
            chain.append(nx); prev, cur = cur, nx
            ln += vv[0]; sp = min(sp, vv[1]); inf = vv[2]
        cedges.append((s, cur, ln, ln / (sp / 3.6), sp, inf, chain))
# segments that never reached a 'keep' node (pure loops) — walk them too
print(f"contracted bike edges: {len(cedges):,}", flush=True)

km = collections.Counter()
for _, _, ln, _, _, inf, _ in cedges:
    km[inf] += ln / 1000.0
print("\n=== bike network in the largest component, by provision ===")
tot = 0
for k, v in km.most_common():
    print(f"  {k:12s} {v:9.1f} km")
    tot += v
print(f"  {'TOTAL':12s} {tot:9.1f} km")

# Write PARQUET, not a table: `executemany` with a list column serialises every row's list
# individually — 359k rows of BIGINT[] took over 15 minutes and held the database lock the whole
# time, blocking every reader. Registering a DataFrame and COPYing is seconds.
import pandas as pd
w = duckdb.connect()
w.register("df_n", pd.DataFrame([{"id": i, "lon": k[0], "lat": k[1]}
                                 for k, i in KEYS.items() if i in used]))
w.execute(f"COPY (SELECT * FROM df_n ORDER BY id) TO '{D}/db/tgbike_nodes.parquet' "
          f"(FORMAT PARQUET, COMPRESSION ZSTD)")
w.register("df_e", pd.DataFrame([{"eid": i, "u": a, "v": b, "len_m": ln, "speed": sp, "weight": wt,
                                  "infra": inf, "nodes": ch}
                                 for i, (a, b, ln, wt, sp, inf, ch) in enumerate(cedges)]))
w.execute(f"COPY (SELECT * FROM df_e ORDER BY eid) TO '{D}/db/tgbike_edges.parquet' "
          f"(FORMAT PARQUET, COMPRESSION ZSTD)")
print(f"\nwrote db/tgbike_nodes.parquet ({len(used):,}) / db/tgbike_edges.parquet ({len(cedges):,})")
print(f"  {os.path.getsize(f'{D}/db/tgbike_edges.parquet')/1e6:.1f} MB")
