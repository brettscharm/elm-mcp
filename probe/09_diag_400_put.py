"""Diagnose the 400 from add_to_module PUT.

Re-fetches a freshly created (still empty) module's RDF and tries the PUT
with full error capture, multiple variants.
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
project_url = sandbox["dng"]["services_url"]

# Make a fresh module + 1 requirement to play with
run_tag = time.strftime("%H%M%S")
mod = c.create_module(project_url, f"Diag-PUT-Module {run_tag}")
print(f"Module: {mod['url']}")
mod_url = mod["url"]

shapes = c.get_artifact_shapes(project_url)
shape = next(s["url"] for s in shapes if s["name"].lower() == "system requirement")

folder_name = f"Diag PUT folder {run_tag}"
folder = c.find_folder(project_url, folder_name) or c.create_folder(project_url, folder_name)
folder_url = folder["url"]

req = c.create_requirement(
    project_url=project_url,
    title=f"Diag PUT Req {run_tag}",
    content="diag",
    shape_url=shape,
    folder_url=folder_url,
)
req_url = req["url"]
print(f"Req: {req_url}\n")

# GET module RDF
r = c.session.get(
    mod_url,
    headers={"Accept": "application/rdf+xml", "OSLC-Core-Version": "2.0"},
    timeout=30,
)
etag = r.headers.get("ETag")
rdf = r.text
print(f"GET module: {r.status_code}, ETag={etag!r}, bytes={len(rdf)}")
print(f"\n--- ORIGINAL module RDF ---")
print(rdf)
print()

# Variant 1: simple regex inject
new_uses = f'    <oslc_rm:uses rdf:resource="{req_url}"/>\n'
v1 = re.sub(
    r'(<rdf:Description[^>]*>)(.*?)(\s*</rdf:Description>)',
    lambda m: f'{m.group(1)}{m.group(2)}\n{new_uses}{m.group(3)}',
    rdf, count=1, flags=re.DOTALL,
)

def try_put(label, body):
    print(f"\n--- {label} ---")
    print(body[:1500])
    print(f"  ... ({len(body)} total bytes)")
    resp = c.session.put(
        mod_url,
        data=body.encode("utf-8"),
        headers={
            "Content-Type": "application/rdf+xml",
            "Accept": "application/rdf+xml",
            "OSLC-Core-Version": "2.0",
            "If-Match": etag,
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=30,
    )
    print(f"  status: {resp.status_code}")
    print(f"  body: {resp.text[:1500]}")
    return resp.status_code

try_put("V1: regex-injected oslc_rm:uses", v1)
