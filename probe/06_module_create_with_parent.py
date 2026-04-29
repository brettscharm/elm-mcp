"""Try various module-creation payloads to find what DNG actually accepts.

Hypotheses:
1. Module must include <nav:parent> folder reference (currently missing)
2. Module must include <oslc_config:component> for GCM-enabled projects
3. Configuration-Context header is required
"""
import sys, os, json, urllib.parse, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from doors_client import DOORSNextClient

c = DOORSNextClient(os.environ["DOORS_URL"], os.environ["DOORS_USERNAME"], os.environ["DOORS_PASSWORD"])
c.authenticate()

with open(os.path.join(os.path.dirname(__file__), "SANDBOX_PROJECTS.json")) as f:
    sandbox = json.load(f)

project_url = sandbox["dng"]["services_url"]
project_area_id = sandbox["dng"]["project_area_id"]
project_area_url = f"{c.base_url}/process/project-areas/{project_area_id}"

# Get/create a folder to use as parent
folder_name = "[AI Generated] MCP Diag Folder"
folder = c.find_folder(project_url, folder_name) or c.create_folder(project_url, folder_name)
print(f"Folder: {folder}")
folder_url = folder["url"]

# Get Module shape
shapes = c.get_artifact_shapes(project_url)
mod_shape = next(s["url"] for s in shapes if s["name"].lower() == "module")
print(f"Module shape: {mod_shape}\n")

# Look up the project's component (GCM)
comp_url = None
try:
    r = c.session.get(
        project_url,
        headers={"Accept": "application/rdf+xml", "OSLC-Core-Version": "2.0"},
        timeout=30,
    )
    import re
    m = re.search(r'oslc_config:component\s+rdf:resource="([^"]+)"', r.text)
    if m:
        comp_url = m.group(1)
        print(f"GCM component: {comp_url}")
except Exception as e:
    print(f"  (no component lookup: {e})")

encoded_pa = urllib.parse.quote(project_area_url, safe="")
factory_url = f"{c.base_url}/requirementFactory?projectURL={encoded_pa}"

run_tag = time.strftime("%H%M%S")

def attempt(label, rdf, headers=None):
    h = {
        "Content-Type": "application/rdf+xml",
        "Accept": "application/rdf+xml",
        "OSLC-Core-Version": "2.0",
        "X-Requested-With": "XMLHttpRequest",
    }
    if headers:
        h.update(headers)
    print(f"\n--- {label} ---")
    resp = c.session.post(factory_url, data=rdf.encode("utf-8"), headers=h, timeout=30)
    print(f"  status: {resp.status_code}")
    if resp.status_code == 201:
        print(f"  Location: {resp.headers.get('Location')}")
        return True
    body = resp.text
    import re
    err = re.search(r'<err:errorMessage[^>]*>([^<]+)', body)
    detail = re.search(r'<err:detailedMessage[^>]*>([^<]+)', body)
    print(f"  err: {err.group(1) if err else '?'}")
    print(f"  detail: {detail.group(1)[:200] if detail else '?'}")
    return False

# A: with nav:parent folder
rdf_A = f'''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:oslc_rm="http://open-services.net/ns/rm#"
         xmlns:oslc="http://open-services.net/ns/core#"
         xmlns:nav="http://jazz.net/ns/rm/navigation#">
  <oslc_rm:RequirementCollection>
    <dcterms:title>Diag A {run_tag}</dcterms:title>
    <oslc:instanceShape rdf:resource="{mod_shape}"/>
    <nav:parent rdf:resource="{folder_url}"/>
  </oslc_rm:RequirementCollection>
</rdf:RDF>'''
attempt("A: with nav:parent", rdf_A)

# B: oslc_rm:Requirement type with Module shape (some servers require this)
rdf_B = f'''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:oslc_rm="http://open-services.net/ns/rm#"
         xmlns:oslc="http://open-services.net/ns/core#"
         xmlns:nav="http://jazz.net/ns/rm/navigation#">
  <oslc_rm:Requirement>
    <dcterms:title>Diag B {run_tag}</dcterms:title>
    <oslc:instanceShape rdf:resource="{mod_shape}"/>
    <nav:parent rdf:resource="{folder_url}"/>
  </oslc_rm:Requirement>
</rdf:RDF>'''
attempt("B: oslc_rm:Requirement type", rdf_B)

# C: with oslc_config:component (GCM)
if comp_url:
    rdf_C = f'''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:oslc_rm="http://open-services.net/ns/rm#"
         xmlns:oslc="http://open-services.net/ns/core#"
         xmlns:oslc_config="http://open-services.net/ns/config#"
         xmlns:nav="http://jazz.net/ns/rm/navigation#">
  <oslc_rm:RequirementCollection>
    <dcterms:title>Diag C {run_tag}</dcterms:title>
    <oslc:instanceShape rdf:resource="{mod_shape}"/>
    <nav:parent rdf:resource="{folder_url}"/>
    <oslc_config:component rdf:resource="{comp_url}"/>
  </oslc_rm:RequirementCollection>
</rdf:RDF>'''
    attempt("C: with oslc_config:component", rdf_C)

# D: Use the Collection Creation Factory - which from services.xml is the SAME url but
# the spec says modules should be created via CreationFactory of usage "module".
# Try with usage parameter.
attempt(
    "D: factory + usage=module URL param",
    rdf_A,
    # No-op: same factory URL handles both — included for completeness
)

# E: Maybe the factory needs the folder context? Try POST with folder URL appended.
factory_url_with_folder = f"{factory_url}&parent={urllib.parse.quote(folder_url, safe='')}"
print(f"\n--- E: factory with &parent= ---")
resp = c.session.post(
    factory_url_with_folder,
    data=rdf_A.encode("utf-8"),
    headers={
        "Content-Type": "application/rdf+xml",
        "Accept": "application/rdf+xml",
        "OSLC-Core-Version": "2.0",
        "X-Requested-With": "XMLHttpRequest",
    },
    timeout=30,
)
print(f"  status: {resp.status_code}")
print(f"  body: {resp.text[:300]}")
