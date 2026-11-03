import duckdb, time

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
con = duckdb.connect()
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


LAT0, LAT1, LON0, LON1 = 47.30, 47.66, 18.90, 19.40
HACC = 150
LOOKAHEAD = 600     # s: window to judge "did the device stay put"
STAY_R = 200        # m: within this radius for LOOKAHEAD => stationary
GAP_MAX = 900       # s: split a moving run if pings gap beyond this

src, aid_col, tag = f"{D}/data/raw_aug/2023-08-12.csv.gz", "aid", "aug12"

t0 = time.time()
con.execute(f"""
CREATE OR REPLACE TABLE pts AS
SELECT CAST(timestamp AS BIGINT) ts, {aid_col} AS aid, latitude lat, longitude lon
FROM read_csv_auto('{src}', header=true)
WHERE latitude BETWEEN {LAT0} AND {LAT1} AND longitude BETWEEN {LON0} AND {LON1}
  AND horizontal_accuracy BETWEEN 0 AND {HACC} AND {aid_col} IS NOT NULL
""")

# stationary = spatial span of points in [ts, ts+LOOKAHEAD] is under STAY_R
con.execute(f"""
CREATE OR REPLACE TABLE w AS
SELECT *,
  sqrt( power((max(lat) OVER f - min(lat) OVER f)*111320, 2)
      + power((max(lon) OVER f - min(lon) OVER f)*111320*cos(radians(lat)), 2) ) AS span_m
FROM pts
WINDOW f AS (PARTITION BY aid ORDER BY ts RANGE BETWEEN CURRENT ROW AND {LOOKAHEAD} FOLLOWING)
""")
print(f"[window done {time.time()-t0:.1f}s]")

con.execute(f"""
CREATE OR REPLACE TABLE trips_{tag} AS
WITH m AS (
  SELECT *, (span_m > {STAY_R}) AS moving,
         ts - lag(ts) OVER wf AS gap_s,
         lag(span_m > {STAY_R}) OVER wf AS was_moving
  FROM w WINDOW wf AS (PARTITION BY aid ORDER BY ts)
),
s AS (
  SELECT *, SUM(CASE WHEN moving AND (was_moving IS DISTINCT FROM TRUE OR gap_s IS NULL OR gap_s > {GAP_MAX}) THEN 1 ELSE 0 END)
              OVER wv AS trip_seq
  FROM m WINDOW wv AS (PARTITION BY aid ORDER BY ts)
)
SELECT aid, trip_seq,
  min(ts) t_start, max(ts) t_end, max(ts)-min(ts) dur_s, count(*) n_pts,
  arg_min(lat,ts) o_lat, arg_min(lon,ts) o_lon, arg_max(lat,ts) d_lat, arg_max(lon,ts) d_lon
FROM s WHERE moving GROUP BY aid, trip_seq
""")

con.execute(f"""
CREATE OR REPLACE TABLE tr_{tag} AS
WITH t AS (SELECT * FROM trips_{tag} WHERE n_pts>=3 AND dur_s BETWEEN 60 AND 3*3600),
o AS (
  SELECT t.aid, t.trip_seq, t.o_lat, t.o_lon, t.d_lat, t.d_lon, t.t_start, t.t_end, t.dur_s,
    mdist(o_lon,o_lat, d_lon,d_lat) od_m
  FROM t
)
SELECT * FROM o
""")
# path distance from raw points assigned to each trip
con.execute(f"""
CREATE OR REPLACE TABLE trip_pts AS
WITH m AS (
  SELECT *, (span_m > {STAY_R}) AS moving,
         ts - lag(ts) OVER wf AS gap_s,
         lag(span_m > {STAY_R}) OVER wf AS was_moving
  FROM w WINDOW wf AS (PARTITION BY aid ORDER BY ts)
),
s AS (
  SELECT *, SUM(CASE WHEN moving AND (was_moving IS DISTINCT FROM TRUE OR gap_s IS NULL OR gap_s > {GAP_MAX}) THEN 1 ELSE 0 END)
              OVER wv AS trip_seq
  FROM m WINDOW wv AS (PARTITION BY aid ORDER BY ts)
)
SELECT aid, trip_seq, ts, lat, lon,
  mdist(lag(lon) OVER w, lag(lat) OVER w, lon, lat) d_m
FROM s WHERE moving
WINDOW w AS (PARTITION BY aid, trip_seq ORDER BY ts)
""")
con.execute(f"""
CREATE OR REPLACE TABLE final_{tag} AS
SELECT t.*, p.path_m FROM tr_{tag} t
JOIN (SELECT aid, trip_seq, sum(d_m) path_m FROM trip_pts GROUP BY 1,2) p USING (aid, trip_seq)
""")

print(f"\n{'='*70}\n{tag}  ({time.time()-t0:.1f}s)\n{'='*70}")
print(con.execute(f"""SELECT count(*) trips, count(DISTINCT aid) devices,
  round(median(path_m)) med_path_m, round(median(od_m)) med_od_m,
  round(median(path_m/nullif(od_m,0)),2) med_detour, round(median(dur_s/60),1) med_min
  FROM final_{tag}""").df().to_string())
print("\npath (km) percentiles:")
print(con.execute(f"SELECT quantile_cont(path_m/1000,[0.1,0.25,0.5,0.75,0.9,0.99]) FROM final_{tag}").df().to_string())
print("\n*** BIKEABILITY BANDS (actual trip length) ***")
print(con.execute(f"""
  SELECT band, count(*) n, round(100.0*count(*)/sum(count(*)) OVER (),1) pct
  FROM (SELECT CASE WHEN path_m<=2000 THEN '1_<=2km' WHEN path_m<=5000 THEN '2_2-5km'
        WHEN path_m<=8000 THEN '3_5-8km' WHEN path_m<=15000 THEN '4_8-15km'
        ELSE '5_>15km' END band FROM final_{tag})
  GROUP BY 1 ORDER BY 1""").df().to_string())
con.execute(f"COPY final_{tag} TO '{D}/out/final_{tag}.parquet' (FORMAT PARQUET)")
print("saved -> out/final_%s.parquet" % tag)
