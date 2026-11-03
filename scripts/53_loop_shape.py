"""Is there an actual LOOP in the routes crossing the user's box?

'Loop' could mean two different things, so test both:
  A. a closed circuit of trips (many trips forming a ring)  -> checked in 52, it's just a corridor
  B. a single ROUTE that doubles back on itself, i.e. passes through the same place twice
     -> that WOULD be a routing fault, and matches the earlier 'illegal left turn' complaint

Test B on the routes crossing the box, and on the city as a whole for comparison.
"""
import duckdb, numpy as np

P = "platform"
LO0, LO1 = 19.051302298868734, 19.0532637
LA0, LA1 = 47.505209626879974, 47.5062439

c = duckdb.connect(); c.execute("PRAGMA threads=8")
g = c.execute(f"SELECT i, xy FROM read_parquet('{P}/routed_geom.parquet') ORDER BY i").df()

M_LON = 111320 * np.cos(np.radians(47.5057))
M_LAT = 110574.0


def crossing(k):
    a = np.asarray(g.xy.values[k], dtype=float).reshape(-1, 2)
    inside = (a[:, 0] >= LO0) & (a[:, 0] <= LO1) & (a[:, 1] >= LA0) & (a[:, 1] <= LA1)
    return a, inside.any()


def self_intersects(a):
    """does the polyline pass within 12 m of a NON-adjacent earlier vertex?"""
    x = (a[:, 0] - a[:, 0].mean()) * M_LON
    y = (a[:, 1] - a[:, 1].mean()) * M_LAT
    n = len(x)
    if n < 5:
        return False
    for j in range(2, n):
        dx = x[:j - 1] - x[j]
        dy = y[:j - 1] - y[j]
        if (dx * dx + dy * dy).min() < 12 * 12:
            return True
    return False


# --- B on the crossing routes ---
cross_idx = [k for k in range(len(g)) if crossing(k)[1]]
print(f"routes crossing the box: {len(cross_idx):,}")
loops = sum(1 for k in cross_idx if self_intersects(
    np.asarray(g.xy.values[k], dtype=float).reshape(-1, 2)))
print(f"  ...that double back on themselves: {loops:,}  ({loops/max(1,len(cross_idx))*100:.1f}%)")
print()

# --- B city-wide (sample) ---
rng = np.random.default_rng(2)
samp = rng.choice(len(g), size=15000, replace=False)
n_loop = sum(1 for k in samp if self_intersects(
    np.asarray(g.xy.values[k], dtype=float).reshape(-1, 2)))
print(f"city-wide sample of 15,000 routes:")
print(f"  ...that double back on themselves: {n_loop:,}  ({n_loop/len(samp)*100:.1f}%)")
print()

# --- A: is the crossing set a ring, or just a corridor? ---
# If it were a 'loop', the routes would fan out in all directions. Measure the bearing
# distribution of the crossing routes at the box: a corridor = bimodal (two opposite headings).
bear = []
for k in cross_idx[:4000]:
    a = np.asarray(g.xy.values[k], dtype=float).reshape(-1, 2)
    inside = (a[:, 0] >= LO0) & (a[:, 0] <= LO1) & (a[:, 1] >= LA0) & (a[:, 1] <= LA1)
    j = np.nonzero(inside)[0]
    if len(j) < 2:
        continue
    p, q = a[j[0]], a[j[-1]]
    dx = (q[0] - p[0]) * M_LON
    dy = (q[1] - p[1]) * M_LAT
    if abs(dx) + abs(dy) < 1:
        continue
    bear.append(np.degrees(np.arctan2(dy, dx)) % 180)   # axis, not direction
bear = np.array(bear)
print(f"axis of travel through the box ({len(bear):,} routes, 0-180 deg):")
hist, edges = np.histogram(bear, bins=12, range=(0, 180))
for h, e0, e1 in zip(hist, edges[:-1], edges[1:]):
    print(f"  {e0:5.0f}-{e1:3.0f} deg  {h:5,}  {'#'*int(h/max(hist)*40)}")
print()
top = np.argmax(hist)
print(f"  peak axis {edges[top]:.0f}-{edges[top+1]:.0f} deg holds {hist[top]:,} of {len(bear):,} "
      f"({hist[top]/len(bear)*100:.0f}%)")
