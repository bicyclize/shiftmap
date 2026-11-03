"""Replace the hardcoded 75000 m/deg longitude scale in span_m with the correct cos(lat) form."""
import re

D = "/Users/peterbiczok/Obsidian_Notes/General_Vault/ReadWrite/Projects/BicyclizeInternational/Transport analysis"
TARGETS = ["06_stays.py", "07_full.py", "10_suburb.py", "14_platform_build.py"]

for name in TARGETS:
    p = f"{D}/scripts/{name}"
    s = open(p).read()
    new, n = re.subn(r"\)\s*\*\s*75000\s*,", ")*111320*cos(radians(lat)),", s)
    if n:
        open(p, "w").write(new)
    print(f"{name:26s} span_m fixed: {n}  (75000 -> 111320*cos(radians(lat)))")

print("\nremaining 75000 in scripts:")
import subprocess
print(subprocess.run(["grep", "-rn", "75000", f"{D}/scripts/"], capture_output=True, text=True).stdout or "  none")
