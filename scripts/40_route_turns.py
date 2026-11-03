"""Route every trip on the FIXED road graph: arterial-preferring cost + real turn restrictions.

Two changes from 25_route_all.py, both aimed at the reported faults.

1. COST IS TIME, NOT DISTANCE. Weight = len_m / speed(class). A distance-minimising router happily
   dives down a residential street to save 50 m; pricing by time lets a 60 km/h arterial beat a
   30 km/h side street over the same distance, so main-road traffic stays on main roads.

2. TURN RESTRICTIONS ARE OBEYED. The graph is DIRECTED, and every junction carrying a restriction
   is split into one copy per incident edge. A turn that a restriction forbids simply has no arc
   between the copies, so the illegal left turn is not a high-cost option — it is not an option.

   Modelled: no_left_turn, no_right_turn, no_straight_on, only_left_turn, only_right_turn,
   only_straight_on.
   NOT modelled: no_u_turn. A u-turn here is not a connector between copies, it is traversing the
   same edge straight back, which the arc set always permits. U-turns essentially never appear in
   an origin-destination shortest path, so the practical effect is nil — but it is not modelled.
"""
import duckdb, math, time, sys, os
import numpy as np
from collections import defaultdict

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
NPROC = int(os.environ.get('NPROC', '8'))
CACHE = f"{D}/db/route_cache_turns.npz"

NSDC, NSCOPE, NSSCEN, NSTOT = 35, 35, 38, 41
NSPLIT = 42
DAYS = ['08', '09', '10', '11', '12', '13', '14']
SCOPES = {'budapest': 0, 'suburb_bp': 1, 'suburb_local': 2}

# km/h by class — the whole point of the fix: an arterial must be cheaper per metre than a side street
SPEED = {
    'motorway': 100, 'motorway_link': 70, 'trunk': 80, 'trunk_link': 60,
    'primary': 60, 'primary_link': 45, 'secondary': 50, 'secondary_link': 40,
    'tertiary': 45, 'tertiary_link': 35, 'unclassified': 40, 'residential': 30,
    'living_street': 15, 'service': 15, 'road': 25, 'track': 15, 'path': 10,
}
CLS_LIST = sorted(SPEED)

MLAT = 110574.0
MLON = 111320.0 * math.cos(math.radians(47.5))
GEOM_TOL = 30.0
GEOM_CAP = 120


def band_of(m):
    m = m or 0
    return 0 if m < 2000 else 1 if m < 5000 else 2 if m < 8000 else 3 if m < 15000 else 4


def _dp_keep(x, y, tol):
    n = len(x)
    keep = np.zeros(n, dtype=bool); keep[0] = keep[-1] = True
    stack = [(0, n - 1)]; t2 = tol * tol
    while stack:
        a, b = stack.pop()
        if b <= a + 1: continue
        ax, ay, bx, by = x[a], y[a], x[b], y[b]
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy
        seg = slice(a + 1, b)
        if l2 == 0:
            d2 = (x[seg] - ax) ** 2 + (y[seg] - ay) ** 2
        else:
            t = np.clip(((x[seg] - ax) * dx + (y[seg] - ay) * dy) / l2, 0, 1)
            d2 = (x[seg] - (ax + t * dx)) ** 2 + (y[seg] - (ay + t * dy)) ** 2
        k = int(np.argmax(d2))
        if d2[k] > t2:
            m = a + 1 + k; keep[m] = True
            stack.append((a, m)); stack.append((m, b))
    return keep


def simplify_xy(c, tol=GEOM_TOL, cap=GEOM_CAP):
    n = len(c)
    if n <= 2:
        return [round(float(v), 5) for v in c.reshape(-1)]
    x = c[:, 0] * MLON; y = c[:, 1] * MLAT
    t = tol
    while True:
        keep = _dp_keep(x, y, t)
        if int(keep.sum()) <= cap or t > 600: break
        t *= 1.6
    out = []
    for k in range(n):
        if keep[k]:
            out.append(round(float(c[k, 0]), 5)); out.append(round(float(c[k, 1]), 5))
    return out


def splits_for(day_tag, od_m, scope, bd, btb, btf):
    di = DAYS.index(day_tag) if day_tag in DAYS else 0
    out = [di * 5 + band_of(od_m), NSCOPE + SCOPES.get(scope, 0), NSTOT]
    if bd: out.append(NSSCEN)
    if btb: out.append(NSSCEN + 1)
    if btf: out.append(NSSCEN + 2)
    return tuple(out)


def prep():
    """Cache the split graph as numpy arrays so each worker loads it fast."""
    if os.path.exists(CACHE):
        return
    t0 = time.time()
    g = duckdb.connect(f"{D}/db/graph.duckdb", read_only=True)
    nodes = g.execute("SELECT id, lon, lat FROM tgraph_nodes ORDER BY id").fetchall()
    coords = np.array([[r[1], r[2]] for r in nodes], dtype=np.float64)

    ce = g.execute("SELECT eid, u, v, len_m, cls, nodes FROM tgraph_edges ORDER BY eid").fetchall()

    # Keep only the largest connected component — the original contraction did this and the
    # rebuilt graph dropped it. Without it, snapping still lands in detached fragments and every
    # route to or from such a fragment is unreachable (that was the residual 0.5% of failures).
    parent = {}
    def find(x):
        r = x
        while parent[r] != r: r = parent[r]
        while parent[x] != r: parent[x], x = r, parent[x]
        return r
    for r in ce:
        parent.setdefault(r[1], r[1]); parent.setdefault(r[2], r[2])
    for r in ce:
        ru, rv = find(r[1]), find(r[2])
        if ru != rv: parent[ru] = rv
    from collections import Counter
    comp = Counter(find(n) for n in parent)
    big, big_n = comp.most_common(1)[0]
    before_e, before_n = len(ce), len(parent)
    ce = [r for r in ce if find(r[1]) == big and find(r[2]) == big]
    print(f"  largest component: {big_n:,} of {before_n:,} nodes kept; "
          f"edges {before_e:,} -> {len(ce):,}  ({comp.most_common(3)} sizes)")

    base = sorted({r[1] for r in ce} | {r[2] for r in ce})
    cmap = {n: i for i, n in enumerate(base)}
    B = len(base)

    inc = defaultdict(list)
    for eid, u, v, ln, cls, ch in ce:
        inc[u].append(eid); inc[v].append(eid)

    rests = g.execute("SELECT node, kind, from_edges, to_edges FROM trestrictions").fetchall()
    by_node = defaultdict(list)
    for nd, kind, fe, te in rests:
        by_node[nd].append((kind, set(fe or []), set(te or [])))

    forbid_local = {}                   # node -> forbidden (i,j) positions within inc[node]
    good_nodes = []
    skipped_uturn = traps_dropped = degenerate = 0
    for nd, rs in by_node.items():
        idxs = inc[nd]
        k = len(idxs)
        if k < 2:                       # nothing to split
            degenerate += 1
            continue
        fb = set()
        for kind, fs, ts in rs:
            # A restriction whose from-way IS its to-way is a U-TURN. A u-turn is not a connector
            # here — it is traversing the same edge straight back — so it cannot be represented,
            # and "forbidding" it is actively wrong: a way running THROUGH the junction appears as
            # TWO contracted edges, so forbidding (A -> A) deletes the legitimate through movement.
            if fs and fs == ts:
                skipped_uturn += 1
                continue
            for i, ei in enumerate(idxs):
                if ei not in fs: continue
                for j, ej in enumerate(idxs):
                    if i == j: continue
                    if kind.startswith('no_'):
                        if ej in ts: fb.add((i, j))
                    else:               # only_* : from A you may ONLY go to B
                        if ej not in ts: fb.add((i, j))
        # If the restriction set leaves ANY approach with no permitted way out, the junction is
        # impassable. That is always a modelling artefact (contradictory or over-broad resolution),
        # and an impassable junction severs the road and makes everything beyond it unreachable.
        # The road wins: keep such a junction intact and drop its restrictions.
        if any(not [j for j in range(k) if j != i and (i, j) not in fb] for i in range(k)):
            traps_dropped += 1
            continue
        forbid_local[nd] = fb
        good_nodes.append(nd)

    split_nodes = sorted(good_nodes)
    copy_node, copy_edge, node_copies = [], [], {}
    for nd in split_nodes:
        idxs = []
        for eid in inc[nd]:
            idxs.append(len(copy_node))
            copy_node.append(nd); copy_edge.append(eid)
        node_copies[nd] = idxs
    copy_of = {(copy_node[i], copy_edge[i]): i for i in range(len(copy_node))}
    forbid = set()
    for nd in split_nodes:
        ids = node_copies[nd]
        for (i, j) in forbid_local[nd]:
            forbid.add((ids[i], ids[j]))

    flat, offs, lens = [], [0], []
    for eid, u, v, ln, cls, ch in ce:
        flat.extend(ch); offs.append(len(flat)); lens.append(ln)

    # Pre-resolve the vertex for the u-end and v-end of every edge, so the engine needs no
    # per-edge Python lookups at all: -1 means "that end is not split, use the base vertex".
    copu = np.array([copy_of.get((r[1], r[0]), -1) for r in ce], dtype=np.int64)
    copv = np.array([copy_of.get((r[2], r[0]), -1) for r in ce], dtype=np.int64)

    np.savez(CACHE, coords=coords,
             copu=copu, copv=copv,
             ce_u=np.array([r[1] for r in ce], dtype=np.int64),
             ce_v=np.array([r[2] for r in ce], dtype=np.int64),
             ce_len=np.array(lens, dtype=np.float64),
             ce_spd=np.array([SPEED.get(r[4], 25.0) for r in ce], dtype=np.float64),
             chain_flat=np.array(flat, dtype=np.int64),
             chain_off=np.array(offs, dtype=np.int64),
             cnodes=np.array(base, dtype=np.int64),
             copy_node=np.array(copy_node, dtype=np.int64),
             copy_edge=np.array(copy_edge, dtype=np.int64),
             copy_off=np.array([0] + [len(node_copies[n]) for n in split_nodes],
                               dtype=np.int64).cumsum(),
             forbid=np.array(sorted(forbid), dtype=np.int64).reshape(-1, 2) if forbid else np.zeros((0, 2), np.int64),
             split_nodes=np.array(split_nodes, dtype=np.int64))
    print(f"cache built {time.time()-t0:.0f}s -> {os.path.getsize(CACHE)/1e6:.0f} MB  "
          f"(base nodes {B:,}, split junctions {len(split_nodes):,}, copies {len(copy_node):,})\n"
          f"  forbidden turn pairs {len(forbid):,}\n"
          f"  skipped: {skipped_uturn:,} u-turn restrictions (not representable), "
          f"{traps_dropped:,} junctions whose restrictions would have made them impassable, "
          f"{degenerate:,} with a single arm")


def make_engine(z):
    import igraph as ig
    from scipy.spatial import cKDTree
    # HOIST EVERY MEMBER OUT OF THE NpzFile FIRST. Indexing z['...'] inside a 300k-iteration
    # loop re-reads and re-decompresses that member on every access and looks exactly like a
    # hang — it cost an hour of CPU on the first attempt at this script.
    coords = z['coords']; cnodes = z['cnodes']
    ce_u = z['ce_u']; ce_v = z['ce_v']; ce_len = z['ce_len']; ce_spd = z['ce_spd']
    copu = z['copu']; copv = z['copv']
    copy_node = z['copy_node']
    forbid = z['forbid']; split_arr = z['split_nodes']
    chain_off = z['chain_off']; chain_flat = z['chain_flat']

    B = len(cnodes); ncopy = len(copy_node)
    split_nodes = set(int(x) for x in split_arr)
    E = len(ce_u)

    # vertex per edge-end, fully vectorised: base index, or the split copy where that end is split
    base_of = np.full(int(cnodes.max()) + 1, -1, dtype=np.int64)
    base_of[cnodes] = np.arange(B, dtype=np.int64)
    vu = base_of[ce_u].copy(); vv = base_of[ce_v].copy()
    mu, mv = copu >= 0, copv >= 0
    vu[mu] = B + copu[mu]
    vv[mv] = B + copv[mv]
    if (vu < 0).any() or (vv < 0).any():
        raise SystemExit("vertex mapping failed: a contracted edge endpoint is not a base node")

    w = ce_len * 3.6 / ce_spd                                   # seconds
    src = np.concatenate([vu, vv]); dst = np.concatenate([vv, vu])
    wts = np.concatenate([w, w])
    E_contract = int(len(src))

    # connectors: one arc per ALLOWED turn at every split junction (forbidden pairs omitted)
    node_copies = defaultdict(list)
    for i in range(ncopy):
        node_copies[int(copy_node[i])].append(i)
    fb = set(map(tuple, forbid.tolist()))
    cs, cd = [], []
    for nd in split_nodes:
        idxs = node_copies[nd]
        if len(idxs) < 2: continue
        for i in idxs:
            for j in idxs:
                if i == j or (i, j) in fb: continue
                cs.append(B + i); cd.append(B + j)
    if cs:
        src = np.concatenate([src, np.array(cs, dtype=np.int64)])
        dst = np.concatenate([dst, np.array(cd, dtype=np.int64)])
        wts = np.concatenate([wts, np.zeros(len(cs))])

    gr = ig.Graph(n=B + ncopy, edges=list(zip(src.tolist(), dst.tolist())), directed=True)
    gr.es['weight'] = wts.tolist()

    lat0 = math.radians(float(coords[:, 1].mean()))
    xy = np.column_stack([coords[:, 0] * 111320.0 * np.cos(lat0), coords[:, 1] * 110540.0])
    node2edge = np.full(coords.shape[0], -1, dtype=np.int64)
    node2edge[chain_flat] = np.repeat(np.arange(E, dtype=np.int64), np.diff(chain_off))
    valid = np.where(node2edge >= 0)[0]
    tree = cKDTree(xy[valid])
    return (gr, tree, vu, vv, node2edge, coords, math.degrees(lat0), valid, B, E_contract)


def route_chunk(args):
    trips, = (args,) if not isinstance(args, tuple) else args
    z = np.load(CACHE)
    (gr, tree, vu, vv, node2edge, coords, lat0, valid, B, E_contract) = make_engine(z)
    off, flat = z['chain_off'], z['chain_flat']
    ce_u, ce_v = z['ce_u'], z['ce_v']
    # Arc layout is [0..E) = u->v and [E..2E) = v->u, then connectors at >= 2E. An arc id is
    # therefore NOT an edge id: reduce it modulo E before using it as one.
    E = len(ce_u)
    cosl = math.cos(math.radians(lat0))
    counts = np.zeros((E, NSPLIT), dtype=np.int32)
    res = []; geoms = []; ok = 0
    t0 = time.time()

    def snap(lo, la):
        """Nearest routable node, then walk its chain to the nearer end. Returns the VERTEX to
        start/end at (the split copy when that edge-end is a restricted junction), the partial
        chain, and the original node id."""
        _, j = tree.query([lo * 111320.0 * cosl, la * 110540.0])
        nid = int(valid[j]); e = int(node2edge[nid])
        if e < 0: return None
        chain = flat[off[e]:off[e + 1]]
        pos = int(np.where(chain == nid)[0][0])
        if pos <= len(chain) - 1 - pos:
            return int(vu[e]), chain[:pos + 1][::-1], int(ce_u[e])
        return int(vv[e]), chain[pos:], int(ce_v[e])

    for (idx, olon, olat, dlon, dlat, od_m, tsplit) in trips:
        so = snap(olon, olat); sd = snap(dlon, dlat)
        if so is None or sd is None:
            res.append((idx, -1, False)); continue
        u, part_o, u_orig = so
        v, part_d, v_orig = sd
        epath = []
        if u != v:
            try:
                ep = gr.get_shortest_paths(u, to=v, weights='weight', output='epath', mode='out')
            except Exception:
                ep = None
            epath = ep[0] if ep else []
            if not epath:
                res.append((idx, -1, False)); continue
        pts = [part_o.tolist()]; cur = u_orig
        for arc in epath:
            if arc >= E_contract: continue          # a turn connector, not a road
            e = arc if arc < E else arc - E         # back to an edge id, direction-independent
            for k in tsplit:
                counts[e, k] += 1
            a, b = int(ce_u[e]), int(ce_v[e])
            ch = flat[off[e]:off[e + 1]]
            if cur == a:
                pts.append(ch.tolist()); cur = b
            else:
                pts.append(ch[::-1].tolist()); cur = a
        pts.append(part_d[::-1].tolist())
        seq = []
        for seg in pts:
            if seq and seg and seq[-1] == seg[0]: seq.extend(seg[1:])
            else: seq.extend(seg)
        c = coords[seq]
        rm = float(np.sum(np.hypot(np.diff(c[:, 0]) * 111320.0 * cosl,
                                   np.diff(c[:, 1]) * 110540.0)))
        res.append((idx, int(round(rm)), True))
        ok += 1
        if len(seq) >= 2:
            geoms.append((idx, simplify_xy(c)))
    part = None
    if geoms:
        import pandas as pd
        part = f"{D}/db/geom_part2_{trips[0][0]}.parquet"
        cd = duckdb.connect()
        cd.register('df_g', pd.DataFrame(geoms, columns=['i', 'xy']))
        cd.execute(f"COPY df_g TO '{part}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        cd.close()
    span = f"{trips[0][0]}..{trips[-1][0]}" if trips else "empty"
    print(f"    chunk {span}: {ok:,}/{len(trips):,} routed in {time.time()-t0:.0f}s", flush=True)
    return res, counts, part


def report(res, trips):
    ok = [r for r in res if r[2]]
    print(f"\nrouted ok {len(ok):,} / {len(res):,}  (failed {len(res)-len(ok):,}, "
          f"{100*(len(res)-len(ok))/max(len(res),1):.1f}%)")
    if ok:
        rm = np.array([r[1] for r in ok]); od = np.array([trips[r[0]][5] for r in ok])
        keep = od > 500
        ratio = rm[keep] / od[keep]
        print(f"median routed length: {np.median(rm)/1000:.2f} km")
        print(f"detour vs straight-line: median {np.median(ratio):.2f} "
              f"p10 {np.percentile(ratio,10):.2f} p90 {np.percentile(ratio,90):.2f}")


def main():
    import pandas as pd
    prep()
    t0 = time.time()
    p = duckdb.connect(f"{D}/db/osm.duckdb", read_only=True)
    rows = p.execute("""SELECT row_number() OVER () - 1 AS idx, o_lon, o_lat, d_lon, d_lat, od_m,
                               day_tag, trip_scope, bike_direct, btb, btf
                         FROM platform""").fetchall()
    trips = [(r[0], r[1], r[2], r[3], r[4], r[5],
              splits_for(r[6], r[5], r[7], r[8], r[9], r[10])) for r in rows]
    print(f"trips: {len(trips):,}")

    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
        sub = [tuple(t) for t in trips[:n]]
        res, counts, part = route_chunk((sub,))
        report(res, trips)
        print(f"edges with traffic: {(counts[:, NSTOT]>0).sum():,} / {len(counts):,}")
        print(f"geometry part: {part}")
        return

    chunks = [trips[i::NPROC] for i in range(NPROC)]
    print(f"routing {len(trips):,} trips on {NPROC} processes ...", flush=True)
    import multiprocessing as mp
    ctx = mp.get_context('spawn')
    with ctx.Pool(NPROC) as pool:
        parts = pool.map(route_chunk, [([tuple(t) for t in c],) for c in chunks])
    res = [x for q in parts for x in q[0]]
    counts = np.sum([q[1] for q in parts], axis=0)
    geom_parts = [q[2] for q in parts if q[2]]
    print(f"\nrouting finished in {time.time()-t0:.0f}s")
    report(res, trips)

    p.close()
    conn = duckdb.connect(f"{D}/db/osm.duckdb")
    rl = pd.DataFrame({'i': [r[0] for r in res], 'route_m': [r[1] for r in res],
                       'ok': [r[2] for r in res]}).sort_values('i')
    conn.register('df_rl', rl)
    conn.execute("CREATE OR REPLACE TABLE route_len AS SELECT * FROM df_rl")
    conn.execute(f"COPY route_len TO '{D}/platform/route_len.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)")

    conn.register('df_cnt', pd.DataFrame({'eid': np.arange(len(counts), dtype=np.int64),
                                          'n': counts[:, NSTOT].astype(np.int64),
                                          'ns': counts.tolist()}))
    conn.execute(f"ATTACH '{D}/db/graph.duckdb' AS gdb (READ_ONLY)")
    conn.execute("CREATE OR REPLACE TABLE edge_geo AS "
                 "SELECT eid, u, v, len_m, nodes FROM gdb.tgraph_edges")
    conn.execute("""CREATE OR REPLACE TABLE epts AS
      SELECT g.eid, t.k, n.lon, n.lat
      FROM edge_geo g, LATERAL (SELECT unnest(range(1, len(g.nodes)+1)) AS k) t
      JOIN gdb.tgraph_nodes n ON n.id = g.nodes[t.k]""")
    conn.execute("""CREATE OR REPLACE TABLE routed_edges AS
      SELECT g.eid, g.u, g.v, g.len_m, c.n, c.ns,
             flatten(list([round(p.lon,5)::FLOAT, round(p.lat,5)::FLOAT] ORDER BY p.k)) AS xy
      FROM edge_geo g JOIN df_cnt c ON c.eid = g.eid JOIN epts p ON p.eid = g.eid
      WHERE c.n > 0
      GROUP BY g.eid, g.u, g.v, g.len_m, c.n, c.ns""")
    conn.execute(f"COPY routed_edges TO '{D}/platform/routed_edges.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)")

    if geom_parts:
        files = "[" + ", ".join(f"'{f}'" for f in geom_parts) + "]"
        conn.execute("CREATE OR REPLACE TABLE routed_geom AS "
                     f"SELECT i, xy FROM read_parquet({files}) ORDER BY i")
        conn.execute(f"COPY routed_geom TO '{D}/platform/routed_geom.parquet' "
                     f"(FORMAT PARQUET, COMPRESSION ZSTD)")
        for f in geom_parts:
            try: os.remove(f)
            except OSError: pass

    print(f"\nedges with traffic : {(counts[:, NSTOT] > 0).sum():,} / {len(counts):,}")
    if geom_parts:
        print(f"routed geometries  : {conn.execute('SELECT count(*) FROM routed_geom').fetchone()[0]:,}")
    for f in ('route_len', 'routed_edges', 'routed_geom'):
        fp = f"{D}/platform/{f}.parquet"
        if os.path.exists(fp): print(f"  {f+'.parquet':26s} {os.path.getsize(fp)/1e6:6.1f} MB")
    print(f"total {time.time()-t0:.0f}s")


if __name__ == '__main__':
    main()
