"""Is the service loop gone from the rail graph?

The user's box: lon 19.051302298868734-19.0532637, lat 47.505209626879974-47.5062439 (District V).
Before the fix, the M2<->M3 stabling connection (service=yard, "Kihuzovagany") was in the graph and
drew a visible loop there. Lists the rail edges that remain in the box, by class.
"""
import duckdb, os

D = ("/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/"
     "Transport analysis")
os.chdir(D)
LON0, LON1 = 19.051302298868734, 19.0532637
LAT0, LAT1 = 47.505209626879974, 47.5062439

# 1. the ways themselves: passenger or not?
print("=== the ways OSM has in that box ===")
print(duckdb.sql(f"""
  SELECT way_id, railway, service, usage, passenger
  FROM read_parquet('db/rail_passenger.parquet')
  WHERE way_id IN ('w324230647','w1426167743','w324237924','w633224446','w692536969','w1547803322')
  ORDER BY passenger, way_id
""").df().to_string(index=False))

g = duckdb.connect("db/graph.duckdb", read_only=True)
g.execute("INSTALL spatial; LOAD spatial;")
print("\n=== rail graph edges with geometry inside the box ===")
df = g.execute(f"""
  SELECT eid, cls,
         round(len_m) AS len_m,
         round(min(lon),6) AS lon_min, round(max(lon),6) AS lon_max,
         round(min(lat),6) AS lat_min, round(max(lat),6) AS lat_max
  FROM (
    SELECT e.eid, e.cls, e.len_m,
           unnest(nodes) AS nid
    FROM tgrail_edges e
  ) x
  JOIN tgrail_nodes nd ON nd.id = x.nid
  WHERE nd.lon BETWEEN {LON0} AND {LON1} AND nd.lat BETWEEN {LAT0} AND {LAT1}
  GROUP BY eid, cls, len_m
  ORDER BY len_m DESC
""").df()
print(df.to_string(index=False) if len(df) else "  (no rail graph edges in the box)")
print(f"\nedges in box: {len(df)}   classes: {sorted(df['cls'].unique().tolist()) if len(df) else []}")

# 2. does the OLD graph (built from all rail ways) have anything the new one does not?
o = duckdb.connect("db/osm.duckdb", read_only=True)
o.execute("INSTALL spatial; LOAD spatial;")
print("\n=== for reference: ALL rail ways in the box, and whether they are passenger ===")
print(o.execute(f"""
  SELECT n.way_id, n.cls, p.passenger, p.railway, p.service,
         round(ST_Length(ST_Transform(ST_SetCRS(n.geom,'OGC:CRS84'),'EPSG:23700'))) AS len_m
  FROM net2 n LEFT JOIN read_parquet('db/rail_passenger.parquet') p USING (way_id)
  WHERE n.kind='rail' AND ST_Intersects(
    ST_Transform(ST_SetCRS(n.geom,'OGC:CRS84'),'EPSG:23700'),
    ST_Transform(ST_SetCRS(ST_GeomFromText('POLYGON(({LON0} {LAT0}, {LON1} {LAT0}, {LON1} {LAT1}, {LON0} {LAT1}, {LON0} {LAT0}))'),'OGC:CRS84'),'EPSG:23700'))
  ORDER BY p.passenger NULLS FIRST, len_m DESC
""").df().to_string(index=False))
