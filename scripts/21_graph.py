"""Build a routable node/edge graph from the OSM network (roads + rail) -> db/graph.duckdb.

Approach: the "segment graph". Every coordinate in every way becomes a node (deduped by
rounded lat/lon); consecutive coordinates within a way become edges. OSM models junctions by
SHARING node coordinates, so ways connect automatically at real junctions and stay separate
where they merely cross (bridges/tunnels) — which is the behaviour we want.
"""
import duckdb, math, time

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
con = duckdb.connect(f"{D}/db/osm.duckdb")
con.execute("INSTALL spatial; LOAD spatial;")

t0 = time.time()
rows = con.execute("""
  SELECT g.way_id, n.kind, n.cls, g.xy
  FROM geo g JOIN net2 n USING (way_id)
""").fetchall()
print(f"ways read: {len(rows):,}  ({time.time()-t0:.0f}s)")

node_of = {}
nodes = []                       # id -> (lon, lat)
edges = []                       # (a, b, len_m, way_id, kind)

def nid(lon, lat):
    key = (round(lat, 6), round(lon, 6))
    i = node_of.get(key)
    if i is None:
        i = len(nodes); node_of[key] = i; nodes.append((lon, lat))
    return i

for way_id, kind, cls, xy in rows:
    prev = None
    for k in range(0, len(xy) - 1, 2):
        cur = nid(xy[k], xy[k+1])
        if prev is not None and prev != cur:
            lon1, lat1 = nodes[prev]; lon2, lat2 = nodes[cur]
            dy = (lat2 - lat1) * 110540.0
            dx = (lon2 - lon1) * 111320.0 * math.cos(math.radians((lat1 + lat2) / 2.0))
            d = math.hypot(dx, dy)
            if d > 0:
                edges.append((prev, cur, d, way_id, kind))
        prev = cur

print(f"nodes {len(nodes):,} | edges {len(edges):,}  ({time.time()-t0:.0f}s)")

import pandas as pd
# NB: executemany() over ~2M rows takes many minutes in DuckDB — register DataFrames and
# INSERT ... SELECT instead (seconds for the same data).
g = duckdb.connect(f"{D}/db/graph.duckdb")
g.execute("CREATE OR REPLACE TABLE nodes(id BIGINT, lon DOUBLE, lat DOUBLE)")
g.register('df_nodes', pd.DataFrame({'id': range(len(nodes)),
                                     'lon': [n[0] for n in nodes],
                                     'lat': [n[1] for n in nodes]}))
g.execute("INSERT INTO nodes SELECT id, lon, lat FROM df_nodes")
g.execute("CREATE OR REPLACE TABLE edges(a BIGINT, b BIGINT, len_m DOUBLE, way_id VARCHAR, kind VARCHAR)")
g.register('df_edges', pd.DataFrame(edges, columns=['a', 'b', 'len_m', 'way_id', 'kind']))
g.execute("INSERT INTO edges SELECT a, b, len_m, way_id, kind FROM df_edges")

print(g.execute("""SELECT kind, count(*) edges, count(DISTINCT a) nodes_from,
  round(sum(len_m)/1000) km FROM edges GROUP BY 1""").df().to_string())
print(f"\nwrote db/graph.duckdb  ({time.time()-t0:.0f}s)")
