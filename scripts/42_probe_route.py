"""Why is the new router slow? Route REAL platform O/D pairs through the turn-restricted engine.

Separates two possibilities that look identical from outside:
  (a) the directed/split graph makes each Dijkstra expensive, or
  (b) many pairs are now UNREACHABLE, and an unreachable Dijkstra explores the whole component
      before it gives up — which is the slowest case and would also mean the split broke
      connectivity.
"""
import time, importlib.util, numpy as np, duckdb, math

D = ("/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/"
     "Transport analysis")
spec = importlib.util.spec_from_file_location("r40", f"{D}/scripts/40_route_turns.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

z = np.load(m.CACHE)
t = time.time(); E = m.make_engine(z); print(f"engine {time.time()-t:.1f}s", flush=True)
(gr, tree, cmap, node2edge, coords, lat0, valid, split_nodes, copy_of, B, E_contract) = E
off, flat = z['chain_off'], z['chain_flat']
ce_u, ce_v = z['ce_u'], z['ce_v']
cosl = math.cos(math.radians(lat0))
print(f"graph {gr.vcount():,} vertices {gr.ecount():,} edges (contract {E_contract:,})", flush=True)

def snap(lo, la):
    _, j = tree.query([lo * 111320.0 * cosl, la * 110540.0])
    nid = int(valid[j]); e = int(node2edge[nid])
    if e < 0: return None
    chain = flat[off[e]:off[e + 1]]
    pos = int(np.where(chain == nid)[0][0])
    if pos <= len(chain) - 1 - pos:
        return int(ce_u[e]), e
    return int(ce_v[e]), e

def vof(nd, eid):
    return B + copy_of[(nd, eid)] if nd in split_nodes else cmap[nd]

con = duckdb.connect(f"{D}/db/osm.duckdb", read_only=True)
rows = con.execute("""SELECT o_lon, o_lat, d_lon, d_lat FROM platform
                      WHERE od_m > 3000 USING SAMPLE 300 ROWS""").fetchall()
print(f"real trips sampled: {len(rows)}", flush=True)

N = len(rows)
t_snap = t_dij = t_tot = 0.0
ok = fail_snap = fail_route = 0
lens = []
for (olon, olat, dlon, dlat) in rows:
    a = time.time()
    so = snap(olon, olat); sd = snap(dlon, dlat)
    if so is None or sd is None: fail_snap += 1; t_snap += time.time() - a; continue
    u_orig, e_o = so; v_orig, e_d = sd
    u, v = vof(u_orig, e_o), vof(v_orig, e_d)
    b = time.time(); t_snap += b - a
    if u == v:
        ok += 1; t_tot += time.time() - a; continue
    try:
        ep = gr.get_shortest_paths(u, to=v, weights='weight', output='epath', mode='out')
    except Exception:
        ep = None
    t_dij += time.time() - b
    if not ep or not ep[0]:
        fail_route += 1
    else:
        ok += 1; lens.append(len(ep[0]))
    t_tot += time.time() - a
    if ok + fail_route + fail_snap >= 40: break

n = ok + fail_route + fail_snap
print(f"\n{routed_ok if False else ''}attempted        {n}")
print(f"  routed ok      {ok}")
print(f"  no snap        {fail_snap}")
print(f"  UNREACHABLE    {fail_route}   {'<-- connectivity broken by the split' if fail_route else ''}")
print(f"\ntime: snap {t_snap:.1f}s | dijkstra {t_dij:.1f}s | total {t_tot:.1f}s")
print(f"dijkstra per attempt: {1000*t_dij/max(n,1):.0f} ms")
print(f"median edges per path: {int(np.median(lens)) if lens else 0}")
print(f"\nprojected full run (439k trips): {t_tot/max(n,1)*438995/3600:.1f} h single, "
      f"{t_tot/max(n,1)*438995/3600/8:.1f} h on 8 cores")
