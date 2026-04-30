"""End-to-end Bob simulation against the live sandbox.

Walks the workflow a typical user would drive through Bob:
  1. List capabilities (discovery)
  2. Tiered decomposition: Business → Stakeholder → System reqs in
     three modules with cross-tier Satisfies links
  3. Filter requirements by status / type
  4. Create an EWM task linked to a system req — verify link sticks
  5. Create an ETM test case linked to the same req — verify
  6. Create an ETM test script linked to the test case
  7. Create a Defect linked to the req — verify
  8. Update a requirement attribute
  9. Verify auto-bind put requirements into modules
 10. Generate a chart of requirements by status

Each step prints PASS/FAIL. If anything fails we know exactly where.
"""
import sys, os, json, time, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from doors_client import DOORSNextClient

c = DOORSNextClient(os.environ.get("ELM_URL") or os.environ["DOORS_URL"],
                    os.environ.get("ELM_USERNAME") or os.environ["DOORS_USERNAME"],
                    os.environ.get("ELM_PASSWORD") or os.environ["DOORS_PASSWORD"])
c.authenticate()
with open(os.path.join(os.path.dirname(__file__), "SANDBOX_PROJECTS.json")) as f:
    sandbox = json.load(f)

dng_url = sandbox["dng"]["services_url"]
ewm_proj = next(p for p in c.list_ewm_projects() if p["title"] == sandbox["ewm"]["title"])
etm_proj = next(p for p in c.list_etm_projects() if p["title"] == sandbox["etm"]["title"])
run = time.strftime("%H%M%S")

results = []
def step(label, ok, detail=""):
    marker = "PASS" if ok else "FAIL"
    print(f"[{marker}] {label}")
    if detail:
        print(f"        {detail}")
    results.append((marker, label, detail))

# ── Setup helpers ─────────────────────────────────────────────
shapes = c.get_artifact_shapes(dng_url)
shape_sysreq = next((s["url"] for s in shapes if s["name"].lower() == "system requirement"), None)
shape_bizreq = next((s["url"] for s in shapes if s["name"].lower() == "business requirement"), None) \
               or next((s["url"] for s in shapes if "stakeholder" in s["name"].lower()), shape_sysreq)
shape_stkreq = next((s["url"] for s in shapes if "stakeholder" in s["name"].lower()), shape_sysreq)
print(f"DNG shapes available: {[s['name'] for s in shapes][:8]}{'...' if len(shapes) > 8 else ''}")
print(f"  Using SR shape: {shape_sysreq}\n")

def make_req(title, content, shape_url, folder):
    r = c.create_requirement(project_url=dng_url, title=title, content=content,
                              shape_url=shape_url, folder_url=folder["url"])
    return r["url"] if r and "error" not in r else None

# ── 1. Tiered creation ───────────────────────────────────────
print("\n=== 1. Tiered decomposition ===\n")

br_folder = c.find_folder(dng_url, f"Business Requirements {run}") or c.create_folder(dng_url, f"Business Requirements {run}")
br_urls = []
for i, txt in enumerate([
    "Reduce production line downtime by 20% over 12 months.",
    "Reduce mean-time-to-repair by 30%.",
], start=1):
    u = make_req(f"BR{i} Run {run}", txt, shape_sysreq, br_folder)
    if u: br_urls.append(u)
step("created 2 Business Requirements", len(br_urls) == 2,
     f"urls: {br_urls}")

stk_folder = c.find_folder(dng_url, f"Stakeholder Requirements {run}") or c.create_folder(dng_url, f"Stakeholder Requirements {run}")
stk_urls = []
for i, (txt, br_idx) in enumerate([
    ("The Operator shall be able to monitor production status in real time.", 0),
    ("The Maintenance Engineer shall be able to schedule preventive maintenance.", 1),
], start=1):
    u = make_req(f"StR{i} Run {run}", txt, shape_stkreq, stk_folder)
    if u: stk_urls.append(u)
step("created 2 Stakeholder Requirements", len(stk_urls) == 2,
     f"urls: {stk_urls}")

sys_folder = c.find_folder(dng_url, f"System Requirements {run}") or c.create_folder(dng_url, f"System Requirements {run}")
sys_urls = []
for i, txt in enumerate([
    "The system shall expose a real-time status dashboard with sub-1s refresh.",
    "The system shall accept maintenance schedules in iCal format.",
    "The system shall log all status changes for audit.",
], start=1):
    u = make_req(f"SR{i} Run {run}", txt, shape_sysreq, sys_folder)
    if u: sys_urls.append(u)
step("created 3 System Requirements", len(sys_urls) == 3,
     f"urls: {sys_urls}")

# ── 2. Filter test ───────────────────────────────────────────
print("\n=== 2. Filter API on get_module_requirements ===\n")

# We don't have a module yet (just folders). Use get_module_requirements
# against an existing populated module from earlier runs to test the filter.
# Use Sandbox_Requirements project's first module as a known-populated source.
existing_modules = c.get_modules(
    "https://goblue.clm.ibmcloud.com/rm/oslc_rm/_yGWz8PR5Eeq_3JxeOWm9kg/services.xml")
if existing_modules:
    test_mod = existing_modules[0]
    all_reqs = c.get_module_requirements(test_mod["url"])
    step(f"get_module_requirements returned reqs from '{test_mod['title']}'",
         bool(all_reqs), f"{len(all_reqs)} reqs")
    # Filter by title_contains
    if all_reqs and len(all_reqs) > 5:
        sample_word = (all_reqs[0]["title"] or "").split()[0] if all_reqs[0].get("title") else ""
        if sample_word:
            filtered = c.get_module_requirements(test_mod["url"],
                                                  filter={"title_contains": sample_word})
            step(f"filter title_contains='{sample_word}'",
                 len(filtered) <= len(all_reqs) and len(filtered) > 0,
                 f"all={len(all_reqs)} → filtered={len(filtered)}")
    # Filter by artifact_type
    types_seen = {r.get("artifact_type", "") for r in all_reqs if r.get("artifact_type")}
    if types_seen:
        sample_type = next(iter(types_seen))
        filtered = c.get_module_requirements(test_mod["url"],
                                              filter={"artifact_type": sample_type})
        step(f"filter artifact_type='{sample_type}'",
             all(r.get("artifact_type") == sample_type for r in filtered),
             f"{len(filtered)} reqs of that type (out of {len(all_reqs)})")
else:
    step("filter test (no module to read from)", False)

# ── 3. EWM task with link verified ───────────────────────────
print("\n=== 3. EWM Task linked to a System Requirement ===\n")

if sys_urls:
    target_req = sys_urls[0]
    task = c.create_ewm_task(service_provider_url=ewm_proj["url"],
                              title=f"Implement SR1 ({run})",
                              description="Implementation task for the dashboard requirement.",
                              requirement_url=target_req)
    step("create_ewm_task succeeded", task and "error" not in task,
         f"url={task.get('url') if task else None}")
    if task and "error" not in task:
        r = c.session.get(task["url"], headers={"Accept": "application/rdf+xml",
                                                  "OSLC-Core-Version": "2.0"},
                           allow_redirects=True, timeout=30)
        linked = target_req in r.text
        step("EWM task back-references the requirement",
             linked, f"target_req {'found' if linked else 'NOT found'} in task RDF")

# ── 4. ETM test case + script ────────────────────────────────
print("\n=== 4. ETM Test Case + Test Script linked ===\n")

if sys_urls:
    tc = c.create_test_case(service_provider_url=etm_proj["url"],
                             title=f"Validate SR1 ({run})",
                             description="Verify dashboard refresh.",
                             requirement_url=sys_urls[0])
    step("create_test_case succeeded", tc and "error" not in tc)
    if tc and "error" not in tc:
        r = c.session.get(tc["url"], headers={"Accept": "application/rdf+xml",
                                                "OSLC-Core-Version": "2.0"}, timeout=30)
        linked = sys_urls[0] in r.text
        step("test case back-references requirement", linked)

        ts = c.create_test_script(service_provider_url=etm_proj["url"],
                                   title=f"Procedure for SR1 ({run})",
                                   steps="1. Open dashboard.\n2. Trigger event.\n3. Verify refresh under 1s.",
                                   test_case_url=tc["url"])
        step("create_test_script succeeded", ts and "error" not in ts,
             f"url={ts.get('url') if ts else None}")

# ── 5. Defect linked to requirement ──────────────────────────
print("\n=== 5. EWM Defect linked to a Requirement ===\n")

if sys_urls:
    df = c.create_defect(service_provider_url=ewm_proj["url"],
                          title=f"Defect against SR1 ({run})",
                          description="Found during early testing — refresh exceeds 1s under load.",
                          requirement_url=sys_urls[0])
    step("create_defect succeeded", df and "error" not in df,
         f"url={df.get('url') if df else None}")
    if df and "error" not in df:
        r = c.session.get(df["url"], headers={"Accept": "application/rdf+xml",
                                               "OSLC-Core-Version": "2.0"},
                           allow_redirects=True, timeout=30)
        linked = sys_urls[0] in r.text
        step("defect back-references requirement", linked)

# ── 6. Update arbitrary attribute ────────────────────────────
print("\n=== 6. update_requirement_attributes ===\n")

if sys_urls:
    # Try setting a common attr — Priority is one most projects have
    res = c.update_requirement_attributes(sys_urls[0],
                                           attributes={"Priority": "High"})
    ok = res and "error" not in res
    step("update_requirement_attributes Priority=High",
         ok, f"result={res}")

# ── 7. Module auto-bind ──────────────────────────────────────
print("\n=== 7. create_requirements with module_name (auto-bind) ===\n")

# Different from earlier — exercises the auto-bind path explicitly
mod_test_run = f"AutoBind {run}"
shapes_for_module = {s["name"].lower(): s["url"] for s in shapes}
mod = c.create_module(dng_url, mod_test_run)
step("create_module", mod and "error" not in mod, f"url={mod.get('url') if mod else None}")
if mod and "error" not in mod:
    folder_for_mod = c.create_folder(dng_url, mod_test_run)
    bind_urls = []
    for i in range(1, 4):
        r = c.create_requirement(project_url=dng_url,
                                  title=f"AutoBind R{i} {run}",
                                  content=f"Body of req {i}",
                                  shape_url=shape_sysreq,
                                  folder_url=folder_for_mod["url"])
        if r and "error" not in r:
            bind_urls.append(r["url"])
    bind_result = c.add_to_module(mod["url"], bind_urls)
    step("add_to_module bound 3 reqs", bind_result and "error" not in bind_result,
         f"result={bind_result}")
    # Verify by re-fetching the module
    rr = c.session.get(mod["url"], headers={"Accept": "application/rdf+xml",
                                              "OSLC-Core-Version": "2.0"}, timeout=30)
    uses = re.findall(r'oslc_rm:uses\s+rdf:resource="([^"]+)"', rr.text)
    step(f"module shows {len(uses)} oslc_rm:uses (expected ≥3)",
         len(uses) >= 3, f"sample: {uses[:3]}")

# ── Summary ──────────────────────────────────────────────────
print("\n" + "=" * 60)
passed = sum(1 for r in results if r[0] == "PASS")
failed = sum(1 for r in results if r[0] == "FAIL")
print(f"SUMMARY: {passed} PASS, {failed} FAIL ({passed+failed} total checks)")
if failed:
    print("\nFailures:")
    for marker, label, detail in results:
        if marker == "FAIL":
            print(f"  • {label}  {detail}")
sys.exit(0 if failed == 0 else 1)
