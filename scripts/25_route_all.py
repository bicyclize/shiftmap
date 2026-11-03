"""Route every trip on the contracted road graph → routed volumes + a routed sample.

Fast path: road graph only, no mode classifier (transit corridors will be wrong until the
classifier lands). Snapping uses the nearest ORIGINAL node (dense, ~10-30 m apart) via a
KD-tree, then walks the contracted chain to its nearer end — so the route starts where the
trip actually started, not at the nearest junction.

Outputs (keyed by platform row index):
  platform/route_len.parquet    - routed length per trip (ALL trips)
  platform/routed_edges.parquet - per contracted edge: trip count + geometry  (the volume map)
  platform/routed_sample.parquet- ~10k trips with full routed geometry
"""
import duckdb, math, time, sys, os
import numpy as np

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
KIND = 'road'
NPROC = int(os.environ.get('NPROC', '8'))
SAMPLE_EVERY = int(os.environ.get('SAMPLE_EVERY', '44'))     # ~10k of 439k
CACHE = f"{D}/db/route_cache_{KIND}.npz"

# Per-edge volume split layout (so the map can re-weight on the fly, not just show an all-trips total).
#   0..34  : day x band cross-product      (day*5 + band)  -> EXACT for day, band, or both
#   35..37 : trip_scope                    (marginal; exact when scope is used alone)
#   38..40 : scenario flags                (marginal; bike_direct / btb / btf)
#   41     : total
NSDC, NSCOPE, NSSCEN, NSTOT = 35, 35, 38, 41
NSPLIT = 42
DAYS = ['08', '09', '10', '11', '12', '13', '14']
SCOPES = {'budapest': 0, 'suburb_bp': 1, 'suburb_local': 2}


def band_of(m):
    m = m or 0
    return 0 if m < 2000 else 1 if m < 5000 else 2 if m < 8000 else 3 if m < 15000 else 4


# ---- geometry simplification ----
# Routed paths have ~197 points, mostly collinear along straight OSM ways, so Douglas-Peucker
# keeps only the real turns: at 30 m a route collapses to ~15 points and still follows the
# streets. Shipping FULL geometry for all 438,995 trips would be ~1.2 GB; simplified it is ~40 MB.
MLAT = 110574.0
MLON = 111320.0 * math.cos(math.radians(47.5))
GEOM_TOL = 30.0
GEOM_CAP = 120


def _dp_keep(x, y, tol):
    n = len(x)
    keep = np.zeros(n, dtype=bool); keep[0] = keep[-1] = True
    stack = [(0, n - 1)]; t2 = tol * tol
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
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
    """Douglas-Peucker in metres -> flat [lon,lat,...] rounded for shipping."""
    n = len(c)
    if n <= 2:
        return [round(float(v), 5) for v in c.reshape(-1)]
    x = c[:, 0] * MLON; y = c[:, 1] * MLAT
    t = tol
    while True:
        keep = _dp_keep(x, y, t)
        if int(keep.sum()) <= cap or t > 600:
            break
        t *= 1.6
    out = []
    for k in range(n):
        if keep[k]:
            out.append(round(float(c[k, 0]), 5))
            out.append(round(float(c[k, 1]), 5))
    return out


def splits_for(day_tag, od_m, scope, bd, btb, btf):
    di = DAYS.index(day_tag) if day_tag in DAYS else 0
    out = [di * 5 + band_of(od_m), NSCOPE + SCOPES.get(scope, 0), NSTOT]
    if bd: out.append(NSSCEN)
    if btb: out.append(NSSCEN + 1)
    if btf: out.append(NSSCEN + 2)
    return tuple(out)


def prep():
    """Cache the graph as numpy arrays so each worker loads it in ~1 s."""
    if os.path.exists(CACHE):
        return
    t0 = time.time()
    g = duckdb.connect(f"{D}/db/graph.duckdb", read_only=True)
    nodes = g.execute("SELECT id, lon, lat FROM nodes ORDER BY id").fetchall()
    coords = np.array([[r[1], r[2]] for r in nodes], dtype=np.float64)
    ce = g.execute(f"SELECT u, v, len_m, node_ids FROM c{KIND}_edges").fetchall()
    cnodes = g.execute(f"SELECT id FROM c{KIND}_nodes ORDER BY id").fetchall()
    flat, offs, lens = [], [0], []
    for u, v, l, nids in ce:
        flat.extend(nids); offs.append(len(flat)); lens.append(l)
    np.savez(CACHE, coords=coords,
             ce_u=np.array([r[0] for r in ce], dtype=np.int64),
             ce_v=np.array([r[1] for r in ce], dtype=np.int64),
             ce_len=np.array(lens, dtype=np.float64),
             chain_flat=np.array(flat, dtype=np.int64),
             chain_off=np.array(offs, dtype=np.int64),
             cnodes=np.array([r[0] for r in cnodes], dtype=np.int64))
    print(f"cache built {time.time()-t0:.0f}s -> {os.path.getsize(CACHE)/1e6:.0f} MB")


def make_engine(z):
    import igraph as ig
    from scipy.spatial import cKDTree
    coords = z['coords']; cnodes = z['cnodes']
    cmap = {int(n): i for i, n in enumerate(cnodes)}
    edges = [(cmap[int(u)], cmap[int(v)]) for u, v in zip(z['ce_u'], z['ce_v'])]
    gr = ig.Graph(n=len(cnodes), edges=edges, directed=False)
    gr.es['weight'] = z['ce_len'].tolist()
    lat0 = math.radians(float(coords[:, 1].mean()))
    xy = np.column_stack([coords[:, 0] * 111320.0 * math.cos(lat0), coords[:, 1] * 110540.0])
    # original node -> one contracted edge containing it.
    # VECTORISED, and the NpzFile members hoisted into locals first: indexing the NpzFile inside
    # a 300k-iteration loop re-reads/re-parses the member each time and effectively hangs.
    node2edge = np.full(coords.shape[0], -1, dtype=np.int64)
    off = z['chain_off']
    cflat = z['chain_flat']
    edge_of_elem = np.repeat(np.arange(len(z['ce_u']), dtype=np.int64), np.diff(off))
    node2edge[cflat] = edge_of_elem
    # Build the KD-tree over ROUTABLE nodes only. Nodes in dropped fragments have no edge, so
    # snapping to them yields no route (this alone caused ~7% failures). Snapping must always
    # land on a node that belongs to an edge.
    valid = np.where(node2edge >= 0)[0]
    tree = cKDTree(xy[valid])
    return gr, tree, cmap, node2edge, coords, cnodes, math.degrees(lat0), valid


def route_chunk(args):
    trips, sample_every = args
    z = np.load(CACHE)
    gr, tree, cmap, node2edge, coords, cnodes, lat0, valid = make_engine(z)
    off, flat = z['chain_off'], z['chain_flat']
    ce_u, ce_v = z['ce_u'], z['ce_v']
    cosl = math.cos(math.radians(lat0))
    counts = np.zeros((len(ce_u), NSPLIT), dtype=np.int32)
    res = []; geoms = []; ok = 0
    t0 = time.time()

    def snap(lo, la):
        _, j = tree.query([lo * 111320.0 * cosl, la * 110540.0])
        nid = int(valid[j]); e = int(node2edge[nid])
        if e < 0:
            return None
        chain = flat[off[e]:off[e + 1]]
        pos = int(np.where(chain == nid)[0][0])
        if pos <= len(chain) - 1 - pos:
            return int(ce_u[e]), chain[:pos + 1][::-1]     # nearest node -> u
        return int(ce_v[e]), chain[pos:]                   # nearest node -> v

    for (idx, olon, olat, dlon, dlat, od_m, tsplit) in trips:
        so = snap(olon, olat); sd = snap(dlon, dlat)
        if so is None or sd is None:
            res.append((idx, -1, False)); continue
        u_orig, part_o = so; v_orig, part_d = sd
        u, v = cmap[u_orig], cmap[v_orig]
        epath = []
        if u != v:
            ep = gr.get_shortest_paths(u, to=v, weights='weight', output='epath')
            epath = ep[0] if ep else []
            if not epath:
                res.append((idx, -1, False)); continue
        pts = [part_o.tolist()]; cur = u_orig
        for e in epath:
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
            if seq and seg and seq[-1] == seg[0]:
                seq.extend(seg[1:])
            else:
                seq.extend(seg)
        c = coords[seq]
        rm = float(np.sum(np.hypot(np.diff(c[:, 0]) * 111320.0 * cosl,
                                   np.diff(c[:, 1]) * 110540.0)))
        res.append((idx, int(round(rm)), True))
        ok += 1
        if len(seq) >= 2:                            # a 1-point "route" cannot be drawn
            geoms.append((idx, simplify_xy(c)))      # EVERY trip, not a sample
    # Write this worker's geometry to its own part file. Returning ~55k variable-length float
    # lists per worker would hold hundreds of MB of Python objects across 8 processes.
    part = None
    if geoms:
        import pandas as pd
        part = f"{D}/db/geom_part_{trips[0][0]}.parquet"
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
              f"p10 {np.percentile(ratio,10):.2f} p90 {np.percentile(ratio,90):.2f}   "
              f"(want ~1.2-1.5)")


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
        res, counts, part = route_chunk((sub, SAMPLE_EVERY))
        report(res, trips)
        print(f"edges with traffic: {(counts[:, NSTOT]>0).sum():,} / {len(counts):,}")
        print(f"geometry part written: {part}")
        return

    chunks = [trips[i::NPROC] for i in range(NPROC)]
    print(f"routing {len(trips):,} trips on {NPROC} processes ...", flush=True)
    import multiprocessing as mp
    ctx = mp.get_context('spawn')
    with ctx.Pool(NPROC) as pool:
        parts = pool.map(route_chunk, [([tuple(t) for t in c], SAMPLE_EVERY) for c in chunks])
    res = [x for p in parts for x in p[0]]
    counts = np.sum([p[1] for p in parts], axis=0)
    geom_parts = [p[2] for p in parts if p[2]]
    print(f"\nrouting finished in {time.time()-t0:.0f}s")
    report(res, trips)

    p.close()   # DuckDB refuses to reopen the same file with a different config (read-only -> rw)
    conn = duckdb.connect(f"{D}/db/osm.duckdb")
    rl = pd.DataFrame({'i': [r[0] for r in res],
                       'route_m': [r[1] for r in res],
                       'ok': [r[2] for r in res]}).sort_values('i')
    conn.register('df_rl', rl)
    conn.execute("CREATE OR REPLACE TABLE route_len AS SELECT * FROM df_rl")
    conn.execute(f"COPY route_len TO '{D}/platform/route_len.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)")

    conn.register('df_cnt', pd.DataFrame({'eid': np.arange(len(counts), dtype=np.int64),
                                          'n': counts[:, NSTOT].astype(np.int64),
                                          'ns': counts.tolist()}))
    # the contracted graph lives in graph.duckdb, not osm.duckdb — attach it (alias gdb, NOT `g`,
    # which is already used as the table alias in the query below)
    conn.execute(f"ATTACH '{D}/db/graph.duckdb' AS gdb (READ_ONLY)")
    conn.execute("CREATE OR REPLACE TABLE edge_geo AS "
                 "SELECT row_number() OVER () - 1 AS eid, u, v, len_m, node_ids FROM gdb.croad_edges")
    conn.execute("""CREATE OR REPLACE TABLE epts AS
      SELECT g.eid, t.k, n.lon, n.lat
      FROM edge_geo g, LATERAL (SELECT unnest(range(1, len(g.node_ids)+1)) AS k) t
      JOIN gdb.nodes n ON n.id = g.node_ids[t.k]""")
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
            try:
                os.remove(f)
            except OSError:
                pass

    print(f"\nedges with traffic : {(counts[:, NSTOT] > 0).sum():,} / {len(counts):,}")
    print(f"routed geometries  : {conn.execute('SELECT count(*) FROM routed_geom').fetchone()[0]:,}")
    for f in ('route_len', 'routed_edges', 'routed_geom'):
        fp = f"{D}/platform/{f}.parquet"
        if os.path.exists(fp):
            print(f"  {f+'.parquet':26s} {os.path.getsize(fp)/1e6:6.1f} MB")
    print(f"total {time.time()-t0:.0f}s")


if __name__ == '__main__':
    main()
