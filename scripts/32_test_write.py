"""Prove the route-output WRITE path works — in seconds, before any 22-minute routing run.

test mode in 25_route_all.py only exercised ROUTING, never the write phase, which is why two
full runs were lost to late crashes. This runs the exact write SQL against the real graph DB
with a handful of dummy edges.
"""
import duckdb, numpy as np, pandas as pd, os, sys

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
NSPLIT = 42
NSTOT = 41

conn = duckdb.connect()                       # in-memory: never touches the real project DBs
conn.execute("INSTALL spatial; LOAD spatial;")
conn.execute(f"ATTACH '{D}/db/graph.duckdb' AS gdb (READ_ONLY)")

# a few real edges, with dummy counts
n_edges = 5
counts = np.zeros((n_edges, NSPLIT), dtype=np.int32)
counts[:, NSTOT] = [3, 7, 1, 9, 2]
counts[:, 0] = [1, 2, 1, 3, 0]
conn.register('df_cnt', pd.DataFrame({'eid': np.arange(n_edges, dtype=np.int64),
                                      'n': counts[:, NSTOT].astype(np.int64),
                                      'ns': counts.tolist()}))

conn.execute("CREATE OR REPLACE TABLE edge_geo AS "
             "SELECT row_number() OVER () - 1 AS eid, u, v, len_m, node_ids FROM gdb.croad_edges")
print("edge_geo rows:", conn.execute("SELECT count(*) FROM edge_geo").fetchone()[0])

conn.execute("""CREATE OR REPLACE TABLE epts AS
  SELECT g.eid, t.k, n.lon, n.lat
  FROM edge_geo g, LATERAL (SELECT unnest(range(1, len(g.node_ids)+1)) AS k) t
  JOIN gdb.nodes n ON n.id = g.node_ids[t.k]""")
print("epts rows    :", conn.execute("SELECT count(*) FROM epts").fetchone()[0])

conn.execute("""CREATE OR REPLACE TABLE routed_edges AS
  SELECT g.eid, g.u, g.v, g.len_m, c.n, c.ns,
         flatten(list([round(p.lon,5)::FLOAT, round(p.lat,5)::FLOAT] ORDER BY p.k)) AS xy
  FROM edge_geo g JOIN df_cnt c ON c.eid = g.eid JOIN epts p ON p.eid = g.eid
  WHERE c.n > 0
  GROUP BY g.eid, g.u, g.v, g.len_m, c.n, c.ns""")

r = conn.execute("""SELECT eid, round(len_m) len_m, n, len(ns) ns_len, len(xy) xy_floats
                    FROM routed_edges ORDER BY eid""").df()
print("\nrouted_edges:")
print(r.to_string())
n = conn.execute("SELECT count(*) FROM routed_edges").fetchone()[0]
assert n == n_edges, f"expected {n_edges} rows, got {n}"
assert (r['ns_len'] == NSPLIT).all(), "ns must be a 42-element list"
assert (r['xy_floats'] >= 4).all(), "xy must hold at least 2 coordinate pairs"

tmp = "/tmp/test_routed_edges.parquet"
conn.execute(f"COPY routed_edges TO '{tmp}' (FORMAT PARQUET, COMPRESSION ZSTD)")
back = duckdb.connect().execute(f"SELECT count(*), max(len(ns)) FROM '{tmp}'").fetchone()
print(f"\nparquet round-trip: {back[0]} rows, max ns len {back[1]}  ({os.path.getsize(tmp)/1024:.0f} KB)")
print("\nWRITE PATH OK")
