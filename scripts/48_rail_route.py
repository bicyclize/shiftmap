"""Move 'rail corridor' trips onto the RAIL network, and take them out of the road volume.

Two bugs are fixed here, both reported from the map ("hide road and red segments over the motorway
remain", "rail trips should go through only rail tracks or tram tracks"):

  1. rail-classified trips were routed on the ROAD graph, so a tram ride was drawn along whatever
     roads connect its ends — 18% of it on motorways;
  2. the volume layer counted them on road edges, so hiding 'road' could not remove them.

Method, chosen to avoid re-routing the other 380k trips (an hour of compute):

  * Pass A — route the rail-classified trips on the RAIL graph -> their geometry + rail edge volume.
  * Pass B — route THOSE SAME trips on the ROAD graph, then SUBTRACT that contribution from the
    existing road volume. Routing is deterministic, so the subtraction is exact; the script asserts
    that no count goes negative.
  * Rail trips whose ends sit far from any track are NOT rail-routed (they keep their road route) —
    a trip starting 2 km from a tram line is not a guideway trip, and routing it from the nearest
    track would invent a journey.

STRUCTURE NOTE: everything runs under `main()` behind an `if __name__ == '__main__'` guard, and the
worker is a top-level function taking a plain list. `multiprocessing` spawn re-imports this module
in every child: without the guard the child would re-run the whole script (and 8 processes would
then all rewrite the same output files), and a worker imported from elsewhere by file path cannot be
pickled at all ("import of module 'r40' failed").
"""
import duckdb, math, time, os, sys, json
import numpy as np

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
NPROC = int(os.environ.get('NPROC', '8'))
SNAP_MAX_M = 800.0          # an end further than this from any track -> not a guideway trip
R40 = f"{D}/scripts/40_route_turns.py"


def load40():
    """Load 40_route_turns as a module (its filename starts with a digit, so a plain import cannot
    name it). Safe to call in every worker."""
    import importlib.util
    if 'r40' in sys.modules:
        return sys.modules['r40']
    spec = importlib.util.spec_from_file_location("r40", R40)
    mod = importlib.util.module_from_spec(spec)
    sys.modules['r40'] = mod
    spec.loader.exec_module(mod)
    return mod


def road_chunk(trips):
    """Worker: per-road-edge split counts for a list of trips. Top-level and plain-data, so spawn
    can pickle the reference (this module is re-imported as __mp_main__ in the child)."""
    m40 = load40()
    return m40.route_chunk((list(trips),))


def main():
    t_start = time.time()
    con = duckdb.connect(f"{D}/db/osm.duckdb", read_only=True)
    rows = con.execute("""SELECT row_number() OVER () - 1 AS idx, o_lon, o_lat, d_lon, d_lat, od_m,
                                 day_tag, trip_scope, bike_direct, btb, btf FROM platform""").fetchall()
    m40a = load40()
    trips = [(r[0], r[1], r[2], r[3], r[4], r[5],
              m40a.splits_for(r[6], r[5], r[7], r[8], r[9], r[10])) for r in rows]
    indices = {t[0]: t for t in trips}
    mode = {r[0]: r[1] for r in con.execute(
        f"SELECT i, mode FROM read_parquet('{D}/platform/rail_mode.parquet')").fetchall()}
    rail_idx = [i for i, mo in mode.items() if mo == 'rail']
    print(f"trips {len(trips):,} | classified rail: {len(rail_idx):,}", flush=True)

    # ---------------- rail engine ----------------
    t0 = time.time()
    g = duckdb.connect(f"{D}/db/graph.duckdb", read_only=True)
    nd = g.execute("SELECT id, lon, lat FROM tgrail_nodes ORDER BY id").fetchall()
    RCOORDS = np.array([[r[1], r[2]] for r in nd])
    ce = g.execute("SELECT eid, u, v, len_m, nodes FROM tgrail_edges ORDER BY eid").fetchall()
    # union-find over the contracted rail edges -> the separate guided systems (tram / metro / HEV
    # / MAV are not connected to each other by any passenger track)
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
    RB = sorted({r[1] for r in ce} | {r[2] for r in ce})
    RCMAP = {n: i for i, n in enumerate(RB)}
    NRAIL = len(ce)
    rflat, roffs = [], [0]
    for r in ce:
        rflat.extend(r[4]); roffs.append(len(rflat))
    rflat = np.array(rflat, dtype=np.int64); roffs = np.array(roffs, dtype=np.int64)
    ru = np.array([r[1] for r in ce], dtype=np.int64)
    rv = np.array([r[2] for r in ce], dtype=np.int64)

    import igraph as ig
    from scipy.spatial import cKDTree
    gr = ig.Graph(n=len(RB), edges=[(RCMAP[r[1]], RCMAP[r[2]]) for r in ce], directed=False)
    gr.es['weight'] = [r[3] for r in ce]
    rnode2edge = np.full(RCOORDS.shape[0], -1, dtype=np.int64)
    rnode2edge[rflat] = np.repeat(np.arange(NRAIL, dtype=np.int64), np.diff(roffs))
    rvalid = np.where(rnode2edge >= 0)[0]
    rlat0 = math.radians(float(RCOORDS[:, 1].mean()))
    rcosl = math.cos(rlat0)
    rxy = np.column_stack([RCOORDS[:, 0] * 111320.0 * rcosl, RCOORDS[:, 1] * 110540.0])
    rtree = cKDTree(rxy[rvalid])
    print(f"rail engine: {gr.vcount():,} vertices {gr.ecount():,} edges  ({time.time()-t0:.0f}s)", flush=True)

    # ---- per-component snap ----
    # The guided systems are separate networks, so snapping each end to the NEAREST track can put
    # the origin on a tram and the destination on a railway: unreachable, and the trip is thrown
    # away. Instead pick the ONE system that fits both ends best and route inside it.
    comp_root = {n: find(n) for n in parent}
    raw_comp = np.full(RCOORDS.shape[0], -1, dtype=np.int64)
    raw_comp[rflat] = np.repeat([comp_root[r[1]] for r in ce], np.diff(roffs))
    comp_trees = {}
    for cv in set(raw_comp.tolist()) - {-1}:
        idx = np.where(raw_comp == cv)[0]
        if len(idx) < 10: continue                      # ignore scraps
        comp_trees[cv] = (cKDTree(rxy[idx]), idx)
    print(f"rail systems with a usable tree: {len(comp_trees)}", flush=True)

    def snap_in(cv, lo, la):
        tree, idx = comp_trees[cv]
        d, j = tree.query([lo * 111320.0 * rcosl, la * 110540.0])
        if d > SNAP_MAX_M: return None
        nid = int(idx[j]); e = int(rnode2edge[nid])
        if e < 0: return None
        ch = rflat[roffs[e]:roffs[e + 1]]
        pos = int(np.where(ch == nid)[0][0])
        if pos <= len(ch) - 1 - pos:
            return d, RCMAP[int(ru[e])], ch[:pos + 1][::-1], int(ru[e])
        return d, RCMAP[int(rv[e])], ch[pos:], int(rv[e])

    # ---------------- Pass A ----------------
    rail_counts = np.zeros((NRAIL, m40a.NSPLIT), dtype=np.int64)
    rail_geom, rail_len, rail_ok = {}, {}, []
    fell_back = 0
    tA = time.time()
    for i in rail_idx:
        _, olon, olat, dlon, dlat, od_m, tsplit = indices[i]
        best = None
        for cv in comp_trees:
            a = snap_in(cv, olon, olat); b = snap_in(cv, dlon, dlat)
            if a is None or b is None: continue
            tot = a[0] + b[0]
            if best is None or tot < best[0]: best = (tot, a, b)
        if best is None:
            fell_back += 1; continue
        _, a, b = best
        u, part_o, u_orig = a[1], a[2], a[3]
        v, part_d, v_orig = b[1], b[2], b[3]
        epath = []
        if u != v:
            try:
                ep = gr.get_shortest_paths(u, to=v, weights='weight', output='epath')
            except Exception:
                ep = None
            epath = ep[0] if ep else []
            if not epath:
                fell_back += 1; continue
        pts = [list(part_o)]; cur = u_orig
        for e in epath:
            for k in tsplit: rail_counts[e, k] += 1
            a, b = int(ru[e]), int(rv[e])
            ch = rflat[roffs[e]:roffs[e + 1]]
            if cur == a:
                pts.append(ch.tolist()); cur = b
            else:
                pts.append(ch[::-1].tolist()); cur = a
        pts.append(list(part_d[::-1]))
        seq = []
        for seg in pts:
            if seq and seg and seq[-1] == seg[0]: seq.extend(seg[1:])
            else: seq.extend(seg)
        c = RCOORDS[seq]
        if len(seq) >= 2:
            rail_len[i] = float(np.sum(np.hypot(np.diff(c[:, 0]) * 111320.0 * rcosl,
                                                np.diff(c[:, 1]) * 110540.0)))
            rail_geom[i] = m40a.simplify_xy(c)
            rail_ok.append(i)
    print(f"Pass A: rail-routed {len(rail_ok):,} of {len(rail_idx):,}  "
          f"(kept their road route: {fell_back:,})  ({time.time()-tA:.0f}s)", flush=True)

    # ---------------- Pass B ----------------
    tB = time.time()
    sub = [tuple(indices[i]) for i in rail_ok]
    chunks = [sub[k::NPROC] for k in range(NPROC)]
    import multiprocessing as mp
    ctx = mp.get_context('spawn')
    with ctx.Pool(NPROC) as pool:
        parts = pool.map(road_chunk, [[tuple(t) for t in c] for c in chunks])
    road_sub = np.sum([p[1] for p in parts], axis=0)
    for p in parts:
        if p[2]:
            try: os.remove(p[2])
            except OSError: pass
    print(f"Pass B: road footprint of those {len(sub):,} trips computed  ({time.time()-tB:.0f}s)", flush=True)

    # ---------------- rebuild the outputs ----------------
    out = f"{D}/platform"
    # The existing routed_edges attached counts to the WRONG geometry: the output join matched
    # edge_geo.eid (ORIGINAL ids, with gaps) to df_cnt.eid (POSITIONS). 3,128 dropped-fragment ids
    # sit below the position ceiling, so from id 35 onward every count sat on another edge's line.
    # Rebuild: counts stay keyed by position, geometry is re-read through the position -> eid map.
    pos2eid = json.load(open(f"{D}/db/position_to_eid.json"))
    print(f"\nalignment repair: {len(pos2eid):,} positions -> original edge ids", flush=True)

    # ROAD edges only: rail edges are written with ids offset by 1e6 and are not positions in the
    # road split array, so including them indexes out of bounds.
    prev = con.execute(f"SELECT eid, n, ns FROM read_parquet('{out}/routed_edges.parquet') "
                       f"WHERE kind='road'").fetchall()
    road_n = np.zeros(len(pos2eid), dtype=np.int64)
    road_ns = np.zeros((len(pos2eid), m40a.NSPLIT), dtype=np.int64)
    for eid, n_, ns_ in prev:                       # eid here IS the position
        road_n[eid] = n_; road_ns[eid] = ns_
    before = int(road_n.sum())
    keep_pos = road_n > 0                           # only positions that carried traffic
    road_ns[keep_pos] = road_ns[keep_pos] - road_sub[keep_pos]
    if (road_ns < 0).any():
        raise SystemExit(f"negative split after subtraction ({(road_ns < 0).sum()} cells) — "
                         f"routing is not deterministic; do not trust this output")
    road_n = road_n - road_sub[:, m40a.NSTOT]
    if (road_n < 0).any():
        raise SystemExit("negative edge count after subtraction")
    print(f"subtracted the rail trips from the road volume: {before:,} -> {int(road_n.sum()):,} edge-visits"
          f"   ({(road_n == 0).sum():,} edges now empty)", flush=True)

    geo = {}
    for i, xy in con.execute(f"SELECT i, xy FROM read_parquet('{out}/routed_geom.parquet')").fetchall():
        geo[i] = rail_geom.get(i, xy)
    rl = con.execute(f"SELECT i, route_m, ok FROM read_parquet('{out}/route_len.parquet')").fetchall()
    con.close()
    print(f"geometry: {len(geo):,} routes, {len(rail_geom):,} of them now follow tracks", flush=True)

    import pandas as pd
    w = duckdb.connect()
    # `on_rail` is the NETWORK THIS TRIP'S DRAWN GEOMETRY FOLLOWS, not the trip's classification.
    # A rail-corridor trip that could not be routed on a single guided system keeps its road route,
    # and the app must draw and count it as road — otherwise hiding the road network still leaves
    # its segments on screen.
    rail_set = set(rail_geom)
    w.register('df_rl', pd.DataFrame([{'i': i, 'route_m': int(round(rail_len.get(i, rm))), 'ok': ok,
                                       'on_rail': i in rail_set}
                                      for i, rm, ok in rl]))
    w.execute(f"COPY (SELECT * FROM df_rl ORDER BY i) TO '{out}/route_len.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)")
    w.register('df_g', pd.DataFrame([{'i': i, 'xy': geo[i]} for i in sorted(geo)]))
    w.execute(f"COPY (SELECT * FROM df_g ORDER BY i) TO '{out}/routed_geom.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)")

    w.register('df_pos', pd.DataFrame({'pos': np.arange(len(pos2eid), dtype=np.int64),
                                       'orig': np.array(pos2eid, dtype=np.int64)}))
    w.register('df_road', pd.DataFrame({
        'pos': np.where(road_n > 0)[0].astype(np.int64),
        'n': road_n[road_n > 0].astype(np.int64),
        'ns': [road_ns[k].tolist() for k in np.where(road_n > 0)[0]]}))
    w.execute(f"ATTACH '{D}/db/graph.duckdb' AS gdb (READ_ONLY)")
    # geometry rebuilt from the correct edge for each position
    w.execute("""CREATE OR REPLACE TABLE re AS
      SELECT r.pos AS eid, 'road' AS kind, g.u, g.v, g.len_m, r.n, r.ns,
             flatten(list([round(nd.lon,5)::FLOAT, round(nd.lat,5)::FLOAT] ORDER BY p.k)) AS xy
      FROM df_road r
      JOIN df_pos m ON m.pos = r.pos
      JOIN gdb.tgraph_edges g ON g.eid = m.orig
      JOIN (SELECT g2.eid, t.k, nd2.lon, nd2.lat FROM gdb.tgraph_edges g2,
            LATERAL (SELECT unnest(range(1, len(g2.nodes)+1)) AS k) t
            JOIN gdb.tgraph_nodes nd2 ON nd2.id = g2.nodes[t.k]) p ON p.eid = g.eid
      JOIN gdb.tgraph_nodes nd ON nd.id = g.nodes[p.k]
      GROUP BY r.pos, g.u, g.v, g.len_m, r.n, r.ns""")

    nrail_used = int((rail_counts[:, m40a.NSTOT] > 0).sum())
    print(f"rail edges with traffic: {nrail_used:,} / {NRAIL:,}")
    # written through DuckDB, not pandas: pandas needs pyarrow/fastparquet for parquet and neither
    # is present, whereas DuckDB has a native parquet writer.
    w.register('df_rc', pd.DataFrame([{'eid': k, 'n': int(rail_counts[k, m40a.NSTOT]),
                                       'ns': [int(x) for x in rail_counts[k]]} for k in range(NRAIL)]))
    w.execute(f"COPY (SELECT * FROM df_rc) TO '{D}/db/rail_counts.parquet' "
              f"(FORMAT PARQUET, COMPRESSION ZSTD)")
    w.execute("CREATE OR REPLACE TABLE rcounts AS SELECT * FROM df_rc")
    w.execute("""CREATE OR REPLACE TABLE rrail AS
      SELECT 1000000 + c.eid AS eid, 'rail' AS kind, g.u, g.v, g.len_m, c.n, c.ns,
             flatten(list([round(p.lon,5)::FLOAT, round(p.lat,5)::FLOAT] ORDER BY p.k)) AS xy
      FROM rcounts c JOIN gdb.tgrail_edges g ON g.eid = c.eid
      JOIN (SELECT g2.eid, t.k, n2.lon, n2.lat FROM gdb.tgrail_edges g2,
            LATERAL (SELECT unnest(range(1, len(g2.nodes)+1)) AS k) t
            JOIN gdb.tgrail_nodes n2 ON n2.id = g2.nodes[t.k]) p ON p.eid = g.eid
      WHERE c.n > 0
      GROUP BY c.eid, g.u, g.v, g.len_m, c.n, c.ns""")
    w.execute(f"COPY (SELECT * FROM re UNION ALL SELECT * FROM rrail) TO '{out}/routed_edges.parquet' "
              f"(FORMAT PARQUET, COMPRESSION ZSTD)")
    nroad = w.execute("SELECT count(*) FROM re").fetchone()[0]
    nrail = w.execute("SELECT count(*) FROM rrail").fetchone()[0]
    print(f"routed_edges: {nroad:,} road edges + {nrail:,} rail edges")
    for f in ('routed_edges', 'routed_geom', 'route_len'):
        fp = f"{out}/{f}.parquet"
        print(f"  {f+'.parquet':24s} {os.path.getsize(fp)/1e6:6.1f} MB")
    print(f"total {time.time()-t_start:.0f}s")


if __name__ == '__main__':
    main()
