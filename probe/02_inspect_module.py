"""Probe: pick a project with modules, fetch one module's RDF, and dump the
raw bytes so we can see exactly how DNG models module->requirement bindings.

This is the key probe for fixing the 'requirements going into folders not
modules' bug.
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from doors_client import DOORSNextClient

URL = os.environ["DOORS_URL"]
USER = os.environ["DOORS_USERNAME"]
PWD = os.environ["DOORS_PASSWORD"]

PROBE_DIR = os.path.dirname(__file__)

client = DOORSNextClient(URL, USER, PWD)
client.authenticate()

# Pick "Vehicle CyberSecurity (Requirements)" - real-looking name from README
with open(os.path.join(PROBE_DIR, "all_projects.json")) as f:
    all_projects = json.load(f)

target_name = "Sandbox_Requirements"
project = next((p for p in all_projects["dng"] if p["title"] == target_name), None)
if not project:
    # fall back to first project that has modules
    print(f"Specific project '{target_name}' not found, will scan...")
    project = all_projects["dng"][2]  # third one

print(f"Using project: {project['title']}")
print(f"  url: {project['url']}\n")

# Get modules
modules = client.get_modules(project["url"])
print(f"Found {len(modules)} module(s) (showing first 10):")
for m in modules[:10]:
    print(f"  - {m.get('title')!r}  url={m.get('url')}  source={m.get('source')}")

with open(os.path.join(PROBE_DIR, "modules.json"), "w") as f:
    json.dump(modules, f, indent=2)

if not modules:
    print("\nNO modules in this project - try a different project")
    sys.exit(0)

# Pick first real module
module = modules[0]
module_url = module["url"]
print(f"\n=== Inspecting module: {module['title']} ===\n")

# Fetch raw RDF for the module
print("--- Raw module RDF ---")
resp = client.session.get(
    module_url,
    headers={
        "Accept": "application/rdf+xml",
        "OSLC-Core-Version": "2.0",
    },
    timeout=30,
)
print(f"  status: {resp.status_code}")
print(f"  content-type: {resp.headers.get('content-type')}")
print(f"  ETag: {resp.headers.get('ETag')}")
print(f"  bytes: {len(resp.content)}")

with open(os.path.join(PROBE_DIR, "module_raw.xml"), "wb") as f:
    f.write(resp.content)
print(f"  saved -> probe/module_raw.xml\n")

# Try fetching the module structure with various Accept headers
print("--- Module structure probes ---")
for accept in [
    "application/rdf+xml",
    "application/x-jazz-rm-module-structure+json",
    "application/x-oslc-rm-module-structure+xml",
    "application/json",
]:
    try:
        r = client.session.get(
            module_url,
            headers={"Accept": accept, "OSLC-Core-Version": "2.0"},
            timeout=30,
        )
        print(f"  Accept: {accept!r:55s} -> {r.status_code}  ct={r.headers.get('content-type','?')}  bytes={len(r.content)}")
    except Exception as e:
        print(f"  Accept: {accept!r:55s} -> ERROR {e}")

# Try the structure endpoint variants DNG often supports
print("\n--- /structure & related endpoints ---")
for suffix in ["/structure", "?_structure=true", "?oslc.properties=*", "/contents"]:
    try:
        u = module_url + suffix
        r = client.session.get(
            u,
            headers={"Accept": "application/rdf+xml", "OSLC-Core-Version": "2.0"},
            timeout=30,
        )
        print(f"  GET {suffix!r:30s} -> {r.status_code}  ct={r.headers.get('content-type','?')}  bytes={len(r.content)}")
        if r.status_code == 200 and len(r.content) > 100:
            outname = "module_" + suffix.replace("/", "_").replace("?", "_").replace("=", "_") + ".xml"
            outpath = os.path.join(PROBE_DIR, outname.strip("_"))
            with open(outpath, "wb") as f:
                f.write(r.content)
            print(f"    saved -> {outpath}")
    except Exception as e:
        print(f"  GET {suffix!r:30s} -> ERROR {e}")
