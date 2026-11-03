// Verify the reported bug is fixed: unticking "road" must actually thin the VOLUME layer, and rail
// trips must be drawn along tracks rather than over motorways.
import { spawn } from 'child_process';
import { mkdtempSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

const PORT = 9351, CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const dir = mkdtempSync(join(tmpdir(), 'cdpn2-'));
const proc = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${dir}`,
  '--no-first-run', '--no-default-browser-check', '--use-gl=angle', '--use-angle=swiftshader',
  '--enable-unsafe-swiftshader', '--window-size=1500,950', '--hide-scrollbars', 'about:blank'], { stdio: 'ignore' });
async function ver() { for (let i = 0; i < 80; i++) { try { const r = await fetch(`http://127.0.0.1:${PORT}/json/version`); if (r.ok) return r.json(); } catch (e) { } await new Promise(r => setTimeout(r, 250)); } throw new Error('no chrome'); }
await ver();
let t;
try { t = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' })).json(); }
catch (e) { t = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find(x => x.type === 'page'); }
const ws = new WebSocket(t.webSocketDebuggerUrl);
let id = 0; const pend = new Map(); const evs = [];
ws.addEventListener('message', e => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); } else evs.push(m); });
const send = (m, p = {}) => new Promise(r => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method: m, params: p })); });
await new Promise(r => ws.addEventListener('open', r, { once: true }));
await send('Runtime.enable'); await send('Page.enable');
await send('Page.navigate', { url: 'http://localhost:8765/' });
for (let i = 0; i < 120; i++) { await new Promise(r => setTimeout(r, 1500));
  const q = await send('Runtime.evaluate', { returnByValue: true, expression: `!document.getElementById('loading')` });
  if (q.result?.result?.value === true) break; }
await new Promise(r => setTimeout(r, 9000));
const ev = async x => (await send('Runtime.evaluate', { returnByValue: true, expression: x })).result.result.value;

// what the volume layer is drawing, split by network
const volState = async () => JSON.parse(await ev(`(()=>{
  const src = window.__map.getSource('flow');
  const feats = (src && (src._data || src.serialize?.().data))?.features || [];
  let rail=0, road=0, railR=0, railsum=0, roadsum=0;
  for (const f of feats){ const p=f.properties;
    if (/rail/i.test(String(p.col)) || f.network==='rail') { rail++; }
  }
  return JSON.stringify({segments: feats.length});
})()`));

const counts = async () => JSON.parse(await ev(`JSON.stringify({
  n: document.getElementById('n').textContent,
  note: document.getElementById('note').textContent.slice(0,150),
  nets: [...document.querySelectorAll('#legend .row[data-mode]')].map(r=>({
     k:r.dataset.mode, cnt:r.querySelector('.ct').textContent, off:r.classList.contains('off')}))
})`));

console.log('=== default (both networks on) ===');
console.log(JSON.stringify(await counts(), null, 1));
console.log('volume:', JSON.stringify(await volState()));

// how much VOLUME is drawn before/after unticking road — the reported bug
const volMass = async () => await ev(`(()=>{
  const src = window.__map.getSource('flow');
  const feats = (src && (src._data || src.serialize?.().data))?.features || [];
  let railwhite=0, mass=0;
  for (const f of feats){
    const w = f.properties.w || 0; mass += w;
    // rail edges were tagged by the kind column -> col carries the flow colour, so re-read via RV
  }
  return JSON.stringify({features: feats.length, widthSum: Math.round(mass)});
})()`);
console.log('\nvolume before hiding road:', await volMass());

await ev(`document.querySelector('#legend [data-mode="road"]').click()`);
await new Promise(r => setTimeout(r, 7000));
console.log('\n=== after unticking ROAD ===');
console.log(JSON.stringify(await counts(), null, 1));
console.log('volume after hiding road :', await volMass());
const s1 = await send('Page.captureScreenshot', { format: 'png' });
writeFileSync('/tmp/net_rail_only.png', Buffer.from(s1.result.data, 'base64'));

await ev(`document.querySelector('#legend [data-mode="road"]').click()`);
await ev(`document.querySelector('#legend [data-mode="rail"]').click()`);
await new Promise(r => setTimeout(r, 7000));
console.log('\n=== after unticking RAIL (rail hidden, road shown) ===');
console.log(JSON.stringify(await counts(), null, 1));
console.log('volume after hiding rail :', await volMass());
const s2 = await send('Page.captureScreenshot', { format: 'png' });
writeFileSync('/tmp/net_road_only.png', Buffer.from(s2.result.data, 'base64'));

console.log('\nscreenshots -> /tmp/net_rail_only.png , /tmp/net_road_only.png');
const bad = evs.filter(e => e.method === 'Network.responseReceived' && e.params.response.status >= 400);
console.log('HTTP >=400:', bad.length ? bad.map(b => b.params.response.status + ' ' + b.params.response.url.slice(-40)).join(' | ') : '(none)');
ws.close(); proc.kill(); process.exit(0);
