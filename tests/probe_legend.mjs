// Verify the legend NAMES the colour scheme that is actually on screen, in every layer state.
import { spawn } from 'child_process';
import { mkdtempSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

const PORT = 9344, CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const dir = mkdtempSync(join(tmpdir(), 'cdpl-'));
const proc = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${dir}`,
  '--no-first-run', '--no-default-browser-check', '--use-gl=angle', '--use-angle=swiftshader',
  '--enable-unsafe-swiftshader', '--window-size=1500,950', '--hide-scrollbars', 'about:blank'], { stdio: 'ignore' });
async function ver() { for (let i = 0; i < 80; i++) { try { const r = await fetch(`http://127.0.0.1:${PORT}/json/version`); if (r.ok) return r.json(); } catch (e) { } await new Promise(r => setTimeout(r, 250)); } throw new Error('no chrome'); }
await ver();
let t = null;
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
await new Promise(r => setTimeout(r, 8000));
const ev = async x => (await send('Runtime.evaluate', { returnByValue: true, expression: x })).result.result.value;

const readLegend = async () => JSON.parse(await ev(`JSON.stringify({
  headings: [...document.querySelectorAll('#legend .lt')].map(e=>e.textContent),
  ramp: !!document.querySelector('#legend .ramp'),
  ramplbl: [...document.querySelectorAll('#legend .ramplbl span')].map(e=>e.textContent),
  keys: [...document.querySelectorAll('#legend .keyrow')].map(r=>r.querySelector('.lb')?.textContent),
  swatches: [...document.querySelectorAll('#legend .keyrow .sw')].map(s=>getComputedStyle(s).backgroundColor),
  footnotes: [...document.querySelectorAll('#legend .fn')].map(e=>e.textContent.slice(0,70))
})`));

console.log('=== state 1: default (Routed volume layer) ===');
console.log(JSON.stringify(await readLegend(), null, 1));

await ev(`(()=>{const s=document.getElementById('lines'); s.value='trips'; s.dispatchEvent(new Event('change'));})()`);
await new Promise(r => setTimeout(r, 6000));
console.log('\n=== state 2: "Routed sample" (trip layer visible) ===');
console.log(JSON.stringify(await readLegend(), null, 1));

const s1 = await send('Page.captureScreenshot', { format: 'png' });
writeFileSync('/tmp/legend_length.png', Buffer.from(s1.result.data, 'base64'));

await ev(`(()=>{const s=document.getElementById('lines'); s.value='flow'; s.dispatchEvent(new Event('change'));})()`);
await new Promise(r => setTimeout(r, 5000));
const s2 = await send('Page.captureScreenshot', { format: 'png' });
writeFileSync('/tmp/legend_volume.png', Buffer.from(s2.result.data, 'base64'));
console.log('\nscreenshots -> /tmp/legend_volume.png , /tmp/legend_length.png');
const bad = evs.filter(e => e.method === 'Network.responseReceived' && e.params.response.status >= 400);
console.log('HTTP >=400:', bad.length ? bad.map(b => b.params.response.status).join(',') : '(none)');
ws.close(); proc.kill(); process.exit(0);
