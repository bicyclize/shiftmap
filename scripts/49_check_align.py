"""Is the per-edge volume attached to the RIGHT geometry?

40_route_turns.prep() drops everything outside the largest connected component, which leaves GAPS in
the original edge ids. The engine then indexes edges POSITIONALLY (0..E-1). But the output join is
`edge_geo.eid = df_cnt.eid` where edge_geo carries ORIGINAL ids and df_cnt carries POSITIONS — so if
any dropped id is below the highest position, counts get attached to the wrong edge's geometry.

This checks whether that misalignment is present, and if so, recovers the position -> original-id map
(deterministically, by re-running the same union-find) so the output can be repaired.
"""
import duckdb, numpy as np, json

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
g = duckdb.connect(f"{D}/db/graph.duckdb", read_only=True)
ce = g.execute("SELECT eid, u, v FROM tgraph_edges ORDER BY eid").fetchall()
print(f"tgraph_edges: {len(ce):,} edges, eid range {ce[0][0]}..{ce[-1][0]}")

parent = {}
def find(x):
    r = x
    while parent[r] != r: r = parent[r]
    while parent[x] != r: parent[x], x = r, parent[x]
    return r
for r in ce:
    parent.setdefault(r[1], r[1]); parent.setdefault(r[2], r[2])
for r in ce:
    ra, rb = find(r[1]), find(r[2])
    if ra != rb: parent[ra] = rb
from collections import Counter
comp = Counter(find(n) for n in parent)
big, big_n = comp.most_common(1)[0]
kept = [r[0] for r in ce if find(r[1]) == big and find(r[2]) == big]
kset = set(kept)                      # built ONCE — rebuilding it inside the comprehension is O(n^2)
dropped = [r[0] for r in ce if r[0] not in kset]
E = len(kept)
print(f"largest component: {big_n:,}/{len(parent):,} nodes -> kept {E:,} edges, dropped {len(dropped):,}")
print(f"positions run 0..{E-1:,}")

bad = [e for e in dropped if e < E - 1]
print(f"\ndropped edge ids that are BELOW the highest position (< {E-1:,}): {len(bad):,}")
if bad:
    print("  -> MISALIGNED: those positions carry counts belonging to a different edge.")
    print("     first few dropped ids:", bad[:10])
else:
    print("  -> aligned: every dropped id lies above the position range, so the join is safe.")

json.dump(kept, open(f"{D}/db/position_to_eid.json", "w"))
print(f"\nkept order (position -> original eid) written to db/position_to_eid.json")
print("first 5 positions ->", kept[:5], " last:", kept[-3:])
