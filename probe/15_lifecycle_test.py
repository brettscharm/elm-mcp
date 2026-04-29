"""End-to-end cross-domain lifecycle test.

DNG requirement -> EWM task linked via 'Implements' -> ETM test case linked
via 'Validates' -> ETM test result. Uses Gio (Brett) family.
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

dng = sandbox["dng"]
ewm = sandbox["ewm"]
etm = sandbox["etm"]
run = time.strftime("%H%M%S")
print(f"DNG: {dng['title']}")
print(f"EWM: {ewm['title']}")
print(f"ETM: {etm['title']}\n")

# 1. Create a DNG requirement
print("[1] Creating DNG requirement")
shapes = c.get_artifact_shapes(dng["services_url"])
shape = next(s["url"] for s in shapes if s["name"].lower() == "system requirement")
folder = (c.find_folder(dng["services_url"], "Lifecycle Test")
          or c.create_folder(dng["services_url"], "Lifecycle Test"))
req = c.create_requirement(
    project_url=dng["services_url"],
    title=f"Lifecycle Req {run}",
    content=f"The system shall pass the lifecycle test on run {run}.",
    shape_url=shape, folder_url=folder["url"],
)
assert req and "error" not in req, f"req failed: {req}"
req_url = req["url"]
print(f"    {req_url}")

# 2. Create EWM task that 'Implements' it
print("\n[2] Creating EWM task linked to that requirement")
ewm_projects = c.list_ewm_projects()
ewm_proj = next(p for p in ewm_projects if p["title"] == ewm["title"])
task = c.create_ewm_task(
    service_provider_url=ewm_proj["url"],
    title=f"Implement Lifecycle Req {run}",
    description=f"Task to implement requirement {req_url}",
    requirement_url=req_url,
)
print(f"    -> {task}")
if not task or "error" in task:
    print(f"    EWM task creation FAILED: {task}")
    sys.exit(1)
task_url = task.get("url") or task.get("workitem_url")
print(f"    {task_url}")

# 3. Create ETM test case that 'Validates' the requirement
print("\n[3] Creating ETM test case linked to the requirement")
etm_projects = c.list_etm_projects()
etm_proj = next(p for p in etm_projects if p["title"] == etm["title"])
tc = c.create_test_case(
    service_provider_url=etm_proj["url"],
    title=f"Test for Lifecycle Req {run}",
    description=f"Verify requirement {req_url}",
    requirement_url=req_url,
)
print(f"    -> {tc}")
if not tc or "error" in tc:
    print(f"    ETM test case creation FAILED: {tc}")
    sys.exit(1)
tc_url = tc.get("url") or tc.get("test_case_url")
print(f"    {tc_url}")

# 4. Create a passing test result
print("\n[4] Recording passing test result")
tr = c.create_test_result(
    service_provider_url=etm_proj["url"],
    test_case_url=tc_url,
    status="passed",
    title=f"Test passed for {run}",
)
print(f"    -> {tr}")

# 5. Verify the link by re-fetching the task and checking it points back to req
print("\n[5] Verifying EWM task -> DNG requirement link")
import re
r = c.session.get(task_url, headers={"Accept": "application/rdf+xml", "OSLC-Core-Version": "2.0"}, timeout=30)
implements = re.findall(r'(?:calm:implementsRequirement|oslc_cm:relatedChangeRequest)\s+rdf:resource="([^"]+)"', r.text)
print(f"    task RDF status: {r.status_code}")
print(f"    implements links found: {implements}")
print(f"    OK?: {req_url in implements or any(req_url in l for l in implements)}")

print("\n" + "="*60)
print("LIFECYCLE TEST COMPLETE")
print(f"  DNG req:      {req_url}")
print(f"  EWM task:     {task_url}")
print(f"  ETM testcase: {tc_url}")
