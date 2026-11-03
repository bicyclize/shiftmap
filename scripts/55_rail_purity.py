"""How much of my RAIL graph is not a passenger line?

The graph was built from every `kind='rail'` way, with no regard for OSM tags. That let in:
  * service=yard / spur / siding / crossover  -> depot + stabling + connections between lines
  * railway=platform_edge                     -> not a running track at all
  * railway=abandoned / disused / construction
The user spotted the consequence: a visible LOOP where the M2<->M3 stabling connection is
("Kihuzovagany, az M2 es M3 metrovonal vasuti osszekottetese", service=yard, maxspeed=25).

Joins the network geometry (net2) to the OSM tags parsed out of the filtered PBF, and reports
exactly how many of MY rail ways are passenger vs not.
"""
import duckdb, os, re
from collections import defaultdict

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
os.chdir(D)

# ---- parse tags out of the OPL dump ----
tags = {}
for line in open("/tmp/rail.opl", encoding="utf-8", errors="replace"):
    line = line.rstrip("\n")
    if not line.startswith("w"):
        continue
    wid = line.split(" ", 1)[0]
    try:
        after = line.split(" T", 1)[1]
        tagstr = after.split(" N", 1)[0]
    except IndexError:
        continue
    t = {}
    for kv in tagstr.split(","):
        if "=" in kv:
            k, v = kv.split("=", 1)
            t[k] = v
    tags[wid] = t
print(f"rail ways parsed from the PBF: {len(tags):,}")

c = duckdb.connect(f"{D}/db/osm.duckdb", read_only=True)
c.execute("PRAGMA threads=8")
c.execute("INSTALL spatial; LOAD spatial;")
rows = c.execute("""
  SELECT way_id, cls, ST_Length(ST_Transform(ST_SetCRS(geom,'OGC:CRS84'),'EPSG:23700'))/1000.0 AS km
  FROM net2 WHERE kind='rail'
""").fetchall()
print(f"rail ways in my graph (net2 kind='rail'): {len(rows):,}")

NONPASS_SERVICE = {"yard", "spur", "siding", "crossover", "industrial", "slipway"}
NONPASS_RAIL = {"platform_edge", "platform", "abandoned", "disused", "construction",
                "razed", "proposed", "razed", "switch", "crossing", "level_crossing",
                "tram_level_crossing", "milestone", "signal", "buffer_stop", "buffer_stop",
                "signal", "turntable", "wash", "fuel", "water_tower", "roundhouse", "depot"}
NONPASS_USAGE = {"industrial", "tourism", "military", "freight", "test", "leisure"}

buckets = defaultdict(lambda: [0, 0.0])
nopass_km = 0.0; tot_km = 0.0
nopass_ways = 0
examples = defaultdict(list)
for way_id, cls, km in rows:
    t = tags.get(way_id, {})
    tot_km += km
    why = None
    if t.get("railway") in NONPASS_RAIL:
        why = f"railway={t.get('railway')}"
    elif t.get("service") in NONPASS_SERVICE:
        why = f"service={t.get('service')}"
    elif t.get("usage") in NONPASS_USAGE:
        why = f"usage={t.get('usage')}"
    if why:
        nopass_ways += 1; nopass_km += km
        buckets[why][0] += 1; buckets[why][1] += km
        if len(examples[why]) < 2:
            examples[why].append((way_id, round(km, 2), t.get("description", "")[:60]))
    else:
        k = f"PASSENGER railway={t.get('railway','?')} usage={t.get('usage','-')}"
        buckets[k][0] += 1; buckets[k][1] += km

print(f"\n=== my rail graph, by tag ===")
for k, (n, km) in sorted(buckets.items(), key=lambda x: -x[1][1]):
    flag = "" if k.startswith("PASSENGER") else "   <-- NOT A PASSENGER LINE"
    print(f"  {k:52s} {n:6,} ways {km:9.1f} km{flag}")
print(f"\nTOTAL           {len(rows):,} ways {tot_km:9.1f} km")
print(f"NON-PASSENGER   {nopass_ways:,} ways {nopass_km:9.1f} km  ({nopass_km/tot_km*100:.1f}% of my rail km)")

print("\n=== examples ===")
for k, ex in examples.items():
    for wid, km, desc in ex:
        print(f"  {k:28s} {wid:14s} {km:7.2f} km  {desc}")
