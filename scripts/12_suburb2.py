import duckdb, time
D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
con = duckdb.connect(f"{D}/db/mobility.duckdb")
con.execute("PRAGMA threads=8"); con.execute("INSTALL spatial; LOAD spatial;")
# ---- canonical metric distance (metres) ----
# ST_Distance_Sphere does NOT scale longitude by cos(latitude) and mis-scales latitude too:
# at Budapest it overstates east-west by up to +48% and understates north-south by ~-5.5%.
# This WGS84 series matches the EPSG:23700 projection to 0.005% and costs only arithmetic.
con.execute("""CREATE OR REPLACE MACRO mdist(lon_a, lat_a, lon_b, lat_b) AS
  sqrt(
    power((lat_b - lat_a) * (111132.92 - 559.82*cos(2*radians((lat_a+lat_b)/2))
                              + 1.175*cos(4*radians((lat_a+lat_b)/2))), 2)
  + power((lon_b - lon_a) * (111412.84*cos(radians((lat_a+lat_b)/2))
                              - 93.5*cos(3*radians((lat_a+lat_b)/2))), 2)
  )""")


BP_LAT0, BP_LAT1, BP_LON0, BP_LON1 = 47.30, 47.66, 18.90, 19.40
ACCESS_M, EGRESS_M, AGG_M, MIN_TRIP_M = 2500, 1300, 40000, 8000

# ---------- stations WITH ids (needed for connectivity) ----------
con.execute(f"""CREATE OR REPLACE TABLE st_mav AS
  SELECT 'M'||CAST(stop_id AS VARCHAR) sid, 'MÁV' op, stop_name stn_name, stop_lat lat, stop_lon lon
  FROM read_csv_auto('{D}/gtfsMavMenetrend/stops.txt', header=true)
  WHERE stop_lat IS NOT NULL AND stop_lon IS NOT NULL""")
con.execute(f"""CREATE OR REPLACE TABLE st_hev AS
  SELECT DISTINCT 'B'||s.stop_id sid, 'HÉV' op, s.stop_name stn_name, s.stop_lat lat, s.stop_lon lon
  FROM read_csv_auto('{D}/budapest_gtfs/stops.txt') s
  JOIN read_csv_auto('{D}/budapest_gtfs/stop_times.txt', ignore_errors=true) st USING (stop_id)
  JOIN read_csv_auto('{D}/budapest_gtfs/trips.txt') t USING (trip_id)
  JOIN read_csv_auto('{D}/budapest_gtfs/routes.txt') r USING (route_id)
  WHERE r.route_type IN (2,109) AND s.stop_lat IS NOT NULL""")
con.execute("CREATE OR REPLACE TABLE stations AS SELECT * FROM st_mav UNION SELECT * FROM st_hev")

# ---------- nearest station (keep id) ----------
con.execute("""CREATE OR REPLACE TABLE endpoints AS
  SELECT aid, trip_seq, 'O' AS ep, o_lat AS lat, o_lon AS lon FROM trips_sub
  UNION ALL SELECT aid, trip_seq, 'D' AS ep, d_lat AS lat, d_lon AS lon FROM trips_sub""")
con.execute("""CREATE OR REPLACE TABLE ep_stn AS
  SELECT e.aid, e.trip_seq, e.ep, s.sid, s.stn_name, s.op,
    mdist(e.lon,e.lat, s.lon,s.lat) AS d_m
  FROM endpoints e JOIN stations s ON abs(e.lat-s.lat)<0.12 AND abs(e.lon-s.lon)<0.18""")
con.execute("""CREATE OR REPLACE TABLE nearest AS
  SELECT aid, trip_seq, ep, arg_min(sid,d_m) sid, arg_min(stn_name,d_m) stn, arg_min(d_m,d_m) d_stn
  FROM ep_stn GROUP BY 1,2,3""")

con.execute(f"""CREATE OR REPLACE TABLE bt AS
  SELECT t.aid, t.trip_seq, t.o_lat,t.o_lon,t.d_lat,t.d_lon, t.path_m, t.dur_s, t.od_m,
    mdist(t.o_lon,t.o_lat, 19.0402,47.4979) o_to_bp_m,
    (t.o_lat BETWEEN {BP_LAT0} AND {BP_LAT1} AND t.o_lon BETWEEN {BP_LON0} AND {BP_LON1}) AS o_in_bp,
    (t.d_lat BETWEEN {BP_LAT0} AND {BP_LAT1} AND t.d_lon BETWEEN {BP_LON0} AND {BP_LON1}) AS d_in_bp,
    no.stn o_stn, no.d_stn o_to_stn, no.sid o_sid,
    nd.stn d_stn, nd.d_stn d_to_stn, nd.sid d_sid
  FROM trips_sub t
  JOIN nearest no ON no.aid=t.aid AND no.trip_seq=t.trip_seq AND no.ep='O'
  JOIN nearest nd ON nd.aid=t.aid AND nd.trip_seq=t.trip_seq AND nd.ep='D'
  WHERE no.d_stn IS NOT NULL AND nd.d_stn IS NOT NULL""")

# ---------- rail connectivity: which stations share a line ----------
con.execute(f"""CREATE OR REPLACE TABLE route_stops AS
  SELECT 'M'||CAST(t.route_id AS VARCHAR) rid, 'M'||CAST(st.stop_id AS VARCHAR) sid
  FROM read_csv_auto('{D}/gtfsMavMenetrend/trips.txt', header=true) t
  JOIN read_csv_auto('{D}/gtfsMavMenetrend/stop_times.txt', header=true) st USING (trip_id)
  WHERE t.route_id IS NOT NULL
  UNION
  SELECT 'B'||t.route_id, 'B'||st.stop_id
  FROM read_csv_auto('{D}/budapest_gtfs/trips.txt') t
  JOIN read_csv_auto('{D}/budapest_gtfs/stop_times.txt', ignore_errors=true) st USING (trip_id)
  JOIN read_csv_auto('{D}/budapest_gtfs/routes.txt') r USING (route_id)
  WHERE r.route_type IN (1,2,109)""")
print("route_stops rows:", con.execute("SELECT count(*) FROM route_stops").fetchone()[0])

CAND_FILTER = f"(NOT o_in_bp) AND o_to_bp_m<={AGG_M} AND o_to_stn<={ACCESS_M} AND d_to_stn<={EGRESS_M} AND od_m>{MIN_TRIP_M}"
con.execute(f"""CREATE OR REPLACE TABLE cand AS SELECT * FROM bt WHERE {CAND_FILTER}""")
con.execute("CREATE OR REPLACE TABLE pairs AS SELECT DISTINCT o_sid, d_sid FROM cand")
con.execute("""CREATE OR REPLACE TABLE conn_d AS
  SELECT DISTINCT p.o_sid, p.d_sid FROM pairs p
  JOIN route_stops a ON a.sid=p.o_sid
  JOIN route_stops b ON b.rid=a.rid AND b.sid=p.d_sid""")
con.execute("""CREATE OR REPLACE TABLE conn_1 AS
  SELECT DISTINCT p.o_sid, p.d_sid FROM pairs p
  JOIN route_stops a ON a.sid=p.o_sid
  JOIN route_stops x ON x.rid=a.rid
  JOIN route_stops c ON c.sid=x.sid
  JOIN route_stops d ON d.rid=c.rid AND d.sid=p.d_sid""")
con.execute("""CREATE OR REPLACE TABLE conn AS
  SELECT o_sid, d_sid, 'direct' kind FROM conn_d
  UNION SELECT o_sid, d_sid, 'one_change' FROM conn_1""")

print(f"\n=== BIKE+TRAIN CANDIDATES  (access<={ACCESS_M/1000}km, egress<={EGRESS_M/1000}km) ===")
con.execute("""CREATE OR REPLACE TABLE cand_lvl AS
  SELECT l.aid, l.trip_seq,
    max(CASE WHEN cn.kind='direct' THEN 2 WHEN cn.kind='one_change' THEN 1 ELSE 0 END) lvl
  FROM cand l LEFT JOIN conn cn ON cn.o_sid=l.o_sid AND cn.d_sid=l.d_sid
  GROUP BY l.aid, l.trip_seq""")
print(con.execute("""SELECT count(*) candidates,
   count(*) FILTER (WHERE lvl=2) link_direct,
   count(*) FILTER (WHERE lvl=1) link_one_change,
   count(*) FILTER (WHERE lvl=0) no_link,
   round(100.0*count(*) FILTER (WHERE lvl>=1)/count(*),1) pct_reachable
  FROM cand_lvl""").df().to_string())
print("\n-- top origin stations (with rail/metro link) --")
print(con.execute("""SELECT l.o_stn, count(*) n, count(*) FILTER (WHERE c.lvl>=1) linked
  FROM cand l JOIN cand_lvl c USING (aid,trip_seq) GROUP BY 1 ORDER BY n DESC LIMIT 12""").df().to_string())

# ---------- NEW: suburban LOCAL trips (both ends outside Budapest) ----------
print("\n=== SUBURBAN LOCAL TRIPS (both ends outside Budapest, <=40 km) ===")
print(con.execute(f"""SELECT count(*) trips, count(DISTINCT aid) devices,
   round(median(od_m)/1000,1) med_km, round(quantile_cont(od_m,0.75)/1000,1) p75_km,
   round(quantile_cont(od_m,0.9)/1000,1) p90_km,
   round(100.0*avg((od_m<=5000)::INT),1) pct_le5km,
   round(100.0*avg((od_m<=8000)::INT),1) pct_le8km
  FROM bt WHERE (NOT o_in_bp) AND (NOT d_in_bp) AND o_to_bp_m<={AGG_M}""").df().to_string())
print("\n-- local suburb trip length distribution (km) --")
print(con.execute(f"""SELECT band, count(*) n, round(100.0*count(*)/sum(count(*)) OVER (),1) pct
  FROM (SELECT CASE WHEN od_m<=2000 THEN '1_<=2km' WHEN od_m<=5000 THEN '2_2-5km'
        WHEN od_m<=8000 THEN '3_5-8km' WHEN od_m<=15000 THEN '4_8-15km' ELSE '5_>15km' END band
        FROM bt WHERE (NOT o_in_bp) AND (NOT d_in_bp) AND o_to_bp_m<={AGG_M})
  GROUP BY 1 ORDER BY 1""").df().to_string())
con.execute("COPY cand TO 'out/cand_may08.parquet' (FORMAT PARQUET)")
