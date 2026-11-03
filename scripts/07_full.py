"""Full trip + bike-potential pipeline. Stay-point segmentation -> trips -> polygons.
Run:  uv run --with duckdb --with numpy --with pandas python scripts/07_full.py
"""
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


LAT0, LAT1, LON0, LON1 = 47.30, 47.66, 18.90, 19.40
HACC, LOOKAHEAD, STAY_R, GAP_MAX = 150, 600, 200, 900
BIKE_KM = 5.0           # "could have been a bike" threshold

# demo polygon: inner Pest
con.execute("""CREATE OR REPLACE TABLE demo_poly AS
  SELECT ST_GeomFromText('POLYGON((19.030 47.475, 19.075 47.475, 19.075 47.520, 19.030 47.520, 19.030 47.475))') AS geom""")


def build(src, aid_col, tag):
    t0 = time.time()
    con.execute(f"""
    CREATE OR REPLACE TABLE w_{tag} AS
    WITH p AS (
      SELECT CAST(timestamp AS BIGINT) ts, {aid_col} AS aid, latitude lat, longitude lon
      FROM read_csv_auto('{src}', header=true)
      WHERE latitude BETWEEN {LAT0} AND {LAT1} AND longitude BETWEEN {LON0} AND {LON1}
        AND horizontal_accuracy BETWEEN 0 AND {HACC} AND {aid_col} IS NOT NULL)
    SELECT *, sqrt(power((max(lat) OVER f - min(lat) OVER f)*111320,2)
                 + power((max(lon) OVER f - min(lon) OVER f)*111320*cos(radians(lat)),2)) AS span_m
    FROM p
    WINDOW f AS (PARTITION BY aid ORDER BY ts RANGE BETWEEN CURRENT ROW AND {LOOKAHEAD} FOLLOWING)
    """)
    seg = f"""
      WITH m AS (SELECT *, (span_m>{STAY_R}) AS moving, ts-lag(ts) OVER wf AS gap_s,
                        lag(span_m>{STAY_R}) OVER wf AS was_moving
                 FROM w_{tag} WINDOW wf AS (PARTITION BY aid ORDER BY ts)),
      s AS (SELECT *, SUM(CASE WHEN moving AND (was_moving IS DISTINCT FROM TRUE OR gap_s IS NULL OR gap_s>{GAP_MAX})
                          THEN 1 ELSE 0 END) OVER wv AS trip_seq
            FROM m WINDOW wv AS (PARTITION BY aid ORDER BY ts))
    """
    con.execute(f"""CREATE OR REPLACE TABLE tp_{tag} AS {seg}
      SELECT aid, trip_seq, ts, lat, lon,
        mdist(lag(lon) OVER w, lag(lat) OVER w, lon,lat) d_m
      FROM s WHERE moving WINDOW w AS (PARTITION BY aid, trip_seq ORDER BY ts)""")
    con.execute(f"""CREATE OR REPLACE TABLE tr_{tag} AS {seg}
      SELECT aid, trip_seq, min(ts) t_start, max(ts) t_end, max(ts)-min(ts) dur_s, count(*) n_pts,
        arg_min(lat,ts) o_lat, arg_min(lon,ts) o_lon, arg_max(lat,ts) d_lat, arg_max(lon,ts) d_lon
      FROM s WHERE moving GROUP BY aid, trip_seq""")
    con.execute(f"""
    CREATE OR REPLACE TABLE final_{tag} AS
    SELECT t.*, p.path_m,
      mdist(t.o_lon,t.o_lat, t.d_lon,t.d_lat) AS od_m,
      (p.path_m <= {BIKE_KM*1000}) AS bikeable
    FROM tr_{tag} t JOIN (SELECT aid, trip_seq, sum(d_m) path_m FROM tp_{tag} GROUP BY 1,2) p
      USING (aid, trip_seq)
    WHERE t.n_pts>=3 AND t.dur_s BETWEEN 60 AND 3*3600 AND p.path_m >= 300""")
    con.execute(f"""CREATE OR REPLACE TABLE lines_{tag} AS
      SELECT l.aid, l.trip_seq, f.path_m, f.bikeable,
        ST_MakeLine(list(ST_Point(l.lon,l.lat) ORDER BY l.ts)) AS geom
      FROM tp_{tag} l JOIN final_{tag} f USING (aid, trip_seq) GROUP BY l.aid, l.trip_seq, f.path_m, f.bikeable""")
    # polygon cross-tab
    con.execute(f"""
    CREATE OR REPLACE TABLE poly_{tag} AS
    SELECT l.aid, l.trip_seq, l.path_m, l.bikeable, l.geom,
      ST_Contains((SELECT geom FROM demo_poly), ST_StartPoint(l.geom)) AS o_in,
      ST_Contains((SELECT geom FROM demo_poly), ST_EndPoint(l.geom))   AS d_in,
      ST_Intersects((SELECT geom FROM demo_poly), l.geom)              AS touches
    FROM lines_{tag} l""")
    print(f"\n{'='*72}\n{tag}   ({time.time()-t0:.1f}s)\n{'='*72}")
    print(con.execute(f"""SELECT count(*) trips, count(DISTINCT aid) devices,
      round(median(path_m)) med_m, round(median(path_m/nullif(od_m,0)),2) detour,
      round(100*avg(bikeable::INT),1) pct_bikeable FROM final_{tag}""").df().to_string())
    print("\n-- trips touching inner-Pest polygon, by category x bikeable --")
    print(con.execute(f"""
      SELECT CASE WHEN o_in AND d_in THEN 'internal' WHEN o_in THEN 'origin_in'
                  WHEN d_in THEN 'dest_in' ELSE 'through' END cat,
             count(*) n, sum(bikeable::INT) bikeable,
             round(100.0*sum(bikeable::INT)/count(*),1) pct_bike
      FROM poly_{tag} WHERE touches GROUP BY 1 ORDER BY n DESC""").df().to_string())
    con.execute(f"""COPY (SELECT aid, trip_seq,
        CASE WHEN o_in AND d_in THEN 'internal' WHEN o_in THEN 'origin_in'
             WHEN d_in THEN 'dest_in' ELSE 'through' END AS category,
        round(path_m) path_m, bikeable, ST_AsGeoJSON(geom) AS geometry
      FROM poly_{tag} WHERE touches) TO '{D}/out/trips_{tag}.geojson' (FORMAT JSON)""")
    print(f"geojson -> out/trips_{tag}.geojson")


build(f"{D}/data/raw_aug/2023-08-12.csv.gz", "aid", "aug12")
build(f"{D}/data/raw_may/08/*.csv.gz", "device_aid", "may08")
