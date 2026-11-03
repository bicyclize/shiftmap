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


MAY = f"{D}/data/raw_may/08/*.csv.gz"
AGG_LAT0, AGG_LAT1, AGG_LON0, AGG_LON1 = 46.8, 48.15, 18.25, 20.25   # agglomeration + commuter rail corridors
BP_LAT0, BP_LAT1, BP_LON0, BP_LON1 = 47.30, 47.66, 18.90, 19.40      # Budapest city bbox
HACC, LOOKAHEAD, STAY_R, GAP_MAX = 150, 600, 200, 900

# ---------- 1. rail stations ----------
con.execute(f"""CREATE OR REPLACE TABLE st_mav AS
  SELECT 'MÁV' op, stop_name AS stn_name, stop_lat lat, stop_lon lon
  FROM read_csv_auto('{D}/gtfsMavMenetrend/stops.txt', header=true)
  WHERE stop_lat IS NOT NULL AND stop_lon IS NOT NULL""")
con.execute(f"""CREATE OR REPLACE TABLE st_hev AS
  SELECT DISTINCT 'HÉV' op, s.stop_name AS stn_name, s.stop_lat lat, s.stop_lon lon
  FROM read_csv_auto('{D}/budapest_gtfs/stops.txt') s
  JOIN read_csv_auto('{D}/budapest_gtfs/stop_times.txt', ignore_errors=true) st USING (stop_id)
  JOIN read_csv_auto('{D}/budapest_gtfs/trips.txt') t USING (trip_id)
  JOIN read_csv_auto('{D}/budapest_gtfs/routes.txt') r USING (route_id)
  WHERE r.route_type IN (2,109) AND s.stop_lat IS NOT NULL""")
con.execute("""CREATE OR REPLACE TABLE stations AS
  SELECT * FROM st_mav UNION SELECT * FROM st_hev""")
print("stations MÁV / HÉV / total:",
      con.execute("SELECT (SELECT count(*) FROM st_mav),(SELECT count(*) FROM st_hev),(SELECT count(*) FROM stations)").fetchone())
print("stations in agglomeration bbox:",
      con.execute(f"SELECT count(*) FROM stations WHERE lat BETWEEN {AGG_LAT0} AND {AGG_LAT1} AND lon BETWEEN {AGG_LON0} AND {AGG_LON1}").fetchone()[0])

# ---------- 2. May trips in agglomeration ----------
t0 = time.time()
con.execute(f"""
CREATE OR REPLACE TABLE w_sub AS
WITH p AS (
  SELECT CAST(timestamp AS BIGINT) ts, device_aid AS aid, latitude lat, longitude lon
  FROM read_csv_auto('{MAY}', header=true)
  WHERE latitude BETWEEN {AGG_LAT0} AND {AGG_LAT1} AND longitude BETWEEN {AGG_LON0} AND {AGG_LON1}
    AND horizontal_accuracy BETWEEN 0 AND {HACC} AND device_aid IS NOT NULL)
SELECT *, sqrt(power((max(lat) OVER f - min(lat) OVER f)*111320,2)
             + power((max(lon) OVER f - min(lon) OVER f)*111320*cos(radians(lat)),2)) AS span_m
FROM p WINDOW f AS (PARTITION BY aid ORDER BY ts RANGE BETWEEN CURRENT ROW AND {LOOKAHEAD} FOLLOWING)""")
print("agg pings:", con.execute("SELECT count(*) FROM w_sub").fetchone()[0], f"({time.time()-t0:.1f}s)")

seg = f"""
  WITH m AS (SELECT *, (span_m>{STAY_R}) AS moving, ts-lag(ts) OVER wf AS gap_s,
                    lag(span_m>{STAY_R}) OVER wf AS was_moving
             FROM w_sub WINDOW wf AS (PARTITION BY aid ORDER BY ts)),
  s AS (SELECT *, SUM(CASE WHEN moving AND (was_moving IS DISTINCT FROM TRUE OR gap_s IS NULL OR gap_s>{GAP_MAX})
                      THEN 1 ELSE 0 END) OVER wv AS trip_seq
        FROM m WINDOW wv AS (PARTITION BY aid ORDER BY ts))
"""
con.execute(f"""CREATE OR REPLACE TABLE tp_sub AS {seg}
  SELECT aid, trip_seq, ts, lat, lon,
    mdist(lag(lon) OVER w, lag(lat) OVER w, lon,lat) d_m
  FROM s WHERE moving WINDOW w AS (PARTITION BY aid, trip_seq ORDER BY ts)""")
con.execute(f"""CREATE OR REPLACE TABLE tr_sub AS {seg}
  SELECT aid, trip_seq, min(ts) t_start, max(ts) t_end, max(ts)-min(ts) dur_s, count(*) n_pts,
    arg_min(lat,ts) o_lat, arg_min(lon,ts) o_lon, arg_max(lat,ts) d_lat, arg_max(lon,ts) d_lon
  FROM s WHERE moving GROUP BY aid, trip_seq""")
con.execute(f"""CREATE OR REPLACE TABLE trips_sub AS
  SELECT t.*, p.path_m,
    mdist(t.o_lon,t.o_lat, t.d_lon,t.d_lat) od_m
  FROM tr_sub t JOIN (SELECT aid,trip_seq,sum(d_m) path_m FROM tp_sub GROUP BY 1,2) p USING (aid,trip_seq)
  WHERE t.n_pts>=3 AND t.dur_s BETWEEN 60 AND 3*3600 AND p.path_m>=300""")
print("agg trips:", con.execute("SELECT count(*) FROM trips_sub").fetchone()[0])

# ---------- 3. nearest rail station to origin & destination ----------
con.execute(f"""CREATE OR REPLACE TABLE endpoints AS
  SELECT aid, trip_seq, 'O' AS ep, o_lat lat, o_lon lon FROM trips_sub
  UNION ALL SELECT aid, trip_seq, 'D' AS ep, d_lat, d_lon FROM trips_sub""")
con.execute("""CREATE OR REPLACE TABLE ep_stn AS
  SELECT e.aid, e.trip_seq, e.ep, s.stn_name, s.op stn_op,
    mdist(e.lon,e.lat, s.lon,s.lat) AS d_m
  FROM (SELECT a.aid,a.trip_seq,a.ep,a.lat,a.lon FROM endpoints a) e
  JOIN stations s ON abs(e.lat-s.lat)<0.12 AND abs(e.lon-s.lon)<0.18""")
con.execute("""CREATE OR REPLACE TABLE nearest AS
  SELECT aid, trip_seq, ep,
    arg_min(stn_name, d_m) stn, arg_min(d_m, d_m) d_stn
  FROM ep_stn GROUP BY aid, trip_seq, ep""")

con.execute(f"""CREATE OR REPLACE TABLE bt AS
  SELECT t.aid, t.trip_seq, t.o_lat,t.o_lon,t.d_lat,t.d_lon, t.path_m, t.dur_s, t.od_m,
    mdist(t.o_lon,t.o_lat, 19.0402,47.4979) o_to_bp_m,
    (t.o_lat NOT BETWEEN {BP_LAT0} AND {BP_LAT1} OR t.o_lon NOT BETWEEN {BP_LON0} AND {BP_LON1}) AS suburb_origin,
    no.stn o_stn, no.d_stn o_to_stn,
    nd.stn d_stn, nd.d_stn d_to_stn
  FROM trips_sub t
  JOIN nearest no ON no.aid=t.aid AND no.trip_seq=t.trip_seq AND no.ep='O'
  JOIN nearest nd ON nd.aid=t.aid AND nd.trip_seq=t.trip_seq AND nd.ep='D'""")

AGG_KM = 40   # agglomeration = origin within this radius of Budapest centre
CAND = f"suburb_origin AND o_to_bp_m<={AGG_KM*1000} AND o_to_stn<=3000 AND d_to_stn<=3000 AND od_m>8000"

print("\n=== SUBURB-ORIGIN trips (May 8) ===")
print(con.execute(f"""SELECT
  count(*) FILTER (WHERE suburb_origin) suburb_trips,
  count(*) FILTER (WHERE suburb_origin AND o_to_bp_m<={AGG_KM*1000}) agglomeration,
  count(*) FILTER (WHERE {CAND}) bike_train_cand,
  count(*) FILTER (WHERE suburb_origin AND od_m<=5000) short_direct_bikeable
  FROM bt""").df().to_string())

print("\n-- O-D straight-line distance (km), suburb+agglomeration --")
print(con.execute(f"SELECT quantile_cont(od_m/1000,[0.1,0.25,0.5,0.75,0.9]) FROM bt WHERE suburb_origin AND o_to_bp_m<={AGG_KM*1000}").df().to_string())
print("\n-- origin -> nearest rail station (km) --")
print(con.execute(f"SELECT quantile_cont(o_to_stn/1000,[0.1,0.25,0.5,0.75,0.9]) FROM bt WHERE {CAND}").df().to_string())
print("\n-- dest -> nearest rail station (km) --")
print(con.execute(f"SELECT quantile_cont(d_to_stn/1000,[0.1,0.25,0.5,0.75,0.9]) FROM bt WHERE {CAND}").df().to_string())
print("\n-- top ORIGIN stations of bike+train candidates --")
print(con.execute(f"SELECT o_stn, count(*) n FROM bt WHERE {CAND} GROUP BY 1 ORDER BY n DESC LIMIT 15").df().to_string())
print("\n-- where do the candidate DESTINATIONS land? --")
print(con.execute(f"""SELECT CASE WHEN d_lat BETWEEN {BP_LAT0} AND {BP_LAT1} AND d_lon BETWEEN {BP_LON0} AND {BP_LON1}
            THEN 'in Budapest' ELSE 'outside Budapest' END dz, count(*) n
  FROM bt WHERE {CAND} GROUP BY 1""").df().to_string())
con.execute("COPY bt TO 'out/bt_may08.parquet' (FORMAT PARQUET)")
print("\nsaved -> out/bt_may08.parquet")
