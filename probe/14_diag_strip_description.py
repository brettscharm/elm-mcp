"""Test: PUT module RDF with the dcterms:description stripped out before adding uses.

Theory: the parseType=Literal description has escaped HTML returned by GET
that parses fine as a roundtrip but fails when other edits are made because
DNG re-parses it after the modification.
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

run_tag = time.strftime("%H%M%S")
mod = c.create_module(project_url, f"Strip-{run_tag}")
mod_url = mod["url"]
print(f"Module: {mod_url}")
shapes = c.get_artifact_shapes(project_url)
shape = next(s["url"] for s in shapes if s["name"].lower() == "system requirement")
folder = c.find_folder(project_url, "Strip Test") or c.create_folder(project_url, "Strip Test")
req = c.create_requirement(project_url=project_url, title=f"Strip Req {run_tag}", content="x",
                            shape_url=shape, folder_url=folder["url"])
req_url = req["url"]
print(f"Req:    {req_url}")

r = c.session.get(mod_url, headers={"Accept":"application/rdf+xml","OSLC-Core-Version":"2.0"}, timeout=30)
text = r.text
etag = r.headers.get("ETag")

def attempt(label, body):
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
    print(f"  [{label}] -> {resp.status_code}")
    if resp.status_code in (200, 204):
        return True
    m = re.search(r'<err:detailedMessage[^>]*>([^<]+)', resp.text)
    print(f"    detail: {m.group(1)[:300] if m else resp.text[:300]}")
    return False

# Variant A: strip description entirely + add uses
no_desc = re.sub(
    r'<dcterms:description[^>]*>.*?</dcterms:description>\s*',
    '',
    text,
    count=1,
    flags=re.DOTALL,
)
with_uses = no_desc.replace(
    "</rdf:Description>",
    f'    <oslc_rm:uses rdf:resource="{req_url}"/>\n  </rdf:Description>',
    1,
)
ok_A = attempt("A: strip description, add uses", with_uses)

# Variant B: replace parseType=Literal description with empty
if not ok_A:
    text2 = r.text  # fresh
    fixed_desc = re.sub(
        r'<dcterms:description[^>]*rdf:parseType="Literal"[^>]*>.*?</dcterms:description>',
        '<dcterms:description></dcterms:description>',
        text2,
        count=1,
        flags=re.DOTALL,
    )
    with_uses2 = fixed_desc.replace(
        "</rdf:Description>",
        f'    <oslc:rm:uses rdf:resource="{req_url}"/>\n  </rdf:Description>',
        1,
    ).replace("oslc:rm:uses", "oslc_rm:uses")
    attempt("B: replace literal desc with empty", with_uses2)

# Verify (re-fetch)
r2 = c.session.get(mod_url, headers={"Accept":"application/rdf+xml","OSLC-Core-Version":"2.0"}, timeout=30)
uses = re.findall(r'oslc_rm:uses\s+rdf:resource="([^"]+)"', r2.text)
print(f"\nFinal: module has {len(uses)} oslc_rm:uses entries")
for u in uses:
    print(f"  - {u}")
print(f"\nOur req URL bound: {req_url in uses}")
