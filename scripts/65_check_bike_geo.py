import duckdb, os
D = ("/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/"
     "Transport analysis")
os.chdir(D)
c = duckdb.connect("db/osm.duckdb", read_only=True)
print("geo table cols:", [r[0] for r in c.execute("DESCRIBE geo").fetchall()])
print("geo rows:", c.execute("SELECT count(*) FROM geo").fetchone()[0])
print("net2 rows:", c.execute("SELECT count(*) FROM net2").fetchone()[0])
for hw in ("cycleway", "path", "footway", "pedestrian", "track", "steps"):
    n_bw = c.execute("SELECT count(*) FROM bike_ways WHERE hw=?", [hw]).fetchone()[0]
    n_geo = c.execute("SELECT count(*) FROM geo WHERE way_id IN (SELECT way_id FROM bike_ways WHERE hw=?)",
                      [hw]).fetchone()[0]
    n_net2 = c.execute("SELECT count(*) FROM net2 WHERE way_id IN (SELECT way_id FROM bike_ways WHERE hw=?)",
                       [hw]).fetchone()[0]
    print(f"  {hw:12s} bike_ways {n_bw:7,}   with geometry {n_geo:7,}   in net2 {n_net2:7,}")
