"""Rewrite every ST_Distance_Sphere(ST_Point(A,B), ST_Point(C,D)) to the correct mdist(A,B,C,D)
and insert the metric macro into each script. Balanced-paren aware, so window-function args
like ST_Point(lag(lon) OVER w, lag(lat) OVER w) are handled correctly.
"""
import os, shutil, re

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
TARGETS = ["02_legs.py", "03_trips.py", "05_bike_potential.py", "06_stays.py",
           "07_full.py", "10_suburb.py", "12_suburb2.py", "14_platform_build.py"]

MACRO = '''
# ---- canonical metric distance (metres) ----
# ST_Distance_Sphere does NOT scale longitude by cos(latitude) and mis-scales latitude too:
# at Budapest it overstates east-west by up to +48% and understates north-south by ~-5.5%.
# This WGS84 series matches the EPSG:23700 projection to 0.005% and costs only arithmetic.
con.execute("""CREATE OR REPLACE MACRO mdist(lon_a, lat_a, lon_b, lat_b) AS
  sqrt(
    power((lat_b - lat_a) * (111132.92 - 559.82*cos(2*radians((lat_a+lat_b)/2))
                              + 1.175*cos(4*radians((lat_a+lat_b)/2))), 2)
  + power((lon_b - lon_a) * (111412.84*cos(radians((lat_a+lat_b)/2))
                              - 93.5*cos(3*radians((lat_a+lat_b)/2))), 2)
  )""")
'''


def balanced(s, i):
    """i points at '('; return index of the matching ')'."""
    depth = 0
    for k in range(i, len(s)):
        if s[k] == '(':
            depth += 1
        elif s[k] == ')':
            depth -= 1
            if depth == 0:
                return k
    raise ValueError("unbalanced parentheses")


def find_calls(s):
    out = []
    key = "ST_Distance_Sphere("
    i = 0
    while True:
        i = s.find(key, i)
        if i < 0:
            break
        op = i + len("ST_Distance_Sphere")
        cl = balanced(s, op)
        inner = s[op + 1:cl]
        p1 = inner.find("ST_Point(")
        c1 = balanced(inner, p1 + len("ST_Point"))
        a = inner[p1 + len("ST_Point("):c1].strip()
        rest = inner[c1 + 1:]
        p2 = rest.find("ST_Point(")
        c2 = balanced(rest, p2 + len("ST_Point"))
        b = rest[p2 + len("ST_Point("):c2].strip()
        out.append((i, cl + 1, a, b))
        i = cl + 1
    return out


total = 0
for name in TARGETS:
    path = f"{D}/scripts/{name}"
    src = open(path).read()
    calls = find_calls(src)
    if not calls:
        print(f"{name:26s} no calls")
        continue
    shutil.copy(path, path + ".bal.bak")
    # replace back-to-front so earlier indices stay valid
    for (start, end, a, b) in reversed(calls):
        src = src[:start] + f"mdist({a}, {b})" + src[end:]
    # insert the macro once, right after the spatial extension is loaded
    if "CREATE OR REPLACE MACRO mdist" not in src:
        m = re.search(r"^.*LOAD spatial.*$", src, re.M)
        if m:
            src = src[:m.end()] + MACRO + src[m.end():]
        else:
            print(f"  !! {name}: no 'LOAD spatial' anchor - macro NOT inserted")
    open(path, "w").write(src)
    total += len(calls)
    print(f"{name:26s} rewrote {len(calls)} call(s): " +
          ", ".join(f"({a[:18]}...|{b[:18]}...)" for _, _, a, b in calls[:2]))

print(f"\ntotal rewrites: {total}")
