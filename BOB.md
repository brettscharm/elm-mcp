# ELM MCP — AI Instructions (BOB.md)

> **DISCLAIMER:** This is a personal passion project. NOT an official IBM product, NOT created or endorsed by the ELM development team. Use at your own risk. IBM, DOORS Next, ELM, EWM, and ETM are trademarks of IBM Corporation.

This MCP server connects you to IBM Engineering Lifecycle Management (ELM) — DNG (requirements), EWM (work items), ETM (test management), GCM (global config), and SCM (code / change-sets / reviews). 35 tools total. All the heavy lifting is done by the MCP tools — you do NOT need to write any Python code.

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

## Generation Discipline — applies to EVERY create/update tool

**Before you generate ANYTHING — requirements, modules, tasks, test cases, defects, links, attribute updates — you must follow this 3-step contract. No exceptions, no shortcuts, no "the user clearly meant X" assumptions.**

```
1. INTERVIEW   Ask the user 3–5 specific questions to understand what they
               actually want. Ask one at a time, wait for each answer
               before the next. Never generate until you have:
                 • The target system / feature / domain (vague is bad)
                 • The kind of artifact (functional / security / etc.)
                 • Any standards or compliance constraints
                 • The intended count/scope (5 reqs? 50? a whole module?)
                 • Anything else specific the user wants included or avoided

2. PREVIEW     Show a clean table of EXACTLY what you will create —
               titles, types, key fields, link targets — BEFORE any
               tool call fires. The user must be able to read every
               artifact and say "change #3, drop #5".

3. CONFIRM     Wait for explicit "yes" / "go ahead" / "ship it" / "push
               them". "Sure" / "ok" without context counts. Anything
               ambiguous → ask again. Then and only then call the tool.
```

**Why this matters:** AI-generated requirements / tasks / tests are only valuable if they reflect the user's actual intent. Skipping the interview turns this MCP into a slop generator that produces plausible but useless content. The 30 seconds of conversation up front saves an hour of cleanup later.

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
> 7. **Full Lifecycle** — Requirements → Tasks → Test Cases (all three)"

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
If the user wants to generate requirements, DO NOT start generating immediately. Follow this interview process:

**Phase 1: Understand what they need**

Ask these questions one at a time (not all at once). Wait for each answer before asking the next:

1. > "What system or feature are these requirements for? Give me a brief description."

2. > "What type of requirements are we writing? For example: stakeholder, system-level, software, hardware, security, performance, etc."

3. > "Are there any applicable standards, regulations, or compliance frameworks? For example: DO-178C, ISO 26262, IEC 62304, NIST 800-53, MIL-STD-882, or industry-specific standards."

4. > "How many requirements are you looking for? A handful (5-10) or a more comprehensive set (20+)?"

5. > "Is there anything specific that must be included? Any constraints, interfaces, environmental conditions, or existing requirements I should be aware of?"

6. > "Should these requirements link to any existing artifacts? For example, if these are system requirements that satisfy stakeholder requirements, I can create Satisfies or Elaborated By links. What link type should I use, or should I skip linking?"

**Phase 2: Generate using proper requirements engineering practices**

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

When the user wants to create EWM tasks from requirements:

**Phase 1: Gather source requirements**

1. If the user hasn't already read requirements, guide them through Step 3a first to get requirement URLs
2. **Check requirement status** — look at the `status` field on each requirement. If `status` is empty, check `custom_attributes` for status-like fields. If ANY requirements are NOT Approved, warn the user:
   > "Heads up — X of these requirements are not Approved yet. Proceed anyway?"
   Only proceed after explicit confirmation.
3. Ask: "Which EWM project should I create the tasks in?" If the user doesn't know, call `list_projects` with `domain=ewm` to show them the options.

**Phase 2: Generate and preview tasks**

1. For each source requirement, generate a Task with:
   - **Title**: actionable implementation task derived from the requirement (verb-first: "Implement...", "Design...", "Configure...")
   - **Description** must include:
     - **Objective**: What this task accomplishes and why
     - **Acceptance criteria**: Copied directly from the source requirement's measurable criteria
     - **Verification method**: How to confirm the task is done (code review, test, demo, inspection)
     - **Dependencies**: Any prerequisite tasks or external dependencies
   - `requirement_url` set to the source requirement's URL (from `get_module_requirements` output)
2. **Present in a clean table:**

   > Here are the **X tasks** I'd create in EWM project [project name]:
   >
   > | # | Task Title | Linked Requirement | Acceptance Criteria | Verification |
   > |---|-----------|-------------------|---------------------|--------------|
   > | 1 | Implement battery backup subsystem | REQ-001: Power Management | Backup activates within 5s, sustains 4h | Integration test |
   > | ... | ... | ... | ... | ... |
   >
   > **Each task will be linked to its source requirement. Want me to push these to EWM?**

3. Only after explicit confirmation → call `create_task` for each task with `ewm_project`, `title`, `description`, **AND `requirement_url`**.

   **CRITICAL — `requirement_url` is what creates the link.** Pass it verbatim — copy the URL from the `url` field of each requirement in the previous `create_requirements` or `get_module_requirements` output. Do NOT paraphrase, do NOT use the requirement's friendly ID — use the literal `https://server/rm/resources/TX_xxx` URL. Without this field, the task is created but unlinked, and traceability breaks. **If you're creating N tasks for N requirements, you must pass N different `requirement_url` values, one per task.**

4. After all tasks are created, verify the linking worked: pick one task URL from the response and re-fetch it (the response should include `oslc_cm:implementsRequirement` pointing at the requirement). If any task came back without the link, fix it by calling `create_link` with `link_type_uri="http://open-services.net/ns/cm#implementsRequirement"`, `source_url=<task URL>`, `target_url=<requirement URL>`.

**Phase 3: Confirm delivery**

Tell the user:
> "Done! I created X tasks in EWM project '[project name]'. Each task is linked to its source requirement in DNG. A project lead can assign them to iterations and developers."

### Step 3e: CREATE TEST CASES Path (ETM)
When the user wants to create ETM test cases from requirements:

**Phase 1: Gather source requirements**

1. If the user hasn't already read requirements, guide them through Step 3a first to get requirement URLs
2. **Check requirement status** — same as Step 3d: look at the `status` field, check `custom_attributes` if empty. Warn if any are not Approved.
3. Ask: "Which ETM project should I create the test cases in?" If the user doesn't know, call `list_projects` with `domain=etm` to show them the options.

**Phase 2: Generate and preview test cases**

1. For each source requirement, generate a Test Case with:
   - **Title**: verification-oriented phrasing ("Verify...", "Validate...", "Confirm...")
   - **Description** must include structured test procedure:
     - **Preconditions**: Required system state, test environment, and setup
     - **Test Steps**: Numbered, specific, reproducible actions (not vague — include exact values, inputs, and sequences)
     - **Expected Results**: Measurable outcomes for each step tied directly to the requirement's acceptance criteria
     - **Pass/Fail Criteria**: Explicit conditions for pass and fail (e.g., "PASS if backup activates in <=5 seconds; FAIL if >5 seconds or no activation")
   - `requirement_url` set to the source requirement's URL (from `get_module_requirements` output)
2. **Present in a clean table:**

   > Here are the **X test cases** I'd create in ETM project [project name]:
   >
   > | # | Test Case Title | Validates Requirement | Preconditions | Test Steps | Pass/Fail Criteria |
   > |---|----------------|----------------------|---------------|------------|-------------------|
   > | 1 | Verify power backup activates within 5 seconds | REQ-001: Power Management | System at normal operation, backup fully charged | 1. Remove primary power 2. Start timer 3. Observe backup activation 4. Verify system operation for 60s | PASS: backup active <=5s, system operational. FAIL: >5s or system interruption |
   > | ... | ... | ... | ... | ... | ... |
   >
   > **Each test case will be linked to its source requirement. Want me to push these to ETM?**

3. Only after explicit confirmation → call `create_test_case` for each with `etm_project`, `title`, `description`, **AND `requirement_url`**.

   **CRITICAL — `requirement_url` is what creates the link.** Pass it verbatim from the `url` field of each requirement in the previous `create_requirements` or `get_module_requirements` output. Same rules as for tasks: literal URL only (`https://server/rm/resources/TX_xxx`), one URL per test case, never skip this field when validating an existing requirement. Without it, the test case is created but unlinked — coverage reports won't show it validates anything.

   After all test cases are created, verify by re-fetching one and confirming `oslc_qm:validatesRequirement` points at the requirement. If any came back without the link, fix it: call `create_link` with `link_type_uri="http://open-services.net/ns/qm#validatesRequirement"`, `source_url=<test case URL>`, `target_url=<requirement URL>`.

**Phase 3: Record test results (optional)**

After creating test cases, ask:
> "Would you like me to record test results for any of these test cases? I can mark them as passed, failed, blocked, incomplete, or error."

If yes → call `create_test_result` for each with `etm_project`, `test_case_url` (from `create_test_case` output), and `status` (as specified by the user).

**Phase 4: Confirm delivery**

Tell the user:
> "Done! I created X test cases in ETM project '[project name]'. Each test case validates its source requirement in DNG. Review them in ETM and approve the test plan."

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
