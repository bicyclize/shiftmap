"""Rebuild trips per May day, then snap each trip's path onto the OSM network
(highways + railways), and export a browser parquet with real path geometry."""
import duckdb, glob, os, time

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
con = duckdb.connect(f"{D}/db/osm.duckdb")
con.execute("PRAGMA threads=8"); con.execute("INSTALL spatial; LOAD spatial;")

LAT0, LAT1, LON0, LON1 = 46.8, 48.15, 18.25, 20.25
BPLAT0, BPLAT1, BPLON0, BPLON1 = 47.30, 47.66, 18.90, 19.40
HACC, LOOKAHEAD, STAY_R, GAP_MAX = 150, 600, 200, 900
ACCESS_M, EGRESS_M, MIN_TRIP_M, BIKE_M, AGG_M = 2500, 1300, 8000, 5000, 40000
SNAP_M = 350          # max distance a point may be pulled to the network
MAXPT = 14            # max vertices kept per trip path

# ---- canonical metric distance (metres) ----
# ST_Distance_Sphere does NOT scale longitude by cos(latitude), and mis-scales latitude too:
# at Budapest it overstates east-west by up to +48% and understates north-south by ~-5.5%.
# This WGS84 series matches the EPSG:23700 projection to 0.005% and costs only arithmetic.
con.execute("""CREATE OR REPLACE MACRO mdist(lon_a, lat_a, lon_b, lat_b) AS
  sqrt(
    power((lat_b - lat_a) * (111132.92 - 559.82*cos(2*radians((lat_a+lat_b)/2))
                              + 1.175*cos(4*radians((lat_a+lat_b)/2))), 2)
  + power((lon_b - lon_a) * (111412.84*cos(radians((lat_a+lat_b)/2))
                              - 93.5*cos(3*radians((lat_a+lat_b)/2))), 2)
  )""")

# ---------------- rail stations + connectivity (as before) ----------------
con.execute(f"""CREATE OR REPLACE TABLE stations AS
  SELECT 'M'||CAST(stop_id AS VARCHAR) sid, 'MÁV' op, stop_name stn_name, stop_lat lat, stop_lon lon
  FROM read_csv_auto('{D}/gtfsMavMenetrend/stops.txt', header=true)
  WHERE stop_lat IS NOT NULL AND stop_lon IS NOT NULL
  UNION
  SELECT DISTINCT 'B'||s.stop_id, 'HÉV', s.stop_name, s.stop_lat, s.stop_lon
  FROM read_csv_auto('{D}/budapest_gtfs/stops.txt') s
  JOIN read_csv_auto('{D}/budapest_gtfs/stop_times.txt', ignore_errors=true) st USING (stop_id)
  JOIN read_csv_auto('{D}/budapest_gtfs/trips.txt') t USING (trip_id)
  JOIN read_csv_auto('{D}/budapest_gtfs/routes.txt') r USING (route_id)
  WHERE r.route_type IN (2,109)""")
con.execute(f"""CREATE OR REPLACE TABLE route_stops AS
  SELECT 'M'||CAST(t.route_id AS VARCHAR) rid, 'M'||CAST(st.stop_id AS VARCHAR) sid
  FROM read_csv_auto('{D}/gtfsMavMenetrend/trips.txt', header=true) t
  JOIN read_csv_auto('{D}/gtfsMavMenetrend/stop_times.txt', header=true) st USING (trip_id)
  UNION
  SELECT 'B'||t.route_id, 'B'||st.stop_id
  FROM read_csv_auto('{D}/budapest_gtfs/trips.txt') t
  JOIN read_csv_auto('{D}/budapest_gtfs/stop_times.txt', ignore_errors=true) st USING (trip_id)
  JOIN read_csv_auto('{D}/budapest_gtfs/routes.txt') r USING (route_id)
  WHERE r.route_type IN (1,2,109)""")
con.execute("""CREATE OR REPLACE TABLE net_m AS
  SELECT way_id, kind, cls, ST_Transform(ST_SetCRS(geom,'OGC:CRS84'),'EPSG:23700') AS geom
  FROM net2""")
print("net_m rows:", con.execute("SELECT count(*) FROM net_m").fetchone()[0])

days = sorted(d for d in os.listdir(f"{D}/data/raw_may") if os.path.isdir(f"{D}/data/raw_may/{d}"))
if os.environ.get('ONLY_DAY'):
    days = [os.environ['ONLY_DAY']]
print("days:", days)


def build_day(day):
    t0 = time.time()
    src = f"{D}/data/raw_may/{day}/*.csv.gz"
    con.execute(f"""CREATE OR REPLACE TABLE w AS
      WITH p AS (SELECT CAST(timestamp AS BIGINT) ts, device_aid AS aid, latitude lat, longitude lon
        FROM read_csv_auto('{src}', header=true)
        WHERE latitude BETWEEN {LAT0} AND {LAT1} AND longitude BETWEEN {LON0} AND {LON1}
          AND horizontal_accuracy BETWEEN 0 AND {HACC} AND device_aid IS NOT NULL)
      SELECT *, sqrt(power((max(lat) OVER f - min(lat) OVER f)*111132,2)
                   + power((max(lon) OVER f - min(lon) OVER f)*111320*cos(radians(lat)),2)) AS span_m
      FROM p WINDOW f AS (PARTITION BY aid ORDER BY ts RANGE BETWEEN CURRENT ROW AND {LOOKAHEAD} FOLLOWING)""")
    seg = f"""
      WITH m AS (SELECT *, (span_m>{STAY_R}) moving, ts-lag(ts) OVER wf gap_s,
                        lag(span_m>{STAY_R}) OVER wf was_moving
                 FROM w WINDOW wf AS (PARTITION BY aid ORDER BY ts)),
      s AS (SELECT *, SUM(CASE WHEN moving AND (was_moving IS DISTINCT FROM TRUE OR gap_s IS NULL OR gap_s>{GAP_MAX})
                          THEN 1 ELSE 0 END) OVER wv AS trip_seq
            FROM m WINDOW wv AS (PARTITION BY aid ORDER BY ts))
    """
    con.execute(f"""CREATE OR REPLACE TABLE tp AS {seg}
      SELECT aid, trip_seq, ts, lat, lon,
        mdist(lag(lon) OVER w, lag(lat) OVER w, lon, lat) d_m
      FROM s WHERE moving WINDOW w AS (PARTITION BY aid, trip_seq ORDER BY ts)""")
    con.execute(f"""CREATE OR REPLACE TABLE tr AS {seg}
      SELECT aid, trip_seq, min(ts) t_start, max(ts) t_end, max(ts)-min(ts) dur_s, count(*) n_pts,
        arg_min(lat,ts) o_lat, arg_min(lon,ts) o_lon, arg_max(lat,ts) d_lat, arg_max(lon,ts) d_lon
      FROM s WHERE moving GROUP BY aid, trip_seq""")
    con.execute("""CREATE OR REPLACE TABLE tips AS
      SELECT t.*, p.path_m, mdist(t.o_lon,t.o_lat,t.d_lon,t.d_lat) od_m
      FROM tr t JOIN (SELECT aid,trip_seq,sum(d_m) path_m FROM tp GROUP BY 1,2) p USING (aid,trip_seq)
      WHERE t.n_pts>=3 AND t.dur_s BETWEEN 60 AND 3*3600 AND p.path_m>=300""")
    # ---- subsample trip points (<= MAXPT) so snapping stays tractable ----
    con.execute(f"""CREATE OR REPLACE TABLE tps AS
      SELECT * FROM (
        SELECT tp.*, row_number() OVER w rn, count(*) OVER (PARTITION BY aid,trip_seq) cnt
        FROM tp JOIN tips USING (aid, trip_seq)
        WINDOW w AS (PARTITION BY aid, trip_seq ORDER BY ts))
      WHERE rn=1 OR rn=cnt OR MOD(rn, GREATEST(1, CAST(CEIL(cnt/{MAXPT}.0) AS BIGINT)))=0""")
    nv = con.execute("SELECT count(*) FROM tps").fetchone()[0]
    # ---- project to EOV (true metres) and snap each vertex to the nearest way ----
    con.execute("""CREATE OR REPLACE TABLE tps_m AS
      SELECT row_number() OVER () AS vid, *,
             ST_Transform(ST_SetCRS(ST_Point(lon,lat),'OGC:CRS84'),'EPSG:23700') AS pt_m
      FROM tps""")
    con.execute(f"""CREATE OR REPLACE TABLE snap AS
      WITH cand AS (
        SELECT s.vid, s.aid, s.trip_seq, s.ts, s.lon, s.lat, s.pt_m, n.geom AS ngeom,
               ST_Distance(s.pt_m, n.geom) AS d
        FROM tps_m s JOIN net_m n ON ST_Intersects(ST_Expand(s.pt_m, 600.0), n.geom)),
      best AS (
        SELECT vid, any_value(aid) aid, any_value(trip_seq) trip_seq, any_value(ts) ts,
               any_value(lon) lon, any_value(lat) lat, any_value(pt_m) pt_m,
               arg_min(ngeom, d) ngeom_best, min(d) AS d
        FROM cand GROUP BY vid),
      res AS (
        SELECT *, CASE WHEN d <= {SNAP_M} THEN ST_ClosestPoint(ngeom_best, pt_m) END AS sp
        FROM best)
      SELECT aid, trip_seq, ts, lon, lat, d AS snap_d,
             CASE WHEN sp IS NULL THEN NULL ELSE ST_X(ST_Transform(sp,'OGC:CRS84')) END AS snap_lon,
             CASE WHEN sp IS NULL THEN NULL ELSE ST_Y(ST_Transform(sp,'OGC:CRS84')) END AS snap_lat
      FROM res""")
    con.execute(f"""CREATE OR REPLACE TABLE paths AS
      SELECT '{day}' AS day_tag, aid, trip_seq,
        flatten(list([round(lon,5)::FLOAT, round(lat,5)::FLOAT] ORDER BY ts)) AS raw_xy,
        flatten(list([round(coalesce(snap_lon,lon),5)::FLOAT,
                      round(coalesce(snap_lat,lat),5)::FLOAT] ORDER BY ts)) AS path_xy,
        round(median(snap_d)) AS snap_med
      FROM snap GROUP BY aid, trip_seq""")
    # ---- trip attributes ----
    con.execute("""CREATE OR REPLACE TABLE ep AS
      SELECT aid,trip_seq,'O' ep, o_lat lat, o_lon lon FROM tips
      UNION ALL SELECT aid,trip_seq,'D' ep, d_lat, d_lon FROM tips""")
    con.execute("""CREATE OR REPLACE TABLE nearest AS
      SELECT aid,trip_seq,ep, arg_min(sid,d_m) sid, arg_min(stn_name,d_m) stn, arg_min(d_m,d_m) d_stn
      FROM (SELECT e.aid,e.trip_seq,e.ep,s.sid,s.stn_name,
              mdist(e.lon,e.lat,s.lon,s.lat) d_m
            FROM ep e JOIN stations s ON abs(e.lat-s.lat)<0.12 AND abs(e.lon-s.lon)<0.18)
      GROUP BY 1,2,3""")
    con.execute(f"""CREATE OR REPLACE TABLE att_{day} AS
      SELECT '{day}' AS day_tag, t.aid, t.trip_seq, t.t_start, t.dur_s,
        round(t.path_m)::INT path_m, round(t.od_m)::INT od_m,
        round(t.o_lat,6) o_lat, round(t.o_lon,6) o_lon, round(t.d_lat,6) d_lat, round(t.d_lon,6) d_lon,
        (t.o_lat BETWEEN {BPLAT0} AND {BPLAT1} AND t.o_lon BETWEEN {BPLON0} AND {BPLON1}) o_in_bp,
        (t.d_lat BETWEEN {BPLAT0} AND {BPLAT1} AND t.d_lon BETWEEN {BPLON0} AND {BPLON1}) d_in_bp,
        round(mdist(t.o_lon,t.o_lat,19.0402,47.4979))::INT o_to_bp_m,
        no.stn o_stn, round(no.d_stn)::INT o_to_stn, no.sid o_sid,
        nd.stn d_stn, round(nd.d_stn)::INT d_to_stn, nd.sid d_sid
      FROM tips t
      JOIN nearest no ON no.aid=t.aid AND no.trip_seq=t.trip_seq AND no.ep='O'
      JOIN nearest nd ON nd.aid=t.aid AND nd.trip_seq=t.trip_seq AND nd.ep='D'""")
    con.execute(f"""CREATE OR REPLACE TABLE day_{day} AS
      SELECT a.*, p.path_xy, p.snap_med FROM att_{day} a JOIN paths p USING (day_tag, aid, trip_seq)""")
    n = con.execute(f"SELECT count(*) FROM day_{day}").fetchone()[0]
    print(f"  day {day}: {n:,} trips, {nv:,} vertices  ({time.time()-t0:.0f}s)")
    for t in ('w','tp','tr','tips','tps','tps_m','snap','paths','ep','nearest','att_'+day):
        con.execute(f"DROP TABLE IF EXISTS {t}")


for d in days:
    build_day(d)

con.execute("CREATE OR REPLACE TABLE plat AS " +
            " UNION ALL BY NAME ".join(f"SELECT * FROM day_{d}" for d in days))

# rail connectivity levels
cd = """SELECT DISTINCT p.o_sid, p.d_sid FROM (SELECT DISTINCT o_sid,d_sid FROM plat) p
  JOIN route_stops a ON a.sid=p.o_sid JOIN route_stops b ON b.rid=a.rid AND b.sid=p.d_sid"""
c1 = """SELECT DISTINCT p.o_sid, p.d_sid FROM (SELECT DISTINCT o_sid,d_sid FROM plat) p
  JOIN route_stops a ON a.sid=p.o_sid JOIN route_stops x ON x.rid=a.rid
  JOIN route_stops c ON c.sid=x.sid JOIN route_stops d ON d.rid=c.rid AND d.sid=p.d_sid"""
con.execute(f"CREATE OR REPLACE TABLE pair_lvl AS SELECT o_sid,d_sid,max(lvl) lvl FROM "
            f"(SELECT o_sid,d_sid,2 lvl FROM ({cd}) UNION SELECT o_sid,d_sid,1 FROM ({c1})) GROUP BY 1,2")

con.execute(f"""CREATE OR REPLACE TABLE platform AS
  SELECT p.day_tag, p.t_start, p.dur_s, p.path_m, p.od_m,
    p.o_lat,p.o_lon,p.d_lat,p.d_lon, p.o_in_bp, p.d_in_bp, p.o_to_bp_m,
    p.o_stn, p.o_to_stn, p.d_stn, p.d_to_stn,
    coalesce(pl.lvl,0)::TINYINT rail_lvl, p.snap_med::SMALLINT snap_med,
    CASE WHEN p.o_in_bp AND p.d_in_bp THEN 'budapest'
         WHEN p.o_in_bp OR p.d_in_bp THEN 'suburb_bp' ELSE 'suburb_local' END AS trip_scope,
    (p.od_m<={BIKE_M}) bike_direct,
    (p.o_to_stn<={ACCESS_M} AND p.d_to_stn<={ACCESS_M} AND coalesce(pl.lvl,0)>=1 AND p.od_m>{MIN_TRIP_M}) btb,
    (p.o_to_stn<={ACCESS_M} AND p.d_to_stn<={EGRESS_M} AND coalesce(pl.lvl,0)>=1 AND p.od_m>{MIN_TRIP_M}) btf,
    p.path_xy
  FROM plat p LEFT JOIN pair_lvl pl ON pl.o_sid=p.o_sid AND pl.d_sid=p.d_sid""")

print("\n=== PLATFORM (with OSM paths) ===")
print(con.execute("""SELECT trip_scope, count(*) trips, sum(bike_direct::INT) bd, sum(btb::INT) btb,
   sum(btf::INT) btf, round(median(snap_med)) snap_med FROM platform GROUP BY 1 ORDER BY 2 DESC""").df().to_string())
con.execute(f"COPY platform TO '{D}/platform/trips_paths.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)")
print("trips_paths.parquet MB:", round(os.path.getsize(f'{D}/platform/trips_paths.parquet')/1e6, 1))
