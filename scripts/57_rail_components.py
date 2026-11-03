"""Why do 58% of rail-classified trips now fail to route on the passenger rail graph?

Two candidate explanations, with very different implications:
  (a) the trip's two ends sit on DIFFERENT guided systems (tram vs metro vs MAV) -> genuine, and
      the trip is an interchange trip that no single network can represent;
  (b) the graph is FRAGMENTED into 94 pieces, so a tram line is split by data gaps and even a
      plain tram trip cannot route -> a data problem worth fixing.

Snaps each rail-classified trip's ends to the passenger rail graph and reports which component
each end lands in.
"""
import duckdb, os, math
import numpy as np
from collections import defaultdict, Counter

D = ("/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/"
     "Transport analysis")
os.chdir(D)
SNAP_MAX_M = 800.0

g = duckdb.connect("db/graph.duckdb", read_only=True)
nd = g.execute("SELECT id, lon, lat FROM tgrail_nodes ORDER BY id").fetchall()
coords = np.array([[r[1], r[2]] for r in nd])
ce = g.execute("SELECT eid, u, v, len_m, cls, nodes FROM tgrail_edges ORDER BY eid").fetchall()
print(f"rail graph: {len(nd):,} nodes, {len(ce):,} edges")

# union-find over the rail graph
parent = {}
def find(x):
    r = x
    while parent[r] != r: r = parent[r]
    while parent[x] != r: parent[x], x = r, parent[x]
    return r
for eid, u, v, ln, cls, ch in ce:
    parent.setdefault(u, u); parent.setdefault(v, v)
for eid, u, v, ln, cls, ch in ce:
    ra, rb = find(u), find(v)
    if ra != rb: parent[ra] = rb
comp_of = {n: find(n) for n in parent}
sizes = Counter(comp_of.values())
print(f"components: {len(sizes)}  sizes {sizes.most_common(6)}")

# label the big components by their dominant class
cls_of_comp = defaultdict(Counter)
for eid, u, v, ln, cls, ch in ce:
    cls_of_comp[find(u)][cls] += 1
big = [c for c, _ in sizes.most_common(8)]
print("\nlargest components by dominant class:")
for c in big:
    dom = cls_of_comp[c].most_common(1)[0][0]
    print(f"  {sizes[c]:6,} nodes  mostly {dom}")

# snap helper
lat0 = math.radians(float(coords[:, 1].mean())); cosl = math.cos(lat0)
flat, offs = [], [0]
for eid, u, v, ln, cls, ch in ce:
    flat.extend(ch); offs.append(len(flat))
flat = np.array(flat, dtype=np.int64); offs = np.array(offs, dtype=np.int64)
node2edge = np.full(coords.shape[0], -1, dtype=np.int64)
node2edge[flat] = np.repeat(np.arange(len(ce), dtype=np.int64), np.diff(offs))
xy = np.column_stack([coords[:, 0] * 111320.0 * cosl, coords[:, 1] * 110540.0])
from scipy.spatial import cKDTree
tree = cKDTree(xy)

def snap(lo, la):
    d, j = tree.query([lo * 111320.0 * cosl, la * 110540.0])
    if d > SNAP_MAX_M: return None
    nid = int(j)
    return comp_of.get(int(nd[nid][0]), None), d, cls_of_comp.get(comp_of.get(int(nd[nid][0]), -1),
                                                                   Counter()).most_common(1)

c = duckdb.connect("db/osm.duckdb", read_only=True)
rows = c.execute("""
  SELECT row_number() OVER () - 1 AS i, o_lon, o_lat, d_lon, d_lat FROM platform
""").fetchall()
mode = {r[0]: r[1] for r in c.execute(
    "SELECT i, mode FROM read_parquet('platform/rail_mode.parquet')").fetchall()}
rail_idx = [i for i, m in mode.items() if m == 'rail']
print(f"\nrail-classified trips: {len(rail_idx):,}")

by = {r[0]: r for r in rows}
same = diff = nosnap = 0
pairs = Counter()
for i in rail_idx:
    r = by.get(i)
    if r is None: continue
    so = snap(r[1], r[2]); sd = snap(r[3], r[4])
    if so is None or sd is None:
        nosnap += 1; continue
    if so[0] == sd[0]:
        same += 1
    else:
        diff += 1
        pairs[(so[2][0][0] if so[2] else '?', sd[2][0][0] if sd[2] else '?')] += 1

tot = same + diff + nosnap
print(f"\n  both ends in the SAME component : {same:,}  ({same/tot*100:.1f}%)")
print(f"  ends in DIFFERENT components    : {diff:,}  ({diff/tot*100:.1f}%)")
print(f"  an end has no rail within 800 m : {nosnap:,}  ({nosnap/tot*100:.1f}%)")
print("\n  most common cross-system pairs (origin system -> destination system):")
for (a, b), n in pairs.most_common(10):
    print(f"    {a:12s} -> {b:12s} {n:6,}")
