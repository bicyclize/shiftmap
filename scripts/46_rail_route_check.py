"""Do trips classified as "rail corridor" actually have RAIL-like route geometry?

Every trip is currently routed on the ROAD graph, regardless of classification. If a trip whose GPS
followed a tram track is drawn as a road route, its geometry will wander onto whatever roads happen
to connect its ends — motorways and trunk roads included. That is exactly the reported symptom:
hide "road" and red segments over the motorway remain.

This measures the road-class mix of routed distance SEPARATELY for rail- vs road-classified trips.
A genuine tram/HÉV trip should barely touch motorway or trunk roads.
"""
import duckdb, sys

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
SAMPLE_MOD = 25
con = duckdb.connect(f"{D}/db/osm.duckdb", read_only=True)
con.execute("INSTALL spatial; LOAD spatial; PRAGMA threads=8")

con.execute(f"""CREATE OR REPLACE TEMP TABLE rg AS
  SELECT g.i, g.xy, m.mode FROM read_parquet('{D}/platform/routed_geom.parquet') g
  JOIN read_parquet('{D}/platform/rail_mode.parquet') m ON m.i = g.i
  WHERE g.i % {SAMPLE_MOD} = 0""")
print("sampled", con.execute("SELECT mode, count(*) FROM rg GROUP BY 1 ORDER BY 2 DESC").df().to_string(index=False))

con.execute("""CREATE OR REPLACE TEMP TABLE net2m AS
  SELECT cls, ST_Transform(ST_SetCRS(geom,'OGC:CRS84'),'EPSG:23700') AS geom
  FROM net2 WHERE kind='road'""")
con.execute("""CREATE OR REPLACE TEMP TABLE rv AS
  SELECT i, mode, xy, unnest(range(1, len(xy), 2)) AS k FROM rg""")
con.execute("""CREATE OR REPLACE TEMP TABLE vp AS
  SELECT i, mode, (k-1)/2 AS seg,
         ST_Transform(ST_SetCRS(ST_Point(xy[k], xy[k+1]),'OGC:CRS84'),'EPSG:23700') AS pt FROM rv""")
con.execute("""CREATE OR REPLACE TEMP TABLE mid AS
  SELECT row_number() OVER () AS sid, i, mode,
         ST_Point((ST_X(a)+ST_X(b))/2, (ST_Y(a)+ST_Y(b))/2) AS m, ST_Distance(a,b) AS len
  FROM (SELECT i, mode, pt AS a, lead(pt) OVER (PARTITION BY i ORDER BY seg) AS b FROM vp)
  WHERE b IS NOT NULL AND ST_Distance(a,b) > 1""")
con.execute("""CREATE OR REPLACE TEMP TABLE cand AS
  SELECT m.sid, m.i, m.mode, w.cls, m.len, ST_Distance(m.m, w.geom) AS d
  FROM mid m JOIN net2m w ON ST_Intersects(ST_Expand(m.m, 40.0), w.geom)""")
con.execute("""CREATE OR REPLACE TEMP TABLE picked AS
  SELECT sid, i, mode, cls, len FROM
    (SELECT *, row_number() OVER (PARTITION BY sid ORDER BY d) AS rn FROM cand) WHERE rn=1""")

print("\n=== road-class mix of routed distance, by trip classification ===")
print(con.execute("""
  SELECT mode, cls, round(100.0*sum(len)/sum(sum(len)) OVER (PARTITION BY mode),1) AS pct
  FROM picked GROUP BY 1,2 HAVING sum(len) > 0
  QUALIFY row_number() OVER (PARTITION BY mode ORDER BY sum(len) DESC) <= 6
  ORDER BY mode, pct DESC""").df().to_string(index=False))

print("\n=== 'highway' share (motorway + trunk + links) per classification ===")
print(con.execute("""
  SELECT mode, round(100.0*sum(len) FILTER (WHERE cls LIKE 'motorway%' OR cls LIKE 'trunk%')/sum(len),1) AS highway_pct,
         round(sum(len)/1000) AS km
  FROM picked GROUP BY 1 ORDER BY km DESC""").df().to_string(index=False))

print("\n=== sanity: how close do rail-classified trips' ROUTES run to actual rail? ===")
con.execute("""CREATE OR REPLACE TEMP TABLE railm AS
  SELECT ST_Transform(ST_SetCRS(geom,'OGC:CRS84'),'EPSG:23700') AS geom FROM net2 WHERE kind='rail'""")
print(con.execute("""
  WITH pts AS (SELECT DISTINCT p.sid, p.mode, p.m FROM mid p)
  SELECT p.mode,
         round(100.0*count(*) FILTER (WHERE EXISTS (
             SELECT 1 FROM railm r WHERE ST_Intersects(ST_Expand(p.m, 30.0), r.geom)))/count(*),1) AS pct_route_within_30m_of_rail
  FROM pts p GROUP BY 1 ORDER BY 1""").df().to_string(index=False))
