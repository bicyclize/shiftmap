// Diagnose the missing basemap: capture MapLibre style state + any failing network request / console error.
import { spawn } from 'child_process';
import { mkdtempSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

const PORT = 9353, CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const dir = mkdtempSync(join(tmpdir(), 'cdpstyle-'));
const proc = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${dir}`,
  '--no-first-run','--no-default-browser-check','--use-gl=angle','--use-angle=swiftshader',
  '--enable-unsafe-swiftshader','--window-size=1200,800','--hide-scrollbars','about:blank'], { stdio: 'ignore' });
async function ver(){ for(let i=0;i<80;i++){ try{ const r=await fetch(`http://127.0.0.1:${PORT}/json/version`); if(r.ok) return r.json(); }catch(e){} await new Promise(r=>setTimeout(r,250)); } throw new Error('no chrome'); }
await ver();
let t; try{ t=await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`,{method:'PUT'})).json(); }
catch(e){ t=(await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find(x=>x.type==='page'); }
const ws = new WebSocket(t.webSocketDebuggerUrl);
let id=0; const pend=new Map(); const evs=[];
ws.addEventListener('message',e=>{ const m=JSON.parse(e.data); if(m.id&&pend.has(m.id)){pend.get(m.id)(m);pend.delete(m.id);} else evs.push(m); });
const send=(m,p={})=>new Promise(r=>{const i=++id;pend.set(i,r);ws.send(JSON.stringify({id:i,method:m,params:p}));});
await new Promise(r=>ws.addEventListener('open',r,{once:true}));
await send('Runtime.enable'); await send('Page.enable'); await send('Network.enable'); await send('Log.enable');
await send('Page.navigate',{url:'http://localhost:8765/'});
for(let i=0;i<120;i++){ await new Promise(r=>setTimeout(r,1500));
  const q=await send('Runtime.evaluate',{returnByValue:true,expression:`!document.getElementById('loading')`});
  if(q.result?.result?.value===true) break; }
await new Promise(r=>setTimeout(r,9000));
const ev=async x=>{ try { return (await send('Runtime.evaluate',{returnByValue:true,expression:x})).result?.result?.value; } catch(e){ return 'ERR'; } };

console.log('isStyleLoaded:', await ev('window.__map.isStyleLoaded()'));
console.log('loaded:', await ev('window.__map.loaded()'));
console.log('style name:', await ev('window.__map.getStyle()?.name'));
console.log('style sources:', await ev('Object.keys(window.__map.getStyle()?.sources||{}).join(",")'));
console.log('map container children:', await ev('document.getElementById("map").children.length'));
console.log('RS routes:', await ev('window.__rs()'));
console.log('matching n:', await ev('document.getElementById("n").textContent'));
console.log('defaults (dmin-dmax):', await ev('[document.getElementById("dmin").value, document.getElementById("dmax").value].join("-")'));

const bad = evs.filter(e=>e.method==='Network.responseReceived' && e.params.response.status>=400)
  .map(e=>e.params.response.status+' '+e.params.response.url.slice(-75));
const errs = evs.filter(e=>e.method==='Log.entryAdded' && e.params.entry.level==='error')
  .map(e=>e.params.entry.text.slice(0,150));
console.log('\nHTTP >=400 ('+bad.length+'):'); bad.slice(0,25).forEach(x=>console.log('  '+x));
console.log('\nconsole/log errors ('+errs.length+'):'); errs.slice(0,25).forEach(x=>console.log('  '+x));
const s1 = await send('Page.captureScreenshot', { format: 'png' });
writeFileSync('/tmp/basemap_check.png', Buffer.from(s1.result.data, 'base64'));
console.log('screenshot -> /tmp/basemap_check.png');
ws.close(); proc.kill(); process.exit(0);
