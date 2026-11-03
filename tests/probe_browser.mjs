// Headless Chrome over CDP: load the app, capture console/network errors, screenshot it.
// Usage: node tests/probe_browser.mjs [url] [outPng]
import { spawn } from 'child_process';
import { mkdtempSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

const URL_ = process.argv[2] || 'http://localhost:8765/';
const OUT  = process.argv[3] || '/tmp/app.png';
const PORT = 9333;
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const dir = mkdtempSync(join(tmpdir(), 'cdp-'));

const proc = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${dir}`,
  '--no-first-run', '--no-default-browser-check',
  '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
  '--window-size=1500,950', '--hide-scrollbars', 'about:blank'
], { stdio: 'ignore' });

async function version(){
  for (let i=0;i<80;i++){
    try { const r = await fetch(`http://127.0.0.1:${PORT}/json/version`); if (r.ok) return r.json(); } catch(e){}
    await new Promise(r=>setTimeout(r,250));
  }
  throw new Error('chrome never came up');
}

let target = null;
async function newTarget(){
  for (const attempt of [1,2]) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`,
                            { method: attempt===1 ? 'PUT' : 'GET' });
      if (r.ok) return r.json();
    } catch(e){}
  }
  const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
  return list.find(t => t.type === 'page');
}

const ver = await version();
console.log('browser :', ver.Browser);
target = await newTarget();

const ws = new WebSocket(target.webSocketDebuggerUrl);
let msgId = 0; const pending = new Map(); const events = [];
ws.addEventListener('message', ev => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  else events.push(m);
});
const send = (method, params={}) => new Promise(res => { const i = ++msgId; pending.set(i, res); ws.send(JSON.stringify({id:i, method, params})); });
await new Promise(r => ws.addEventListener('open', r, {once:true}));

await send('Runtime.enable'); await send('Page.enable');
await send('Log.enable');     await send('Network.enable');
// collect errors that fire before the app's own scripts run
await send('Page.addScriptToEvaluateOnNewDocument', {source:
  `window.__errs=[];addEventListener('error',e=>__errs.push(String(e.message)+' @'+(e.filename||'')+':'+(e.lineno||'')));
   addEventListener('unhandledrejection',e=>__errs.push('REJECT: '+String(e.reason&&e.reason.message||e.reason)));`});

await send('Page.navigate', {url: URL_});

// poll until the app removes its loading placeholder, or give up
const t0 = Date.now();
let done = false;
for (let i=0;i<90;i++){
  await new Promise(r => setTimeout(r, 2000));
  const q = await send('Runtime.evaluate', {returnByValue:true,
    expression:`!document.getElementById('loading')`});
  if (q.result?.result?.value === true){ done = true; break; }
}
console.log(`\napp finished loading: ${done}  (after ${((Date.now()-t0)/1000).toFixed(1)}s)`);
await new Promise(r => setTimeout(r, done ? 6000 : 0));   // let tiles + lines draw

const ex = await send('Runtime.evaluate', {returnByValue:true, expression:
  `JSON.stringify({
     n: (document.getElementById('n')||{}).textContent,
     pct: (document.getElementById('pct')||{}).textContent,
     note: (document.getElementById('note')||{}).textContent,
     loadingStillThere: !!document.getElementById('loading'),
     canvas: !!document.querySelector('#map canvas'),
     dayOptions: [...document.querySelectorAll('#day option')].length,
     baseSelect: !!document.getElementById('base'),
     linesValue: (document.getElementById('lines')||{}).value,
     legend: ((document.getElementById('legend')||{}).innerText||'').replace(/\\n+/g,' | '),
     errs: window.__errs
   })`});

console.log('\n=== DOM STATE ===');
console.log(ex.result?.result?.value ?? JSON.stringify(ex).slice(0,600));

console.log('\n=== CONSOLE / EXCEPTIONS ===');
let shown = 0;
for (const e of events){
  if (e.method === 'Runtime.exceptionThrown'){
    const d = e.params.exceptionDetails;
    console.log('EXCEPTION:', d.text, '|', d.exception?.description?.split('\n')[0] || '');
    shown++;
  }
  if (e.method === 'Runtime.consoleAPICalled'){
    const txt = e.params.args.map(a => a.value ?? a.description ?? '').join(' ');
    if (e.params.type === 'error' || e.params.type === 'warning') { console.log('CONSOLE['+e.params.type+']:', txt.slice(0,300)); shown++; }
  }
  if (e.method === 'Log.entryAdded' && e.params.entry.level === 'error'){
    console.log('LOG:', e.params.entry.text?.slice(0,300)); shown++;
  }
}
if (!shown) console.log('(no errors)');

console.log('\n=== FAILED / ERROR REQUESTS ===');
const fails = events.filter(e => e.method === 'Network.loadingFailed');
for (const f of fails.slice(0,15)) console.log('  FAIL', f.params.type, f.params.errorText);
const bad = events.filter(e => e.method === 'Network.responseReceived' && e.params.response.status >= 400);
if (!fails.length && !bad.length) console.log('(none)');
for (const b of bad.slice(0,15)) console.log('  HTTP', b.params.response.status, b.params.response.url.slice(0,160));

const shot = await send('Page.captureScreenshot', {format:'png'});
writeFileSync(OUT, Buffer.from(shot.result.data, 'base64'));
console.log('\nscreenshot ->', OUT);

ws.close(); proc.kill();
process.exit(0);
