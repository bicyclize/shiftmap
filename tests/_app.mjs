
import { parquetReadObjects, parquetMetadata } from './vendor/hyparquet.js';
import { compressors } from './vendor/hyparquet-compressors.js';

const COLS = ['day_tag','od_m','path_m','o_lon','o_lat','d_lon','d_lat','o_in_bp','d_in_bp',
              'trip_scope','bike_direct','btb','btf','rail_lvl','o_stn','d_stn','o_to_stn','d_to_stn','dur_s'];
const BANDS = [[0,2000,'≤2 km','#1a9850'],[2000,5000,'2–5 km','#66bd63'],[5000,8000,'5–8 km','#fdae61'],
               [8000,15000,'8–15 km','#f46d43'],[15000,1e9,'>15 km','#d73027']];
const BANDM = [[0,2000],[2000,5000],[5000,8000],[8000,15000],[15000,1e9]];
const DAYS  = ['08','09','10','11','12','13','14'];
// Legend = the FILTER control for trips relative to a drawn area. A trip is shown if it satisfies
// ANY checked criterion (a trip that both starts and ends inside inside satisfies two of them).
const ROLE_ON  = { start: true, end: true, pass: true };
const ROLE_COL = { start: '#1F6FB2', end: '#2CA25F', pass: '#F2A900', both: '#8E44AD' };
let volNote = '';              // what the volume layer actually reflects for the current filter
let selEdge = null;            // a clicked network segment (index into RV edges)
let D = null;              // column arrays
let poly = [];             // [[lon,lat], ...] drawn polygon
let polyClosed = false;
let drawing = false;
let RV = null;                       // per-edge routed trip volumes
let RS = null;                       // trip index -> CALCULATED ROUTE geometry (every trip)
const DATA = 'trips_attrs.parquet';        // attributes only; geometry always comes from a route
const ROUTEDVOL = 'routed_edges.parquet';
const ROUTEDGEOM = 'routed_geom.parquet';
const RAILMODE  = 'rail_mode.parquet';
const ROUTELEN  = 'route_len.parquet';   // per-trip: on_rail -> the NETWORK its route follows
let RM = null;                       // per-trip rail-corridor proxy (from the observed pings)
let RL = null;                       // per-trip network the DRAWN ROUTE actually follows

const OSM_ATTR = '© <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> contributors';
const MB_ATTR  = '© <a href="https://www.mapbox.com/about/maps/" target="_blank">Mapbox</a> · ' + OSM_ATTR;
const MB_STYLE = 'style.json';   // Bicyclize Monochrome, pre-converted for MapLibre

const map = new maplibregl.Map({
  container:'map', style:MB_STYLE,
  center:[19.06,47.50], zoom:11, attributionControl:false
});
window.__map = map;      // test hook: lets the headless probes inspect the rendered layers

// ---- (re)build our own layers after every style swap ----
map.on('style.load', () => {
  if (!map.getSource('flow')){
    map.addSource('flow', {type:'geojson', data:{type:'FeatureCollection',features:[]}});
    map.addLayer({id:'flow', type:'line', source:'flow',
      layout:{'line-cap':'round','line-join':'round'},
      paint:{'line-color':['get','col'],'line-width':['get','w'],'line-opacity':['get','op']}});
  }
  if (!map.getSource('trips')){
    map.addSource('trips', {type:'geojson', data:{type:'FeatureCollection',features:[]}});
    map.addLayer({id:'trips', type:'line', source:'trips',
      paint:{'line-color':['get','col'],'line-width':['get','w'],'line-opacity':['get','op']}});
  }
  if (!map.getSource('poly')){
    map.addSource('poly', {type:'geojson', data:{type:'FeatureCollection',features:[]}});
    map.addLayer({id:'polyfill', type:'fill', source:'poly',
      filter:['!=',['geometry-type'],'Point'],
      paint:{'fill-color':'#7EC4F5','fill-opacity':0.30}});
    map.addLayer({id:'polyline', type:'line', source:'poly',
      filter:['!=',['geometry-type'],'Point'],
      paint:{'line-color':'#1F6FB2','line-width':1.8,'line-dasharray':[3,2]}});
    map.addLayer({id:'polypts', type:'circle', source:'poly',
      filter:['==',['geometry-type'],'Point'],
      paint:{'circle-radius':4.5,'circle-color':'#1F6FB2','circle-stroke-color':'#fff','circle-stroke-width':1.5}});
  }
  if (!map.getSource('seledge')){
    map.addSource('seledge', {type:'geojson', data:{type:'FeatureCollection',features:[]}});
    map.addLayer({id:'seledge', type:'line', source:'seledge',
      layout:{'line-cap':'round','line-join':'round'},
      paint:{'line-color':'#ff2d55','line-width':4.5,'line-opacity':0.9}});
  }
  const el = document.getElementById('attrib'); if (el) el.innerHTML = MB_ATTR;
  refreshPoly(); updateLineModes(); renderFlow(); apply();
});

document.getElementById('lines').addEventListener('change', apply);
document.getElementById('legend').addEventListener('click', e => {
  const mr = e.target.closest('[data-mode]');
  if (mr){ const k = mr.dataset.mode; MODE_ON[k] = !MODE_ON[k]; apply(); return; }
  const r = e.target.closest('[data-role]'); if (!r) return;
  const k = r.dataset.role;
  ROLE_ON[k] = !ROLE_ON[k];
  apply();          // re-filters AND re-counts every number on the left
});

function bandOf(m){ for (const [a,b,l,c] of BANDS) if (m>=a && m<b) return {l,c}; return {l:'?',c:'#999'}; }
const EMPTY = {type:'FeatureCollection',features:[]};

// ---------------- geometry helpers (no external deps) ----------------
function pointInPoly(p, pg){
  let inside = false;
  for (let i=0, j=pg.length-1; i<pg.length; j=i++){
    const [xi,yi]=pg[i], [xj,yj]=pg[j];
    if (((yi>p[1]) !== (yj>p[1])) && (p[0] < (xj-xi)*(p[1]-yi)/(yj-yi)+xi)) inside = !inside;
  }
  return inside;
}
function segInt(a,b,c,d){
  const o=(p,q,r)=> ((q[1]-p[1])*(r[0]-q[0]) - (q[0]-p[0])*(r[1]-q[1]));
  const o1=o(a,b,c), o2=o(a,b,d), o3=o(c,d,a), o4=o(c,d,b);
  return ((o1>0)!==(o2>0)) && ((o3>0)!==(o4>0));
}
// does the trip's CALCULATED ROUTE touch the polygon? There is no O–D fallback: a trip without a
// calculated route is never attributed to an area (and is never drawn).
function pathHits(i, pg){
  const pts = tripPts(i);
  if (!pts) return false;       // no calculated route → it cannot be attributed to the area
  for (let k=0; k+3 < pts.length; k+=2){
    const a=[pts[k],pts[k+1]], b=[pts[k+2],pts[k+3]];
    if (pointInPoly(a,pg) || pointInPoly(b,pg)) return true;
    for (let e=0; e<pg.length; e++){
      const c=pg[e], d=pg[(e+1)%pg.length];
      if (segInt(a,b,c,d)) return true;
    }
  }
  return false;
}
// The ONLY geometry the app ever draws: the trip's calculated route.
// No snapped-ping chords, and never a straight O–D line.
function tripLine(i){
  const xy = tripPts(i);
  if (!xy) return null;
  const c=[]; for (let k=0;k+1<xy.length;k+=2) c.push([xy[k],xy[k+1]]);
  return c.length >= 2 ? c : null;
}

// ---------------- network-segment selection: click a road → keep only trips using it ----------
const M_LAT = 110574, M_LON = 111320 * Math.cos(47.5 * Math.PI / 180);   // metres per degree, locally
const SEL_TOL_M = 22;
// A trip's CALCULATED ROUTE, or null if it has none. This is the single geometry accessor —
// every draw, area test and segment test goes through it, so an O–D straight line cannot appear.
function tripPts(i){
  if (!RS) return null;
  const xy = RS.get(i);
  return (xy && xy.length >= 4) ? xy : null;
}
function distPtSegM(plon, plat, alon, alat, blon, blat){
  const px=(plon-alon)*M_LON, py=(plat-alat)*M_LAT;
  const bx=(blon-alon)*M_LON, by=(blat-alat)*M_LAT;
  const l2 = bx*bx + by*by;
  let t = l2 ? (px*bx + py*by)/l2 : 0;
  t = t < 0 ? 0 : (t > 1 ? 1 : t);
  return Math.hypot(px - t*bx, py - t*by);
}
let selSegs = null, selBox = null;   // cached segments / bbox of the selected edge
function setSelEdge(e){
  selEdge = e; selSegs = null; selBox = null;
  const src = map.getSource('seledge');
  if (e === null || !RV || !RV.xy){ if (src) src.setData(EMPTY); return; }
  const xy = RV.xy[e];
  if (!xy || xy.length < 4){ selEdge = null; if (src) src.setData(EMPTY); return; }
  const segs = [], coords = [[xy[0], xy[1]]];
  let mnx=xy[0], mxx=xy[0], mny=xy[1], mxy=xy[1];
  let a = [xy[0], xy[1]];
  for (let k=2;k+1<xy.length;k+=2){
    const b = [xy[k], xy[k+1]];
    segs.push([a[0],a[1],b[0],b[1]]);
    coords.push(b);
    if (b[0]<mnx) mnx=b[0]; if (b[0]>mxx) mxx=b[0];
    if (b[1]<mny) mny=b[1]; if (b[1]>mxy) mxy=b[1];
    a = b;
  }
  selSegs = segs;
  const pad = 0.0006;                          // ~40 m
  selBox = [mnx-pad, mny-pad, mxx+pad, mxy+pad];
  if (src) src.setData({type:'FeatureCollection', features:[
    {type:'Feature',properties:{},geometry:{type:'LineString',coordinates:coords}}]});
}
// does trip i run along the selected segment?
function usesEdge(i){
  if (!selSegs) return true;
  const pts = tripPts(i);
  if (!pts) return false;            // no calculated route → cannot be along the segment
  let mnx=1e9,mxx=-1e9,mny=1e9,mxy=-1e9;
  for (let k=0;k+1<pts.length;k+=2){
    if (pts[k]<mnx) mnx=pts[k]; if (pts[k]>mxx) mxx=pts[k];
    if (pts[k+1]<mny) mny=pts[k+1]; if (pts[k+1]>mxy) mxy=pts[k+1];
  }
  if (mxx < selBox[0] || mnx > selBox[2] || mxy < selBox[1] || mny > selBox[3]) return false;
  for (let k=0;k+3<pts.length;k+=2){
    for (const s of selSegs){
      if (distPtSegM(pts[k],   pts[k+1], s[0],s[1],s[2],s[3]) < SEL_TOL_M) return true;
      if (distPtSegM(pts[k+2], pts[k+3], s[0],s[1],s[2],s[3]) < SEL_TOL_M) return true;
    }
  }
  return false;
}
function nearestEdge(lon, lat, tolM){
  if (!RV || !RV.xy) return null;
  let best = null, bd = tolM * tolM;
  for (let i=0;i<RV.xy.length;i++){
    const xy = RV.xy[i]; if (!xy || xy.length < 4) continue;
    for (let k=0;k+3<xy.length;k+=2){
      const d = distPtSegM(lon, lat, xy[k], xy[k+1], xy[k+2], xy[k+3]);
      if (d*d < bd){ bd = d*d; best = i; }
    }
  }
  return best;
}
map.on('click', e => {
  if (drawing || !RV) return;
  const hit = nearestEdge(e.lngLat.lng, e.lngLat.lat, 25);
  // clicking the SAME road again deselects it — in a dense city almost every point is near some
  // road, so "click empty space to clear" would be unreliable
  setSelEdge(hit === selEdge ? null : hit);
  if (selEdge !== null) document.getElementById('lines').value = 'trips';   // trips must be visible
  apply();
});

// ---------------- flow layer: OSM network with thickness = trip volume ----------------
function mixHex(c1,c2,u){
  const p=h=>[parseInt(h.slice(1,3),16),parseInt(h.slice(3,5),16),parseInt(h.slice(5,7),16)];
  const A=p(c1),B=p(c2);
  return 'rgb('+A.map((v,i)=>Math.round(v+(B[i]-v)*u)).join(',')+')';
}
function flowColor(t){
  const stops=[[0,'#3b4cc0'],[0.35,'#39a0c9'],[0.7,'#f2c14e'],[1,'#d73027']];
  for (let i=0;i<stops.length-1;i++){
    const a=stops[i][0], b=stops[i+1][0];
    if (t<=b) return mixHex(stops[i][1], stops[i+1][1], (t-a)/((b-a)||1));
  }
  return stops[stops.length-1][1];
}
function curFilter(){
  return {
    scope: document.getElementById('scope').value,
    scen:  document.getElementById('scen').value,
    day:   document.getElementById('day').value,
    dmin:  (+document.getElementById('dmin').value||0)*1000,
    dmax:  (+document.getElementById('dmax').value||999)*1000
  };
}
function bandIdxSet(dmin, dmax){
  const s=[];
  for (let b=0;b<5;b++) if (BANDM[b][0] < dmax && BANDM[b][1] > dmin) s.push(b);
  return s.length ? s : [0,1,2,3,4];
}
// Per-edge trip counts for the CURRENT filter, from the routed split vector.
// Exact for day, for length, for day+length, and for scope alone. Scope combined with day or
// length cannot be exact — the splits are stored as separate marginals — so we apply scope and
// SAY SO in the legend rather than silently showing a number that ignores a filter.
function routedCounts(f){
  const n = RV.ns.length, out = new Float64Array(n);
  const bands = bandIdxSet(f.dmin, f.dmax);
  const days  = f.day === 'all' ? [0,1,2,3,4,5,6] : [Math.max(0, DAYS.indexOf(f.day))];
  const dayC  = f.day !== 'all';
  const bandC = !(f.dmin <= 0 && f.dmax >= 999000);
  const si = f.scope==='budapest'?0 : f.scope==='suburb_bp'?1 : f.scope==='suburb_local'?2 : -1;
  if (si >= 0){
    volNote = (dayC || bandC) ? 'volume: scope only — day/length NOT applied here'
                              : 'volume: scope';
    for (let i=0;i<n;i++){ const c = RV.ns[i]; out[i] = c ? c[35+si] : 0; }
  } else {
    volNote = (dayC || bandC) ? 'volume: day + length' : 'volume: all trips';
    for (let i=0;i<n;i++){
      const c = RV.ns[i]; if (!c) continue;
      let s = 0;
      for (const d of days) for (const b of bands) s += c[d*5+b];
      out[i] = s;
    }
  }
  // NETWORK MASK — without this the volume layer ignored the street legend entirely, which is why
  // unticking "road" left every red segment on screen. Rail trips are routed along the guideway and
  // road trips along roads, so hiding a network can now genuinely remove its edges.
  if (RV.kind){
    let any = false;
    for (let i=0;i<n;i++){
      const off = RV.kind[i] === 'rail' ? !MODE_ON.rail : !MODE_ON.road;
      if (off) out[i] = 0; else if (out[i] > 0) any = true;
    }
    volNote = any ? (volNote + (MODE_ON.rail && MODE_ON.road ? '' : ' (one network hidden)'))
                  : 'nothing to show — every network is hidden';
  }
  return out;
}
function renderFlow(){
  const src = map.getSource('flow'); if (!src) return;
  let N, XY;
  if (RV && RV.ns && RV.xy){ N = routedCounts(curFilter()); XY = RV.xy; }
  else { src.setData(EMPTY); volNote = ''; return; }
  let maxN = 1; for (let i=0;i<N.length;i++) if (N[i] > maxN) maxN = N[i];
  const feats = [];
  for (let i=0;i<N.length;i++){
    const n = N[i]; if (!n) continue;
    const xy = XY[i]; if (!xy || xy.length < 4) continue;
    const c=[]; for (let k=0;k+1<xy.length;k+=2) c.push([xy[k],xy[k+1]]);
    const t = Math.sqrt(n / maxN);                       // perceptual (area) scaling
    feats.push({type:'Feature',
      properties:{ w: 0.45 + 9.5*t, op: 0.22 + 0.70*t, col: flowColor(t), n: n },
      geometry:{type:'LineString', coordinates:c}});
  }
  src.setData({type:'FeatureCollection', features:feats});
}
function updateLineModes(){
  const m = document.getElementById('lines').value;
  const forceTrips = (polyClosed && poly.length >= 3) || selEdge !== null;
  // Neither the volume layer nor an area can be applied to pre-aggregated edges, so when an
  // area or a clicked segment is active we show ONLY the matching trips — which is the point.
  const showFlow  = (m==='flow'  || m==='both') && !forceTrips;
  const showTrips = (m==='trips' || m==='both') || forceTrips;
  if (map.getLayer('flow'))  map.setLayoutProperty('flow',  'visibility', showFlow  ? 'visible':'none');
  if (map.getLayer('trips')) map.setLayoutProperty('trips', 'visibility', showTrips ? 'visible':'none');
}
function bandIndexOf(m){ for (let b=0;b<5;b++) if (m>=BANDM[b][0] && m<BANDM[b][1]) return b; return 4; }
// primary role of a trip relative to the area — used for COLOUR only
function roleKey(oIn, dIn){
  if (oIn && dIn) return 'both';
  return oIn ? 'start' : dIn ? 'end' : 'pass';
}
function roleColor(k){ return ROLE_COL[k] || '#999'; }
function fmt(n){ return (n||0).toLocaleString(); }
// ---- mode rows: ROAD vs RAIL. Like the role rows these are FILTERS, not a display style, so
// they carry no colour swatch — the map is coloured by length band (or by area role).
// TWO toggles, matching the two NETWORKS the trips are actually drawn on: a rail-classified trip is
// routed along the guideway, everything else along roads. That keeps the volume layer exact — an
// edge is hidden precisely when its network's toggle is off. Trips that only PARTLY follow a
// guideway are drawn on roads (a road route is what they are), so they count as road; the legend
// reports their number so the distinction is not lost.
const MODE_ON  = {rail:true, road:true};
const MODE_LBL = {rail:'rail corridor', road:'road'};
const MODE_TIP = {rail:'routed along the PUBLIC PASSENGER guideway — metro, tram, HÉV, rail. ' +
                       'Depot, yard, siding and cross-over tracks are excluded, so a trip over a ' +
                       'service connection is never drawn as rail',
                  road:'routed along roads. NOT the same as “car” — a bus runs on a road'};
function modeKey(i){
  // The network the trip's CALCULATED ROUTE actually follows. Using the classification instead was
  // the bug: a rail-corridor trip that fell back to a road route was coloured and filtered as rail,
  // so switching the road network off still left red segments sitting on motorways.
  if (RL) return RL.on_rail[i] ? 'rail' : 'road';
  if (!RM) return null;
  return RM.mode[i] === 'rail' ? 'rail' : 'road';       // fallback if route_len is unavailable
}
function modeRow(k, cnt){
  const on = MODE_ON[k];
  return `<div class="row${on?'':' off'}" data-mode="${k}" title="${MODE_TIP[k]} — click to ${on?'hide':'show'}">` +
         `<span class="cbx">${on?'✓':''}</span>` +
         `<span class="lb">${MODE_LBL[k]}</span><span class="ct">${fmt(cnt)}</span></div>`;
}

// ---- legend: WHICH TRIPS TO SHOW. Drives both the map and every number on the left. ----
function lgRow(k, lbl, cnt){
  const on = ROLE_ON[k];
  return `<div class="row${on?'':' off'}" data-role="${k}" title="click to ${on?'hide':'show'}">` +
         `<span class="cbx">${on?'✓':''}</span>` +
         `<span class="sw" style="background:${ROLE_COL[k]}"></span>` +
         `<span class="lb">${lbl}</span><span class="ct">${fmt(cnt)}</span></div>`;
}
// A non-interactive colour key row (no data-role / data-mode, so the click handler ignores it).
function keyRow(col, lbl){
  return `<div class="keyrow"><span class="sw" style="background:${col}"></span>` +
         `<span class="lb">${lbl}</span></div>`;
}
// The legend must NAME the colour scheme currently on screen, because the map is coloured three
// different ways: by routed volume, by trip length, or by a trip's role relative to a drawn area.
function colourKeyHTML(showFlow, usePoly){
  if (usePoly){
    return '<div class="lt">Colour — role in the area</div>' +
      '<div class="fn">The rows below are also the colour key.</div>';
  }
  if (showFlow){
    return '<div class="lt">Colour & thickness — routed volume</div>' +
      '<div class="ramp"></div>' +
      '<div class="ramplbl"><span>fewer trips</span><span>more trips</span></div>' +
      '<div class="fn">Trips routed along each OSM road segment. Thicker and more opaque = busier.</div>';
  }
  return '<div class="lt">Colour — trip length</div>' +
    BANDS.map(b => keyRow(b[3], b[2])).join('') +
    '<div class="fn">Straight-line distance, origin to destination.</div>';
}

function renderLegend(Pf, usePoly, Mcnt, showFlow){
  const el = document.getElementById('legend'); if (!el) return;
  let h = colourKeyHTML(showFlow, usePoly);
  if (RM) h += '<div class="lt">Network — click to hide</div>' +
    modeRow('rail',  Mcnt.rail) +
    modeRow('road',  Mcnt.road) +
    `<div class="fn">Rail trips are routed along the <b>tracks</b>; every other trip along roads. ` +
    `Only <b>public passenger</b> lines count as tracks — depot, yard, siding and cross-over ` +
    `connections are excluded, so a trip over a service link is never drawn as rail. ` +
    `A rail-corridor trip whose ends sit on <i>different</i> guided systems (tram at one end, ` +
    `metro at the other) is not one guideway trip and keeps its road route. ` +
    `Rail is read off the guideway, so <b>underground metro is under-detected</b> (no GPS in tunnels). ` +
    `“Road” ≠ “car” — a bus runs on a road.` +
    (Mcnt.partly ? ` <span style="color:#999">Road includes ${fmt(Mcnt.partly)} that only partly follow a guideway.</span>` : '') +
    `</div>`;
  h += '<div class="lt">Show trips that…</div>';
  if (!usePoly){
    h += '<div class="fn">Draw an area on the map to filter by starting, ending or passing by.</div>';
  } else {
    h += lgRow('start', 'start inside', Pf.start) +
         lgRow('end',   'end inside',   Pf.end) +
         lgRow('pass',  'pass by',      Pf.pass) +
         `<div class="fn"><span class="sw" style="background:${ROLE_COL.both};display:inline-block;vertical-align:-1px"></span>` +
         ` ${fmt(Pf.both)} both ends inside <span style="color:#999">(count as starting <i>and</i> ending)</span></div>`;
  }
  el.innerHTML = h;
}

// ---------------- drawing ----------------
function refreshPoly(){
  const src = map.getSource('poly'); if (!src) return;
  if (!poly.length){ src.setData(EMPTY); return; }
  const feats = [];
  // from 3 corners on, fill the enclosed area immediately — you see the shape as you draw it
  if (poly.length >= 3){
    feats.push({type:'Feature',properties:{},
      geometry:{type:'Polygon',coordinates:[[...poly, poly[0]]]}});
  } else if (poly.length === 2){
    feats.push({type:'Feature',properties:{},
      geometry:{type:'LineString',coordinates:poly}});
  }
  for (const p of poly) feats.push({type:'Feature',properties:{},geometry:{type:'Point',coordinates:p}});
  src.setData({type:'FeatureCollection',features:feats});
}
function setDrawing(on){
  drawing = on;
  document.getElementById('btndraw').classList.toggle('on', on);
  map.getCanvas().style.cursor = on ? 'crosshair' : '';
  map.doubleClickZoom[on ? 'disable' : 'enable']();
  document.getElementById('drawhint').textContent = on
    ? 'Click the map to place corners. Double-click or “Finish” to close, “Clear” to start over.'
    : 'Click “Draw area”, then click the map to place corners; double-click (or “Finish”) to close.';
}
map.on('click', e => {
  if (!drawing) return;
  poly.push([e.lngLat.lng, e.lngLat.lat]); polyClosed = false; refreshPoly();
});
map.on('dblclick', e => { if (drawing && poly.length >= 3){ e.preventDefault(); finishDraw(); } });
function finishDraw(){
  if (poly.length < 3) return;
  polyClosed = true; refreshPoly(); apply(); setDrawing(false);
}
document.getElementById('btndraw').addEventListener('click', () => setDrawing(!drawing));
document.getElementById('btnfin').addEventListener('click', finishDraw);
document.getElementById('btnclear').addEventListener('click', () => { poly=[]; polyClosed=false; refreshPoly(); apply(); });

// ---------------- data ----------------
// hyparquet returns parquetMetadata().schema as a FLAT object keyed by index (0 = root),
// NOT a {children:[...]} tree. Reading `.children` yields undefined, so every column looks
// absent — which silently disabled the snapped paths AND the whole flow layer. Handle both shapes.
function schemaNames(md){
  const out = new Set();
  const s = md && md.schema; if (!s) return out;
  if (Array.isArray(s.children)){
    for (const c of s.children){ const n = c?.element?.name ?? c?.name; if (n) out.add(n); }
  } else {
    for (const k of Object.keys(s)){ const n = s[k] && s[k].name; if (n) out.add(n); }
  }
  return out;
}

async function load(){
  const buf = await (await fetch(DATA)).arrayBuffer();
  let have = null;
  try { have = schemaNames(parquetMetadata(buf)); } catch (e) { /* fall back to requesting everything */ }
  const cols = (have && have.size) ? COLS.filter(c => have.has(c)) : COLS;
  const rows = await parquetReadObjects({ file: buf, compressors, columns: cols });
  D = {}; for (const c of cols) D[c] = new Array(rows.length);
  for (let i=0;i<rows.length;i++){ const r=rows[i]; for (const c of cols) D[c][i] = (typeof r[c]==='bigint' ? Number(r[c]) : r[c]); }

  // routed volumes per edge → the thickness layer
  try {
    const rb = await (await fetch(ROUTEDVOL)).arrayBuffer();
    const rm = schemaNames(parquetMetadata(rb));
    const rcols = ['len_m', 'n', 'ns', 'xy', 'kind'].filter(c => rm.has(c));
    const rrows = await parquetReadObjects({ file: rb, compressors, columns: rcols });
    RV = {}; for (const c of rcols) RV[c] = rrows.map(r => typeof r[c] === 'bigint' ? Number(r[c]) : r[c]);
  } catch (e) { RV = null; }
  // the CALCULATED ROUTE for every trip — the only geometry this app ever draws or tests
  try {
    const gb = await (await fetch(ROUTEDGEOM)).arrayBuffer();
    const grows = await parquetReadObjects({ file: gb, compressors, columns: ['i','xy'] });
    RS = new Map();
    for (const r of grows) RS.set(typeof r.i === 'bigint' ? Number(r.i) : r.i, r.xy);
  } catch (e) { RS = null; }
  // first-pass rail-corridor proxy per trip
  try {
    const nb = await (await fetch(RAILMODE)).arrayBuffer();
    const nrows = await parquetReadObjects({ file: nb, compressors, columns: ['i','mode','rail_share'] });
    RM = { mode: new Array(rows.length), share: new Array(rows.length) };
    for (const r of nrows){
      const i = typeof r.i === 'bigint' ? Number(r.i) : r.i;
      RM.mode[i] = r.mode;
      RM.share[i] = typeof r.rail_share === 'bigint' ? Number(r.rail_share) : r.rail_share;
    }
  } catch (e) { RM = null; }
  // Which NETWORK each drawn route follows. This is the flag the rail/road toggles act on: a
  // rail-corridor trip that could not be routed on a single guided system keeps its ROAD route, and
  // must be drawn and counted as road or hiding the road network would still leave it on screen.
  try {
    const lb = await (await fetch(ROUTELEN)).arrayBuffer();
    const lrows = await parquetReadObjects({ file: lb, compressors, columns: ['i','on_rail'] });
    RL = { on_rail: new Uint8Array(rows.length) };
    for (const r of lrows){
      const i = typeof r.i === 'bigint' ? Number(r.i) : r.i;
      RL.on_rail[i] = r.on_rail ? 1 : 0;
    }
  } catch (e) { RL = null; }

  const days = [...new Set(D.day_tag)].sort();
  const sel = document.getElementById('day');
  for (const d of days){ const o=document.createElement('option'); o.value=d; o.textContent='May '+d; sel.appendChild(o); }
  document.getElementById('loading').remove();
  apply();
}

function apply(){
  if(!D) return;
  const scope = document.getElementById('scope').value;
  const scen  = document.getElementById('scen').value;
  const day   = document.getElementById('day').value;
  const dmin  = (+document.getElementById('dmin').value||0)*1000;
  const dmax  = (+document.getElementById('dmax').value||999)*1000;
  const usePoly = polyClosed && poly.length >= 3;

  const idx=[]; const brk={bike_direct:0,btb:0,btf:0}; let inArea=0;
  const hist=[0,0,0,0,0];
  const P  = {n:0,o:0,d:0,int:0,th:0, bd:0, btb:0, btf:0};   // trips actually SHOWN
  const Pf = {n:0,start:0,end:0,pass:0,both:0};               // ALL trips touching the area (legend)
  const Mcnt = {rail:0, road:0, partly:0};                    // network legend counts
  const roleOf = new Map();          // trip index -> role relative to the drawn area

  for(let i=0;i<D.od_m.length;i++){
    if(scope!=='all' && D.trip_scope[i]!==scope) continue;
    if(day!=='all' && D.day_tag[i]!==day) continue;
    inArea++;
    const m=D.od_m[i]; if(m<dmin||m>dmax) continue;
    if(scen!=='any' && !D[scen][i]) continue;
    if(selEdge !== null && !usesEdge(i)) continue;      // a clicked network segment is selected

    // legend network toggles (rail / road) — count every candidate, then drop the hidden ones
    const mk = modeKey(i);
    if (mk) Mcnt[mk]++;
    if (RM && RM.mode[i] === 'mixed') Mcnt.partly++;
    if (mk && !MODE_ON[mk]) continue;

    if (usePoly){
      const oIn = pointInPoly([D.o_lon[i],D.o_lat[i]], poly);
      const dIn = pointInPoly([D.d_lon[i],D.d_lat[i]], poly);
      const thru = pathHits(i, poly);
      if (!(oIn || dIn || thru)) continue;              // everything unrelated disappears
      const pass = !oIn && !dIn;                        // "pass by" = through traffic only
      Pf.n++;
      if (oIn) Pf.start++;
      if (dIn) Pf.end++;
      if (pass) Pf.pass++;
      if (oIn && dIn) Pf.both++;
      // THE LEGEND DECIDES what is counted and drawn: shown if it satisfies ANY checked criterion
      if (!((oIn && ROLE_ON.start) ||
            (dIn && ROLE_ON.end)   ||
            (pass && ROLE_ON.pass))) continue;
      roleOf.set(i, roleKey(oIn, dIn));
      P.n++; P.bd += D.bike_direct[i]?1:0; P.btb += D.btb[i]?1:0; P.btf += D.btf[i]?1:0;
      if (oIn && dIn) P.int++; else if (oIn) P.o++; else if (dIn) P.d++; else P.th++;
    }
    idx.push(i);
    hist[bandIndexOf(m)]++;
    brk.bike_direct += D.bike_direct[i]?1:0;
    brk.btb += D.btb[i]?1:0;
    brk.btf += D.btf[i]?1:0;
  }

  document.getElementById('n').textContent = idx.length.toLocaleString();
  document.getElementById('pct').innerHTML = (100*idx.length/Math.max(inArea,1)).toFixed(1)+'%<small> of '+inArea.toLocaleString()+'</small>';
  const tb=document.querySelector('#brk tbody'); tb.innerHTML='';
  for(const [k,lbl] of [['bike_direct','bike direct'],['btb','bike+train+bike'],['btf','bike+train+foot']]){
    const tr=document.createElement('tr');
    tr.innerHTML=`<td>${lbl}</td><td>${brk[k].toLocaleString()}</td><td>${(100*brk[k]/Math.max(inArea,1)).toFixed(1)}%</td>`;
    tb.appendChild(tr);
  }
  const tot=hist.reduce((a,b)=>a+b,0)||1;
  document.getElementById('bar').innerHTML = hist.map((h,i)=>
    `<div style="width:${100*h/tot}%;background:${BANDS[i][3]}">${h?Math.round(100*h/tot)+'%':''}</div>`).join('');
  document.getElementById('barlg').innerHTML = BANDS.map(b=>`<span style="margin-right:9px"><span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${b[3]};margin-right:3px"></span>${b[2]}</span>`).join('');

  // polygon analysis panel
  const panel = document.getElementById('poly');
  if (usePoly){
    panel.style.display='block';
    document.getElementById('pn').textContent = P.n.toLocaleString();
    const pt=document.querySelector('#pbrk tbody'); pt.innerHTML='';
    for (const [lbl,v] of [['starts inside → out',P.o],['outside → ends in',P.d],['inside → inside',P.int],['passes through',P.th]]){
      const tr=document.createElement('tr');
      tr.innerHTML=`<td>${lbl}</td><td>${v.toLocaleString()}</td><td>–</td><td>–</td>`;
      pt.appendChild(tr);
    }
    const tr=document.createElement('tr');
    tr.innerHTML=`<td><b>of these, could be…</b></td><td></td><td></td><td></td>`; pt.appendChild(tr);
    for (const [lbl,v] of [['bike',P.bd],['bike+train+bike',P.btb],['bike+train+foot',P.btf]]){
      const r=document.createElement('tr');
      r.innerHTML=`<td>· ${lbl}</td><td>${v.toLocaleString()}</td><td>${(100*v/Math.max(P.n,1)).toFixed(1)}%</td><td></td>`;
      pt.appendChild(r);
    }
  } else panel.style.display='none';

  // map — idx already reflects EVERY filter, including the legend's role toggles
  const CAP=4000, step=Math.max(1, Math.ceil(idx.length/CAP));
  const feats=[];
  let noRoute = 0;
  for(let k=0;k<idx.length;k+=step){
    const i=idx[k];
    const line = tripLine(i);
    if (!line){ noRoute++; continue; }        // no calculated route → nothing to draw, ever
    const bi = bandIndexOf(D.od_m[i]);
    const role = usePoly ? roleOf.get(i) : null;
    const sel = selEdge !== null;
    feats.push({type:'Feature',
      properties:{i: i, col: role ? roleColor(role) : BANDS[bi][3],
                  w: sel ? 1.6 : (idx.length>20000?0.7:1.2),
                  op: sel ? 0.85 : 0.55},
      geometry:{type:'LineString',coordinates: line}});
  }
  const src = map.getSource('trips');
  if (src) src.setData({type:'FeatureCollection',features:feats});
  renderFlow();
  updateLineModes();
  // which layer is actually visible decides what the legend has to explain
  const lm = document.getElementById('lines').value;
  const forceTrips = usePoly || selEdge !== null;
  const showFlow = (lm === 'flow' || lm === 'both') && !forceTrips;
  renderLegend(Pf, usePoly, Mcnt, showFlow);
  document.getElementById('note').textContent =
    (idx.length>CAP ? `Map shows ${feats.length.toLocaleString()} sampled of ${idx.length.toLocaleString()} matching trips (all used for the counts). ` :
     `Map shows all ${feats.length.toLocaleString()} matching trips. `) +
    (usePoly ? 'Area filter applied — only trips that start, end or pass through the drawn area. ' : '') +
    (selEdge !== null ? 'Segment selected — showing only trips routed along it; click the same road again to clear. ' : '') +
    (volNote && !usePoly ? `Routed volume — ${volNote.replace(/^volume:\s*/,'')}. ` : '') +
    (RS ? `${RS.size.toLocaleString()} trips carry a calculated route.` +
          (noRoute ? ` ${noRoute.toLocaleString()} of the drawn selection has no route and is not shown.` : '')
        : 'Route geometry not loaded.');
}

for (const id of ['scope','scen','day','dmin','dmax']) document.getElementById(id).addEventListener('change', apply);
document.querySelectorAll('.chip').forEach(c=>c.addEventListener('click',()=>{
  const [a,b]=c.dataset.band.split(',');
  document.getElementById('dmin').value=a; document.getElementById('dmax').value=(+b>900?999:b);
  apply();
}));
load();
