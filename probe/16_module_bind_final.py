"""B probe: final attempt at programmatic module-binding.

Three hypotheses to test against AI Hub DNG sandbox:
  H1: /rm/views?action=com.ibm.rdm.web.module.insertArtifact (DNG private UI)
  H2: /rm/delivery-sessions factory (saw in services.xml; might handle module
      structure changes via a "delivery session")
  H3: POST a binding directly via requirementFactory but with the module URL
      as nav:parent AND oslc:instanceShape pointing at a Module-Bound shape

If any returns 2xx AND the module's oslc_rm:uses persists, we win — and B
becomes "wire that into the existing add_to_module".

This is the final 30-min budget probe before declaring B blocked.
"""
import sys, os, json, time, re, urllib.parse
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

# Setup: make a fresh module + a fresh requirement
run = time.strftime("%H%M%S")
mod = c.create_module(project_url, f"B-Probe Module {run}")
mod_url = mod["url"]
print(f"Module: {mod_url}")
shapes = c.get_artifact_shapes(project_url)
shape = next(s["url"] for s in shapes if s["name"].lower() == "system requirement")
folder = c.find_folder(project_url, "B Probe") or c.create_folder(project_url, "B Probe")
req = c.create_requirement(project_url=project_url, title=f"B Probe Req {run}", content="x",
                            shape_url=shape, folder_url=folder["url"])
req_url = req["url"]
print(f"Req: {req_url}\n")


def show_module_uses(label):
    r = c.session.get(mod_url, headers={"Accept":"application/rdf+xml","OSLC-Core-Version":"2.0"}, timeout=30)
    uses = re.findall(r'oslc_rm:uses\s+rdf:resource="([^"]+)"', r.text)
    print(f"  [{label}] module has {len(uses)} oslc_rm:uses ; req bound: {req_url in uses}")
    return req_url in uses


# ── H1: /rm/views with insertArtifact action ───────────────
print("--- H1: /rm/views?action=insertArtifact ---")
url = (
    f"{c.base_url}/views?"
    f"action=com.ibm.rdm.web.module.insertArtifact&"
    f"module={urllib.parse.quote(mod_url, safe='')}&"
    f"boundArtifact={urllib.parse.quote(req_url, safe='')}"
)
for method in ("POST", "PUT", "GET"):
    try:
        resp = c.session.request(
            method, url,
            headers={"Accept": "application/rdf+xml", "OSLC-Core-Version": "2.0"},
            timeout=20,
        )
        print(f"  {method} {url[:80]}... -> {resp.status_code}  ct={resp.headers.get('content-type','?')[:30]}")
        if resp.status_code in (200, 201, 204):
            print(f"    body: {resp.text[:200]}")
    except Exception as e:
        print(f"  {method} -> EXC {e}")
show_module_uses("after H1")


# ── H2: /rm/delivery-sessions factory ──────────────────────
print("\n--- H2: /rm/delivery-sessions factory ---")
ds_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:oslc_rm="http://open-services.net/ns/rm#">
  <rdf:Description>
    <oslc_rm:targetCollection rdf:resource="{mod_url}"/>
    <oslc_rm:uses rdf:resource="{req_url}"/>
  </rdf:Description>
</rdf:RDF>"""
try:
    resp = c.session.post(
        f"{c.base_url}/delivery-sessions",
        data=ds_body.encode("utf-8"),
        headers={
            "Content-Type": "application/rdf+xml",
            "Accept": "application/rdf+xml",
            "OSLC-Core-Version": "2.0",
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=30,
    )
    print(f"  POST -> {resp.status_code}")
    print(f"  body: {resp.text[:400]}")
except Exception as e:
    print(f"  EXC {e}")
show_module_uses("after H2")


# ── H3: POST binding via requirementFactory with module URL as nav:parent ──
# This time include EVERY attribute we observed in the populated module:
# nav:parent=module URL, dcterms:type pointing at oslc_rm:Requirement,
# oslc:instanceShape Module-Bound. Hopefully the factory recognizes "creating a
# requirement whose parent is a module" and inserts a binding for us.
print("\n--- H3: requirementFactory with nav:parent=module + extra ns ---")
project_area_url = f"{c.base_url}/process/project-areas/{project_area_id}"
encoded_pa = urllib.parse.quote(project_area_url, safe="")

h3_rdf = f'''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:oslc_rm="http://open-services.net/ns/rm#"
         xmlns:oslc="http://open-services.net/ns/core#"
         xmlns:nav="http://jazz.net/ns/rm/navigation#"
         xmlns:jazz_rm="http://jazz.net/ns/rm#">
  <oslc_rm:Requirement>
    <dcterms:title>H3 Binding Probe {run}</dcterms:title>
    <oslc:instanceShape rdf:resource="{shape}"/>
    <nav:parent rdf:resource="{mod_url}"/>
    <jazz_rm:primaryText rdf:parseType="Literal"><div xmlns="http://www.w3.org/1999/xhtml"><p>H3</p></div></jazz_rm:primaryText>
  </oslc_rm:Requirement>
</rdf:RDF>'''
try:
    resp = c.session.post(
        f"{c.base_url}/requirementFactory?projectURL={encoded_pa}",
        data=h3_rdf.encode("utf-8"),
        headers={
            "Content-Type": "application/rdf+xml",
            "Accept": "application/rdf+xml",
            "OSLC-Core-Version": "2.0",
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=30,
    )
    print(f"  POST -> {resp.status_code}")
    if resp.status_code == 201:
        print(f"  Location: {resp.headers.get('Location')}")
    else:
        print(f"  body: {resp.text[:500]}")
except Exception as e:
    print(f"  EXC {e}")
show_module_uses("after H3")


# ── H4 (bonus): try ?vvc.configuration=<stream> on the PUT ─────
print("\n--- H4 (bonus): GCM-aware PUT with vvc.configuration param ---")
# discover stream
mod_resp = c.session.get(mod_url, headers={"Accept":"application/rdf+xml","OSLC-Core-Version":"2.0"}, timeout=30)
m = re.search(r'oslc_config:component\s+rdf:resource="([^"]+)"', mod_resp.text)
if m:
    comp_url = m.group(1)
    cfg = c.session.get(comp_url + "/configurations", headers={"Accept":"application/rdf+xml"}, timeout=20)
    s = re.search(r'rdfs:member\s+rdf:resource="([^"]+)"', cfg.text)
    if s:
        stream_url = s["url"] if isinstance(s, dict) else s.group(1)
        encoded_stream = urllib.parse.quote(stream_url, safe='')
        etag = mod_resp.headers.get("ETag")
        new_uses_line = f'    <oslc_rm:uses rdf:resource="{req_url}"/>\n  '
        body = mod_resp.text.replace("</rdf:Description>", new_uses_line + "</rdf:Description>", 1)
        url_with_config = f"{mod_url}?vvc.configuration={encoded_stream}"
        try:
            resp = c.session.put(
                url_with_config,
                data=body.encode("utf-8"),
                headers={
                    "Content-Type": "application/rdf+xml",
                    "Accept": "application/rdf+xml",
                    "OSLC-Core-Version": "2.0",
                    "If-Match": etag,
                    "X-Requested-With": "XMLHttpRequest",
                    "Configuration-Context": stream_url,
                },
                timeout=30,
            )
            print(f"  PUT (with vvc.configuration) -> {resp.status_code}")
            if resp.status_code not in (200, 204):
                m2 = re.search(r'<err:detailedMessage[^>]*>([^<]+)', resp.text)
                if m2:
                    print(f"    detail: {m2.group(1)[:200]}")
        except Exception as e:
            print(f"  EXC {e}")
        show_module_uses("after H4")
    else:
        print("  no stream URL found")
else:
    print("  no GCM component on module")

print("\n=== B PROBE COMPLETE ===")
