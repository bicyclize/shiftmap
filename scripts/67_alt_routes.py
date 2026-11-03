"""ALTERNATIVE PATHS — how each scenario trip COULD have been done.

  bike_direct        one bike leg            O -> D
  bike+train+bike    bike O -> station, train station -> station, bike station -> D
  bike+train+foot    bike O -> station, train station -> station, foot station -> D

Legs are ROUTED, never sketched: bike and foot legs on the bike network built by 66_bike_graph.py
(roads + the separate cycleway/path/footway ways, costed by TIME so calm streets beat short fast
ones), the train leg on the passenger rail graph from 47_rail_graph.py. Station ends carry the
station's id and coordinates so the app can put a dot there.

A leg that cannot be routed is NOT invented — the whole alternative is dropped for that trip and
counted, so the coverage figure stays honest.

SNAPPING. Both graphs are CONTRACTED: degree-2 chains were merged into single edges, so a graph
vertex is a chain END, not every point. Two traps follow, and both are silent:
  * the contracted vertex set still contains every swallowed interior node as an ISOLATED vertex
    (798,929 of them in the bike graph), so a nearest-node snap lands on a vertex with no edges and
    every route "cannot reach some vertices";
  * snapping to the nearest chain END can be kilometres off on a long chain — on the rail network a
    station sat 8 km from its own line, which silently killed every bike+train alternative.
So snap onto the chain and carry the PARTIAL CHAIN into the leg geometry.

Writes platform/alt_routes.parquet (one row per leg), alt_summary.parquet, alt_stations.parquet.
"""
import duckdb, math, os, sys, time

D = ("/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/"
     "Transport analysis")
os.chdir(D)
OUT = "platform"
ACCESS_M = 2500.0          # origin -> station, by bike
EGRESS_M = 1300.0          # station -> destination, on foot
SNAP_MAX_M = 2000.0
LAT0 = math.radians(47.5)
M_LON = 111320.0 * math.cos(LAT0)
M_LAT = 110540.0
COLS = ["i", "scen", "leg", "mode", "xy", "s_stn", "e_stn", "s_lon", "s_lat", "e_lon", "e_lat"]
TYPES = ["BIGINT", "VARCHAR", "INTEGER", "VARCHAR", "DOUBLE[]", "VARCHAR", "VARCHAR",
         "DOUBLE", "DOUBLE", "DOUBLE", "DOUBLE"]


def load40():
    """40_route_turns holds the shared geometry simplifier (its filename starts with a digit, so a
    plain import cannot reach it)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("r40", os.path.join(D, "scripts/40_route_turns.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GW = {}
CACHE = {}


def make_net(np, nid, nlon, nlat, us_raw, vs_raw, weights, chains_raw, cKDTree, ig):
    """Bundle a contracted graph with everything snapping needs.

    chains_raw[e] lists the ORIGINAL node ids of chain e (endpoint first). Positions are indices into
    the coordinate arrays; `flat` is every chain node, which is what we snap against."""
    n = len(nid)
    imap = np.full(int(max(nid)) + 1, -1, dtype=np.int64)
    imap[np.asarray(nid, dtype=np.int64)] = np.arange(n, dtype=np.int64)
    coords = np.column_stack([np.asarray(nlon, dtype=np.float64),
                              np.asarray(nlat, dtype=np.float64)])
    chains = [imap[np.asarray(c, dtype=np.int64)] for c in chains_raw]
    us = imap[np.asarray(us_raw, dtype=np.int64)]
    vs = imap[np.asarray(vs_raw, dtype=np.int64)]
    lens = np.array([len(c) for c in chains])
    flat = np.concatenate(chains) if len(chains) else np.zeros(0, dtype=np.int64)
    node2edge = np.full(n, -1, dtype=np.int64)
    node2edge[flat] = np.repeat(np.arange(len(chains), dtype=np.int64), lens)
    xy = np.column_stack([coords[:, 0] * M_LON, coords[:, 1] * M_LAT])
    gr = ig.Graph(n=n, edges=list(zip(us.tolist(), vs.tolist())), directed=False)
    gr.es["w"] = np.asarray(weights, dtype=np.float64).tolist()
    return {"n": n, "coords": coords, "xy": xy, "imap": imap, "chains": chains, "us": us, "vs": vs,
            "flat": flat, "node2edge": node2edge, "tree": cKDTree(xy[flat]), "gr": gr}


def _init():
    """Build both networks once per worker process (spawn re-imports this module in every child)."""
    m40 = load40()
    import igraph as ig
    import numpy as np
    from scipy.spatial import cKDTree
    GW.update(m40=m40, np=np, ig=ig, cKDTree=cKDTree)

    # the bike network lives as PARQUET — reading a database table would take a lock on graph.duckdb
    pq = duckdb.connect()
    bn = pq.execute(f"SELECT id, lon, lat FROM read_parquet('{D}/db/tgbike_nodes.parquet') "
                    f"ORDER BY id").fetchall()
    be = pq.execute(f"SELECT eid, u, v, len_m, speed, nodes FROM "
                    f"read_parquet('{D}/db/tgbike_edges.parquet') ORDER BY eid").fetchall()
    blen = np.array([r[3] for r in be], dtype=np.float64)
    bspd = np.array([r[4] for r in be], dtype=np.float64)
    # cost by TIME, not distance: a bike route should trade a longer calm street for a short fast one
    GB = make_net(np, [r[0] for r in bn], [r[1] for r in bn], [r[2] for r in bn],
                  [r[1] for r in be], [r[2] for r in be], blen / (bspd / 3.6), [r[5] for r in be],
                  cKDTree, ig)
    # a foot leg walks the same network (it holds the footway/pedestrian ways) at walking speed, so it
    # is effectively distance-based rather than bike-fast-road-based
    GB["gr"].es["w_bike"] = GB["gr"].es["w"]
    GB["gr"].es["w_foot"] = (blen / 4.8 * 3.6).tolist()
    GW["bike"] = GB

    # the rail network, same construction (its tables live in graph.duckdb, not in parquet)
    rcon = duckdb.connect(f"{D}/db/graph.duckdb", read_only=True)
    rn = rcon.execute("SELECT id, lon, lat FROM tgrail_nodes ORDER BY id").fetchall()
    rr = rcon.execute("SELECT eid, u, v, len_m, nodes FROM tgrail_edges ORDER BY eid").fetchall()
    rail = make_net(np, [r[0] for r in rn], [r[1] for r in rn], [r[2] for r in rn],
                    [r[1] for r in rr], [r[2] for r in rr], [r[3] for r in rr],
                    [r[4] for r in rr], cKDTree, ig)
    # the guided systems are physically separate (47_rail_graph.py), so keep one tree PER system and
    # pick the system that fits both ends best
    comp = rail["gr"].components()
    cm = np.array(comp.membership, dtype=np.int64)
    rail["ctrees"] = {}
    for cv in sorted(set(cm[rail["flat"]].tolist())):
        sel = rail["flat"][cm[rail["flat"]] == cv]
        if len(sel) >= 10:
            rail["ctrees"][cv] = (cKDTree(rail["xy"][sel]), sel)
    GW["rail"] = rail

    ocon = duckdb.connect(f"{D}/db/osm.duckdb", read_only=True)
    st = ocon.execute("SELECT sid, stn_name, lat, lon FROM stations").fetchall()
    GW["stations"] = st
    GW["stree"] = cKDTree(np.array([[r[3] * M_LON, r[2] * M_LAT] for r in st]))
    GW["NSYSTEMS"] = len(rail["ctrees"])
    return True


def snap_net(N, lon, lat, tree=None):
    """Nearest point ON the network -> (distance, chain-end vertex, partial chain endpoint->point).

    The partial chain matters: the network is contracted, so the nearest chain END can be far away
    along a long chain, and dropping it would start every leg at the wrong junction."""
    np = GW["np"]
    tree = tree or N["tree"]
    d, j = tree.query([lon * M_LON, lat * M_LAT])
    if d > SNAP_MAX_M:
        return None
    p = int(N["flat"][j])
    e = int(N["node2edge"][p])
    if e < 0:
        return None
    ch = N["chains"][e]
    pos = int(np.where(ch == p)[0][0])
    if pos <= len(ch) - 1 - pos:
        return d, int(N["us"][e]), ch[:pos + 1]        # u end -> snapped point
    return d, int(N["vs"][e]), ch[pos:][::-1]          # v end -> snapped point


def route_between(N, va, vb, wname):
    """Cached chain of coordinates from vertex va to vertex vb."""
    if va == vb:
        return []
    key = (id(N["gr"]), va, vb, wname)
    if key in CACHE:
        return CACHE[key]
    coords = []
    try:
        ep = N["gr"].get_shortest_paths(va, to=vb, weights=wname, output="epath")
    except Exception:
        ep = None
    if ep and ep[0]:
        seq = []
        cur = va
        for e in ep[0]:
            ch = N["chains"][e]
            if N["us"][e] == cur:
                seq.extend(ch); cur = int(N["vs"][e])
            else:
                seq.extend(ch[::-1]); cur = int(N["us"][e])
        coords = N["coords"][GW["np"].asarray(seq, dtype="int64")]
        coords = [tuple(c) for c in coords]
    if len(CACHE) < 120000:
        CACHE[key] = coords
    return coords


def leg_net(N, alon, alat, blon, blat, wname, tree=None):
    """Full leg geometry: origin -> network -> destination, partial chains included."""
    np = GW["np"]
    A = snap_net(N, alon, alat, tree)
    B = snap_net(N, blon, blat, tree)
    if A is None or B is None:
        return None
    _, va, pa = A
    _, vb, pb = B
    mid = route_between(N, va, vb, wname)
    if va != vb and not mid:
        return None
    pts = list(N["coords"][pa]) + list(mid) + list(N["coords"][pb])
    if len(pts) < 2:
        return None
    return GW["m40"].simplify_xy(np.array(pts, dtype=np.float64))


def bike_leg(alon, alat, blon, blat, wname="w_bike"):
    return leg_net(GW["bike"], alon, alat, blon, blat, wname)


def rail_leg(s_a, s_b):
    """Between two stations, on the single guided system that fits BOTH best."""
    a = [s_a[3] * M_LON, s_a[2] * M_LAT]
    b = [s_b[3] * M_LON, s_b[2] * M_LAT]
    best = None
    for cv, (tree, sel) in GW["rail"]["ctrees"].items():
        da, ja = tree.query(a)
        db_, jb = tree.query(b)
        if da > SNAP_MAX_M or db_ > SNAP_MAX_M:
            continue
        if best is None or da + db_ < best[0]:
            best = (da + db_, cv)
    if best is None:
        return None
    tree, sel = GW["rail"]["ctrees"][best[1]]
    N = GW["rail"]
    d1, j1 = tree.query(a)
    p1 = int(sel[j1])
    d2, j2 = tree.query(b)
    p2 = int(sel[j2])
    def one(p):
        e = int(N["node2edge"][p])
        if e < 0:
            return None
        np = GW["np"]
        ch = N["chains"][e]
        pos = int(np.where(ch == p)[0][0])
        if pos <= len(ch) - 1 - pos:
            return int(N["us"][e]), ch[:pos + 1]
        return int(N["vs"][e]), ch[pos:][::-1]
    A = one(p1); B = one(p2)
    if A is None or B is None:
        return None
    va, pa = A
    vb, pb = B
    mid = route_between(N, va, vb, "w")
    if va != vb and not mid:
        return None
    np = GW["np"]
    pts = list(N["coords"][pa]) + list(mid) + list(N["coords"][pb])
    if len(pts) < 2:
        return None
    return GW["m40"].simplify_xy(np.array(pts, dtype=np.float64))


def nearest_station(lon, lat, max_m):
    d, j = GW["stree"].query([lon * M_LON, lat * M_LAT])
    return None if d > max_m else GW["stations"][int(j)]


def build(t):
    i, olon, olat, dlon, dlat, scen = t
    if scen == "bike_direct":
        p = bike_leg(olon, olat, dlon, dlat)
        if p is None:
            return None
        return [(i, scen, 0, "bike", p, None, None, olon, olat, dlon, dlat)]
    so = nearest_station(olon, olat, ACCESS_M)
    sd = nearest_station(dlon, dlat, ACCESS_M if scen == "btb" else EGRESS_M)
    if so is None or sd is None:
        return None
    p1 = bike_leg(olon, olat, so[3], so[2])
    p2 = rail_leg(so, sd)
    p3 = bike_leg(sd[3], sd[2], dlon, dlat, "w_bike" if scen == "btb" else "w_foot")
    if not (p1 and p2 and p3):
        return None
    return [(i, scen, 0, "bike", p1, None, so[0], olon, olat, so[3], so[2]),
            (i, scen, 1, "train", p2, so[0], sd[0], so[3], so[2], sd[3], sd[2]),
            (i, scen, 2, "bike" if scen == "btb" else "foot", p3, sd[0], None,
             sd[3], sd[2], dlon, dlat)]


def worker(chunk):
    """Top-level function: `multiprocessing` spawn has to be able to pickle this."""
    rows, stats = [], {}
    for t in chunk:
        try:
            legs = build(tuple(t))
        except Exception:
            legs = None
        k = (t[5], "ok" if legs else "drop")
        stats[k] = stats.get(k, 0) + 1
        if legs:
            rows.extend(legs)
    return rows, stats


def main():
    t0 = time.time()
    NPROC = int(os.environ.get("NPROC", "8"))
    LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 0

    con = duckdb.connect(f"{D}/db/osm.duckdb", read_only=True)
    print("loading trips ...", flush=True)
    rows = con.execute(f"""
      SELECT row_number() OVER () - 1 AS i, o_lon, o_lat, d_lon, d_lat, bike_direct, btb, btf
      FROM read_parquet('{OUT}/trips_attrs.parquet')
    """).fetchall()
    jobs = []
    for i, ol, oa, dl, da, bd, btb, btf in rows:
        if bd:  jobs.append((i, ol, oa, dl, da, "bike_direct"))
        if btb: jobs.append((i, ol, oa, dl, da, "btb"))
        if btf: jobs.append((i, ol, oa, dl, da, "btf"))
    if LIMIT:
        jobs = jobs[:LIMIT]
    print(f"jobs: {len(jobs):,}  (one per qualifying scenario)", flush=True)

    chunks = [[tuple(j) for j in jobs[k::NPROC]] for k in range(NPROC)]
    import multiprocessing as mp
    ctx = mp.get_context("spawn")
    all_rows, all_stats = [], {}
    with ctx.Pool(NPROC, initializer=_init) as pool:
        for n, (rr, st) in enumerate(pool.imap_unordered(worker, chunks), 1):
            all_rows.extend(rr)
            for k, v in st.items():
                all_stats[k] = all_stats.get(k, 0) + v
            print(f"  chunk {n}/{NPROC}: {len(rr):,} legs  ({time.time()-t0:.0f}s)", flush=True)

    print(f"\nlegs routed: {len(all_rows):,}   ({time.time()-t0:.0f}s)", flush=True)
    for k in sorted(all_stats):
        print(f"   {k[0]:12s} {k[1]:5s} {all_stats[k]:,}", flush=True)

    import numpy as np
    by = {}
    for r in all_rows:
        a = np.array(r[4], dtype=np.float64).reshape(-1, 2)
        m = float(np.sum(np.hypot(np.diff(a[:, 0]) * M_LON, np.diff(a[:, 1]) * M_LAT))) if len(a) > 1 else 0.0
        d = by.setdefault((r[0], r[1]), {"bike": 0.0, "train": 0.0, "foot": 0.0, "n": 0})
        d[r[3]] = d.get(r[3], 0.0) + m
        d["n"] += 1

    w = duckdb.connect()
    w.execute(f"CREATE OR REPLACE TABLE ar({','.join(c + ' ' + t for c, t in zip(COLS, TYPES))})")
    w.executemany(f"INSERT INTO ar VALUES ({','.join('?' * len(COLS))})", all_rows)
    w.execute(f"COPY ar TO '{OUT}/alt_routes.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)")
    w.execute("CREATE OR REPLACE TABLE asum(i BIGINT, scen VARCHAR, bike_m DOUBLE, train_m DOUBLE, "
              "foot_m DOUBLE, n_legs INTEGER)")
    w.executemany("INSERT INTO asum VALUES (?,?,?,?,?,?)",
                  [(i, s, d["bike"], d["train"], d["foot"], d["n"]) for (i, s), d in by.items()])
    w.execute(f"COPY asum TO '{OUT}/alt_summary.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)")
    st = duckdb.connect(f"{D}/db/osm.duckdb", read_only=True).execute(
        "SELECT sid, stn_name, lon, lat FROM stations ORDER BY sid").df()
    w.register("df_st", st)
    w.execute(f"COPY df_st TO '{OUT}/alt_stations.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)")

    print(f"alt_routes: {len(all_rows):,} legs, {len(by):,} trip-alternatives")
    for f in ("alt_routes.parquet", "alt_summary.parquet", "alt_stations.parquet"):
        print(f"  {f:26s} {os.path.getsize(f'{OUT}/{f}')/1e6:.1f} MB")
    print(f"total {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
