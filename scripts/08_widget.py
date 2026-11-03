import duckdb, json

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
con = duckdb.connect(f"{D}/db/mobility.duckdb"); con.execute("INSTALL spatial; LOAD spatial;")

BANDS = [(0,2000,'≤2 km','#1a9850'),(2000,5000,'2–5 km','#66bd63'),
         (5000,8000,'5–8 km','#fdae61'),(8000,15000,'8–15 km','#f46d43'),(15000,10**9,'>15 km','#d73027')]

def hist(tag):
    out=[]
    for lo,hi,lab,col in BANDS:
        n = con.execute(f"SELECT count(*) FROM final_{tag} WHERE path_m>{lo} AND path_m<={hi}").fetchone()[0]
        out.append({"label":lab,"n":n,"color":col})
    tot = sum(x["n"] for x in out) or 1
    for x in out: x["pct"] = round(100*x["n"]/tot,1)
    return out

h_aug, h_may = hist("aug12"), hist("may08")

# sample trip lines for the map (bikeable vs not)
rows = con.execute(f"""
  SELECT bikeable, round(path_m)::INT AS m, ST_AsGeoJSON(geom) AS g
  FROM lines_aug12 USING SAMPLE 900 ROWS
""").fetchall()
feats = [{"type":"Feature","properties":{"bikeable":bool(b),"m":m},"geometry":json.loads(g)} for b,m,g in rows]
# polygon
poly = con.execute("SELECT ST_AsGeoJSON(geom) FROM demo_poly").fetchone()[0]

aug = con.execute("SELECT count(*), count(DISTINCT aid), round(100*avg(bikeable::INT),1) FROM final_aug12").fetchone()
may = con.execute("SELECT count(*), count(DISTINCT aid), round(100*avg(bikeable::INT),1) FROM final_may08").fetchone()
cross = con.execute("""SELECT CASE WHEN o_in AND d_in THEN 'internal' WHEN o_in THEN 'origin_in'
   WHEN d_in THEN 'dest_in' ELSE 'through' END cat, count(*) n, sum(bikeable::INT) b
   FROM poly_aug12 WHERE touches GROUP BY 1""").fetchall()
crossmap = {c:(n,b) for c,n,b in cross}

html = f"""<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
 body{{margin:0;font-family:-apple-system,system-ui,sans-serif;color:var(--foreground,#111)}}
 .hd{{font-size:15px;font-weight:650;margin:0 0 2px}} .sub{{font-size:12px;color:var(--muted-foreground,#666);margin-bottom:10px}}
 .row{{display:flex;gap:18px;flex-wrap:wrap;margin-bottom:10px}}
 .card{{border:1px solid var(--border,#ddd);border-radius:8px;padding:8px 12px;min-width:120px}}
 .card .k{{font-size:11px;color:var(--muted-foreground,#666)}} .card .v{{font-size:19px;font-weight:650}}
 #map{{height:430px;width:100%;max-width:780px;border-radius:8px;border:1px solid var(--border,#ddd)}}
 .bar{{display:flex;height:22px;border-radius:5px;overflow:hidden;margin:8px 0 4px;max-width:780px}}
 .bar div{{display:flex;align-items:center;justify-content:center;color:#fff;font-size:10px;font-weight:600}}
 .lg{{font-size:11px;color:var(--muted-foreground,#666);display:flex;gap:12px;flex-wrap:wrap}}
 .dot{{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:4px}}
 table{{border-collapse:collapse;font-size:12px;margin-top:8px}} td,th{{padding:3px 10px 3px 0;text-align:left}}
 th{{color:var(--muted-foreground,#666);font-weight:500}}
</style></head><body>
<p class="hd">Budapest trips — could they have been done by bike?</p>
<p class="sub">Stay-point segmented trips, 12 Aug 2023 (event period) · demo area = inner Pest</p>
<div class="row">
 <div class="card"><div class="k">trips / day</div><div class="v">{aug[0]:,}</div></div>
 <div class="card"><div class="k">devices</div><div class="v">{aug[1]:,}</div></div>
 <div class="card"><div class="k">≤5 km ("bikeable")</div><div class="v">{aug[2]}%</div></div>
 <div class="card"><div class="k">median trip</div><div class="v">6.9 km</div></div>
</div>
<div class="bar">""" + "".join(f'<div style="width:{x["pct"]}%;background:{x["color"]}">{x["pct"]}%</div>' for x in h_aug) + f"""</div>
<div class="lg">""" + "".join(f'<span><span class="dot" style="background:{x["color"]}"></span>{x["label"]} ({x["n"]:,})</span>' for x in h_aug) + f"""</div>
<div id="map" style="margin-top:12px"></div>
<p class="sub" style="margin-top:8px">Sampled 900 trip trajectories · <b>green = ≤5 km (bikeable)</b>, red = longer · grey box = analysis polygon. Traffic <i>through</i> the area is only {round(100*crossmap.get('through',(1,0))[1]/max(crossmap.get('through',(1,1))[0],1),1)}% bikeable; trips <i>internal</i> to it are {round(100*crossmap.get('internal',(1,0))[1]/max(crossmap.get('internal',(1,1))[0],1),1)}%.</p>
<table><tr><th>within area</th><th>trips</th><th>bikeable</th><th>%</th></tr>""" + "".join(
  f"<tr><td>{k}</td><td>{v[0]:,}</td><td>{v[1]:,}</td><td>{round(100*v[1]/v[0],1)}%</td></tr>"
  for k,v in sorted(crossmap.items(), key=lambda kv:-kv[1][0])) + f"""</table>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const trips={json.dumps(feats)}; const poly={poly};
const m=L.map('map',{{zoomControl:true}}).setView([47.497,19.075],12);
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png',{{attribution:'© OpenStreetMap © CARTO',maxZoom:19}}).addTo(m);
L.geoJSON(poly,{{style:{{color:'#888',weight:1.5,fill:false,dashArray:'4 3'}}}}).addTo(m);
L.geoJSON({{type:'FeatureCollection',features:trips}},{{style:f=>({{color:f.properties.bikeable?'#1a9850':'#d73027',weight:f.properties.bikeable?1.6:1,opacity:f.properties.bikeable?0.85:0.35}})}}).addTo(m);
</script></body></html>"""

open(f"{D}/out/preview.html","w").write(html)
print("wrote out/preview.html  |  aug bikeable", aug[2], "% | may bikeable", may[2], "%")
print("crossmap:", crossmap)
