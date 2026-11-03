"""Mark which OSM rail ways are PASSENGER lines -> db/rail_passenger.parquet.

The rail graph was built from every `kind='rail'` way with no regard for OSM tags, so 35% of its
kilometres are depot/stabling infrastructure. That is why a visible loop appeared where the M2<->M3
service connection is: nothing stopped the router using it.

Rules (checked in this order, first match wins):
  EXCLUDE  railway in {platform_edge, platform, switch, crossing, level_crossing, ...,
                       abandoned, disused, construction, razed, proposed, buffer_stop, ...}
  EXCLUDE  service in {yard, spur, industrial, slipway}   <- depot/stabling + freight branch
           (but NOT siding/crossover: the through line at a station is tagged service=siding)
  EXCLUDE  usage   in {industrial, tourism, military, freight, test, leisure}
  KEEP     everything else (railway rail/light_rail/subway/tram/narrow_gauge/monorail,
           usage main or branch or absent)

Regenerates the OPL dump itself, so this is reproducible without a leftover /tmp file.
"""
import duckdb, os, subprocess, sys

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
os.chdir(D)
PBF = "data/osm/net.osm.pbf"
OPL = "/tmp/rail_passenger.opl"

NONPASS_RAIL = {
    "platform_edge", "platform", "switch", "crossing", "level_crossing", "tram_level_crossing",
    "milestone", "signal", "buffer_stop", "turntable", "roundhouse", "depot", "wash",
    "water_tower", "fuel", "abandoned", "disused", "construction", "razed", "proposed",
    "razed", "narrow_gauge_disused",
}
# `yard` = depot/stabling (this is the M2<->M3 link that drew the bogus loop) and `spur` = an
# industrial/freight branch: both are genuinely not for passengers, so both are excluded.
# `siding` and `crossover` are NOT: at a station the through line is routinely tagged
# `service=siding`, and a cross-over links parallel tracks. Removing those shattered the MAV
# network into 5 pieces (largest component 11,732 nodes instead of 49,731) and made almost every
# bike+train alternative unroutable — a station pair on two different fragments has no route.
NONPASS_SERVICE = {"yard", "spur", "industrial", "slipway"}
NONPASS_USAGE = {"industrial", "tourism", "military", "freight", "test", "leisure"}

print("filtering the PBF to rail ways ...", flush=True)
subprocess.run(["osmium", "tags-filter", PBF, "w/railway", "-o", "/tmp/railonly.osm.pbf",
                "--overwrite"], check=True, capture_output=True)
with open(OPL, "w") as fh:
    subprocess.run(["osmium", "cat", "/tmp/railonly.osm.pbf", "-f", "opl"],
                   check=True, stdout=fh, stderr=subprocess.DEVNULL)

rows, keep, drop = [], 0, 0
dropwhy = {}
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
    rw, sv, us = t.get("railway", ""), t.get("service", ""), t.get("usage", "")
    why = None
    if rw in NONPASS_RAIL:          why = f"railway={rw}"
    elif sv in NONPASS_SERVICE:     why = f"service={sv}"
    elif us in NONPASS_USAGE:       why = f"usage={us}"
    passenger = why is None
    if passenger:
        keep += 1
    else:
        drop += 1
        dropwhy[why] = dropwhy.get(why, 0) + 1
    rows.append((wid, passenger, rw, sv, us))

print(f"rail ways: {len(rows):,}   passenger {keep:,}   non-passenger {drop:,}")
for k, v in sorted(dropwhy.items(), key=lambda x: -x[1]):
    print(f"    dropped {k:28s} {v:6,}")

c = duckdb.connect(f"{D}/db/osm.duckdb")
c.execute("CREATE OR REPLACE TABLE rail_passenger(way_id VARCHAR, passenger BOOLEAN, "
          "railway VARCHAR, service VARCHAR, usage VARCHAR)")
c.executemany("INSERT INTO rail_passenger VALUES (?,?,?,?,?)", rows)
c.execute(f"COPY rail_passenger TO '{D}/db/rail_passenger.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)")
tot = c.execute("SELECT count(*) FILTER (WHERE passenger) p, count(*) n FROM rail_passenger").fetchone()
print(f"\nwrote db/rail_passenger.parquet  ({tot[0]:,} passenger of {tot[1]:,})")

# how much of MY rail graph does the filter change?
c.execute("INSTALL spatial; LOAD spatial;")
print(c.execute("""
  SELECT p.passenger, count(*) AS ways,
         round(sum(ST_Length(ST_Transform(ST_SetCRS(n.geom,'OGC:CRS84'),'EPSG:23700')))/1000) AS km
  FROM net2 n LEFT JOIN rail_passenger p USING (way_id)
  WHERE n.kind='rail' GROUP BY 1 ORDER BY 2 DESC
""").df().to_string(index=False))
