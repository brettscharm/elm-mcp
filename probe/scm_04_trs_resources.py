"""SCM Probe 04: dereference per-resource URLs from the TRS feed and the
Reportable REST 'base' endpoint. The TRS gives us individual change-set
resource URLs which should resolve to full RDF/XML of the change set.
"""
import sys, os, re, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from doors_client import DOORSNextClient

PROBE_DIR = os.path.dirname(os.path.abspath(__file__))
client = DOORSNextClient(os.environ["DOORS_URL"], os.environ["DOORS_USERNAME"], os.environ["DOORS_PASSWORD"])
client.authenticate()
CCM = client.ccm_url

# Pull change-set URLs from the saved TRS file
with open(os.path.join(PROBE_DIR, "scm_03_trs_changesets.xml")) as f:
    trs = f.read()

cs_urls = re.findall(r'rdf:resource="(https://[^"]+/scm/reportable/cs/[^"]+)"', trs)
print(f"Found {len(cs_urls)} changeset resource URLs in TRS feed")
for u in cs_urls[:3]:
    print(f"  {u}")

# Try multiple Accept variations on first changeset
if cs_urls:
    cs = cs_urls[0]
    print(f"\nDereferencing first changeset: {cs}")
    for accept in ("application/rdf+xml", "application/xml", "application/json", "text/turtle"):
        r = client.session.get(cs, headers={"Accept": accept, "OSLC-Core-Version": "2.0"}, timeout=30)
        print(f"  Accept={accept:<25} -> {r.status_code}  ct={r.headers.get('content-type','')[:40]:<40}  bytes={len(r.content)}")
        if r.status_code == 200 and len(r.content) > 100:
            ext = "xml" if "xml" in r.headers.get("content-type","") else ("json" if "json" in r.headers.get("content-type","") else "txt")
            with open(os.path.join(PROBE_DIR, f"scm_04_changeset_first.{ext}"), "wb") as f:
                f.write(r.content)
            print(f"    saved scm_04_changeset_first.{ext}")
            print(f"    head: {r.text[:600]}")
            break

# Also probe the TRS 'base' resource - this lists ALL current change sets (initial state)
print(f"\n=== TRS base feed for change sets ===")
base_url = f"{CCM}/rtcoslc/scm/reportable/base/cs"
r = client.session.get(base_url, headers={"Accept":"application/rdf+xml","OSLC-Core-Version":"2.0"}, timeout=60)
print(f"  base -> {r.status_code} bytes={len(r.content)} ct={r.headers.get('content-type')}")
with open(os.path.join(PROBE_DIR, "scm_04_trs_base_cs.xml"), "wb") as f:
    f.write(r.content)
# Look for pagination in body
if "trs:Page" in r.text or "trs:cutoff" in r.text:
    print("  (has TRS pagination markers)")

# Now probe the equivalent for the cslink TRS -- this links change-sets to work-items
print(f"\n=== TRS cslink resource sample ===")
with open(os.path.join(PROBE_DIR, "scm_03_trs_cslinks.xml")) as f:
    cslink = f.read()
print(cslink[:1500])
