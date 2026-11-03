"""Debug: are the assembled routes geometrically sane?"""
import duckdb, math, sys
import numpy as np
sys.path.insert(0, 'scripts')
from importlib import import_module
m = import_module('25_route_all')

D = m.D
z = np.load(m.CACHE)
gr, tree, cmap, node2edge, coords, cnodes, lat0 = m.make_engine(z)
off, flat = z['chain_off'], z['chain_flat']
ce_u, ce_v = z['ce_u'], z['ce_v']
cosl = math.cos(math.radians(lat0))


def snap(lo, la):
    _, nid = tree.query([lo * 111320.0 * cosl, la * 110540.0])
    nid = int(nid); e = int(node2edge[nid])
    if e < 0:
        return None
    chain = flat[off[e]:off[e + 1]]
    pos = int(np.where(chain == nid)[0][0])
    if pos <= len(chain) - 1 - pos:
        return int(ce_u[e]), chain[:pos + 1][::-1], int(ce_u[e]), len(chain)
    return int(ce_v[e]), chain[pos:], int(ce_v[e]), len(chain)


def dist_m(lo1, la1, lo2, la2):
    return math.hypot((lo2 - lo1) * 111320.0 * cosl, (la2 - la1) * 110540.0)


p = duckdb.connect(f"{D}/db/osm.duckdb", read_only=True)
trips = p.execute("""SELECT o_lon,o_lat,d_lon,d_lat,od_m FROM platform
                     WHERE od_m BETWEEN 2000 AND 15000 LIMIT 8""").fetchall()

for i, (olon, olat, dlon, dlat, od_m) in enumerate(trips):
    so = snap(olon, olat); sd = snap(dlon, dlat)
    if not so or not sd:
        print(f"{i}: SNAP FAILED"); continue
    u_orig, part_o, _, chain_o = so
    v_orig, part_d, _, chain_d = sd
    u, v = cmap[u_orig], cmap[v_orig]
    ep = gr.get_shortest_paths(u, to=v, weights='weight', output='epath')
    epath = ep[0] if ep else []
    pts = [part_o.tolist()]; cur = u_orig
    for e in epath:
        a, b = int(ce_u[e]), int(ce_v[e])
        ch = flat[off[e]:off[e + 1]]
        if cur == a:
            pts.append(ch.tolist()); cur = b
        else:
            pts.append(ch[::-1].tolist()); cur = a
    pts.append(part_d[::-1].tolist())
    seq = []
    for seg in pts:
        if seq and seg and seq[-1] == seg[0]:
            seq.extend(seg[1:])
        else:
            seq.extend(seg)
    c = coords[seq]
    dx = np.diff(c[:, 0]) * 111320.0 * cosl
    dy = np.diff(c[:, 1]) * 110540.0
    rm = float(np.sum(np.hypot(dx, dy)))
    d_o = dist_m(olon, olat, c[0, 0], c[0, 1])
    d_d = dist_m(dlon, dlat, c[-1, 0], c[-1, 1])
    print(f"{i}: od {od_m/1000:5.2f}km routed {rm/1000:5.2f}km ratio {rm/od_m:4.2f} | "
          f"pts {len(seq):4d} epath {len(epath):4d} | chain_o {chain_o:4d} chain_d {chain_d:4d} | "
          f"start_err {d_o:6.0f}m end_err {d_d:6.0f}m | u==v {u==v}")
