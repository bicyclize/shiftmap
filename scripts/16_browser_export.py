import duckdb, os, json
D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
con = duckdb.connect()
con.execute(f"""
COPY (
  SELECT day_tag, t_start, dur_s, path_m, od_m, o_lat, o_lon, d_lat, d_lon,
         o_in_bp, d_in_bp, o_to_bp_m, o_stn, o_to_stn, d_stn, d_to_stn,
         rail_lvl, trip_scope, bike_direct, btb, btf
  FROM read_parquet('{D}/platform/trips.parquet')
) TO '{D}/platform/trips.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)
""")
mb = os.path.getsize(f"{D}/platform/trips.parquet")/1e6
print("browser trips.parquet MB:", round(mb,1))

# small precomputed summary so the UI has numbers before data loads
def bands(where="true"):
    r = con.execute(f"""SELECT count(*) n,
      sum(bike_direct::INT) bd, sum(btb::INT) btb, sum(btf::INT) btf,
      round(median(od_m)) med,
      count(*) FILTER (WHERE od_m<=2000) b1, count(*) FILTER (WHERE od_m>2000 AND od_m<=5000) b2,
      count(*) FILTER (WHERE od_m>5000 AND od_m<=8000) b3, count(*) FILTER (WHERE od_m>8000 AND od_m<=15000) b4,
      count(*) FILTER (WHERE od_m>15000) b5
      FROM read_parquet('{D}/platform/trips.parquet') WHERE {where}""").fetchone()
    return r
scopes = {}
for sc in ['budapest','suburb_bp','suburb_local']:
    scopes[sc] = bands(f"trip_scope='{sc}'")
summary = {"total": bands(), "scopes": scopes}
json.dump(summary, open(f"{D}/platform/summary.json","w"), indent=1)
print("summary.json:", json.dumps({k:(v[0] if isinstance(v,tuple) else v) for k,v in summary.items()})[:200])
