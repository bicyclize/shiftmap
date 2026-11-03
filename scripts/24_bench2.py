"""Benchmark routing on the CONTRACTED graph, and test multiprocessing scaling."""
import duckdb, time, math, sys
import igraph as ig

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 200
KIND = sys.argv[2] if len(sys.argv) > 2 else 'road'
t0 = time.time()

g = duckdb.connect(f"{D}/db/graph.duckdb")
cn = [r[0] for r in g.execute(f"SELECT id FROM c{KIND}_nodes").fetchall()]
ce = g.execute(f"SELECT u, v, len_m FROM c{KIND}_edges").fetchall()
cmap = {n: i for i, n in enumerate(cn)}
print(f"contracted {KIND}: {len(cn):,} nodes, {len(ce):,} edges  ({time.time()-t0:.0f}s)")

gr = ig.Graph(n=len(cn), edges=[(cmap[u], cmap[v]) for u, v, _ in ce], directed=False)
gr.es['weight'] = [l for _, _, l in ce]
print(f"igraph built  ({time.time()-t0:.0f}s)")

# node coordinates for snapping (original node ids carry lon/lat)
coords = g.execute("SELECT id, lon, lat FROM nodes").fetchall()
lon = {i: x for i, x, y in coords}; lat = {i: y for i, x, y in coords}
CELL = 0.01
grid = {}
for i, n in enumerate(cn):
    grid.setdefault((int(lat[n]/CELL), int(lon[n]/CELL)), []).append(i)

def snap(lo, la):
    ci, cj = int(la/CELL), int(lo/CELL)
    if (ci, cj) not in grid and not any((ci+di, cj+dj) in grid for di in (-1,0,1) for dj in (-1,0,1)):
        return None
    best, bd = None, 1e18
    for di in (-2,-1,0,1,2):
        for dj in (-2,-1,0,1,2):
            for i in grid.get((ci+di, cj+dj), ()):
                n = cn[i]
                dy = (lat[n]-la)*110540.0
                dx = (lon[n]-lo)*111320.0*math.cos(math.radians(la))
                d = dx*dx+dy*dy
                if d < bd: bd, best = d, i
    return best if bd < 90_000_000 else None     # reject snaps > ~9.5 km

p = duckdb.connect(f"{D}/db/osm.duckdb")
trips = p.execute(f"""SELECT o_lon,o_lat,d_lon,d_lat FROM platform
                      WHERE od_m BETWEEN 3000 AND 40000 USING SAMPLE {N} ROWS""").fetchall()

snapped = [(snap(a, b), snap(c, d)) for a, b, c, d in trips]
ok = sum(1 for s, t in snapped if s is not None and t is not None and s != t)
print(f"sampled {len(trips)} trips | snapped ok {ok} | unsnappable {len(trips)-ok}")

ok = fail = 0; lens = []
t0 = time.time()
for s, t in snapped:
    if s is None or t is None or s == t: fail += 1; continue
    r = gr.get_shortest_paths(s, to=t, weights='weight')[0]
    if not r: fail += 1
    else: ok += 1; lens.append(len(r))
el = time.time() - t0
print(f"\nrouted {ok} ok / {fail} failed in {el:.1f}s")
if ok:
    per = el/ok
    print(f"per route        : {per*1000:.1f} ms   (was 84.2 ms uncontracted)")
    print(f"median hops      : {sorted(lens)[len(lens)//2]}")
    print(f"single process   : {per*440516/3600:.1f} h for 440,516 routes")
    print(f"8 processes (est): {per*440516/8/60:.1f} min")
