"""Try creating a requirement DIRECTLY inside a module by setting
nav:parent to the module URL (instead of a folder URL).
"""
import sys, os, json, time, urllib.parse, re
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

run_tag = time.strftime("%H%M%S")
mod = c.create_module(project_url, f"InModule-{run_tag}")
mod_url = mod["url"]
print(f"Module: {mod_url}")
shapes = c.get_artifact_shapes(project_url)
shape = next(s["url"] for s in shapes if s["name"].lower() == "system requirement")

encoded_pa = urllib.parse.quote(project_area_url, safe="")
factory_url = f"{c.base_url}/requirementFactory?projectURL={encoded_pa}"

# Variant A: nav:parent = module URL
title = f"In-module Req A {run_tag}"
rdf_A = f'''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:oslc_rm="http://open-services.net/ns/rm#"
         xmlns:oslc="http://open-services.net/ns/core#"
         xmlns:nav="http://jazz.net/ns/rm/navigation#">
  <oslc_rm:Requirement>
    <dcterms:title>{title}</dcterms:title>
    <oslc:instanceShape rdf:resource="{shape}"/>
    <nav:parent rdf:resource="{mod_url}"/>
  </oslc_rm:Requirement>
</rdf:RDF>'''

print("\n[A] POST with nav:parent=module URL")
resp = c.session.post(
    factory_url,
    data=rdf_A.encode("utf-8"),
    headers={
        "Content-Type": "application/rdf+xml",
        "Accept": "application/rdf+xml",
        "OSLC-Core-Version": "2.0",
        "X-Requested-With": "XMLHttpRequest",
    },
    timeout=30,
)
print(f"  status: {resp.status_code}, Location: {resp.headers.get('Location')}")
if resp.status_code != 201:
    print(f"  body: {resp.text[:500]}")

# Variant B: factory URL with &moduleURI=...
factory_with_mod = f"{factory_url}&moduleURI={urllib.parse.quote(mod_url, safe='')}"
title = f"In-module Req B {run_tag}"
folder = c.find_folder(project_url, "InModule Test") or c.create_folder(project_url, "InModule Test")
rdf_B = f'''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:oslc_rm="http://open-services.net/ns/rm#"
         xmlns:oslc="http://open-services.net/ns/core#"
         xmlns:nav="http://jazz.net/ns/rm/navigation#">
  <oslc_rm:Requirement>
    <dcterms:title>{title}</dcterms:title>
    <oslc:instanceShape rdf:resource="{shape}"/>
    <nav:parent rdf:resource="{folder['url']}"/>
  </oslc_rm:Requirement>
</rdf:RDF>'''

print(f"\n[B] POST with &moduleURI=... in factory URL")
resp = c.session.post(
    factory_with_mod,
    data=rdf_B.encode("utf-8"),
    headers={
        "Content-Type": "application/rdf+xml",
        "Accept": "application/rdf+xml",
        "OSLC-Core-Version": "2.0",
        "X-Requested-With": "XMLHttpRequest",
    },
    timeout=30,
)
print(f"  status: {resp.status_code}, Location: {resp.headers.get('Location')}")
if resp.status_code != 201:
    print(f"  body: {resp.text[:500]}")

# Variant C: factory URL with &parent=<module url>
factory_with_parent = f"{factory_url}&parent={urllib.parse.quote(mod_url, safe='')}"
print(f"\n[C] POST with &parent=<module URL> in factory URL")
resp = c.session.post(
    factory_with_parent,
    data=rdf_A.encode("utf-8"),  # body has nav:parent=module too
    headers={
        "Content-Type": "application/rdf+xml",
        "Accept": "application/rdf+xml",
        "OSLC-Core-Version": "2.0",
        "X-Requested-With": "XMLHttpRequest",
    },
    timeout=30,
)
print(f"  status: {resp.status_code}, Location: {resp.headers.get('Location')}")

# Re-fetch module and see if anything was bound
r = c.session.get(mod_url, headers={"Accept":"application/rdf+xml","OSLC-Core-Version":"2.0"}, timeout=30)
uses = re.findall(r'oslc_rm:uses\s+rdf:resource="([^"]+)"', r.text)
print(f"\nModule now has {len(uses)} oslc_rm:uses entries")
for u in uses:
    print(f"  - {u}")
