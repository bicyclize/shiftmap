"""Probe the reported "loop" of 3,943 trips in the user's GeoJSON area.

The GeoJSON's first two "polygons" are degenerate (4 identical vertices, zero area), so only the
third is a real shape. That rectangle is ~147 m x 115 m = 1.7 ha, about two city blocks.

Questions:
  1. How many trips START / END / have BOTH ends in that box?
  2. How many trip ROUTES pass through it?
  3. Are the in-box trips LOOPS (start ~ end), and is that unusual vs the city as a whole?
  4. Do they cluster on one device/time?  (No device id in this table — check time-of-day instead.)
"""
import duckdb, numpy as np, pandas as pd

P = "platform"
c = duckdb.connect()
c.execute("PRAGMA threads=8")

# --- the real rectangle (feature 3) ---
LO0, LO1 = 19.051302298868734, 19.0532637
LA0, LA1 = 47.505209626879974, 47.5062439
print(f"box: lon {LO0:.6f}..{LO1:.6f}  lat {LA0:.6f}..{LA1:.6f}")
print(f"     {(LO1-LO0)*111320*np.cos(np.radians(47.5057)):.0f} m x {(LA1-LA0)*110574:.0f} m"
      f"  = {(LO1-LO0)*111320*np.cos(np.radians(47.5057))*(LA1-LA0)*110574/10000:.2f} ha")
print()

df = c.execute(f"""
  SELECT row_number() OVER () - 1 AS i, o_lat, o_lon, d_lat, d_lon, path_m, od_m, day_tag, t_start,
         trip_scope, rail_lvl
  FROM read_parquet('{P}/trips_attrs.parquet')
""").df()
print(f"trips total: {len(df):,}")

in_o = (df.o_lon.between(LO0, LO1)) & (df.o_lat.between(LA0, LA1))
in_d = (df.d_lon.between(LO0, LO1)) & (df.d_lat.between(LA0, LA1))
in_both = in_o & in_d

print(f"  origin in box      : {in_o.sum():,}")
print(f"  destination in box : {in_d.sum():,}")
print(f"  BOTH ends in box   : {in_both.sum():,}")
print(f"  either end in box  : {(in_o | in_d).sum():,}")
print()

# --- how does that compare to a box of the same size elsewhere? (grid sample of the city) ---
# crude but decisive: count how many 147x115 m cells across Budapest hold >= 3,943 origins
wlon = LO1 - LO0
wlat = LA1 - LA0
lo_min, lo_max = 18.90, 19.28
la_min, la_max = 47.38, 47.61
nx = int((lo_max - lo_min) / wlon) + 1
ny = int((la_max - la_min) / wlat) + 1
print(f"reference grid over Budapest: {nx} x {ny} = {nx*ny:,} cells of the same size")
gx = ((df.o_lon - lo_min) // wlon).astype("Int64")
gy = ((df.o_lat - la_min) // wlat).astype("Int64")
ok = gx.between(0, nx) & gy.between(0, ny)
cnt = pd.DataFrame({"gx": gx[ok], "gy": gy[ok]}).value_counts()
print(f"  cells with >= 3,943 origins: {(cnt >= 3943).sum()}")
print(f"  cells with >= 1,000 origins: {(cnt >= 1000).sum()}")
print(f"  max origins in any cell    : {cnt.max():,}")
print(f"  the user's cell            : {in_o.sum():,}")
print(f"  median non-empty cell      : {int(cnt.median()):,}")
print()

# --- are the in-box trips LOOPS? ---
sub = df[in_both | in_o | in_d]
d = sub[in_both]
print(f"--- the {in_both.sum():,} trips with BOTH ends in the box ---")
if len(d):
    print(f"  od_m  median {d.od_m.median():.0f} m   p90 {d.od_m.quantile(.9):.0f} m   max {d.od_m.max():.0f} m")
    print(f"  path_m median {d.path_m.median():.0f} m  max {d.path_m.max():.0f} m")
    print(f"  od_m < 200 m : {(d.od_m < 200).sum():,}  ({(d.od_m<200).mean()*100:.0f}%)")
    print(f"  od_m < 100 m : {(d.od_m < 100).sum():,}  ({(d.od_m<100).mean()*100:.0f}%)")
print()
print(f"--- ALL {len(df):,} trips, for comparison ---")
print(f"  od_m < 100 m : {(df.od_m < 100).sum():,}  ({(df.od_m<100).mean()*100:.1f}%)")
print(f"  od_m < 200 m : {(df.od_m < 200).sum():,}  ({(df.od_m<200).mean()*100:.1f}%)")
print()

# --- day split of in-box trips ---
print("--- day split (origin in box) ---")
print(df[in_o].day_tag.value_counts().sort_index().to_string())
print()
print("--- hour of day (origin in box), t_start is unix seconds ---")
h = pd.to_datetime(df[in_o].t_start, unit="s", utc=True).dt.tz_convert("Europe/Budapest").dt.hour
print(h.value_counts().sort_index().to_string())
