// Fetch the COORDINATES of the turn-restriction via nodes.
//
// The graph builder assigns its own synthetic node ids (deduped by rounded lat/lon), so an OSM
// via-node id means nothing to it. We need each via node's lat/lon to map it back to a graph node.
// `out body; >; out skel qt;` recurses down into members, which yields the node coordinates.
import { writeFileSync, existsSync, readFileSync } from 'fs';

const REST = '/Users/peterbiczok/.hermes/cache/scratch/buda_restrictions.json';
const OUT  = '/Users/peterbiczok/.hermes/cache/scratch/buda_via_coords.json';
const UA = 'Bicyclize-mobility-analysis/1.0 (peter@bicyclize.com)';
const MIRRORS = [
  'https://overpass-api.de/api/interpreter',
  'https://overpass.kumi.systems/api/interpreter',
  'https://overpass.private.coffee/api/interpreter',
  'https://overpass.osm.ch/api/interpreter',
];

if (existsSync(OUT)) { console.log('already fetched ->', OUT); process.exit(0); }
const restrictions = JSON.parse(readFileSync(REST, 'utf8'));
const want = new Set(restrictions.filter(r => r.via_node).map(r => r.via_node));
console.log(`restrictions ${restrictions.length}, distinct via nodes ${want.size}`);

// Ask only for the node ids we need — far smaller than recursing the whole relations.
const ids = [...want].join(',');
const Q = `[out:json][timeout:900];
node(id:${ids});
out;`;

async function overpass(q) {
  let last = '';
  for (let a = 0; a < 3; a++) {
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
          if ((j.elements || []).length) { console.log(`  OK ${m.split('/')[2]}: ${j.elements.length} nodes`); return j; }
          last = `${m.split('/')[2]} -> 0 elements`; 
        } else last = `${m.split('/')[2]} -> HTTP ${r.status}`;
        console.log('  retry:', last);
      } catch (e) { last = `${m.split('/')[2]} -> ${e.message}`; console.log('  retry:', last); }
      await new Promise(r => setTimeout(r, 3000));
    }
  }
  throw new Error('all mirrors failed: ' + last);
}

const d = await overpass(Q);
const out = {};
for (const e of d.elements) {
  if (e.type === 'node' && e.lat != null) out[e.id] = [e.lon, e.lat];
}
writeFileSync(OUT, JSON.stringify(out));
console.log(`via nodes with coordinates: ${Object.keys(out).length} of ${want.size} -> ${OUT}`);
const missing = [...want].filter(i => !out[i]);
console.log('missing:', missing.length, missing.slice(0, 8));
