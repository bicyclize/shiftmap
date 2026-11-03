import duckdb, time

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
con = duckdb.connect()
con.execute("PRAGMA threads=8")

AUG = f"{D}/data/raw_aug/2023-08-12.csv.gz"
MAY = f"{D}/data/raw_may/08/*.csv.gz"

print("=" * 70)
print("AUG 12 SCHEMA")
print("=" * 70)
print(con.execute(f"DESCRIBE SELECT * FROM read_csv_auto('{AUG}', header=true)").df().to_string())

def profile(label, src, aid_col="aid"):
    print("\n" + "=" * 70)
    print(label)
    print("=" * 70)
    t0 = time.time()
    q = f"""
    SELECT count(*) n, count(DISTINCT {aid_col}) devices,
           to_timestamp(min(timestamp)) t_min, to_timestamp(max(timestamp)) t_max,
           min(latitude) lat_min, max(latitude) lat_max,
           min(longitude) lon_min, max(longitude) lon_max
    FROM read_csv_auto('{src}', header=true)
    """
    print(con.execute(q).df().to_string())
    print(f"[read {time.time()-t0:.1f}s]")

    print("\n-- location_method --")
    print(con.execute(f"SELECT location_method, count(*) n, round(100.0*count(*)/sum(count(*)) OVER (),2) pct FROM read_csv_auto('{src}',header=true) GROUP BY 1 ORDER BY n DESC").df().to_string())

    print("\n-- horizontal_accuracy percentiles --")
    print(con.execute(f"SELECT quantile_cont(horizontal_accuracy,[0.1,0.5,0.9,0.99]) hacc_pct FROM read_csv_auto('{src}',header=true) WHERE horizontal_accuracy>0").df().to_string())

    print("\n-- points per device --")
    ppd = con.execute(f"SELECT {aid_col} a, count(*) c FROM read_csv_auto('{src}',header=true) GROUP BY 1").df()
    print(ppd['c'].describe(percentiles=[0.1,0.25,0.5,0.75,0.9,0.99]).to_string())
    print(f"devices: {len(ppd):,} | >=10 pts: {(ppd['c']>=10).sum():,} | >=50: {(ppd['c']>=50).sum():,}")

profile("AUG 12 (2023-08-12)", AUG, "aid")
profile("MAY 08 (19 hour-files)", MAY, "device_aid")
