import duckdb
D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
con = duckdb.connect()
con.execute("INSTALL spatial; LOAD spatial;")
src = f"{D}/data/osm/net.ndjson"
print("duckdb", duckdb.__version__)

print("\n-- 1. auto --")
try:
    print(con.execute(f"SELECT count(*) FROM read_json('{src}')").fetchone())
except Exception as e:
    print("ERR", str(e)[:200])

print("\n-- 2. newline_delimited + columns --")
try:
    r = con.execute(f"""SELECT count(*) n FROM read_json('{src}', format='newline_delimited',
        columns={{'type':'VARCHAR','id':'VARCHAR','geometry':'JSON','properties':'JSON'}})""").fetchone()
    print("count:", r)
except Exception as e:
    print("ERR", str(e)[:300])

print("\n-- 3. types present --")
try:
    print(con.execute(f"""SELECT "type" t, count(*) n FROM read_json('{src}', format='newline_delimited',
        columns={{'type':'VARCHAR','id':'VARCHAR','geometry':'JSON','properties':'JSON'}}) GROUP BY 1""").df().to_string())
except Exception as e:
    print("ERR", str(e)[:300])

print("\n-- 4. raw first line as a string table --")
try:
    print(con.execute(f"SELECT count(*) FROM read_csv('{src}', header=false, quote='', columns={{'line':'VARCHAR'}}, delim='\\x01')").fetchone())
    print(con.execute(f"SELECT substr(line,1,90) FROM read_csv('{src}', header=false, quote='', columns={{'line':'VARCHAR'}}, delim='\\x01') LIMIT 1").fetchone())
except Exception as e:
    print("ERR", str(e)[:300])

print("\n-- 5. from_json on a raw line --")
try:
    print(con.execute(f"""SELECT from_json(substr(line,1,400), '{{"type":"VARCHAR","geometry":"JSON"}}')->>'type' AS t
        FROM read_csv('{src}', header=false, quote='', columns={{'line':'VARCHAR'}}, delim='\\x01') LIMIT 3""").df().to_string())
except Exception as e:
    print("ERR", str(e)[:300])
