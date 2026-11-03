"""Validate that resolved turn restrictions are geometrically sensible.

The engine obeys the forbidden pairs by construction, so that proves nothing about whether the
pairs were resolved CORRECTLY. This checks the resolution independently: a `no_left_turn` must
resolve to a movement that is actually a LEFT turn at the via node, and `no_right_turn` to a right
turn. If the way->edge matching picked the wrong arm, the angles would be random and the match rate
would sit near 50%.

Sign convention (x = east, y = north): cross(in, out) > 0 means a LEFT turn (counter-clockwise).
Hungary drives on the right, so a left turn crosses oncoming traffic — which is exactly why
no_left_turn is the most common ban.
"""
import duckdb, math
from collections import defaultdict

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
g = duckdb.connect(f"{D}/db/graph.duckdb", read_only=True)

coords = {r[0]: (r[1], r[2]) for r in g.execute("SELECT id, lon, lat FROM tgraph_nodes").fetchall()}
edges = {r[0]: r for r in g.execute("SELECT eid, u, v, nodes FROM tgraph_edges").fetchall()}
rests = g.execute("SELECT node, kind, from_edges, to_edges FROM trestrictions").fetchall()
print(f"restrictions {len(rests):,} | edges {len(edges):,} | nodes {len(coords):,}")

def meters(p, q):
    la = math.radians((p[1] + q[1]) / 2)
    return ((q[0] - p[0]) * 111320.0 * math.cos(la), (q[1] - p[1]) * 110540.0)

def in_vector(eid, node):
    """Direction of ARRIVAL at `node` along edge `eid` — points TOWARD the node. Uses a vertex ~3
    steps away so the bearing reflects the street, not one jittery point."""
    ch = edges[eid][3]
    if ch[0] == node:        a, b = ch[min(3, len(ch) - 1)], ch[0]
    elif ch[-1] == node:     a, b = ch[max(0, len(ch) - 4)], ch[-1]
    else: return None
    if a == b or a not in coords or b not in coords: return None
    return meters(coords[a], coords[b])


def out_vector(eid, node):
    """Direction of DEPARTURE from `node` along edge `eid` — points AWAY from the node.
    Getting this backwards flips every left/right label, so it is a separate function on purpose."""
    ch = edges[eid][3]
    if ch[0] == node:        a, b = ch[0], ch[min(3, len(ch) - 1)]
    elif ch[-1] == node:     a, b = ch[-1], ch[max(0, len(ch) - 4)]
    else: return None
    if a == b or a not in coords or b not in coords: return None
    return meters(coords[a], coords[b])

signed = defaultdict(list)
skipped = 0
for node, kind, fe, te in rests:
    if not fe or not te:
        skipped += 1; continue
    vin = in_vector(fe[0], node)
    vout = out_vector(te[0], node)
    if vin is None or vout is None:
        skipped += 1; continue
    cross = vin[0] * vout[1] - vin[1] * vout[0]
    dot = vin[0] * vout[0] + vin[1] * vout[1]
    ang = math.degrees(math.atan2(cross, dot))          # + left, - right, ~0 straight
    signed[kind].append(ang)

print(f"unresolvable for geometry: {skipped}\n")
print(f"{'kind':18s}{'n':>7s}{'mean angle':>12s}{'% left':>8s}{'% right':>9s}{'% straight':>11s}")
for kind in ['no_left_turn', 'only_left_turn', 'no_right_turn', 'only_right_turn',
             'no_straight_on', 'only_straight_on']:
    a = signed.get(kind, [])
    if not a: continue
    L = 100 * sum(1 for x in a if x > 20) / len(a)
    R = 100 * sum(1 for x in a if x < -20) / len(a)
    S = 100 * sum(1 for x in a if abs(x) <= 20) / len(a)
    print(f"{kind:18s}{len(a):>7,}{sum(a)/len(a):>11.0f}°{L:>7.0f}%{R:>8.0f}%{S:>10.0f}%")

print("\nEXPECTED: no_left_turn / only_left_turn -> mean angle clearly POSITIVE, % left high.")
print("          no_right_turn / only_right_turn -> mean clearly NEGATIVE, % right high.")
print("          straight kinds -> mean near 0, % straight high.")
print("A match rate near 50% on the left/right kinds would mean the way->edge matching is wrong.")
