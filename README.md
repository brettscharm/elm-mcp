# ELM MCP — talk to IBM ELM from Bob

> **Stop clicking around DOORS Next. Just tell Bob what you want.**
>
> *"Bob, build me a tracking service end-to-end with requirements, tasks, and tests in ELM."*
> *"Bob, import this Jira epic PDF into DNG."*
> *"Bob, what's the team been doing this week?"*

> ⚠️ Personal passion project. **NOT** an official IBM tool. Use at your own risk. IBM, DOORS Next, ELM, EWM, ETM are trademarks of IBM Corp.

---

## Set up Bob in 3 steps (30 seconds)

You need: macOS, Linux, **or Windows**; Python 3.9+; and an ELM account.

> ### 🛑 Prerequisite: DNG configuration management (CM) must be enabled on your projects
>
> ELM MCP is built around the full DNG flow — modules, baselines, streams, traceability — which **all require IBM's configuration management (CM) feature** on the DNG project. Without CM:
> - You can still create requirements (in folders)
> - You **cannot** bind requirements into modules programmatically — there is no DNG API path for this on non-CM projects (verified against IBM's own ELM-Python-Client)
> - You **cannot** baseline requirements at Phase 5 of `/build-project`
> - You **cannot** use streams for parallel requirements work
>
> **If your DNG project doesn't have CM enabled:** ask your DNG admin to enable it (one project-level toggle in DNG admin; doesn't break existing data). Most enterprise ELM customers have CM on by default.
>
> **If you don't know whether CM is enabled:** ask Bob to connect and try `/build-new-project` — the flow tells you immediately if CM is missing on the target project.

### Step 1 — install

**macOS / Linux** — open Terminal, paste this, hit Enter:

```bash
curl -fsSL https://raw.githubusercontent.com/brettscharm/elm-mcp/main/install.sh | bash
```

**Windows** — open PowerShell, paste this, hit Enter:

```powershell
irm https://raw.githubusercontent.com/brettscharm/elm-mcp/main/install.ps1 | iex
```

Either command:
- Downloads ELM MCP to `~/.elm-mcp` (`%USERPROFILE%\.elm-mcp` on Windows)
- Asks you for your ELM URL, username, password (typed at the prompt — never sent anywhere except your own machine)
- Writes Bob's MCP config automatically (`~/.bob/settings/mcp_settings.json`)
- **Installs the 5 custom modes** (🧭 Concierge, 📝 Plan, 📤 Push, 🎯 Impact Analyst, 📜 Compliance Auditor) — merged into Bob's modes, your other modes preserved
- Verifies the whole thing works end-to-end

> **Dependencies just work.** Even if Bob launches the server with a different Python than the installer used (the #1 cause of "missing dependency" failures), the server **self-heals** on first start — it installs its own dependencies into whatever interpreter Bob uses, then restarts. No guessing, no manual `pip install`.

> **No internet one-liner / corporate-locked machine?** Works on every OS:
> `git clone https://github.com/brettscharm/elm-mcp.git ~/.elm-mcp`, then
> `cd ~/.elm-mcp` and `python3 setup.py` (use `py setup.py` on Windows).
> `setup.py` is the cross-platform workhorse — the one-liners above just wrap it.

> Don't want the modes? add `--no-modes`. Re-install just the modes after editing them? `setup.py --modes-only`.

### Step 2 — fully quit + reopen Bob

Bob only loads MCP servers at startup; you have to actually quit, not just close the window. **macOS:** Cmd + Q. **Windows:** right-click the tray/taskbar icon → Quit (or Alt+F4). Then reopen.

### Step 3 — say hi

In any Bob chat, type:

> *"Connect to ELM and list my projects."*

Bob should respond with your DNG projects. **You're done.** Try one of these next:

- *"Build me a temperature converter web app end-to-end."*
- *"Show me what's in the [Module Name] module."*
- *"What can you do?"* (Bob calls `list_capabilities` and shows you the menu)

---

## Common things you'll ask Bob

| You say | What Bob does |
|---|---|
| *"build me a [thing]"* | Full agentic flow: requirements → tasks → tests → review pause → code |
| *"import this Jira epic [paste text or PDF path]"* | Parses the epic into ELM artifacts (epic + reqs + tests + cross-links) |
| *"import JIRA-1234"* / *"/import-jira"* | **Live** Jira pull via elm-mcp's native Jira tools — fetches the issue, interviews you, creates DNG requirements with `Source: JIRA-XXX` stamp, posts a back-link comment on the Jira issue. Talks to Jira REST directly (API token, no OAuth). Requires `--with-jira` setup (see below). |
| *"show me the reqs in [module]"* | Reads the module from DNG, summarizes |
| *"what's the team doing?"* | Reads the BOB Team Actions module, summarizes who did what |
| *"resume my last build"* | Picks up an in-progress build run from where you left off |
| *"I'm done for today"* | Wraps up your session with a final entry teammates can read |
| *"update yourself"* | Pulls the latest version of ELM MCP from GitHub |
| *"are you connected? what version?"* | Self-diagnoses connection state, version, active runs |

You don't have to memorize these. Bob figures it out from natural language. If you're not sure what to do, just type **`/getting-started`** and Bob asks one question to point you at the right starting point.

---

## When something goes wrong

**Bob can't see ELM MCP after install:**
1. Did you fully quit Bob (Cmd+Q) and reopen?
2. Run `python3 ~/.elm-mcp/setup.py --diagnose` — it tells you what's wrong in plain English

**Bob asks for approval on every single action:**
- Re-run `python3 ~/.elm-mcp/setup.py` — refreshes Bob's allow-list with the current set of safe-to-auto-approve tools
- Quit + reopen Bob

**Module binding fails ("requirements created but not in module"):**
- Your DNG project doesn't have configuration management enabled
- Either ask your DNG admin to enable it, or open the module in DNG and drag the requirements in manually
- Then tell Bob *"continue"* and the build flow picks back up

**Anything else:**
- Tell Bob *"run elm_mcp_health"* — it'll dump connection state, version, last update check, etc.
- Or open an issue: https://github.com/brettscharm/elm-mcp/issues

---

## To update

The simplest way: **say *"update yourself"* in any Bob chat.** That's a single tool call — Bob pulls the latest from GitHub and tells you to restart.

Or in terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/brettscharm/elm-mcp/main/install.sh | bash
```

(Same command as install — re-running it just updates.)

---

## Optional: live Jira integration (`/import-jira`)

If you want Bob to pull live Jira issues into DNG and post back-link comments to Jira (round-trip traceability), add Jira credentials to your `.env`:

```bash
# If you already have elm-mcp installed:
python3 ~/.elm-mcp/setup.py --with-jira

# Or edit ~/.elm-mcp/.env directly and add:
#   JIRA_BASE_URL=https://yourorg.atlassian.net
#   JIRA_EMAIL=your-atlassian-email@example.com
#   JIRA_API_TOKEN=ATATT...
# Token: https://id.atlassian.com/manage-profile/security/api-tokens
```

**How it works:** elm-mcp talks to Jira's REST API **directly** using your email + API token (HTTP Basic auth). No Atlassian MCP server, no `mcp-remote` bridge, no OAuth, no Node.js. Five tools are added: `get_jira_issue`, `search_jira_issues`, `add_jira_comment`, `add_jira_remote_link`, `jira_health`.

**Why this instead of Atlassian's official MCP?** Atlassian's hosted MCP at `mcp.atlassian.com/v1/mcp` uses OAuth 2.1 and the OAuth flow doesn't complete reliably inside IBM Bob's embedded webview — verified in the field. Going direct-REST sidesteps the problem.

After credentials are in `.env`:
1. Quit + reopen Bob (so it picks up the new tools).
2. Run `jira_health` in chat to confirm auth works.
3. Try it: *"`/import-jira issue_key=PROJ-123`"* — Bob fetches the issue, interviews you, creates DNG requirements with `Source: PROJ-123 — <jira-url>` stamped on each, then posts a comment back to Jira listing all the created DNG URLs.

See `BOB.md` Step 3l for the full workflow.

---

## What it actually does (for the curious)

ELM MCP is a Model Context Protocol server. It exposes IBM Engineering Lifecycle Management — DNG (requirements), EWM (work items / tasks / defects), ETM (test management), GCM (global config), and SCM/code-review — as **62 tools and 10 prompts** that any MCP-speaking AI assistant can call. Bob is one such assistant; Claude Code, Cursor, Windsurf are others.

The MCP itself does **zero AI generation**. Every tool is a deterministic API call against ELM. The intelligence — writing requirements, parsing PDFs, picking the right module — comes from whichever AI you connect.

The headline workflow is **`/build-new-project`**:
1. You give Bob a one-line idea
2. Bob interviews you (5 min)
3. Bob proposes requirements; you approve
4. Bob proposes tasks; you approve
5. Bob proposes test cases; you approve
6. **STOP** — you review everything in DNG/EWM/ETM
7. Bob re-pulls current state, writes the actual app code with `# Implements: REQ-005` headers tying every file to the requirement
8. Bob marks tasks resolved, records test results in ETM as it goes
9. Final summary: traceability matrix, all URLs clickable

Every phase has an explicit user-approval gate. Bob can't blast through to writing code without your sign-off at each step.

---

## Bring your own AI assistant

Same server works against any MCP-speaking host. `install.sh` writes the right config for every host it detects:

| AI Assistant | Config file written |
|---|---|
| **IBM Bob** | `~/.bob/mcp_settings.json` (global) + `<project>/.bob/mcp.json` (project-local) |
| **Claude Code** | `~/.claude.json` (global) + `.mcp.json` (project) |
| **VS Code Copilot** | `.vscode/mcp.json` |
| **Cursor** | `~/.cursor/mcp.json` |
| **Windsurf** | `~/.codeium/windsurf/mcp_config.json` |

---

## Manual install (only if `curl | bash` doesn't fit your security policy)

```bash
git clone https://github.com/brettscharm/elm-mcp.git ~/.elm-mcp
cd ~/.elm-mcp
python3 setup.py
```

Same outcome, just two more steps.

For air-gapped / locked-down environments where automatic config-write doesn't work, run `python3 ~/.elm-mcp/setup.py --print-config`. It outputs the JSON ready to paste manually into Bob's `~/.bob/mcp_settings.json` with absolute paths pre-filled for your machine.

---

## Privacy + credentials

- ELM password lives ONLY in `~/.elm-mcp/.env` on your machine
- That file is gitignored; it's never committed
- The MCP authenticates directly with your ELM server using your account; no third-party services involved
- Re-enter credentials anytime by deleting `.env` and re-running `setup.py`

---

## File layout (if you want to inspect the code)

```
~/.elm-mcp/
├── setup.py                  # Installer (this is what install.sh runs)
├── doors_mcp_server.py       # The MCP server itself (62 tools)
├── doors_client.py           # ELM REST client (DNG + EWM + ETM + GCM + SCM)
├── BOB.md                    # Instructions Bob reads automatically
├── README.md                 # This file
├── .env                      # YOUR credentials (gitignored, local only)
└── probe/                    # Live-server probes + research notes
```

---

## Help / issues / contributing

- Issues: https://github.com/brettscharm/elm-mcp/issues
- Email: brett.scharmett@ibm.com (personal capacity, not IBM support)

PRs welcome. The probes in `probe/` document the live ELM API surface; new tools should follow the patterns in `doors_client.py` (GET-with-ETag → modify → PUT-with-If-Match for updates; service-provider-discovery → POST to creation factory for creates).

---

## Share with your team

Copy-paste-ready blurb:

> 🤖 **ELM MCP** — drive IBM DOORS Next, EWM, and ETM from Bob (or any AI assistant) instead of clicking around the web UI.
>
> Install in 30 seconds:
> ```
> curl -fsSL https://raw.githubusercontent.com/brettscharm/elm-mcp/main/install.sh | bash
> ```
> Restart Bob. Say *"connect to ELM and list my projects."*
>
> 62 tools, 10 prompts. Read/write requirements (rich text + tables + images), build full projects end-to-end with traceable code, import Jira epics, see what your team's been up to. Full details: https://github.com/brettscharm/elm-mcp
>
> ⚠️ Personal passion project — NOT an official IBM tool.
