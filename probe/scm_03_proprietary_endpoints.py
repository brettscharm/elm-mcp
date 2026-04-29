"""SCM Probe 03: probe EWM-proprietary SCM REST endpoints. The standard
OSLC SCM 2.0 catalog only exposes a file-picker dialog; the real SCM
data (workspaces, change sets, components, code reviews) lives behind
EWM-internal `/ccm/service/...` and `/ccm/rpt/repository/...` paths.

Read-only only. We probe with both XML and JSON Accepts to see what
the server prefers.
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from doors_client import DOORSNextClient

PROBE_DIR = os.path.dirname(os.path.abspath(__file__))
client = DOORSNextClient(os.environ["DOORS_URL"], os.environ["DOORS_USERNAME"], os.environ["DOORS_PASSWORD"])
client.authenticate()

CCM = client.ccm_url

def probe(name, url, headers=None, params=None):
    h = {"OSLC-Core-Version": "2.0"}
    if headers: h.update(headers)
    try:
        r = client.session.get(url, headers=h, params=params, timeout=30, allow_redirects=False)
        ct = r.headers.get("content-type", "")
        size = len(r.content)
        snippet = r.text[:400]
        print(f"  [{r.status_code:>3}] {name:<40} {size:>8}b  ct={ct[:38]:<38}")
        if r.status_code == 200 and size > 50:
            ext = "xml" if "xml" in ct else ("json" if "json" in ct else "txt")
            with open(os.path.join(PROBE_DIR, f"scm_03_{name}.{ext}"), "wb") as f:
                f.write(r.content)
        elif size > 20 and size < 800:
            print(f"        {snippet[:200]}")
        return {"url": url, "status": r.status_code, "ct": ct, "bytes": size, "snippet": snippet}
    except Exception as e:
        print(f"  [ERR] {name:<40} {e}")
        return {"url": url, "error": str(e)}

results = {}

# A) Reportable REST for SCM (this is documented in EWM docs)
#    /ccm/rpt/repository/scm  -- equivalent to the /rm/publish? endpoints in DNG
print("=== A) Reportable REST: /ccm/rpt/repository/scm ===")
for entity in ["workspace", "component", "changeSet", "snapshot", "stream", "fileItem", "folderItem"]:
    results[f"rpt_{entity}"] = probe(
        f"rpt_{entity}",
        f"{CCM}/rpt/repository/scm",
        headers={"Accept": "application/xml"},
        params={"fields": f"{entity}/(itemId|name|description)", "size": "5"},
    )

# B) The TRS feeds discovered in rootservices
print("\n=== B) TRS 2.0 feeds for SCM ===")
results["trs_changesets"] = probe("trs_changesets", f"{CCM}/rtcoslc/scm/reportable/trs/cs",
                                   headers={"Accept": "application/rdf+xml"})
results["trs_cslinks"]    = probe("trs_cslinks",    f"{CCM}/rtcoslc/scm/cslink/trs",
                                   headers={"Accept": "application/rdf+xml"})
results["trs_scm_config"] = probe("trs_scm_config", f"{CCM}/rtcoslc/trs/scm/config",
                                   headers={"Accept": "application/rdf+xml"})

# C) EWM-internal SCM service entry points (these are HTTP-accessible
#    via the same auth session; private API but stable across versions)
print("\n=== C) EWM-internal /service/com.ibm.team.scm... ===")
internal_paths = [
    "/service/com.ibm.team.scm.common.IScmService",
    "/service/com.ibm.team.scm.common.IScmQueryService",
    "/service/com.ibm.team.filesystem.common.IFileSystemQueryService",
    "/service/com.ibm.team.filesystem.common.IFileSystemService",
    "/service/com.ibm.team.scm.common.IVersionedContentService",
]
for p in internal_paths:
    name = p.replace("/service/com.ibm.team.", "").replace(".", "_")
    results[f"svc_{name}"] = probe(f"svc_{name}", f"{CCM}{p}",
                                    headers={"Accept": "application/json"})

# D) Code review REST -- known EWM REST for review work items
#    Code reviews in EWM are work items of type "approval/review" plus
#    backing review-result records. Try the REST collection endpoint.
print("\n=== D) Code review REST (work-item based) ===")
results["review_rest_root"]   = probe("review_rest_root", f"{CCM}/rest/com.ibm.team.review",
                                       headers={"Accept": "application/json"})
results["review_resources"]   = probe("review_resources", f"{CCM}/resource/com.ibm.team.review.common.IReviewItem",
                                       headers={"Accept": "application/json"})
# The webUI uses these "service" endpoints for the review pane:
results["review_svc"]         = probe("review_svc", f"{CCM}/service/com.ibm.team.review.common.IReviewRestService",
                                       headers={"Accept": "application/json"})

# E) Workspaces/Streams via the reportable REST (different URL style)
print("\n=== E) Workspace/stream REST hits ===")
results["wsm_root"]       = probe("wsm_root",     f"{CCM}/wsm",                   headers={"Accept": "application/xml"})
results["scmweb_root"]    = probe("scmweb_root",  f"{CCM}/scmweb/streams",        headers={"Accept": "application/xml"})
results["resource_workspace"] = probe("resource_workspace", f"{CCM}/resource/itemName/com.ibm.team.scm.Workspace",
                                       headers={"Accept": "application/xml"}, params={"size": "5"})
results["resource_changeset"] = probe("resource_changeset", f"{CCM}/resource/itemName/com.ibm.team.scm.ChangeSet",
                                       headers={"Accept": "application/xml"}, params={"size": "5"})
results["resource_component"] = probe("resource_component", f"{CCM}/resource/itemName/com.ibm.team.scm.Component",
                                       headers={"Accept": "application/xml"}, params={"size": "5"})

with open(os.path.join(PROBE_DIR, "scm_03_results.json"), "w") as f:
    json.dump(results, f, indent=2, default=str)
print("\nDone. Results in scm_03_results.json.")
