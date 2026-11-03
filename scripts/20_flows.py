"""Compute trip volume per OSM way (from the snapped paths) -> flows.parquet for the map."""
import duckdb, os, time

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
con = duckdb.connect(f"{D}/db/osm.duckdb")
con.execute("PRAGMA threads=8"); con.execute("INSTALL spatial; LOAD spatial;")

# rebuild the metric network (net2 gained real way ids)
con.execute("""CREATE OR REPLACE TABLE net_m AS
  SELECT way_id, kind, cls, ST_Transform(ST_SetCRS(geom,'OGC:CRS84'),'EPSG:23700') AS geom
  FROM net2""")
print("net_m rows:", con.execute("SELECT count(*) FROM net_m").fetchone()[0])

t0 = time.time()
con.execute("""CREATE OR REPLACE TABLE tidx AS
  SELECT row_number() OVER () AS tid, trip_scope, path_xy
  FROM platform WHERE len(path_xy) >= 4""")
ntr = con.execute("SELECT count(*) FROM tidx").fetchone()[0]

con.execute("""CREATE OR REPLACE TABLE tv AS
  SELECT tid, trip_scope, i, path_xy[i] AS lon, path_xy[i+1] AS lat
  FROM (SELECT *, unnest(range(1, len(path_xy), 2)) AS i FROM tidx)""")
nv = con.execute("SELECT count(*) FROM tv").fetchone()[0]
print(f"trips {ntr:,} | vertices {nv:,}  ({time.time()-t0:.0f}s)")

con.execute("""CREATE OR REPLACE TABLE tvm AS
  SELECT tid, trip_scope, i, lon, lat,
         ST_Transform(ST_SetCRS(ST_Point(lon,lat),'OGC:CRS84'),'EPSG:23700') AS pt_m
  FROM tv""")

# nearest way per vertex — snapped vertices sit ON the network, so a tight bbox suffices
con.execute("""CREATE OR REPLACE TABLE hits AS
  WITH cand AS (
    SELECT t.tid, t.trip_scope, t.i, n.way_id, ST_Distance(t.pt_m, n.geom) AS d
    FROM tvm t JOIN net_m n ON ST_Intersects(ST_Expand(t.pt_m, 60.0), n.geom))
  SELECT tid, trip_scope, i, arg_min(way_id, d) AS way_id, min(d) AS d
  FROM cand GROUP BY tid, trip_scope, i""")
nh = con.execute("SELECT count(*) FROM hits").fetchone()[0]
print(f"vertex->way hits {nh:,}  ({time.time()-t0:.0f}s)")

con.execute("""CREATE OR REPLACE TABLE flows AS
  SELECT way_id,
    count(DISTINCT tid) AS n_all,
    count(DISTINCT tid) FILTER (WHERE trip_scope='budapest')     AS n_bp,
    count(DISTINCT tid) FILTER (WHERE trip_scope='suburb_bp')    AS n_sbp,
    count(DISTINCT tid) FILTER (WHERE trip_scope='suburb_local') AS n_sl
  FROM hits WHERE d <= 40 GROUP BY way_id""")

# flatten each way's coordinates (same list format the app already consumes)
con.execute("""CREATE OR REPLACE TABLE geo AS
  SELECT way_id, flatten(list([round(ST_X(p),5)::FLOAT, round(ST_Y(p),5)::FLOAT] ORDER BY k)) AS xy
  FROM (SELECT way_id, ST_PointN(geom, k::INTEGER) AS p, k
        FROM (SELECT way_id, geom, unnest(range(1, ST_NPoints(geom)+1)) AS k FROM net2))
  GROUP BY way_id""")

con.execute("""CREATE OR REPLACE TABLE flows_out AS
  SELECT f.way_id, f.n_all, f.n_bp, f.n_sbp, f.n_sl, n.kind, n.cls, g.xy
  FROM flows f JOIN net2 n USING (way_id) JOIN geo g USING (way_id)""")

print("\n=== FLOWS ===")
print(con.execute("""SELECT count(*) ways_with_trips,
    round(avg(n_all)) avg_trips, median(n_all) med_trips, max(n_all) max_trips
  FROM flows_out""").df().to_string())
print("\nbusiest 12 segments:")
print(con.execute("""SELECT cls, round(avg(n_all)) n FROM flows_out GROUP BY 1 ORDER BY 2 DESC LIMIT 12""").df().to_string())
con.execute(f"COPY flows_out TO '{D}/platform/flows.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)")
print("\nflows.parquet MB:", round(os.path.getsize(f'{D}/platform/flows.parquet')/1e6, 1))
