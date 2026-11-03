"""Reconnaissance for the alternative-path feature.

Needs to know, before building anything:
 1. which station fields the app already has (station id / name / access distance per trip end);
 2. where the station COORDINATES and the rail-link pairs live;
 3. whether the OSM extract carries cycleway tags, so a bike route can prefer real cycling
    infrastructure rather than just avoiding motorways.
"""
import duckdb, os, subprocess

D = ("/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/"
     "Transport analysis")
os.chdir(D)

print("=== platform/trips_attrs.parquet columns ===")
print(duckdb.sql("DESCRIBE SELECT * FROM read_parquet('platform/trips_attrs.parquet')").df()
      [['column_name', 'column_type']].to_string(index=False))

for db in ("db/osm.duckdb", "db/graph.duckdb"):
    c = duckdb.connect(db, read_only=True)
    print(f"\n=== tables in {db} ===")
    print([r[0] for r in c.execute("SHOW TABLES").fetchall()])

c = duckdb.connect("db/osm.duckdb", read_only=True)
print("\n=== candidate station tables ===")
for t in [r[0] for r in c.execute("SHOW TABLES").fetchall()]:
    if any(k in t.lower() for k in ("stn", "stop", "station", "pair", "lvl")):
        n = c.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        cols = [r[0] for r in c.execute(f"DESCRIBE {t}").fetchall()]
        print(f"  {t}: {n:,} rows  cols={cols}")

print("\n=== cycleway tags present in the OSM extract? ===")
subprocess.run(["osmium", "tags-filter", "data/osm/net.osm.pbf",
                "w/highway=cycleway", "w/cycleway", "w/bicycle",
                "-o", "/tmp/cyc.osm.pbf", "--overwrite"], check=True, capture_output=True)
with open("/tmp/cyc.opl", "w") as fh:
    subprocess.run(["osmium", "cat", "/tmp/cyc.osm.pbf", "-f", "opl"],
                   check=True, stdout=fh, stderr=subprocess.DEVNULL)
import collections
cnt = collections.Counter()
ways = 0
for line in open("/tmp/cyc.opl", encoding="utf-8", errors="replace"):
    if not line.startswith("w"):
        continue
    ways += 1
    try:
        tagstr = line.split(" T", 1)[1].split(" N", 1)[0]
    except IndexError:
        continue
    for kv in tagstr.split(","):
        if kv.startswith(("cycleway=", "bicycle=", "highway=cycleway", "cycleway:left=",
                          "cycleway:right=", "cycleway:both=")):
            cnt[kv] += 1
print(f"ways matched: {ways:,}")
for k, v in cnt.most_common(20):
    print(f"  {k:32s} {v:,}")
