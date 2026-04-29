"""Identify the smallest edit that DNG accepts when adding oslc_rm:uses.

Strategy: take the GET bytes verbatim, insert one well-formed line just
before </rdf:Description>. Try several insertion-point variations until
one returns 200/204.
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

run_tag = time.strftime("%H%M%S")
mod = c.create_module(project_url, f"Min-{run_tag}")
mod_url = mod["url"]
print(f"Module: {mod_url}")
shapes = c.get_artifact_shapes(project_url)
shape = next(s["url"] for s in shapes if s["name"].lower() == "system requirement")
folder = c.find_folder(project_url, "Min Test") or c.create_folder(project_url, "Min Test")
req = c.create_requirement(project_url=project_url, title=f"Min Req {run_tag}", content="x",
                            shape_url=shape, folder_url=folder["url"])
req_url = req["url"]
print(f"Req:    {req_url}\n")

def fresh_get():
    r = c.session.get(
        mod_url,
        headers={"Accept": "application/rdf+xml", "OSLC-Core-Version": "2.0"},
        timeout=30,
    )
    return r.text, r.headers.get("ETag")

def try_put(label, body_text, etag, extra_headers=None):
    headers = {
        "Content-Type": "application/rdf+xml",
        "Accept": "application/rdf+xml",
        "OSLC-Core-Version": "2.0",
        "If-Match": etag,
        "X-Requested-With": "XMLHttpRequest",
    }
    if extra_headers:
        headers.update(extra_headers)
    resp = c.session.put(mod_url, data=body_text.encode("utf-8"), headers=headers, timeout=30)
    print(f"  [{label}] -> {resp.status_code}")
    if resp.status_code not in (200, 204):
        # extract just the err:detailedMessage
        import re
        m = re.search(r'<err:detailedMessage[^>]*>([^<]+)', resp.text)
        if m:
            print(f"    detail: {m.group(1)[:200]}")
    return resp.status_code

# Variant A: insert just before </rdf:Description>
text, etag = fresh_get()
new_line = f'    <oslc_rm:uses rdf:resource="{req_url}"/>\n  '
v_a = text.replace("</rdf:Description>", new_line + "</rdf:Description>", 1)
try_put("A: insert before </rdf:Description>", v_a, etag)

# Variant B: same insertion + Configuration-Context header
text, etag = fresh_get()
v_b = text.replace("</rdf:Description>", new_line + "</rdf:Description>", 1)
stream_url = "https://goblue.clm.ibmcloud.com/rm/cm/stream/_K8VOoENbEe6-DeGEq1-kAw"
try_put("B: + Configuration-Context", v_b, etag,
        extra_headers={"Configuration-Context": stream_url,
                       "vvc.configuration": stream_url})

# Variant C: insert AFTER the dcterms:title line specifically (a known stable spot)
text, etag = fresh_get()
import re
v_c = re.sub(
    r'(<dcterms:title[^>]*>[^<]*</dcterms:title>)',
    lambda m: f'{m.group(1)}\n    <oslc_rm:uses rdf:resource="{req_url}"/>',
    text, count=1,
)
try_put("C: insert after dcterms:title", v_c, etag)

# Variant D: insert WITHOUT trailing newlines/indentation
text, etag = fresh_get()
v_d = text.replace("</rdf:Description>",
                   f'<oslc_rm:uses rdf:resource="{req_url}"/></rdf:Description>', 1)
try_put("D: no whitespace insertion", v_d, etag)

# Variant E: PATCH method?
text, etag = fresh_get()
v_e = text.replace("</rdf:Description>", new_line + "</rdf:Description>", 1)
print("  [E: try PATCH method]")
resp = c.session.request(
    "PATCH",
    mod_url,
    data=v_e.encode("utf-8"),
    headers={
        "Content-Type": "application/rdf+xml",
        "Accept": "application/rdf+xml",
        "OSLC-Core-Version": "2.0",
        "If-Match": etag,
    },
    timeout=30,
)
print(f"    -> {resp.status_code}")
print(f"    {resp.text[:300]}")
