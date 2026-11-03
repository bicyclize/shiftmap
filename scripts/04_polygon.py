import duckdb

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
con = duckdb.connect()
con.execute("PRAGMA threads=8")
con.execute("INSTALL spatial; LOAD spatial;")

# ---- rebuild legs WITH trip_seq, then trip polylines (Aug 12) ----
con.execute(f"""
CREATE OR REPLACE TABLE trip_lines AS
WITH l AS (SELECT * FROM read_parquet('{D}/out/legs_aug12.parquet')
           WHERE dt_s>=10 AND dist_m/dt_s*3.6<=150),
g AS (SELECT *, p_ts - lag(ts) OVER w AS gap_s FROM l WINDOW w AS (PARTITION BY aid ORDER BY p_ts)),
s AS (SELECT *, SUM(CASE WHEN gap_s IS NULL OR gap_s>180 THEN 1 ELSE 0 END) OVER w AS trip_seq
      FROM g WINDOW w AS (PARTITION BY aid ORDER BY p_ts)),
pts AS (
  SELECT aid, trip_seq, p_ts AS t, o_lat AS lat, o_lon AS lon, 0 AS ord FROM s
  UNION ALL
  SELECT aid, trip_seq, ts  AS t, d_lat AS lat, d_lon AS lon, 1 AS ord FROM s
),
lines AS (
  SELECT aid, trip_seq,
         ST_MakeLine(list(ST_Point(lon,lat) ORDER BY t, ord)) AS geom,
         min(t) t_start, max(t) t_end, count(*)/2 AS n_legs
  FROM pts GROUP BY aid, trip_seq
)
SELECT * FROM lines WHERE n_legs >= 2
""")
print("trip polylines:", con.execute("SELECT count(*) FROM trip_lines").fetchone()[0])

# ---- demo polygon: inner Pest (Belváros / Lipótváros / Erzsébetváros) ----
con.execute("""CREATE OR REPLACE TABLE demo_poly AS
  SELECT ST_GeomFromText('POLYGON((19.030 47.475, 19.075 47.475, 19.075 47.520, 19.030 47.520, 19.030 47.475))') AS geom""")

print("\n=== trips vs demo polygon (inner Pest) ===")
print(con.execute(f"""
WITH tl AS (
  SELECT l.aid, l.trip_seq, l.geom,
     ST_Contains((SELECT geom FROM demo_poly), ST_StartPoint(l.geom)) AS starts_in,
     ST_Contains((SELECT geom FROM demo_poly), ST_EndPoint(l.geom))   AS ends_in,
     ST_Intersects((SELECT geom FROM demo_poly), l.geom)              AS touches
  FROM trip_lines l
)
SELECT
  count(*) AS total_trips,
  sum(starts_in::INT) AS o_inside,
  sum(ends_in::INT)   AS d_inside,
  sum((starts_in IS FALSE AND ends_in IS FALSE AND touches)::INT) AS through_only,
  sum((starts_in AND ends_in)::INT) AS internal,
  sum(touches::INT)   AS any_contact
FROM tl
""").df().to_string())

print("\n=== sample of through-only trips ===")
print(con.execute(f"""
WITH tl AS (
  SELECT l.aid, l.trip_seq, l.geom, l.t_start, l.t_end, l.n_legs,
     ST_Contains((SELECT geom FROM demo_poly), ST_StartPoint(l.geom)) AS starts_in,
     ST_Contains((SELECT geom FROM demo_poly), ST_EndPoint(l.geom))   AS ends_in,
     ST_Intersects((SELECT geom FROM demo_poly), l.geom)              AS touches
  FROM trip_lines l
)
SELECT aid, t_start, t_end, n_legs, round(ST_Length(geom)) AS len_m
FROM tl
WHERE starts_in IS FALSE AND ends_in IS FALSE AND touches
ORDER BY len_m DESC LIMIT 8
""").df().to_string())

# ---- export GeoJSON of trips touching the polygon (for the map) ----
con.execute(f"""
COPY (
  WITH tl AS (
    SELECT l.aid, l.trip_seq, l.geom,
       ST_Contains((SELECT geom FROM demo_poly), ST_StartPoint(l.geom)) AS starts_in,
       ST_Contains((SELECT geom FROM demo_poly), ST_EndPoint(l.geom))   AS ends_in,
       ST_Intersects((SELECT geom FROM demo_poly), l.geom)              AS touches
    FROM trip_lines l
  )
  SELECT aid, trip_seq,
    CASE WHEN starts_in AND ends_in THEN 'internal'
         WHEN starts_in THEN 'origin_in'
         WHEN ends_in THEN 'dest_in'
         ELSE 'through' END AS category,
    ST_AsGeoJSON(geom) AS geometry
  FROM tl WHERE touches
) TO '{D}/out/trips_through_demo.geojson' (FORMAT JSON)
""")
print("\nexported -> out/trips_through_demo.geojson")
