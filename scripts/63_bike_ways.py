"""Classify every OSM highway way for CYCLING -> db/bike_ways.parquet.

The alternative-path feature needs a route a person could actually ride, so the bike network is not
the car network: it must prefer real cycling infrastructure and refuse ways where cycling is banned.

Per way: `allowed` (can you ride it at all), `infra` (how good the provision is) and a riding speed
used as the routing cost. Speed is the cost because a bike route should trade distance for calmer,
faster-for-a-bike streets.

bicycle=no / private / use_sidepath is respected UNLESS an explicit bicycle=yes|designated overrides
it — `bicycle=no` sits on 6,631 ways here and routing through them would produce routes nobody rides.
"""
import duckdb, os, subprocess, collections

D = ("/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/"
     "Transport analysis")
os.chdir(D)
PBF, OPL = "data/osm/net.osm.pbf", "/tmp/highway.opl"

# riding speed km/h by highway class, when cycling is permitted at all
SPEED = {"cycleway": 19.0, "path": 14.0, "track": 13.0, "residential": 18.0, "unclassified": 17.0,
         "tertiary": 16.0, "tertiary_link": 16.0, "secondary": 15.0, "secondary_link": 15.0,
         "primary": 14.0, "primary_link": 14.0, "trunk": 12.0, "trunk_link": 12.0,
         "living_street": 10.0, "service": 12.0, "footway": 8.0, "pedestrian": 8.0, "steps": 3.0,
         "motorway": 0.0, "motorway_link": 0.0, "construction": 0.0, "proposed": 0.0}
GOOD = {"cycleway", "track", "opposite_lane", "opposite_track", "lane", "shared_lane", "share_busway",
        "separate", "crossing", "buffered_lane"}
BANNED = {"no", "private", "use_sidepath"}

print("filtering the PBF to highway ways ...", flush=True)
subprocess.run(["osmium", "tags-filter", PBF, "w/highway", "-o", "/tmp/hw.osm.pbf", "--overwrite"],
               check=True, capture_output=True)
with open(OPL, "w") as fh:
    subprocess.run(["osmium", "cat", "/tmp/hw.osm.pbf", "-f", "opl"],
                   check=True, stdout=fh, stderr=subprocess.DEVNULL)

rows, infra_cnt = [], collections.Counter()
for line in open(OPL, encoding="utf-8", errors="replace"):
    if not line.startswith("w"):
        continue
    wid = line.split(" ", 1)[0]
    try:
        tagstr = line.split(" T", 1)[1].split(" N", 1)[0]
    except IndexError:
        continue
    t = {}
    for kv in tagstr.split(","):
        if "=" in kv:
            k, v = kv.split("=", 1)
            t[k] = v
    hw = t.get("highway", "")
    if not hw:
        continue
    base = SPEED.get(hw, 14.0)
    if base <= 0.0:                       # motorway & friends: not a bike route, ever
        rows.append((wid, hw, False, "none", 0.0, 0))
        infra_cnt[f"forbidden:{hw}"] += 1
        continue
    b = t.get("bicycle", "")
    # explicit bicycle=no/private/use_sidepath, unless the way is itself a cycleway or
    # designated for bikes (OSM routinely tags a cycleway bicycle=designated)
    if b in BANNED and hw != "cycleway" and b != "designated":
        rows.append((wid, hw, False, "none", 0.0, 0))
        infra_cnt[f"bicycle={b}"] += 1
        continue
    cw = [t.get("cycleway", ""), t.get("cycleway:left", ""), t.get("cycleway:right", ""),
          t.get("cycleway:both", "")]
    if hw == "cycleway":
        infra, sp = "cycleway", base
    elif b == "designated":
        infra, sp = "designated", base + 1.0
    elif any(x in GOOD for x in cw):
        infra, sp = "laned", base + 1.0
    elif hw in ("footway", "pedestrian"):
        infra, sp = "walk", base
    else:
        infra, sp = "none", base
    # a dismount is a walk with a bike: slower but permitted
    if b == "dismount":
        sp = 6.0
    rows.append((wid, hw, True, infra, sp, 1))
    infra_cnt[infra] += 1

print(f"highway ways parsed: {len(rows):,}")
for k, v in infra_cnt.most_common(12):
    print(f"  {k:22s} {v:,}")

c = duckdb.connect(f"{D}/db/osm.duckdb")
c.execute("CREATE OR REPLACE TABLE bike_ways(way_id VARCHAR, hw VARCHAR, allowed BOOLEAN, "
          "infra VARCHAR, speed DOUBLE, ok INTEGER)")
c.executemany("INSERT INTO bike_ways VALUES (?,?,?,?,?,?)", rows)
c.execute(f"COPY bike_ways TO '{D}/db/bike_ways.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)")

c.execute("INSTALL spatial; LOAD spatial;")
print("\n=== coverage of my ROAD network, weighted by km ===")
print(c.execute("""
  SELECT coalesce(b.infra,'(not in bike_ways)') AS infra,
         count(*) ways,
         round(sum(ST_Length(ST_Transform(ST_SetCRS(n.geom,'OGC:CRS84'),'EPSG:23700')))/1000) km,
         round(avg(b.speed)) avg_speed
  FROM net2 n LEFT JOIN bike_ways b USING (way_id)
  WHERE n.kind='road'
  GROUP BY 1 ORDER BY km DESC
""").df().to_string(index=False))
print("\n=== road classes in net2 ===")
print(c.execute("SELECT cls, count(*) FROM net2 WHERE kind='road' GROUP BY 1 ORDER BY 2 DESC")
      .df().to_string(index=False))
