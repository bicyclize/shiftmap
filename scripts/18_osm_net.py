"""Load OSM highways + railways (geojsonseq) into DuckDB and save as a compact parquet."""
import duckdb, os, time

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
con = duckdb.connect(f"{D}/db/osm.duckdb")
con.execute("PRAGMA threads=8"); con.execute("INSTALL spatial; LOAD spatial;")

src = f"{D}/data/osm/net.ndjson"
print("ndjson size MB:", round(os.path.getsize(src)/1e6, 1))
t0 = time.time()

con.execute(f"""
CREATE OR REPLACE TABLE net AS
SELECT
  id AS way_id,
  ST_GeomFromGeoJSON(geometry::VARCHAR) AS geom,
  CASE WHEN properties->>'railway' IS NOT NULL THEN 'rail' ELSE 'road' END AS kind,
  COALESCE(properties->>'highway', properties->>'railway', '') AS cls
FROM read_json('{src}', format='newline_delimited',
               columns={{'type':'VARCHAR','id':'VARCHAR','geometry':'JSON','properties':'JSON'}})
WHERE geometry->>'type' = 'LineString'
""")
print(f"loaded ({time.time()-t0:.1f}s)")

print(con.execute("SELECT kind, count(*) ways FROM net GROUP BY 1").df().to_string())
print("\ntop road classes:")
print(con.execute("""SELECT cls, count(*) n FROM net WHERE kind='road' GROUP BY 1 ORDER BY n DESC LIMIT 12""").df().to_string())
print("\nrail classes:")
print(con.execute("""SELECT cls, count(*) n FROM net WHERE kind='rail' GROUP BY 1 ORDER BY n DESC LIMIT 8""").df().to_string())

# keep only drivable/walkable roads + real rail (drop footways/paths that would mis-snap cars)
con.execute("""
CREATE OR REPLACE TABLE net2 AS
SELECT * FROM net
WHERE (kind='road' AND cls IN ('motorway','trunk','primary','secondary','tertiary','unclassified',
       'residential','motorway_link','trunk_link','primary_link','secondary_link','tertiary_link',
       'living_street','service','road'))
   OR (kind='rail' AND cls IN ('rail','light_rail','subway','tram','narrow_gauge'))
""")
print("\nkept:", con.execute("SELECT kind, count(*) FROM net2 GROUP BY 1").df().to_string())

con.execute(f"COPY net2 TO '{D}/data/osm/net.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)")
print("net.parquet MB:", round(os.path.getsize(f'{D}/data/osm/net.parquet')/1e6, 1))
