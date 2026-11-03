"""Why do 3,736 of 3,765 restriction via-nodes fall 'outside' the graph?

Compares the two coordinate sources: Overpass (via nodes) vs the OSM extract the graph was built
from. Tests exact 6-dp key match, then nearest-node distance, to tell a precision mismatch apart
from the via nodes genuinely not being in the extracted network.
"""
import duckdb, json, math

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
SC = "/Users/peterbiczok/.hermes/cache/scratch"
VIA = json.load(open(f"{SC}/buda_via_coords.json"))

con = duckdb.connect(f"{D}/db/osm.duckdb", read_only=True)
con.execute("INSTALL spatial; LOAD spatial; PRAGMA threads=8")

# how many road ways / coords does the extract actually hold, and in what bbox?
print("=== the extract's road geometry ===")
print(con.execute("""
  SELECT count(*) ways, round(min(ST_XMin(ST_Extent(geom))),4) minlon, round(max(ST_XMax(ST_Extent(geom))),4) maxlon,
         round(min(ST_YMin(ST_Extent(geom))),4) minlat, round(max(ST_YMax(ST_Extent(geom))),4) maxlat
  FROM net2 WHERE kind='road'""").df().to_string(index=False))
print()
print(con.execute("SELECT cls, count(*) ways FROM net2 WHERE kind='road' GROUP BY 1 ORDER BY 2 DESC LIMIT 12").df().to_string(index=False))

# build the graph node set exactly as 38_graph_turns.py does
rows = con.execute("SELECT xy FROM geo").fetchall()
print(f"\ngeo rows: {len(rows):,}")
coords = set()
for (xy,) in rows:
    for k in range(0, len(xy) - 1, 2):
        coords.add((round(xy[k+1], 6), round(xy[k], 6)))
print(f"distinct 6-dp coords in the graph: {len(coords):,}")

hit = miss = 0
missed = []
for rid, (lon, lat) in VIA.items():
    if (round(lat, 6), round(lon, 6)) in coords: hit += 1
    else:
        miss += 1
        if len(missed) < 8: missed.append((rid, lon, lat))
print(f"via nodes matching a graph coord: {hit}   not matching: {miss}")

print("\n=== nearest graph node to a few misses (are they within a metre, or genuinely absent?) ===")
con.execute("CREATE OR REPLACE TEMP TABLE vn(id VARCHAR, g GEOMETRY)")
for rid, lon, lat in missed:
    con.execute("INSERT INTO vn VALUES (?, ST_SetCRS(ST_Point(?, ?), 'OGC:CRS84'))", [rid, lon, lat])
con.execute("CREATE OR REPLACE TEMP TABLE gpts AS SELECT DISTINCT ST_SetCRS(ST_Point(xy[k], xy[k+1]), 'OGC:CRS84') AS p FROM geo, range(1, len(xy), 2) t(k)")
print(f"graph points: {con.execute('SELECT count(*) FROM gpts').fetchone()[0]:,}")
try:
    print(con.execute("""
      SELECT v.id, round(min(ST_Distance_Sphere(v.g, g.p))) AS nearest_m
      FROM vn v, gpts g GROUP BY 1 ORDER BY 2""").df().to_string(index=False))
except Exception as e:
    print("  nearest lookup failed:", str(e)[:120])

# are the missed via nodes even inside the extracted bbox?
print("\n=== are the misses on roads the extract contains? (nearest road way) ===")
try:
    print(con.execute(f"""
      WITH s AS (SELECT * FROM vn LIMIT 6)
      SELECT s.id, n.cls, round(ST_Distance_Sphere(s.g, ST_SetCRS(n.geom,'OGC:CRS84'))) AS nearest_way_m
      FROM s, net2 n WHERE n.kind='road'
      QUALIFY row_number() OVER (PARTITION BY s.id ORDER BY nearest_way_m) = 1 ORDER BY 2""").df().to_string(index=False))
except Exception as e:
    print("  failed:", str(e)[:140])
