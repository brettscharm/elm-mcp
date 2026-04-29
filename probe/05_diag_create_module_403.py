"""Diagnose the 403 from create_module on the sandbox project.

Captures the raw POST request and full response body — the existing
create_module wraps the error too tightly to see what's wrong.
"""
import sys, os, json, urllib.parse
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

# Find Module shape
shapes = c.get_artifact_shapes(project_url)
print(f"Got {len(shapes)} artifact shapes:")
mod_shape = None
for s in shapes:
    print(f"  - {s['name']!r}  url={s['url']}")
    if s["name"].lower() == "module":
        mod_shape = s["url"]
print(f"\nModule shape: {mod_shape}\n")

if not mod_shape:
    print("ERROR: no Module shape found - sandbox may not allow modules")
    sys.exit(1)

# Replicate create_module's POST and dump response
title = "[AI Generated] Diag Test Module"
desc_xhtml = "<p>diagnostic</p>"
rdf = f'''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:oslc_rm="http://open-services.net/ns/rm#"
         xmlns:oslc="http://open-services.net/ns/core#">
  <oslc_rm:RequirementCollection>
    <dcterms:title>{title}</dcterms:title>
    <dcterms:description rdf:parseType="Literal">
      <div xmlns="http://www.w3.org/1999/xhtml"><p><strong>[AI Generated]</strong></p>{desc_xhtml}</div>
    </dcterms:description>
    <oslc:instanceShape rdf:resource="{mod_shape}"/>
  </oslc_rm:RequirementCollection>
</rdf:RDF>'''

encoded_pa = urllib.parse.quote(project_area_url, safe="")
url = f"{c.base_url}/requirementFactory?projectURL={encoded_pa}"

print(f"POST {url}")
print(f"\n--- request body ---\n{rdf}\n")

resp = c.session.post(
    url,
    data=rdf.encode("utf-8"),
    headers={
        "Content-Type": "application/rdf+xml",
        "Accept": "application/rdf+xml",
        "OSLC-Core-Version": "2.0",
        "X-Requested-With": "XMLHttpRequest",
    },
    timeout=30,
)
print(f"--- response ---")
print(f"status: {resp.status_code}")
print(f"location: {resp.headers.get('Location')}")
for k in ("oslc-core-version", "content-type", "x-com-ibm-team-repository-web-auth-msg"):
    if k in resp.headers or k in (h.lower() for h in resp.headers):
        print(f"{k}: {resp.headers.get(k)}")
print(f"\n--- body (first 2000 chars) ---")
print(resp.text[:2000])
