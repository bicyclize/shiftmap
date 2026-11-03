"""How big would routed geometry for ALL 438,995 trips be, at various simplifications?

Measured on the existing 9,631-route sample, then extrapolated. Decides whether the browser can
hold a calculated route for every trip, or must work on a sample.
"""
import duckdb, numpy as np, math

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
MLAT, MLON = 110574.0, 111320.0 * math.cos(math.radians(47.5))
TOTAL = 438995

c = duckdb.connect()
rows = c.execute(f"SELECT i, xy FROM '{D}/platform/routed_sample.parquet'").fetchall()
print(f"sample routes: {len(rows):,}")

def dp(x, y, tol):
    """Douglas-Peucker, iterative."""
    n = len(x)
    if n < 3:
        return n
    keep = np.zeros(n, dtype=bool); keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    t2 = tol * tol
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        ax, ay, bx, by = x[a], y[a], x[b], y[b]
        dx, dy = bx - ax, by - ay
        l2 = dx*dx + dy*dy
        seg = slice(a + 1, b)
        if l2 == 0:
            d2 = (x[seg]-ax)**2 + (y[seg]-ay)**2
        else:
            t = np.clip(((x[seg]-ax)*dx + (y[seg]-ay)*dy)/l2, 0, 1)
            d2 = (x[seg] - (ax + t*dx))**2 + (y[seg] - (ay + t*dy))**2
        k = np.argmax(d2)
        if d2[k] > t2:
            m = a + 1 + k
            keep[m] = True
            stack.append((a, m)); stack.append((m, b))
    return int(keep.sum())

pts = []
for i, xy in rows:
    if xy and len(xy) >= 4:
        pts.append(len(xy)//2)
pts = np.array(pts)
print(f"points per route: median {int(np.median(pts))}, mean {pts.mean():.0f}, p90 {int(np.percentile(pts,90))}, max {pts.max()}")
print(f"total points in sample: {pts.sum():,}")
print(f"\nfull geometry for all {TOTAL:,} trips: "
      f"{TOTAL * pts.mean() * 8 / 1e6:.0f} MB uncompressed (float32 lon/lat)")

print("\n--- after Douglas-Peucker simplification ---")
print(f"{'tol':>5} {'median pts':>11} {'total pts':>11} {'ALL trips MB':>13} {'~ZSTD MB':>9}")
for tol in (10, 20, 30, 50, 75, 100, 150):
    tot = 0; ns = []
    for i, xy in rows[:3000]:
        if not xy or len(xy) < 4:
            continue
        arr = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
        x = arr[:, 0] * MLON; y = arr[:, 1] * MLAT
        k = dp(x, y, tol)
        tot += k; ns.append(k)
    med = int(np.median(ns)); mean = tot / max(len(ns), 1)
    mb = TOTAL * mean * 8 / 1e6
    print(f"{tol:>5} {med:>11} {mean:>11.0f} {mb:>13.0f} {mb*0.45:>9.0f}")
print("\n(ZSTD factor ~0.45 measured on the existing sample file)")
