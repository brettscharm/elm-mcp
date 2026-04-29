"""SCM Probe 01: discover EWM rootservices and SCM-related catalogs.

Read-only. Saves raw responses to probe/ for offline inspection.
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from doors_client import DOORSNextClient

PROBE_DIR = os.path.dirname(os.path.abspath(__file__))
client = DOORSNextClient(os.environ["DOORS_URL"], os.environ["DOORS_USERNAME"], os.environ["DOORS_PASSWORD"])
auth = client.authenticate()
print(f"auth: {auth}")
if not auth.get("success"):
    sys.exit(1)

# Standard OSLC headers used everywhere
H_RDF = {"Accept": "application/rdf+xml", "OSLC-Core-Version": "2.0"}
H_JSON = {"Accept": "application/json", "OSLC-Core-Version": "2.0"}

CCM = client.ccm_url
print(f"\nCCM base: {CCM}\n")

# Endpoints we want to probe
candidates = [
    # Standard Jazz rootservices
    ("ccm_rootservices", f"{CCM}/rootservices", H_RDF),
    # OSLC SCM 2.0 catalog (per OSLC spec)
    ("scm_catalog_oslc_scm",   f"{CCM}/oslc_scm/catalog",   H_RDF),
    ("scm_catalog_oslc_scm_json", f"{CCM}/oslc_scm/catalog", H_JSON),
    # Older variant some EWM versions used
    ("scm_catalog_oslc_scm_v1", f"{CCM}/oslc/scm/catalog",  H_RDF),
    # Workspaces / streams query roots
    ("workspaces_oslc_scm",    f"{CCM}/oslc/workspaces",     H_RDF),
    ("workspaces_oslc_scm_alt",f"{CCM}/oslc/scm/workspaces", H_RDF),
    # EWM internal SCM service paths (private but read-only-safe to discover)
    ("scm_service_root",       f"{CCM}/service/com.ibm.team.scm.common.IScmService", H_JSON),
    # The EWM web UI calls these for code review
    ("review_catalog",         f"{CCM}/oslc/reviews/catalog", H_RDF),
    ("review_query",           f"{CCM}/oslc/reviews",         H_RDF),
    # Components & change-set query roots (per OSLC SCM)
    ("components_q",           f"{CCM}/oslc/components",      H_RDF),
    ("changesets_q",           f"{CCM}/oslc/changesets",      H_RDF),
    # Code review web UI hint - sometimes exposed via
    ("rest_workitem_oslc",     f"{CCM}/oslc/workitems/catalog", H_RDF),
]

results = {}
for name, url, hdrs in candidates:
    try:
        r = client.session.get(url, headers=hdrs, timeout=30, allow_redirects=False)
        ct = r.headers.get("content-type", "")
        size = len(r.content)
        loc = r.headers.get("location", "")
        ww = r.headers.get("www-authenticate", "")
        # First ~600 chars of body for triage
        snippet = r.text[:600] if r.text else ""
        results[name] = {
            "url": url,
            "status": r.status_code,
            "content_type": ct,
            "bytes": size,
            "location": loc,
            "www_authenticate": ww,
            "snippet": snippet,
        }
        # Save full body if it looks substantive
        if r.status_code == 200 and size > 50:
            ext = "xml" if "xml" in ct else ("json" if "json" in ct else "txt")
            out = os.path.join(PROBE_DIR, f"scm_01_{name}.{ext}")
            with open(out, "wb") as f:
                f.write(r.content)
        print(f"  [{r.status_code:>3}] {name:<32} {size:>7}b  ct={ct[:40]:<40} url={url}")
    except Exception as e:
        results[name] = {"url": url, "error": f"{type(e).__name__}: {e}"}
        print(f"  [ERR] {name:<32} {e}")

with open(os.path.join(PROBE_DIR, "scm_01_results.json"), "w") as f:
    json.dump(results, f, indent=2)
print(f"\nSaved scm_01_results.json")
