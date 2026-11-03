"""Is 4,029 routes crossing a 1.7 ha box anomalous, or normal for an inner-city box that size?

Method: slide the SAME-SIZED box across Budapest on a grid, count how many routes cross each
placement, and see where the user's box sits in that distribution. If the user's box is a normal
hub, the distribution will be broad and 4,029 unremarkable. If the app were buggy (counting routes
that do NOT cross), the user's box would be a lone spike far above every control.
"""
import duckdb, numpy as np, pandas as pd, json

P = "platform"
UL0, UL1 = 19.051302298868734, 19.0532637      # the user's box
UA0, UA1 = 47.505209626879974, 47.5062439
W, H = UL1 - UL0, UA1 - UA0

c = duckdb.connect(); c.execute("PRAGMA threads=8")
g = c.execute(f"SELECT xy FROM read_parquet('{P}/routed_geom.parquet')").df()
geoms = [np.asarray(xy, dtype=float).reshape(-1, 2) for xy in g.xy.values]
print(f"routes: {len(geoms):,}")

# pre-compute each route's bounding box for a cheap first filter
bnd = np.array([[a[:, 0].min(), a[:, 1].min(), a[:, 0].max(), a[:, 1].max()] for a in geoms])


def crosses(lo0, la0, lo1, la1):
    """Count routes whose polyline crosses the rectangle (proper segment test)."""
    cand = np.nonzero((bnd[:, 0] <= lo1) & (bnd[:, 2] >= lo0) &
                      (bnd[:, 1] <= la1) & (bnd[:, 3] >= la0))[0]
    n = 0
    for k in cand:
        a = geoms[k]
        dx, dy = np.diff(a[:, 0]), np.diff(a[:, 1])
        # skip segments fully outside on either axis
        keep = ~(((a[:-1, 0] < lo0) & (a[1:, 0] < lo0)) | ((a[:-1, 0] > lo1) & (a[1:, 0] > lo1)) |
                 ((a[:-1, 1] < la0) & (a[1:, 1] < la0)) | ((a[:-1, 1] > la1) & (a[1:, 1] > la1)))
        for j in np.nonzero(keep)[0]:
            p, q = a[j], a[j + 1]
            ddx, ddy = q[0] - p[0], q[1] - p[1]
            t0, t1 = 0.0, 1.0
            hit = True
            for num, den in ((p[0] - lo0, -ddx), (lo1 - p[0], ddx), (p[1] - la0, -ddy), (la1 - p[1], ddy)):
                if den == 0:
                    if num < 0: hit = False; break
                else:
                    t = num / den
                    if den < 0:
                        if t > t1: hit = False; break
                        if t > t0: t0 = t
                    else:
                        if t < t0: hit = False; break
                        if t < t1: t1 = t
            if hit: n += 1; break
    return n


user_n = crosses(UL0, UA0, UL1, UA1)
print(f"\nUSER BOX  {user_n:,} routes cross it")
print()

# --- controls: named landmarks + a random sample of placements ---
land = {
    "Kálvin tér (user's box)": (UL0, UA0),
    "Deák tér": (19.0540, 47.4970),
    "Blaha Lujza tér": (19.0700, 47.4960),
    "Oktogon": (19.0620, 47.5050),
    "Széll Kálmán tér": (19.0250, 47.5070),
    "Margit híd budai hídfő": (19.0380, 47.5140),
    "Keleti pályaudvar": (19.0850, 47.5000),
    "a random Buda residential block": (19.0100, 47.4900),
}
print(f"{'placement':<34}{'routes crossing':>16}")
for name, (lo, la) in land.items():
    print(f"{name:<34}{crosses(lo, la, lo + W, la + H):>16,}")
print()

rng = np.random.default_rng(1)
samp = []
for _ in range(60):
    lo = rng.uniform(18.95, 19.25)
    la = rng.uniform(47.40, 47.58)
    samp.append(crosses(lo, la, lo + W, la + H))
samp = np.array(samp)
print(f"60 random same-size boxes across Budapest:")
print(f"  min {samp.min():,}  median {int(np.median(samp)):,}  p90 {int(np.quantile(samp,.9)):,}  max {samp.max():,}")
print(f"  user's box {user_n:,} -> percentile among random placements: "
      f"{100*(samp < user_n).mean():.0f}%")
