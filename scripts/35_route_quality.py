"""Diagnose route plausibility: WHERE does the routed distance actually go?

The router minimises pure length, so it has no reason to prefer an arterial over a side street.
This measures the class mix of routed distance and compares it to the network's own km-by-class,
plus the minor-road share of LONG trips (a 10 km trip on residential streets is implausible).
"""
import duckdb, time

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
con = duckdb.connect(f"{D}/db/osm.duckdb", read_only=True)
con.execute("PRAGMA threads=8"); con.execute("INSTALL spatial; LOAD spatial;")

MINOR = "('residential','service','living_street','unclassified','road','track','path')"
SAMPLE_MOD = 50          # every Nth trip -> ~8.5k trips, ~180k segments

t0 = time.time()
con.execute("""CREATE TEMP TABLE net2m AS
  SELECT way_id, cls, ST_Transform(ST_SetCRS(geom,'OGC:CRS84'),'EPSG:23700') AS geom
  FROM net2 WHERE kind='road'""")
print(f"network: {con.execute('SELECT count(*) FROM net2m').fetchone()[0]:,} ways  ({time.time()-t0:.0f}s)", flush=True)

con.execute(f"""CREATE TEMP TABLE rv AS
  SELECT i, xy, unnest(range(1, len(xy), 2)) AS k
  FROM routed_geom WHERE i % {SAMPLE_MOD} = 0""")
con.execute("""CREATE TEMP TABLE vp AS
  SELECT i, (k-1)/2 AS seg,
         ST_Transform(ST_SetCRS(ST_Point(xy[k], xy[k+1]),'OGC:CRS84'),'EPSG:23700') AS pt
  FROM rv""")
con.execute("""CREATE TEMP TABLE mid AS
  SELECT row_number() OVER () AS sid, i, seg,
         ST_Point((ST_X(a)+ST_X(b))/2, (ST_Y(a)+ST_Y(b))/2) AS m, ST_Distance(a,b) AS len
  FROM (SELECT i, seg, pt AS a, lead(pt) OVER (PARTITION BY i ORDER BY seg) AS b FROM vp)
  WHERE b IS NOT NULL AND ST_Distance(a,b) > 1""")
nseg = con.execute("SELECT count(*) FROM mid").fetchone()[0]
print(f"route segments: {nseg:,}  ({time.time()-t0:.0f}s)", flush=True)

con.execute("""CREATE TEMP TABLE cand AS
  SELECT m.sid, m.i, w.cls, m.len, ST_Distance(m.m, w.geom) AS d
  FROM mid m JOIN net2m w ON ST_Intersects(ST_Expand(m.m, 40.0), w.geom)""")
con.execute("""CREATE TEMP TABLE picked AS
  SELECT sid, i, cls, len FROM
    (SELECT *, row_number() OVER (PARTITION BY sid ORDER BY d) AS rn FROM cand) WHERE rn=1""")
print(f"snapped {con.execute('SELECT count(*) FROM picked').fetchone()[0]:,} segments  ({time.time()-t0:.0f}s)", flush=True)

tot = con.execute("SELECT sum(len)/1000 FROM picked").fetchone()[0]
print(f"\n=== routed distance by road class (sampled {nseg:,} segments, {tot:,.0f} km) ===")
print(con.execute("""
  SELECT cls,
         round(sum(len)/1000) AS routed_km,
         round(100.0*sum(len)/sum(sum(len)) OVER (),1) AS routed_pct,
         round((SELECT sum(ST_Length(geom))/1000 FROM net2m n WHERE n.cls=p.cls)) AS net_km,
         round(100.0*(SELECT sum(ST_Length(geom)) FROM net2m n WHERE n.cls=p.cls)
               /(SELECT sum(ST_Length(geom)) FROM net2m)) AS net_pct
  FROM picked p GROUP BY cls ORDER BY routed_km DESC LIMIT 14""").df().to_string(index=False))

print(f"\n=== minor-road share by trip length (minor = {MINOR}) ===")
print(con.execute(f"""
  WITH tl AS (SELECT i, len(xy)/2 AS pts, ST_Distance_Sphere(
      ST_Point(xy[1],xy[2]), ST_Point(xy[-2],xy[-1]))/1000 AS km FROM routed_geom WHERE i % {SAMPLE_MOD}=0),
  agg AS (SELECT p.i, sum(p.len) tot, sum(p.len) FILTER (WHERE p.cls IN {MINOR}) minor
          FROM picked p GROUP BY p.i)
  SELECT CASE WHEN t.km<2 THEN 'a) <2 km' WHEN t.km<5 THEN 'b) 2-5 km'
              WHEN t.km<10 THEN 'c) 5-10 km' ELSE 'd) >=10 km' END band,
         count(*) trips, round(sum(a.tot)/1000) km,
         round(100.0*sum(a.minor)/sum(a.tot),1) minor_pct
  FROM agg a JOIN tl t USING (i) GROUP BY 1 ORDER BY 1""").df().to_string(index=False))

print("\n=== how far a routed line sits from its own straight line (sanity) ===")
print("(a route that follows the road network is longer than the straight line; 1.0 would be a ruler)")
print(con.execute(f"""
  SELECT round(median(ST_Distance_Sphere(ST_Point(xy[1],xy[2]), ST_Point(xy[-2],xy[-1]))/1000),2) med_km
  FROM routed_geom WHERE i % {SAMPLE_MOD}=0""").df().to_string(index=False))
print(f"\n{t0 and (time.time()-t0):.0f}s")
