"""District-coverage check: is the device panel geographically representative of Budapest?

Method: give every device a "home district" = the district containing most of its trip origins
across the week (a home-location proxy), then compare devices per district against the 2022 census
population of that district. If devices/1000-residents is flat across districts, the panel is
spatially unbiased and the map results are defensible; a strong gradient means they are not.

Sources: district boundaries = OSM admin_level=9 (23 kerületek); population = 2022 census.
"""
import duckdb, json, re, os

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
SC = "/Users/peterbiczok/.hermes/cache/scratch"
DIST = json.load(open(f"{SC}/buda_districts.json"))
POP = json.load(open(f"{SC}/ker_pop.json"))          # {'I': 23685, ...}

def wkt_of(rings):
    parts = []
    for r in rings:
        r = list(r)
        if r[0] != r[-1]: r.append(r[0])
        parts.append("((" + ",".join(f"{p[0]:.6f} {p[1]:.6f}" for p in r) + "))")
    return "MULTIPOLYGON(" + ",".join(parts) + ")"

rows = []
for x in DIST:
    if x.get("level") != "9": continue
    m = re.match(r"^([IVXL]+)\.", x["name"].strip())
    if not m: continue
    rows.append((m.group(1), x["name"].strip(), wkt_of(x["rings"])))
print(f"districts with geometry: {len(rows)}  (populations known: {len(POP)})")

con = duckdb.connect(f"{D}/db/osm.duckdb")
con.execute("INSTALL spatial; LOAD spatial; PRAGMA threads=8")
con.execute("CREATE OR REPLACE TEMP TABLE ker(ker VARCHAR, name VARCHAR, g GEOMETRY)")
for k, nm, w in rows:
    con.execute("INSERT INTO ker VALUES (?, ?, ST_SetCRS(ST_GeomFromText(?), 'OGC:CRS84'))", [k, nm, w])

days = [f"day_{d:02d}" for d in range(8, 15)]
con.execute("CREATE OR REPLACE TEMP TABLE dev_pt AS " + " UNION ALL ".join(
    f"SELECT aid, ST_SetCRS(ST_Point(o_lon, o_lat), 'OGC:CRS84') AS p FROM {t}" for t in days))
npt = con.execute("SELECT count(*) FROM dev_pt").fetchone()[0]
print(f"trip origins: {npt:,}")

con.execute("""CREATE OR REPLACE TEMP TABLE dev_dist AS
  SELECT d.aid, k.ker, count(*) AS n
  FROM dev_pt d JOIN ker k ON ST_Contains(k.g, d.p)
  GROUP BY 1, 2""")
con.execute("""CREATE OR REPLACE TEMP TABLE dev_home AS
  SELECT aid, arg_max(ker, n) AS ker FROM dev_dist GROUP BY aid""")

res = con.execute("SELECT ker, count(*) dev FROM dev_home GROUP BY 1").fetchall()
home = {k: v for k, v in res}
tot_dev = sum(home.values())
all_dev = con.execute("SELECT count(DISTINCT aid) FROM dev_pt").fetchone()[0]
print(f"devices assigned a home district: {tot_dev:,} of {all_dev:,} "
      f"({100*tot_dev/all_dev:.1f}% — the rest never start a trip inside a district)")

print(f"\n=== devices per district vs 2022 census population ===")
print(f"{'ker':5s}{'devices':>9s}{'population':>12s}{'dev/1000':>10s}{'index':>8s}")
rowsout = []
for k in sorted(POP, key=lambda s: [c for c in range(23) if ['I','II','III','IV','V','VI','VII','VIII','IX','X','XI','XII','XIII','XIV','XV','XVI','XVII','XVIII','XIX','XX','XXI','XXII','XXIII'][c] == s]):
    pass
ORDER = ['I','II','III','IV','V','VI','VII','VIII','IX','X','XI','XII','XIII','XIV','XV','XVI','XVII','XVIII','XIX','XX','XXI','XXII','XXIII']
tot_pop = sum(POP.values())
for k in ORDER:
    if k not in POP: continue
    dev = home.get(k, 0); pop = POP[k]
    per1000 = 1000.0 * dev / pop
    rowsout.append((k, dev, pop, per1000))
grand = 1000.0 * tot_dev / tot_pop
for k, dev, pop, per1000 in rowsout:
    print(f"{k:5s}{dev:>9,}{pop:>12,}{per1000:>10.2f}{per1000/grand:>8.2f}")
print(f"{'ALL':5s}{tot_dev:>9,}{tot_pop:>12,}{grand:>10.2f}{1.0:>8.2f}")

vals = sorted(rowsout, key=lambda r: r[3])
print(f"\nspread: min {vals[0][0]} {vals[0][3]:.2f}/1000  |  max {vals[-1][0]} {vals[-1][3]:.2f}/1000"
      f"   ratio {vals[-1][3]/max(vals[0][3],1e-9):.2f}x")

con.execute("DROP TABLE IF EXISTS dev_dist"); con.execute("DROP TABLE IF EXISTS dev_home")
print("\nunder-sampled districts (<60% of the city-wide rate):",
      ", ".join(f"{k} ({v:.2f})" for k, _, _, v in vals if v < 0.6 * grand) or "none")
print("over-sampled districts (>160% of the city-wide rate):",
      ", ".join(f"{k} ({v:.2f})" for k, _, _, v in vals if v > 1.6 * grand) or "none")
