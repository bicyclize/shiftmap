// Verify the flow layer: parse flows.parquet as the page does and replicate renderFlow().
import { parquetReadObjects } from '../vendor/hyparquet.js';
import { compressors } from '../vendor/hyparquet-compressors.js';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
const here = dirname(fileURLToPath(import.meta.url));
const buf = readFileSync(join(here, '..', 'flows.parquet'));
const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);

const COLS = ['n_all','n_bp','n_sbp','n_sl','kind','cls','xy'];
const rows = await parquetReadObjects({ file: ab, compressors, columns: COLS });
console.log('flow ways parsed :', rows.length.toLocaleString());

const FL = {}; for (const c of COLS) FL[c] = rows.map(r => typeof r[c]==='bigint' ? Number(r[c]) : r[c]);

function mixHex(c1,c2,u){ const p=h=>[parseInt(h.slice(1,3),16),parseInt(h.slice(3,5),16),parseInt(h.slice(5,7),16)];
  const A=p(c1),B=p(c2); return 'rgb('+A.map((v,i)=>Math.round(v+(B[i]-v)*u)).join(',')+')'; }
function flowColor(t){ const s=[[0,'#3b4cc0'],[0.35,'#39a0c9'],[0.7,'#f2c14e'],[1,'#d73027']];
  for(let i=0;i<s.length-1;i++){ const a=s[i][0],b=s[i+1][0]; if(t<=b) return mixHex(s[i][1],s[i+1][1],(t-a)/((b-a)||1)); }
  return s[s.length-1][1]; }

function renderFlow(key){
  const N = FL[key] || FL.n_all;
  let maxN = 1, sum = 0; for (let i=0;i<N.length;i++){ if (N[i] > maxN) maxN = N[i]; sum += N[i]; }
  const feats = [];
  for (let i=0;i<N.length;i++){
    const n = N[i]; if (!n) continue;
    const xy = FL.xy[i]; if (!xy || xy.length < 4) continue;
    const c=[]; for (let k=0;k+1<xy.length;k+=2) c.push([xy[k],xy[k+1]]);
    const t = Math.sqrt(n / maxN);
    feats.push({w: 0.45 + 9.5*t, op: 0.22 + 0.70*t, col: flowColor(t), n});
  }
  let minN = Infinity; for (let i=0;i<N.length;i++) if (N[i]>0 && N[i]<minN) minN = N[i];
  return {feats, maxN, sum, minN};
}

for (const [key,label] of [['n_all','all'],['n_bp','budapest'],['n_sbp','suburb_bp'],['n_sl','suburb_local']]){
  const r = renderFlow(key);
  const narrow = r.feats.filter(f=>f.w < 1.5).length, wide = r.feats.filter(f=>f.w > 6).length;
  let wmax = 0; for (const f of r.feats) if (f.w > wmax) wmax = f.w;
  console.log(`${label.padEnd(13)} ways=${String(r.feats.length).padStart(7)}  trips/way min=${String(r.minN).padStart(4)} max=${String(r.maxN).padStart(5)}  widths ${r.feats[0].w.toFixed(1)}..${wmax.toFixed(1)}px  (thin ${narrow}, thick ${wide})`);
}
const sample = renderFlow('n_all').feats.sort((a,b)=>b.n-a.n)[0];
console.log('\nbusiest segment:', JSON.stringify({trips: sample.n, width_px: +sample.w.toFixed(2), opacity: +sample.op.toFixed(2), colour: sample.col}));
console.log('total trips-on-ways (sum, all scopes):', renderFlow('n_all').sum.toLocaleString());
