"""Convert a Mapbox style JSON into a MapLibre-loadable style with absolute URLs."""
import json, urllib.request, os

TOK = open('/tmp/mbtok.txt').read().strip()
D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"

d = json.load(open('/tmp/mbstyle.json'))


def fix(u):
    if not isinstance(u, str) or not u.startswith('mapbox://'):
        return u
    rest = u[len('mapbox://'):]
    if rest.startswith('sprites/'):
        # mapbox://sprites/{user}/{style}/{hash} — the trailing hash is an internal version
        # stamp, NOT a URL path. The real endpoint is .../styles/v1/{user}/{style}/sprite;
        # the map loader then appends '.json'/'.png' (and '@2x' for retina). Keeping the hash
        # produces a 404 and silently drops every sprite icon.
        p = rest[len('sprites/'):].split('/')
        return f"https://api.mapbox.com/styles/v1/{p[0]}/{p[1]}/sprite?access_token={TOK}"
    if rest.startswith('fonts/'):
        return f"https://api.mapbox.com/fonts/v1/{rest[len('fonts/'):]}?access_token={TOK}"
    return f"https://api.mapbox.com/v4/{rest}.json?access_token={TOK}"


def walk(o):
    if isinstance(o, dict):
        return {k: (fix(v) if isinstance(v, str) else walk(v)) for k, v in o.items()}
    if isinstance(o, list):
        return [walk(x) for x in o]
    return o


d = walk(d)
# drop mapbox-only metadata that MapLibre ignores anyway
for k in ('metadata', 'owner', 'created', 'modified', 'id', 'draft', 'visibility'):
    d.pop(k, None)
d['name'] = 'Bicyclize Monochrome'

os.makedirs(f"{D}/platform", exist_ok=True)
json.dump(d, open(f"{D}/platform/style.json", 'w'))
print("wrote platform/style.json")

for k, v in d.get('sources', {}).items():
    print("source:", k, "->", v.get('url'))
print("glyphs:", d.get('glyphs'))
print("sprite:", d.get('sprite'))


def head(url):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'check'}), timeout=30)
        return f"HTTP {r.status}  {r.headers.get('content-type')}  {r.headers.get('content-length')}B"
    except Exception as e:
        return f"FAIL {e}"


print("\n-- reachability --")
for k, v in d.get('sources', {}).items():
    u = v.get('url')
    print(" tilejson:", head(u))
    if u and 'api.mapbox.com' in u:
        tj = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'check'}), timeout=30))
        print("   tiles template:", tj.get('tiles', [''])[0])
        print("   min/max zoom:", tj.get('minzoom'), tj.get('maxzoom'))
print(" glyphs :", head(d.get('glyphs', '').replace('{fontstack}', 'DIN%20Pro%20Medium').replace('{range}', '0-255')))
sp = d.get('sprite', '')
if sp:
    base, _, qs = sp.partition('?')
    print(" sprite json:", head(base + '.json' + (('?'+qs) if qs else '')))
    print(" sprite png :", head(base + '.png'  + (('?'+qs) if qs else '')))
