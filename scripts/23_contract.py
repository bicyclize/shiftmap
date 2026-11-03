"""Contract the segment graph: drop tiny components, merge degree-2 chains into single edges.

Why: (a) correctness — snapped points landing in disconnected fragments make ~10% of routes
unroutable; (b) speed — Dijkstra explores nodes, and ~80% of road nodes are degree-2 shape
points; (c) it yields the compact edge-with-polyline structure needed to ship routes.
"""
import duckdb, time, sys
from collections import defaultdict

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
KIND = sys.argv[1] if len(sys.argv) > 1 else 'road'
t0 = time.time()

g = duckdb.connect(f"{D}/db/graph.duckdb")
edges = g.execute("SELECT a, b, len_m, way_id FROM edges WHERE kind = ?", [KIND]).fetchall()
print(f"{KIND}: {len(edges):,} segments  ({time.time()-t0:.0f}s)")

adj = defaultdict(list)
for i, (a, b, l, w) in enumerate(edges):
    adj[a].append((b, l, i)); adj[b].append((a, l, i))
print(f"nodes touched: {len(adj):,}")

# ---- giant connected component ----
seen = set(); best = []
for s in adj:
    if s in seen: continue
    comp = []; stack = [s]; seen.add(s)
    while stack:
        x = stack.pop(); comp.append(x)
        for (y, _, _) in adj[x]:
            if y not in seen: seen.add(y); stack.append(y)
    if len(comp) > len(best): best = comp
giant = set(best)
print(f"components: giant = {len(giant):,} nodes; dropping {len(adj)-len(giant):,} in fragments")
adj = {n: v for n, v in adj.items() if n in giant}

# ---- contract degree-2 chains ----
deg = {n: len(v) for n, v in adj.items()}
used = set(); chains = []

def walk(start, first_edge):
    total = 0.0; nodes_chain = [start]; cur = start; e = first_edge
    while True:
        used.add(e)
        a, b, l, w = edges[e]
        nxt = b if a == cur else a
        total += l; nodes_chain.append(nxt)
        if deg.get(nxt, 0) != 2: break
        nxt_e = None
        for (y, _, ee) in adj[nxt]:
            if ee != e: nxt_e = ee; break
        if nxt_e is None: break
        cur, e = nxt, nxt_e
    return nodes_chain, total

for s in list(adj.keys()):
    if deg[s] == 2: continue
    for (y, _, e) in adj[s]:
        if e not in used:
            nc, tl = walk(s, e)
            chains.append((nc[0], nc[-1], nc, tl))

# pure cycles (every node degree 2) never touched above
for e in range(len(edges)):
    if e in used: continue
    a, b, _, _ = edges[e]
    if a not in adj: used.add(e); continue
    nc, tl = walk(a, e)
    chains.append((nc[0], nc[-1], nc, tl))

print(f"contracted edges: {len(chains):,}  (from {len(edges):,} segments)")

cnodes = sorted({n for u, v, nc, _ in chains for n in (u, v)})
# NB: c*_edges.u/v must be ORIGINAL node ids (consistent with c*_nodes, and node_ids below),
# NOT indices into cnodes — mixing the two silently breaks every lookup.
crows = [(u, v, tl, len(nc), nc) for u, v, nc, tl in chains]

import pandas as pd
g.execute("CREATE OR REPLACE TABLE c%s_nodes(id BIGINT)" % KIND)
g.register('df_cn', pd.DataFrame({'id': cnodes}))
g.execute(f"INSERT INTO c{KIND}_nodes SELECT id FROM df_cn")
g.execute(f"CREATE OR REPLACE TABLE c{KIND}_edges(u BIGINT, v BIGINT, len_m DOUBLE, n BIGINT, node_ids BIGINT[])")
g.register('df_ce', pd.DataFrame(crows, columns=['u', 'v', 'len_m', 'n', 'node_ids']))
g.execute(f"INSERT INTO c{KIND}_edges SELECT u, v, len_m, n, node_ids FROM df_ce")
print(f"wrote c{KIND}_edges / c{KIND}_nodes  ({time.time()-t0:.0f}s)")
print(g.execute(f"SELECT count(*) contracted_edges, round(sum(len_m)/1000) km FROM c{KIND}_edges").df().to_string())
