"""Benchmark: can a custom Dijkstra route 440k trips? Measures real trips snapped to the graph."""
import duckdb, time, math, random, sys

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 300

g = duckdb.connect(f"{D}/db/graph.duckdb")
t0 = time.time()
nodes = g.execute("SELECT id, lon, lat FROM nodes").fetchall()
edges = g.execute("SELECT a, b, len_m, kind FROM edges").fetchall()
print(f"graph: {len(nodes):,} nodes, {len(edges):,} edges  ({time.time()-t0:.0f}s)")

import igraph as ig
road = [(a, b, w) for a, b, w, k in edges if k == 'road']
rail = [(a, b, w) for a, b, w, k in edges if k == 'rail']
print(f"road edges {len(road):,} | rail edges {len(rail):,}")

gr = ig.Graph(n=len(nodes), edges=[(a, b) for a, b, _ in road], directed=False)
gr.es['weight'] = [w for _, _, w in road]
print(f"igraph road built  ({time.time()-t0:.0f}s)")

# grid index for snapping
CELL = 0.01
grid = {}
for i, (_, lon, lat) in enumerate(nodes):
    grid.setdefault((int(lat/CELL), int(lon/CELL)), []).append(i)

def snap(lon, lat):
    ci, cj = int(lat/CELL), int(lon/CELL)
    best, bd = None, 1e18
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            for i in grid.get((ci+di, cj+dj), ()):
                _, nlon, nlat = nodes[i]
                dy = (nlat-lat)*110540.0
                dx = (nlon-lon)*111320.0*math.cos(math.radians(lat))
                d = dx*dx+dy*dy
                if d < bd: bd, best = d, i
    return best

p = duckdb.connect(f"{D}/db/osm.duckdb")
trips = p.execute(f"""SELECT o_lon,o_lat,d_lon,d_lat FROM platform
                      WHERE od_m BETWEEN 3000 AND 40000 USING SAMPLE {N} ROWS""").fetchall()
print(f"sampled {len(trips)} real trips (3-40 km)")

t0 = time.time()
snapped = [(snap(a, b), snap(c, d)) for a, b, c, d in trips]
print(f"snapped in {time.time()-t0:.1f}s")

ok = fail = 0
lens = []
t0 = time.time()
for s, t in snapped:
    if s is None or t is None or s == t:
        fail += 1; continue
    r = gr.get_shortest_paths(s, to=t, weights='weight')[0]   # the real operation we need
    if not r:
        fail += 1
    else:
        ok += 1
        lens.append(len(r))

el = time.time()-t0
print(f"\nrouted {ok} ok / {fail} failed in {el:.1f}s")
if ok:
    per = el/ok
    print(f"per route: {per*1000:.1f} ms")
    print(f"median nodes in path: {sorted(lens)[len(lens)//2]}")
    print(f"=> 440,516 routes would take {per*440516/3600:.1f} hours")
