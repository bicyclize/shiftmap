"""Rebuild the road graph with everything the routing fix needs:

  * per-edge road CLASS  -> cost can prefer arterials over side streets
  * per-edge WAY ID at each end -> a turn restriction can be matched to the edges that meet at a node
  * restriction via-nodes kept NON-CONTRACTIBLE -> a restriction always lands on a real graph node

Without the last point, degree-2 contraction would swallow the very junction the restriction is
about, and the restriction could never be applied.

Writes to db/graph.duckdb: tgraph_nodes, tgraph_edges, trestrictions.
"""
import duckdb, math, time, json
from collections import defaultdict

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
SC = "/Users/peterbiczok/.hermes/cache/scratch"

VIA = json.load(open(f"{SC}/buda_via_coords.json"))                  # osm node id -> [lon, lat]
REST = json.load(open(f"{SC}/buda_restrictions.json"))               # [{kind, from, to, via_node}]

# --- speed by class (km/h). Routing minimises TIME, which is what makes an arterial cheaper than a
# --- parallel side street and stops the router cutting through residential streets to save metres.
SPEED = {
    'motorway': 100, 'motorway_link': 70, 'trunk': 80, 'trunk_link': 60,
    'primary': 60, 'primary_link': 45, 'secondary': 50, 'secondary_link': 40,
    'tertiary': 45, 'tertiary_link': 35, 'unclassified': 40, 'residential': 30,
    'living_street': 15, 'service': 15, 'road': 25, 'track': 15, 'path': 10,
}
DEFAULT_SPEED = 25.0

con = duckdb.connect(f"{D}/db/osm.duckdb", read_only=True)
t0 = time.time()
rows = con.execute("SELECT g.way_id, n.cls, g.xy FROM geo g JOIN net2 n USING (way_id) WHERE n.kind='road'").fetchall()
print(f"road ways read: {len(rows):,}  ({time.time()-t0:.0f}s)")

node_of, nodes = {}, []
edges = []                              # (a, b, len_m, way_id, cls)

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
                edges.append((prev, cur, d, way_id, cls))
        prev = cur
print(f"nodes {len(nodes):,} | edges {len(edges):,}  ({time.time()-t0:.0f}s)")

# ---- which nodes must survive contraction? ----
# NB: the extract's node positions differ from today's Overpass snapshot by up to ~1 m (OSM nodes
# get nudged), so an exact rounded-coordinate key match finds almost nothing. Match to the NEAREST
# graph coordinate within a small tolerance instead.
TOL_M = 8.0
bucket = defaultdict(list)               # ~11 m cell -> [(node id, lon, lat)]
for i, (lon, lat) in enumerate(nodes):
    bucket[(round(lat, 4), round(lon, 4))].append((i, lon, lat))

def nearest_node(lon, lat):
    kl = round(lat, 4); ko = round(lon, 4)
    best, bestd = None, 1e18
    coslat = math.cos(math.radians(lat))
    for dlat in (-0.0001, 0.0, 0.0001):
        for dlon in (-0.0001, 0.0, 0.0001):
            for i, glon, glat in bucket.get((round(kl + dlat, 4), round(ko + dlon, 4)), ()):
                dy = (glat - lat) * 110540.0
                dx = (glon - lon) * 111320.0 * coslat
                d = math.hypot(dx, dy)
                if d < bestd: bestd, best = d, i
    return (best, bestd) if best is not None and bestd <= TOL_M else (None, bestd)

rest_nodes = {}                          # graph node id -> set of osm via node ids
via_g = {}                               # osm via id -> graph node id
outside = 0
for rid, co in VIA.items():
    lon, lat = co
    g, _d = nearest_node(lon, lat)
    if g is None: outside += 1; continue
    via_g[str(rid)] = g
    rest_nodes.setdefault(g, set()).add(int(rid))
print(f"restriction via nodes: {len(VIA)}  mapped into the graph: {len(rest_nodes)}  outside: {outside}")

deg = defaultdict(int)
inc = defaultdict(list)
for i, (a, b, *_ ) in enumerate(edges):
    deg[a] += 1; deg[b] += 1; inc[a].append(i); inc[b].append(i)

keeps = set(rest_nodes) | {n for n, dgr in deg.items() if dgr != 2}
print(f"nodes kept through contraction: {len(keeps):,} of {len(nodes):,}")

# ---- contract degree-2 chains, recording way identity at BOTH ends ----
visited = [False] * len(edges)
out_edges = []
chain_of_node = {}                       # every original node -> (new edge idx, order in the chain)

def other(e, n): return e[1] if e[0] == n else e[0]

for start in range(len(edges)):
    if visited[start]: continue
    a0, b0 = edges[start][0], edges[start][1]
    if a0 not in keeps and b0 not in keeps:
        continue
    u = a0 if a0 in keeps else b0
    chain = [start]; visited[start] = True
    cur = other(edges[start], u)
    while cur not in keeps:
        nxt = None
        for j in inc[cur]:
            if not visited[j]:
                nxt = j; break
        if nxt is None: break
        visited[nxt] = True
        chain.append(nxt)
        cur = other(edges[nxt], cur)
    v = cur
    nodes_seq = [u]
    for j in chain:
        nodes_seq.append(other(edges[j], nodes_seq[-1]))
    total = sum(edges[j][2] for j in chain)
    by_cls = defaultdict(float)
    for j in chain: by_cls[edges[j][4]] += edges[j][2]
    cls = max(by_cls, key=by_cls.get)
    ei = len(out_edges)
    out_edges.append((u, v, total, cls, edges[chain[0]][3], edges[chain[-1]][3], nodes_seq))
    for pos, n in enumerate(nodes_seq):
        chain_of_node.setdefault(n, (ei, pos))

# any edge left over sits on a pure loop with no keep node — emit it standalone
for i in range(len(edges)):
    if not visited[i]:
        visited[i] = True
        a, b, ln, w, c = edges[i]
        ei = len(out_edges)
        out_edges.append((a, b, ln, c, w, w, [a, b]))
        chain_of_node.setdefault(a, (ei, 0)); chain_of_node.setdefault(b, (ei, 1))

print(f"contracted edges: {len(out_edges):,}  ({time.time()-t0:.0f}s)")

# ---- resolve each restriction to the pair of ways that meet at its via node ----
adj_at = defaultdict(list)               # graph node -> [(edge idx, way id adjacent to that node)]
for ei, (u, v, ln, c, uw, vw, seq) in enumerate(out_edges):
    adj_at[u].append((ei, uw))
    adj_at[v].append((ei, vw))

# osmium writes ids as 'w1169807620'; Overpass writes 1169807620 — normalise before comparing.
def norm_way(v):
    s = str(v)
    return s[1:] if s[:1] in ('w', 'n', 'r') else s

resolved, unresolvable, why = [], 0, defaultdict(int)
for r in REST:
    if not r.get('via_node'): why['no via node'] += 1; continue
    g = via_g.get(str(r['via_node']))
    if g is None: unresolvable += 1; why['via node outside network'] += 1; continue
    inc_ways = adj_at.get(g, [])
    fw, tw = norm_way(r['from']), norm_way(r['to'])
    from_e = [e for e, w in inc_ways if norm_way(w) == fw]
    to_e   = [e for e, w in inc_ways if norm_way(w) == tw]
    if not from_e or not to_e:
        why['from/to way not incident at the node'] += 1
        unresolvable += 1
        continue
    if not from_e or not to_e: unresolvable += 1; continue
    resolved.append({'node': g, 'kind': r['kind'], 'from_edges': from_e, 'to_edges': to_e})
print(f"restrictions resolved to graph edges: {len(resolved):,}  unresolvable: {unresolvable}")
for k, v in sorted(why.items(), key=lambda x: -x[1]): print(f"    {k}: {v}")

# ---- write it all out ----
g = duckdb.connect(f"{D}/db/graph.duckdb")
g.execute("CREATE OR REPLACE TABLE tgraph_nodes(id BIGINT, lon DOUBLE, lat DOUBLE)")
g.execute("CREATE OR REPLACE TABLE tgraph_edges(eid BIGINT, u BIGINT, v BIGINT, len_m DOUBLE, cls VARCHAR, "
          "u_way VARCHAR, v_way VARCHAR, nodes BIGINT[])")
g.execute("CREATE OR REPLACE TABLE tgraph_chain(node BIGINT, eid BIGINT, pos BIGINT)")
g.execute("CREATE OR REPLACE TABLE trestrictions(node BIGINT, kind VARCHAR, from_edges BIGINT[], to_edges BIGINT[])")
import pandas as pd
g.register('dn', pd.DataFrame({'id': range(len(nodes)), 'lon': [n[0] for n in nodes], 'lat': [n[1] for n in nodes]}))
g.execute("INSERT INTO tgraph_nodes SELECT id, lon, lat FROM dn")
g.register('de', pd.DataFrame([{'eid': i, 'u': e[0], 'v': e[1], 'len_m': e[2], 'cls': e[3],
                                'u_way': str(e[4]), 'v_way': str(e[5]), 'nodes': e[6]}
                               for i, e in enumerate(out_edges)]))
g.execute("INSERT INTO tgraph_edges SELECT eid, u, v, len_m, cls, u_way, v_way, nodes FROM de")
g.register('dc', pd.DataFrame([{'node': n, 'eid': ei, 'pos': p} for n, (ei, p) in chain_of_node.items()]))
g.execute("INSERT INTO tgraph_chain SELECT node, eid, pos FROM dc")
g.register('dr', pd.DataFrame(resolved))
g.execute("INSERT INTO trestrictions SELECT node, kind, from_edges, to_edges FROM dr")

print("\n=== contracted edges by class ===")
print(g.execute("""SELECT cls, count(*) edges, round(sum(len_m)/1000) km,
  round(100.0*sum(len_m)/sum(sum(len_m)) OVER (),1) pct FROM tgraph_edges GROUP BY 1 ORDER BY 3 DESC""").df().to_string(index=False))
print("\n=== restrictions by kind ===")
print(g.execute("SELECT kind, count(*) n FROM trestrictions GROUP BY 1 ORDER BY 2 DESC").df().to_string(index=False))
print(f"\nwrote db/graph.duckdb: tgraph_nodes/edges/chain, trestrictions  ({time.time()-t0:.0f}s)")
