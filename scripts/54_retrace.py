"""How much of a route is retraced? A genuine 'loop' retraces a large share of its own length.

For each route: walk the polyline, mark vertices that come within 12 m of an earlier
non-adjacent vertex, and sum the length of those retraced legs. A U-turn or a
'go around the block to escape a banned turn' shows up as a big retraced share.
"""
import duckdb, numpy as np

P = "platform"
LO0, LO1 = 19.051302298868734, 19.0532637
LA0, LA1 = 47.505209626879974, 47.5062439
M_LON = 111320 * np.cos(np.radians(47.5057)); M_LAT = 110574.0

c = duckdb.connect(); c.execute("PRAGMA threads=8")
g = c.execute(f"SELECT i, xy FROM read_parquet('{P}/routed_geom.parquet') ORDER BY i").df()


def crossing(a):
    return bool(((a[:, 0] >= LO0) & (a[:, 0] <= LO1) & (a[:, 1] >= LA0) & (a[:, 1] <= LA1)).any())


def retrace(a):
    """returns (retraced_m, total_m)"""
    x = (a[:, 0] - a[:, 0].mean()) * M_LON
    y = (a[:, 1] - a[:, 1].mean()) * M_LAT
    n = len(x)
    tot = float(np.hypot(np.diff(x), np.diff(y)).sum())
    ret = 0.0
    for j in range(2, n):
        d = np.hypot(x[:j - 1] - x[j], y[:j - 1] - y[j])
        if d.min() < 12:
            ret += float(np.hypot(x[j] - x[j - 1], y[j] - y[j - 1]))
    return ret, tot


cross, allr = [], []
for k in range(len(g)):
    a = np.asarray(g.xy.values[k], dtype=float).reshape(-1, 2)
    if crossing(a):
        r, t = retrace(a)
        cross.append(r / t if t > 0 else 0)
rng = np.random.default_rng(2)
for k in rng.choice(len(g), 15000, replace=False):
    a = np.asarray(g.xy.values[k], dtype=float).reshape(-1, 2)
    r, t = retrace(a)
    allr.append(r / t if t > 0 else 0)

cross = np.array(cross); allr = np.array(allr)
for nm, v in (("crossing the box", cross), ("city-wide sample", allr)):
    print(f"{nm:20s} n={len(v):6,}  median retraced {np.median(v)*100:4.1f}%  "
          f">20% retraced: {(v>0.20).mean()*100:4.1f}%  >40%: {(v>0.40).mean()*100:4.1f}%")
print()

# worst offenders among crossing routes
order = np.argsort(-cross)
print("worst 6 crossing routes by retraced share:")
shown = 0
for k in range(len(g)):
    a = np.asarray(g.xy.values[k], dtype=float).reshape(-1, 2)
    if not crossing(a):
        continue
    r, t = retrace(a)
    if t <= 0 or r / t < 0.55:
        continue
    print(f"  trip {g.i.values[k]:7d}  pts {len(a):3d}  len {t/1000:5.2f} km  retraced {r/t*100:4.0f}%")
    # print the retraced spine: first, closest-pair, last
    x = (a[:, 0] - a[:, 0].mean()) * M_LON; y = (a[:, 1] - a[:, 1].mean()) * M_LAT
    for j in range(2, len(x)):
        d = np.hypot(x[:j - 1] - x[j], y[:j - 1] - y[j])
        if d.min() < 12:
            m = int(np.argmin(d))
            print(f"      vertex {j:3d} revisits vertex {m:3d}  ({d.min():.0f} m apart, "
                  f"{j-m} steps apart)")
            break
    shown += 1
    if shown >= 6:
        break
