"""Phase-by-phase timing of the routing engine, to find what is slow."""
import time, math, sys
import numpy as np

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
CACHE = f"{D}/db/route_cache_road.npz"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 200

t = time.time(); z = np.load(CACHE)
coords = z['coords']; ce_u, ce_v = z['ce_u'], z['ce_v']; ce_len = z['ce_len']
flat, off, cnodes = z['chain_flat'], z['chain_off'], z['cnodes']
print(f"1. load cache          {time.time()-t:.1f}s  ({len(coords):,} nodes, {len(ce_u):,} edges)", flush=True)

t = time.time()
cmap = {int(n): i for i, n in enumerate(cnodes)}
print(f"2. node map            {time.time()-t:.1f}s", flush=True)

t = time.time()
import igraph as ig
gr = ig.Graph(n=len(cnodes), edges=[(cmap[int(u)], cmap[int(v)]) for u, v in zip(ce_u, ce_v)], directed=False)
gr.es['weight'] = ce_len.tolist()
print(f"3. igraph build        {time.time()-t:.1f}s", flush=True)

t = time.time()
from scipy.spatial import cKDTree
lat0 = math.radians(float(coords[:, 1].mean()))
xy = np.column_stack([coords[:, 0] * 111320.0 * math.cos(lat0), coords[:, 1] * 110540.0])
tree = cKDTree(xy)
print(f"4. KD-tree             {time.time()-t:.1f}s", flush=True)

t = time.time()
node2edge = np.full(coords.shape[0], -1, dtype=np.int64)
for e in range(len(ce_u)):
    for n in flat[off[e]:off[e + 1]]:
        node2edge[n] = e
print(f"5. node->edge map      {time.time()-t:.1f}s", flush=True)

t = time.time()
q = np.array([[19.05, 47.50], [19.06, 47.51], [19.04, 47.49]] * (N // 3))
qs = np.column_stack([q[:, 0] * 111320.0 * math.cos(lat0), q[:, 1] * 110540.0])
d, idx = tree.query(qs)
print(f"6. {len(qs)} snap queries   {time.time()-t:.1f}s  ({1000*(time.time()-t)/len(qs):.2f} ms each)", flush=True)

t = time.time()
for k in range(min(N, 200)):
    gr.get_shortest_paths(0, to=gr.vcount() // 2, weights='weight', output='epath')
print(f"7. 200 dijkstra(epath) {time.time()-t:.1f}s  ({1000*(time.time()-t)/min(N,200):.1f} ms each)", flush=True)

t = time.time()
for k in range(min(N, 200)):
    gr.get_shortest_paths(0, to=gr.vcount() // 2, weights='weight')
print(f"8. 200 dijkstra(vpath) {time.time()-t:.1f}s  ({1000*(time.time()-t)/min(N,200):.1f} ms each)", flush=True)
