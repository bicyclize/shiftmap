import duckdb, time

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
con = duckdb.connect()
con.execute("PRAGMA threads=8")
con.execute("INSTALL spatial; LOAD spatial;")
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


BREAK_S = 180      # >3 min without a >=300 m move = trip boundary
SPD_MAX = 150      # km/h: drop impossible legs (GPS jumps)

con.execute(f"""CREATE OR REPLACE VIEW clean_legs AS
  SELECT * FROM (
    SELECT * FROM read_parquet('{D}/out/legs_aug12.parquet')
    UNION ALL BY NAME
    SELECT * FROM read_parquet('{D}/out/legs_may08.parquet')
  )""")

def trips(tag, src):
    con.execute(f"""
    CREATE OR REPLACE TABLE trips_{tag} AS
    WITH l AS (
      SELECT * FROM read_parquet('{src}') WHERE dt_s >= 10 AND dist_m/dt_s*3.6 <= {SPD_MAX}
    ),
    g AS (SELECT *, p_ts - lag(ts) OVER w AS gap_s FROM l WINDOW w AS (PARTITION BY aid ORDER BY p_ts)),
    s AS (SELECT *, SUM(CASE WHEN gap_s IS NULL OR gap_s > {BREAK_S} THEN 1 ELSE 0 END) OVER w AS trip_seq
          FROM g WINDOW w AS (PARTITION BY aid ORDER BY p_ts))
    SELECT aid, trip_seq,
      min(p_ts) t_start, max(ts) t_end, max(ts)-min(p_ts) dur_s,
      arg_min(o_lat, p_ts) o_lat, arg_min(o_lon, p_ts) o_lon,
      arg_max(d_lat, ts) d_lat, arg_max(d_lon, ts) d_lon,
      sum(dist_m) path_m, sum(dt_s) move_s, count(*) n_legs,
      sum(dist_m)/nullif(sum(dt_s),0) spd_ms
    FROM s GROUP BY aid, trip_seq
    """)
    con.execute(f"""
    CREATE OR REPLACE TABLE tr_{tag} AS
    SELECT *,
      mdist(o_lon,o_lat, d_lon,d_lat) AS od_m,
      spd_ms*3.6 AS spd_kmh
    FROM trips_{tag}
    WHERE dur_s BETWEEN 120 AND 3*3600 AND path_m >= 500
    """)
    print(f"\n{'='*70}\n{tag}\n{'='*70}")
    print(con.execute(f"""SELECT count(*) trips, count(DISTINCT aid) devices, round(avg(path_m)) avg_m,
                          round(median(path_m)) med_m, round(median(dur_s)) med_dur_s,
                          round(median(spd_kmh),1) med_kmh FROM tr_{tag}""").df().to_string())
    print("\npath distance (m) percentiles:")
    print(con.execute(f"SELECT quantile_cont(path_m,[0.1,0.25,0.5,0.75,0.9,0.99]) d FROM tr_{tag}").df().to_string())
    print("\nduration (min) percentiles:")
    print(con.execute(f"SELECT quantile_cont(dur_s/60,[0.1,0.25,0.5,0.75,0.9,0.99]) d FROM tr_{tag}").df().to_string())
    print("\nspeed (km/h) percentiles:")
    print(con.execute(f"SELECT quantile_cont(spd_kmh,[0.1,0.25,0.5,0.75,0.9,0.99]) d FROM tr_{tag}").df().to_string())
    print("\nmode band by median speed (first-cut):")
    print(con.execute(f"""
      SELECT CASE
          WHEN spd_kmh < 7 THEN '0_walk_<7'
          WHEN spd_kmh < 25 THEN '1_bike_7-25'
          WHEN spd_kmh < 60 THEN '2_car_25-60'
          ELSE '3_fast_60+' END AS band,
        count(*) n, round(100.0*count(*)/sum(count(*)) OVER (),1) pct
      FROM tr_{tag} GROUP BY 1 ORDER BY 1""").df().to_string())
    out = f"{D}/out/trips_{tag}.parquet"
    con.execute(f"COPY tr_{tag} TO '{out}' (FORMAT PARQUET)")
    print("saved ->", out)

trips("aug12", f"{D}/out/legs_aug12.parquet")
trips("may08", f"{D}/out/legs_may08.parquet")
