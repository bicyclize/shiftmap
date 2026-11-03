// Verify: (1) NO drawn trip is a straight O–D line, (2) the rail-corridor mode filter works.
// Uses the window.__map test hook to inspect the actual rendered trip layer.
import { spawn } from 'child_process';
import { mkdtempSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

const PORT = 9338, CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const dir = mkdtempSync(join(tmpdir(), 'cdpn-'));
const proc = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${dir}`,
  '--no-first-run', '--no-default-browser-check', '--use-gl=angle', '--use-angle=swiftshader',
  '--enable-unsafe-swiftshader', '--window-size=1500,950', '--hide-scrollbars', 'about:blank'], {stdio:'ignore'});
async function ver(){ for(let i=0;i<80;i++){ try{ const r=await fetch(`http://127.0.0.1:${PORT}/json/version`); if(r.ok) return r.json(); }catch(e){} await new Promise(r=>setTimeout(r,250)); } throw new Error('no chrome'); }
await ver();
let t=null;
try { t = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`,{method:'PUT'})).json(); }
catch(e){ t = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find(x=>x.type==='page'); }
const ws = new WebSocket(t.webSocketDebuggerUrl);
let id=0; const pend=new Map(); const evs=[];
ws.addEventListener('message', e => { const m=JSON.parse(e.data); if(m.id&&pend.has(m.id)){pend.get(m.id)(m);pend.delete(m.id);} else evs.push(m); });
const send=(m,p={})=>new Promise(r=>{const i=++id;pend.set(i,r);ws.send(JSON.stringify({id:i,method:m,params:p}));});
await new Promise(r=>ws.addEventListener('open',r,{once:true}));
await send('Runtime.enable'); await send('Page.enable');
await send('Page.navigate',{url:'http://localhost:8765/'});
for(let i=0;i<120;i++){ await new Promise(r=>setTimeout(r,1500));
  const q=await send('Runtime.evaluate',{returnByValue:true,expression:`!document.getElementById('loading')`});
  if(q.result?.result?.value===true) break; }
await new Promise(r=>setTimeout(r,8000));
const ev = async x => (await send('Runtime.evaluate',{returnByValue:true,expression:x})).result.result.value;

console.log('note:', (await ev(`document.getElementById('note').textContent`)).slice(0,200));

// ---- 1. is any drawn feature a straight O–D line? ----
// A real route deviates from its own endpoint-to-endpoint chord. An O–D line has zero deviation.
const shape = await ev(`(()=>{
  const src = window.__map.getSource('trips');
  const feats = (src && (src._data || src.serialize?.().data))?.features || [];
  let n=0, maxDev=0, twoPt=0;
  const MLON = 111320*Math.cos(47.5*Math.PI/180), MLAT = 110574;
  for (const f of feats){
    const c = f.geometry.coordinates; if (!c || c.length < 2) continue;
    n++;
    if (c.length === 2) twoPt++;
    const ax=c[0][0]*MLON, ay=c[0][1]*MLAT;
    const bx=c[c.length-1][0]*MLON, by=c[c.length-1][1]*MLAT;
    const dx=bx-ax, dy=by-ay, l2=dx*dx+dy*dy;
    let dev=0;
    for (let k=1;k<c.length-1;k++){
      const px=c[k][0]*MLON, py=c[k][1]*MLAT;
      const t = l2 ? Math.max(0,Math.min(1,((px-ax)*dx+(py-ay)*dy)/l2)) : 0;
      dev = Math.max(dev, Math.hypot(px-(ax+t*dx), py-(ay+t*dy)));
    }
    if (dev > maxDev) maxDev = dev;
  }
  // median points per drawn feature
  const lens = feats.map(f=>f.geometry.coordinates.length).sort((a,b)=>a-b);
  return JSON.stringify({features:n, twoPointFeatures:twoPt,
    medianPoints: lens[Math.floor(lens.length/2)], maxDeviationM: Math.round(maxDev)});
})()`);
console.log('\n=== drawn trip geometry ===');
console.log(shape);

// ---- 2. legend Road / Rail toggle ----
const legendRows = async () => JSON.parse(await ev(`JSON.stringify(
  [...document.querySelectorAll('#legend [data-mode]')].map(r=>({mode:r.dataset.mode,
    label:r.querySelector('.lb').textContent, count:r.querySelector('.ct').textContent,
    off:r.classList.contains('off')})))`));
const nTotal = async () => await ev(`document.getElementById('n').textContent`);
console.log('\n=== legend road/rail rows ===');
for (const r of await legendRows())
  console.log(` ${r.mode.padEnd(6)} ${r.label.padEnd(16)} ${r.count.padStart(9)}   ${r.off?'HIDDEN':'shown'}`);
console.log(' total shown :', await nTotal());
await ev(`document.querySelector('#legend [data-mode="road"]').click()`);
await new Promise(r=>setTimeout(r,4000));
console.log('\n hide ROAD          ->', await nTotal(), '(expect rail only)');
await ev(`document.querySelector('#legend [data-mode="road"]').click()`);
await new Promise(r=>setTimeout(r,4000));
console.log(' restore ROAD       ->', await nTotal(), '(expect all)');
const s = await send('Page.captureScreenshot',{format:'png'});
writeFileSync('/tmp/mode_rail.png', Buffer.from(s.result.data,'base64'));
console.log('\nscreenshot -> /tmp/mode_rail.png');
const bad = evs.filter(e=>e.method==='Network.responseReceived'&&e.params.response.status>=400);
console.log('HTTP >=400:', bad.length ? bad.map(b=>b.params.response.status+' '+b.params.response.url.slice(0,70)).join(' | ') : '(none)');
ws.close(); proc.kill(); process.exit(0);
