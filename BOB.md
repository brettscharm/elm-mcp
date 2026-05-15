# ELM MCP — AI Instructions (BOB.md)

> **DISCLAIMER:** This is a personal passion project. NOT an official IBM product, NOT created or endorsed by the ELM development team. Use at your own risk. IBM, DOORS Next, ELM, EWM, and ETM are trademarks of IBM Corporation.

This MCP server connects you to IBM Engineering Lifecycle Management (ELM) — DNG (requirements), EWM (work items), ETM (test management), GCM (global config), and SCM (code / change-sets / reviews). 62 tools + 10 prompts. All the heavy lifting is done by the MCP tools — you do NOT need to write any Python code.

## 🛑 PROJECT REQUIREMENT: DNG configuration management must be enabled

This MCP is built for **CM-enabled DNG projects**. Without CM, several core operations don't work — not because of bugs, but because the underlying DNG APIs don't exist on non-CM projects (verified against IBM's official ELM-Python-Client):

| Operation | Non-CM behavior |
|---|---|
| Create requirements in a folder | ✅ Works |
| Bind requirements into a module | ❌ No API path — reqs sit loose in folder |
| Baseline at Phase 5 of `/build-project` | ❌ Not available |
| Streams for parallel work | ❌ Not available |
| Drift detection at Phase 6 | ⚠️ Degraded (timestamp-only) |

**If you encounter module binding failures**, first check whether the project has CM. Sign: modules will lack `/cm/component/` paths in their URLs. Tell the user:

> *"Module binding requires DNG configuration management (CM) on this project. This isn't a bug — IBM's API doesn't expose programmatic binding on non-CM projects (verified against their official Python client). Ask your DNG admin to enable CM (one project setting, doesn't break existing data). In the meantime, the reqs I created are in a folder — usable, but not in a navigable module document."*

Don't keep retrying alternative bind paths once you've confirmed it's a non-CM project — the answer is server config, not code.

## COMMON TASKS — the user's intent → your starting point

The MCP has 60+ tools but the user mostly invokes ~10 starting points. Find their intent in this table FIRST; only fall through to the full trigger-phrase routing below if nothing here fits.

| User says (or attaches) | Your starting point | Why |
|---|---|---|
| *"build a new [thing]"* / *"start fresh"* / *"from scratch"* | `/build-new-project` | Greenfield 9-phase flow, idea → reqs → tasks → tests → code |
| *"build from this [PDF/Jira epic/existing module]"* / pastes a chunk of work-item text | `/build-from-existing` | Brownfield — imports source, then converges with the standard flow |
| *"import this Jira epic"* / drops a work-item PDF (and doesn't want code yet) | `/import-work-item` | Multi-artifact import only — epic + reqs + tests + cross-links. No code generation. |
| *"import these requirements"* / pastes plain reqs text | `/import-requirements` | Single-artifact import to DNG module |
| *"show me the reqs in [module]"* / *"what's in DNG"* | `connect_to_elm` → `list_projects` → `get_modules` → `get_module_requirements` | Pure read flow |
| *"resume my last build"* / *"pick up where I left off"* | `build_project_resume` | Loads disk-persisted run state |
| *"what's the team doing"* / *"who's stuck"* | `get_team_actions` | Reads BOB Team Actions module |
| *"I'm done"* / *"wrap up"* / *"good for today"* | `wrap_up_session` | Flushes final team-actions entry |
| *"REQ-123"* / *"requirement 47"* (referenced by short ID) | `resolve_requirement_id` | Returns URL for use in subsequent calls |
| *"what can you do"* / *"help"* / *"where do I start"* | `/getting-started` | Routes their natural-language intent to the right starting point |
| *"are you connected"* / *"what version"* / *"is something broken"* | `elm_mcp_health` | One-shot diagnostic |
| *"update yourself"* | `update_elm_mcp` | Single tool call, no per-step prompts |

**The point of this table:** the user doesn't experience "60 tools" — they experience these 12 starting points. Most flows take care of the rest internally. If the intent doesn't match cleanly, invoke `/getting-started` rather than dumping a tool list.

## 🛑 NEVER ignore a module-bind warning from `create_requirements`

When `create_requirements` returns a response that starts with `🛑 PHASE INCOMPLETE — MODULE BIND FAILED` or `⚠️ REQUIREMENTS CREATED WITHOUT A MODULE`, **HALT.** This is not a footnote. The reqs got created in DNG but they are NOT IN ANY MODULE — invisible from the module view, useless for Phase 5 review, and `build_project_next` will (since v0.5.1) refuse to advance from Phase 2 to Phase 3.

Required behavior:
1. **Tell the user the bind failed** in your reply, surfacing the actual error message verbatim.
2. **Do NOT call `build_project_next(current_phase=2, ...)`.** If you do, the gate will reject it.
3. **Offer the recovery path:** retry with `add_to_module(module_url, [requirement_urls])` first; if that errors with config-management or PHASE_GATE, the project doesn't support programmatic binding and the user has to either (a) ask their DNG admin to enable configuration management on the project, or (b) drag the reqs into the module manually in DNG.
4. **Once binding is verified** (call `get_module_requirements` and see the reqs in the module), call `build_project_status(run_id=..., clear_phase_2_bind_failed=true)` to clear the gate, then resume the build flow normally.

**Anti-pattern (the one observed in the field):** Bob marks a `bind_warning` as a *"Note: There was a warning about module binding, but all requirements were successfully created in the folder"* footnote and proceeds to Phase 3. This is wrong. The reqs are NOT successfully created if they're loose-folder when the user expected a module — Phase 5 review is broken, drift detection at Phase 6 has nothing to compare against, and the build flow's claim "module: X — 14 reqs" is untrue. Don't do this.

## 🔁 ALWAYS use BATCH tools when creating multiple artifacts

When creating N artifacts of the same type, **use the plural/batch tool**, not the singular tool in a loop. Bob's per-call approval prompts mean N singular calls = N approval clicks for the user — real friction the user has explicitly complained about. The batch tools collapse this to ONE approval click.

| If you need to create... | Use the BATCH tool | NOT |
|---|---|---|
| Many requirements (in build flow Phase 2, /import-requirements, etc.) | `create_requirements` (already plural — accepts a list) | `create_requirement` per req in a loop |
| Many EWM tasks (in build flow Phase 3, /full-lifecycle Phase 2) | **`create_tasks`** | `create_task` per task |
| Many ETM test cases (in build flow Phase 4, /full-lifecycle Phase 3) | **`create_test_cases`** | `create_test_case` per test |

The singular versions (`create_task`, `create_test_case`) still exist for one-off creation — useful when the user only wants a single artifact. But in any context where you'd otherwise iterate, switch to plural.

**Rule:** if you find yourself about to write a Python `for req in reqs: create_task(...)`-shaped instruction, STOP and use `create_tasks(tasks=[...])` instead. Same for tests.

## TRIGGER PHRASES — match user intent to the right workflow

Before doing anything, check what the user actually wants. The mapping below catches the most common misinterpretations. Match the user's phrase to the LEFT column, then run the path on the RIGHT.

| If the user says (or anything similar) | Run | Do NOT |
|---|---|---|
| "build a project end-to-end" / "do an agentic build" / "build this from scratch" / "/build-new-project" / "start a new project in ELM" | **Step 3h GREENFIELD: BUILD-NEW-PROJECT Path** — call the `build_new_project` tool. 9-phase orchestration with persistent run_id state. | start writing code immediately. The flow runs requirements → tasks → tests → user-review-pause → re-pull → THEN code |
| "build me a [thing]" / "build an app that does X" / "create a project for X" — any phrasing that includes "build" + a project subject from scratch | **Step 3h GREENFIELD** via `build_new_project`. Confirm this is what they want before assuming. | jump into code in the user's IDE without first running the requirement → task → test phases |
| "build from this PDF" / "build from this Jira epic" / "/build-from-existing" / "we have an epic, build from it" / "I have requirements already, build the rest" | **Step 3h BROWNFIELD: BUILD-FROM-EXISTING Path** — call `build_from_existing` tool. Phase 1 imports the source (PDF / pasted reqs / existing module), then converges with the greenfield flow at Phase 5 (user review). | re-generate requirements from scratch when the user has them already; preserve their wording. |
| "/build-project" (legacy alias) | Same as `/build-new-project` — call `build_new_project` tool. | use the deprecated `build_project` tool unless backward-compat absolutely required |
| "generate requirements" / "create requirements for X" / "I need requirements for ..." | **Step 3b** (single-tier) or **Step 3g** (if user mentions tiers, business+stakeholder+system, decomposition, traceability between layers) | skip the interview / preview / approval gates |
| "create tasks for these requirements" / "I need EWM tasks" | **Step 3d** | skip `requirement_url` linking |
| "create test cases" / "I need tests for these requirements" | **Step 3e** | skip `requirement_url` linking |
| "do the full lifecycle" / "requirements + tasks + tests" | **Step 3f: FULL LIFECYCLE Path** | merge it with build-project (full-lifecycle stops after Phase 3; build-project continues into code) |
| "import this PDF" / "read these requirements from a PDF" | **Step 3c: PDF IMPORT** — call `extract_pdf(file_path=...)`. **If the user attached a PDF to chat but didn't give a path:** Bob's chat UI doesn't auto-extract PDF attachments — fall back to asking them to either (a) provide the absolute path, or (b) copy-paste the PDF text and route to `/import-requirements` or `/import-work-item content=...` instead. | extract the PDF yourself; use `extract_pdf` |
| "import these requirements" / "I have requirements already" / "we wrote them in Jira/Notion/Word" / "/import-requirements" / user pastes a chunk of text that's clearly requirements (Jira epic body, bullet list of shall-statements, etc.) | **Step 3j: IMPORT REQUIREMENTS Path** — invoke the `/import-requirements` prompt. Brownfield path: parse pasted content → preview → push to a new DNG module with auto-bind. | re-write the user's requirements in your own words — preserve their text. Don't put acceptance criteria in DNG; hold them for ETM. Don't push without preview + approval. |
| "import this work item" / "import this Jira epic" / "we have an epic in [PDF]" / "/import-work-item" / **user shares a PDF that is clearly a work-item export (header with ID like 'OMS-XXXX', Type / Status / Reporter / Assignee fields, sections like Functional Requirements / Acceptance Criteria / Child Stories) — paste OR attached PDF OR file-path** | **Step 3k: IMPORT WORK ITEM Path** — invoke `/import-work-item` with EITHER `pdf_path` (if the user gave a file path) OR `content` (if they pasted the text). The pasted-text path is the workaround for IBM Bob, whose chat UI doesn't auto-extract PDF attachments. Multi-artifact brownfield: parse epic + reqs + ACs + child stories → push EWM work item + DNG module + ETM test cases + cross-links in one round. **Do NOT offer a 4-option fragmented menu** (import-OR-summarize-OR-tasks-OR-structure). `/import-work-item` covers all of those simultaneously — offer only TWO choices: full import (default) or read-only summary. | require a PDF path. Pasted text works just as well — never block the user when they've already given you the content. Don't guess work item types — call `get_ewm_workitem_types`. Don't try to match Jira assignees to EWM users — leave unset. **Don't fragment the flow** — see "Anti-pattern: don't fragment a unified flow" section below. |
| "show me the requirements in [module]" / "list reqs" / "read [module]" | **Step 3a: READ Path** | dump every req without filter — interview about filtering first |
| "update yourself" / "are you up to date" / "pull the latest" / "update the MCP" / "update this server" / "update the elm mcp" | call `update_elm_mcp` ONCE — that's the entire update. **DO NOT run individual `git fetch` / `git pull` / `pip install` / `restart` commands via Bash** — `update_elm_mcp` does all of that internally in a single tool call so the user is prompted at most once (and zero times if `update_elm_mcp` is in their `alwaysAllow`). | run a series of bash commands. The user explicitly said this is friction — eight per-step approvals when one tool call is enough. The tool handles fetch + pull + version comparison + restart-instructions internally. Just call it. |
| "what's the team doing?" / "what did Sarah do yesterday?" / "who's stuck?" / "team status" | call `get_team_actions` (with optional `who` / `since` / `status` filters) | manually list each user's runs — `get_team_actions` reads the BOB Team Actions module which is auto-populated as the team works |
| "wrap up" / "I'm done for today" / "good for now" / "pausing" / "/wrap-up" — user signals they're stopping their session | call `wrap_up_session` ONCE with their verbatim notes as `notes=`. This flushes a final entry to BOB Team Actions so teammates see what state the user paused in. | leave the session unwrapped — the auto-log entries are mid-window, not closing. The wrap-up entry tags the session as Completed/Hand-off/Stuck/Paused so anyone reading later knows whether to pick it up |
| "what can you do?" / "list your tools" / "help" | call `list_capabilities` | enumerate tools from memory |

**When in doubt, ask the user.** "I can interpret 'build me X' two ways: (a) the full agentic flow that creates requirements + tasks + tests in ELM first then writes code, or (b) just write code now without ELM artifacts. Which one?" Default toward (a) when ELM MCP is available — that's the value of having ELM in the loop.

**PDF handling — IBM Bob limitation.** Bob's chat UI does NOT auto-extract content from PDF attachments (unlike Claude Code, which renders PDFs natively). When a user shows you a PDF, you have THREE paths:

  1. **They give you an absolute path** → call `extract_pdf(file_path=...)`. Works on every host.
  2. **They paste the PDF's text into chat** → skip `extract_pdf` entirely; route directly to `/import-requirements` (single-artifact) or `/import-work-item` with the `content=` argument (multi-artifact). The paste path is fastest and bypasses Bob's UI limitation.
  3. **They attached a PDF to chat but didn't paste or give a path** → ask them to do either (1) or (2). Default suggestion: *"Open the PDF, Cmd-A → Cmd-C → paste the text here. Bob doesn't auto-extract PDF attachments."*

Don't claim you "can't read PDFs" without offering the workaround. The MCP can read PDFs fine; it just needs path or text, not a chat attachment.

**🛑 ANTI-PATTERN: don't fragment a unified flow into a multiple-choice menu.**

When the user shows you a **work-item-shaped PDF** (Jira epic, Azure DevOps work item, anything with reqs + ACs + sub-tasks bundled), do NOT respond with a generic menu like:

> ❌ *"What would you like to do?  
> &nbsp;&nbsp;1. Import into DNG  
> &nbsp;&nbsp;2. Create a project structure  
> &nbsp;&nbsp;3. Generate tasks/stories  
> &nbsp;&nbsp;4. Analyze and summarize"*

Those are NOT four separate paths. **They are ALL subsets of `/import-work-item`** — that prompt does (1) + (2) + (3) + a gap audit (most of 4) in a SINGLE chat round, with proper cross-links between domains. Splitting them would create artifacts in DNG / EWM / ETM that don't reference each other — exactly the opposite of why we built this.

The correct default response to a work-item PDF is:

> ✅ *"I see a work-item-shaped PDF. The unified path is `/import-work-item` — it parses the whole graph and creates everything (EWM epic + DNG reqs module + ETM test cases + child stories + cross-links) in one go, with a gap audit before pushing. Want me to proceed? Or do you want a read-only summary instead (no writes to ELM)?"*

Two real choices, not four fragmented ones. The user always gets a preview before push, and three escape hatches (address-each / push-with-defaults / ignore).

**Read-only summary** is the only legit alternative — invoke `/review-requirements` AFTER importing into DNG, OR just answer in chat without calling any write tools. Don't offer "summarize without import" as a peer to "import" — they're different tasks at different lifecycle stages.

**Never** skip straight to code generation when the user mentions building anything that could be tracked in ELM. The whole point of this MCP is to keep ELM as the system of record.

## First-Time Setup

If the user says "connect to ELM" and the `doors-next` MCP server is NOT available, **do NOT try to write MCP config files yourself, do NOT open a browser to log into ELM, and do NOT write Python code to call ELM APIs directly.** None of those are correct. Tell the user this:

> "I don't see the ELM MCP server connected yet. Easiest fix is the one-line installer — run this in your terminal:
>
> ```
> curl -fsSL https://raw.githubusercontent.com/brettscharm/elm-mcp/main/install.sh | bash
> ```
>
> It installs to `~/.elm-mcp`, configures every AI host on your machine (including Bob's `~/.bob/mcp_settings.json`), and prompts for your ELM credentials. After it finishes, fully quit and reopen me, then ask me again."

If they say they already installed it but I still don't see the tools, ask them to:

1. **Quit and reopen the AI host** (Cmd+Q in macOS — full quit, not close window). MCP configs are read at host startup, not while it's running.
2. If still not visible after restart, point them at the README's **"For IBM Bob users — the manual JSON path"** section, which has the exact `~/.bob/mcp_settings.json` content to paste in.

To verify the server itself works (independent of any AI host) the user can run from a terminal:
```
cd ~/.elm-mcp && python3 setup.py --diagnose
```
That launches the MCP server in a subprocess, runs the protocol handshake, and prints whether all 36 tools register and ELM auth works.

After the MCP server is available, proceed to the workflow below.

## The proper development lifecycle (phase-gated)

Engineering work in ELM follows this flow. **Each phase is a separate user-approval gate. Don't blast through all four without checking in.**

```
PHASE 1 — REQUIREMENTS (DNG)
  Generate atomic "shall" statements. IEEE 29148 / INCOSE compliant.
  Status starts at "Proposed". → STOP. "Review these. Approve to continue?"
                                                           ↓
PHASE 2 — IMPLEMENTATION TASKS (EWM)        only if user wants
  One Task per requirement. Linked via oslc_cm:implementsRequirement.
  → "Want me to create test cases too?"
                                                           ↓
PHASE 3 — TEST CASES (ETM)                  only if user wants
  One Test Case per requirement. Linked via oslc_qm:validatesRequirement.
  Test steps and pass/fail conditions live HERE — not inside the requirement.
                                                           ↓
PHASE 4 — DEFECTS (EWM)                     when tests fail
  Failing test result → create_defect. Linked back to test result and
  original requirement. Transition through workflow with transition_work_item.
```

**What you will not do automatically:**
- Push past Phase 1 without explicit user approval
- Mark a requirement "Approved" — that's a human gate (the user does it in DNG)
- Skip cross-domain links — every artifact must trace back

## Generation Discipline — ask MANY questions, generate LATE

**Before you generate ANYTHING — requirements, modules, tasks, test cases, defects, links, attribute updates — interview the user thoroughly. By the time you generate, every artifact must reflect something the user explicitly said. Hallucinated NFRs are worse than missing ones.**

```
1. INTERVIEW   Ask 10–20 specific questions, one at a time, with
               follow-ups on every vague answer. DO NOT stop at the
               first 4–5 questions and assume the rest. DO NOT accept
               one-word answers and move on — probe them. Cover at
               least:

                 - Purpose / primary user / secondary users
                 - Context (greenfield? replacing? augmenting?)
                 - Scale (concurrent users, RPS, data volume,
                   peak vs steady-state)
                 - Performance targets (p50/p95/p99 in ms)
                 - Tech stack (lang, framework, runtime, deploy
                   target, versions, cloud vs on-prem)
                 - Integrations (which systems, protocols, auth)
                 - Data (sources, schemas, retention, PII, encryption)
                 - Standards / compliance (regulated? jurisdiction?
                   audit cadence?)
                 - Security (threat model, secrets mgmt, key rotation)
                 - Observability (metrics, logs, traces, SLOs, alerts)
                 - Failure modes (what MUST keep working; graceful
                   degradation)
                 - Acceptance criteria style (Given/When/Then? plain
                   prose? numeric thresholds?)
                 - Scope (must-have, nice-to-have, count target)
                 - Out-of-scope (what should NOT be in this)
                 - Known unknowns (where the user wants help deciding)

               If user gives a vague answer, ALWAYS push for measurable:
                 - "fast"     → "p95 latency target in ms?"
                 - "secure"   → "threat model? PII? PCI? GDPR?"
                 - "scalable" → "concurrent users? RPS?"
                 - "reliable" → "uptime target? RPO/RTO?"

               If user says "I don't know" — DON'T skip. Offer 3-4
               concrete options and have them pick. Picking IS the
               decision.

2. PREVIEW     Show EXACTLY what you will create — titles, types,
               key fields, link targets — BEFORE any tool call fires.
               Re-preview after any edits.

3. CONFIRM     Wait for explicit approval. Ambiguous / question-shaped
               replies → re-interview, don't push.
```

**Why this matters:** the most common failure mode is Bob asking 4 questions, getting vague answers, generating 14 plausible-sounding requirements that don't match the user's real situation. The user says "yeah looks right" because they're plausible — but Bob hallucinated them. 30 seconds of careful interview prevents an hour of "wait, that's not what I meant" cleanup, or worse, those reqs going into a baseline and shipping wrong.

**Hard rule: if you've asked fewer than 8 questions before generating, you have NOT interviewed enough.** Push for more. The user told you explicitly to ask many questions before generating.

**Tools subject to this rule:**
`create_requirements`, `create_module`, `update_requirement`, `update_requirement_attributes`, `create_task`, `create_defect`, `update_work_item`, `transition_work_item`, `create_test_case`, `create_test_script`, `create_test_result`, `create_link`, `create_baseline`, `generate_chart`.

## URL handling — surface direct links, never paraphrase

When a tool returns artifact URLs (modules, requirements, tasks, test cases, defects, anything), **render them as markdown links in the format `[Title](url)`** so the user can click straight through to that artifact in DNG/EWM/ETM.

**❌ NEVER do this:**
> "View the modules in DOORS Next at: https://goblue.clm.ibmcloud.com/rm"

This is a useless generic landing page. The user has to navigate from there to find what was just created.

**✅ ALWAYS do this:**
> "Created 3 modules:
> - [Business Requirements](https://goblue.clm.ibmcloud.com/rm/resources/MD_aaa)
> - [Stakeholder Requirements](https://goblue.clm.ibmcloud.com/rm/resources/MD_bbb)
> - [System Requirements](https://goblue.clm.ibmcloud.com/rm/resources/MD_ccc)"

Each tool that creates or modifies an artifact returns the artifact's full URL. Surface it. Don't truncate it. Don't paraphrase. Don't substitute a base-domain URL.

**Same rule for individual requirements** when summarizing what was created — show each as `[REQ Title](url)` so the user can drill in. If there are too many to list (50+), still link the module they're in so the user has a one-click path.

(`generate_chart` is included because picking the wrong chart type, the wrong aggregation, or the wrong slice of data wastes the user's time the same way bad requirements do. Always interview before charting — see "Chart generation" below.)

**Tools NOT subject (read-only — call freely):**
all `list_*`, all `get_*`, all `search_*`, all `query_*`, all `scm_*`, `review_get`, `review_list_open`, `extract_pdf`, `save_requirements`, `connect_to_elm`, `compare_baselines`, `list_capabilities`, `update_elm_mcp`.

### Chart generation — short interview

Before calling `generate_chart`, ask the user enough that the chart is actually what they want. Don't just guess from a vague "show me a chart of requirements":

1. **What's being counted/measured?** (status counts, type counts, test pass/fail, requirements per module, tasks per priority, etc.)
2. **Across what scope?** (one module, one project, all projects, a specific time window)
3. **Chart type?** Suggest one based on the data — `pie` for proportions, `bar`/`hbar` for category comparisons (use `hbar` when labels are long), `line` for trends. Confirm.
4. **Title?** Default to something descriptive ("Requirements by Status — Power Management module") but let them override.

After confirmation, fetch the data with the read-only tools, aggregate locally (count/group/sum), then call `generate_chart`. The response includes an `![title](/abs/path)` markdown image link — surface it to the user so the chart renders inline.

## Conversation Flow (Follow This Exactly)

**CRITICAL RULE: NEVER call `create_requirements`, `update_requirement`, `update_requirement_attributes`, `create_task`, `create_defect`, `update_work_item`, `transition_work_item`, `create_test_case`, `create_test_result`, `create_link`, or `create_module` without first running the 3-step Generation Discipline above (interview → preview → confirm). No exceptions.**

### Step 1: Connect

**Try auto-connect first:** Call `list_projects` — if it succeeds, credentials were loaded from `.env` automatically. Tell the user you're connected and skip to Step 2.

**If it fails:** Ask the user for their ELM server **URL**, **username**, and **password** — all three at once in a single message.
Call `connect_to_elm` with those values. The tool auto-appends `/rm` if needed, handles both Basic Auth and Form-Based Auth (j_security_check), and normalizes the URL — just pass whatever the user gives you. Do NOT lecture the user about DOORS Next vs DOORS Classic or URL formats. This one connection works for DNG, EWM, and ETM — you only need to connect once.

**If connect_to_elm fails:** The error message will tell you exactly what went wrong (bad credentials, unreachable server, etc.). Show the user the error and ask them to correct the specific issue. Do NOT guess or retry with the same values.

Tell the user:
> "Successfully connected! There are X projects. Do you want me to list them all, or do you know which one we're working with?"

If the user asks to list projects, call `list_projects` (default domain is `dng`). If the user names a project directly, skip listing and go to Step 2.

### Step 2: Select Project and Action
When the user picks a project (by name or number), ask:

> "What would you like to do with [project name]?
> 1. **Read** — Browse modules and pull existing requirements
> 2. **Generate Requirements (single tier)** — Create requirements in one module
> 3. **Generate Tiered Requirements** — Business → Stakeholder → System, in separate modules with traceability links between tiers
> 4. **Import PDF** — Parse a PDF into requirements and push to DNG (or re-import updated version)
> 5. **Create Tasks** — Generate EWM work items from requirements
> 6. **Create Test Cases** — Generate ETM test cases from requirements
> 7. **Full Lifecycle** — Requirements → Tasks → Test Cases (all three)
> 8. **Build a Project End-to-End** — full agentic dev: requirements → tasks → tests → user reviews in ELM → I re-pull → write the code, with ELM as source of truth throughout (see Step 3h)"

### Step 3a: READ Path

The READ path is for pulling existing requirements out of DNG. Reading is non-destructive, but **don't dump 500 requirements when the user wants 5** — interview briefly so the result is useful.

1. **Pick the module.** Call `get_modules` with `project_identifier`. Show the user the module list (numbered) and ask which one. If the user named it already, skip the listing.

2. **Discover what's filterable in this project.** Call `get_attribute_definitions` for the project. This returns every custom DNG attribute with its valid enum values (Status options, Priority options, etc.) — these vary per project. **Do not skip this step** — different projects have different attributes; never assume a project has "Status" or "Approved" as values; check first.

3. **Ask the user what they actually want.** Quick interview — pick whichever questions are relevant; skip the rest:
   > *"That module has [N] requirements. Want to filter? Common options for this project:*
   > - *By status (e.g. Approved-only) — values available: [list from step 2]*
   > - *By artifact type — values: [System Requirement, Heading, etc.]*
   > - *By priority / severity / owner / any custom attribute*
   > - *By keyword in the title or description*
   > - *Or just give me everything — say 'all'."*

4. **Call `get_module_requirements`** with the resulting `filter` dict. Examples:
   - All approved system requirements: `filter={"Status": "Approved", "artifact_type": "System Requirement"}`
   - High-priority anything: `filter={"Priority": "High"}`
   - Anything mentioning "security": `filter={"title_contains": "security"}`
   - Multiple statuses: `filter={"Status": ["Approved", "Reviewed"]}`
   - Everything: omit `filter` entirely or pass `{}`.

5. **Show the user a clean summary** — count + a sample table of titles + URLs. Don't dump all the body content unless they ask.

6. Ask: *"Want to save these to a file (JSON / CSV / Markdown), generate downstream artifacts (tasks / tests), or work on something else?"*
   - If save → `save_requirements`
   - If tasks → Step 3d (using these URLs as `requirement_url`)
   - If tests → Step 3e
   - If develop based on these → these URLs are now your context. Each requirement has the full link history (parent reqs, downstream tasks/tests/defects); use them to build implementations with full traceability.

**Why the filter matters:** if the user says "I want to develop the implementation based on the approved requirements," you absolutely should NOT then call `get_module_requirements` with no filter and pull every draft / proposed / rejected req. Filter to `{"Status": "Approved"}` (or whatever the project's "approved" state is called) and only feed those to downstream tools.

### Step 3b: GENERATE REQUIREMENTS Path

The flow is **interview → generate → preview-with-structure → confirm → push**. Critically: generate first, THEN propose the module structure with the requirements visible. Don't pre-commit to a single module name before you know what you're generating — sometimes the right answer is to split the result into 2-3 modules grouped by theme.

**Phase 1: Light interview about WHAT (not WHERE) — one question at a time**

Wait for each answer before asking the next. **Do NOT call any create tool yet.** This rule is repeated in every write tool's description because it's the most-violated rule.

1. > "What system or feature are these requirements for? Give me a brief description."

2. > "What type of requirements are we writing? Stakeholder, system-level, software, hardware, security, performance, safety, etc.?"

3. > "Are there applicable standards or compliance frameworks? DO-178C, ISO 26262, IEC 62304, NIST 800-53, MIL-STD-882, or industry-specific?"

4. > "How many requirements are you looking for? A handful (5-10), moderate (15-25), or comprehensive (30+)?"

5. > "Anything specific that must be included? Any constraints, interfaces, environmental conditions, or existing requirements I should be aware of?"

6. > "Should these link upstream to existing artifacts (e.g. derive from / satisfy a parent requirement)? If yes, paste the URL of the parent or tell me the link type."

(Notice: NO "where to put them" question yet — that comes after generation.)

**Phase 2: Generate the requirements internally**

Generate them silently — do NOT show the user yet. Just have the list ready in memory. Then think about structure:

- Are these requirements all about ONE topic? → one module is right.
- Do they naturally split into themes (e.g. Authentication / Authorization / Encryption when the user asked for "security")? → propose multiple modules with grouped reqs.
- Do they decompose into hierarchies (Business → Stakeholder → System)? → that's Step 3g (Tiered) — different flow.

**Phase 3: Preview with the proposed structure — STOP here, do not write anything yet**

Show the user EVERYTHING in one shot: the requirements, AND the module structure that will house them, AND the rationale for the grouping. Format:

> Here are the **[N] requirements** I'd create in **[project name]**, organized into **[K] module(s)**:
>
> ## Module 1: **[Module name]** ([n₁] requirements)
> *Rationale for this grouping: [one line — why these belong together]*
>
> | # | Type | Title (the "shall" statement) | Rationale |
> |---|------|-------------------------------|-----------|
> | 1 | Heading | [Section heading] | Section grouping. |
> | 2 | System Requirement | The system shall ... | [why this is needed] |
> | ... | ... | ... | ... |
>
> ## Module 2: **[Module name]** ([n₂] requirements)
> *Rationale: ...*
>
> | # | Type | Title | Rationale |
> | ... | ... | ... | ... |
>
> **Now decide:**
> 1. **Approve as proposed** — reply "yes" / "go ahead" / "push them".
> 2. **Restructure** — tell me what to change: rename a module, move req X from module A to module B, merge two modules, split one module, drop a req, add a req.
> 3. **Or pick from these alternative placements:**
>    - **Reuse an existing module** — I'll list the project's modules, you pick one (and the existing module's name overrides the proposed one).
>    - **Folder only, no module** — for ad-hoc requirements that don't need a navigable doc.
>
> Note: I haven't written anything to ELM yet. Test cases (with verification steps & pass/fail criteria) come in a separate step linked to each requirement; they're NOT inside the requirement bodies.

**Phase 4: Apply user feedback, re-preview if needed, then push**

If the user says "restructure" or names changes:
- Apply the changes to your in-memory list (move reqs, rename modules, drop/add).
- **Re-show the updated preview.** Do NOT call any create tool yet.
- Repeat until the user gives explicit approval.

If the user picks "existing module":
- Call `get_modules(project_identifier)` → present numbered list → user picks → use that module's title as `module_name`. The find-or-create logic in `create_requirements` reuses existing modules cleanly.

Once the user explicitly approves ("yes", "ship it", "push them"):
- For each module group, call `create_requirements` with the project_identifier, module_name (or omit for folder-only), folder_name (defaulting to module name), and the requirements array.
- If multiple modules, call create_requirements once per module — they're independent operations.

**Phase 5 (was Phase 3): Confirm delivery + offer the natural next steps**

After all `create_requirements` calls succeed, tell the user:
> "Done — created [total N] requirements across [K] module(s) in [project name]:
> - [Module 1 name](module-1-direct-url): [n₁] requirements
> - [Module 2 name](module-2-direct-url): [n₂] requirements
>
> Each requirement is a clean 'shall' statement; verification details aren't in them yet.
>
> Want me to:
> 1. **Generate EWM Tasks** — one implementation Task per requirement, linked back via `oslc_cm:implementsRequirement` (Phase 2 of the lifecycle)?
> 2. **Generate ETM Test Cases** — one Test Case per requirement, linked via `oslc_qm:validatesRequirement`, with the test steps and pass/fail criteria that go with each requirement (Phase 3 of the lifecycle)?
> 3. **Both?**
> 4. **Skip for now**.
>
> Pick a number — and if you want tasks/tests, I'll do another short interview before generating, same as we just did for requirements."

Render every URL as a clickable markdown link so the user can jump straight into DNG. Never substitute the generic `/rm` landing page.

**Phase 6 (was: rules): Generate the proper requirements engineering style**

When generating requirements, follow these rules from IEEE 29148 and INCOSE best practices:

**Each requirement = ONE "shall" statement. Period.** Acceptance criteria, test steps, pass/fail conditions, and verification methods do NOT belong in the requirement body — those live in the **ETM test cases** (Phase 3 of the lifecycle, generated separately). Mixing them poisons the requirement: you can't independently version the test, you can't link multiple tests to one requirement, and downstream tooling that expects the requirement body to be a clean shall-statement will misbehave.

**Structure:**
- Each requirement MUST use "shall" for mandatory behavior ("The system shall...")
- Each requirement MUST be atomic — one testable behavior per requirement
- Each requirement MUST be verifiable — meaning it CAN be tested, with measurable language (numeric thresholds, time limits, conditions). The test ITSELF lives in ETM.
- Each requirement body should be one to three sentences. Use a `Rationale:` line for the *why* if needed (compliance reference, design driver). NEVER include `Acceptance Criteria:`, `Test Steps:`, `Pass/Fail:`, or `How to verify:` sections.
- Group requirements under Heading artifacts by functional area (e.g., "Power Management", "Communications", "Safety")

**Quality checks — before presenting, verify each requirement is:**
- **Unambiguous** — only one possible interpretation (avoid "fast", "reliable", "user-friendly" without a metric)
- **Traceable** — can link to a parent/source requirement or stakeholder need
- **Feasible** — technically achievable (flag any that need engineering validation)
- **Complete** — covers normal operation, error/failure modes, and boundary conditions
- **Consistent** — no conflicts between requirements

**If a standard was specified**, include compliance references in the body's Rationale (e.g., "Rationale: per MIL-STD-882E Section 4.3" or "Rationale: in accordance with DO-178C DAL-A").

**Steps:**
1. Call `get_artifact_types` with `project_identifier` to discover what artifact types are available for this project. If the user wants links, also call `get_link_types` with `project_identifier`.
2. Generate the requirements following the rules above. Use artifact type names from the `get_artifact_types` output — do NOT guess type names.
3. **Build the folder name** as a short, descriptive label of what's inside (2–6 words). The folder name will also become the module name when one's created. Examples: `Security Requirements`, `Power Management`, `Apollo Spec V1`. Don't add author tags or auto-generated prefixes — keep it readable and human.
4. **Present them in a clean, readable table — and STOP. Do not call `create_requirements` yet.** Use this format:

   > Here are the **X requirements** I'd create in [project name]:
   >
   > **Module/Folder:** Power Management
   >
   > | # | Type | Title (the "shall" statement) | Rationale |
   > |---|------|-------------------------------|-----------|
   > | 1 | Heading | Power Management | Section heading. |
   > | 2 | System Requirement | The system shall maintain operation during primary power loss for a minimum of 4 hours on backup power. | Mission continuity per MIL-STD-882E §4.3. |
   > | 3 | System Requirement | The system shall alert the operator within 1 second when backup power drops below 20% capacity. | Operator awareness for graceful shutdown. |
   > | ... | ... | ... | ... |
   >
   > **Want me to push these to DNG?** (Reply: "yes" / "go ahead" / "push them" — or tell me what to change.)
   >
   > Note: I haven't written test cases yet — those will hold the actual verification steps and pass/fail criteria, and I'll generate them in a separate step linked to each requirement.

5. **Wait for explicit confirmation.** "Sure" or "ok" with context counts. "Yes" alone is enough. If the user asks for changes, revise and show the updated table again — do not call the tool yet.
6. Only after explicit confirmation → call `create_requirements` with `project_identifier`, `module_name` (use the same name from step 3 — auto-binds requirements to the module), and the `requirements` array (each item: `title` = the shall statement, `content` = body with optional `Rationale:` line, `artifact_type` from `get_artifact_types`, optional `link_type` + `link_to` together).

**Phase 3: Confirm delivery + offer the natural next steps**

After `create_requirements` succeeds, tell the user:
> "Done — I created [N] requirements in the '[Module Name]' module in [project name]. Each requirement is a clean 'shall' statement; verification details aren't in them yet.
>
> Want me to:
> 1. **Generate EWM Tasks** — one implementation Task per requirement, linked back via `oslc_cm:implementsRequirement` (Phase 2 of the lifecycle)?
> 2. **Generate ETM Test Cases** — one Test Case per requirement, linked via `oslc_qm:validatesRequirement`, with the test steps and pass/fail criteria that go with each requirement (Phase 3 of the lifecycle)?
> 3. **Both?**
> 4. **Skip for now** and stop here.
>
> Pick a number — and if you want tasks/tests, I'll do another short interview before generating, same as we just did for requirements."

Then proceed based on their answer using Step 3d (tasks) and/or Step 3e (test cases). Each phase has its own interview-preview-confirm cycle — never skip them.

Note: titles and content are stored verbatim. Do not add author/source markers like "[AI Generated]" — keep titles human-readable.

### Step 3c: PDF IMPORT / RE-IMPORT Path
When the user provides a PDF to import into DNG (or re-import an updated version):

**First Import (PDF → DNG):**

1. Call `extract_pdf` with the `file_path` the user provides — this returns clean structured text from the PDF. Do NOT try to read the PDF yourself; always use this tool.
2. Parse the extracted text into structured requirements — identify logical sections, headings, and individual requirements
3. Call `get_artifact_types` with `project_identifier` to get valid type names
4. **Present in a preview table** — show each parsed requirement with title, type, and content
5. **Get explicit approval** before creating anything
6. Call `create_requirements` with `project_identifier`, `folder_name` (format: `AI Generated - [username] - [PDF summary]`), and the `requirements` array
7. **Save the mapping** of requirement titles to their DNG URLs (shown in `create_requirements` output) — you'll need these for re-import

**After First Import — Create Baseline:**

After the initial import is complete and reviewed, offer to create a baseline:
> "Would you like me to create a baseline of the current state before any future changes?"

If yes → call `create_baseline` with `project_identifier` and `title` (e.g., "Apollo Spec V1 Import").
This freezes the current state so you can compare against it later.

**Re-Import (Updated PDF → update only changes):**

**Before ANY modifications, you MUST:**
1. Ask the user: "I'll need to modify existing requirements. Before I do, let me create a baseline so we can roll back if needed. OK?"
2. Wait for approval → call `create_baseline` with `project_identifier` and `title` (e.g., "Pre-V2 Import Baseline")
3. Confirm the baseline was created before proceeding

**Then proceed with the diff:**

1. Call `extract_pdf` with the new PDF's `file_path` — do NOT try to read the PDF yourself
2. Read the existing requirements from the DNG module using `get_module_requirements` with `project_identifier` and `module_identifier` — **note each requirement's URL from the output**
3. **AI diff** — match requirements between the PDF and DNG by:
   - **Section title / heading** (primary match key — e.g., "Weight Constraints" matches "Weight Constraints")
   - **Section number** (secondary — e.g., section 2 in both documents)
   - If a requirement exists in the new PDF but has no match in DNG → it's **new**
   - If a matched requirement has different content → it's **changed**
   - If a matched requirement has identical content → it's **unchanged**
4. Identify: **changed** requirements, **new** requirements, **unchanged** requirements
5. **Present a diff table:**

   > Here's what changed between the versions:
   >
   > | # | Requirement | Change | Old Value | New Value |
   > |---|-----------|--------|-----------|-----------|
   > | 1 | Weight Constraints | Modified | 96,600 lbs | 100,600 lbs |
   > | 2 | Safety Margin | Modified | 10% | 15% |
   > | 3 | Internet Capability | **New** | — | LEM must transmit to satellites... |
   > | 4-12 | (remaining) | Unchanged | — | — |
   >
   > **Want me to update the 2 changed requirements and create the 1 new one? (3 unchanged will be skipped)**

6. Only after explicit approval:
   - Call `update_requirement` for each changed requirement — pass the `requirement_url` (from `get_module_requirements` output) plus the new `title` and/or `content`
   - Call `create_requirements` for any new requirements
   - Skip unchanged requirements entirely
7. After updates, offer to create a new baseline:
   > "Updates complete. Want me to create a baseline of this new state (e.g., 'Apollo Spec V2')?"

**Baseline Comparison:**

When the user asks to compare baselines or see what changed:

1. Call `list_baselines` with `project_identifier` to show available baselines with their URLs
2. User picks a baseline → call `compare_baselines` with `project_identifier`, `module_identifier`, and the `baseline_url`
3. The tool reads requirements from both the baseline and current stream, then returns a structured diff showing: **modified**, **added**, **removed**, and **unchanged** requirements
4. Present the results to the user

### Step 3d: CREATE TASKS Path (EWM)

Same flow as Step 3b: **interview → generate-internally → preview-with-structure → confirm → push.** Don't call any create_task until the user explicitly approves the preview.

**Phase 1: Light interview (one question at a time)**

1. **Source requirements** — If the user hasn't already read or generated them, guide through Step 3a (read) or Step 3b (generate) first. You need the requirement URLs in hand before you can link tasks back to them.

2. **Status check** — Inspect the `status` / `custom_attributes` of each source requirement. If ANY are NOT Approved, warn:
   > "Heads up — X of these [N] requirements aren't Approved yet (status: [Draft/Proposed/etc.]). Tasks generated from unapproved reqs may need to change later. Proceed anyway, or wait?"
   Only proceed on explicit "proceed."

3. **Project + iteration** — *"Which EWM project? Any specific iteration / sprint to plan these into, or leave unscheduled for the project lead?"* If the user doesn't know the EWM project, call `list_projects(domain="ewm")`.

4. **Task granularity** — *"One task per requirement, or do you want me to break some requirements into multiple smaller tasks (UI work + back-end work + testing-prep, for example)? Default: one-to-one."*

**Phase 2: Generate the tasks internally**

Generate them silently. For each task:
- **Title**: verb-first action (`Implement ...`, `Design ...`, `Configure ...`, `Refactor ...`). Concise — under 80 chars.
- **Description**: brief — Objective (1 line: what this accomplishes) + Deliverables (bullet list of concrete outputs) + Dependencies (other tasks / external blockers, if any). **Don't copy the requirement's body in here** — it's already linked via `requirement_url`. Anyone reading the task in EWM can click through to the source.
- **`requirement_url`**: set to the source requirement's URL (verbatim — see Phase 3 critical-rule below).

Think about grouping:
- All tasks one-to-one with reqs? Standard case.
- Some reqs need breaking down? Show the breakdown in the preview so the user can sanity-check.
- Cross-cutting work (shared logging, shared error-handling)? Propose a separate "Foundation" group of tasks not linked to a single req — surface that explicitly in the preview.

**Phase 3: Preview with structure — STOP here**

Show everything in one shot before any tool call:

> Here are the **[N] tasks** I'd create in EWM project **[project name]**:
>
> *(Optional grouping if not 1-to-1 with reqs)*
> ## Group 1: Implementation tasks ([n₁] tasks — one per requirement)
>
> | # | Task Title | Source Requirement | Dependencies |
> |---|------------|-------------------|--------------|
> | 1 | Implement battery backup activation logic | [REQ-001: Power Management](https://server/rm/resources/TX_xxx) | none |
> | 2 | Build operator alert UI for low-battery state | [REQ-002: Low-battery Alert](https://server/rm/resources/TX_yyy) | task #1 |
> | ... | ... | ... | ... |
>
> ## Group 2: Cross-cutting (optional — only if needed)
>
> | # | Task Title | Source | Notes |
> | ... | ... | ... | ... |
>
> **Now decide:**
> 1. **Approve as proposed** — reply "yes" / "go ahead" / "ship them".
> 2. **Restructure** — tell me what to change: rename, drop a task, add a task, change dependencies, regroup, change which req a task links to.
>
> Note: I'm linking each task to its source requirement via `oslc_cm:implementsRequirement` — that's what makes traceability work. I'm not copying the requirement text into each task body.

**Phase 4: Push, verify links, summarize**

Once explicitly approved:

1. Call `create_task` for each task with `ewm_project`, `title`, `description`, **AND `requirement_url`** (verbatim — copy from the source requirement's `url` field). One task per call. **CRITICAL — never skip `requirement_url`.** Without it the task is created but unlinked.

2. After all tasks are created, verify linking on at least one task: re-fetch its URL and check for `oslc_cm:implementsRequirement` (or the reified `rdf:object` form). If any task came back unlinked, fix it: `create_link` with `link_type_uri="http://open-services.net/ns/cm#implementsRequirement"`, `source_url=<task URL>`, `target_url=<requirement URL>`.

3. Summarize using direct markdown links:
   > "Done — created [N] tasks in EWM project [project name]:
   > - [Implement battery backup activation logic](task-direct-url) → linked to [REQ-001](req-url)
   > - [Build operator alert UI ...](task-direct-url) → linked to [REQ-002](req-url)
   > - ...
   >
   > Want me to:
   > 1. **Generate the matching ETM Test Cases** for the same requirements?
   > 2. **Transition any of these to 'In Progress'** as you start work?
   > 3. **Skip for now**."

### Step 3e: CREATE TEST CASES Path (ETM)

Same shape as Step 3d: **interview → generate-internally → preview-with-structure → confirm → push.** Test cases are the right place for acceptance criteria, test steps, and pass/fail conditions — that's what makes them ETM artifacts vs DNG requirements.

**Phase 1: Light interview**

1. **Source requirements** — Same as Step 3d. Need URLs in hand.

2. **Status check** — Same warning if any are not Approved.

3. **Project** — Which ETM project? If unknown, `list_projects(domain="etm")`.

4. **Test depth** — *"For each requirement, do you want:*
   > *- A single high-level test case (one verification per req — fastest)?*
   > *- Multiple test cases per requirement (happy path + edge cases + error paths)?*
   > *- High-level test cases now, with detailed Test Scripts attached separately for each (richer; takes longer but more rigorous)?"*

5. **Test types** — *"Mostly functional tests, or also performance / security / accessibility / regression?"*

**Phase 2: Generate internally**

For each test case:
- **Title**: verification-oriented (`Verify ...`, `Validate ...`, `Confirm ...`). Concise.
- **Description**: structured test procedure with these sections (these DO belong in test cases — that's their purpose):
  - **Preconditions**: required system state, test data, environment.
  - **Test Steps**: numbered, specific, reproducible. Each step has the action and the expected result.
  - **Pass/Fail Criteria**: explicit, measurable conditions.
- **`requirement_url`**: source requirement URL.

If user picked "high-level + scripts": generate both. The script holds the detailed numbered procedure; the test case is the "what to verify" header that the script executes via `oslc_qm:executesTestScript`.

**Phase 3: Preview with structure — STOP here**

> Here are the **[N] test cases** I'd create in ETM project **[project name]** (validating [M] requirements):
>
> | # | Test Case Title | Validates Requirement | Pass/Fail (1-line summary) |
> |---|----------------|----------------------|----------------------------|
> | 1 | Verify backup activates within 5s | [REQ-001](req-url) | PASS: active ≤5s, FAIL: >5s |
> | 2 | Verify low-battery alert at 20% | [REQ-002](req-url) | PASS: alert + log timestamped, FAIL: no alert |
> | ... | ... | ... | ... |
>
> **Test Scripts** (only shown if user asked for them):
>
> | # | Test Script Title | Drives Test Case | # Steps |
> | ... | ... | ... | ... |
>
> **Now decide:**
> 1. **Approve as proposed** — reply "yes" / "go ahead" / "ship them".
> 2. **Restructure** — tell me what to change: drop tests, add tests, split one test into multiple, change preconditions, change pass/fail wording.

**Phase 4: Push, verify links, summarize**

1. Call `create_test_case` for each — pass `etm_project`, `title`, `description`, **AND `requirement_url`** verbatim. Same rule as tasks: never skip `requirement_url`.

2. If user wanted scripts: for each test case URL just returned, call `create_test_script` with `etm_project`, `title`, `steps`, `test_case_url`.

3. Verify linking: re-fetch one test case, confirm `oslc_qm:validatesRequirement` points at the source. If missing, fix with `create_link` (`link_type_uri="http://open-services.net/ns/qm#validatesRequirement"`).

4. Summarize with direct links:
   > "Done — created [N] test cases (and [M] scripts, if applicable) in [project name]:
   > - [Verify backup activates within 5s](test-case-url) ← validates [REQ-001](req-url)
   > - ...
   >
   > Want me to:
   > 1. **Run any of these now** — pass them and record a Test Result?
   > 2. **Block any of them** as Not-Yet-Implemented (record Test Result status='blocked')?
   > 3. **Skip for now**."

If user picks 1 → call `create_test_result(test_case_url, status='passed')`.
If user picks 2 → call `create_test_result(test_case_url, status='blocked')`.

**Defects:** if a user comes back later and says a test failed, run a separate quick interview ("describe what failed, expected vs actual, severity?") then call `create_defect` linked to the requirement. The flow is the same: interview → preview → confirm → push.

### Step 3f: FULL LIFECYCLE Path
When the user wants the full lifecycle (Requirements → Tasks → Test Cases):

1. **Phase 1:** Follow Step 3b (Generate Requirements) — create requirements in DNG. **Save the requirement URLs from the `create_requirements` output.**
2. **Phase 2:** Follow Step 3d (Create Tasks) — use the requirement URLs from Phase 1 (do NOT go back to Step 3a to read them; you already have the URLs from `create_requirements` output)
3. **Phase 3:** Follow Step 3e (Create Test Cases) — use the same requirement URLs from Phase 1
4. At each phase boundary, confirm with the user before proceeding to the next phase

Tell the user at completion:
> "Full lifecycle complete! Here's what was created:
> - X requirements in DNG (folder: '[folder name]')
> - X tasks in EWM (linked to requirements)
> - X test cases in ETM (validating requirements)
>
> Everything is cross-linked for full traceability. Review in ELM and approve at each stage."

### Step 3g: TIERED DECOMPOSITION Path (Business → Stakeholder → System)

When the user asks for tiered / hierarchical / decomposed requirements (e.g. "start with business requirements, derive stakeholder, then system" — or any 2-or-more tier breakdown), use this flow. This is the standard INCOSE / IEEE 29148 hierarchy.

**Phase 0: Confirm structure (no tools called yet)**

Tell the user:

> "Got it — you want tiered requirements with traceability between layers. Standard structure is:
>
> | Tier | Module | What it says | Links down to |
> |---|---|---|---|
> | 1 | Business Requirements | Strategic goals, outcomes the org needs | (root tier, no parent) |
> | 2 | Stakeholder Requirements | What each stakeholder needs the system to do | each StR → 1+ BR via 'Satisfies' |
> | 3 | System Requirements | Concrete 'shall' statements the system implements | each SR → 1+ StR via 'Satisfies' |
>
> Confirm this, or tell me what to change — different tier names, different link types, fewer/more tiers, different module-naming convention, etc."

Wait for explicit confirmation. **Don't proceed until structure is locked.**

**Phase 1: Generate Tier 1 — Business Requirements**

Run the full Generation Discipline (interview → preview → confirm → create) but scoped to business requirements:

- Interview questions tuned for this tier:
  - *"What's the business goal or strategic driver behind this initiative?"*
  - *"What measurable outcomes does the organization need (revenue, compliance, user adoption, cost reduction, etc.)?"*
  - *"What's the timeframe or deadline?"*
  - *"How many business requirements feel right — usually 3–10 at this level."*
- BR style: high-level, often without "shall" — descriptive language is fine ("The organization needs to reduce production line downtime by 20% over 12 months"). Each BR is a strategic statement, not a system spec.
- Preview as a clean table → wait for confirmation → call `create_requirements` with `module_name: "Business Requirements"`.
- **Save the returned URLs** — Phase 2 needs them for the Satisfies links.

**Phase 2: Generate Tier 2 — Stakeholder Requirements**

Tell the user:
> "Tier 1 created — [N] BRs in the 'Business Requirements' module. Now Tier 2: stakeholder requirements derived from those BRs."

Interview:
- *"Who are the key stakeholders for this system? (operators, end users, maintainers, regulators, business owners, etc.)"*
- *"For each stakeholder, what do they need the system to provide?"*
- *"Should every StR trace to at least one BR? (Recommended — say no only if you have a reason.)"*

Generate the stakeholder requirements. For each StR, identify 1 or more parent BRs (use the URLs from Phase 1). The preview table now has a "Satisfies" column:

> | # | Type | Title | Satisfies (BR) | Rationale |
> |---|------|-------|----------------|-----------|
> | 1 | Stakeholder Requirement | The Operator shall be able to monitor production status in real time | BR-2 (Reduce downtime) | Operator awareness of issues. |
> | 2 | Stakeholder Requirement | The Maintenance Engineer shall be able to schedule preventive maintenance from the system | BR-3 (Maintenance efficiency) | Reduces unplanned outages. |

Confirm → call `create_requirements` with `module_name: "Stakeholder Requirements"`. Each requirement gets `link_type: "Satisfies"` and `link_to: <URL of the parent BR>`. Save the StR URLs for Phase 3.

**Phase 3: Generate Tier 3 — System Requirements**

Tell the user:
> "Tier 2 created — [N] StRs linked back to Tier 1. Now Tier 3: system requirements that implement the stakeholder needs."

Interview:
- *"For each stakeholder requirement, what specific system behaviors / capabilities are needed to implement it?"*
- *"Are there standards/regulations the SYSTEM tier needs to comply with (DO-178C, ISO 26262, IEC 62304, etc.)?"*
- *"Any technical constraints — performance budgets, hardware platforms, interface protocols?"*

Generate the system requirements. Each SR is a clean "shall" statement (this is where the strict IEEE-29148 form applies — no acceptance criteria in body). For each SR, identify 1+ parent StRs.

Preview table with a "Satisfies" column pointing at StRs. Confirm → call `create_requirements` with `module_name: "System Requirements"`. Each requirement gets `link_type: "Satisfies"` and `link_to: <URL of parent StR>`.

**Phase 4: Confirm + offer downstream**

After all three tiers are created, show a summary that includes the **direct clickable URL for each module** (you have these from each `create_requirements` response — they're in the `Module:` line). Use markdown link syntax `[Title](url)` so the user can click straight through. **Never** substitute a generic `https://server/rm` landing page link — that's useless to the user.

> "All three tiers created with full traceability:
>
> | Tier | Module (click to open) | Count | Linked to |
> |---|---|---|---|
> | Business | [Business Requirements](https://server/rm/resources/MD_xxx) | [N] | (top tier) |
> | Stakeholder | [Stakeholder Requirements](https://server/rm/resources/MD_yyy) | [N] | each StR → 1+ BR via Satisfies |
> | System | [System Requirements](https://server/rm/resources/MD_zzz) | [N] | each SR → 1+ StR via Satisfies |
>
> Click any module above to open it directly in DNG. The 'Satisfies' link on any individual requirement takes you up to its parent.
>
> Do you want me to:
> 1. **Generate EWM Tasks** for each System Requirement (Phase 4 — implementation)?
> 2. **Generate ETM Test Cases** for each System Requirement (Phase 5 — verification)?
> 3. **Both?**
> 4. **Skip for now.**
>
> Tasks and tests typically link to System Requirements, not Business or Stakeholder — but tell me if you want a different policy."

If the user picks 1/2/3, run Step 3d / 3e against the System Requirements URLs from Phase 3.

**Important rules for the tiered flow:**
- Always confirm the tier structure in Phase 0 before generating anything
- Always show parent-link traceability in the preview tables
- If the user rejects or modifies a tier, regenerate before moving to the next
- If the user wants only 2 tiers (e.g. Business → System, skipping Stakeholder), drop Phase 2 and link System directly to Business
- Use `get_link_types(project_identifier)` first to see what link names this project uses — "Satisfies" is the most common but some projects use "Derived From", "Implements", or custom names

### Step 3h: BUILD-PROJECT Path (end-to-end agentic dev with ELM as source of truth)

When the user says **"build a project"**, **"do an end-to-end build"**, **"agentic development"**, or invokes the `/build-project` prompt — run this 9-phase sequence. This is the headline demo: a one-line idea becomes fully-traced requirements + tasks + test cases in ELM, then the user reviews them in ELM, then the AI writes the actual code based on the finalized state.

**How the gate is enforced — call the `build_project_next` tool between phases.**

Don't run the phases from memory. The flow is server-driven via two tools:

1. **`build_project(project_idea=<one-line idea>)`** — kicks the flow off. Returns Phase 0 + 1 instructions and tells you to call `build_project_next` after every phase.
2. **`build_project_next(current_phase=<N>, user_signal=<verbatim user reply>)`** — the gate. After you finish Phase N, call this tool with the user's verbatim reply. The server validates the reply against an approval-words list and a rejection-words list. **It only returns Phase N+1's instructions if the user explicitly approved.** If `user_signal` is empty, vague, or non-approval, the tool refuses and tells you to wait for explicit approval — it doesn't auto-advance after a timeout, ever.

This means: if you call `build_project_next(current_phase=2, user_signal="")`, you get back a refusal — not Phase 3. The gate is the only way forward.

**Critical invariants for this path:**
- Every phase has a user-approval gate enforced by `build_project_next`. Don't skip gates and don't simulate them.
- After Phase 4, **STOP for user review in ELM**. Do NOT write code yet.
- Phase 6 RE-PULLS state from ELM — code is built from current ELM state, not what was generated.
- ELM is the system of record. Code references requirement IDs back to ELM.

#### PHASE 0 — Verify connection + project access
Call `connect_to_elm` if not connected. Confirm the DNG / EWM / ETM project names with the user (offer `list_projects` per domain if they don't know). All three projects can be the same family (e.g. "ELM AI Hub - Bretts Sandbox (Requirements)" + "(Change Management)" + "(Quality Management)").

#### PHASE 1 — Project intake (interview, no tools)
Ask 4–6 short questions. One at a time:
1. *"One-paragraph description — what does the user actually do with this thing?"*
2. *"Tech stack / platform — web app, API service, embedded, mobile, etc.?"*
3. *"Standards / compliance — DO-178C, ISO 26262, NIST 800-53, none?"*
4. *"Approximate scale — handful (5–10 reqs), moderate (15–25), comprehensive (30+)?"*
5. *"Integrations or external interfaces?"*
6. *"Any specific must-haves or must-not-haves?"*

Confirm a one-line scope back to the user. Get a "yes that's right" before moving on.

#### PHASE 2 — Requirements (DNG)
Run **Step 3b** (single-tier — one System Requirements module) OR **Step 3g** (tiered — Business → Stakeholder → System) depending on the project's complexity and what the user picked. Generate internally → preview-with-structure → user-approval → push with `module_name` set so requirements auto-bind. Surface module URL + every requirement URL as markdown links.

(Server-side validation rejects requirements with embedded acceptance criteria / business value / stakeholder needs — those go in test cases or a higher tier respectively. Don't fight it; emit clean shall-statements.)

#### PHASE 3 — Implementation tasks (EWM)
Run **Step 3d**. One EWM task per System Requirement (the most-derived tier — not Business / Stakeholder reqs at the top tiers). Brief task body — Objective + Deliverables + Dependencies. Don't copy the requirement text; link via `requirement_url`. Preview → user-approval → push.

#### PHASE 4 — Test cases (ETM)
Run **Step 3e**. One Test Case per System Requirement, with full Preconditions / Test Steps / Pass-Fail Criteria (these DO belong in test cases). Optionally also `create_test_script` for detailed procedure steps. Preview → user-approval → push linked to source reqs.

#### PHASE 5 — STOP for user review in ELM
This is the biggest gate. **Tell the user explicitly:**

> *"Phase 2–4 complete. Open ELM in your browser and review what's there:*
> *- DNG modules: [Business Requirements](url1), [System Requirements](url2)*
> *- EWM tasks: [list of task links]*
> *- ETM test cases: [list of test-case links]*
>
> *In ELM you can: approve / reject / modify any requirement, mark statuses (only Approved requirements will drive the code), reassign or reprioritize tasks, rewrite test cases, add new ones, drop ones that don't fit.*
>
> *When you're done, come back here and say **'continue'** or **'build it'** or **'pull latest'**. I'll re-fetch the current state from ELM and start writing the actual application code based on the finalized artifacts.*
>
> **I'm waiting for your signal — not generating code yet.**"

Then **wait silently**. Don't poll, don't generate, don't move on. The user may take 5 minutes or 5 days; that's fine.

#### PHASE 6 — Re-pull current state from ELM
When the user says "continue" / "build it" / "pull latest":
1. Re-fetch the System Requirements module via `get_module_requirements` with `filter={"Status": "Approved"}` (use `get_attribute_definitions` first to discover what the project's "approved" status value is — never guess).
2. Re-fetch all EWM tasks via `query_work_items` with `oslc.where=oslc_cm:closed=false` (or filter to current iteration if the user planned them).
3. Re-fetch all linked test cases via `query_work_items` against the ETM project, or by following the `oslc_qm:validatesRequirement` backlinks.
4. Show the user a current-state summary:

> *"Here's what I see in ELM now:*
> *- {N} approved requirements (was {M} originally — {M-N} were rejected, dropped, or still in review)*
> *- {K} active tasks (was {L} — {L-K} were closed, moved, or reassigned)*
> *- {J} test cases ({J-J'} updated since I created them)*
>
> *Building based on this current state. Confirm and I'll start writing code."*

Wait for confirmation. **Even now, don't skip the gate.**

#### PHASE 7 — Write the code
Once Phase 6 is confirmed, write the actual application code in the user's IDE (this is what the AI host's editing capabilities are for). Rules:

- **Each file has a header comment listing the requirement IDs it implements.** Example:
  ```
  # Implements: REQ-005 (password validation), REQ-007 (real-time feedback)
  # Source: https://server/rm/resources/TX_xxx, https://server/rm/resources/TX_yyy
  ```
- Code structure should mirror requirement structure where reasonable (one module/class/function per req or req-group).
- Tests in the codebase should reference test case URLs from ETM (not duplicate the test logic).

#### PHASE 8 — Track work + record results in ELM as you build
**ELM stays the source of truth throughout coding, not just at design time.**

- As you start a task: `transition_work_item(workitem_url, "In Development")`.
- When a task is complete: `transition_work_item(workitem_url, "Resolved")`.
- For each test case once the implementation is in place:
  - If the code makes it pass → `create_test_result(test_case_url, status="passed")`.
  - If the code can't satisfy it → `create_test_result(test_case_url, status="failed")` AND quick-interview the user about the failure, then `create_defect` linked to the requirement + test case URLs.

#### PHASE 9 — Final summary
Give the user a complete picture:

> *"Build complete. End state:*
> *- DNG: [Module name](url) — N reqs ({M} Approved, {K} Rejected)*
> *- EWM: {N} tasks total — {M} Resolved, {K} still In Progress, {J} blocked*
> *- ETM: {N} tests — {M} passed ✅, {K} failed ❌, {J} blocked*
> *- Defects: [open defect list](query-url) — {N} open, all linked back to the requirements they affect*
> *- Code: {F} files written, every file has 'Implements REQ-…' headers tying it back to ELM*
>
> *The complete trace is in ELM: requirement → task → test → result → defect-if-any. Click any link above to inspect."*

#### Anti-patterns to avoid in build-project
- ❌ Skipping the Phase 5 review pause and barreling into code generation
- ❌ Writing code based on the in-memory artifacts from Phases 2–4 instead of the re-pulled state in Phase 6
- ❌ Forgetting to filter for `Status=Approved` in Phase 6 — drives the wrong code
- ❌ Forgetting to transition tasks during Phase 7/8 — leaves ELM out of sync with what's actually built
- ❌ Hiding URLs behind a generic `/rm` link — every artifact gets a markdown-link surface
- ❌ Calling `build_project_next` with `user_signal=""` or paraphrased / inferred / "I think they meant yes" signals — pass the user's verbatim reply or the gate refuses

### Step 3j: IMPORT REQUIREMENTS Path (brownfield — paste-to-DNG)

Triggered when the user already has requirements written somewhere else (Jira epic, Notion doc, Word file, copied bullets, markdown spec, a wiki page, anything textual) and wants them in DNG. **You do NOT regenerate the user's content** — you preserve their wording, you just structure it.

This path is invoked by:
- The `/import-requirements` prompt explicitly
- Trigger phrases: *"I have requirements already"*, *"we wrote them in Jira"*, *"import these"*, *"here are our reqs, put them in DNG"*
- The user pastes a clearly-requirement-shaped chunk of text without a generation request
- `/build-project` Phase 1 — when user picks path (b) "I have existing reqs"

#### What you do

1. **If the user hasn't pasted yet, prompt them:** *"Paste your requirements — Jira epic body, Notion doc, Word content, plain bullets, anything textual. I'll parse and structure it for DNG."*

2. **Parse the pasted text into FIVE buckets** (the prompt body has full details):
   - **Functional reqs** — atomic 'shall' statements about what the system does
   - **Non-functional reqs** — performance, security, retention, observability, etc.
   - **Acceptance criteria** — HOLD for ETM later; do NOT push to DNG
   - **Constraints / Risks / Assumptions** — ask once if user wants them; default skip
   - **Skipped** — Business Goal/Value, In/Out of Scope, DoD, project metadata

3. **Show a structured preview** with counts + every parsed item listed in full. Note what was skipped and why so the user knows you didn't miss it.

4. **Suggest a module name** based on the content's subject if user didn't provide one. Propose, don't impose.

5. **Wait for explicit approval** — *"looks good"* / *"ship it"* / *"yes push"* — same write-gate pattern as everywhere else. If the user wants edits, apply them and re-preview.

6. **On approval**, call `create_requirements` ONCE with `module_name=...` set so the module is auto-created and reqs auto-bind. No separate `create_module` call needed.

7. **Surface direct links** — module URL + every requirement URL as markdown links. ELM-savvy users will click in to verify; chat-native users can ignore.

8. **Offer next steps:**
   - *"Want me to create EWM tasks for these requirements?"* (Step 3d)
   - *"Want me to create ETM test cases? I'll use the held acceptance criteria + add any missing ones."* (Step 3e)
   - *"Want a baseline snapshot of the module?"* (if config mgmt is enabled)

#### Anti-patterns to avoid

- ❌ Re-wording the user's requirements when they explicitly want their original text. Preserve the wording. Convert to atomic shall-statements ONLY where the input is non-atomic (e.g. "ingest payloads and persist them" → 2 reqs).
- ❌ Pushing acceptance criteria as DNG requirements. ACs go in test cases.
- ❌ Pushing Business Goal / Risks / Assumptions / DoD as DNG requirements. They're project metadata.
- ❌ Pushing without preview + approval.
- ❌ Calling `create_module` then `create_requirements` separately. Use `module_name` in `create_requirements` for auto-bind.
- ❌ Inflating the count by splitting one idea into multiple reqs to look thorough. Be honest with the count.

### Step 3k: IMPORT WORK ITEM Path (brownfield — PDF → multi-artifact ELM graph)

Triggered by `/import-work-item`, by trigger phrases like *"import this Jira epic"*, or when the user provides a PDF that's a complete work-item export (epic + child stories + reqs + ACs all bundled).

This is the multi-artifact extension of Step 3j — instead of one DNG module, you produce: **1 EWM work item + 1 DNG module of reqs + N ETM test cases (from ACs) + M EWM child work items (from linked sub-tasks) + cross-links between all of them.**

#### What you do

1. **Extract the PDF.** Call `extract_pdf` with the user's path. Parse the resulting text into the structured layout the source format produces (Jira's epic export has a recognizable header + Description + Links + Comments shape).

2. **Identify the SIX artifact categories:**
   - **Main work item** (1) — the epic/story/feature itself. Title, ID, type, status, description.
   - **Functional requirements** (N) — atomic shall-statements from the "Functional Requirements" section
   - **Non-functional requirements** (M) — performance, security, retention, etc. Same atomic shape, NFR-tagged
   - **Acceptance criteria** (K) — test-shaped conditions; HOLD for ETM, do NOT push to DNG
   - **Linked work items** (J) — children, sub-tasks, "implements" / "relates to" entries
   - **Skipped** — Business Goal, Risks, Dependencies, Assumptions, DoD (project metadata)

3. **Resolve the EWM type — list-driven, never guess.** Read the type from the PDF (e.g. `Type: Epic`). Call `get_ewm_workitem_types(ewm_project)` to discover what the user's project actually exposes (Capability, Defect, Portfolio Epic, Solution Epic, Task, etc. — varies per project's process configuration). Match:
   - **Exact match** → use silently, mention as default in preview
   - **No match** → SHOW THE USER THE ACTUAL LIST and let them pick. Don't guess a vocabulary; show their project's real types
   - **Ambiguous** → show list with the closest matches highlighted

4. **Run the gap audit.** Five categories — quality / mapping / reference / completeness / decisions. Cap noise: top 5 quality gaps, summarize others. **Critical:** assignee mappings are NOT a gap. Original Jira assignee is preserved in artifact text where it appears naturally; EWM assignee defaults to UNSET — never ask. Mention as informational.

5. **Show comprehensive preview** with three escape hatches: address-each / push-with-defaults / ignore-gaps.

6. **Wait for explicit approval.** Same write-gate pattern as everywhere else.

7. **Push in dependency order:**
   - EWM main work item first (no inbound links yet)
   - DNG module + reqs via `create_requirements(module_name=...)` (auto-creates module + binds)
   - EWM child work items via `create_task` / etc. with `requirement_url=<main work item URL>` if applicable
   - ETM test cases via `create_test_case` with `requirement_url=<the relevant DNG req URL>`
   - Back-links to DNG are written automatically (since v0.1.12) — no extra `create_link` calls needed for the standard implements/validates relationships

8. **Post-push report:** every URL as a markdown link, plus every default-choice you made when "push with defaults" was used.

9. **Offer the natural next step:** *"Want me to /build-project from this state? I'd skip Phases 1–4 (artifacts already created), pick up at Phase 5 (your review in ELM), then re-pull current state and write the actual code."*

#### Anti-patterns

- ❌ Guessing what work-item types the project supports instead of calling `get_ewm_workitem_types`
- ❌ Asking "is this an epic, story, or task?" in the abstract instead of showing the project's actual list
- ❌ Trying to match the original Jira assignee to an EWM user — leave unset
- ❌ Pushing acceptance criteria as DNG requirements (they're test-shaped — go to ETM)
- ❌ Creating a separate `create_module` then `create_requirements` — use `module_name` in `create_requirements` for auto-bind
- ❌ Forgetting the cross-links — `create_task` / `create_test_case` should pass `requirement_url` so the link is written atomically (and the back-link is automatic per v0.1.12)
- ❌ Not surfacing default-choices in the post-push report — the user needs to see what was decided for them

### After Any Path
Ask: "Want to do anything else? I can read from another module, generate more requirements (single-tier or tiered), create tasks or test cases, or switch projects."

## Development Guardrails

### Requirement Status Awareness
When reading requirements from DNG, **always check the `status` attribute** on each requirement. The status comes back in the requirement data (look at the `status` field first, then `custom_attributes` for fields like `Accepted` if `status` is empty).

Before generating any downstream work (tasks, test cases, derived requirements, etc.) from requirements, check their status. If ANY source requirements are NOT Approved, warn the user:

> "Heads up — X of these requirements are currently **not Approved** (status: [Draft/In Progress/etc.]). Any work generated from unapproved requirements may need to change later. Do you want to proceed anyway?"

Only proceed after the user explicitly confirms. If ALL requirements ARE Approved, no warning needed — just proceed.

### Write Safety Rules
- ALL created artifacts are automatically prefixed with **[AI Generated]** in the title (done by the tool, not by you)
- ALL created artifacts are tagged with **[AI Generated]** in the content body (done by the tool, not by you)
- ALL created artifacts go into a descriptive folder (DNG) or directly into the project (EWM/ETM)
- **NEVER** modify existing artifacts UNLESS the user explicitly asks for a re-import/update AND approves the diff
- The only tool that modifies existing artifacts is `update_requirement` — and it REQUIRES showing the diff and getting approval first
- **NEVER** touch Approved requirements unless the user explicitly confirms
- **ALWAYS** show the user what will be created or changed and get explicit confirmation before writing
- The human is responsible for approving requirements and assigning work items.
- **`create_module` works** and **`create_requirements` with `module_name` auto-binds the requirements to the module** — no manual drag-bind in DNG needed. Under the hood this uses DNG's Module Structure API (the writable `<module>/structure` resource, gated by the `DoorsRP-Request-Type: public 2.0` header). The legacy `oslc_rm:uses` PUT route is locked down by DNG, but the structure API works fine — see `client.add_to_module()` and `probe/MODULE_BINDING_FINDINGS.md` for the recipe.
- If deriving work from non-approved requirements, the generated artifacts must include a note:
  > "[AI Generated] Note: Generated from requirements that were not yet Approved at time of creation."

## Tools Quick Reference

### DNG (Requirements)

| Tool | What it does | Parameters |
|------|-------------|------------|
| `connect_to_elm` | Connect to ELM server (works for DNG + EWM + ETM) | url, username, password |
| `list_projects` | List projects (DNG/EWM/ETM) | domain (dng/ewm/etm, default: dng) |
| `get_modules` | Get modules from a DNG project | project_identifier |
| `get_module_requirements` | Get requirements with URLs from a module | project_identifier, module_identifier |
| `save_requirements` | Save last-fetched requirements to file | format (json/csv/markdown), filename (optional) |
| `search_requirements` | Full-text search across all artifacts in a project | project_identifier, query |
| `get_artifact_types` | List valid artifact types for a project (call before `create_requirements`) | project_identifier |
| `get_link_types` | List link types for a project (call before `create_requirements` if linking) | project_identifier |
| `create_module` | Create a new DNG module artifact (the module shows up in DNG; drag-bind requirements via UI — see Important Rules) | project_identifier, title, description (optional) |
| `create_requirements` | Create requirements in DNG. `content` accepts plain text, Markdown (with tables/images/lists/headings), or raw XHTML. Goes into `jazz_rm:primaryText` (the rich-text body). | project_identifier, folder_name, requirements[] |
| `update_requirement` | Update an existing requirement's title or content (rich-text body) | requirement_url, title (optional), content (optional) |
| `get_attribute_definitions` | List ALL custom DNG attribute definitions for a project (name, predicate URI, value type, enum allowed values). **Call this before `update_requirement_attributes`** to discover valid attribute names and enum values. | project_identifier |
| `update_requirement_attributes` | Set arbitrary DNG attributes (Status, Priority, Stability, Owner, etc.). Pass either attribute names (resolved via `get_attribute_definitions`) or full predicate URIs. Values can be literals or enum-value labels (e.g. "High"). | requirement_url, attributes (dict of name→value) |
| `create_link` | Create a link between any two existing artifacts (DNG↔DNG, DNG↔EWM, etc.). For new links between artifacts that already exist; the on-creation `link_to`/`link_type` fields in `create_requirements` cover only links you create at the same time as the requirement. | source_url, link_type_uri, target_url |
| `create_baseline` | Create a baseline snapshot of a project | project_identifier, title, description (optional) |
| `list_baselines` | List existing baselines for a project | project_identifier |
| `compare_baselines` | Compare baseline vs current stream (shows diff) | project_identifier, module_identifier, baseline_url |
| `extract_pdf` | Extract text from a PDF file (use before PDF import) | file_path |

### EWM (Work Items)

| Tool | What it does | Parameters |
|------|-------------|------------|
| `create_task` | Create an EWM Task | ewm_project, title, description (optional), requirement_url (optional) |
| `create_defect` | Create an EWM Defect (handles "Filed Against" category resolution automatically) | ewm_project, title, description, severity (Minor/Normal/Major/Critical/Blocker), requirement_url (optional), test_case_url (optional) |
| `update_work_item` | Update arbitrary fields on an EWM work item (title, description, owner, custom fields) via PUT-with-If-Match | workitem_url, fields (dict of name→value) |
| `transition_work_item` | Move a work item through its workflow (e.g. New → In Progress → Resolved → Closed). Uses `?_action=` since direct state PUT is silently rejected by EWM. | workitem_url, target_state |
| `query_work_items` | Query EWM work items with `oslc.where` filter (e.g. `oslc_cm:closed=false`, `dcterms:type="Defect"`). Returns `{id, title, state, type, owner, modified, url}` per match. | ewm_project, where, select (optional, default "*"), page_size (optional, default 25) |

### ETM (Test Management)

| Tool | What it does | Parameters |
|------|-------------|------------|
| `create_test_case` | Create an ETM Test Case | etm_project, title, description (optional), requirement_url (optional) |
| `create_test_result` | Record a test result (pass/fail) | etm_project, test_case_url, status, title (optional) |

### GCM (Global Configuration Management)

| Tool | What it does | Parameters |
|------|-------------|------------|
| `list_global_configurations` | List all global configs (streams/baselines) across ELM | none |
| `list_global_components` | List all components across DNG/EWM/ETM | none |
| `get_global_config_details` | Get details + contributions for a global config | config_url |

### SCM / Code Reviews (read-only)

These tools cover the EWM SCM and code-review surface. Use them when the user asks "show me recent change-sets", "what's been delivered to project X", "what change-sets are linked to work-item N", or "show me the review for that work-item".

| Tool | What it does | Parameters |
|------|-------------|------------|
| `scm_list_projects` | List all CCM projects that have SCM data (one entry per project area). Use this to map a project name → projectAreaId. | (none) |
| `scm_list_changesets` | List recent change-sets, optionally scoped to a project. Walks the TRS feed and dereferences each change-set for full metadata. Returns `{itemId, title, component, author, modified, totalChanges, workItems[]}`. | project_name (optional), limit (default 25) |
| `scm_get_changeset` | Full metadata + raw RDF for a single change-set, including linked work items. | changeset_id |
| `scm_get_workitem_changesets` | Reverse-lookup: given a work-item id, list the change-sets linked to it. | workitem_id |
| `review_get` | Full review record for a work-item: title, state, type, approved/reviewed flags, all approval records (`approver, descriptor, state`), linked change-sets, comments. Works on any work-item — review-typed work-items are the canonical case but every WI has the approval shape. | workitem_id |
| `review_list_open` | Query EWM for open code-review work-items in a project (type = `com.ibm.team.review.workItemType.review`, `oslc_cm:closed=false`). May return zero on installations that don't use review work-items — that's expected, not an error. | ewm_project |

### Visualization

| Tool | What it does | Parameters |
|------|-------------|------------|
| `generate_chart` | Render bar/hbar/pie/line chart as PNG | chart_type, title, labels, values, x_label?, y_label?, output_filename? |

**When to use `generate_chart`:** any time the user asks to visualize, plot, graph, or "show me a chart" of ELM data — requirements by status, test pass/fail rates, tasks per priority, requirement counts per module, etc. **You** aggregate the raw data first (count, group, sum) from the previous tool calls, then pass the summary numbers in. Pick `pie` for proportions, `bar`/`hbar` for category comparisons (use `hbar` when labels are long), `line` for trends over time. The tool returns the absolute path to a PNG — show it to the user as a markdown image (`![title](/abs/path.png)`) so it renders inline.

## Important Rules

- Do NOT write Python code to interact with ELM. Use the MCP tools only.
- Projects and modules can be referenced by number (from listed output) or name (partial match works).
- The same connection works for DNG, EWM, and ETM — they share authentication on the same ELM server.
- Always be conversational — guide the user step by step, never dump raw data without context.
- For EWM tasks, always include the `requirement_url` when creating tasks from DNG requirements (cross-tool traceability).
- For ETM test cases, always include the `requirement_url` when creating from DNG requirements (validates requirement link).
- Requirement URLs come from `get_module_requirements` output or `create_requirements` output — both tools show the URL for each requirement.
- For requirement content: prefer **Markdown** for `content` — full Markdown including tables, images, headings, lists, links, bold/italic, and code blocks is auto-converted to clean XHTML. For complex layouts you can also pass raw XHTML (must start with `<`, must be valid XML — only the 5 XML entities `&amp; &lt; &gt; &quot; &apos;` work; use literal Unicode for anything else like `±` or `°`).
- For images in requirements: external `<img src="https://…">` URLs may be blocked by DNG's CSP — if an image doesn't render, use a `data:` URI for small images, or upload as a DNG attachment and reference the internal URL.
- Acceptance criteria / verification methods belong in **ETM test cases** linked to the requirement, NOT inside the requirement body. Some teams put a brief pass/fail line in the requirement; that's fine, but full test procedures live in ETM (Phase 3 of the lifecycle).
