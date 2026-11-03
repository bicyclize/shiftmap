// Verify the filter-aware volume layer: do day / length filters actually change the rendered map?
// Compares screenshots by hash — a different map must produce different pixels.
import { spawn } from 'child_process';
import { mkdtempSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import { createHash } from 'crypto';

const PORT = 9336, CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const dir = mkdtempSync(join(tmpdir(), 'cdpf-'));
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
const send=(method,params={})=>new Promise(r=>{const i=++id;pend.set(i,r);ws.send(JSON.stringify({id:i,method,params}));});
await new Promise(r=>ws.addEventListener('open',r,{once:true}));
await send('Runtime.enable'); await send('Page.enable');
await send('Page.navigate',{url:'http://localhost:8765/'});
for(let i=0;i<90;i++){ await new Promise(r=>setTimeout(r,1500));
  const q=await send('Runtime.evaluate',{returnByValue:true,expression:`!document.getElementById('loading')`});
  if(q.result?.result?.value===true) break; }
await new Promise(r=>setTimeout(r,7000));   // let the routed volume layer draw

const ev = async (expr) => (await send('Runtime.evaluate',{returnByValue:true, expression: expr})).result.result.value;
const shot = async (f) => { const s = await send('Page.captureScreenshot',{format:'png'});
  const b = Buffer.from(s.result.data,'base64'); writeFileSync(f,b);
  return createHash('md5').update(b).digest('hex').slice(0,10); };

const state = async () => JSON.parse(await ev(`JSON.stringify({
  n: document.getElementById('n').textContent,
  note: document.getElementById('note').textContent,
  legend: (document.getElementById('legend').innerText||'').replace(/\\n+/g,' | ') })`));

console.log('=== BASELINE (all trips) ===');
let s = await state(); console.log(' n:', s.n); console.log(' legend:', s.legend);
const h0 = await shot('/tmp/f_all.png'); console.log(' map hash:', h0);

console.log('\n=== DAY = 08 ===');
await ev(`(()=>{const d=document.getElementById('day'); d.value='08'; d.dispatchEvent(new Event('change'));})()`);
await new Promise(r=>setTimeout(r,4000));
s = await state(); console.log(' n:', s.n); console.log(' legend:', s.legend);
const h1 = await shot('/tmp/f_day08.png'); console.log(' map hash:', h1);

console.log('\n=== BACK TO ALL DAYS, LENGTH 5-8 km ===');
await ev(`(()=>{const d=document.getElementById('day'); d.value='all'; d.dispatchEvent(new Event('change'));
                 document.querySelector('.chip[data-band="5,8"]').click();})()`);
await new Promise(r=>setTimeout(r,4000));
s = await state(); console.log(' n:', s.n); console.log(' legend:', s.legend);
const h2 = await shot('/tmp/f_5to8.png'); console.log(' map hash:', h2);

console.log('\n=== VERDICT ===');
console.log(` day filter changed the map : ${h0 !== h1}`);
console.log(` length filter changed map  : ${h0 !== h2}`);
if (h0===h1 || h0===h2) console.log(' !! a filter did NOT change the rendered map');

const bad = evs.filter(e=>e.method==='Network.responseReceived'&&e.params.response.status>=400);
console.log('\nHTTP >=400:', bad.length ? bad.map(b=>b.params.response.status+' '+b.params.response.url.slice(0,80)).join(' | ') : '(none)');
ws.close(); proc.kill(); process.exit(0);
