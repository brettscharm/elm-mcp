"""End-to-end live test of the module fix.

Creates a module + 3 requirements bound to it in the
'ELM AI Hub - Bretts Sandbox (Requirements)' project,
then re-fetches the module to verify the bindings stuck.
"""
import sys, os, json, time, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from doors_client import DOORSNextClient

c = DOORSNextClient(os.environ["DOORS_URL"], os.environ["DOORS_USERNAME"], os.environ["DOORS_PASSWORD"])
c.authenticate()

with open(os.path.join(os.path.dirname(__file__), "SANDBOX_PROJECTS.json")) as f:
    sandbox = json.load(f)

dng_project_url = sandbox["dng"]["services_url"]
print(f"Using DNG sandbox: {sandbox['dng']['title']}")
print(f"  url: {dng_project_url}\n")

run_tag = time.strftime("%Y%m%d-%H%M%S")
module_title = f"MCP-Test Module {run_tag}"
folder_name = f"[AI Generated] MCP-Test Folder {run_tag}"

# 1) Create module
print(f"[1] create_module title='{module_title}'")
mod = c.create_module(dng_project_url, module_title)
print(f"    -> {mod}")
assert mod and "error" not in mod, f"create_module failed: {mod}"
module_url = mod["url"]
assert module_url, "module URL missing"

# 2) Create 3 requirements in a folder
shapes = c.get_artifact_shapes(dng_project_url)
shape_map = {s["name"].lower(): s["url"] for s in shapes}
print(f"\n[2] artifact types available: {list(shape_map.keys())[:8]}{'...' if len(shape_map) > 8 else ''}")
shape = shape_map.get("system requirement") or next(iter(shape_map.values()))
print(f"    using shape: {shape}")

folder = c.find_folder(dng_project_url, folder_name) or c.create_folder(dng_project_url, folder_name)
assert folder, "could not create folder"
folder_url = folder["url"]
print(f"    folder: {folder_url}")

req_urls = []
for i in range(1, 4):
    r = c.create_requirement(
        project_url=dng_project_url,
        title=f"Test Requirement {i} ({run_tag})",
        content=f"Body of requirement {i}. Created by MCP module-fix probe.",
        shape_url=shape,
        folder_url=folder_url,
    )
    print(f"    [req {i}] -> {r}")
    assert r and "error" not in r and r.get("url"), f"create_requirement {i} failed"
    req_urls.append(r["url"])

# 3) Bind to module
print(f"\n[3] add_to_module ({len(req_urls)} requirements)")
bind = c.add_to_module(module_url, req_urls)
print(f"    -> {bind}")
assert bind and "error" not in bind, f"add_to_module failed: {bind}"

# 4) Re-fetch module RDF and verify each req URL appears as oslc_rm:uses
print(f"\n[4] verify by re-fetching module RDF")
resp = c.session.get(
    module_url,
    headers={"Accept": "application/rdf+xml", "OSLC-Core-Version": "2.0"},
    timeout=30,
)
rdf = resp.text
uses = set(re.findall(r'oslc_rm:uses\s+rdf:resource="([^"]+)"', rdf))
print(f"    module now has {len(uses)} oslc_rm:uses entries")
for u in req_urls:
    if u in uses:
        print(f"    OK    {u}")
    else:
        print(f"    MISS  {u}")
        sys.exit(1)

print(f"\nSUCCESS — module {module_title} contains all {len(req_urls)} new requirements.")
print(f"View in DNG: {module_url}")
