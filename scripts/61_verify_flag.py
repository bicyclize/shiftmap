import duckdb
c = duckdb.connect()
print(c.execute("""
  SELECT on_rail, count(*) trips FROM read_parquet('platform/route_len.parquet') GROUP BY 1 ORDER BY 1
""").fetchall())
print(c.execute("""
  SELECT kind, count(*) edges, round(sum(len_m)/1000) km FROM read_parquet('platform/routed_edges.parquet')
  GROUP BY 1 ORDER BY 1
""").fetchall())
# do the rail-classified trips that fell back stay road (on_rail false)?
print(c.execute("""
  WITH m AS (SELECT i, mode FROM read_parquet('platform/rail_mode.parquet')),
       l AS (SELECT i, on_rail FROM read_parquet('platform/route_len.parquet'))
  SELECT m.mode, l.on_rail, count(*) FROM m JOIN l USING (i) GROUP BY 1,2 ORDER BY 1,2
""").fetchall())
