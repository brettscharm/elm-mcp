"""SCM Probe 05: hunt for code-review endpoints. EWM code reviews are
typically delivered via the work-item OSLC API (work items of type
'com.ibm.team.review.workItemType.review') with approvals as the
formal voting record. We also test the proprietary review REST.
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

H_RDF  = {"Accept": "application/rdf+xml", "OSLC-Core-Version": "2.0"}
H_JSON = {"Accept": "application/json",     "OSLC-Core-Version": "2.0"}
H_XML  = {"Accept": "application/xml"}

def probe(name, url, headers=None, params=None):
    h = {"OSLC-Core-Version": "2.0"}
    if headers: h.update(headers)
    try:
        r = client.session.get(url, headers=h, params=params, timeout=30, allow_redirects=False)
        size = len(r.content)
        ct = r.headers.get("content-type","")
        print(f"  [{r.status_code:>3}] {name:<45} {size:>7}b  ct={ct[:30]:<30}")
        if 200 <= r.status_code < 300 and size > 50:
            ext = "xml" if "xml" in ct else ("json" if "json" in ct else "txt")
            with open(os.path.join(PROBE_DIR, f"scm_05_{name}.{ext}"), "wb") as f:
                f.write(r.content)
        elif r.text:
            print(f"        body[:160]: {r.text[:160]!r}")
        return {"url": url, "status": r.status_code, "ct": ct, "bytes": size,
                "snippet": r.text[:300]}
    except Exception as e:
        print(f"  [ERR] {name:<45} {e}")
        return {"url": url, "error": str(e)}

results = {}

# A) The EWM Reportable REST workitem feed -- include approvals + change sets
#    to see how reviews link to changesets
print("=== A) Reportable REST workitem (approvals/changeSets) ===")
results["wi_schema"] = probe("wi_schema",
    f"{CCM}/rpt/repository/workitem", headers=H_XML, params={"metadata":"schema"})

# B) OSLC CM workitem catalog & query base for one project
print("\n=== B) OSLC CM workitems via known project ===")
# We pull the workitems services.xml for Sandbox_Development from earlier results
SD_PROJECT_SVC = f"{CCM}/oslc/contexts/_NriAMPR6EeqGRvJUHcwY_A/workitems/services.xml"
results["sd_services"] = probe("sd_services", SD_PROJECT_SVC, headers=H_RDF)

# C) Dedicated EWM review endpoints (varies by version)
print("\n=== C) Dedicated review REST attempts ===")
endpoints = [
    ("review_resource_factory_oslc", f"{CCM}/oslc/reviews/types"),
    ("review_resource_factory_alt",  f"{CCM}/resource/itemName/com.ibm.team.workitem.Approval"),
    ("review_workitem_type",         f"{CCM}/oslc/contexts/_NriAMPR6EeqGRvJUHcwY_A/workitems/types/com.ibm.team.review.workItemType.review"),
    # Internal review service (fragments observed in EWM source)
    ("review_internal_service",      f"{CCM}/service/com.ibm.team.review.internal.service.IReviewRestService"),
    # WorkItem REST for approvals
    ("approvals_wi",                 f"{CCM}/oslc/contexts/_NriAMPR6EeqGRvJUHcwY_A/workitems/approvals"),
]
for name, url in endpoints:
    results[name] = probe(name, url, headers=H_RDF)

# D) Try OSLC CM query for review-type work items
print("\n=== D) OSLC CM query for review work items ===")
# query base for work items in Sandbox_Development
wi_query = f"{CCM}/oslc/contexts/_NriAMPR6EeqGRvJUHcwY_A/workitems"
results["wi_query_default"] = probe("wi_query_default",
    wi_query, headers=H_RDF, params={"oslc.pageSize":"5"})
# By type filter using OSLC where clause
results["wi_query_review"] = probe("wi_query_review",
    wi_query, headers=H_RDF, params={
        "oslc.where": 'rtc_cm:type="com.ibm.team.review.workItemType.review"',
        "oslc.pageSize":"5"})

# E) Try the change-set-link TRS to find which changesets are linked to which workitems
print("\n=== E) Sample cs-link resource ===")
# pluck an example URL from saved cslinks file
with open(os.path.join(PROBE_DIR, "scm_03_trs_cslinks.xml")) as f:
    cl = f.read()
import re
links = re.findall(r'rdf:resource="(https://[^"]+/cslink/resource/[^"]+)"', cl)
if links:
    results["cslink_sample"] = probe("cslink_sample", links[0], headers=H_RDF)

with open(os.path.join(PROBE_DIR, "scm_05_results.json"), "w") as f:
    json.dump(results, f, indent=2, default=str)
print("\nDone.")
