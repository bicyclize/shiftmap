// Verification: parse the browser parquet exactly as the page does, then reproduce the
// page's filter + polygon logic. Run: node tests/verify.mjs
import { parquetReadObjects, parquetMetadata } from '../vendor/hyparquet.js';
import { compressors } from '../vendor/hyparquet-compressors.js';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const here = dirname(fileURLToPath(import.meta.url));
const buf = readFileSync(join(here, '..', 'trips_paths.parquet'));
const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);

const md = parquetMetadata(ab);
console.log('num_rows:', Number(md.num_rows));

const COLS = ['day_tag','od_m','path_m','o_lon','o_lat','d_lon','d_lat','o_in_bp','d_in_bp',
              'trip_scope','bike_direct','btb','btf','rail_lvl','o_stn','d_stn','o_to_stn','d_to_stn','dur_s','path_xy'];
const rows = await parquetReadObjects({ file: ab, compressors, columns: COLS });
const D = {}; for (const c of COLS) D[c] = rows.map(r => r[c]);
console.log('rows parsed:', rows.length);

const paths = rows.filter(r => r.path_xy && r.path_xy.length >= 4);
console.log('trips WITH path_xy :', paths.length, `(${(100*paths.length/rows.length).toFixed(1)}%)`);
console.log('sample path len     :', paths[0].path_xy.length, 'coords ->', paths[0].path_xy.slice(0,6).map(v=>+v.toFixed(4)).join(','));

function apply(scope, scen, day, dmin, dmax) {
  let n = 0, inArea = 0, bd = 0, btb = 0, btf = 0;
  for (let i = 0; i < D.od_m.length; i++) {
    if (scope !== 'all' && D.trip_scope[i] !== scope) continue;
    if (day !== 'all' && D.day_tag[i] !== day) continue;
    inArea++;
    const m = D.od_m[i]; if (m < dmin || m > dmax) continue;
    if (D.bike_direct[i]) bd++; if (D.btb[i]) btb++; if (D.btf[i]) btf++;
    if (scen !== 'any' && !D[scen][i]) continue;
    n++;
  }
  return { n, inArea, bd, btb, btf };
}

// ---- polygon logic, identical to index.html ----
function pointInPoly(p, pg){ let ins=false;
  for(let i=0,j=pg.length-1;i<pg.length;j=i++){ const [xi,yi]=pg[i],[xj,yj]=pg[j];
    if(((yi>p[1])!==(yj>p[1])) && (p[0] < (xj-xi)*(p[1]-yi)/(yj-yi)+xi)) ins=!ins; } return ins; }
function segInt(a,b,c,d){ const o=(p,q,r)=>((q[1]-p[1])*(r[0]-q[0])-(q[0]-p[0])*(r[1]-q[1]));
  const o1=o(a,b,c),o2=o(a,b,d),o3=o(c,d,a),o4=o(c,d,b); return ((o1>0)!==(o2>0))&&((o3>0)!==(o4>0)); }
function pathHits(i, pg){
  const xy = D.path_xy[i];
  const pts = (xy && xy.length>=4) ? xy : [D.o_lon[i], D.o_lat[i], D.d_lon[i], D.d_lat[i]];
  for (let k=0;k+3<pts.length;k+=2){
    const a=[pts[k],pts[k+1]], b=[pts[k+2],pts[k+3]];
    if (pointInPoly(a,pg) || pointInPoly(b,pg)) return true;
    for (let e=0;e<pg.length;e++){ if (segInt(a,b,pg[e],pg[(e+1)%pg.length])) return true; }
  }
  return false;
}
const POLY = [[19.030,47.475],[19.075,47.475],[19.075,47.520],[19.030,47.520]];
let P = {n:0,o:0,d:0,int:0,th:0,bd:0,btb:0,btf:0};
for (let i=0;i<D.od_m.length;i++){
  const oIn = pointInPoly([D.o_lon[i],D.o_lat[i]], POLY);
  const dIn = pointInPoly([D.d_lon[i],D.d_lat[i]], POLY);
  const thru = pathHits(i, POLY);
  if (!(oIn||dIn||thru)) continue;
  P.n++; P.bd+=D.bike_direct[i]?1:0; P.btb+=D.btb[i]?1:0; P.btf+=D.btf[i]?1:0;
  if (oIn&&dIn) P.int++; else if (oIn) P.o++; else if (dIn) P.d++; else P.th++;
}
console.log('o_only + internal =', (P.o+P.int).toLocaleString(), '(DuckDB origin-inside: 34,646)');
console.log('d_only + internal =', (P.d+P.int).toLocaleString(), '(DuckDB dest-inside  : 33,453)');

console.log('\n-- plain filters --');
console.log('ALL/any          :', JSON.stringify(apply('all','any','all',0,999000)));
console.log('suburb_bp/btb    :', JSON.stringify(apply('suburb_bp','btb','all',0,999000)));
console.log('\n-- polygon (inner Pest) --');
console.log('touching         :', P.n.toLocaleString());
console.log('starts inside→out:', P.o.toLocaleString());
console.log('outside→ends in  :', P.d.toLocaleString());
console.log('inside→inside    :', P.int.toLocaleString());
console.log('passes through   :', P.th.toLocaleString());
console.log('bikeable         :', P.bd.toLocaleString(), `(${(100*P.bd/P.n).toFixed(1)}%)`);
console.log('bike+train+bike  :', P.btb.toLocaleString(), `(${(100*P.btb/P.n).toFixed(1)}%)`);
console.log('bike+train+foot  :', P.btf.toLocaleString(), `(${(100*P.btf/P.n).toFixed(1)}%)`);
const t0=Date.now(); for(let i=0;i<D.od_m.length;i++) pathHits(i,POLY); console.log('\npolygon pass over all trips:', Date.now()-t0, 'ms');
