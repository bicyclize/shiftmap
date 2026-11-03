import duckdb, os
D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
con = duckdb.connect()
con.execute("INSTALL spatial; LOAD spatial;")
con.execute(f"""
COPY (
  SELECT day_tag, t_start, dur_s,
    path_m::INT AS path_m, od_m::INT AS od_m,
    o_lat, o_lon, d_lat, d_lon,
    o_in_bp, d_in_bp, o_to_bp_m::INT AS o_to_bp_m,
    o_stn, o_to_stn::INT AS o_to_stn, d_stn, d_to_stn::INT AS d_to_stn,
    rail_lvl::TINYINT AS rail_lvl,
    trip_scope, bike_direct, btb, btf,
    wkb
  FROM read_parquet('{D}/platform/trips.parquet')
) TO '{D}/platform/trips.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)
""")
print("lean trips.parquet MB:", round(os.path.getsize(f"{D}/platform/trips.parquet")/1e6, 1))
print(con.execute(f"SELECT count(*) n, sum(bike_direct::INT) bd, sum(btb::INT) btb, sum(btf::INT) btf FROM read_parquet('{D}/platform/trips.parquet')").df().to_string())
