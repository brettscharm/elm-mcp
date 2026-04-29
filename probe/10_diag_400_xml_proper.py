"""Use proper XML parsing (ElementTree) for the module update PUT.

Theory: regex injection corrupted the rdf:parseType="Literal" content
(escaped HTML entities re-served as text). ET-based modification
preserves the original literal node properly.
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import xml.etree.ElementTree as ET
from dotenv import load_dotenv
load_dotenv()
from doors_client import DOORSNextClient

c = DOORSNextClient(os.environ["DOORS_URL"], os.environ["DOORS_USERNAME"], os.environ["DOORS_PASSWORD"])
c.authenticate()

with open(os.path.join(os.path.dirname(__file__), "SANDBOX_PROJECTS.json")) as f:
    sandbox = json.load(f)
project_url = sandbox["dng"]["services_url"]

run_tag = time.strftime("%H%M%S")
mod = c.create_module(project_url, f"Diag-XML-Module {run_tag}")
mod_url = mod["url"]
print(f"Module: {mod_url}")

shapes = c.get_artifact_shapes(project_url)
shape = next(s["url"] for s in shapes if s["name"].lower() == "system requirement")
folder_name = f"Diag XML folder {run_tag}"
folder = c.find_folder(project_url, folder_name) or c.create_folder(project_url, folder_name)
folder_url = folder["url"]
req = c.create_requirement(
    project_url=project_url,
    title=f"Diag XML Req {run_tag}",
    content="diag",
    shape_url=shape, folder_url=folder_url,
)
req_url = req["url"]
print(f"Req: {req_url}")

# GET module RDF
r = c.session.get(
    mod_url,
    headers={"Accept": "application/rdf+xml", "OSLC-Core-Version": "2.0"},
    timeout=30,
)
etag = r.headers.get("ETag")
print(f"GET ETag: {etag}, bytes: {len(r.content)}")

# Parse with ET, register namespaces so ET serializes them as the originals
namespaces = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "acp": "http://jazz.net/ns/acp#",
    "public_rm_10": "http://www.ibm.com/xmlns/rm/public/1.0/",
    "calm": "http://jazz.net/xmlns/prod/jazz/calm/1.0/",
    "jazz_rm": "http://jazz.net/ns/rm#",
    "acc": "http://open-services.net/ns/core/acc#",
    "process": "http://jazz.net/ns/process#",
    "dcterms": "http://purl.org/dc/terms/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "oslc": "http://open-services.net/ns/core#",
    "nav": "http://jazz.net/ns/rm/navigation#",
    "oslc_config": "http://open-services.net/ns/config#",
    "oslc_rm": "http://open-services.net/ns/rm#",
}
for prefix, uri in namespaces.items():
    ET.register_namespace(prefix, uri)

root = ET.fromstring(r.content)
RDF_NS = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
RM_NS = "{http://open-services.net/ns/rm#}"

# Find the Description with rdf:about == module URL
target_desc = None
for desc in root.findall(f"{RDF_NS}Description"):
    if desc.get(f"{RDF_NS}about") == mod_url:
        target_desc = desc
        break
if target_desc is None:
    # fallback: first Description
    target_desc = root.find(f"{RDF_NS}Description")
print(f"Found target Description: {target_desc is not None}")

# Append <oslc_rm:uses rdf:resource="<req_url>"/>
new_uses = ET.SubElement(target_desc, f"{RM_NS}uses")
new_uses.set(f"{RDF_NS}resource", req_url)

# Serialize
new_body = ET.tostring(root, encoding="utf-8", xml_declaration=True)
print(f"\nSerialized len: {len(new_body)}")
print(f"First 1200 bytes:")
print(new_body[:1200].decode("utf-8"))

# PUT
resp = c.session.put(
    mod_url,
    data=new_body,
    headers={
        "Content-Type": "application/rdf+xml",
        "Accept": "application/rdf+xml",
        "OSLC-Core-Version": "2.0",
        "If-Match": etag,
        "X-Requested-With": "XMLHttpRequest",
    },
    timeout=30,
)
print(f"\nPUT status: {resp.status_code}")
print(f"body: {resp.text[:1500]}")

if resp.status_code in (200, 204):
    # verify
    r2 = c.session.get(mod_url, headers={"Accept":"application/rdf+xml","OSLC-Core-Version":"2.0"}, timeout=30)
    import re
    found = req_url in r2.text
    print(f"\nVerified by re-GET: req URL in module RDF: {found}")
    print(f"  oslc_rm:uses count: {len(re.findall(r'oslc_rm:uses', r2.text))}")
