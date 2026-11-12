// Verify the live HTTPS site now renders the basemap (mixed-content fix), and that no http://
// tile requests are made.
import { spawn } from 'child_process';
import { mkdtempSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

const PORT = 9354, CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const dir = mkdtempSync(join(tmpdir(), 'cdplive-'));
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
await send('Page.navigate',{url:'https://bicyclize.github.io/shiftmap/'});
for(let i=0;i<180;i++){ await new Promise(r=>setTimeout(r,2000));
  const q=await send('Runtime.evaluate',{returnByValue:true,expression:`!document.getElementById('loading')`});
  if(q.result?.result?.value===true){ console.log('app finished loading (step '+i+')'); break; }
}
await new Promise(r=>setTimeout(r,15000));
const ev=async x=>{ try { return (await send('Runtime.evaluate',{returnByValue:true,expression:x})).result?.result?.value; } catch(e){ return 'ERR'; } };
console.log('isStyleLoaded:', await ev('window.__map?.isStyleLoaded()'));
console.log('areTilesLoaded:', await ev('window.__map?.areTilesLoaded()'));
console.log('composite loaded:', await ev('window.__map?.getSource("composite")?.loaded()'));

const tileUrls = evs.filter(e=>e.method==='Network.requestWillBeSent' && e.params.request.url.includes('tiles.mapbox.com'))
  .map(e=>e.params.request.url);
console.log('tile requests: '+tileUrls.length+', http:// ones: '+tileUrls.filter(u=>u.startsWith('http://')).length);
const fails = evs.filter(e=>e.method==='Network.loadingFailed')
  .map(e=>(e.params.errorText||'')+' blocked='+(e.params.blockedReason||''));
console.log('loadingFailed ('+fails.length+'):', [...new Set(fails)].slice(0,8));
const bad = evs.filter(e=>e.method==='Network.responseReceived' && e.params.response.status>=400)
  .map(e=>e.params.response.status+' '+e.params.response.url.slice(-55));
console.log('HTTP >=400 ('+bad.length+'):', bad.slice(0,8));

const s1 = await send('Page.captureScreenshot', { format: 'png' });
writeFileSync('/tmp/live_check.png', Buffer.from(s1.result.data, 'base64'));
console.log('screenshot -> /tmp/live_check.png');
ws.close(); proc.kill(); process.exit(0);
