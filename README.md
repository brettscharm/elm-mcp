# ELM MCP

**An MCP server that lets AI assistants drive IBM Engineering Lifecycle Management (ELM) — DOORS Next, EWM, ETM, GCM, and SCM/code-review — through standard OSLC and Reportable REST APIs.**

> ## ⚠️ This is a personal passion project. NOT created, endorsed, supported, or distributed by IBM or the ELM development team.
>
> **Use entirely at your own risk.** Built by Brett Scharmett on personal time for community / demo use.
> No warranty. No SLAs. No IBM backing. Things can and will break — file issues, send PRs, or just don't use it.
>
> *IBM, DOORS Next, ELM, EWM, ETM, Engineering Workflow Management, Engineering Test Management, and Jazz are trademarks of International Business Machines Corp. This project is independently developed against IBM's public OSLC / Reportable REST APIs.*

---

## What it does

**35 MCP tools, 4 workflow prompts, 3 resource templates** — read and write across the full ELM stack from any MCP-speaking AI assistant (Claude Code, VS Code Bob/Copilot, Cursor, Windsurf, custom agents).

| Domain | Read | Write | Query / Workflow |
|---|---|---|---|
| **DNG** (Requirements) | List projects, modules, requirements, artifact types, link types, attribute definitions, baselines | Create requirements (with rich Markdown / XHTML / tables / images), create modules, create folders, update title/content, **update arbitrary attributes** (Status, Priority, etc.), create baselines | Search, compare baselines, **create links** between any two existing artifacts |
| **EWM** (Work Items) | List projects | Create Tasks, **create Defects** (with Filed Against resolution) | **Update work items**, **transition workflow states** (New → In Progress → Resolved → Closed), **query work items** with `oslc.where` filters |
| **ETM** (Test) | List projects | Create test cases, create test results | — |
| **GCM** (Global Config) | List configs, list components, get config details | — | — |
| **SCM** (Code) | List SCM projects, list change sets, get change set + linked work items, get code review record | — | Reverse-lookup: get change sets for a work item |
| **Other** | Extract PDF (for re-import), generate charts (PNG) | — | — |

The MCP server itself does **zero AI generation** — every tool is a deterministic API call against ELM. The intelligence (writing requirements, parsing PDFs, picking chart types, choosing tools) comes from whichever AI assistant you connect.

---

## Quick Start (≈ 2 minutes)

You need: Python 3.9+, an ELM account, and one of: Claude Code, VS Code (with Copilot/Bob), Cursor, or Windsurf.

### Option A — Smithery (one-line install for IBM Bob, Claude Code, Cursor, etc.)

```bash
# Once Smithery CLI is installed
npm install -g @smithery/cli       # one-time
smithery install brettscharm/elm-mcp
```

Smithery clones, configures, and registers the MCP with whatever AI host you have. You'll be prompted for `ELM_URL`, `ELM_USERNAME`, `ELM_PASSWORD`. Updates: `smithery update elm-mcp`.

### Option B — Manual clone + setup.py

```bash
# 1. Get the code (one-time — never re-clone, just `git pull` to update)
git clone https://github.com/brettscharm/elm-mcp.git
cd elm-mcp

# 2. Run setup. Installs deps, writes MCP config for every AI host
#    detected (Claude Code, IBM Bob, VS Code, Cursor, Windsurf), prompts
#    for ELM credentials, and ACTUALLY LAUNCHES the MCP server in a
#    subprocess to verify the handshake + tool registration end-to-end.
python3 setup.py

# 3. Restart your AI assistant and say:
#    "Connect to ELM and list my projects"
```

`setup.py` is idempotent — re-run it any time (after switching AI tools, rotating your password, upgrading Python, etc.). It exits non-zero on any real failure so it's safe to wire into CI.

**After first setup, restart your AI assistant** so it picks up the new MCP entry. Claude Code reads `~/.claude.json` and the project-local `.mcp.json` on each session start.

### Verify it works any time

```bash
python3 setup.py --diagnose
```

Skips installation and config writes. Just:
1. Confirms the current Python can import every dependency
2. Launches `doors_mcp_server.py` as a subprocess, runs the MCP `initialize` handshake, calls `tools/list`, asserts ≥1 tool registered (proves the server actually starts)
3. Optionally exercises ELM auth if `.env` has credentials

Use this when something feels off — server "not found" in your IDE, password rotated, Python upgraded, etc.

---

## Bring your own LLM

This repo is the **hands**, not the brain. Same server works against any MCP-speaking host:

| AI Assistant | Config file `setup.py` writes | Doc reference |
|---|---|---|
| **Claude Code** | `~/.claude.json` (user) + `.mcp.json` (project) | https://code.claude.com/docs/en/mcp |
| **IBM Bob** | `~/.bob/mcp_settings.json` (user) + `.bob/mcp.json` (project) | https://bob.ibm.com/docs/ide/configuration/mcp/mcp-in-bob |
| **VS Code** (Copilot) | `.vscode/mcp.json` (workspace) | https://code.visualstudio.com/docs/copilot/customization/mcp-servers |
| **Cursor** | `.cursor/mcp.json` (workspace) + `~/.cursor/mcp.json` (user) | https://cursor.com/docs/context/mcp |
| **Windsurf** | `~/.codeium/windsurf/mcp_config.json` | https://docs.windsurf.com/windsurf/cascade/mcp |

`setup.py` writes to every host it detects in one run. **For Bob specifically:** the read-only tools (list, get, query, search, etc.) are pre-approved via `alwaysAllow`, so Bob runs them without per-call permission prompts. Writes (create, update, transition, link) still ask for confirmation.

---

## Credentials

`setup.py` walks you through it. Under the hood it writes a local `.env`:

```
ELM_URL=https://your-elm-server.com
ELM_USERNAME=your_username
ELM_PASSWORD=your_password
```

One login covers all five ELM domains — DNG, EWM, ETM, GCM, SCM. The URL field accepts any of `https://server`, `https://server/rm`, `https://server/ccm`, `https://server/jts` etc.; the client strips the domain suffix and re-attaches the right path per call.

`.env` is gitignored. The server handles **Basic Auth and Form-Based Auth (`j_security_check`)** automatically and falls back to disabled SSL verification for self-signed certs — you don't need to know which one your server uses.

> **Legacy compat:** older `.env` files using `DOORS_URL` / `DOORS_USERNAME` / `DOORS_PASSWORD` still work. The new `ELM_*` names take precedence when both are set. No migration required — but if you regenerate `.env` via `setup.py` it'll write the new names.

To re-enter credentials later, delete `.env` and re-run `setup.py`.

---

## The proper development flow

This is what good engineering looks like with ELM, and what the AI should follow. **Each phase has a user-approval gate** — the AI shouldn't blast through all four without checking in.

```
┌─────────────────────────────────────────────────────────────┐
│ PHASE 1 — REQUIREMENTS  (DNG)                               │
│ AI generates atomic "shall" statements. Organized in a      │
│ module. IEEE 29148 / INCOSE compliant: atomic, verifiable,  │
│ unambiguous. Status starts at "Proposed".                   │
│ ─→ AI STOPS. "Review these. Approve to continue?"           │
└─────────────────────────────────────────────────────────────┘
                             ↓ user approves
┌─────────────────────────────────────────────────────────────┐
│ PHASE 2 — IMPLEMENTATION TASKS  (EWM)   only if user wants  │
│ One Task per requirement. Linked via                        │
│ calm:implementsRequirement. Owner / iteration / estimate    │
│ default unset.                                              │
│ ─→ "Want me to create test cases too?"                      │
└─────────────────────────────────────────────────────────────┘
                             ↓ user approves
┌─────────────────────────────────────────────────────────────┐
│ PHASE 3 — TEST CASES  (ETM)             only if user wants  │
│ One Test Case per requirement. Linked via                   │
│ oslc_qm:validatesRequirement. Test steps, expected results, │
│ pass/fail conditions live HERE — not inside the requirement.│
└─────────────────────────────────────────────────────────────┘
                             ↓ post-implementation
┌─────────────────────────────────────────────────────────────┐
│ PHASE 4 — DEFECTS  (EWM)                when tests fail     │
│ Failing test result triggers a Defect (with proper          │
│ Filed Against resolution). Linked back to test result and   │
│ original requirement. Transitioned through workflow.        │
└─────────────────────────────────────────────────────────────┘
```

What the AI **will not** do automatically:
- Push past Phase 1 without explicit user approval
- Mark a requirement "Approved" — that's a human gate
- Skip cross-domain links — every artifact traces back

The full instructions the AI reads are in [BOB.md](BOB.md).

---

## Rich text in requirements

`create_requirements`'s `content` field accepts three input shapes (the AI picks whichever is easiest):

1. **Raw XHTML** — for hand-built complex layouts. Pass-through when content starts with `<`. Must be valid XML — only the 5 XML entities (`&amp; &lt; &gt; &quot; &apos;`); use literal Unicode for everything else (`±`, `°`, etc.). Named HTML entities like `&plusmn;` will reject.
2. **Markdown** — full Markdown including tables, images, headings, lists, links, bold/italic, code blocks. Auto-converted to XHTML.
3. **Plain text** — paragraphs split on blank lines; lines starting with `- ` or `* ` become bulleted lists.

DNG renders the result in `jazz_rm:primaryText` (the rich-text body), not `dcterms:description` (which is a short summary).

**Image caveat:** DNG's CSP may block external image URLs. If your image doesn't render, upload it as a DNG attachment and reference the internal URL — or use a `data:` URI for small images.

---

## Known limitations

These are **server-side restrictions**, not bugs in this MCP:

- **Adding requirements to a module's structure programmatically** is locked down on most ELM deployments. The standard OSLC PUT/PATCH pattern that works for every other write returns `400 "Content must be valid rdf+xml"` only when the change involves `oslc_rm:uses`. ReqIF import is the only documented path; not yet implemented in this MCP. Workaround: `create_module` + `create_requirements` produces the module + a folder of requirements, then drag them into the module in DNG UI. (Full investigation: [probe/MODULE_BINDING_FINDINGS.md](probe/MODULE_BINDING_FINDINGS.md).)
- **Some ELM features depend on server version / feature flags** — DNG glossary, link validity, certain GCM operations may return 404 on older deployments.
- **Permissions vary per project** — `setup.py --diagnose` confirms auth works, but write permissions are project-scoped in DNG/EWM/ETM. If a write fails with 403, it's a permission grant in your DNG admin, not a code bug.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `setup.py`: "No AI assistants detected" | Install one of Claude Code / VS Code / Cursor / Windsurf, then re-run. |
| AI can't see the MCP server | Restart your IDE. Run `python3 setup.py --diagnose` to verify the server itself works independent of the IDE. |
| Connection test fails | The error tells you what's wrong (bad password, unreachable server, cert issue). Fix the one thing and re-run. |
| EWM/ETM/DNG creation fails with 403 | Your account needs Create permission in that project. Open the project's admin → Permissions and grant your role write access. |
| Requirements created but Primary Text is empty | Older artifacts only — this was a bug fixed Apr 2026. New requirements use `jazz_rm:primaryText` correctly. Re-run with the AI to recreate. |
| "Module created but requirements aren't in it" | DNG locks `oslc_rm:uses` writes; see Known Limitations above. |
| Charts don't render in chat | Make sure your AI tool can display markdown images. Worst case, open the file directly — paths are printed. |

---

## Project structure

```
elm-mcp/
├── setup.py               # One-command installer + --diagnose flag
├── doors_mcp_server.py    # MCP server (35 tools, 4 prompts, 3 resources)
├── doors_client.py        # ELM REST client (DNG + EWM + ETM + GCM + SCM)
├── BOB.md                 # Instructions the AI reads automatically
├── CLAUDE.md              # Pointer to BOB.md for Claude Code
├── LIFECYCLE.md           # Full requirements-to-test lifecycle reference
├── README.md              # This file
├── requirements.txt       # Python dependencies
├── .env.example           # Credential template (copied to .env by setup)
├── .mcp.json              # Project-local Claude Code MCP entry (gen by setup)
├── charts/                # Generated PNGs (gitignored)
└── probe/                 # Live-server probes + research reports
    ├── OSLC_GAPS.md       # Tool gap analysis
    ├── SCM_RESEARCH.md    # SCM + code review research
    └── MODULE_BINDING_FINDINGS.md  # Why module-binding is locked down
```

---

## Contributing / Issues

- GitHub issues: https://github.com/brettscharm/elm-mcp/issues
- Email: brett.scharmett@ibm.com  *(personal capacity — not IBM support)*

PRs welcome. The probes in `probe/` document everything we've learned about the live ELM API surface; new tools should follow the patterns in `doors_client.py` (GET-with-ETag → modify → PUT-with-If-Match for updates; service-provider-discovery → POST to creation factory for creates) and add a one-line live-test entry to `probe/A_C_LIVE_TESTS.txt` if exercising new endpoints.
