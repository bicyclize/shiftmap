import duckdb
c = duckdb.connect()
for f in ["routed_geom", "route_len", "routed_edges", "rail_mode"]:
    p = f"platform/{f}.parquet"
    print(f"== {f}")
    for row in c.execute(f"DESCRIBE SELECT * FROM read_parquet('{p}')").fetchall():
        print(f"   {row[0]:12s} {row[1]}")
    print("   rows:", c.execute(f"SELECT count(*) FROM read_parquet('{p}')").fetchone()[0])
