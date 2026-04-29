"""Test if a no-op PUT (echo back GET response) works.

If this 400s, PUT is rejected for reasons unrelated to our edit.
If this 200/204s, the issue is specifically what we added.
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from doors_client import DOORSNextClient

c = DOORSNextClient(os.environ["DOORS_URL"], os.environ["DOORS_USERNAME"], os.environ["DOORS_PASSWORD"])
c.authenticate()

with open(os.path.join(os.path.dirname(__file__), "SANDBOX_PROJECTS.json")) as f:
    sandbox = json.load(f)
project_url = sandbox["dng"]["services_url"]

# Use a fresh module
mod = c.create_module(project_url, f"RT-{time.strftime('%H%M%S')}")
mod_url = mod["url"]
print(f"Module: {mod_url}")

# GET it
r = c.session.get(
    mod_url,
    headers={"Accept": "application/rdf+xml", "OSLC-Core-Version": "2.0"},
    timeout=30,
)
etag = r.headers.get("ETag")
body = r.content
print(f"GET status: {r.status_code}, ETag: {etag!r}, bytes: {len(body)}")

# PUT exact same bytes
print(f"\n[A] PUT exact GET bytes (no-op)")
resp = c.session.put(
    mod_url,
    data=body,
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
if resp.status_code != 200 and resp.status_code != 204:
    print(f"  body: {resp.text[:1500]}")

# Look for Configuration-Context hints in the original RDF
import re
comp = re.search(r'oslc_config:component\s+rdf:resource="([^"]+)"', body.decode("utf-8"))
print(f"\n[B] GCM component on module: {comp.group(1) if comp else None}")

# Discover the project's default configuration (stream)
# OSLC config: GET /rm/cm/components/<id>/configurations
if comp:
    comp_url = comp.group(1)
    cfg_resp = c.session.get(
        comp_url + "/configurations",
        headers={"Accept": "application/rdf+xml", "OSLC-Core-Version": "2.0"},
        timeout=30,
    )
    print(f"\n[C] GET {comp_url}/configurations -> {cfg_resp.status_code}, bytes={len(cfg_resp.content)}")
    print(cfg_resp.text[:1500])
