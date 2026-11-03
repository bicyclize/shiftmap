// Fetch two things the routing fix needs, from Overpass, with mirror fallback:
//   1. Budapest district (kerület) boundaries  -> district coverage check
//   2. OSM turn restrictions (type=restriction) -> the illegal-left-turn fix
// Writes simplified districts to disk so the big geometry payload never crosses the wire.
import { writeFileSync, readFileSync, existsSync } from 'fs';

const OUT_DIST = '/Users/peterbiczok/.hermes/cache/scratch/buda_districts.json';
const OUT_REST = '/Users/peterbiczok/.hermes/cache/scratch/buda_restrictions.json';
const TOL = 0.0005;                                // ~40 m
const UA = 'Bicyclize-mobility-analysis/1.0 (peter@bicyclize.com)';

const MIRRORS = [
  'https://overpass-api.de/api/interpreter',
  'https://overpass.kumi.systems/api/interpreter',
  'https://overpass.private.coffee/api/interpreter',
  'https://overpass.osm.ch/api/interpreter',
  'https://maps.mail.ru/osm/tools/overpass/api/interpreter',
];

async function overpass(q) {
  let last = '';
  for (let attempt = 0; attempt < 3; attempt++) {
    for (const m of MIRRORS) {
      try {
        const r = await fetch(m, {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'User-Agent': UA, 'Accept': 'application/json' },
          body: 'data=' + encodeURIComponent(q),
        });
        const t = await r.text();
        if (r.status === 200 && t.trimStart().startsWith('{')) {
          const j = JSON.parse(t);
          if ((j.elements || []).length === 0 && t.length < 1000) {
            console.log(`  EMPTY from ${m.split('/')[2]}: ${t.slice(0, 260)}`);
            last = `${m.split('/')[2]} -> empty: ${t.slice(0, 120)}`;
            continue;                                  // a mirror answering "nothing" is not an answer
          }
          console.log(`  OK ${m.split('/')[2]}  ${t.length} chars, ${j.elements.length} elements`);
          return j;
        }
        last = `${m.split('/')[2]} -> HTTP ${r.status}`;
        console.log(`  retry: ${last}`);
      } catch (e) { last = `${m.split('/')[2]} -> ${e.message}`; console.log(`  retry: ${last}`); }
      await new Promise(r => setTimeout(r, 4000));
    }
  }
  throw new Error('all mirrors failed: ' + last);
}

// ---------------- 1. districts ----------------
console.log('districts:');
const dq = `[out:json][timeout:600];
(rel["boundary"="administrative"]["admin_level"="9"](47.30,18.90,47.66,19.40);
 rel["boundary"="administrative"]["admin_level"="10"](47.30,18.90,47.66,19.40););
out geom;`;                                      // NOT "out geom tags;" — that silently drops members
const dd = await overpass(dq);

const eq = (p, q) => Math.abs(p[0] - q[0]) < 1e-9 && Math.abs(p[1] - q[1]) < 1e-9;
function ringFrom(ways) {
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
function dp(pts, tol) {
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
      const dd2 = Math.hypot(px - (ax + u * dx), py - (ay + u * dy));
      if (dd2 > md) { md = dd2; mi = k; }
    }
    if (md > tol && mi > 0) { keep[mi] = 1; st.push([s, mi]); st.push([mi, e]); }
  }
  const out = []; for (let i = 0; i < pts.length; i++) if (keep[i]) out.push(pts[i]);
  return out;
}

const dists = [];
for (const e of dd.elements) {
  if (e.type !== 'relation') continue;
  const tg = e.tags || {};
  const outer = (e.members || []).filter(m => m.type === 'way' && (m.role === 'outer' || m.role === '') && m.geometry)
    .map(m => m.geometry.map(p => [p.lon, p.lat]));
  if (!outer.length) continue;
  const rings = ringFrom(outer).map(rr => dp(rr, TOL)).filter(rr => rr.length >= 4);
  if (!rings.length) continue;
  dists.push({ name: tg.name || '?', level: tg.admin_level, rings });
}
if (!dists.length) {
  const byType = {};
  for (const e of dd.elements) byType[e.type] = (byType[e.type] || 0) + 1;
  console.log('  DEBUG element types:', JSON.stringify(byType));
  for (const e of dd.elements.slice(0, 6)) {
    console.log('   ', e.type, JSON.stringify(e.tags || {}).slice(0, 160));
    if (e.members) console.log('      members:', e.members.slice(0, 4).map(m => `${m.type}/${m.role}${m.geometry ? '+geom' : ''}`).join(', '), '| total', e.members.length);
  }
}
writeFileSync(OUT_DIST, JSON.stringify(dists));
let pts = 0; for (const x of dists) for (const r of x.rings) pts += r.length;
console.log(`  districts=${dists.length} points=${pts} -> ${OUT_DIST}`);
for (const x of dists) console.log(`    lvl ${x.level}  ${x.name}  pts=${x.rings.reduce((a, b) => a + b.length, 0)}`);

// ---------------- 2. turn restrictions ----------------
console.log('\nturn restrictions:');
if (existsSync(OUT_REST)) {
  const have = JSON.parse(readFileSync(OUT_REST, 'utf8'));
  console.log(`  already fetched: ${have.length} restrictions -> ${OUT_REST} (skipping)`);
  process.exit(0);
}
const rq = `[out:json][timeout:900];
rel["type"="restriction"](47.30,18.90,47.66,19.40);
out body;`;
const rd = await overpass(rq);

const rests = [];
const counts = {};
for (const e of rd.elements) {
  if (e.type !== 'relation') continue;
  const tg = e.tags || {};
  const kind = tg.restriction || tg['restriction:motorcar'] || tg['restriction:bicycle'] || '';
  if (!kind) continue;
  const mem = e.members || [];
  const from = mem.find(m => m.role === 'from' && m.type === 'way');
  const to   = mem.find(m => m.role === 'to'   && m.type === 'way');
  const viaN = mem.find(m => m.role === 'via'  && m.type === 'node');
  const viaW = mem.find(m => m.role === 'via'  && m.type === 'way');
  if (!from || !to) continue;
  if (!viaN && !viaW) continue;                       // need a via point to place the restriction
  counts[kind] = (counts[kind] || 0) + 1;
  rests.push({ id: e.id, kind, from: from.ref, to: to.ref,
               via_node: viaN ? viaN.ref : null, via_way: viaW ? viaW.ref : null,
               except: tg.except || null });
}
writeFileSync(OUT_REST, JSON.stringify(rests));
console.log(`  restrictions=${rests.length} -> ${OUT_REST}`);
for (const [k, v] of Object.entries(counts).sort((a, b) => b[1] - a[1])) console.log(`    ${k.padEnd(22)} ${v}`);
