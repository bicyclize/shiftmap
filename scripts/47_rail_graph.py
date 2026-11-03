"""Build a routable RAIL graph (tram / metro / HÉV / rail) -> db/graph.duckdb.

A trip whose GPS followed a guideway must be routed along the guideway, not along whatever roads
happen to connect its two ends. Without this, a tram ride is drawn crossing a motorway.

Same segment-graph scheme as the road graph, so routing and geometry reconstruction are identical:
every coordinate becomes a node (deduped by rounded lat/lon), consecutive coordinates within a way
become edges, only the largest connected component is kept, and degree-2 chains are contracted.

No turn restrictions: they are a road concept. A tram follows its track, and OSM maps tram
restrictions very sparsely; treating rail as restriction-free is the honest approximation.
Writes tgrail_edges / tgrail_nodes.
"""
import duckdb, math, time
from collections import defaultdict

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"

con = duckdb.connect(f"{D}/db/osm.duckdb", read_only=True)
t0 = time.time()
rows = con.execute("""
  SELECT g.way_id, n.cls, g.xy FROM geo g JOIN net2 n USING (way_id)
  WHERE n.kind='rail'
    AND g.way_id IN (SELECT way_id FROM rail_passenger WHERE passenger)
""").fetchall()
print("  (passenger-only: depot/stabling sidings, yards, crossovers and platform edges excluded)")
print(f"rail ways: {len(rows):,}  ({time.time()-t0:.0f}s)")

node_of, nodes, edges = {}, [], []
def nid(lon, lat):
    key = (round(lat, 6), round(lon, 6))
    i = node_of.get(key)
    if i is None:
        i = len(nodes); node_of[key] = i; nodes.append((lon, lat))
    return i

for way_id, cls, xy in rows:
    prev = None
    for k in range(0, len(xy) - 1, 2):
        cur = nid(xy[k], xy[k + 1])
        if prev is not None and prev != cur:
            lon1, lat1 = nodes[prev]; lon2, lat2 = nodes[cur]
            dy = (lat2 - lat1) * 110540.0
            dx = (lon2 - lon1) * 111320.0 * math.cos(math.radians((lat1 + lat2) / 2.0))
            d = math.hypot(dx, dy)
            if d > 0:
                edges.append((prev, cur, d, cls))
        prev = cur
print(f"raw nodes {len(nodes):,} | raw edges {len(edges):,}  ({time.time()-t0:.0f}s)")

# --- DO NOT keep only the largest component here ---
# The guided systems are PHYSICALLY SEPARATE: tram, metro, HEV and MAV have no passenger track in
# common. The only things that used to join them were the depot and stabling connections
# (service=yard/spur/siding/crossover) — the very ways that drew the bogus loop. Filtering to the
# largest component would therefore silently discard every system except one.
# Instead keep every component and let routing fail honestly: if a trip's two ends sit on different
# systems it cannot be a single guideway trip, and it keeps its road route.
parent = {}
def find(x):
    r = x
    while parent[r] != r: r = parent[r]
    while parent[x] != r: parent[x], x = r, parent[x]
    return r
for a, b, *_ in edges:
    parent.setdefault(a, a); parent.setdefault(b, b)
for a, b, *_ in edges:
    ra, rb = find(a), find(b)
    if ra != rb: parent[ra] = rb
from collections import Counter
comp = Counter(find(n) for n in parent)
sizes = comp.most_common()
print(f"rail components: {len(sizes)}  (largest {sizes[0][1]:,} nodes, "
      f"top5 {[s for _, s in sizes[:5]]})")
print("  keeping ALL components — each guided system is its own network")

deg = defaultdict(int); inc = defaultdict(list)
for i, (a, b, *_) in enumerate(edges):
    deg[a] += 1; deg[b] += 1; inc[a].append(i); inc[b].append(i)
keeps = {n for n, d in deg.items() if d != 2}
print(f"keep {len(keeps):,} nodes of {len(nodes):,}")

visited = [False] * len(edges)
out_edges = []
def other(e, n): return e[1] if e[0] == n else e[0]

for start in range(len(edges)):
    if visited[start]: continue
    a0, b0 = edges[start][0], edges[start][1]
    if a0 not in keeps and b0 not in keeps: continue
    u = a0 if a0 in keeps else b0
    chain = [start]; visited[start] = True
    cur = other(edges[start], u)
    while cur not in keeps:
        nxt = next((j for j in inc[cur] if not visited[j]), None)
        if nxt is None: break
        visited[nxt] = True; chain.append(nxt)
        cur = other(edges[nxt], cur)
    seq = [u]
    for j in chain: seq.append(other(edges[j], seq[-1]))
    by_cls = defaultdict(float)
    for j in chain: by_cls[edges[j][3]] += edges[j][2]
    out_edges.append((u, cur, sum(edges[j][2] for j in chain), max(by_cls, key=by_cls.get), seq))
for i in range(len(edges)):
    if not visited[i]:
        a, b, ln, cls = edges[i]
        out_edges.append((a, b, ln, cls, [a, b]))

print(f"contracted rail edges: {len(out_edges):,}  ({time.time()-t0:.0f}s)")

import pandas as pd
g = duckdb.connect(f"{D}/db/graph.duckdb")
g.execute("CREATE OR REPLACE TABLE tgrail_nodes(id BIGINT, lon DOUBLE, lat DOUBLE)")
g.register('dn', pd.DataFrame({'id': range(len(nodes)), 'lon': [n[0] for n in nodes], 'lat': [n[1] for n in nodes]}))
g.execute("INSERT INTO tgrail_nodes SELECT id, lon, lat FROM dn")
g.execute("CREATE OR REPLACE TABLE tgrail_edges(eid BIGINT, u BIGINT, v BIGINT, len_m DOUBLE, cls VARCHAR, nodes BIGINT[])")
g.register('de', pd.DataFrame([{'eid': i, 'u': e[0], 'v': e[1], 'len_m': e[2], 'cls': e[3], 'nodes': e[4]}
                               for i, e in enumerate(out_edges)]))
g.execute("INSERT INTO tgrail_edges SELECT eid, u, v, len_m, cls, nodes FROM de")
print("\n=== contracted rail edges by class ===")
print(g.execute("""SELECT cls, count(*) edges, round(sum(len_m)/1000) km
                   FROM tgrail_edges GROUP BY 1 ORDER BY 3 DESC""").df().to_string(index=False))
print(f"\nwrote tgrail_nodes / tgrail_edges  ({time.time()-t0:.0f}s)")
