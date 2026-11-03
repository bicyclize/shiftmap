"""Measure route quality for a routed-geometry file, so pre- and post-fix can be compared.

Usage: 44_route_quality_cmp.py <routed_geom.parquet> <label>

Reports, per length band:
  * the class mix of routed distance (what road types the routes actually use)
  * the MINOR-road share — the symptom the user reported ("main road traffic takes small roads")
  * median points per route, a proxy for how much the route turns: Douglas-Peucker keeps the
    real turns, so a smoother route keeps fewer points.
"""
import duckdb, sys, time

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
PATH, LABEL = sys.argv[1], sys.argv[2]
MINOR = "('residential','service','living_street','unclassified','road','track','path')"
SAMPLE_MOD = 50

con = duckdb.connect(f"{D}/db/osm.duckdb", read_only=True)
con.execute("INSTALL spatial; LOAD spatial; PRAGMA threads=8")
t0 = time.time()

con.execute(f"CREATE OR REPLACE TEMP TABLE rg AS SELECT i, xy FROM read_parquet('{PATH}')")
n = con.execute("SELECT count(*) FROM rg").fetchone()[0]
med_pts = con.execute(f"SELECT median(len(xy)/2) FROM rg WHERE i % {SAMPLE_MOD} = 0").fetchone()[0]
print(f"\n===== {LABEL} =====  {n:,} routes, median {med_pts:.0f} points/route")

con.execute("""CREATE OR REPLACE TEMP TABLE net2m AS
  SELECT cls, ST_Transform(ST_SetCRS(geom,'OGC:CRS84'),'EPSG:23700') AS geom
  FROM net2 WHERE kind='road'""")
con.execute(f"""CREATE OR REPLACE TEMP TABLE rv AS
  SELECT i, xy, unnest(range(1, len(xy), 2)) AS k FROM rg WHERE i % {SAMPLE_MOD} = 0""")
con.execute("""CREATE OR REPLACE TEMP TABLE vp AS
  SELECT i, (k-1)/2 AS seg,
         ST_Transform(ST_SetCRS(ST_Point(xy[k], xy[k+1]),'OGC:CRS84'),'EPSG:23700') AS pt FROM rv""")
con.execute("""CREATE OR REPLACE TEMP TABLE mid AS
  SELECT row_number() OVER () AS sid, i,
         ST_Point((ST_X(a)+ST_X(b))/2, (ST_Y(a)+ST_Y(b))/2) AS m, ST_Distance(a,b) AS len
  FROM (SELECT i, pt AS a, lead(pt) OVER (PARTITION BY i ORDER BY seg) AS b FROM vp)
  WHERE b IS NOT NULL AND ST_Distance(a,b) > 1""")
con.execute("""CREATE OR REPLACE TEMP TABLE cand AS
  SELECT m.sid, m.i, w.cls, m.len, ST_Distance(m.m, w.geom) AS d
  FROM mid m JOIN net2m w ON ST_Intersects(ST_Expand(m.m, 40.0), w.geom)""")
con.execute("""CREATE OR REPLACE TEMP TABLE picked AS
  SELECT sid, i, cls, len FROM
    (SELECT *, row_number() OVER (PARTITION BY sid ORDER BY d) AS rn FROM cand) WHERE rn=1""")
print(f"snapped {con.execute('SELECT count(*) FROM picked').fetchone()[0]:,} segments   ({time.time()-t0:.0f}s)")

print("\n-- routed distance by class --")
print(con.execute("""
  SELECT cls, round(100.0*sum(len)/sum(sum(len)) OVER (),1) AS routed_pct,
         round(100.0*(SELECT sum(ST_Length(geom)) FROM net2m n WHERE n.cls=p.cls)
               /(SELECT sum(ST_Length(geom)) FROM net2m)) AS net_pct
  FROM picked p GROUP BY cls HAVING sum(len) > 0 ORDER BY routed_pct DESC LIMIT 9""").df().to_string(index=False))

print(f"\n-- MINOR-road share by trip length (minor = {MINOR}) --")
print(con.execute(f"""
  WITH tl AS (SELECT i, ST_Distance_Sphere(ST_Point(xy[1],xy[2]), ST_Point(xy[-2],xy[-1]))/1000 AS km
               FROM rg WHERE i % {SAMPLE_MOD}=0),
  agg AS (SELECT p.i, sum(p.len) tot, sum(p.len) FILTER (WHERE p.cls IN {MINOR}) minor
          FROM picked p GROUP BY p.i)
  SELECT CASE WHEN t.km<2 THEN 'a) <2 km' WHEN t.km<5 THEN 'b) 2-5 km'
              WHEN t.km<10 THEN 'c) 5-10 km' ELSE 'd) >=10 km' END band,
         count(*) trips, round(100.0*sum(a.minor)/sum(a.tot),1) minor_pct
  FROM agg a JOIN tl t USING (i) GROUP BY 1 ORDER BY 1""").df().to_string(index=False))

print("\n-- overall minor share --")
print(con.execute(f"SELECT round(100.0*sum(len) FILTER (WHERE cls IN {MINOR})/sum(len),1) AS minor_pct FROM picked").df().to_string(index=False))
print(f"({time.time()-t0:.0f}s)")
