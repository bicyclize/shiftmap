"""Find what makes ~0.5% of routes unreachable in the turn-restricted graph.

A split junction is represented by one copy per incident edge, connected by connectors for every
ALLOWED turn. If some copy ends up with no outgoing connector it is a dead end: anything arriving
on that edge cannot continue, and the road beyond becomes unreachable. This finds those traps and
names the restrictions responsible.
"""
import importlib.util, numpy as np, duckdb
from collections import defaultdict

D = ("/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/"
     "Transport analysis")
spec = importlib.util.spec_from_file_location("r40", f"{D}/scripts/40_route_turns.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

z = np.load(m.CACHE)
copy_node = z['copy_node']; copy_edge = z['copy_edge']
forbid = set(map(tuple, z['forbid'].tolist()))
split_nodes = set(int(x) for x in z['split_nodes'])
B = len(z['cnodes'])
print(f"split junctions {len(split_nodes):,} | copies {len(copy_node):,} | forbidden pairs {len(forbid):,}")

copies_of = defaultdict(list)
for i in range(len(copy_node)):
    copies_of[int(copy_node[i])].append(i)

out_deg, in_deg = defaultdict(int), defaultdict(int)
for (i, j) in forbid:
    pass
traps, dead_ins, tiny = [], [], 0
for nd in split_nodes:
    idxs = copies_of[nd]
    if len(idxs) < 2:
        tiny += 1
        continue
    for i in idxs:
        outs = [j for j in idxs if j != i and (i, j) not in forbid]
        ins = [j for j in idxs if j != i and (j, i) not in forbid]
        if not outs: traps.append((nd, i, len(idxs)))
        if not ins:  dead_ins.append((nd, i, len(idxs)))
print(f"\njunctions with <2 copies (degenerate)   {tiny:,}")
print(f"copies with NO allowed way out (TRAPS)  {len(traps):,}")
print(f"copies with NO way in (UNREACHABLE)     {len(dead_ins):,}")
print(f"total copies                            {len(copy_node):,}")

if traps:
    g = duckdb.connect(f"{D}/db/graph.duckdb", read_only=True)
    print("\n=== the traps, with the restrictions at them ===")
    shown = 0
    for nd, i, k in traps[:400]:
        rows = g.execute("SELECT kind, from_edges, to_edges FROM trestrictions WHERE node = ?", [nd]).fetchall()
        if not rows: continue
        me = int(copy_edge[i])
        print(f"  node {nd}  copy edge {me}  (junction has {k} edges)")
        for kind, fe, te in rows:
            print(f"      {kind:18s} from={list(fe)}  to={list(te)}")
        shown += 1
        if shown >= 6: break

print("\n=== which restriction kinds sit at trap junctions ===")
if traps:
    g = duckdb.connect(f"{D}/db/graph.duckdb", read_only=True)
    kinds = defaultdict(int)
    for nd, i, k in traps:
        for kind, fe, te in g.execute("SELECT kind, from_edges, to_edges FROM trestrictions WHERE node = ?", [nd]).fetchall():
            kinds[kind] += 1
    for kk, vv in sorted(kinds.items(), key=lambda x: -x[1]): print(f"  {kk:20s} {vv}")
