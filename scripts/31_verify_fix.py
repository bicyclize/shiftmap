"""Verify the distance fix: old vs new platform, and check the detour ratio is now sane."""
import duckdb

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
c = duckdb.connect(f"{D}/db/osm.duckdb", read_only=True)

print("=== TRIP COUNTS ===")
print(c.execute("""
  SELECT 'old' src, count(*) trips, sum(bike_direct::INT) bike_direct, sum(btb::INT) btb, sum(btf::INT) btf
  FROM platform_old
  UNION ALL
  SELECT 'new', count(*), sum(bike_direct::INT), sum(btb::INT), sum(btf::INT) FROM platform
  """).df().to_string())

print("\n=== MEDIAN DISTANCES (m) ===")
print(c.execute("""
  SELECT 'old' src, round(median(od_m)) od_m, round(median(path_m)) path_m,
         round(median(path_m/nullif(od_m,0)),3) detour
  FROM platform_old WHERE od_m>500
  UNION ALL
  SELECT 'new', round(median(od_m)), round(median(path_m)), round(median(path_m/nullif(od_m,0)),3)
  FROM platform WHERE od_m>500
  """).df().to_string())

print("\n=== DETOUR RATIO: should now be >= 1 (a path cannot be shorter than the straight line) ===")
for tbl in ('platform_old', 'platform'):
    r = c.execute(f"""
      SELECT count(*) n,
        round(100.0*count(*) FILTER (WHERE path_m < od_m)/count(*),1) pct_impossible
      FROM {tbl} WHERE od_m>1000""").fetchone()
    print(f"  {tbl:14s} {r[0]:>8,} trips | {r[1]:>5}% have path_m < od_m  (impossible => broken distances)")

print("\n=== BY AXIS: new od_m / true straight-line should be ~1.00 for every axis ===")
print(c.execute("""
  WITH f AS (SELECT abs(d_lon-o_lon) dlon, abs(d_lat-o_lat) dlat, od_m,
       sqrt(power((d_lon-o_lon)*111320*cos(radians((o_lat+d_lat)/2)),2)+power((d_lat-o_lat)*110540,2)) t
     FROM platform WHERE od_m>1000)
  SELECT CASE WHEN dlon > 3*dlat THEN 'mostly E-W' WHEN dlat > 3*dlon THEN 'mostly N-S' ELSE 'mixed' END axis,
     count(*) n, round(median(od_m/t),3) new_over_true
  FROM f GROUP BY 1 ORDER BY 2 DESC""").df().to_string())

print("\n=== station distances: are access/egress thresholds now applied to true metres? ===")
print(c.execute("""
  SELECT 'old' src, round(median(o_to_stn)) o_to_stn_med, sum(btb::INT) btb FROM platform_old
  UNION ALL SELECT 'new', round(median(o_to_stn)), sum(btb::INT) FROM platform""").df().to_string())
print("  (true distance to a station should be SMALLER than the old inflated value => more trips qualify)")
