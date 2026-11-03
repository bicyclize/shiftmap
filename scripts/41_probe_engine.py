"""Time each stage of the turn-restricted engine, to find what made the 2k-trip test take minutes."""
import time, importlib.util, numpy as np

P = ("/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/"
     "Transport analysis/scripts/40_route_turns.py")
spec = importlib.util.spec_from_file_location("r40", P)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

t = time.time(); z = np.load(m.CACHE); print(f"load cache      {time.time()-t:6.1f}s  ({z['ce_u'].shape[0]:,} edges, {len(z['copy_node']):,} copies, "
      f"{len(z['forbid']):,} forbidden)", flush=True)

import igraph as ig
from scipy.spatial import cKDTree
from collections import defaultdict

t = time.time()
coords = z['coords']; cnodes = z['cnodes']; B = len(cnodes)
cmap = {int(n): i for i, n in enumerate(cnodes)}
print(f"base maps       {time.time()-t:6.1f}s  (B={B:,})", flush=True)

t = time.time()
split_nodes = set(int(x) for x in z['split_nodes'])
copy_node = z['copy_node']; copy_edge = z['copy_edge']
copy_of = {(int(copy_node[i]), int(copy_edge[i])): i for i in range(len(copy_node))}
print(f"copy map        {time.time()-t:6.1f}s", flush=True)

E = len(z['ce_u'])
t = time.time()
src, dst, wts = [], [], []
ce_u = z['ce_u'].tolist(); ce_v = z['ce_v'].tolist()
ce_len = z['ce_len'].tolist(); ce_spd = z['ce_spd'].tolist()
print(f"  tolist()      {time.time()-t:6.1f}s", flush=True)
t = time.time()
for eid in range(E):
    u, v = ce_u[eid], ce_v[eid]
    vu = B + copy_of[(u, eid)] if u in split_nodes else cmap[u]
    vv = B + copy_of[(v, eid)] if v in split_nodes else cmap[v]
    w = ce_len[eid] * 3.6 / ce_spd[eid]
    src.append(vu); dst.append(vv); wts.append(w)
    src.append(vv); dst.append(vu); wts.append(w)
print(f"edge arcs       {time.time()-t:6.1f}s  ({len(src):,})", flush=True)

t = time.time()
node_copies = defaultdict(list)
for i in range(len(copy_node)):
    node_copies[int(copy_node[i])].append(i)
fb = set(map(tuple, z['forbid'].tolist()))
ncon = 0
for nd in split_nodes:
    idxs = node_copies[nd]
    if len(idxs) < 2: continue
    for i in idxs:
        for j in idxs:
            if i == j or (i, j) in fb: continue
            src.append(B + i); dst.append(B + j); wts.append(0.0); ncon += 1
print(f"connectors      {time.time()-t:6.1f}s  ({ncon:,} connectors, {len(src):,} arcs total)", flush=True)

t = time.time()
gr = ig.Graph(n=B + len(copy_node), edges=list(zip(src, dst)), directed=True)
gr.es['weight'] = wts
print(f"igraph build    {time.time()-t:6.1f}s  ({gr.vcount():,} vertices, {gr.ecount():,} edges)", flush=True)

t = time.time()
lat0 = np.radians(float(coords[:, 1].mean()))
xy = np.column_stack([coords[:, 0] * 111320.0 * np.cos(lat0), coords[:, 1] * 110540.0])
node2edge = np.full(coords.shape[0], -1, dtype=np.int64)
off, cflat = z['chain_off'], z['chain_flat']
node2edge[cflat] = np.repeat(np.arange(E, dtype=np.int64), np.diff(off))
valid = np.where(node2edge >= 0)[0]
tree = cKDTree(xy[valid])
print(f"kd-tree         {time.time()-t:6.1f}s  ({len(valid):,} routable nodes)", flush=True)

# --- time the actual Dijkstra on this graph ---
t = time.time(); N = 50
rng = np.random.default_rng(0)
sample = rng.choice(valid, size=N * 2, replace=False)
got = 0
for k in range(N):
    a, b = int(node2edge[sample[2 * k]]), int(node2edge[sample[2 * k + 1]])
    va = B + copy_of.get((int(ce_u[a]), a), 0)
    vb = B + copy_of.get((int(ce_v[b]), b), 0)
    try:
        r = gr.get_shortest_paths(va, to=vb, weights='weight', output='epath', mode='out')
        if r and r[0]: got += 1
    except Exception as e:
        pass
el = time.time() - t
print(f"dijkstra        {el:6.1f}s for {N} routes = {1000*el/max(N,1):.0f} ms/route  ({got} found)", flush=True)
print(f"\nprojected full run: {1000*el/max(N,1)*438995/1000/3600:.1f} h single-process, "
      f"{1000*el/max(N,1)*438995/1000/3600/8:.1f} h on 8 cores")
