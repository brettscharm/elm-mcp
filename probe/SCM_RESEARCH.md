# SCM / Code Review research for `doors-next-ai-agent`

Research target: extend the MCP server with EWM/RTC SCM and code-review tools so an AI assistant can use the same workflows the four jazz.net "Bob" articles describe — but driven by REST instead of the EWM CLI.

Live server probed: `https://goblue.clm.ibmcloud.com` as `brettscharmettibm` (read-only).
Generated probe scripts: `probe/scm_01_*` … `probe/scm_05_*` (see file list at the end).

---

## 1. The four articles — short summaries

The articles are **conceptual / UX guides for the "Bob" AI assistant**, not REST references. None of them publishes an HTTP method, URL, or header. They describe workflows the user wants the LLM to perform:

- **Article 98473 — *Part 1: Set up Bob to work with EWM SCM*.** Install/config-only: download `scm` CLI, add to PATH, verify with `scm help` / `scm version`, install the EWM VS Code extension, point Bob at the SCM daemon. Confirms that Bob's "official" path is the EWM CLI, not REST. Implication for us: there is no documented public REST surface for these flows; we have to derive one from the EWM rootservices and OSLC SCM 2.0 spec.
- **Article 98480 — *Part 2: Daily development tasks*.** Conversational workflow that maps onto these CLI commands: `scm status`, `scm accept`, `scm create changeset`, `scm checkin`, `scm associate <wi>`, `scm deliver`. Surface implied: list incoming/outgoing changes for a workspace, create/load change-sets, link change-set ↔ work-item, do a pre-deliver dry-run, deliver if clean.
- **Article 98650 — *Part 3: Code reviews*.** Bob runs custom-mode reviews against changeset diffs, flags findings by severity (high/medium/low), and proposes fixes. Review rules live in `.bob/custom_modes.yaml` — *client-side*. The article never describes posting a review back to EWM. So our MCP must (a) fetch the diff for a change-set so the LLM can review it, and (b) optionally write the review verdict as an EWM **approval** (the formal review record on the work-item).
- **Article 98700 — *Part 4: Build an EWM release pipeline*.** Pipeline / build-engine / build-definition focused; Eclipse-IDE driven. Out of scope for the first SCM milestone but informs a later "build" tool family.

> Bottom line: **Treat the articles as a UX spec, not an API spec.** The actual API surface has to come from EWM's OSLC SCM domain + reportable REST + OSLC CM (work items) + the proprietary `/ccm/rtcoslc/...` paths discovered by probe.

---

## 2. Endpoint inventory (what we found on the live server)

Authentication: same form-based / Basic-auth flow `DOORSNextClient.authenticate()` already does (`doors_client.py:81`). No extra headers needed — the existing logged-in `client.session` works against every endpoint below. All probes used `OSLC-Core-Version: 2.0` plus the listed `Accept`.

| # | Purpose | Method | URL | Accept | Status on goblue |
|---|---|---|---|---|---|
| 1 | EWM rootservices (advertises everything else) | GET | `/ccm/rootservices` | `application/rdf+xml` | **200, 14 KB** (`probe/scm_01_ccm_rootservices.xml`) |
| 2 | **OSLC SCM 2.0 ServiceProvider catalog** (NB: hyphen, not underscore) | GET | `/ccm/oslc-scm/catalog` | `application/rdf+xml` | **200, 82 KB, 105 providers** (`probe/scm_02_catalog.xml`) |
| 3 | Per-project SCM ServiceProvider | GET | `/ccm/rtcoslc/oslc_scm/scm/serviceprovider/project-area/<paId>` | `application/rdf+xml` | **200**, but only exposes a **File-Selection Dialog** — no QueryCapability or CreationFactory (`probe/scm_02_provider_0.xml:8-15`) |
| 4 | Reportable REST for SCM (workspaces, components, change-sets, statistics) | GET | `/ccm/rpt/repository/scm` | `application/xml` | **200**; field syntax is strict — `metadata=schema` works; named field selectors mostly rejected (see Gotchas) (`probe/scm_03_rpt_schema.xml`) |
| 5 | Reportable REST for SCM — XSD schema | GET | `/ccm/rpt/repository/scm?metadata=schema` | `application/xml` | **200, 8.5 KB** — gives the full type tree: Workspace / Component / ChangeSet / Statistics / Changes (`probe/scm_03_rpt_schema.xml`) |
| 6 | TRS 2.0 feed: change-sets | GET | `/ccm/rtcoslc/scm/reportable/trs/cs` | `application/rdf+xml` | **200, 2.7 KB** — recent change-set URIs (`probe/scm_03_trs_changesets.xml`) |
| 7 | TRS 2.0 feed: change-set ↔ work-item links | GET | `/ccm/rtcoslc/scm/cslink/trs` | `application/rdf+xml` | **200, 23 KB** (`probe/scm_03_trs_cslinks.xml`) |
| 8 | TRS 2.0 feed: SCM configurations | GET | `/ccm/rtcoslc/trs/scm/config` | `application/rdf+xml` | **200, 800 b** |
| 9 | Change-set base resource (full RDF for one CS) | GET | `/ccm/rtcoslc/scm/reportable/cs/<csId>` | `application/rdf+xml` | **200**, ~1.9 KB per CS — has `dcterms:title`, `scm:component`, `dcterms:contributor`, `scm:totalChanges`, `process:projectArea` (`probe/scm_04_changeset_first.xml`) |
| 10 | Canonical change-set resource | GET | `/ccm/resource/itemOid/com.ibm.team.scm.ChangeSet/<csId>` | `application/rdf+xml` | **200** (referenced from #9 and from work-item `tracksChangeSet`) |
| 11 | Work-item by friendly id | GET | `/ccm/resource/itemName/com.ibm.team.workitem.WorkItem/<id>` | `application/rdf+xml` | **200** — full RDF including approvals/changesets (`probe/scm_05_wi_3323.xml`) |
| 12 | OSLC CM workitems query (per project area) | GET | `/ccm/oslc/contexts/<paId>/workitems` | `application/rdf+xml` | **200**; supports `oslc.where`, `oslc.select`, `oslc.pageSize` (`probe/scm_05_wi_query_default.xml`) |
| 13 | OSLC CM workitem services | GET | `/ccm/oslc/contexts/<paId>/workitems/services.xml` | `application/rdf+xml` | **200, 30 KB** (`probe/scm_05_sd_services.xml`) |
| 14 | OSLC CM approvals query | GET | `/ccm/oslc/contexts/<paId>/workitems/approvals` | `application/rdf+xml` | **302** to a query with result-token (works, just needs follow-redirects) |
| 15 | EWM internal SCM service (RPC-style) | GET | `/ccm/service/com.ibm.team.scm.common.IScmService` | `application/json` | **200** but empty body — entry point only; useful operations require POST RPC payloads (skip) |
| 16 | EWM internal SCM query service | GET | `/ccm/service/com.ibm.team.scm.common.IScmQueryService` | — | **400** "service cannot run" — needs explicit operation suffix (skip) |
| 17 | `/ccm/oslc/scm/catalog`, `/ccm/oslc/workspaces`, `/ccm/oslc/scm/workspaces`, `/ccm/oslc/reviews/*` | GET | various | — | **404** — these older guesses are not exposed on this server |

**What is NOT available:**

- No standard OSLC SCM 2.0 query capabilities — the per-project ServiceProvider only ships an OSLC selection dialog (file-picker). All listing has to go through reportable REST or the work-item OSLC.
- No public `/oslc/reviews/*` endpoint. Code reviews on EWM aren't a separate REST domain — they're work-items of type `com.ibm.team.review.workItemType.review` plus standard Approval records.
- No work-items of type *review* exist on this instance (we queried all 30 EWM project areas). The Approval mechanism is still usable — every work-item has approvals.

---

## 3. Live-server probe results

| Probe | What it tells us |
|---|---|
| `scm_01_*` | Rootservices is the discovery doc. It advertises an `<oslc_scm:scmServiceProviders>` triple at `/ccm/oslc-scm/catalog` and three TRS-2.0 feeds. We **must** GET rootservices first for any SCM tool — bake the URL into the client lazily. |
| `scm_02_*` | The catalog has **105 SCM service providers**, one per project area, each at `/ccm/rtcoslc/oslc_scm/scm/serviceprovider/project-area/<paId>`. Each provider is a thin wrapper exposing only a file-picker Dialog. The interesting `<dcterms:title>` lets us map `paId → project name` cheaply. |
| `scm_03_*` | The reportable-REST schema lists everything we need: `Workspace`, `Component`, `ChangeSet`, `Snapshot`, `Statistics`, `Changes`. Caveat: the runtime `fields` validator is brittle (see Gotchas). |
| `scm_04_*` | Dereferencing a change-set RDF works; example `_UrB4WENEEfGL3a8XuCNang` returned `dcterms:title="Initial for CALHEERS … Default Component"`, `dcterms:contributor=jeff.hanson`, `scm:totalChanges=1`. Real production data, fully readable as `brettscharmettibm`. |
| `scm_05_*` | Work-item 3323 (`probe/scm_05_wi_3323.xml`) is the gold-mine example: it has **two** `rtc_cm:com.ibm.team.filesystem.workitems.change_set.com.ibm.team.scm.ChangeSet` properties + `oslc_cm:approved`/`oslc_cm:reviewed` booleans. The change-set ↔ work-item link is bidirectional and queryable. The Approval shape (from XSD) is `{stateIdentifier, stateName, approver, approvalDescriptor}` — `stateIdentifier` is the state-machine value we'll need. |

---

## 4. Proposed MCP tool surface

Goal — an LLM should be able to chain these without guessing IDs. Every tool that needs a project takes a human-readable name; the client looks it up via the catalog.

| Tool | Params | Returns | Underlying endpoint(s) | Prereq |
|---|---|---|---|---|
| `scm_list_projects` | (none) | `[ {name, projectAreaId, providerUrl} ]` for every CCM project that has SCM data | (1) GET `/ccm/oslc-scm/catalog`; (2) parse `<dcterms:title>` per provider | none |
| `scm_list_workspaces` | `project_name: str`, optional `streams_only: bool` | `[ {itemId, name, description, isStream, owner, modified} ]` | GET `/ccm/rpt/repository/scm?fields=workspace/(itemId\|name\|description\|stream\|modified\|modifiedBy/name)&filter=projectArea/itemId=<paId>` (see Gotcha #2 for syntax) | `scm_list_projects` |
| `scm_list_components` | `project_name: str` | `[ {itemId, name, modified} ]` | GET `/ccm/rpt/repository/scm?fields=component/(itemId\|name\|modified)&filter=…` | `scm_list_projects` |
| `scm_list_changesets` | `project_name: str`, `since?: ISO8601`, `author?: str`, `component_name?: str`, `limit?: int=25` | `[ {itemId, title, component, author, modified, totalChanges, workItems[]} ]` | (1) Catalog → resolve `paId`; (2) GET `/ccm/rtcoslc/scm/reportable/trs/cs` for recent IDs (paginated TRS); (3) For each, GET `/ccm/rtcoslc/scm/reportable/cs/<csId>`; (4) For work-item links, GET `/ccm/rtcoslc/scm/cslink/trs` then per-link resource | `scm_list_projects` |
| `scm_get_changeset` | `changeset_id: str` (the `_xxx` itemId) | `{itemId, title, component, author, modified, totalChanges, workItemIds[], rawRDF}` | GET `/ccm/rtcoslc/scm/reportable/cs/<csId>` + GET `/ccm/resource/itemOid/com.ibm.team.scm.ChangeSet/<csId>` | none |
| `scm_get_changeset_diff` | `changeset_id: str`, `format?: "unified"\|"json"=unified` | `{ files: [ {path, op, beforeContent?, afterContent?} ] }` | GET file-versions per change → uses the FileVersion content service (not yet probed; planned via the file-picker Dialog's selection-dialog pattern, fallback to `/ccm/service/com.ibm.team.scm.common.IVersionedContentService`) | `scm_get_changeset` |
| `scm_get_workitem_changesets` | `workitem_id: str` (numeric) | `[ {changeSetId, title} ]` | GET `/ccm/resource/itemName/com.ibm.team.workitem.WorkItem/<id>`, parse `rtc_cm:…ChangeSet` triples | none |
| `scm_get_changeset_workitems` | `changeset_id: str` | `[ {workItemId, title} ]` | scan `/ccm/rtcoslc/scm/cslink/trs` for the change-set OID | none |
| `review_list_open` | `project_name: str` | `[ {workItemId, title, type, state, approvals[]} ]` | OSLC CM query: `/ccm/oslc/contexts/<paId>/workitems?oslc.where=rtc_cm:type="com.ibm.team.review.workItemType.review"%20and%20oslc_cm:closed=false` | `scm_list_projects` |
| `review_get` | `workitem_id: str` | `{title, state, approvals: [ {approver, descriptor, state, stateName} ], changeSets: [...], comments: [...] }` | GET work-item + parse `oslc_cm:approved/reviewed` + linked change-sets + `oslc:discussedBy` | none |
| `review_summarize` (LLM-side) | `workitem_id: str`, optional `mode: str="default"` | `{verdict, findings: [ {severity, file, line, message, suggestion} ]}` | composes `scm_get_changeset_diff` over each linked CS + LLM analysis (no server call beyond the diff) | `review_get` |

> Tools that POST (record-an-approval, deliver, etc.) are **deferred to phase 2** — the user mandated read-only for this research pass and the article workflow can be approximated without them.

The "first-try-works" ergonomic comes from three things: (a) every tool that needs a project takes the human name, (b) `changeset_id` and `workitem_id` are the natural identifiers users see in the EWM UI, (c) the catalog + cslink TRS together remove the need to know `paId`s.

---

## 5. Gotchas

1. **Catalog URL is `oslc-scm` (hyphen), not `oslc_scm`.** Three other URL variants we tested 404'd. Found via rootservices discovery; do not hard-code without going through rootservices first.
2. **Reportable-REST `fields` syntax is brittle.** `fields=workspace/*` returns a 200 with empty workspace tags. `fields=workspace/(name)` is rejected as "not a valid field name" even though the XSD declares `name`. `fields=workspace.name` returns 200 but no body either. Workaround: use `metadata=schema` to discover types, then test the *exact* spelling on a known instance — there is server-version drift here. The schema in `probe/scm_03_rpt_schema.xml` lists ten fields per Workspace; `name`, `description`, `stream` are the ones we care about — implementation should fall back to `fields=workspace` (default representation) and parse whatever XML comes back.
3. **OSLC SCM ServiceProvider has no QueryCapability or CreationFactory.** Don't waste time looking for the OSLC standard discovery pattern under `/ccm/oslc-scm/...` — IBM only ships the file-selection Dialog (`probe/scm_02_provider_0.xml:8-15`). You have to use either reportable REST or the proprietary `/ccm/rtcoslc/scm/...` endpoints for the actual data.
4. **Approval queries 302 to a result-token URL.** `requests.Session.get(...)` will follow it by default (we used `allow_redirects=False` only for diagnostic purposes). Don't disable redirects in tools.
5. **Large EWM-CCM `services.xml` (30 KB) parses slowly.** Cache them per project per session.
6. **No code-review work-items existed in any of the 30 EWM project areas we sampled.** That doesn't mean the API is broken — it means we can't end-to-end-validate the `review_*` tools against this instance for "happy-path real review data". We can validate against generic work-item approvals (every WI in the system has the approval shape).
7. **EWM proprietary `/ccm/service/com.ibm.team.scm.*` endpoints exist but require RPC-style POST bodies** with the operation as a path suffix (e.g. `…/IScmQueryService/findItems`). They're version-fragile and undocumented. **Avoid for v1** — reportable REST + TRS feeds + canonical resources cover all read flows.
8. **Diff content (file-version bytes) is the hard part.** The reportable REST returns metadata only; we still need to (a) traverse the change-set's `Changes` to get per-file before/after item-IDs, then (b) GET the FileVersion bytes from a non-OSLC content service that the file-picker Dialog discovers at runtime. Probe phase 2 should hit `/ccm/service/com.ibm.team.scm.common.IVersionedContentService/contentVersion/{id}` once we have a real change-set with file content (the demo ones are all "Initial" placeholder change-sets with no diff content yet).
9. **TRS feeds are paginated by `<trs:previous>` — they only return ~5 most recent changes per page**, then a previous-page link. To list "all change-sets" we have to walk the previous chain. For "recent change-sets" we just take the first page. Document this in the tool description so the LLM doesn't expect completeness.
10. **Permissions:** `brettscharmettibm` can read every change-set we've tried, but workspace listing returned empty — that's because workspaces are owned by individual users and our user has none. Streams (workspaces with `<scm:stream>true</scm:stream>`) should still be visible — but our current `fields` syntax doesn't return populated rows on this server, so we need to verify against a server where the syntax is known to work.

---

## 6. Recommended implementation order

1. **`scm_list_projects`** — purely catalog parsing; trivial; everything else depends on it. (Half a day.)
2. **`scm_list_changesets` + `scm_get_changeset`** via TRS + reportable-base resource. Read-only, immediately useful, gives the LLM something to talk about. (One day.)
3. **`scm_get_workitem_changesets`** — single work-item GET, parse RDF triples. Lets the LLM connect SCM↔work-item without leaving CCM. (Half a day.)
4. **`review_get` + `review_list_open`** — OSLC CM queries with the type filter; no new endpoints. Do this even though demo data is empty — the API works. (One day.)
5. **`scm_list_workspaces` / `scm_list_components`** — lower priority; needs the Reportable-REST `fields` quirk solved first. Stub initially with the catalog data we already have (project name + paId). (One day, blocked on the field syntax.)
6. **`scm_get_changeset_diff`** — the highest-leverage tool for the article workflow ("review my changes"). Requires solving the FileVersion content service. **Spike a probe (`scm_06_diff.py`) before committing to a design** — the binary path differs across EWM versions. (Two-three days.)
7. **Phase 2 (write):** `review_record_approval`, `scm_associate_workitem`, `scm_deliver_changeset`. Deliberately deferred — write paths require extra auth tokens (CSRF / `X-Jazz-CSRF-Prevent`) and the OSLC CM `Update` flows that are well-documented but invasive.

---

## 7. Probe artifacts (file index)

Scripts:
- `probe/scm_01_rootservices_and_catalog.py` — catalog discovery
- `probe/scm_02_catalog_and_providers.py` — service-provider listing
- `probe/scm_03_proprietary_endpoints.py` — TRS / reportable / RPC sweep
- `probe/scm_04_trs_resources.py` — change-set dereferencing
- `probe/scm_05_code_reviews.py` — work-item approvals & review-type WIs

Raw responses worth keeping for offline reference:
- `probe/scm_01_ccm_rootservices.xml` (rootservices)
- `probe/scm_02_catalog.xml` (105 service providers)
- `probe/scm_02_provider_0.xml` (typical SP — only a file-picker)
- `probe/scm_03_rpt_schema.xml` (full reportable-REST XSD for SCM)
- `probe/scm_03_trs_changesets.xml` / `scm_03_trs_cslinks.xml` (TRS feeds)
- `probe/scm_04_changeset_first.xml` (real change-set RDF)
- `probe/scm_05_wi_3323.xml` (work-item with linked change-sets and approvals)
- `probe/scm_05_wi_schema.xml` (workitem reportable-REST XSD — has Approval / ApprovalState / ApprovalDescriptor types)

---

*The articles tell us what to build; the probes tell us what we can build today. Phase 1 (read-only catalog + change-sets + work-item linkage + approvals) is fully feasible against this live instance with no new auth, no extra headers, and the existing `DOORSNextClient.session`.*
