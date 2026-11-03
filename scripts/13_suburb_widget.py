import duckdb, json
D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
con = duckdb.connect(f"{D}/db/mobility.duckdb"); con.execute("INSTALL spatial; LOAD spatial;")

rows = con.execute("""SELECT c.o_lon,c.o_lat,c.d_lon,c.d_lat, round(c.od_m/1000,1) km, l.lvl, c.o_stn, c.d_stn
  FROM cand c JOIN cand_lvl l USING (aid,trip_seq)""").fetchall()
KIND = {2:'direct',1:'one_change',0:'no_link'}
feats = [{"type":"Feature","properties":{"km":k,"k":KIND[lv],"o":o,"d":dd},
          "geometry":{"type":"LineString","coordinates":[[a,b],[c,e]]}} for a,b,c,e,k,lv,o,dd in rows]

stn = con.execute("""SELECT c.o_stn, count(*) n, count(*) FILTER (WHERE l.lvl>=1) linked,
    avg(c.o_lon) lon, avg(c.o_lat) lat FROM cand c JOIN cand_lvl l USING (aid,trip_seq)
  GROUP BY 1 ORDER BY n DESC LIMIT 30""").fetchall()
sfeats = [{"type":"Feature","properties":{"name":nm,"n":n,"lk":lk},
           "geometry":{"type":"Point","coordinates":[lo,la]}} for nm,n,lk,lo,la in stn]

LOC = "bt.o_lat IS NOT NULL AND (NOT bt.o_in_bp) AND (NOT bt.d_in_bp) AND bt.o_to_bp_m<=40000"
bands = con.execute(f"""SELECT band, count(*) n FROM (SELECT CASE WHEN od_m<=2000 THEN '≤2 km'
    WHEN od_m<=5000 THEN '2–5 km' WHEN od_m<=8000 THEN '5–8 km' WHEN od_m<=15000 THEN '8–15 km'
    ELSE '>15 km' END band FROM bt WHERE {LOC}) GROUP BY 1""").fetchall()
order = ['≤2 km','2–5 km','5–8 km','8–15 km','>15 km']
bmap = dict(bands); tot = sum(bmap.values()) or 1
cols = ['#1a9850','#66bd63','#fdae61','#f46d43','#d73027']
bars = "".join(f'<div style="width:{100*bmap.get(b,0)/tot:.1f}%;background:{c}">{100*bmap.get(b,0)/tot:.0f}%</div>' for b,c in zip(order,cols))
lgd = "".join(f'<span><span class="dot" style="background:{c}"></span>{b} ({bmap.get(b,0):,})</span>' for b,c in zip(order,cols))

s = con.execute("SELECT (SELECT count(*) FROM cand) cand, (SELECT count(*) FROM cand_lvl WHERE lvl>=1) reach").fetchone()
locn = con.execute(f"SELECT count(*), round(100.0*avg((od_m<=5000)::INT),1) FROM bt WHERE {LOC}").fetchone()

html = f"""<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
 body{{margin:0;font-family:-apple-system,system-ui,sans-serif;color:var(--foreground,#111)}}
 .hd{{font-size:15px;font-weight:650;margin:0 0 2px}} .sub{{font-size:12px;color:var(--muted-foreground,#666);margin-bottom:10px}}
 .row{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:8px}}
 .card{{border:1px solid var(--border,#ddd);border-radius:8px;padding:7px 11px;min-width:104px}}
 .card .k{{font-size:11px;color:var(--muted-foreground,#666)}} .card .v{{font-size:18px;font-weight:650}}
 #map{{height:420px;width:100%;max-width:780px;border-radius:8px;border:1px solid var(--border,#ddd)}}
 .bar{{display:flex;height:20px;border-radius:5px;overflow:hidden;margin:6px 0 4px;max-width:780px}}
 .bar div{{display:flex;align-items:center;justify-content:center;color:#fff;font-size:10px;font-weight:600}}
 .lg{{font-size:11px;color:var(--muted-foreground,#666);display:flex;gap:12px;flex-wrap:wrap}}
 .dot{{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:4px}}
 h4{{font-size:12px;margin:14px 0 4px;font-weight:600}}
</style></head><body>
<p class="hd">Suburb trips → could be done by bike + train</p>
<p class="sub">May 8 2023 · origin outside Budapest ≤40 km · bike access ≤2.5 km to a suburban rail station · egress ≤1.3 km · trip &gt;8 km</p>
<div class="row">
 <div class="card"><div class="k">bike+train candidates</div><div class="v">{s[0]:,}</div></div>
 <div class="card"><div class="k">with rail/metro link</div><div class="v">{s[1]:,}</div></div>
 <div class="card"><div class="k">reachable (≤1 change)</div><div class="v">{100*s[1]/s[0]:.0f}%</div></div>
 <div class="card"><div class="k">suburban local trips</div><div class="v">{locn[0]:,}</div></div>
 <div class="card"><div class="k">local trips ≤5 km</div><div class="v">{locn[1]}%</div></div>
</div>
<div id="map"></div>
<div class="lg" style="margin-top:6px">
 <span><span class="dot" style="background:#1a9850"></span>direct train link</span>
 <span><span class="dot" style="background:#2E3B8E"></span>link with one change</span>
 <span><span class="dot" style="background:#d73027"></span>no rail link</span>
 <span><span class="dot" style="background:#444;border-radius:50%"></span>origin station (size = candidates)</span>
</div>
<h4>Suburban local trips (both ends outside Budapest) — how long?</h4>
<div class="bar">{bars}</div>
<div class="lg">{lgd}</div>
<p class="sub" style="margin-top:8px">Median local suburb trip: <b>2.4 km</b> straight-line — <b>{locn[1]}% are ≤5 km</b>, i.e. most could have been a bike outright.</p>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const trips={json.dumps(feats)}, stns={json.dumps(sfeats)};
const CM={{direct:'#1a9850',one_change:'#2E3B8E',no_link:'#d73027'}};
const m=L.map('map').setView([47.55,19.05],10);
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png',{{attribution:'© OpenStreetMap © CARTO',maxZoom:19}}).addTo(m);
L.geoJSON({{type:'FeatureCollection',features:trips}},{{style:f=>({{color:CM[f.properties.k],weight:1.2,opacity:0.55}})}}).addTo(m);
stns.forEach(s=>{{const lk=s.properties.lk/s.properties.n;
  L.circleMarker([s.geometry.coordinates[1],s.geometry.coordinates[0]],
  {{radius:Math.max(4,Math.sqrt(s.properties.n)*1.4),color:'#444',fillColor:'#444',fillOpacity:0.15+0.5*lk,weight:1}})
  .bindTooltip(s.properties.name+' — '+s.properties.n+' candidates, '+s.properties.lk+' with rail link').addTo(m);}});
</script></body></html>"""
open(f"{D}/out/suburb_preview.html","w").write(html)
print("wrote out/suburb_preview.html | candidates:", s[0], "reachable:", s[1], "| local trips:", locn[0], "le5km:", locn[1], "%")
print("local bands:", bmap)
