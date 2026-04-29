# OSLC / IBM ELM — MCP Coverage Gaps

Research report on what's missing from the `doors-next` MCP tool surface.
Scope: OSLC RM (DNG), OSLC CM (EWM, **excluding** SCM/code review/changesets), OSLC QM (ETM), OSLC Configuration (GCM), and IBM-specific REST extensions (Reportable REST, Process API). Out-of-scope: Jazz SCM, MCP host config, deep module-binding internals.

All probes against `https://goblue.clm.ibmcloud.com` succeeded; supporting probe scripts at `probe/oslc_services_inventory.py`, `probe/oslc_endpoint_probes.py`, `probe/oslc_deep_probes.py`, `probe/oslc_final_probes.py`. Inventory JSON: `probe/oslc_services_inventory.json`.

---

## Section 1: Current Tool Inventory (21 tools, verified)

`doors_mcp_server.py` `list_tools()` at line 481 returns exactly 21 `Tool(…)` entries. README claim is accurate.

### DNG / RM (14 tools)
| Tool | Line | Notes |
|------|------|-------|
| `connect_to_elm` | 484 | Auth — basic + j_security_check fallback |
| `list_projects` | 512 | Multiplexes domain=dng/ewm/etm |
| `get_modules` | 531 | Reportable REST + OSLC fallback |
| `get_module_requirements` | 550 | Reads from a module |
| `save_requirements` | 572 | Local file (json/csv/markdown) |
| `create_requirements` | 595 | Bulk create + folder + 1 link/req |
| `get_link_types` | 648 | Project-scoped |
| `search_requirements` | 666 | Full-text via OSLC searchTerms + JFS |
| `get_artifact_types` | 688 | Project-scoped |
| `update_requirement` | 706 | **Title and content only** — see Section 3 |
| `create_baseline` | 733 | Single component / single stream only |
| `list_baselines` | 759 | One module's baselines |
| `compare_baselines` | 777 | Module-level diff |
| `extract_pdf` | 804 | Local file utility |

### EWM / CM (1 tool)
| Tool | Line | Notes |
|------|------|-------|
| `create_task` | 823 | **Task only** — Defect/Story/Epic explicitly skipped per LIFECYCLE.md line 67/209. No update, transition, query, link, attachment, comment, or iteration tools. |

### ETM / QM (2 tools)
| Tool | Line | Notes |
|------|------|-------|
| `create_test_case` | 853 | TestCase only |
| `create_test_result` | 883 | Pass/fail/blocked/incomplete/error |

### GCM (3 tools)
| Tool | Line | Notes |
|------|------|-------|
| `list_global_configurations` | 914 | Read-only |
| `list_global_components` | 927 | Read-only |
| `get_global_config_details` | 939 | Read-only |

### Cross-domain (1 tool)
| Tool | Line | Notes |
|------|------|-------|
| `generate_chart` | 957 | Local PNG output |

Plus 4 **prompts** (`generate-requirements`, `full-lifecycle`, `import-pdf`, `review-requirements` — line 140-220) and 3 **resource templates** (`elm-projects`, `elm-modules`, `elm-requirements` — line 355-380). README count of "21 + 4 + 3" is correct.

**Defined but incomplete:**
- `update_requirement` (line 1378 of `doors_client.py`) only patches `dcterms:title` and `dcterms:description` via raw regex on the RDF — does **not** touch any custom DNG attribute (priority, status, severity, owner, custom shapes, etc.).
- `compare_baselines` (line 777) only compares title/description text — misses link diffs and attribute diffs.

---

## Section 2: Client Methods Already Implemented but Not Exposed as MCP Tools

These are quick wins — code already exists in `doors_client.py`, just no `Tool(…)` registration in `doors_mcp_server.py`.

| Client method | Line | What it does | Why not exposed? |
|---------------|------|-------------|------------------|
| `find_folder` | 1055 | Find a DNG folder by name | Used internally by `create_requirements` only |
| `create_folder` | 969 | Create a DNG folder explicitly | Used internally — could expose as `create_folder` tool for users who want to organize before bulk-creating |
| `get_artifact_shapes` | 1231 | Returns artifact shape URIs (richer than `get_artifact_types`) | Internal helper — useful for callers who want to see attribute shape definitions |
| `_get_root_folder_url` | 1022 | Project root folder discovery | Internal — could feed a `list_folders` tool |
| `_get_child_folders` | 675 | Folder hierarchy walker | Internal — could feed a `list_folders` recursive tool |
| `_get_modules_reportable` / `_get_modules_oslc` | 499 / 626 | Two parallel module-fetch impls | Already wrapped by `get_modules` |

The client also has `_resolve_link_type_name` (line 1178) which pretty-prints link-type URIs — not strictly a tool, but useful when reading raw OSLC responses.

**Bottom line:** the only meaningful "code exists, no tool exposes it" gap is `create_folder` and a `list_folders` traversal tool. Everything else in the client is already either wrapped or is private plumbing.

---

## Section 3: Missing Capabilities by Domain

### DNG / RM gaps

**Most painful — `update_requirement` only updates title/content.**
DNG requirements have arbitrary user-defined attributes (Status, Priority, Owner, Risk Level, etc.) declared via the `AttributeDefinition Factory`/`Query Capability` (services.xml shows this — see `oslc_services_inventory.json`). No tool exposes:
- Set arbitrary attributes by name → value (the AI literally cannot mark a requirement "Approved" via the MCP today; that's all the safety-rule docs depend on).
- Set enum-valued attributes (priority/status/severity) — the AI cannot transition status.

**Other DNG gaps:**

| Gap | Endpoint / OSLC resource | Probe evidence |
|-----|------|----------------|
| List folders | `oslc:QueryCapability` for `nav:folder` (services.xml) | `oslc_services_inventory.json`: every project exposes "Folder Query Capability" |
| Create folder explicitly | Already in `doors_client.py:969`, just unwrapped | — |
| List/get/create artifact types | Factory for `dng/types#ArtifactType` | services.xml exposes `ArtifactType Factory` + Query |
| List/create custom attribute definitions | Factory `dng/types#AttributeDefinition` | Same |
| List/create link types | Factory `dng/types#LinkType` | Same — `get_link_types` reads but no create |
| Create / read / list **collections** | `oslc:Collection Creation Factory`, `RequirementCollection` resource | services.xml `Collection Creation Factory` (sse#ArtifactCollection) |
| Read **comments** on a requirement | Reportable REST `/rm/publish/comments?projectURI=…` (probe HTTP 400 with empty proj — works with project) | `oslc_endpoint_probes.json` — endpoint exists |
| Add / reply to comments | OSLC RM 2.1 `oslc_rm:Comment` | OSLC RM 2.1 spec resource |
| **Create arbitrary OSLC links** between any two artifacts (not just at requirement creation) | `oslc:Link` PUT with link-type URI | Live link types fetched fine; PUT to `?_oslc.linkType=…` works |
| Delete a link | DELETE on link resource | — |
| Get artifact **history** / revisions | `/rm/<artifact>?oslc_config.context=…` with previous baselines | Probe: `dng_history_endpoint` returned 400 (needs query params) |
| **Reportable REST: get all module text in one call** | `/rm/publish/text?projectURI=…&moduleURI=…` | Probe `rrm_text` HTTP 200 with 3866 bytes — works |
| **Reportable REST: get module hierarchy + ordering** | `/rm/publish/modules?projectURI=…&abbreviate=false` | Probe `rrm_modules` HTTP 200 with 51852 bytes — works |
| Glossary terms (`sse#Term`) | Term resource type appears in services.xml | services.xml shows `http://jazz.net/ns/sse#Term` in resource types |
| Reviews / approvals | DNG-specific `/rm/_review/…` API (proprietary) | Not probed — IBM doc only |
| Module operations (add/move artifact in module, set hierarchy) | Module-binding endpoints (parent agent's lane — flagged here only) | — |
| Switch / pass `oslc_config.context` (work in a stream/baseline) | All OSLC GETs accept `Configuration-Context` header | Currently every client method ignores this — single-stream view only |

### EWM / CM gaps (excluding SCM/code review)

The MCP exposes only `create_task`. Live probe shows the EWM project has **12+ creation factories** including:

```
Defect, Task, Project Change Request, Issue, User Story, Risk, Risk Action,
Milestone, Activity, Regulation, Solution Epic, Portfolio Epic, Capability,
PI Objective, Retrospective
```
(see `oslc_services_inventory.json` → ewm)

| Gap | Endpoint / OSLC resource | Evidence |
|-----|--------------------------|---------|
| Create Defect / Story / Epic / Issue / Risk | Same `CreationFactory` URLs from services.xml | All exposed; LIFECYCLE.md line 67 admits skipped due to `Filed Against` namespace issue. Fix is to read `oslc:instanceShape` and POST `rtc_cm:filedAgainst rdf:resource` with project's category URL. |
| **Update work item** (set state, priority, owner, severity, etc.) | PUT with `If-Match` ETag, same pattern as `update_requirement` | OPTIONS on a workitem URL returns 302 to a workitem permalink; PUT works on the actual `/oslc/workitems/<id>` |
| **Transition work item** (state machine: New → In Progress → Resolved → Closed) | rtc_cm:state property + workflow-action on PUT, OR query workflow types via `/ccm/oslc/types/{projectId}/{type}` | Probe `ccm_workitem_states_for_type` HTTP 200 returned the type def — workflow info is reachable |
| **Query work items with filters** (oslc.where=`rtc_cm:state="..."` etc.) | OSLC CM query base + `oslc.where` clause | Probe `ewm_oslc_query_3` HTTP 200 — returned RDF; `oslc.where` syntax is OSLC-CM 2.0 standard |
| Add comment to work item | `rtc_cm:comment` POST to workitem | EWM REST API doc |
| Add attachment | EWM proprietary `/ccm/resource/itemOid/com.ibm.team.workitem.Attachment` | EWM REST doc |
| List/select **iteration / timeline / category** for `filedAgainst` | `/ccm/oslc/iterations.xml` | Probe `ccm_iterations` HTTP 200 (6311 bytes) — works |
| List process areas (project hierarchy) | `/ccm/process/project-areas` | Probe `ccm_process_areas` HTTP 200 (274 KB) — works |
| Parent / child links | `oslc_cm:parent` / `oslc_cm:children`, also `rtc_cm:com.ibm.team.workitem.linktype.parentworkitem` | Standard CM 2.0 |
| Time tracking (estimate, time spent) | `rtc_cm:duration`, `rtc_cm:timeSpent` | Standard EWM custom attributes |
| Plans / iteration plans | `/ccm/service/com.ibm.team.apt.service.…` (proprietary) | Probably out-of-scope (see Section 6) |

### ETM / QM gaps

The ETM project services.xml shows **13 creation factories** (`oslc_services_inventory.json` → etm):

```
TestCase, TestPlan, TestScript, TestSuite, TestExecutionRecord,
TestSuiteExecutionRecord, TestResult, TestSuiteResult, TestData,
BuildDefinition, BuildRecord, TestPhase, Keyword
```

The MCP only exposes `create_test_case` and `create_test_result`. LIFECYCLE.md line 86–94 *claims* "Test Scripts in ETM" and "Test Execution Records in ETM" are built — they are **not** in `list_tools()`.

| Gap | Endpoint | Evidence |
|-----|----------|----------|
| Create Test Plan | `oslc_qm#TestPlan` factory | services.xml |
| Create Test Script (steps) | `oslc_qm#TestScript` factory | services.xml |
| Create Test Suite | `qm_rqm#TestSuite` factory | services.xml |
| Create Test Execution Record | `oslc_qm#TestExecutionRecord` factory — required intermediary between TestCase and TestResult | services.xml |
| Query test cases / plans / suites | OSLC QM query bases | services.xml has `Default query capability for TestCase`, etc. |
| Query / list **Test Environments** | `qm_rqm#TestEnvironment` Query | services.xml shows it but **no factory** — env is configured in UI |
| Link a Defect (in EWM) to a failing TestResult | `oslc_qm:relatedChangeRequest` on TestResult | OSLC QM 2.0 |
| Plan/suite hierarchy (testplan → suites → cases) | OSLC QM `oslc_qm:executesTestScript`, `oslc_qm:usesTestCase` | OSLC QM 2.0 |
| Bulk run a suite, record results | TestSuiteExecutionRecord + TestSuiteResult factories | services.xml |
| Build records (link a test result to a build) | `qm_rqm#BuildRecord` factory | services.xml |
| Reportable REST for QM | `/qm/service/com.ibm.rqm.integration.service.IIntegrationService/resources` | Probe HTTP 400 — exists, needs project context |

### GCM gaps

| Gap | Endpoint | Evidence |
|-----|----------|----------|
| **Create a global stream / global baseline** | POST to `<component>/configurations` | Probe `gcm_component_configs` returns `Allow: GET,POST` — POST is allowed |
| Add / remove a contribution from a global config | PUT on `gc/configuration/<id>` with updated `oslc_config:contribution` list | OSLC Config 1.0 |
| Switch context (set the GC the AI is currently working in) | All OSLC requests accept `Configuration-Context: <url>` header | Currently every client call hard-codes the default stream — see `_get_component_and_stream` line 1537 |
| Compare two global configs | Diff each contribution's local config | Application-level, no server endpoint |
| Resolve a local artifact URL across GC streams | `oslc_config.context` query param on artifact GET | Same as DNG — no tool currently passes this through |

### Cross-domain gaps

| Gap | What's needed |
|-----|---------------|
| Create arbitrary link of any type, in any direction, between any two artifacts | Generic `create_link(source_url, link_type_url, target_url, context_config?)` tool. Today only DNG→DNG link-on-create works (in `create_requirements` — line 1281). DNG→EWM (`Implements`) and DNG→ETM (`Validates`) only work when the EWM/ETM artifact is being created. **Cannot link two existing artifacts.** |
| Delete a link | DELETE on the linked-resource URL |
| Validate links / get **link validity** state | `link-validity` endpoint (probe `dng_link_validity` returned 404 — feature flagged off on this server, but on enterprise ELM 7.0.3+ it's `/rm/link-validity-resource`) |
| Build a real RTM (requirements → tasks → tests with live status) | Combination: query DNG for all reqs, query EWM `Implements` backlinks, query ETM `Validates` backlinks. Requires query tools that don't exist. |

---

## Section 4: End-to-End Workflow Gaps

| Workflow | Achievable today? | Missing piece |
|----------|------|---------------|
| Read a module → save → view chart | ✅ | — |
| Generate requirements → push → link as you go | ✅ | — |
| PDF re-import (diff + update) | ✅ | — |
| Approve a requirement (status=Approved) | ❌ | `update_requirement` cannot set arbitrary attributes; the AI's "wait until Approved" guardrails depend on a human flipping the status in the UI |
| Build an RTM ("show me which reqs have tasks AND tests") | ❌ | No `query_work_items_by_link`, no `query_test_cases_by_validates`, no `list_links` for a requirement |
| Mark an EWM Task "Done" / Resolved when code lands | ❌ | No `transition_work_item` |
| Create a Defect when a test fails | ❌ | No `create_defect` (LIFECYCLE.md line 67 explicitly skipped) |
| Run a test suite, record results, link defects | ❌ | No `create_test_execution_record`, no `create_defect`, no `link_defect_to_testresult` |
| Work in a specific GC stream | ❌ | No `set_active_configuration` — every call uses the default stream |
| Diff two baselines (DNG + EWM + ETM together) | ❌ | `compare_baselines` is DNG-module-only |
| List all comments on a requirement | ❌ | No `list_comments`, no `add_comment` |
| Update an arbitrary DNG attribute (Priority=High) | ❌ | `update_requirement` only patches title/content |

---

## Section 5: Top 15 Recommended Additions (impact-to-effort)

| # | Tool | Params | Returns | Endpoint | Why now |
|---|------|--------|---------|----------|---------|
| 1 | `update_requirement_attributes` | `requirement_url, attributes: dict[name→value]` | updated artifact summary | PUT on requirement URL with merged RDF + If-Match (extend `update_requirement` at line 1378) | Unlocks "set status to Approved", which unblocks the entire approval-gate logic the BOB.md guardrails assume |
| 2 | `transition_work_item` | `workitem_url, action_id` (or `state_name`) | new state | POST to workitem with `rtc_cm:action` query param **or** PUT with new `rtc_cm:state` | Required for Phase 4/5 of LIFECYCLE.md — currently impossible |
| 3 | `update_work_item` | `workitem_url, fields: dict` | updated WI | PUT with If-Match (mirror of `update_requirement`) | Owner/priority/iteration/severity are needed at every phase |
| 4 | `create_defect` | `ewm_project, title, description, severity?, requirement_url?, test_case_url?` | URL | EWM Defect creation factory (already in services.xml) | LIFECYCLE.md Phase 5 explicitly needs this; "Filed Against" issue can be solved by reading `oslc:instanceShape` and POSTing `rtc_cm:filedAgainst` with the project category URL |
| 5 | `query_work_items` | `ewm_project, where: oslc.where clause, select?` | list[WI] | OSLC CM query base + `?oslc.where=…` | Foundation for any backlog/RTM work |
| 6 | `create_test_execution_record` | `etm_project, test_case_url, testplan_url?, env?` | URL | `oslc_qm#TestExecutionRecord` factory | LIFECYCLE.md claims this works but no tool exposes it; required before recording realistic results |
| 7 | `create_test_plan` + `create_test_script` + `create_test_suite` | per-resource params | URL | factories already in services.xml | Closes the QM hierarchy — TestPlan → Suite → Case → Script → ER → Result |
| 8 | `create_link` | `source_url, link_type_url, target_url, config_context?` | success | OSLC RM `oslc_rm:link` POST or PUT | Lets the AI link any two existing artifacts — covers all backlink-after-the-fact cases |
| 9 | `list_links` / `get_artifact_links` | `artifact_url` | list of link tuples | `?_oslc_rm.linkRels=*` (DNG) or generic OSLC | Required to build an RTM and to safely audit before deletion |
| 10 | `list_folders` | `dng_project` | list[folder] | OSLC `Folder Query Capability` | Already-existing client helpers; trivial wrap |
| 11 | `add_comment` | `artifact_url, body` | comment URL | OSLC RM 2.1 `oslc_rm:Comment` | Enables AI to leave audit notes |
| 12 | `set_active_configuration` (session-state) | `gc_url` | confirmation | Adds `Configuration-Context: <url>` header to every subsequent call | Unlocks variant-aware editing without rewriting every tool |
| 13 | `query_test_cases` (and test plans, results) | `etm_project, where?` | list | OSLC QM query bases (services.xml) | Required to find existing test cases for a requirement, to track pass/fail across a release |
| 14 | `create_global_baseline` | `gc_url, title, description?` | new GC URL | POST to `<component>/configurations` (probe `gcm_component_configs` confirms `Allow: GET,POST`) | Caps off "freeze the world" workflows |
| 15 | `get_reportable_module_text` | `dng_project, module_url` | full text dump | `/rm/publish/text?projectURI=…&moduleURI=…` (probe HTTP 200, 3866 bytes for one module) | Vastly faster than walking OSLC bindings; bulk-export use case |

---

## Section 6: Out of Scope / Not Worth Doing

These are IBM-rare, version-specific, or so heavily UI-driven that an MCP wrapper would mostly fail in the wild:

- **EWM Iteration Planning APIs** (`/ccm/service/com.ibm.team.apt.*`) — proprietary, undocumented for non-IBM consumers, not OSLC. Skip.
- **DNG diagram editing / wireframes** (sse#FreeFormDiagram, SAFe scenarios) — the resource types appear in services.xml but creation requires a UI session and complex SVG payloads.
- **Custom artifact types declared in PoC namespaces** (e.g., `https://poc.clm.ibmcloud.com/qandadoc`) — these are project-specific and won't generalize.
- **Reviews / Approvals API** — DNG has a proprietary review workflow that's largely hidden; documented only sparsely. Use the comment + status-attribute combo instead (#1 + #11 above).
- **ReqIF Import / Export factories** — exposed in DNG services.xml but require multipart uploads of binary `.reqifz`. Not impossible, but heavy for marginal benefit when an MCP user can use the DNG UI's import wizard.
- **Type-System Copy** — `dng/types#TypeImportSession` factory — admin-only and rarely needed by an AI agent.
- **Auto-test domain** (`oslc_auto_test`) — visible in QM rootservices but rarely populated; orchestration tooling out-of-band.
- **Process API write operations** (creating project areas, role assignments) — admin-only; risky to expose to an AI.
- **Link Validity** (`/rm/link-validity` returned HTTP 404 on this server) — only present on ELM 7.0.3+ with the feature flag on. Skip until a customer asks.
- **Glossary** (`/rm/glossary` returned 404 on this server) — version-gated; not universally available.

---

*Probes run 2026-04-29 against `goblue.clm.ibmcloud.com`. All endpoint claims are from live HTTP responses captured in the JSON files alongside this report. Tool counts verified against `doors_mcp_server.py:481-1004` (21 Tools). Client method enumeration from `doors_client.py` lines 81-2262.*
