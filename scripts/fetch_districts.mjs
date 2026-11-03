// Fetch Budapest district (kerület) boundaries from Overpass and write a SIMPLIFIED polygon file.
// Pure Node: no browser, no key. Simplification happens here so the raw payload never leaves the box.
import { writeFileSync } from 'fs';

const OUT = '/Users/peterbiczok/.hermes/cache/scratch/buda_districts.json';
const TOL = 0.0005;          // ~40 m — plenty for assigning a point to a district

const Q = `[out:json][timeout:600];
(rel["boundary"="administrative"]["admin_level"="9"](47.30,18.90,47.66,19.40);
 rel["boundary"="administrative"]["admin_level"="10"](47.30,18.90,47.66,19.40););
out geom tags;`;

const res = await fetch('https://overpass-api.de/api/interpreter', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/x-www-form-urlencoded',
    // Overpass returns 406 to requests without a real User-Agent
    'User-Agent': 'Bicyclize-mobility-analysis/1.0 (peter@bicyclize.com)',
    'Accept': 'application/json',
  },
  body: 'data=' + encodeURIComponent(Q),
});
const txt = await res.text();
console.log('HTTP', res.status, txt.length, 'chars');
if (res.status !== 200) { console.log(txt.slice(0, 400)); process.exit(1); }
const d = JSON.parse(txt);

const eq = (p, q) => Math.abs(p[0] - q[0]) < 1e-9 && Math.abs(p[1] - q[1]) < 1e-9;
function ringFrom(ways) {                        // stitch member ways into closed rings
  const rem = ways.slice(), rings = [];
  while (rem.length) {
    let cur = rem.shift().slice(), ch = true;
    while (ch) {
      ch = false;
      for (let i = 0; i < rem.length; i++) {
        const w = rem[i], a = cur[cur.length - 1];
        if (eq(a, w[0])) { cur = cur.concat(w.slice(1)); rem.splice(i, 1); ch = true; break; }
        if (eq(a, w[w.length - 1])) { cur = cur.concat(w.slice(0, -1).reverse()); rem.splice(i, 1); ch = true; break; }
      }
    }
    rings.push(cur);
  }
  return rings;
}
function dp(pts, tol) {                          // Douglas-Peucker
  if (pts.length < 3) return pts;
  const keep = new Uint8Array(pts.length); keep[0] = 1; keep[pts.length - 1] = 1;
  const st = [[0, pts.length - 1]];
  while (st.length) {
    const [s, e] = st.pop(); let md = -1, mi = -1;
    const ax = pts[s][0], ay = pts[s][1], bx = pts[e][0], by = pts[e][1];
    const dx = bx - ax, dy = by - ay, l2 = dx * dx + dy * dy;
    for (let k = s + 1; k < e; k++) {
      const px = pts[k][0], py = pts[k][1];
      const u = l2 ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / l2)) : 0;
      const dd = Math.hypot(px - (ax + u * dx), py - (ay + u * dy));
      if (dd > md) { md = dd; mi = k; }
    }
    if (md > tol && mi > 0) { keep[mi] = 1; st.push([s, mi]); st.push([mi, e]); }
  }
  const out = []; for (let i = 0; i < pts.length; i++) if (keep[i]) out.push(pts[i]);
  return out;
}

const out = [];
for (const e of d.elements) {
  if (e.type !== 'relation') continue;
  const tg = e.tags || {};
  const outer = (e.members || []).filter(m => m.type === 'way' && (m.role === 'outer' || m.role === '') && m.geometry)
    .map(m => m.geometry.map(p => [p.lon, p.lat]));
  if (!outer.length) continue;
  const rings = ringFrom(outer).map(rr => dp(rr, TOL)).filter(rr => rr.length >= 4);
  if (!rings.length) continue;
  out.push({ name: tg.name || '?', level: tg.admin_level, rings });
}

writeFileSync(OUT, JSON.stringify(out));
let pts = 0; for (const x of out) for (const r of x.rings) pts += r.length;
console.log(`relations with polygons: ${out.length}   points after simplify: ${pts}   ${OUT}`);
for (const x of out) console.log(`  level ${x.level}  ${x.name}  rings=${x.rings.length} pts=${x.rings.reduce((a, b) => a + b.length, 0)}`);
