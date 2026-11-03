import duckdb, os
D = ("/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/"
     "Transport analysis")
os.chdir(D)
c = duckdb.connect("db/osm.duckdb", read_only=True)
c.execute("INSTALL spatial; LOAD spatial;")
print("=== bike_ways ===")
print(c.execute("SELECT infra, allowed, count(*) ways, round(avg(speed),1) spd FROM bike_ways GROUP BY 1,2 ORDER BY 3 DESC").df().to_string(index=False))
print("\n=== my ROAD network by cycling provision (km) ===")
print(c.execute("""
  SELECT coalesce(b.infra,'NOT IN bike_ways') AS infra, count(*) ways,
         round(sum(ST_Length(ST_Transform(ST_SetCRS(n.geom,'OGC:CRS84'),'EPSG:23700')))/1000) km
  FROM net2 n LEFT JOIN bike_ways b USING (way_id) WHERE n.kind='road'
  GROUP BY 1 ORDER BY km DESC
""").df().to_string(index=False))
print("\n=== allowed to ride? (km) ===")
print(c.execute("""
  SELECT coalesce(b.allowed,TRUE) allowed, count(*) ways,
         round(sum(ST_Length(ST_Transform(ST_SetCRS(n.geom,'OGC:CRS84'),'EPSG:23700')))/1000) km
  FROM net2 n LEFT JOIN bike_ways b USING (way_id) WHERE n.kind='road' GROUP BY 1
""").df().to_string(index=False))
print("\n=== net2 road classes ===")
print(c.execute("SELECT cls, count(*) ways FROM net2 WHERE kind='road' GROUP BY 1 ORDER BY 2 DESC").df().to_string(index=False))
