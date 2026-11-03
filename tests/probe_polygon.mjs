// Drive the area tool in a real browser: draw a polygon, screenshot mid-draw and after finishing.
import { spawn } from 'child_process';
import { mkdtempSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

const PORT = 9334, CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const dir = mkdtempSync(join(tmpdir(), 'cdpp-'));
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
await new Promise(r=>setTimeout(r,5000));
console.log('loaded, trips =', (await send('Runtime.evaluate',{returnByValue:true,expression:`document.getElementById('n').textContent`})).result.result.value);

async function shot(f){ const s=await send('Page.captureScreenshot',{format:'png'}); writeFileSync(f,Buffer.from(s.result.data,'base64')); console.log('  screenshot ->',f); }
async function click(x,y){
  await send('Input.dispatchMouseEvent',{type:'mousePressed',x,y,button:'left',clickCount:1});
  await send('Input.dispatchMouseEvent',{type:'mouseReleased',x,y,button:'left',clickCount:1});
  await new Promise(r=>setTimeout(r,450));
}

await send('Runtime.evaluate',{expression:`document.getElementById('btndraw').click()`});
console.log('draw mode on, clicking 4 corners...');
const PTS=[[700,220],[1120,250],[1150,650],[740,690]];
for (const [x,y] of PTS) await click(x,y);
await new Promise(r=>setTimeout(r,900));
console.log('MID-DRAW:');
console.log('  poly source features =', (await send('Runtime.evaluate',{returnByValue:true,
  expression:`(()=>{const f=window.__polyFeats;return f?f:document.querySelectorAll('#poly').length})()`})).result.result.value);
await shot('/tmp/poly_mid.png');

await send('Runtime.evaluate',{expression:`document.getElementById('btnfin').click()`});
await new Promise(r=>setTimeout(r,4000));
const state = await send('Runtime.evaluate',{returnByValue:true, expression:
  `JSON.stringify({ panelVisible: getComputedStyle(document.getElementById('poly')).display,
     pn: document.getElementById('pn').textContent,
     table: [...document.querySelectorAll('#pbrk tbody tr')].map(r=>r.innerText.replace(/\\s+/g,' ').trim()),
     n: document.getElementById('n').textContent, note: document.getElementById('note').textContent })`});
console.log('\nAFTER FINISH:');
console.log(state.result.result.value);
await shot('/tmp/poly_done.png');

// ---- legend: role rows appear, and toggling one removes those trips from the map ----
const lg = await send('Runtime.evaluate', {returnByValue:true, expression:
  `JSON.stringify({legend:((document.getElementById('legend')||{}).innerText||'').replace(/\\n+/g,' | '),
                   note: document.getElementById('note').textContent})`});
console.log('\nLEGEND (with area drawn):');
console.log(lg.result.result.value);

await send('Runtime.evaluate', {expression:`document.querySelector('[data-lg="r2"]').click()`});
await new Promise(r=>setTimeout(r,2500));
const tg = await send('Runtime.evaluate', {returnByValue:true, expression:
  `JSON.stringify({off:[...document.querySelectorAll('#legend .row.off')].map(e=>e.innerText.replace(/\\s+/g,' ').trim()),
                   note: document.getElementById('note').textContent})`});
console.log('\nAFTER toggling "passes through" OFF:');
console.log(tg.result.result.value);
await shot('/tmp/poly_toggled.png');

const bad = evs.filter(e => e.method === 'Network.responseReceived' && e.params.response.status >= 400);
console.log('\nHTTP >=400:', bad.length ? bad.map(b=>b.params.response.status+' '+b.params.response.url.slice(0,90)).join(' | ') : '(none)');
ws.close(); proc.kill(); process.exit(0);
