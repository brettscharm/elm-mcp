"""Scan DNG projects to find one with modules."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from doors_client import DOORSNextClient

PROBE_DIR = os.path.dirname(__file__)
client = DOORSNextClient(os.environ["DOORS_URL"], os.environ["DOORS_USERNAME"], os.environ["DOORS_PASSWORD"])
client.authenticate()

with open(os.path.join(PROBE_DIR, "all_projects.json")) as f:
    all_projects = json.load(f)

# Try projects in order until we find one with modules
candidates = []
for p in all_projects["dng"][:30]:
    try:
        mods = client.get_modules(p["url"])
        n = len(mods)
        print(f"  [{n:>3}] {p['title']}")
        if n > 0:
            candidates.append({"project": p, "module_count": n, "first_module": mods[0]})
            if len(candidates) >= 5:
                break
    except Exception as e:
        print(f"  [ERR] {p['title']}: {e}")

with open(os.path.join(PROBE_DIR, "module_candidates.json"), "w") as f:
    json.dump(candidates, f, indent=2)
print(f"\nSaved {len(candidates)} candidate projects with modules to probe/module_candidates.json")
