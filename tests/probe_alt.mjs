// Verify the alternative-path layer: selecting a scenario must draw routed bike/train/foot legs
// and station dots, with the legend swapping to the leg colour key.
import { spawn } from 'child_process';
import { mkdtempSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

const PORT = 9352, CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const dir = mkdtempSync(join(tmpdir(), 'cdpalt-'));
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
await new Promise(r => setTimeout(r, 10000));
const ev = async x => (await send('Runtime.evaluate', { returnByValue: true, expression: x })).result.result.value;

const srcFeats = async (name) => await ev(`(()=>{
  const s = window.__map.getSource('${name}');
  const feats = (s && (s._data || s.serialize?.().data))?.features || [];
  const byMode = {};
  for (const f of feats) byMode[f.properties?.mode || '?'] = (byMode[f.properties?.mode||'?']||0)+1;
  return JSON.stringify({features: feats.length, byMode});
})()`);

console.log('=== default (any trip) — alt should be OFF ===');
console.log('alt:', await srcFeats('alt'));
console.log('altstn:', await srcFeats('altstn'));

await ev(`(()=>{ const s=document.getElementById('scen'); s.value='btb'; s.dispatchEvent(new Event('change')); return s.value; })()`);
await new Promise(r => setTimeout(r, 9000));

console.log('\n=== scenario = bike+train+bike (alt ON) ===');
console.log('alt:', await srcFeats('alt'));
console.log('altstn:', await srcFeats('altstn'));
console.log('note:', await ev(`document.getElementById('note').textContent.slice(0,260)`));
console.log('legend heading:', await ev(`(document.querySelector('#legend .lt')||{}).textContent || ''`));
console.log('legend keys:', await ev(`JSON.stringify([...document.querySelectorAll('#legend .keyrow .lb')].map(x=>x.textContent))`));
console.log('altchk checked:', await ev(`document.getElementById('altchk').checked`));

const s1 = await send('Page.captureScreenshot', { format: 'png' });
writeFileSync('/tmp/alt_btb.png', Buffer.from(s1.result.data, 'base64'));

// switch to bike_direct (single leg, no stations)
await ev(`(()=>{ const s=document.getElementById('scen'); s.value='bike_direct'; s.dispatchEvent(new Event('change')); })()`);
await new Promise(r => setTimeout(r, 9000));
console.log('\n=== scenario = bike (direct) ===');
console.log('alt:', await srcFeats('alt'));
console.log('altstn:', await srcFeats('altstn'));

const bad = evs.filter(e => e.method === 'Network.responseReceived' && e.params.response.status >= 400);
console.log('\nHTTP >=400:', bad.length ? bad.map(b => b.params.response.status + ' ' + b.params.response.url.slice(-40)).join(' | ') : '(none)');
console.log('screenshot -> /tmp/alt_btb.png');
ws.close(); proc.kill(); process.exit(0);
