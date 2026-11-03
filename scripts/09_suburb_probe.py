import duckdb
D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
con = duckdb.connect(f"{D}/db/mobility.duckdb")

MAY = f"{D}/data/raw_may/08/*.csv.gz"
AUG = f"{D}/data/raw_aug/2023-08-12.csv.gz"

print("=== DATA EXTENT ===")
for lab, src, idc in [("AUG 12", AUG, "aid"), ("MAY 08", MAY, "device_aid")]:
    print(f"\n-- {lab} --")
    print(con.execute(f"""
      SELECT count(*) n,
        sum(CASE WHEN latitude BETWEEN 47.30 AND 47.66 AND longitude BETWEEN 18.90 AND 19.40 THEN 1 ELSE 0 END) in_bp,
        sum(CASE WHEN latitude BETWEEN 45.7 AND 48.6 AND longitude BETWEEN 16.0 AND 23.0
                 AND NOT (latitude BETWEEN 47.30 AND 47.66 AND longitude BETWEEN 18.90 AND 19.40) THEN 1 ELSE 0 END) in_hu_outside_bp,
        round(min(latitude),3) lat0, round(max(latitude),3) lat1,
        round(min(longitude),3) lon0, round(max(longitude),3) lon1
      FROM read_csv_auto('{src}', header=true)""").df().to_string())

print("\n=== BKK GTFS route types ===")
print(con.execute(f"SELECT route_type, count(*) routes FROM read_csv_auto('{D}/budapest_gtfs/routes.txt') GROUP BY 1 ORDER BY 2 DESC").df().to_string())
print("\n=== MÁV GTFS route types ===")
print(con.execute(f"SELECT route_type, count(*) routes FROM read_csv_auto('{D}/gtfsMavMenetrend/routes.txt') GROUP BY 1 ORDER BY 2 DESC").df().to_string())

print("\n=== BKK stops columns / sample ===")
print(con.execute(f"DESCRIBE SELECT * FROM read_csv_auto('{D}/budapest_gtfs/stops.txt')").df().to_string())
print("\n=== MÁV stops columns / count ===")
print(con.execute(f"DESCRIBE SELECT * FROM read_csv_auto('{D}/gtfsMavMenetrend/stops.txt', header=true)").df().to_string())

# HÉV / rail stops in BKK: routes with route_type rail; join trips->stops
print("\n=== BKK stops reached by rail-type routes (HÉV/MÁV-in-BKK) ===")
print(con.execute(f"""
  SELECT count(DISTINCT s.stop_id) stations
  FROM read_csv_auto('{D}/budapest_gtfs/stops.txt') s
  JOIN read_csv_auto('{D}/budapest_gtfs/stop_times.txt') st USING (stop_id)
  JOIN read_csv_auto('{D}/budapest_gtfs/trips.txt') t USING (trip_id)
  JOIN read_csv_auto('{D}/budapest_gtfs/routes.txt') r USING (route_id)
  WHERE r.route_type = 2
""").df().to_string())
