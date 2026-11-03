"""First-pass mode proxy: does a trip follow a RAIL corridor?

For each trip we measure what fraction of its observed GPS vertices sit within 25 m of a railway
way (tram / HÉV / rail / metro tunnel). High share ⇒ the phone travelled along a guideway.

HONEST LIMITS (reported with the output, not hidden):
  * catches TRAM, HÉV and surface RAIL well — they have their own visible guideway;
  * UNDER-detects METRO, because the underground portion has no GPS at all: the pings stop at the
    surface portal and resume after. A metro trip can therefore score low;
  * a BUS passenger looks exactly like a car user — a bus route IS a road route. So "not rail"
    must never be read as "car".
Output is therefore labelled "rail corridor" / "not rail", never "transit" / "car".
"""
import duckdb, time, os

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
con = duckdb.connect(f"{D}/db/osm.duckdb")
con.execute("PRAGMA threads=8"); con.execute("INSTALL spatial; LOAD spatial;")
# DuckDB v2 requires this before ST_Transform on [lon,lat] geometries (OGC:CRS84 has x=lon first,
# so "always_xy" = treat the first axis as easting is the correct choice here).
con.execute("SET geometry_always_xy = true")

NEAR_M = 25.0        # a vertex this close to a rail way counts as "on the guideway"
EXPAND_M = 60.0      # search radius when looking for candidate rail ways

t0 = time.time()
# PASSENGER LINES ONLY. Measuring proximity to any railway way counted depot sidings, yards and
# platform edges as "on the guideway", which both misclassified trips and let the router use
# stabling connections between metro lines.
con.execute("""CREATE OR REPLACE TABLE rail_m AS
  SELECT way_id, ST_Transform(ST_SetCRS(geom,'OGC:CRS84'),'EPSG:23700') AS geom
  FROM net2 WHERE kind='rail'
    AND way_id IN (SELECT way_id FROM rail_passenger WHERE passenger)""")
print("passenger rail ways:", con.execute("SELECT count(*) FROM rail_m").fetchone()[0], flush=True)
print("all rail ways      :", con.execute("SELECT count(*) FROM net2 WHERE kind='rail'").fetchone()[0], flush=True)

con.execute("""CREATE OR REPLACE TABLE rv AS
  SELECT row_number() OVER () - 1 AS i, path_xy,
         unnest(range(1, len(path_xy), 2)) AS k
  FROM platform""")
ts = None
print(f"trip vertices: {con.execute('SELECT count(*) FROM rv').fetchone()[0]:,}", flush=True)

con.execute("""CREATE OR REPLACE TABLE rvm AS
  SELECT i, k, ST_Transform(ST_SetCRS(ST_Point(path_xy[k], path_xy[k+1]),'OGC:CRS84'),'EPSG:23700') AS pt
  FROM rv""")
print(f"projected {time.time()-t0:.0f}s", flush=True)

con.execute(f"""CREATE OR REPLACE TABLE rvh AS
  SELECT v.i, v.k, min(ST_Distance(v.pt, r.geom)) AS d
  FROM rvm v
  LEFT JOIN rail_m r ON ST_Intersects(ST_Expand(v.pt, {EXPAND_M}), r.geom)
  GROUP BY v.i, v.k""")
print(f"vertex->rail distances {time.time()-t0:.0f}s", flush=True)

con.execute(f"""CREATE OR REPLACE TABLE rail_share AS
  SELECT i,
         count(*) AS n_pts,
         count(*) FILTER (WHERE d IS NOT NULL AND d <= {NEAR_M}) AS n_near,
         avg(((d IS NOT NULL AND d <= {NEAR_M})::INT))::DOUBLE AS share
  FROM rvh GROUP BY i""")

con.execute("""CREATE OR REPLACE TABLE rail_mode AS
  SELECT i, n_pts, n_near, round(share,3) AS rail_share,
         CASE WHEN share >= 0.5 THEN 'rail'
              WHEN share >= 0.25 THEN 'mixed'
              ELSE 'not_rail' END AS mode
  FROM rail_share""")

print("\n=== distribution (min 3 vertices) ===")
print(con.execute("""
  SELECT mode, count(*) trips,
         round(100.0*count(*)/sum(count(*)) OVER (),1) pct,
         round(median(rail_share),3) med_share
  FROM rail_mode WHERE n_pts >= 3 GROUP BY 1 ORDER BY 2 DESC""").df().to_string())

print("\ncross-check against the trips already flagged bike+train (btb), which need a rail link:")
print(con.execute("""
  WITH p AS (SELECT row_number() OVER () - 1 AS i, btb FROM platform)
  SELECT m.mode, count(*) n, round(100.0*count(*)/sum(count(*)) OVER (),1) pct
  FROM p JOIN rail_mode m USING (i)
  WHERE p.btb GROUP BY 1 ORDER BY 2 DESC""").df().to_string())

con.execute(f"COPY rail_mode TO '{D}/platform/rail_mode.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)")
print(f"\nrail_mode.parquet MB: {os.path.getsize(f'{D}/platform/rail_mode.parquet')/1e6:.1f}"
      f"   ({time.time()-t0:.0f}s)")
