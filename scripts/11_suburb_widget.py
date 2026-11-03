import duckdb, json
D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
con = duckdb.connect(f"{D}/db/mobility.duckdb"); con.execute("INSTALL spatial; LOAD spatial;")
AGG_KM = 40
CAND = f"suburb_origin AND o_to_bp_m<={AGG_KM*1000} AND o_to_stn<=3000 AND d_to_stn<=3000 AND od_m>8000"
BPL = "d_lat BETWEEN 47.30 AND 47.66 AND d_lon BETWEEN 18.90 AND 19.40"

lines = con.execute(f"""SELECT o_lon,o_lat,d_lon,d_lat, round(od_m/1000,1) km, o_stn, d_stn,
   ({BPL}) AS dest_bp FROM bt WHERE {CAND}""").fetchall()
feats = [{"type":"Feature","properties":{"km":k,"o":o,"d":dd,"inbp":bool(b)},
          "geometry":{"type":"LineString","coordinates":[[a,b_],[c,e]]}}
         for a,b_,c,e,k,o,dd,b in lines]

stns = con.execute(f"""SELECT o_stn, count(*) n, avg(o_lon) lon, avg(o_lat) lat
   FROM bt WHERE {CAND} GROUP BY 1 ORDER BY n DESC""").fetchall()
sfeats = [{"type":"Feature","properties":{"name":nm,"n":n},
           "geometry":{"type":"Point","coordinates":[lo,la]}} for nm,n,lo,la in stns]

stats = con.execute(f"""SELECT
  count(*) FILTER (WHERE suburb_origin) a,
  count(*) FILTER (WHERE suburb_origin AND o_to_bp_m<={AGG_KM*1000}) b,
  count(*) FILTER (WHERE {CAND}) c,
  count(*) FILTER (WHERE suburb_origin AND od_m<=5000) d,
  round(median(o_to_stn)/1000,2) e FROM bt""").fetchone()

html = f"""<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
 body{{margin:0;font-family:-apple-system,system-ui,sans-serif;color:var(--foreground,#111)}}
 .hd{{font-size:15px;font-weight:650;margin:0 0 2px}} .sub{{font-size:12px;color:var(--muted-foreground,#666);margin-bottom:10px}}
 .row{{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:10px}}
 .card{{border:1px solid var(--border,#ddd);border-radius:8px;padding:8px 12px;min-width:110px}}
 .card .k{{font-size:11px;color:var(--muted-foreground,#666)}} .card .v{{font-size:19px;font-weight:650}}
 #map{{height:440px;width:100%;max-width:780px;border-radius:8px;border:1px solid var(--border,#ddd)}}
 .lg{{font-size:11px;color:var(--muted-foreground,#666);display:flex;gap:14px;flex-wrap:wrap;margin-top:6px}}
 .dot{{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:4px}}
 table{{border-collapse:collapse;font-size:12px;margin-top:8px}} td,th{{padding:3px 12px 3px 0;text-align:left}}
 th{{color:var(--muted-foreground,#666);font-weight:500}}
</style></head><body>
<p class="hd">Suburb trips that could be done by bike + train</p>
<p class="sub">May 8 2023 (baseline) · origin outside Budapest, within 40 km · both ends ≤3 km from a rail station · trip >8 km (too far to bike direct)</p>
<div class="row">
 <div class="card"><div class="k">suburb-origin trips</div><div class="v">{stats[0]:,}</div></div>
 <div class="card"><div class="k">in agglomeration (≤40 km)</div><div class="v">{stats[1]:,}</div></div>
 <div class="card"><div class="k">bike+train candidates</div><div class="v">{stats[2]:,}</div></div>
 <div class="card"><div class="k">median access to station</div><div class="v">{stats[4]} km</div></div>
 <div class="card"><div class="k">short trips (≤5 km, bike direct)</div><div class="v">{stats[3]:,}</div></div>
</div>
<div id="map"></div>
<div class="lg">
 <span><span class="dot" style="background:#1a9850"></span>destination in Budapest</span>
 <span><span class="dot" style="background:#f46d43"></span>destination outside Budapest</span>
 <span><span class="dot" style="background:#2E3B8E;border-radius:50%"></span>origin rail station (size = candidates)</span>
</div>
<table><tr><th>top origin stations</th><th>candidates</th></tr>""" + "".join(
  f"<tr><td>{nm}</td><td>{n}</td></tr>" for nm,n,lo,la in stns[:12]) + f"""</table>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const trips={json.dumps(feats)}, stns={json.dumps(sfeats)};
const m=L.map('map').setView([47.52,19.02],11);
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png',{{attribution:'© OpenStreetMap © CARTO',maxZoom:19}}).addTo(m);
L.geoJSON({{type:'FeatureCollection',features:trips}},{{style:f=>({{color:f.properties.inbp?'#1a9850':'#f46d43',weight:1.1,opacity:0.5}})}}).addTo(m);
stns.forEach(s=>{{L.circleMarker([s.geometry.coordinates[1],s.geometry.coordinates[0]],
  {{radius:Math.max(4,Math.sqrt(s.properties.n)*1.5),color:'#2E3B8E',fillColor:'#2E3B8E',fillOpacity:.55,weight:1}})
  .bindTooltip(s.properties.name+' — '+s.properties.n+' candidates').addTo(m);}});
</script></body></html>"""
open(f"{D}/out/suburb_preview.html","w").write(html)
print("wrote out/suburb_preview.html | candidates:", stats[2], "| stations:", len(stns))
