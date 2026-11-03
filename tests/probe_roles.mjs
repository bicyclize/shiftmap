// Verify: (1) legend role toggles re-CALCULATE the left panel, (2) clicking a road selects it
// and keeps only trips routed along it.
import { spawn } from 'child_process';
import { mkdtempSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

const PORT = 9337, CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const dir = mkdtempSync(join(tmpdir(), 'cdpr-'));
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
for(let i=0;i<90;i++){ await new Promise(r=>setTimeout(r,1500));
  const q=await send('Runtime.evaluate',{returnByValue:true,expression:`!document.getElementById('loading')`});
  if(q.result?.result?.value===true) break; }
await new Promise(r=>setTimeout(r,7000));
const ev = async x => (await send('Runtime.evaluate',{returnByValue:true,expression:x})).result.result.value;
const shot = async f => { const s=await send('Page.captureScreenshot',{format:'png'});
  writeFileSync(f, Buffer.from(s.result.data,'base64')); };
const st = async () => JSON.parse(await ev(`JSON.stringify({
  n: document.getElementById('n').textContent,
  pct: document.getElementById('pct').innerText.replace(/\\n+/g,' '),
  pn: (document.getElementById('pn')||{}).textContent,
  lines: document.getElementById('lines').value,
  legend: (document.getElementById('legend').innerText||'').replace(/\\n+/g,' | '),
  off: [...document.querySelectorAll('#legend .row.off')].map(e=>e.dataset.role),
  brk: [...document.querySelectorAll('#brk tbody tr')].map(r=>r.innerText.replace(/\\s+/g,' ').trim()),
  pbrk: [...document.querySelectorAll('#pbrk tbody tr')].map(r=>r.innerText.replace(/\\s+/g,' ').trim()),
  note: document.getElementById('note').textContent })`));

console.log('TOTAL trips =', await ev(`document.getElementById('n').textContent`));

// ---------- 1. draw an area, then toggle a role off ----------
await ev(`document.getElementById('btndraw').click()`);
async function click(x,y){
  await send('Input.dispatchMouseEvent',{type:'mousePressed',x,y,button:'left',clickCount:1});
  await send('Input.dispatchMouseEvent',{type:'mouseReleased',x,y,button:'left',clickCount:1});
  await new Promise(r=>setTimeout(r,420));
}
for (const [x,y] of [[700,220],[1120,250],[1150,650],[740,690]]) await click(x,y);
await ev(`document.getElementById('btnfin').click()`);
await new Promise(r=>setTimeout(r,4000));
let a = await st();
console.log('\n=== AREA DRAWN (all 3 roles on) ===');
console.log(' matching trips :', a.n, '|', a.pct);
console.log(' panel trips    :', a.pn);
console.log(' legend         :', a.legend);
console.log(' feasibility    :', a.brk.join(' || '));

await ev(`document.querySelector('[data-role="start"]').click()`);
await new Promise(r=>setTimeout(r,4000));
let b = await st();
console.log('\n=== "start inside" UNCHECKED ===');
console.log(' matching trips :', b.n, '|', b.pct);
console.log(' panel trips    :', b.pn);
console.log(' legend         :', b.legend);
console.log(' feasibility    :', b.brk.join(' || '));
console.log('');
console.log(' LEFT PANEL RECALCULATED :', a.n !== b.n);
console.log(`   matching trips ${a.n} -> ${b.n}`);
await shot('/tmp/roles_off.png');

// restore + clear
await ev(`document.querySelector('[data-role="start"]').click()`);
await ev(`document.getElementById('btnclear').click()`);
await new Promise(r=>setTimeout(r,3000));

// ---------- 2. click a road segment ----------
console.log('\n=== CLICK A ROAD (segment selection) ===');
let before = await st();
await click(900, 470);
await new Promise(r=>setTimeout(r,5000));
let c = await st();
console.log(' before      :', before.n, ' trips, mode', before.lines);
console.log(' after click :', c.n, ' trips, mode', c.lines);
console.log(' note        :', c.note.slice(0,150));
console.log(' SEGMENT SELECTION WORKS :', before.n !== c.n && c.lines === 'trips');
await shot('/tmp/segment_selected.png');
// click the SAME road again to deselect
await click(900, 470);
await new Promise(r=>setTimeout(r,4000));
let d = await st();
console.log(' after clicking the same road again:', d.n, 'trips, mode', d.lines);
console.log(' TOGGLES OFF :', d.n === before.n);

const bad = evs.filter(e=>e.method==='Network.responseReceived'&&e.params.response.status>=400);
console.log('\nHTTP >=400:', bad.length ? bad.map(b=>b.params.response.status+' '+b.params.response.url.slice(0,80)).join(' | ') : '(none)');
ws.close(); proc.kill(); process.exit(0);
