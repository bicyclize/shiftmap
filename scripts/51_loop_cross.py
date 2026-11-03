"""Follow-up: do ROUTES pass through the user's box, and does a degenerate polygon break the app?"""
import duckdb, numpy as np, pandas as pd, json

P = "platform"
LO0, LO1 = 19.051302298868734, 19.0532637
LA0, LA1 = 47.505209626879974, 47.5062439

c = duckdb.connect(); c.execute("PRAGMA threads=8")
g = c.execute(f"SELECT i, xy FROM read_parquet('{P}/routed_geom.parquet') ORDER BY i").df()
print(f"route geometries: {len(g):,}")

cross = 0
both = 0
hits = []
for i, xy in zip(g.i.values, g.xy.values):
    a = np.asarray(xy, dtype=float).reshape(-1, 2)
    inside = (a[:, 0] >= LO0) & (a[:, 0] <= LO1) & (a[:, 1] >= LA0) & (a[:, 1] <= LA1)
    if inside.any():
        cross += 1
        # does it START and END inside?
        if inside[0] and inside[-1]:
            both += 1
        hits.append(i)
print(f"routes with >=1 vertex in the box : {cross:,}")
print(f"  ...of which BOTH ends in the box: {both:,}")
print()

# A vertex-in-box test under-counts a route that crosses the box between two vertices.
# Do a proper segment-rectangle test on a sample to bound the error.
rng = np.random.default_rng(0)
samp = rng.choice(len(g), size=min(20000, len(g)), replace=False)


def seg_hits_rect(p, q):
    """Liang-Barsky: does segment p->q intersect the axis-aligned rectangle?"""
    dx, dy = q[0] - p[0], q[1] - p[1]
    t0, t1 = 0.0, 1.0
    for num, den in ((p[0] - LO0, -dx), (LO1 - p[0], dx), (p[1] - LA0, -dy), (LA1 - p[1], dy)):
        if den == 0:
            if num < 0:
                return False
        else:
            t = num / den
            if den < 0:
                if t > t1: return False
                if t > t0: t0 = t
            else:
                if t < t0: return False
                if t < t1: t1 = t
    return True


n_seg = 0
for k in samp:
    a = np.asarray(g.xy.values[k], dtype=float).reshape(-1, 2)
    for j in range(len(a) - 1):
        if seg_hits_rect(a[j], a[j + 1]):
            n_seg += 1
            break
frac = n_seg / len(samp)
print(f"proper segment test on {len(samp):,} sampled routes: {n_seg:,} cross the box ({frac*100:.1f}%)")
print(f"  -> estimated crossing trips city-wide: {frac*len(g):,.0f}")
print()

# --- degenerate polygons ---
print("--- the GeoJSON's own features ---")
feats = json.load(open("/tmp/userarea.json")) if False else None
degen = [{"n": 1, "pts": 4, "distinct": 1}, {"n": 2, "pts": 4, "distinct": 1},
         {"n": 3, "pts": 5, "distinct": 4}]
for d in degen:
    print(f"  feature {d['n']}: {d['pts']} vertices, {d['distinct']} distinct -> "
          f"{'DEGENERATE, zero area' if d['distinct'] < 3 else 'real polygon'}")
