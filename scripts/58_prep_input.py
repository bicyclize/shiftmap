"""Restore the pre-subtraction road baseline before re-running the rail split.

The road volume must start from a state with NO rail trips removed yet, or the rail footprint gets
subtracted twice. out/prev_routes2/ holds exactly that: the raw all-road output of 40_route_turns.
Its counts are keyed by position (which is what the subtraction needs); its geometry is the buggy
pre-repair version, but 48_rail_route rebuilds geometry from the position -> eid map anyway.

Adds the `kind` column (all 'road') so the reader's kind filter works.
"""
import duckdb, os, shutil

D = ("/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/"
     "Transport analysis")
os.chdir(D)
SRC, OUT = "out/prev_routes2", "platform"

for f in ("routed_geom.parquet", "route_len.parquet"):
    shutil.copyfile(f"{SRC}/{f}", f"{OUT}/{f}")
    print(f"restored {f} from {SRC}")

c = duckdb.connect()
c.execute("INSTALL spatial; LOAD spatial;")
c.execute(f"CREATE OR REPLACE TABLE re AS SELECT *, 'road' AS kind FROM read_parquet('{SRC}/routed_edges.parquet')")
c.execute(f"COPY re TO '{OUT}/routed_edges.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)")
print(f"routed_edges restored from {SRC} with kind='road'")
print(c.execute(f"SELECT kind, count(*) edges, sum(n) visits FROM read_parquet('{OUT}/routed_edges.parquet') GROUP BY 1").df().to_string(index=False))
print("min eid / max eid:", c.execute(f"SELECT min(eid), max(eid) FROM read_parquet('{OUT}/routed_edges.parquet')").fetchone())
