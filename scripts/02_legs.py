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


# Budapest core bbox (generous)
LAT0, LAT1, LON0, LON1 = 47.30, 47.66, 18.90, 19.40
HACC_MAX = 150          # metres
DISP_MIN = 300          # metres: consecutive pings further apart than this = a movement leg
DT_MAX = 7200           # seconds: ignore gaps longer than this


def build(src, aid_col, tag):
    t0 = time.time()
    pts = f"""
      SELECT CAST(timestamp AS BIGINT) ts, {aid_col} AS aid,
             latitude lat, longitude lon, horizontal_accuracy hacc, location_method lm
      FROM read_csv_auto('{src}', header=true)
      WHERE latitude BETWEEN {LAT0} AND {LAT1} AND longitude BETWEEN {LON0} AND {LON1}
        AND horizontal_accuracy BETWEEN 0 AND {HACC_MAX}
        AND {aid_col} IS NOT NULL AND timestamp IS NOT NULL
    """
    n_pts = con.execute(f"SELECT count(*) FROM ({pts})").fetchone()[0]
    legs = f"""
      WITH s AS (
        SELECT *, lag(ts) OVER w p_ts, lag(lat) OVER w p_lat, lag(lon) OVER w p_lon
        FROM ({pts}) WINDOW w AS (PARTITION BY aid ORDER BY ts)
      )
      SELECT aid, p_ts, ts, ts - p_ts AS dt_s,
             p_lat o_lat, p_lon o_lon, lat d_lat, lon d_lon,
             mdist(p_lon, p_lat, lon, lat) AS dist_m
      FROM s
      WHERE p_ts IS NOT NULL AND (ts - p_ts) BETWEEN 1 AND {DT_MAX}
    """
    con.execute(f"CREATE OR REPLACE TABLE legs_{tag} AS SELECT * FROM ({legs}) WHERE dist_m >= {DISP_MIN}")
    con.execute(f"CREATE OR REPLACE TABLE move_{tag} AS SELECT * FROM ({legs}) WHERE dist_m >= {DISP_MIN}")
    print(f"\n{'='*70}\n{tag}  ({time.time()-t0:.1f}s)\n{'='*70}")
    print(f"filtered pings: {n_pts:,}")
    r = con.execute(f"""
      SELECT count(*) legs, count(DISTINCT aid) devices,
             round(avg(dist_m)) avg_m, round(median(dist_m)) med_m,
             round(avg(dt_s)) avg_dt_s, round(median(dt_s)) med_dt_s
      FROM legs_{tag}
    """).df()
    print(r.to_string())
    print("\nleg distance (m) percentiles:")
    print(con.execute(f"SELECT quantile_cont(dist_m,[0.1,0.25,0.5,0.75,0.9,0.99]) FROM legs_{tag}").df().to_string())
    print("\nimplied speed (km/h) = dist/dt percentiles:")
    print(con.execute(f"""SELECT quantile_cont(dist_m/dt_s*3.6,[0.1,0.25,0.5,0.75,0.9,0.99]) spd_kmh
                          FROM legs_{tag} WHERE dt_s>0 AND dist_m/dt_s*3.6 < 200""").df().to_string())
    print("\nlegs per device percentiles:")
    lpd = con.execute(f"SELECT aid, count(*) c FROM legs_{tag} GROUP BY 1").df()
    print(lpd['c'].describe(percentiles=[0.25,0.5,0.75,0.9,0.99]).to_string())
    # save
    out = f"{D}/out/legs_{tag}.parquet"
    con.execute(f"COPY legs_{tag} TO '{out}' (FORMAT PARQUET)")
    print(f"saved -> {out}")


AUG = f"{D}/data/raw_aug/2023-08-12.csv.gz"
MAY = f"{D}/data/raw_may/08/*.csv.gz"
build(AUG, "aid", "aug12")
build(MAY, "device_aid", "may08")
