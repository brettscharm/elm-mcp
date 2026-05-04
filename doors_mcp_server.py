#!/usr/bin/env python3
"""
DOORS Next AI Agent — MCP Server
Provides tools for AI assistants to interact with IBM Engineering Lifecycle Management (ELM)
Covers DNG (requirements), EWM (work items), ETM (test management), and SCM (change-sets).

Tools (33):
  Existing (21):
    1.  connect_to_elm              - Connect with credentials
    2.  list_projects               - List DNG/EWM/ETM projects (domain parameter)
    3.  get_modules                 - Get modules from a DNG project
    4.  get_module_requirements     - Get requirements from a module
    5.  save_requirements           - Save requirements to a file (JSON/CSV/Markdown)
    6.  search_requirements         - Full-text search across all artifacts in a project
    7.  get_artifact_types          - Discover artifact types for a DNG project
    8.  get_link_types              - Discover link types for a DNG project
    9.  create_requirements         - Create requirements with links in a descriptive folder
   10. update_requirement          - Update an existing requirement's title and/or content
   11. create_baseline             - Create a baseline snapshot of a DNG project
   12. list_baselines              - List existing baselines for a DNG project
   13. compare_baselines           - Compare baseline vs current stream (shows diff)
   14. extract_pdf                 - Extract text from a PDF file for import into DNG
   15. create_task                 - Create an EWM Task with optional DNG requirement link
   16. create_test_case            - Create an ETM Test Case with optional DNG requirement link
   17. create_test_result          - Create an ETM Test Result (pass/fail) for a test case
   18. list_global_configurations  - List all global configs (streams/baselines) from GCM
   19. list_global_components      - List all components across DNG/EWM/ETM from GCM
   20. get_global_config_details   - Get details + contributions for a global configuration
   21. generate_chart              - Render a bar/hbar/pie/line chart as PNG (visualize ELM data)

  New (12 — OSLC + SCM/Reviews):
   22. get_attribute_definitions   - Discover DNG attribute predicates + allowed enum values
   23. update_requirement_attributes - Set arbitrary DNG attributes (Status, Priority, etc.)
   24. update_work_item            - PUT-with-If-Match arbitrary fields on an EWM WI
   25. transition_work_item        - Move WI through workflow via _action= query param
   26. query_work_items            - OSLC CM query (oslc.where / oslc.select)
   27. create_link                 - Generic OSLC link between two existing artifacts
   28. create_defect               - Create EWM Defect (auto-resolves filedAgainst category)
   29. scm_list_projects           - SCM service-providers from /ccm/oslc-scm/catalog
   30. scm_list_changesets         - Recent change-sets via TRS feed
   31. scm_get_changeset           - Single change-set + linked work items
   32. scm_get_workitem_changesets - Change-sets on a given WI
   33. review_get                  - Review-relevant WI fields (approvals, change-sets, etc.)
   34. review_list_open            - Open review-typed WIs in a project
"""

import os
import sys
import logging
import asyncio
from typing import Any, Optional, List, Dict

# MCP stdio servers must log to stderr, never stdout
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("doors-next")
from mcp.server import Server
from mcp.types import (
    Tool, TextContent,
    Resource, ResourceTemplate, BlobResourceContents, TextResourceContents,
    Prompt, PromptMessage, PromptArgument,
)
import mcp.server.stdio
from dotenv import load_dotenv
from doors_client import DOORSNextClient

load_dotenv()

# Bumped on each release. The auto-update logic below uses this to
# decide if a newer GitHub release exists; the `connect_to_elm`
# response also surfaces it so users always know what version they're
# running.
__version__ = "0.2.0"
GITHUB_REPO = "brettscharm/elm-mcp"

app = Server("doors-next-server")

# ── Auto-update on server startup ─────────────────────────────
# When Bob (or any MCP host) launches this server, we transparently
# check GitHub for a newer release at most once per 24 hours, pull it,
# and re-exec ourselves so the user always has the latest version
# without remembering any commands. Fails open: any network/git
# hiccup leaves the current version running.
#
# Throttle file: ~/.elm-mcp/.last-update-check (just a unix timestamp)
# Disable knob:  ELM_MCP_AUTO_UPDATE=0 in .env or the host's env

_AUTO_UPDATE_THROTTLE_SECONDS = 24 * 60 * 60  # once a day
_update_notice: Optional[str] = None  # set by _fetch_latest_version when a
                                       # newer version exists but we couldn't
                                       # auto-pull (e.g. not a git checkout)
_update_notice_shown: bool = False


def _project_dir() -> str:
    """The directory containing this script — that's the install dir
    we manage when we self-update."""
    return os.path.dirname(os.path.abspath(__file__))


def _is_git_managed() -> bool:
    """True if the install dir is a git checkout we can `git pull`."""
    return os.path.isdir(os.path.join(_project_dir(), ".git"))


def _last_check_path() -> str:
    return os.path.join(_project_dir(), ".last-update-check")


def _throttle_allows_check() -> bool:
    """Returns False if we checked GitHub within the throttle window."""
    try:
        import time as _t
        with open(_last_check_path()) as f:
            last = float(f.read().strip() or "0")
        return (_t.time() - last) >= _AUTO_UPDATE_THROTTLE_SECONDS
    except (OSError, ValueError):
        return True  # never checked, or file unreadable — go ahead


def _record_check_now() -> None:
    try:
        import time as _t
        with open(_last_check_path(), "w") as f:
            f.write(str(_t.time()))
    except OSError:
        pass


def _fetch_latest_version() -> Optional[str]:
    """Return the latest published version string, or None on failure."""
    try:
        import urllib.request, json as _json
        req = urllib.request.Request(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": f"elm-mcp/{__version__}"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        return (data.get("tag_name") or "").lstrip("v") or None
    except Exception:
        return None


def _git_pull() -> bool:
    """Hard-reset the install dir to origin/main. Returns True on success."""
    import subprocess
    try:
        subprocess.run(["git", "-C", _project_dir(), "fetch", "--quiet", "origin"],
                       check=True, timeout=15)
        subprocess.run(["git", "-C", _project_dir(), "reset", "--hard", "--quiet",
                        "origin/main"], check=True, timeout=10)
        return True
    except Exception:
        return False


def _re_exec() -> None:
    """Replace the current process with a fresh copy of this script so
    the new code takes over. Bob's stdio pipes stay attached because
    execv keeps the same fd table."""
    os.execvp(sys.executable, [sys.executable, os.path.abspath(__file__)])


def _auto_update_at_startup() -> None:
    """Called once near the top of the server, before MCP handshake.
    Transparently auto-updates the install if a newer release exists.
    Skips silently if disabled, throttled, offline, not a git checkout,
    or up-to-date."""
    global _update_notice
    if os.environ.get("ELM_MCP_AUTO_UPDATE", "1") == "0":
        return
    if not _throttle_allows_check():
        return
    latest = _fetch_latest_version()
    # Only record the check timestamp if the network call ACTUALLY
    # succeeded. Previously we recorded unconditionally — meaning a
    # transient network failure (or being offline at startup) would
    # block the next 24h of update checks. Now: failed checks don't
    # count, so the next start retries.
    if latest is None:
        sys.stderr.write(
            f"[elm-mcp] v{__version__}: update check failed (network/GitHub "
            f"unreachable). Will retry on next startup.\n"
        )
        sys.stderr.flush()
        return
    _record_check_now()
    if latest == __version__:
        sys.stderr.write(
            f"[elm-mcp] v{__version__}: up to date.\n"
        )
        sys.stderr.flush()
        return
    # A newer version exists. Try to pull + re-exec.
    if _is_git_managed() and _git_pull():
        # Log to stderr so it surfaces in Bob's MCP output panel; then
        # exec back into the new code. The re-exec happens before any
        # MCP traffic so Bob sees the new version's tools/list output.
        sys.stderr.write(
            f"[elm-mcp] auto-updated v{__version__} -> v{latest}; restarting\n"
        )
        sys.stderr.flush()
        _re_exec()
        # _re_exec only returns on failure
    # Couldn't auto-update (not a git checkout, e.g. installed via
    # Smithery as a frozen bundle). Surface a notice the next time
    # connect_to_elm runs so the user knows to update manually.
    sys.stderr.write(
        f"[elm-mcp] v{__version__}: v{latest} is available — "
        f"will surface notice on first tool call.\n"
    )
    sys.stderr.flush()
    _update_notice = (
        f"\n\n> 🔔 **ELM MCP v{latest} is available** (you're on v{__version__}). "
        f"To update: just say *\"update yourself\"* — that's a single tool "
        f"call (no per-step prompts). Or for a fresh-machine reinstall: "
        f"`curl -fsSL https://raw.githubusercontent.com/{GITHUB_REPO}/main/install.sh | bash`"
    )


def _preflight_version_block() -> str:
    """Quick GitHub version check used at the top of major orchestration
    tools (build_project, build_new_project, build_from_existing). The
    user asked for this — they want to know up-front whether they're
    running the latest before kicking off a long workflow.

    Returns a short markdown block to prepend to the response. Empty
    string if up to date or check fails (don't block on slow network)."""
    try:
        latest = _fetch_latest_version()
        if latest is None:
            # Network failed — don't punish the user, just continue silently.
            return ""
        if latest == __version__:
            return (
                f"> ✅ Running ELM MCP **v{__version__}** (latest).\n\n"
            )
        # Outdated — surface clearly with the one-tool update path.
        return (
            f"> ⚠️ **Update available:** you're on ELM MCP v{__version__}, "
            f"latest is **v{latest}**.\n>\n"
            f"> The build flow has gotten meaningful improvements between "
            f"versions. To update before continuing: just say "
            f"*\"update yourself\"* — that's ONE tool call, no per-step "
            f"prompts. Bob will pull v{latest} and tell you to restart.\n>\n"
            f"> Or proceed with v{__version__} now — your choice. "
            f"Either is fine; the warning won't repeat.\n\n"
        )
    except Exception:
        return ""


def _maybe_append_update_notice(text: str) -> str:
    """Append the update notice exactly once per session, on the first
    tool that calls this. Only fires when auto-update couldn't apply."""
    global _update_notice_shown
    if _update_notice_shown or not _update_notice:
        return text
    _update_notice_shown = True
    return text + _update_notice


# Run the update check now, before we register tools or open stdio.
_auto_update_at_startup()

# ── Session State ─────────────────────────────────────────────
_client: Optional[DOORSNextClient] = None
_projects_cache: List[Dict] = []              # DNG projects
_ewm_projects_cache: List[Dict] = []          # EWM projects
_etm_projects_cache: List[Dict] = []          # ETM projects
_modules_cache: Dict[str, List[Dict]] = {}    # project_id -> modules
_last_requirements: List[Dict] = []
_last_module_name: str = ""
_last_project_name: str = ""
_folder_cache: Dict[str, Dict] = {}           # folder_name -> {title, url}


_client_error: str = ""


# ── Build-project run state ───────────────────────────────────
# In-memory dict keyed by run_id. Each entry is the full state of one
# /build-project (or /build-new-project / /build-from-existing) run.
# Lives only as long as the MCP server process; if Bob restarts, state
# is lost and the user starts a new run. That's acceptable for v0.1.14;
# disk persistence can come later if needed.
#
# Schema:
#   {
#     "run_id": "<short uuid>",
#     "command": "build-new-project" | "build-from-existing",
#     "started_at": "<iso>",
#     "last_updated_at": "<iso>",
#     "current_phase": int,
#     "tier_mode": "single" | "tiered",
#     "project_idea": str,
#     "project_urls": {"dng": str, "ewm": str, "etm": str},
#     "approved_state_value": str,  # discovered at Phase 6 prep
#     "artifacts": {
#       "modules":      [{"url", "title", "created_at"}],
#       "requirements": [{"url", "title", "created_at", "modified_at"}],
#       "tasks":        [{"url", "title", "created_at", "modified_at"}],
#       "tests":        [{"url", "title", "created_at", "modified_at"}],
#       "child_workitems": [...]
#     },
#     "approval_signals": {<phase>: <verbatim user reply>},
#     "drift": null | {"unchanged": int, "modified": [...], "deleted": [...], "added_externally": [...]}
#   }
_RUNS: Dict[str, Dict] = {}


def _runs_dir() -> str:
    """Disk location for persisted run state. Created on first write."""
    home = os.path.expanduser("~")
    d = os.path.join(home, ".elm-mcp", "runs")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def _persist_run(run: Dict) -> None:
    """Write a run's current state to disk so it survives server
    restart. Best-effort — disk failures are logged but don't block
    the in-memory operation."""
    try:
        import json as _json
        path = os.path.join(_runs_dir(), f"{run['run_id']}.json")
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            _json.dump(run, f, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        sys.stderr.write(f"[elm-mcp] failed to persist run {run.get('run_id')}: {e}\n")


def _load_runs_from_disk() -> int:
    """Load any persisted runs into _RUNS at startup. Returns the
    number loaded. Silently skips unreadable / corrupt files."""
    import json as _json
    count = 0
    try:
        d = _runs_dir()
        if not os.path.isdir(d):
            return 0
        for name in os.listdir(d):
            if not name.endswith(".json"):
                continue
            path = os.path.join(d, name)
            try:
                with open(path) as f:
                    run = _json.load(f)
                rid = run.get("run_id")
                if rid:
                    _RUNS[rid] = run
                    count += 1
            except Exception:
                continue
    except OSError:
        pass
    return count


def _new_run(command: str, project_idea: str = "",
             tier_mode: str = "single", project_urls: Optional[Dict] = None) -> Dict:
    """Create a new build-project run and register it. Returns the new
    run dict (caller can mutate; changes persist in _RUNS by reference
    AND on disk via _persist_run)."""
    import uuid as _uuid
    import datetime as _dt
    run_id = _uuid.uuid4().hex[:10]
    now = _dt.datetime.utcnow().isoformat() + "Z"
    run = {
        "run_id": run_id,
        "command": command,
        "started_at": now,
        "last_updated_at": now,
        "current_phase": 0,
        "tier_mode": tier_mode,
        "project_idea": project_idea,
        "project_urls": project_urls or {},
        "approved_state_value": "",
        "artifacts": {
            "modules": [],
            "requirements": [],
            "tasks": [],
            "tests": [],
            "child_workitems": [],
        },
        "approval_signals": {},
        "drift": None,
        "dng_state_artifact_url": "",  # set if/when DNG-resident state is enabled
    }
    _RUNS[run_id] = run
    _persist_run(run)
    return run


def _get_run(run_id: str) -> Optional[Dict]:
    """Look up a run by id. Returns None if unknown."""
    return _RUNS.get(run_id) if run_id else None


def _touch_run(run: Dict) -> None:
    """Update last_updated_at on the run, then persist to disk."""
    import datetime as _dt
    run["last_updated_at"] = _dt.datetime.utcnow().isoformat() + "Z"
    _persist_run(run)


def _record_artifact_in_run(run: Dict, kind: str, url: str, title: str,
                             modified_at: str = "") -> None:
    """Append an artifact to the run's artifacts dict. kind is one of
    modules / requirements / tasks / tests / child_workitems."""
    import datetime as _dt
    if kind not in run["artifacts"]:
        run["artifacts"][kind] = []
    now = _dt.datetime.utcnow().isoformat() + "Z"
    run["artifacts"][kind].append({
        "url": url,
        "title": title,
        "created_at": now,
        "modified_at": modified_at or now,
    })
    _touch_run(run)


def _list_active_runs() -> List[Dict]:
    """Return a summary list of all active runs (for resume / status)."""
    return [
        {
            "run_id": r["run_id"],
            "command": r.get("command", "unknown"),
            "phase": r.get("current_phase", 0),
            "idea": r.get("project_idea", "")[:80],
            "started_at": r.get("started_at", ""),
            "last_updated_at": r.get("last_updated_at", ""),
        }
        for r in _RUNS.values()
    ]


def _render_run_as_markdown(run: Dict) -> str:
    """Render a run's state as a human-readable markdown document.
    Used for the DNG-resident state artifact body and (optionally) for
    user-facing summaries. The body is recognizable to humans browsing
    DNG, and machine-parseable enough that a teammate's Bob session can
    re-fetch it and reconstruct what was built."""
    arts = run.get("artifacts", {}) or {}
    lines = [
        f"# Build State: {run.get('project_idea', '?')}",
        "",
        f"**Run ID:** `{run.get('run_id', '?')}`",
        f"**Command:** {run.get('command', 'unknown')}",
        f"**Current phase:** {run.get('current_phase', 0)}",
        f"**Tier mode:** {run.get('tier_mode', 'single')}",
        f"**Started:** {run.get('started_at', '')}",
        f"**Last updated:** {run.get('last_updated_at', '')}",
        "",
        "## Project URLs",
    ]
    urls = run.get("project_urls", {}) or {}
    for k in ("dng", "ewm", "etm"):
        v = urls.get(k, "")
        lines.append(f"- {k.upper()}: {v if v else '_(not set)_'}")

    lines.append("")
    lines.append("## Artifacts created")
    for kind in ("modules", "requirements", "tasks", "tests", "child_workitems"):
        items = arts.get(kind, []) or []
        if not items:
            continue
        lines.append(f"### {kind} ({len(items)})")
        for it in items:
            lines.append(f"- [{it.get('title', '?')}]({it.get('url', '')})")

    sigs = run.get("approval_signals", {}) or {}
    if sigs:
        lines.append("")
        lines.append("## Approval signals received per phase")
        for ph in sorted(sigs.keys(), key=lambda x: float(x)):
            lines.append(f"- Phase {ph}: \"{sigs[ph]}\"")

    drift = run.get("drift")
    if drift:
        lines.append("")
        lines.append("## Drift detected at Phase 6")
        lines.append(f"- unchanged: {drift.get('unchanged', 0)}")
        lines.append(f"- modified: {drift.get('modified', [])}")
        lines.append(f"- deleted: {drift.get('deleted', [])}")
        lines.append(f"- added externally: {drift.get('added_externally', [])}")

    return "\n".join(lines)


# Load any persisted runs at module import time (after the helpers are
# defined). Quiet on first-run (empty dir).
_loaded_run_count = _load_runs_from_disk()
if _loaded_run_count > 0:
    sys.stderr.write(f"[elm-mcp] loaded {_loaded_run_count} run(s) from disk\n")


def _get_or_create_client() -> Optional[DOORSNextClient]:
    """Get existing client or try to create one from .env.

    Sets _client_error with the reason if connection fails.
    """
    global _client, _client_error
    if _client is not None:
        return _client

    # Read ELM_* (preferred) with DOORS_* fallback for legacy installs.
    base_url = os.getenv("ELM_URL") or os.getenv("DOORS_URL")
    username = os.getenv("ELM_USERNAME") or os.getenv("DOORS_USERNAME")
    password = os.getenv("ELM_PASSWORD") or os.getenv("DOORS_PASSWORD")

    if not all([base_url, username, password]):
        missing = []
        if not base_url:
            missing.append("ELM_URL")
        if not username:
            missing.append("ELM_USERNAME")
        if not password:
            missing.append("ELM_PASSWORD")
        _client_error = f"Missing .env variables: {', '.join(missing)}"
        return None

    # The client itself normalizes the URL (strips /rm, /ccm, /qm, /gc, /jts
    # variants and re-attaches per-domain paths). Don't mangle it here.
    client = DOORSNextClient(base_url.strip(), username, password)
    auth_result = client.authenticate()
    if auth_result['success']:
        _client = client
        _client_error = ""
        return _client

    _client_error = auth_result['error']
    logger.warning("Auto-connect from .env failed: %s", _client_error)
    return None


def _find_by_identifier(items: List[Dict], identifier: str, key: str = 'title') -> Optional[Dict]:
    """Find item by 1-based index number or case-insensitive partial name match"""
    # Try as number first
    try:
        idx = int(identifier) - 1
        if 0 <= idx < len(items):
            return items[idx]
    except ValueError:
        pass

    # Partial name match (case-insensitive)
    lower = identifier.lower()
    for item in items:
        if lower in item.get(key, '').lower():
            return item

    return None


# ── Prompts ───────────────────────────────────────────────────

@app.list_prompts()
async def list_prompts() -> list[Prompt]:
    return [
        Prompt(
            name="generate-requirements",
            description=(
                "Generate IEEE 29148-compliant requirements for a system or feature. "
                "Walks through a structured interview, generates requirements with "
                "measurable acceptance criteria, and pushes to DNG."
            ),
            arguments=[
                PromptArgument(
                    name="system_description",
                    description="What system or feature are these requirements for?",
                    required=True,
                ),
                PromptArgument(
                    name="requirement_type",
                    description="Type of requirements: stakeholder, system, software, hardware, security, performance",
                    required=False,
                ),
                PromptArgument(
                    name="standards",
                    description="Applicable standards or regulations (e.g., DO-178C, ISO 26262, MIL-STD-882)",
                    required=False,
                ),
                PromptArgument(
                    name="count",
                    description="How many requirements: 'few' (5-10) or 'comprehensive' (20+)",
                    required=False,
                ),
            ],
        ),
        Prompt(
            name="full-lifecycle",
            description=(
                "Create a complete lifecycle: Requirements in DNG -> Tasks in EWM -> "
                "Test Cases in ETM, all cross-linked for full traceability."
            ),
            arguments=[
                PromptArgument(
                    name="system_description",
                    description="What system or feature to build the lifecycle for?",
                    required=True,
                ),
                PromptArgument(
                    name="dng_project",
                    description="DNG project name or number for requirements",
                    required=False,
                ),
                PromptArgument(
                    name="ewm_project",
                    description="EWM project name or number for tasks",
                    required=False,
                ),
                PromptArgument(
                    name="etm_project",
                    description="ETM project name or number for test cases",
                    required=False,
                ),
            ],
        ),
        Prompt(
            name="import-pdf",
            description=(
                "Import a PDF document into DNG as structured requirements. "
                "Extracts text, parses into requirements, previews, and pushes to DNG. "
                "Supports re-import with diff detection for updated PDFs."
            ),
            arguments=[
                PromptArgument(
                    name="file_path",
                    description="Absolute path to the PDF file",
                    required=True,
                ),
                PromptArgument(
                    name="project",
                    description="DNG project name or number",
                    required=False,
                ),
            ],
        ),
        Prompt(
            name="import-requirements",
            description=(
                "Brownfield import — user pastes existing requirements (Jira "
                "epic body, Notion doc, Word content, bullet list, anything), "
                "AI parses into atomic shall-statements + NFRs, separates "
                "acceptance criteria for ETM later, skips non-requirement "
                "content (business goals / risks / assumptions / DoD), shows "
                "a preview, and on approval creates a DNG module with all "
                "requirements auto-bound. Returns direct DNG links so "
                "ELM-savvy users can dive in normally. Zero retyping — paste "
                "and ship."
            ),
            arguments=[
                PromptArgument(
                    name="content",
                    description="The requirements text to parse and import. Paste a Jira epic body, Notion doc, Word content, markdown, plain bullets — anything textual. Optional; AI will ask if not provided.",
                    required=False,
                ),
                PromptArgument(
                    name="module_name",
                    description="What to call the new DNG module. Optional — AI will suggest a name based on the content if not provided.",
                    required=False,
                ),
                PromptArgument(
                    name="project",
                    description="DNG project name or number where the module should be created. Optional — AI will ask if not provided.",
                    required=False,
                ),
                PromptArgument(
                    name="source_hint",
                    description="Hint about the format/source: 'jira', 'notion', 'word', 'markdown', 'bullets', 'prose'. Optional — AI auto-detects.",
                    required=False,
                ),
            ],
        ),
        Prompt(
            name="import-work-item",
            description=(
                "Brownfield work-item import — user provides a PDF (Jira epic "
                "export, Azure DevOps work item, etc.) and AI parses the "
                "complete work-item graph into ELM: an EWM work item for the "
                "main item, DNG requirements for the functional/NFR sections, "
                "ETM test cases for the acceptance criteria, EWM child stories "
                "for linked sub-items, and proper cross-tool links between "
                "all of them. Performs gap detection (vague NFRs, untestable "
                "ACs, missing fields) and surfaces decision points (work item "
                "type — picked from the project's actual list, NEVER guessed). "
                "Composes naturally with /build-project for code generation "
                "after import."
            ),
            arguments=[
                PromptArgument(
                    name="pdf_path",
                    description="Absolute path to the work-item PDF (Jira epic export, ADO work item, etc.). Optional; AI will ask if not provided.",
                    required=False,
                ),
                PromptArgument(
                    name="dng_project",
                    description="DNG project for the requirements module. Optional — AI will use connected project or ask.",
                    required=False,
                ),
                PromptArgument(
                    name="ewm_project",
                    description="EWM project for the work item + child stories. Optional — AI will ask if not provided.",
                    required=False,
                ),
                PromptArgument(
                    name="etm_project",
                    description="ETM project for the test cases (from acceptance criteria). Optional — AI will ask if not provided.",
                    required=False,
                ),
                PromptArgument(
                    name="source_hint",
                    description="Hint about the source format: 'jira', 'azure-devops', 'servicenow', 'aha', 'linear', 'github'. Optional — AI auto-detects.",
                    required=False,
                ),
            ],
        ),
        Prompt(
            name="build-project",
            description=(
                "Legacy alias for /build-new-project (greenfield flow). Kept for "
                "backward compatibility. Prefer /build-new-project (greenfield) "
                "or /build-from-existing (brownfield) explicitly."
            ),
            arguments=[
                PromptArgument(name="project_idea", description="One-line description of what to build.", required=True),
                PromptArgument(name="dng_project", description="DNG project name. Optional.", required=False),
                PromptArgument(name="ewm_project", description="EWM project name. Optional.", required=False),
                PromptArgument(name="etm_project", description="ETM project name. Optional.", required=False),
                PromptArgument(name="tier_mode", description="'single' or 'tiered'. Default 'single'.", required=False),
            ],
        ),
        Prompt(
            name="build-new-project",
            description=(
                "Greenfield agentic build — start from a one-line idea, generate "
                "fresh requirements/tasks/tests, write code, with phase-gated "
                "user approvals. Use this when there's NO existing material to "
                "import. Returns a run_id used by build_project_next, "
                "build_project_status, and generate_traceability_matrix to "
                "persist phase context (artifact URLs, tier_mode, drift state)."
            ),
            arguments=[
                PromptArgument(name="project_idea", description="One-line description of what to build (e.g. 'a temperature converter web app').", required=True),
                PromptArgument(name="dng_project", description="DNG project name. Optional — AI will ask.", required=False),
                PromptArgument(name="ewm_project", description="EWM project name. Optional.", required=False),
                PromptArgument(name="etm_project", description="ETM project name. Optional.", required=False),
                PromptArgument(name="tier_mode", description="'single' (one System Requirements module) or 'tiered' (Business→Stakeholder→System).", required=False),
            ],
        ),
        Prompt(
            name="build-from-existing",
            description=(
                "Brownfield agentic build — start from existing material (a "
                "Jira/work-item PDF, pasted requirements, an existing DNG "
                "module URL) and continue from there. Phase 1 asks WHAT the "
                "user has and routes to /import-work-item or /import-requirements "
                "or just reads an existing module. Then converges with the "
                "standard flow at Phase 5 (user review). Returns a run_id."
            ),
            arguments=[
                PromptArgument(name="source_kind", description="'pdf' (work-item PDF), 'text' (paste), 'module' (existing DNG module URL), 'mixed', or '' (ask user).", required=False),
                PromptArgument(name="source_path", description="PDF path or DNG module URL. Optional — AI will ask.", required=False),
                PromptArgument(name="project_idea", description="Short summary. Optional — AI derives from source.", required=False),
                PromptArgument(name="dng_project", description="DNG project name. Optional.", required=False),
                PromptArgument(name="ewm_project", description="EWM project name. Optional.", required=False),
                PromptArgument(name="etm_project", description="ETM project name. Optional.", required=False),
                PromptArgument(name="tier_mode", description="'single' or 'tiered'. Default 'single'.", required=False),
            ],
        ),
        Prompt(
            name="review-requirements",
            description=(
                "Read requirements from a DNG module and review them for quality: "
                "checks for ambiguity, missing acceptance criteria, testability, "
                "and IEEE 29148 compliance."
            ),
            arguments=[
                PromptArgument(
                    name="project",
                    description="DNG project name or number",
                    required=True,
                ),
                PromptArgument(
                    name="module",
                    description="Module name or number to review",
                    required=True,
                ),
            ],
        ),
    ]


@app.get_prompt()
async def get_prompt(name: str, arguments: dict | None = None) -> list[PromptMessage]:
    args = arguments or {}

    if name == "generate-requirements":
        system_desc = args.get("system_description", "")
        req_type = args.get("requirement_type", "system")
        standards = args.get("standards", "")
        count = args.get("count", "10-15")

        standards_note = f"\n\nApplicable standards: {standards}. Include compliance references in each requirement." if standards else ""

        return [PromptMessage(
            role="user",
            content=TextContent(type="text", text=(
                f"Generate {req_type} requirements for the following system:\n\n"
                f"{system_desc}\n\n"
                f"Target count: {count} requirements.{standards_note}\n\n"
                f"Follow IEEE 29148 / INCOSE best practices:\n"
                f"- Use 'shall' for mandatory behavior\n"
                f"- Each requirement must be atomic and testable\n"
                f"- Include measurable acceptance criteria (numeric thresholds, time limits)\n"
                f"- Group under Heading artifacts by functional area\n"
                f"- Specify condition -> action -> expected result\n\n"
                f"First connect to ELM (if not connected), then:\n"
                f"1. Call get_artifact_types to get valid type names\n"
                f"2. Generate the requirements following the rules above\n"
                f"3. Present in a preview table with Type, Title, and Acceptance Criteria columns\n"
                f"4. Wait for my approval before pushing to DNG"
            )),
        )]

    elif name == "full-lifecycle":
        system_desc = args.get("system_description", "")
        dng = args.get("dng_project", "")
        ewm = args.get("ewm_project", "")
        etm = args.get("etm_project", "")

        project_notes = ""
        if dng:
            project_notes += f"\nDNG project: {dng}"
        if ewm:
            project_notes += f"\nEWM project: {ewm}"
        if etm:
            project_notes += f"\nETM project: {etm}"

        return [PromptMessage(
            role="user",
            content=TextContent(type="text", text=(
                f"Create a full engineering lifecycle for:\n\n{system_desc}\n"
                f"{project_notes}\n\n"
                f"Phase 1: Generate requirements in DNG (IEEE 29148 compliant, with acceptance criteria)\n"
                f"Phase 2: Create implementation tasks in EWM linked to requirements\n"
                f"Phase 3: Create test cases in ETM linked to requirements (with preconditions, steps, pass/fail criteria)\n\n"
                f"At each phase:\n"
                f"- Preview what will be created in a table\n"
                f"- Wait for my approval before pushing\n"
                f"- Use the requirement URLs from Phase 1 for cross-linking in Phases 2 and 3"
            )),
        )]

    elif name == "import-pdf":
        file_path = args.get("file_path", "")
        project = args.get("project", "")

        return [PromptMessage(
            role="user",
            content=TextContent(type="text", text=(
                f"Import this PDF into DNG as structured requirements:\n\n"
                f"File: {file_path}\n"
                f"{'Project: ' + project if project else 'Ask me which project to use.'}\n\n"
                f"Steps:\n"
                f"1. Call extract_pdf to get the text\n"
                f"2. Parse into structured requirements (identify headings, sections, individual requirements)\n"
                f"3. Call get_artifact_types to get valid type names\n"
                f"4. Present in a preview table\n"
                f"5. Wait for my approval before pushing to DNG\n"
                f"6. After creation, offer to create a baseline snapshot"
            )),
        )]

    elif name == "import-requirements":
        content = args.get("content", "")
        module_name = args.get("module_name", "")
        project = args.get("project", "")
        source_hint = args.get("source_hint", "")

        intro = (
            "The user wants to import existing requirements they already wrote "
            "elsewhere (Jira epic, Notion doc, Word content, bullet list, "
            "markdown, copied PDF text, etc.) into DNG as a structured module. "
            "This is the BROWNFIELD path — they aren't asking you to write new "
            "reqs, they're asking you to STRUCTURE what they already have.\n\n"
        )

        if content:
            content_block = (
                f"--- USER'S PASTED CONTENT ---\n{content}\n--- END ---\n\n"
            )
        else:
            content_block = (
                "The user hasn't pasted content yet. Your first message should "
                "be a short prompt: *\"Paste your requirements — Jira epic body, "
                "Notion doc, Word content, plain bullets, anything textual. I'll "
                "parse and structure it for DNG.\"* Then wait for the paste.\n\n"
            )

        hint_block = (
            f"Source hint from user: '{source_hint}'. Use this to inform parsing "
            f"(e.g. 'jira' implies Atlassian markdown + epic structure; 'word' "
            f"implies prose paragraphs; 'bullets' implies pre-structured items).\n\n"
        ) if source_hint else ""

        target_block = ""
        if project:
            target_block += f"Target DNG project: '{project}' (use this; don't ask).\n"
        else:
            target_block += (
                "Target DNG project: not specified. Use the currently-connected "
                "project if there's one obvious; otherwise ask which project. "
                "Don't `list_projects` unless the user is unsure.\n"
            )
        if module_name:
            target_block += f"Target module name: '{module_name}' (use this; don't ask).\n\n"
        else:
            target_block += (
                "Target module name: not specified. Suggest one based on the "
                "content's subject — e.g. if the paste is about a tracking "
                "service, suggest 'ETS Tracking - System Requirements'. Make "
                "the suggestion concrete and ask the user to confirm or edit.\n\n"
            )

        instructions = (
            "## How to parse the pasted content\n\n"
            "Walk through the text and bucket everything into one of FIVE "
            "categories. Be strict — don't put things in the wrong bucket "
            "just to inflate the count.\n\n"
            "### 1. Functional Requirements\n"
            "Statements of WHAT the system does. Convert each to a single "
            "atomic 'shall' statement. Examples:\n"
            "  • 'Ingest FarEye payloads from ASB' → 'The system shall ingest "
            "    FarEye tracking payloads from Azure Service Bus Topic + "
            "    Subscription.'\n"
            "  • 'Mask PII in API responses' → 'The system shall mask PII "
            "    fields (receivedBy, driverName, POD URLs) in all public API "
            "    response payloads.'\n"
            "Don't merge two statements into one req. Don't fluff one idea "
            "into two reqs.\n\n"
            "### 2. Non-Functional Requirements\n"
            "Performance, reliability, security, observability, retention, "
            "concurrency, etc. Examples: 'p95 < 200ms cached', 'append-only "
            "history', 'idempotent processing', '7-year retention'. Same atomic "
            "'shall' shape, but tagged as NFR.\n\n"
            "### 3. Acceptance Criteria  →  HOLD for ETM\n"
            "Numbered AC lists, 'given/when/then', 'X is implemented', or any "
            "test-shaped condition. These DO NOT belong in DNG as requirements. "
            "Capture them and tell the user *\"I'll put these in test cases "
            "later if you create test cases for this module.\"* Don't push them "
            "as requirements no matter how the input formats them.\n\n"
            "### 4. Constraints / Assumptions / Risks  →  optionally separate\n"
            "If the input has Risks / Dependencies / Assumptions sections, ask "
            "the user once if they want those captured as separate artifacts "
            "(typically a different shape — Constraint, Risk, Assumption). "
            "Default behavior: SKIP them and tell the user they were skipped.\n\n"
            "### 5. Skip entirely\n"
            "Business Goal, Business Value, In/Out of Scope, Definition of "
            "Done, Epic Components, project descriptions, comments, change "
            "logs, header/footer metadata. These aren't requirements; they're "
            "project metadata. Note them as 'Skipped' in the preview so the "
            "user knows you saw them and made a decision.\n\n"
            "## The preview\n\n"
            "Before pushing anything, show the user a structured preview:\n\n"
            "```\n"
            "Parsed your input:\n\n"
            "  Functional Requirements (N)\n"
            "    1. <full text of req 1>\n"
            "    2. <full text of req 2>\n"
            "    ... all listed\n\n"
            "  Non-Functional Requirements (M)\n"
            "    1. ...\n\n"
            "  Acceptance Criteria (K) — held for ETM if you create test cases\n"
            "    1. ...\n\n"
            "  Skipped (J items, project metadata not requirement-shaped)\n"
            "    - Business Goal, Business Value\n"
            "    - Risks, Dependencies, Assumptions  (say 'yes' to capture as separate artifacts)\n"
            "    - Definition of Done\n"
            "    ... etc\n\n"
            "  Target: New module '<suggested or specified name>' in <project>\n\n"
            "Edits before I push? Or 'looks good' to ship.\n"
            "```\n\n"
            "## Wait for explicit approval\n\n"
            "Don't push until the user says 'yes' / 'looks good' / 'ship it' / "
            "'push' or similar verbatim approval. If they ask for edits, apply "
            "them and re-preview. Same write-gate pattern as every other tool.\n\n"
            "## On approval\n\n"
            "Call `create_requirements` ONCE with:\n"
            "  • project_url (the connected/specified DNG project)\n"
            "  • module_name=<the agreed name>  (this auto-creates the module "
            "    AND auto-binds every requirement to it — no separate "
            "    create_module call needed)\n"
            "  • requirements=[ ... ] with one entry per parsed requirement, "
            "    each containing title (short summary) + content (the full "
            "    'shall' statement) + appropriate type (functional / NFR / "
            "    constraint based on which bucket it landed in)\n\n"
            "## After the push\n\n"
            "Surface direct links — the module URL plus every requirement URL "
            "as markdown links. Engineers who know DNG will click in to verify; "
            "engineers who don't can ignore the links. Both audiences served.\n\n"
            "Then offer the natural next steps:\n"
            "  • *\"Want me to create EWM tasks for these requirements? "
            "    (one task per req, linked via implementsRequirement)\"*\n"
            "  • *\"Want me to create ETM test cases? "
            "    (I'll use the held acceptance criteria + generate any missing "
            "    ones, all linked back to the reqs)\"*\n"
            "  • *\"Want a baseline snapshot of the module right now?\"* (if "
            "    the project has configuration management enabled)\n\n"
            "## What this prompt is NOT\n\n"
            "  • Not for generating reqs from scratch — that's "
            "    /generate-requirements\n"
            "  • Not for importing PDFs — that's /import-pdf (which extracts "
            "    text first, then could chain into here)\n"
            "  • Not for the full /build-project flow — though /build-project "
            "    Phase 1 path (b) reuses this same parsing logic when the "
            "    user says they have existing reqs"
        )

        return [PromptMessage(
            role="user",
            content=TextContent(type="text", text=(
                intro + content_block + hint_block + target_block + instructions
            )),
        )]

    elif name == "import-work-item":
        pdf_path = args.get("pdf_path", "")
        dng_proj = args.get("dng_project", "")
        ewm_proj = args.get("ewm_project", "")
        etm_proj = args.get("etm_project", "")
        source_hint = args.get("source_hint", "")

        intro = (
            "The user wants to import a complete work-item graph (epic + "
            "stories + reqs + tests + cross-links) from a PDF into ELM. "
            "This is the BROWNFIELD-COMPLETE path — multi-artifact, "
            "multi-tool. The PDF is typically a Jira epic export, an "
            "Azure DevOps work item, or similar. You preserve the user's "
            "wording wherever possible — you structure, don't rewrite.\n\n"
        )

        if pdf_path:
            input_block = (
                f"PDF to import: {pdf_path}\n\n"
                f"Step 1: call `extract_pdf` with this path. You'll get the "
                f"full text including title, metadata, sections, comments. "
                f"Don't ask the user — just extract.\n\n"
            )
        else:
            input_block = (
                "The user hasn't provided a PDF path yet. Ask them once: "
                "*\"Drop the absolute path to the work-item PDF — Jira epic "
                "export, Azure DevOps work item, anything similar.\"* Wait "
                "for the path, then call `extract_pdf`.\n\n"
            )

        hint_block = (
            f"Source hint from user: '{source_hint}'. Adjust parsing for "
            f"that format's conventions (Jira PDFs have header metadata + "
            f"a Description block; ADO work items have different layout; "
            f"etc.).\n\n"
        ) if source_hint else ""

        target_block = (
            "## Target projects\n\n"
        )
        target_block += (
            f"DNG project: '{dng_proj}'\n" if dng_proj
            else "DNG project: not specified — use connected project or ask.\n"
        )
        target_block += (
            f"EWM project: '{ewm_proj}'\n" if ewm_proj
            else "EWM project: not specified — ask which one.\n"
        )
        target_block += (
            f"ETM project: '{etm_proj}'\n\n" if etm_proj
            else "ETM project: not specified — ask which one.\n\n"
        )

        instructions = (
            "## How to parse the work-item PDF\n\n"
            "After extraction, walk through the text and identify EVERY "
            "category. Produce a structured plan, not a single artifact:\n\n"
            "### A. The MAIN work item (1)\n"
            "Look for the work-item title, ID (e.g. 'OMS-28894'), type "
            "label ('Type: Epic'), description, status, labels, priority, "
            "assignee, dates, fix version, components. Preserve the ID in "
            "the EWM artifact title or as a custom attribute so the trace "
            "back to the source is obvious.\n\n"
            "### B. Functional Requirements (atomic 'shall' statements)\n"
            "Look in 'Functional Requirements' / 'Key Functional "
            "Requirements' / similar sections. Convert each to atomic "
            "shall-statements. Preserve the user's wording — only split "
            "when an item bundles multiple requirements.\n\n"
            "### C. Non-Functional Requirements\n"
            "Performance, reliability, security, observability, retention, "
            "concurrency, etc. Same atomic shape, tagged as NFR.\n\n"
            "### D. Acceptance Criteria — for ETM, NOT for DNG\n"
            "Numbered AC lists or 'Definition of Done' items that read "
            "like test conditions. Each becomes a test case in ETM, "
            "linked to the relevant requirement(s). DO NOT push as DNG "
            "requirements.\n\n"
            "### E. Linked work items (children, sub-tasks, related)\n"
            "Section often called 'Links' / 'Sub-tasks' / 'Implements' / "
            "'Relates to'. Each becomes a separate EWM work item linked "
            "to the main one. Title-only is fine if no body text is "
            "available — that's a 'completeness gap' to surface (see "
            "below).\n\n"
            "### F. Skipped (project metadata)\n"
            "Business Goal, Business Value, In/Out of Scope, Risks, "
            "Dependencies, Assumptions, Definition of Done sections that "
            "aren't AC-shaped. Note them as 'Skipped' so the user sees "
            "you noticed.\n\n"
            "## Type resolution — list-driven, never guess\n\n"
            "After parsing, before previewing:\n"
            "1. Read the type from the PDF (e.g. 'Type: Epic')\n"
            "2. Call `get_ewm_workitem_types` for the target EWM project. "
            "You'll get the actual list (e.g. Capability, Defect, "
            "Portfolio Epic, Solution Epic, Task, etc.)\n"
            "3. Match the PDF type to the project's list:\n"
            "   - **Exact match** (case-insensitive): use it silently, "
            "mention as default in preview\n"
            "   - **No match**: SHOW THE USER THE ACTUAL LIST, let them "
            "pick. Don't ask 'is this an epic or story' — show their "
            "project's real types\n"
            "   - **Ambiguous** (multiple plausible matches): show list, "
            "let them pick\n\n"
            "Same principle applies to status (default 'New' or whatever "
            "the project's initial state is) and severity (don't ask "
            "unless creating a Defect-typed item that requires it).\n\n"
            "## Gap detection — surface before pushing\n\n"
            "Before showing the preview, audit the parsed artifacts for "
            "five categories of gaps:\n\n"
            "1. **Quality gaps** (actionable): vague NFRs without "
            "measurable criteria, ACs without verifiable conditions, "
            "risks without severity ranking, etc.\n"
            "2. **Mapping gaps** (mostly informational): fields like "
            "'Fix Version' that don't have an EWM equivalent (note as "
            "'will skip')\n"
            "3. **Reference gaps** (informational only): external systems "
            "/ repos / tools mentioned in the body — preserved as text, "
            "not enforced\n"
            "4. **Completeness gaps** (decision needed): linked sub-tasks "
            "referenced but with no body in this PDF — create as "
            "title-only placeholders or skip?\n"
            "5. **Decisions** (only when something is genuinely "
            "ambiguous — the type-list-pick from above is one of these)\n\n"
            "**Critical:** assignee mappings are NOT a gap. Original Jira "
            "assignee names are preserved in artifact text where they "
            "appear naturally (description, comments). The EWM assignee "
            "field defaults to UNSET — never try to match Jira usernames "
            "to EWM users. Mention as informational, never ask.\n\n"
            "## The preview\n\n"
            "Show a comprehensive preview before pushing anything:\n\n"
            "```\n"
            "Plan: import OMS-28894 into ELM\n\n"
            "  EWM (1 main + N children)\n"
            "    Main: 'OMS-28894: <title>' (Type: Epic — exact match in project)\n"
            "    Children:\n"
            "      - <child 1 title> (Story)\n"
            "      - ...\n\n"
            "  DNG (X reqs in new module '<suggested name>')\n"
            "    Functional Requirements (Y) — full list\n"
            "    Non-Functional Requirements (Z) — full list\n\n"
            "  ETM (W test cases) — from acceptance criteria\n"
            "    Each linked to the relevant requirement(s)\n\n"
            "  Cross-links (N total): list them\n\n"
            "  Skipped (project metadata): Business Goal, Risks, etc.\n\n"
            "  Gaps to address:\n"
            "    QUALITY (Q): vague reqs / untestable ACs\n"
            "    COMPLETENESS (C): placeholder children — create title-only?\n\n"
            "  Defaults I'll use (informational):\n"
            "    Type: Epic / Status: New / Assignee: unset\n"
            "    (Other available types in your EWM project: ...)\n\n"
            "  Address gaps + decisions, or 'push with defaults'.\n"
            "```\n\n"
            "## Wait for explicit approval — same gate pattern\n\n"
            "Don't push until the user says 'yes' / 'looks good' / 'ship it' / "
            "'push with defaults'. Three escape hatches:\n"
            "  - **Address each**: user answers the gaps individually\n"
            "  - **Push with defaults**: AI picks reasonable answer for "
            "every open question, surfaces every choice in the post-push "
            "report\n"
            "  - **Ignore the gaps**: just push, skip the quality items "
            "and placeholder children\n\n"
            "## Push order matters\n\n"
            "Create artifacts in dependency order so the cross-links "
            "succeed:\n"
            "  1. EWM main work item (no inbound links yet)\n"
            "  2. DNG requirements via `create_requirements` with "
            "`module_name=<chosen>` (auto-creates module + binds reqs)\n"
            "  3. EWM child work items via `create_task`/`create_defect`/"
            "etc. with `requirement_url=<main work item URL>` if they "
            "logically implement parts of the main item\n"
            "  4. ETM test cases via `create_test_case` with "
            "`requirement_url=<the relevant DNG req URL>` — back-link is "
            "now automatic (v0.1.12 fix)\n\n"
            "Each `create_*` call writes its forward link AND the inverse "
            "back-link onto the requirement (since v0.1.12), so the trace "
            "web is complete in both directions without extra calls.\n\n"
            "## After the push — the post-push report\n\n"
            "Show every URL as a markdown link, plus every default-choice "
            "you made during 'push with defaults':\n"
            "  - 'Type: Epic (matched from PDF)'\n"
            "  - 'Status: New (default for this project)'\n"
            "  - 'Assignee: unset (originally <Jira name> — set manually "
            "if needed)'\n"
            "  - 'Placeholder children created (titles only, no body)'\n"
            "  - 'Quality issues flagged on these reqs: REQ-7 (vague NFR), "
            "AC-9 (untestable as written)'\n\n"
            "Then offer the natural next step:\n"
            "  *\"Want me to /build-project from this state? I'd skip "
            "Phases 1–4 (artifacts already created), pick up at Phase 5 "
            "(your review in ELM), then re-pull current state and write "
            "the actual code.\"*\n\n"
            "## What this prompt is NOT\n\n"
            "  - Not for plain-text requirement paste — that's "
            "/import-requirements (single-artifact-type)\n"
            "  - Not for code generation — composes with /build-project "
            "afterward\n"
            "  - Not for non-PDF sources — those are out of scope for "
            "v0.1.13 (Notion exports, ADO API, etc. could be added later)"
        )

        return [PromptMessage(
            role="user",
            content=TextContent(type="text", text=(
                intro + input_block + hint_block + target_block + instructions
            )),
        )]

    elif name == "build-project":
        idea = args.get("project_idea", "")
        dng = args.get("dng_project", "")
        ewm = args.get("ewm_project", "")
        etm = args.get("etm_project", "")
        tier_mode = (args.get("tier_mode", "") or "single").lower()
        proj_lines = []
        if dng: proj_lines.append(f"DNG project: {dng}")
        if ewm: proj_lines.append(f"EWM project: {ewm}")
        if etm: proj_lines.append(f"ETM project: {etm}")
        proj_block = "\n".join(proj_lines) if proj_lines else "Ask me which projects to use for each domain if not obvious."

        return [PromptMessage(
            role="user",
            content=TextContent(type="text", text=(
                f"# Build a project end-to-end with ELM as the system of record\n\n"
                f"**Project idea:** {idea}\n\n"
                f"{proj_block}\n\n"
                f"**Tier mode:** {tier_mode} "
                f"({'Business → Stakeholder → System in 3 modules with Satisfies links' if tier_mode == 'tiered' else 'one System Requirements module'})\n\n"
                f"You are the agent driving an end-to-end agentic-development "
                f"workflow. The full sequence is below. **Each phase has an "
                f"explicit user-approval gate. Never skip a gate. Never push "
                f"without preview. Surface every artifact URL as a clickable "
                f"markdown link — never paraphrase to a /rm landing page.**\n\n"
                f"---\n\n"
                f"## PHASE 0 — Verify connection and project access\n"
                f"Call `connect_to_elm` (if not connected). Confirm with me which "
                f"DNG / EWM / ETM projects to use; offer `list_projects` if I "
                f"don't know.\n\n"
                f"## PHASE 1 — Project intake (interview)\n"
                f"Confirm the project idea by asking 4–6 quick questions:\n"
                f"- What's the user-facing description (one paragraph)?\n"
                f"- Tech stack / platform constraints (web app? embedded? service?)\n"
                f"- Standards or compliance (DO-178C, ISO 26262, NIST, none, etc.)\n"
                f"- Approximate scale (5–10 reqs / 20+ reqs / massive)\n"
                f"- Integrations or external interfaces?\n"
                f"- Anything specific I MUST or MUST NOT include?\n\n"
                f"Confirm a one-line scope summary back to me before moving on.\n\n"
                f"## PHASE 2 — Requirements (DNG)\n"
                f"Run **Step 3b** (single-tier) or **Step 3g** (tiered) per the "
                f"`tier_mode` argument above. For each tier in tiered mode:\n"
                f"  • Generate requirements internally\n"
                f"  • Show a preview table grouped by proposed module with "
                f"rationale per group\n"
                f"  • Wait for my explicit 'yes' / 'go ahead'\n"
                f"  • Push via `create_requirements` with `module_name` set "
                f"(auto-binds to the module)\n"
                f"  • Surface direct module + requirement URLs as markdown links\n\n"
                f"**Server-side validation will reject** requirement bodies "
                f"containing 'Acceptance Criteria', 'Business Value', "
                f"'Stakeholder Need', 'Test Steps', etc. — those go in test "
                f"cases (or in a separate StR/BR tier). Each requirement body "
                f"must be a clean 'shall' statement with optional 'Rationale:' "
                f"line.\n\n"
                f"## PHASE 3 — Implementation tasks (EWM)\n"
                f"Run **Step 3d**. Once Phase 2 is approved + pushed, generate "
                f"one EWM Task per System Requirement (the lowest tier). "
                f"Verb-first titles. Brief body — no copy of the requirement "
                f"text (it's linked). Preview → my approval → push with "
                f"`requirement_url` for every task.\n\n"
                f"## PHASE 4 — Test cases (ETM)\n"
                f"Run **Step 3e**. Same as tasks but generating Test Cases "
                f"with full preconditions / steps / pass-fail. Preview → "
                f"approval → push linked to each requirement via "
                f"`requirement_url`.\n\n"
                f"## PHASE 5 — Hand-off pause\n"
                f"**STOP HERE. Do not write any code.** Tell me:\n\n"
                f"  > 'Phase 2–4 complete. Open ELM and review:\n"
                f"  >   • DNG: <module markdown links>\n"
                f"  >   • EWM: <task list — links>\n"
                f"  >   • ETM: <test case list — links>\n"
                f"  > In ELM you can:\n"
                f"  >   - approve / reject / modify any requirement\n"
                f"  >   - mark requirements 'Approved' (only Approved reqs "
                f"will drive the code in Phase 6)\n"
                f"  >   - reassign tasks, change priorities\n"
                f"  >   - rewrite test cases\n"
                f"  > When you're ready, come back and say *continue* / "
                f"*build it* / *pull latest*. I'll re-fetch everything from "
                f"ELM (current state, not what we generated) and start "
                f"writing the actual app code.'\n\n"
                f"Then **wait silently for me to come back**. Do not poll, "
                f"do not generate code, do not move on.\n\n"
                f"## PHASE 6 — Re-pull and confirm scope\n"
                f"When I say 'continue':\n\n"
                f"1. Re-fetch the requirements module(s) using "
                f"`get_module_requirements` with `filter={{\"Status\": \"Approved\"}}` "
                f"(or whatever this project's approved-state value is — discover "
                f"via `get_attribute_definitions` first; never guess).\n"
                f"2. Re-fetch linked work items via `query_work_items` "
                f"(filter to active iterations, exclude any moved out of scope).\n"
                f"3. Re-fetch test cases for the same requirements.\n"
                f"4. Show me the current state as a summary table:\n"
                f"   • {{X}} approved requirements (down from {{Y}} originally — "
                f"these were rejected/dropped)\n"
                f"   • {{N}} active tasks\n"
                f"   • {{M}} test cases\n"
                f"5. Confirm: 'Building based on this current state. OK?'\n\n"
                f"## PHASE 7 — Write the code\n"
                f"Once I approve the current state in Phase 6, write the actual "
                f"application code in my IDE. For each file you write, "
                f"include a comment block linking back to the source "
                f"requirement IDs (e.g. `# Implements REQ-005, REQ-007`). The "
                f"code structure should mirror the requirement structure — "
                f"each module / class / function should map to one or more "
                f"reqs.\n\n"
                f"**During coding, after each task is implemented:**\n"
                f"- Call `transition_work_item` to move the task from "
                f"'New' → 'In Development' → 'Resolved'\n"
                f"- For each requirement implemented, you can also call "
                f"`update_requirement_attributes` to record implementation "
                f"status if the project has such an attribute\n\n"
                f"## PHASE 8 — Run tests, record results, file defects on failure\n"
                f"Once code is in place, walk the test cases:\n"
                f"- For each test case that passes the implementation: call "
                f"`create_test_result(test_case_url, status='passed')`\n"
                f"- For each that fails: call `create_test_result(... status='failed')` "
                f"AND interview me briefly to capture the failure (steps, expected "
                f"vs actual, severity), then call `create_defect` linked to "
                f"both the requirement and the test case URL.\n\n"
                f"## PHASE 9 — Final summary\n"
                f"Give me an end-of-build summary with markdown links:\n\n"
                f"  • DNG: [Module name](url) — N reqs (M Approved, K Rejected)\n"
                f"  • EWM: [task list](query-url) — N tasks (M Resolved, K In Progress)\n"
                f"  • ETM: [test results](query-url) — M passed, K failed, J blocked\n"
                f"  • Defects: [open defect list](query-url) — N open\n"
                f"  • Code: list of files written, each with a 'Implements REQ-…' header\n\n"
                f"---\n\n"
                f"**REMEMBER:** the WRITE GATE rule applies to every create_* "
                f"and update_* and transition_* tool call. Never skip the "
                f"interview-preview-confirm gates. The user's approval is "
                f"per-phase, not session-wide.\n\n"
                f"Ready? Call `connect_to_elm` (if needed) and start Phase 0."
            )),
        )]

    elif name == "build-new-project":
        idea = args.get("project_idea", "")
        dng = args.get("dng_project", "")
        ewm = args.get("ewm_project", "")
        etm = args.get("etm_project", "")
        tier_mode = (args.get("tier_mode", "") or "single").lower()
        return [PromptMessage(
            role="user",
            content=TextContent(type="text", text=(
                f"The user wants a GREENFIELD agentic build — start from a "
                f"one-line idea, generate fresh requirements, tasks, tests, "
                f"and code. Use the `build_new_project` TOOL (not the legacy "
                f"build_project tool) so phase context persists via run_id.\n\n"
                f"Call `build_new_project(project_idea=\"{idea}\""
                + (f", dng_project=\"{dng}\"" if dng else "")
                + (f", ewm_project=\"{ewm}\"" if ewm else "")
                + (f", etm_project=\"{etm}\"" if etm else "")
                + (f", tier_mode=\"{tier_mode}\"" if tier_mode else "")
                + ").\n\n"
                f"The tool returns a run_id and Phase 0+1 instructions. "
                f"**Pass that run_id to every subsequent `build_project_next` "
                f"call** so artifact URLs and tier_mode persist across phases.\n\n"
                f"After each phase's user-approval moment, call "
                f"`build_project_next(current_phase=N, user_signal=<verbatim "
                f"user reply>, run_id=<the run_id>)`. The tool refuses to "
                f"advance on empty / vague / non-approval signals. Never "
                f"paraphrase the signal; pass the user's actual words.\n\n"
                f"At Phase 9, call `generate_traceability_matrix(run_id=...)` "
                f"to produce the deliverable matrix. Use "
                f"`build_project_status(run_id=...)` anytime to inspect run "
                f"state.\n\n"
                f"Don't write code until Phase 7. Don't push to ELM without "
                f"per-phase preview-and-approval. Surface every URL as a "
                f"markdown link.\n\n"
                f"Start now."
            )),
        )]

    elif name == "build-from-existing":
        source_kind = (args.get("source_kind", "") or "").lower().strip()
        source_path = args.get("source_path", "")
        idea = args.get("project_idea", "")
        dng = args.get("dng_project", "")
        ewm = args.get("ewm_project", "")
        etm = args.get("etm_project", "")
        tier_mode = (args.get("tier_mode", "") or "single").lower()

        source_intro = ""
        if source_kind == "pdf" and source_path:
            source_intro = (
                f"Source kind: **PDF** at `{source_path}`. After "
                f"`build_from_existing` returns, invoke `/import-work-item` "
                f"with that path to do the structured parsing, then capture "
                f"the resulting EWM/DNG/ETM URLs into the run via "
                f"`build_project_next` context.\n\n"
            )
        elif source_kind == "text":
            source_intro = (
                "Source kind: **pasted requirements text**. After "
                "`build_from_existing` returns, invoke `/import-requirements` "
                "to parse and push, then capture the resulting module + req "
                "URLs into the run via `build_project_next` context.\n\n"
            )
        elif source_kind == "module" and source_path:
            source_intro = (
                f"Source kind: **existing DNG module** at `{source_path}`. "
                f"After `build_from_existing` returns, call "
                f"`get_module_requirements({source_path})` to read all reqs, "
                f"capture the URLs into the run via `build_project_next` "
                f"context, and skip Phase 2 (already exists).\n\n"
            )
        else:
            source_intro = (
                "Source kind not yet specified. In Phase 1, ask the user "
                "*'What do you have as input — (a) a PDF of a work item, "
                "(b) requirements pasted as text, (c) an existing DNG module "
                "URL, or (d) a mix?'* Then route accordingly.\n\n"
            )

        args_block = (
            (f"source_kind=\"{source_kind}\", " if source_kind else "")
            + (f"source_path=\"{source_path}\", " if source_path else "")
            + (f"project_idea=\"{idea}\", " if idea else "")
            + (f"dng_project=\"{dng}\", " if dng else "")
            + (f"ewm_project=\"{ewm}\", " if ewm else "")
            + (f"etm_project=\"{etm}\", " if etm else "")
            + (f"tier_mode=\"{tier_mode}\"" if tier_mode else "")
        ).rstrip(", ")

        return [PromptMessage(
            role="user",
            content=TextContent(type="text", text=(
                f"The user wants a BROWNFIELD agentic build — start from "
                f"existing material rather than a blank slate.\n\n"
                f"{source_intro}"
                f"Call `build_from_existing({args_block})`. The tool returns "
                f"a run_id and Phase 0+1 instructions, including the "
                f"branching logic for whichever source the user has.\n\n"
                f"**Pass run_id to every `build_project_next` call.** Phase 1 "
                f"differs from greenfield — it's an import phase rather than "
                f"an interview phase. After import, the run converges with "
                f"the standard flow at Phase 5 (user review).\n\n"
                f"Phase 2 may be SKIPPED if the import created reqs already; "
                f"Phase 3 / 4 may be skipped similarly if the import included "
                f"tasks / tests. The Phase 6 drift detection works the same "
                f"way regardless of source.\n\n"
                f"Surface every URL as a markdown link. Don't write code "
                f"until Phase 7. Use `build_project_status(run_id=...)` "
                f"anytime to inspect."
            )),
        )]

    elif name == "review-requirements":
        project = args.get("project", "")
        module = args.get("module", "")

        return [PromptMessage(
            role="user",
            content=TextContent(type="text", text=(
                f"Review the requirements in project '{project}', module '{module}' for quality.\n\n"
                f"1. Call get_module_requirements to read all requirements\n"
                f"2. Analyze each requirement against IEEE 29148 criteria:\n"
                f"   - Uses 'shall' for mandatory behavior?\n"
                f"   - Atomic (one testable behavior)?\n"
                f"   - Has measurable acceptance criteria?\n"
                f"   - Unambiguous (no vague terms like 'fast', 'reliable')?\n"
                f"   - Verifiable and testable?\n"
                f"3. Present a quality report:\n"
                f"   - Overall score (% compliant)\n"
                f"   - Table of issues found per requirement\n"
                f"   - Suggested rewrites for non-compliant requirements\n"
                f"4. Ask if I want to update the non-compliant requirements in DNG"
            )),
        )]

    raise ValueError(f"Unknown prompt: {name}")


# ── Resources ────────────────────────────────────────────────

@app.list_resource_templates()
async def list_resource_templates() -> list[ResourceTemplate]:
    return [
        ResourceTemplate(
            uriTemplate="elm://projects/{domain}",
            name="elm-projects",
            description="List all projects in an ELM domain (dng, ewm, or etm)",
            mimeType="application/json",
        ),
        ResourceTemplate(
            uriTemplate="elm://project/{project_name}/modules",
            name="elm-modules",
            description="List modules in a DNG project",
            mimeType="application/json",
        ),
        ResourceTemplate(
            uriTemplate="elm://project/{project_name}/module/{module_name}/requirements",
            name="elm-requirements",
            description="Get all requirements from a specific module",
            mimeType="application/json",
        ),
    ]


@app.list_resources()
async def list_resources() -> list[Resource]:
    """List static resources — connected project info if available."""
    resources = []
    client = _get_or_create_client()
    if client and _projects_cache:
        resources.append(Resource(
            uri="elm://connection/status",
            name="ELM Connection Status",
            description=f"Connected to {client.base_url} with {len(_projects_cache)} DNG projects",
            mimeType="application/json",
        ))
    return resources


@app.read_resource()
async def read_resource(uri: str) -> str:
    import json as _json

    # elm://connection/status
    if uri == "elm://connection/status":
        client = _get_or_create_client()
        if client:
            return _json.dumps({
                "connected": True,
                "server": client.base_url,
                "dng_projects": len(_projects_cache),
                "ewm_projects": len(_ewm_projects_cache),
                "etm_projects": len(_etm_projects_cache),
            }, indent=2)
        return _json.dumps({"connected": False, "error": _client_error})

    # elm://projects/{domain}
    if uri.startswith("elm://projects/"):
        domain = uri.split("/")[-1]
        client = _get_or_create_client()
        if not client:
            return _json.dumps({"error": "Not connected to ELM"})

        if domain == "ewm":
            projects = client.list_ewm_projects()
        elif domain == "etm":
            projects = client.list_etm_projects()
        else:
            projects = client.list_projects()

        return _json.dumps([{"title": p["title"], "id": p.get("id", "")} for p in projects], indent=2)

    # elm://project/{name}/modules
    if "/modules" in uri and uri.startswith("elm://project/"):
        parts = uri.replace("elm://project/", "").split("/")
        project_name = parts[0]
        client = _get_or_create_client()
        if not client:
            return _json.dumps({"error": "Not connected to ELM"})

        if not _projects_cache:
            _projects_cache.extend(client.list_projects())

        project = _find_by_identifier(_projects_cache, project_name)
        if not project:
            return _json.dumps({"error": f"Project not found: {project_name}"})

        modules = client.get_modules(project["url"])
        return _json.dumps([{"title": m["title"], "id": m.get("id", "")} for m in modules], indent=2)

    # elm://project/{name}/module/{module}/requirements
    if "/requirements" in uri and "/module/" in uri:
        parts = uri.replace("elm://project/", "").split("/")
        # parts: [project_name, "module", module_name, "requirements"]
        project_name = parts[0]
        module_name = parts[2] if len(parts) > 2 else ""
        client = _get_or_create_client()
        if not client:
            return _json.dumps({"error": "Not connected to ELM"})

        if not _projects_cache:
            _projects_cache.extend(client.list_projects())

        project = _find_by_identifier(_projects_cache, project_name)
        if not project:
            return _json.dumps({"error": f"Project not found: {project_name}"})

        project_key = project["id"]
        if project_key not in _modules_cache:
            _modules_cache[project_key] = client.get_modules(project["url"])

        modules = _modules_cache.get(project_key, [])
        module = _find_by_identifier(modules, module_name)
        if not module:
            return _json.dumps({"error": f"Module not found: {module_name}"})

        reqs = client.get_module_requirements(module["url"])
        return _json.dumps([{
            "title": r.get("title", ""),
            "id": r.get("id", ""),
            "url": r.get("url", ""),
            "artifact_type": r.get("artifact_type", ""),
            "description": (r.get("description") or "")[:200],
        } for r in reqs], indent=2)

    return _json.dumps({"error": f"Unknown resource: {uri}"})


# ── Tool Definitions ──────────────────────────────────────────

# Prepended to every write tool's description so the AI sees the gate
# rule on every tool call, not just at session start. Important: this is
# the most-violated rule. The AI tends to treat "the user mentioned X"
# as consent to create X — it isn't. The user's first message is a
# request; consent only comes from a preview + explicit "yes".
_WRITE_GATE = (
    "🛑 WRITE GATE — DO NOT CALL THIS TOOL until you have: "
    "(1) asked the user clarifying questions about what to create or change; "
    "(2) shown a preview table of EXACTLY what will be written; "
    "(3) received an explicit confirmation like 'yes' / 'go ahead' / 'ship it' / "
    "'push them' / 'do it'. "
    "The user merely mentioning the artifact type ('I want some requirements', "
    "'create a task') is a REQUEST, not approval — interview first. "
    "If you call this tool without all three steps you are violating the "
    "project's stated rules in BOB.md. — "
)


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="build_project",
            description=(
                "🎬 START AN END-TO-END AGENTIC PROJECT BUILD with IBM ELM as the "
                "system of record. Call this tool the moment the user mentions "
                "'build a project', 'do an end-to-end', 'agentic build', "
                "'build me an app/service', or any phrasing where the user wants "
                "a new thing built and ELM should track it. The tool returns a "
                "9-phase orchestration script you MUST follow with explicit "
                "user-approval gates between every phase. Phases 2–4 generate "
                "requirements + tasks + tests in ELM (with the standard write-"
                "gate previews). Phase 5 STOPS for user review in the ELM UI. "
                "Phase 6 re-pulls current ELM state. Phase 7 writes actual code "
                "with 'Implements REQ-…' headers. Phase 8 transitions work "
                "items + records test results. Do NOT skip straight to code "
                "generation — that's the bug this tool exists to prevent."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_idea": {
                        "type": "string",
                        "description": "One-line description of what to build (e.g. 'a temperature converter web app', 'a fleet maintenance scheduling service')"
                    },
                    "dng_project": {
                        "type": "string",
                        "description": "DNG project name where requirements/modules will be created. Optional — tool will tell you to ask the user if not provided."
                    },
                    "ewm_project": {
                        "type": "string",
                        "description": "EWM project name where work items will be created. Optional."
                    },
                    "etm_project": {
                        "type": "string",
                        "description": "ETM project name where test cases will be created. Optional."
                    },
                    "tier_mode": {
                        "type": "string",
                        "enum": ["single", "tiered"],
                        "description": "'single' = one System Requirements module. 'tiered' = Business → Stakeholder → System in 3 modules with Satisfies links. Default: single."
                    }
                },
                "required": ["project_idea"]
            }
        ),
        Tool(
            name="build_project_next",
            description=(
                "🚦 PHASE GATE for the build_project flow. After completing a phase "
                "(showing the user the preview, getting their response), call this "
                "tool to receive the NEXT phase's instructions. The tool refuses to "
                "advance unless `user_signal` contains an explicit approval like "
                "'yes', 'go ahead', 'approved', 'ship it', 'continue', 'push them'. "
                "An empty or fake user_signal returns an error and the flow stalls "
                "— that's the point. This is the lock that prevents Bob from "
                "advancing phases without real user consent. Pass the user's "
                "actual reply text, not a paraphrase. Pass `run_id` (returned by "
                "build_project / build_new_project / build_from_existing) so the "
                "tool can persist artifact URLs, tier_mode, etc. across phases — "
                "without it, state survives only as long as your conversation "
                "context."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "current_phase": {
                        "type": "integer",
                        "description": "The phase number you JUST finished (0–8). build_project_next will return the instructions for phase current_phase + 1. Phase 7 advances to Phase 7.5 (code-review gate) before Phase 8.",
                        "minimum": 0,
                        "maximum": 8
                    },
                    "user_signal": {
                        "type": "string",
                        "description": "VERBATIM text of what the user typed in response to your phase preview. Must contain explicit approval ('yes' / 'go ahead' / 'approved' / 'ship it' / 'continue' / 'push them' / 'do it' / 'looks good'). The tool validates this — empty or generic non-approval text gets an error and you must wait. Do not paraphrase, do not assume, do not fake."
                    },
                    "run_id": {
                        "type": "string",
                        "description": "Run id returned by build_project / build_new_project / build_from_existing. Optional but STRONGLY recommended — it lets the gate persist artifact URLs and tier_mode across phases. Without it, you must remember everything in your context, and Phase 6 drift detection can't tell what changed."
                    },
                    "context": {
                        "type": "string",
                        "description": "Optional: brief context the next phase should know about (e.g. URLs of artifacts created in the prior phase, the user's specific changes to your preview). The next-phase script will reference this back."
                    }
                },
                "required": ["current_phase", "user_signal"]
            }
        ),
        Tool(
            name="list_capabilities",
            description=(
                "Return the full inventory of what this MCP server can do — every "
                "tool grouped by domain (DNG / EWM / ETM / GCM / SCM / Charts / "
                "Server-mgmt) with a one-line description of each. Use this when "
                "the user asks 'what can you do?', 'list your tools', 'show me "
                "everything', or 'help'. Always call this — never enumerate from "
                "memory, since the actual list of registered tools is the source "
                "of truth and may include tools added in a newer version than "
                "what this docstring knows about."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        Tool(
            name="build_new_project",
            description=(
                "Greenfield build flow — start from a one-line idea and produce "
                "requirements (DNG) → tasks (EWM) → tests (ETM) → user review → "
                "code → tracking. Use this when the user has NO existing artifacts "
                "and is starting fresh. For brownfield (existing PDF / pasted "
                "reqs / existing module), use `build_from_existing` instead. "
                "Returns a run_id you must pass to every subsequent "
                "`build_project_next` call."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_idea": {
                        "type": "string",
                        "description": "One-line description of what to build (e.g. 'a temperature converter web app', 'a fleet maintenance scheduling service')."
                    },
                    "dng_project": {"type": "string", "description": "DNG project name (optional — AI will ask)."},
                    "ewm_project": {"type": "string", "description": "EWM project name (optional)."},
                    "etm_project": {"type": "string", "description": "ETM project name (optional)."},
                    "tier_mode": {"type": "string", "description": "'single' (one System Requirements module) or 'tiered' (Business→Stakeholder→System). Default 'single'."}
                },
                "required": ["project_idea"]
            }
        ),
        Tool(
            name="build_from_existing",
            description=(
                "Brownfield build flow — start from existing material (a Jira "
                "epic PDF, pasted requirements text, an existing DNG module, "
                "etc.) and continue from there. Imports / reuses what's already "
                "there, then converges with the standard flow at Phase 5 (user "
                "review). Use this when the user has source material to import "
                "rather than a fresh idea. The first phase asks WHAT they have "
                "(PDF / pasted text / existing module / link to a ticket) and "
                "branches accordingly. Returns a run_id you must pass to every "
                "subsequent `build_project_next` call."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "source_kind": {
                        "type": "string",
                        "description": "What kind of source material the user has: 'pdf' (work-item PDF — chains into /import-work-item), 'text' (pasted requirements — chains into /import-requirements), 'module' (existing DNG module URL), 'mixed' (multiple) or '' (ask the user)."
                    },
                    "source_path": {"type": "string", "description": "Path to the PDF, or URL of the existing module. Optional — AI will ask if missing."},
                    "project_idea": {"type": "string", "description": "Short summary of the project. AI will derive from source if not provided."},
                    "dng_project": {"type": "string", "description": "DNG project name (optional)."},
                    "ewm_project": {"type": "string", "description": "EWM project name (optional)."},
                    "etm_project": {"type": "string", "description": "ETM project name (optional)."},
                    "tier_mode": {"type": "string", "description": "'single' or 'tiered'. Default 'single'."}
                },
                "required": []
            }
        ),
        Tool(
            name="build_project_status",
            description=(
                "Inspect the state of a build-project run by run_id, OR list all "
                "active runs if run_id is omitted. Returns: current phase, idea, "
                "tier_mode, project URLs, all artifacts created so far (with "
                "URLs), approval signals received per phase, drift state if "
                "Phase 6 has run. Use this when the user asks *'where am I in "
                "the build?'*, *'what runs are active?'*, or *'what did I do "
                "in run X?'*. Read-only — no approval gate."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "run_id": {"type": "string", "description": "Run id (optional). If omitted, lists all active runs."}
                },
                "required": []
            }
        ),
        Tool(
            name="generate_traceability_matrix",
            description=(
                "Generate a markdown traceability matrix from a build-project "
                "run's recorded artifacts. Each row: requirement → tasks → test "
                "cases → results → defects, with clickable URLs. Phase 9 of the "
                "build flow uses this to produce the final deliverable, but you "
                "can call it anytime mid-build to show the user the trace web "
                "as it exists right now. Read-only — no approval gate."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "run_id": {"type": "string", "description": "Run id from build_new_project / build_from_existing / build_project."}
                },
                "required": ["run_id"]
            }
        ),
        Tool(
            name="build_project_resume",
            description=(
                "Pick up an in-progress build run after a break, a Bob restart, "
                "or even on a different machine (state persists to disk at "
                "~/.elm-mcp/runs/<run_id>.json). Without arguments, lists all "
                "resumable runs and asks the user which one. With run_id, "
                "loads that specific run, summarizes current state, and "
                "returns instructions for continuing from the right phase. "
                "Read-only — doesn't modify ELM."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "run_id": {"type": "string", "description": "Run id to resume (optional). If omitted, lists all resumable runs."}
                },
                "required": []
            }
        ),
        Tool(
            name="publish_build_state_to_dng",
            description=(_WRITE_GATE +
                "Write (or update) a build run's current state as a DNG "
                "artifact, so teammates can see where you are in the build "
                "and pick it up themselves. The artifact is named "
                "`[BOB-BUILD-STATE] <project idea>` and lives in any module "
                "the user picks (or a default 'AI Build State' module). "
                "Updates idempotently — re-calling overwrites the body with "
                "the latest state, preserving the same artifact URL across "
                "phases. After phase changes, build_project_next can call "
                "this automatically if the run already has a "
                "dng_state_artifact_url. Use this when the user wants "
                "cross-team handoff visibility (Brett starts a build, Sarah "
                "opens DNG, sees the cursor, picks it up)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "run_id": {
                        "type": "string",
                        "description": "Run id from build_new_project / build_from_existing / build_project."
                    },
                    "module_url": {
                        "type": "string",
                        "description": "DNG module URL to write the artifact into. Optional — if not provided and the run already has a dng_state_artifact_url, the existing artifact is updated."
                    },
                    "shape_url": {
                        "type": "string",
                        "description": "Optional artifact shape URL. If omitted, uses System Requirement (any shape works — body is the deliverable, not the type)."
                    }
                },
                "required": ["run_id"]
            }
        ),
        Tool(
            name="connect_to_elm",
            description=(
                "Connect to an IBM ELM server with credentials. "
                "The URL can be the base server URL (e.g., https://server.com) "
                "or the DNG URL ending in /rm — both work. "
                "This single connection is used for ALL tools (DNG, EWM, and ETM). "
                "Must be called before any other tool."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "ELM server URL (e.g., https://server.com or https://server.com/rm)"
                    },
                    "username": {
                        "type": "string",
                        "description": "ELM username"
                    },
                    "password": {
                        "type": "string",
                        "description": "ELM password"
                    }
                },
                "required": ["url", "username", "password"]
            }
        ),
        Tool(
            name="list_projects",
            description=(
                "List projects from IBM ELM. "
                "Supports three domains: 'dng' (requirements), 'ewm' (work items), 'etm' (test management). "
                "Defaults to 'dng'. Returns a numbered list."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "enum": ["dng", "ewm", "etm"],
                        "description": "Which ELM domain to list projects from: 'dng' (default), 'ewm', or 'etm'"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="get_modules",
            description=(
                "Get all modules from a DOORS Next project. "
                "Modules are containers that hold requirements. "
                "Call list_projects first to get project numbers. "
                "To see actual requirements inside a module, use get_module_requirements next."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_identifier": {
                        "type": "string",
                        "description": "Project number (e.g., '3') or name (partial match supported)"
                    }
                },
                "required": ["project_identifier"]
            }
        ),
        Tool(
            name="get_module_requirements",
            description=(
                "Get requirements from a module, optionally filtered by ANY attribute "
                "(status, type, priority, custom field, title substring, etc.). "
                "Call get_modules first to find the module. To discover what attributes "
                "this project supports for filtering, call get_attribute_definitions. "
                "Returns requirement URLs needed by update_requirement, create_task, "
                "and create_test_case."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_identifier": {
                        "type": "string",
                        "description": "Project number or name"
                    },
                    "module_identifier": {
                        "type": "string",
                        "description": "Module number (from get_modules output) or name"
                    },
                    "filter": {
                        "type": "object",
                        "description": (
                            "Optional filter dict. Each key/value pair narrows results "
                            "(AND'd together, case-insensitive). Examples:\n"
                            "  • Exact: {\"Status\": \"Approved\"}, "
                            "{\"artifact_type\": \"System Requirement\"}\n"
                            "  • Multi-value (any-of): {\"Status\": [\"Approved\", \"Reviewed\"]}\n"
                            "  • Substring (append _contains): {\"title_contains\": \"security\"}, "
                            "{\"description_contains\": \"ISO 26262\"}\n\n"
                            "The keys are project-specific — DIFFERENT DNG projects expose "
                            "DIFFERENT custom attributes. Use get_attribute_definitions FIRST "
                            "to see what's available; never guess attribute names."
                        ),
                        "additionalProperties": True
                    }
                },
                "required": ["project_identifier", "module_identifier"]
            }
        ),
        Tool(
            name="save_requirements",
            description=(
                "Save requirements to a file. "
                "Requires get_module_requirements to have been called first in this session. "
                "Supports JSON, CSV, and Markdown formats."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "format": {
                        "type": "string",
                        "enum": ["json", "csv", "markdown"],
                        "description": "Output format: json, csv, or markdown"
                    },
                    "filename": {
                        "type": "string",
                        "description": "Output filename (optional - auto-generated if omitted)"
                    }
                },
                "required": ["format"]
            }
        ),
        Tool(
            name="create_module",
            description=(_WRITE_GATE +
                "Create a new DOORS Next module (a navigable document that holds requirements). "
                "Use this when the user wants a fresh module to house requirements. "
                "After creating the module, call create_requirements with module_name set "
                "to bind requirements into it. Returns the module URL."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_identifier": {
                        "type": "string",
                        "description": "DNG project number or name"
                    },
                    "title": {
                        "type": "string",
                        "description": "Module title"
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional module description"
                    }
                },
                "required": ["project_identifier", "title"]
            }
        ),
        Tool(
            name="add_to_module",
            description=(_WRITE_GATE +
                "Bind one or more EXISTING requirements into an EXISTING module's "
                "structure. Use this when requirements were created without a "
                "module_name (so they're loose in a folder) and you need to add "
                "them to a module afterward. For NEW requirements, pass "
                "module_name to `create_requirements` instead — that auto-binds "
                "during creation. Uses DNG's Module Structure API (the "
                "DoorsRP-Request-Type: public 2.0 path that probe/MODULE_BINDING_FINDINGS.md "
                "documents). Idempotent — safe to re-run; already-bound reqs are skipped."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "module_url": {
                        "type": "string",
                        "description": "Full URL of the existing DNG module (from get_modules or create_module)"
                    },
                    "requirement_urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of full requirement URLs to bind into the module"
                    }
                },
                "required": ["module_url", "requirement_urls"]
            }
        ),
        Tool(
            name="create_folder",
            description=(_WRITE_GATE +
                "Create a folder in a DNG project's folder tree. Useful for "
                "organizing requirements before creating them — e.g. 'Business "
                "Requirements / Run 2026-05'. Returns the folder URL which can "
                "be passed as `folder_url` to subsequent `create_requirement` "
                "calls. If you just want to ensure a folder exists, call "
                "`find_folder` first; if it returns None, then `create_folder`."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_identifier": {
                        "type": "string",
                        "description": "DNG project number or name"
                    },
                    "folder_name": {
                        "type": "string",
                        "description": "Name for the new folder"
                    },
                    "parent_folder_url": {
                        "type": "string",
                        "description": "Optional parent folder URL. If omitted, creates at the project root."
                    }
                },
                "required": ["project_identifier", "folder_name"]
            }
        ),
        Tool(
            name="find_folder",
            description=(
                "Look up a DNG folder by name within a project. Returns the "
                "folder URL if found, otherwise None. Use this BEFORE "
                "`create_folder` to avoid creating duplicates. Read-only — no "
                "approval gate."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_identifier": {
                        "type": "string",
                        "description": "DNG project number or name"
                    },
                    "folder_name": {
                        "type": "string",
                        "description": "Folder name to search for (case-sensitive)"
                    }
                },
                "required": ["project_identifier", "folder_name"]
            }
        ),
        Tool(
            name="create_requirements",
            description=(_WRITE_GATE +
                "Create requirements in a DOORS Next project AND bind them to a module so they "
                "appear in DNG's module/document view. STRONGLY PREFER providing module_name — "
                "module_name is what makes requirements visible as a navigable document; folder-only "
                "requirements (no module_name) end up as orphan artifacts most users can't find. "
                "MUST call get_artifact_types first to get valid type names for this project. "
                "Returns created requirement URLs needed by create_task and create_test_case."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_identifier": {
                        "type": "string",
                        "description": "Project number or name"
                    },
                    "module_name": {
                        "type": "string",
                        "description": "Module name to bind requirements into. If a module with this name exists it's reused; otherwise it's created. STRONGLY RECOMMENDED — without it, requirements are orphans in a folder."
                    },
                    "folder_name": {
                        "type": "string",
                        "description": "Optional folder for the underlying base artifacts (DNG stores every artifact in a folder, even module-bound ones). Defaults to a folder named after the module."
                    },
                    "requirements": {
                        "type": "array",
                        "description": "Array of requirements to create",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {
                                    "type": "string",
                                    "description": "Requirement title"
                                },
                                "content": {
                                    "type": "string",
                                    "description": "Requirement body text with details and acceptance criteria"
                                },
                                "artifact_type": {
                                    "type": "string",
                                    "description": "Artifact type name — MUST match a name from get_artifact_types output for this project"
                                },
                                "link_type": {
                                    "type": "string",
                                    "description": "Optional: Link type name (e.g., 'Satisfies', 'Elaborated By') from get_link_types"
                                },
                                "link_to": {
                                    "type": "string",
                                    "description": "Optional: URL of the requirement to link to (from get_module_requirements output). Must be provided together with link_type."
                                }
                            },
                            "required": ["title", "content", "artifact_type"]
                        }
                    }
                },
                "required": ["project_identifier", "requirements"]
            }
        ),
        Tool(
            name="get_link_types",
            description=(
                "Get all available link types for a DOORS Next project. "
                "Use this to find the correct link type when creating linked requirements "
                "(e.g., Satisfies, Elaborated By, etc.)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_identifier": {
                        "type": "string",
                        "description": "Project number or name"
                    }
                },
                "required": ["project_identifier"]
            }
        ),
        Tool(
            name="search_requirements",
            description=(
                "Full-text search across all artifacts in a DNG project. "
                "Finds requirements, modules, and other artifacts matching the search terms. "
                "Use this to quickly find specific requirements by keyword."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_identifier": {
                        "type": "string",
                        "description": "DNG project number or name"
                    },
                    "query": {
                        "type": "string",
                        "description": "Search terms (e.g., 'security', 'power backup', 'login')"
                    }
                },
                "required": ["project_identifier", "query"]
            }
        ),
        Tool(
            name="get_artifact_types",
            description=(
                "Get all available artifact types for a DOORS Next project. "
                "MUST be called before create_requirements — artifact types vary by project. "
                "Returns the exact type names to use in the artifact_type field."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_identifier": {
                        "type": "string",
                        "description": "Project number or name"
                    }
                },
                "required": ["project_identifier"]
            }
        ),
        Tool(
            name="update_requirement",
            description=(_WRITE_GATE +
                "Update an existing requirement in DNG. "
                "Provide the requirement URL (from get_module_requirements or create_requirements) "
                "and the new title and/or content. Uses OSLC optimistic locking (ETag). "
                "Use this for PDF re-import workflows where only changed requirements need updating."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "requirement_url": {
                        "type": "string",
                        "description": "Full URL of the requirement to update (from get_module_requirements or create_requirements output)"
                    },
                    "title": {
                        "type": "string",
                        "description": "New title for the requirement (optional — keeps existing if omitted)"
                    },
                    "content": {
                        "type": "string",
                        "description": "New content/description as plain text (optional — keeps existing if omitted)"
                    }
                },
                "required": ["requirement_url"]
            }
        ),
        Tool(
            name="create_baseline",
            description=(_WRITE_GATE +
                "Create a baseline (immutable snapshot) of the current state of a DNG project. "
                "Use this after importing requirements to freeze the state before making changes. "
                "Baseline creation is async — the server processes it in the background."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_identifier": {
                        "type": "string",
                        "description": "DNG project number or name"
                    },
                    "title": {
                        "type": "string",
                        "description": "Baseline name (e.g., 'V1 Import Baseline')."
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional baseline description"
                    }
                },
                "required": ["project_identifier", "title"]
            }
        ),
        Tool(
            name="list_baselines",
            description=(
                "List all baselines for a DNG project. "
                "Returns baseline names, URLs, and creation dates. "
                "Use this to see available baselines for comparison."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_identifier": {
                        "type": "string",
                        "description": "DNG project number or name"
                    }
                },
                "required": ["project_identifier"]
            }
        ),
        Tool(
            name="compare_baselines",
            description=(
                "Compare requirements between a baseline and the current stream. "
                "Reads requirements from a baseline snapshot and the current state, "
                "then returns what changed, was added, or was removed. "
                "Call list_baselines first to get baseline URLs."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_identifier": {
                        "type": "string",
                        "description": "DNG project number or name"
                    },
                    "module_identifier": {
                        "type": "string",
                        "description": "Module number or name (from get_modules)"
                    },
                    "baseline_url": {
                        "type": "string",
                        "description": "URL of the baseline to compare against (from list_baselines output)"
                    }
                },
                "required": ["project_identifier", "module_identifier", "baseline_url"]
            }
        ),
        Tool(
            name="extract_pdf",
            description=(
                "Extract text from a PDF file. "
                "Use this INSTEAD of trying to read PDFs yourself. "
                "Returns clean structured text with page numbers. "
                "Use this as the first step when importing a PDF into DNG."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the PDF file on disk"
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="create_task",
            description=(_WRITE_GATE +
                "Create an EWM Task work item. "
                "**ALWAYS pass `requirement_url` when the task implements a DNG requirement** — "
                "without it, the task is unlinked, traceability breaks, and reports "
                "(RTM, coverage) won't show the relationship. The URL comes verbatim "
                "from `create_requirements` output (the `url` field of each created "
                "requirement) or `get_module_requirements` output. The link is written "
                "as `calm:implementsRequirement`. Use list_projects with domain='ewm' "
                "first to find the EWM project."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ewm_project": {
                        "type": "string",
                        "description": "EWM project number (from list_projects domain=ewm) or name"
                    },
                    "title": {
                        "type": "string",
                        "description": "Task title"
                    },
                    "description": {
                        "type": "string",
                        "description": "Task description with details"
                    },
                    "requirement_url": {
                        "type": "string",
                        "description": "STRONGLY RECOMMENDED. Full URL of the DNG requirement this task implements. Get this verbatim from create_requirements output (each created requirement's `url` field) or get_module_requirements output. Example: 'https://server/rm/resources/TX_xxx'. Omitting this leaves the task unlinked — traceability breaks."
                    }
                },
                "required": ["ewm_project", "title"]
            }
        ),
        Tool(
            name="create_test_case",
            description=(_WRITE_GATE +
                "Create an ETM Test Case. "
                "**ALWAYS pass `requirement_url` when the test validates a DNG requirement** — "
                "without it, the test case is unlinked and reports won't show what it "
                "validates. The URL comes verbatim from `create_requirements` output "
                "or `get_module_requirements` output. The link is written as "
                "`oslc_qm:validatesRequirement`. Use list_projects with domain='etm' "
                "first to find the ETM project."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "etm_project": {
                        "type": "string",
                        "description": "ETM project number (from list_projects domain=etm) or name"
                    },
                    "title": {
                        "type": "string",
                        "description": "Test case title"
                    },
                    "description": {
                        "type": "string",
                        "description": "Test case description with test steps, expected results, pass/fail criteria"
                    },
                    "requirement_url": {
                        "type": "string",
                        "description": "STRONGLY RECOMMENDED. Full URL of the DNG requirement this test validates. Get this verbatim from create_requirements output (each created requirement's `url` field) or get_module_requirements output. Example: 'https://server/rm/resources/TX_xxx'. Omitting this leaves the test case unlinked — traceability breaks."
                    }
                },
                "required": ["etm_project", "title"]
            }
        ),
        Tool(
            name="create_test_script",
            description=(_WRITE_GATE +
                "Create an ETM Test Script — the actual test procedure (numbered "
                "steps, expected results, pass/fail criteria). Test Cases say "
                "*what* to verify; Test Scripts say *how* to verify it. Use this "
                "in addition to `create_test_case` when you want the full "
                "procedure as a separate, reusable artifact (one script can be "
                "referenced by multiple test cases). Pass `test_case_url` to "
                "wire the script to its test case via `oslc_qm:executesTestScript`."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "etm_project": {
                        "type": "string",
                        "description": "ETM project number (from list_projects domain=etm) or name"
                    },
                    "title": {
                        "type": "string",
                        "description": "Test script title (the procedure name, not the test case it validates)"
                    },
                    "steps": {
                        "type": "string",
                        "description": "Numbered procedure body. Each step typically has: action, expected result, pass/fail. Plain text or simple Markdown. Example:\n\n1. Power on the device.\n   Expected: status LED turns green within 2s.\n   PASS if green within 2s, FAIL otherwise.\n\n2. ..."
                    },
                    "test_case_url": {
                        "type": "string",
                        "description": "Optional. URL of the Test Case this script executes (from create_test_case output). Wires the script to the case via oslc_qm:executesTestScript so the case knows which procedure to run."
                    }
                },
                "required": ["etm_project", "title"]
            }
        ),
        Tool(
            name="create_test_result",
            description=(_WRITE_GATE +
                "Create an ETM Test Result for a test case. "
                "Records a pass/fail/blocked/incomplete/error result. "
                "Requires the test case URL from create_test_case output."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "etm_project": {
                        "type": "string",
                        "description": "ETM project number (from list_projects domain=etm) or name"
                    },
                    "test_case_url": {
                        "type": "string",
                        "description": "URL of the Test Case this result reports on (from create_test_case)"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["passed", "failed", "blocked", "incomplete", "error"],
                        "description": "Test result status"
                    },
                    "title": {
                        "type": "string",
                        "description": "Optional result title (auto-generated if omitted)"
                    }
                },
                "required": ["etm_project", "test_case_url", "status"]
            }
        ),
        Tool(
            name="list_global_configurations",
            description=(
                "List all global configurations from GCM (Global Configuration Management). "
                "Shows streams and baselines that span across DNG, EWM, and ETM. "
                "These are the top-level configurations that tie together components from all ELM apps."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="list_global_components",
            description=(
                "List all components registered in GCM across DNG, EWM, and ETM. "
                "Shows every component in the ELM deployment with its project area and configuration URLs."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_global_config_details",
            description=(
                "Get details for a specific global configuration from GCM. "
                "Shows the configuration type (stream/baseline), component, and which "
                "DNG/EWM/ETM local configurations contribute to it. "
                "Use list_global_configurations first to get config URLs."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "config_url": {
                        "type": "string",
                        "description": "URL of the global configuration (from list_global_configurations)"
                    }
                },
                "required": ["config_url"]
            }
        ),
        Tool(
            name="update_elm_mcp",
            description=(
                "Force-check for a new version of ELM MCP and update in place if "
                "available. Bypasses the once-per-day auto-update throttle. Use "
                "this when the user says 'are you up to date', 'update yourself', "
                "or 'pull the latest version'. Returns the new version number on "
                "success and tells the user to restart their AI assistant; the "
                "running server keeps using the OLD code until the next restart, "
                "by design (we don't yank the rug mid-conversation)."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="generate_chart",
            description=(_WRITE_GATE +
                "Generate a chart (bar, horizontal bar, pie, or line) from data and save it as a PNG. "
                "Use this to visualize ELM data — e.g., requirements by status, test results pass/fail, "
                "tasks by priority, requirements per module. The host LLM should aggregate the data first "
                "(from get_module_requirements, search_requirements, etc.), then call this tool with the "
                "summary numbers. Returns the absolute path to the saved PNG."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "chart_type": {
                        "type": "string",
                        "enum": ["bar", "hbar", "pie", "line"],
                        "description": "Chart type: 'bar' (vertical), 'hbar' (horizontal — best for long category names), 'pie', or 'line'"
                    },
                    "title": {
                        "type": "string",
                        "description": "Chart title shown at the top"
                    },
                    "labels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Category labels (x-axis for bar/line, slice labels for pie)"
                    },
                    "values": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Numeric values, one per label (same length as labels)"
                    },
                    "x_label": {
                        "type": "string",
                        "description": "X-axis label (ignored for pie). Optional."
                    },
                    "y_label": {
                        "type": "string",
                        "description": "Y-axis label (ignored for pie). Optional."
                    },
                    "output_filename": {
                        "type": "string",
                        "description": "Output filename (no path, no extension). Optional — auto-generated from title + timestamp if omitted."
                    }
                },
                "required": ["chart_type", "title", "labels", "values"]
            }
        ),
        # ── DNG: arbitrary attribute updates ────────────────────
        Tool(
            name="get_attribute_definitions",
            description=(
                "List all DNG attribute property definitions for a project — name, "
                "predicate URI, value type, and (for enums) allowed values. "
                "Use this BEFORE update_requirement_attributes to see what attributes "
                "exist on the project's artifact shapes (e.g. Priority, Status, Stability) "
                "and what enum labels are valid. "
                "Call list_projects with domain='dng' first to find the project."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_identifier": {
                        "type": "string",
                        "description": "DNG project number or name"
                    }
                },
                "required": ["project_identifier"]
            }
        ),
        Tool(
            name="update_requirement_attributes",
            description=(_WRITE_GATE +
                "Set arbitrary DNG attributes on a requirement (e.g. Priority='High', "
                "Status='Approved'). Uses optimistic locking (GET ETag → PUT If-Match). "
                "Pass attribute keys by friendly name OR full predicate URI. For enum-valued "
                "attributes, pass the human-readable label (resolved via the project's "
                "shape definitions). Call get_attribute_definitions first to discover "
                "valid attribute names and their allowed values. "
                "NOTE: this tool updates standalone artifact attributes; module-bound "
                "writes are restricted on this DNG server (see add_to_module)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "requirement_url": {
                        "type": "string",
                        "description": "Full URL of the requirement (from get_module_requirements / create_requirements)"
                    },
                    "attributes": {
                        "type": "object",
                        "description": "Dict mapping attribute name (e.g. 'Priority') or predicate URI to its new value (string literal, resource URI, or enum label like 'High')",
                        "additionalProperties": True
                    }
                },
                "required": ["requirement_url", "attributes"]
            }
        ),
        # ── EWM: work-item operations ──────────────────────────
        Tool(
            name="update_work_item",
            description=(_WRITE_GATE +
                "Update arbitrary fields on an EWM work item via PUT-with-If-Match. "
                "Friendly aliases: title, description, owner (user URI), severity / priority "
                "(enum URIs), subject (tag list), filedAgainst (category URI). "
                "Predicate URIs are also accepted. To change state, use transition_work_item."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "workitem_url": {
                        "type": "string",
                        "description": "Full work-item URL (e.g. .../resource/itemName/com.ibm.team.workitem.WorkItem/3583 — output from create_task)"
                    },
                    "fields": {
                        "type": "object",
                        "description": "Dict of {field_name: new_value}. Friendly names: title, description, owner, severity, priority, subject, filedAgainst. Resource-valued fields take URIs.",
                        "additionalProperties": True
                    }
                },
                "required": ["workitem_url", "fields"]
            }
        ),
        Tool(
            name="transition_work_item",
            description=(_WRITE_GATE +
                "Move an EWM work item through its workflow (e.g. New → In Development → Done). "
                "Looks up the project's workflow actions and PUTs with `?_action=<actionId>`. "
                "Pass `target_state` as a state title ('In Development', 'Done') or identifier. "
                "**Tip:** call `get_workflow_states(workitem_url)` first to see exactly which "
                "states are available for THIS work item's workflow — different work item "
                "types and projects use different state names. Don't guess 'Resolved' vs "
                "'Done' vs 'Closed'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "workitem_url": {
                        "type": "string",
                        "description": "Full work-item URL (from create_task / query_work_items)"
                    },
                    "target_state": {
                        "type": "string",
                        "description": "Desired state name (e.g. 'In Development', 'Done', 'New')"
                    }
                },
                "required": ["workitem_url", "target_state"]
            }
        ),
        Tool(
            name="get_workflow_states",
            description=(
                "List the workflow states available for a specific EWM work "
                "item — its current state plus every state defined in its "
                "workflow. Different work-item types (Task, Defect, Story) and "
                "different projects use different state names. Call this BEFORE "
                "`transition_work_item` to know exactly which `target_state` "
                "value to pass. Eliminates the 'guess Resolved / Done / Closed' "
                "trial-and-error pattern. Read-only — no approval gate."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "workitem_url": {
                        "type": "string",
                        "description": "Full work-item URL (from create_task / query_work_items / etc.)"
                    }
                },
                "required": ["workitem_url"]
            }
        ),
        Tool(
            name="query_work_items",
            description=(
                "Query EWM work items via OSLC CM. Use this to find work items matching "
                "filters such as `oslc_cm:closed=false` or `dcterms:creator=\"<user-uri>\"`. "
                "Supports OSLC where syntax. Resolves project name → project area, then "
                "calls /ccm/oslc/contexts/<paId>/workitems?oslc.where=...&oslc.select=...&oslc.pageSize=N. "
                "Use list_projects domain='ewm' to find the EWM project name."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ewm_project": {
                        "type": "string",
                        "description": "EWM project number or name"
                    },
                    "where": {
                        "type": "string",
                        "description": "OSLC where clause (e.g. 'oslc_cm:closed=false', 'rtc_cm:type=\"...task\"')"
                    },
                    "select": {
                        "type": "string",
                        "description": "OSLC select clause (default '*')"
                    },
                    "page_size": {
                        "type": "integer",
                        "description": "Max items per page (default 25)"
                    }
                },
                "required": ["ewm_project"]
            }
        ),
        Tool(
            name="get_ewm_workitem_types",
            description=(
                "List the available work item types in an EWM project — Epic, "
                "Capability, Story, Task, Defect, etc. — whatever the project's "
                "process configuration exposes. Use this BEFORE `create_task` / "
                "`create_defect` when you need to know what types are available "
                "(e.g. when importing a Jira epic and figuring out what the "
                "EWM-side equivalent is called). Returns name, creation_url, "
                "shape_url for each type. Show the user the actual list rather "
                "than guessing what types might exist."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ewm_project": {
                        "type": "string",
                        "description": "EWM project number or name (use list_projects domain='ewm' to find it)"
                    }
                },
                "required": ["ewm_project"]
            }
        ),
        # ── Cross-domain link creation ─────────────────────────
        Tool(
            name="create_link",
            description=(_WRITE_GATE +
                "Create an OSLC link between two artifacts that already exist. Use this "
                "when the link wasn't created at artifact-creation time — e.g. linking an "
                "existing EWM task to an existing DNG requirement after the fact. For "
                "NEW artifacts, prefer `create_task` / `create_test_case` / "
                "`create_requirements` with the link arguments — those write the link "
                "atomically as part of creation.\n\n"
                "PICK THE RIGHT link_type_uri based on the source/target combination:\n\n"
                "  • EWM workitem → DNG requirement (Implements):\n"
                "      http://open-services.net/xmlns/prod/jazz/calm/1.0/implementsRequirement\n"
                "  • ETM test case → DNG requirement (Validates):\n"
                "      http://open-services.net/ns/qm#validatesRequirement\n"
                "  • DNG req → DNG req (Satisfies, Derived From, etc.):\n"
                "      Call get_link_types(project_identifier) first to discover\n"
                "      the project's actual link type URLs (LT_xxx). The list\n"
                "      varies by project — never guess.\n"
                "  • EWM workitem → EWM workitem (parent/child, related, blocks):\n"
                "      http://open-services.net/ns/cm#parent  (parent of)\n"
                "      http://open-services.net/ns/cm#tracksWorkItem  (tracks)\n\n"
                "Auto-detects source domain (DNG / EWM / ETM) from the URL prefix and uses "
                "GET-ETag → PUT-If-Match on the source resource. NOTE: DNG normalizes "
                "custom link-type predicates after PUT."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "source_url": {
                        "type": "string",
                        "description": "Full URL of the source artifact (DNG req, EWM workitem, or ETM test case). The link is stored on the source side of the relationship."
                    },
                    "link_type_uri": {
                        "type": "string",
                        "description": "The full link-type URI. See the cheat sheet in this tool's description for common values. For DNG-internal links, call get_link_types first to discover the project-specific LT_ URLs — don't guess."
                    },
                    "target_url": {
                        "type": "string",
                        "description": "Full URL of the target artifact (the thing the source points at)"
                    }
                },
                "required": ["source_url", "link_type_uri", "target_url"]
            }
        ),
        Tool(
            name="link_workitem_to_external_url",
            description=(_WRITE_GATE +
                "Attach an external URL (GitHub PR, GitLab MR, Bitbucket "
                "commit, Confluence page — anything outside ELM) to an EWM "
                "work item as a clickable reference. Lightweight cross-tool "
                "integration: the external system doesn't need to speak OSLC, "
                "we just store the URL on the EWM side. Use this for teams "
                "hosting code in GitHub instead of Jazz SCM — link a task to "
                "its PR so the trace web in EWM connects to the actual code "
                "review. Uses oslc_cm:relatedURL — EWM displays it under "
                "Links → References."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "workitem_url": {
                        "type": "string",
                        "description": "Full EWM work-item URL"
                    },
                    "external_url": {
                        "type": "string",
                        "description": "External URL to attach (GitHub PR, etc.)"
                    },
                    "label": {
                        "type": "string",
                        "description": "Display label for the link (default 'External link'). Used in confirmation message; the OSLC predicate is fixed at relatedURL."
                    },
                    "comment": {
                        "type": "string",
                        "description": "Optional comment about why this link exists"
                    }
                },
                "required": ["workitem_url", "external_url"]
            }
        ),
        Tool(
            name="elm_mcp_health",
            description=(
                "Self-diagnose tool — returns connection state, MCP version, "
                "auto-update status, active build runs, environment summary. "
                "Call this when something feels broken: 'Bob, what's your "
                "health?' / 'are you connected?' / 'what's wrong?'. Returns "
                "everything the user (or you) need to debug an issue without "
                "running setup.py --diagnose by hand. Read-only."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        # ── EWM: defect creation ───────────────────────────────
        Tool(
            name="create_defect",
            description=(_WRITE_GATE +
                "Create an EWM Defect work item. Resolves the project category for "
                "`rtc_cm:filedAgainst` automatically (process rules typically reject the "
                "Unassigned default — this tool picks the first concrete category). Severity "
                "can be a friendly name (Minor/Moderate/Major/Critical) or a literal URI. "
                "Optional cross-links: requirement_url (calm:affectedByDefect) and "
                "test_case_url (oslc_cm:relatedTestCase). "
                "Use list_projects domain='ewm' first."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ewm_project": {
                        "type": "string",
                        "description": "EWM project number or name"
                    },
                    "title": {
                        "type": "string",
                        "description": "Defect title"
                    },
                    "description": {
                        "type": "string",
                        "description": "Description / repro steps"
                    },
                    "severity": {
                        "type": "string",
                        "description": "Optional severity label (Minor / Moderate / Major / Critical / Blocker / Unclassified)"
                    },
                    "requirement_url": {
                        "type": "string",
                        "description": "Optional DNG requirement URL — links via calm:affectedByDefect"
                    },
                    "test_case_url": {
                        "type": "string",
                        "description": "Optional ETM test case URL — links via oslc_cm:relatedTestCase"
                    }
                },
                "required": ["ewm_project", "title"]
            }
        ),
        # ── SCM (read-only) ────────────────────────────────────
        Tool(
            name="scm_list_projects",
            description=(
                "List all CCM/EWM project areas that have an SCM service provider. "
                "Reads /ccm/oslc-scm/catalog (note the hyphen — not underscore). "
                "Returns name, projectAreaId, providerUrl. Use this before scm_list_changesets "
                "to filter by project."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        Tool(
            name="scm_list_changesets",
            description=(
                "List recent SCM change-sets via the TRS feed at "
                "/ccm/rtcoslc/scm/reportable/trs/cs. Each TRS page exposes ~5 most-recent "
                "items so this tool walks <trs:previous> until `limit` is reached. "
                "For each change-set, returns itemId, title, component, author, modified, "
                "totalChanges, and any work-item links (resolved via /ccm/rtcoslc/scm/cslink/trs). "
                "Optional `project_name` filter restricts to one project area."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "Optional project name (substring match) — call scm_list_projects to see options"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max change-sets to return (default 25)"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="scm_get_changeset",
            description=(
                "Fetch a single SCM change-set by its itemId (the `_xxx...` token). "
                "GETs /ccm/rtcoslc/scm/reportable/cs/<id> for metadata and constructs the "
                "canonical /ccm/resource/itemOid/com.ibm.team.scm.ChangeSet/<id> URL. "
                "Returns full metadata + linked work items + raw RDF. "
                "Pass an itemId obtained from scm_list_changesets."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "changeset_id": {
                        "type": "string",
                        "description": "Change-set item ID (e.g. '_UrB4WENEEfGL3a8XuCNang' — leading underscore optional)"
                    }
                },
                "required": ["changeset_id"]
            }
        ),
        Tool(
            name="scm_get_workitem_changesets",
            description=(
                "List the SCM change-sets attached to a single EWM work item. "
                "GETs /ccm/resource/itemName/com.ibm.team.workitem.WorkItem/<id> and parses "
                "the rtc_cm:com.ibm.team.filesystem.workitems.change_set.com.ibm.team.scm.ChangeSet "
                "triples. Returns [{changeSetId, title, url}]. Empty list if the WI has no "
                "code attached — that's normal."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "workitem_id": {
                        "type": "string",
                        "description": "Numeric work-item ID (e.g. '3323')"
                    }
                },
                "required": ["workitem_id"]
            }
        ),
        Tool(
            name="review_get",
            description=(
                "Fetch review-relevant fields for an EWM work item: title, state, type, "
                "approved/reviewed booleans, approval records, linked change-sets, and the "
                "comments URL. Approval shape: {approver, descriptor, stateName, stateIdentifier}. "
                "Works on any work item — review-typed work items are not required (the "
                "approval shape is universal)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "workitem_id": {
                        "type": "string",
                        "description": "Numeric work-item ID"
                    }
                },
                "required": ["workitem_id"]
            }
        ),
        Tool(
            name="review_list_open",
            description=(
                "List open EWM review work items in a project (type = "
                "com.ibm.team.review.workItemType.review and oslc_cm:closed=false). "
                "Most projects on this server have zero review-typed WIs — that's not an "
                "error, the OSLC query simply returns an empty list. Use review_get on any "
                "work item to read its approvals."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ewm_project": {
                        "type": "string",
                        "description": "EWM project number or name"
                    }
                },
                "required": ["ewm_project"]
            }
        ),
    ]


# ── Tool Handlers ─────────────────────────────────────────────

@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    global _client, _projects_cache, _ewm_projects_cache, _etm_projects_cache
    global _modules_cache, _last_requirements, _last_module_name, _last_project_name
    global _folder_cache

    logger.info("Tool called: %s", name)

    try:
        # ── connect_to_elm ────────────────────────────────────
        if name == "connect_to_elm":
            url = arguments.get("url", "").strip().rstrip('/')
            username = arguments.get("username", "").strip()
            password = arguments.get("password", "").strip()

            if not all([url, username, password]):
                return [TextContent(type="text", text="Error: url, username, and password are all required.")]

            # Pass the URL as-is — the client normalizes it and sets up all endpoints
            client = DOORSNextClient(url, username, password)
            auth_result = client.authenticate()
            if not auth_result['success']:
                return [TextContent(type="text", text=(
                    f"Failed to connect: {auth_result['error']}\n\n"
                    "Please check:\n"
                    "- URL is correct (e.g., https://your-server.com)\n"
                    "- Username and password are correct\n"
                    "- The server is reachable from this machine"
                ))]

            _client = client
            # Clear all caches on new connection
            _ewm_projects_cache.clear()
            _etm_projects_cache.clear()
            _modules_cache.clear()
            _folder_cache.clear()
            _last_requirements.clear()

            projects = _client.list_projects()
            _projects_cache = projects

            body = (
                f"Successfully connected to IBM ELM (ELM MCP v{__version__}).\n\n"
                f"**Endpoints configured:**\n"
                f"- DNG (requirements): `{client.base_url}`\n"
                f"- EWM (work items / SCM): `{client.ccm_url}`\n"
                f"- ETM (test mgmt): `{client.qm_url}`\n\n"
                f"Found **{len(projects)}** DNG projects.\n\n"
                f"**What I can do:**\n"
                f"- **DNG** — Read, create, and update requirements. Create modules and "
                f"automatically populate them with requirements (no manual drag-bind needed). "
                f"Import PDFs. Create and compare baselines.\n"
                f"- **EWM** — Create Tasks and Defects, transition workflow states, "
                f"query work items, update arbitrary fields.\n"
                f"- **ETM** — Create Test Cases and record Test Results (pass/fail).\n"
                f"- **SCM** — Inspect change-sets and code reviews linked to work items.\n"
                f"- **Full Lifecycle** — Requirements → Tasks → Test Cases → Defects, "
                f"all cross-linked.\n\n"
                f"Which project would you like to work with?"
            )
            return [TextContent(type="text", text=_maybe_append_update_notice(body))]

        # ── update_elm_mcp (no ELM connection needed) ─────────
        if name == "build_project_next":
            current_phase = arguments.get("current_phase")
            user_signal = (arguments.get("user_signal") or "").strip()
            context = (arguments.get("context") or "").strip()
            run_id = (arguments.get("run_id") or "").strip()

            if current_phase is None or not isinstance(current_phase, int) or current_phase < 0 or current_phase > 8:
                return [TextContent(type="text", text=(
                    "Error: current_phase is required and must be an integer 0–8. "
                    "Pass the phase number you JUST finished (e.g. current_phase=2 "
                    "means you finished Phase 2 and are asking for Phase 3). "
                    "Phase 7 advances to a new Phase 7.5 (code-review gate) before "
                    "Phase 8."
                ))]

            # If run_id provided, look up the run. State persists across phases.
            run = _get_run(run_id) if run_id else None
            if run_id and not run:
                # User passed a run_id we don't recognize — likely server
                # restart between phases. Surface clearly so AI knows to
                # start fresh OR continue without state.
                return [TextContent(type="text", text=(
                    f"⚠️ run_id `{run_id}` not found in active runs.\n\n"
                    f"Likely cause: the MCP server restarted between phases "
                    f"(state is in-memory; doesn't survive restart). Two options:\n\n"
                    f"  1. **Restart the build flow** — call "
                    f"`build_new_project` or `build_from_existing` again with "
                    f"the user's original idea. They'll get a fresh run_id and "
                    f"you'll need to redo any phases that were already approved.\n"
                    f"  2. **Continue without state** — re-call "
                    f"`build_project_next` without the `run_id` argument. "
                    f"You'll lose drift detection at Phase 6 and traceability "
                    f"matrix at Phase 9 (both depend on stored state), but "
                    f"approval gates still work.\n\n"
                    f"Currently active runs: "
                    f"{[r['run_id'] for r in _list_active_runs()] or 'none'}"
                ))]

            # Approval-signal validation. We accept "yes"/"go ahead"/etc. (1+ word
            # approvals) AND longer messages that include those tokens. We REJECT:
            # empty, just whitespace, or a clear non-approval ("no", "stop",
            # "wait", "not yet", "let me think").
            #
            # Word lists are CONSERVATIVE — bare verbs like "do", "go", "build",
            # "push", "pull", "continue" were removed because they trip on
            # questions ("do I need to approve each one?", "go where?", "can
            # you push when I say so?"). Multi-word phrases ("go ahead", "push
            # it", "build it") still match via substring on signal_lower.
            approval_words = {
                "yes", "yeah", "yep", "yup", "approved", "approve", "approves",
                "ok", "okay", "lgtm", "ship", "ships",
                "looks", "perfect", "alright", "confirmed", "confirm",
            }
            approval_phrases = {
                "go ahead", "push it", "push them", "ship it", "build it",
                "looks good", "let's go", "lets go", "proceed", "continue with",
                "do it", "make it so", "go for it",
            }
            rejection_words = {
                "no", "stop", "wait", "hold", "cancel", "abort", "reject",
                "rejected", "skip", "skipped",
            }
            rejection_phrases = {
                "not yet", "not now", "don't", "dont", "do not",
                "hold on", "hold up", "let me think",
                "wait for", "wait until", "stop right",
                "i don't", "i dont", "i'm not", "im not",
            }
            signal_lower = user_signal.lower()
            signal_tokens = set(t.strip(".,!?;:") for t in signal_lower.split())

            if not user_signal:
                return [TextContent(type="text", text=(
                    "🚦 GATE LOCKED — user_signal is empty.\n\n"
                    "You cannot advance to the next phase without the user's "
                    "verbatim approval text. Go back to the user, show them the "
                    "preview again, ask explicitly *'should I push these to ELM "
                    "and continue?'*, and only call build_project_next once they "
                    "actually reply with approval. The user merely being silent, "
                    "or you assuming they're satisfied, does NOT count."
                ))]

            # Detect rejection (token OR multi-word phrase). Critically, a
            # rejection PHRASE like "do not push" beats any approval word in
            # the same string — phrase-match wins because it's more specific.
            rejection_phrase_hit = any(rp in signal_lower for rp in rejection_phrases)
            rejection_token_hit = bool(signal_tokens & rejection_words)
            approval_phrase_hit = any(ap in signal_lower for ap in approval_phrases)
            approval_token_hit = bool(signal_tokens & approval_words)

            # Rejection wins if there's a rejection phrase, OR a rejection
            # token without any approval signal at all.
            if rejection_phrase_hit or (rejection_token_hit and not (approval_phrase_hit or approval_token_hit)):
                return [TextContent(type="text", text=(
                    f"🚦 GATE LOCKED — user said something that looks like a "
                    f"REJECTION, not an approval.\n\n"
                    f"You sent: \"{user_signal}\"\n\n"
                    f"That doesn't read as approval. The user may want changes, may "
                    f"want to stop, or may be asking a question. Address what they "
                    f"actually said — don't try to advance. If they want changes, "
                    f"revise the preview and re-show it, then ask again. If they "
                    f"want to stop the build, acknowledge and end."
                ))]

            # Approval requires either an approval phrase ("go ahead", "ship
            # it", "looks good") OR an approval token ("yes", "ok", "lgtm").
            matched = signal_tokens & approval_words
            matched_phrases = {ap for ap in approval_phrases if ap in signal_lower}
            if not matched and not matched_phrases:
                return [TextContent(type="text", text=(
                    f"🚦 GATE LOCKED — user_signal doesn't contain explicit approval.\n\n"
                    f"You sent: \"{user_signal}\"\n\n"
                    f"This needs to contain a clear approval word: yes / go ahead / "
                    f"approved / continue / ship it / push them / looks good / etc.\n\n"
                    f"If the user is asking a question or requesting changes, that's "
                    f"NOT approval — handle their request first, then re-ask. If "
                    f"they truly approved but used unusual phrasing, ask them to "
                    f"confirm with 'yes' before calling this tool."
                ))]

            # Phase 7 advances to 7.5 (review gate), then 7.5 to 8.
            if current_phase == 7:
                next_phase = 7.5
            elif current_phase == 7.5 or (isinstance(current_phase, float) and abs(current_phase - 7.5) < 0.01):
                next_phase = 8
            else:
                next_phase = current_phase + 1

            # Persist state on the run if we have one.
            if run is not None:
                run["current_phase"] = next_phase
                run["approval_signals"][str(current_phase)] = user_signal
                _touch_run(run)

            ctx_block = f"\n\n**Context from prior phase:** {context}" if context else ""
            all_matches = sorted(matched) + sorted(matched_phrases)
            run_block = (
                f"\n\n**Run state:** `{run['run_id']}` at phase {next_phase}. "
                f"`build_project_status(run_id=\"{run['run_id']}\")` shows "
                f"all artifacts so far."
                if run else ""
            )
            ack = (f"✓ Phase {current_phase} approved (matched on: "
                   f"{', '.join(all_matches) if all_matches else 'approval'}). "
                   f"Advancing to Phase {next_phase}.{run_block}")

            phase_scripts = {
                1: ("PHASE 1 — PROJECT INTAKE INTERVIEW",
                    "Ask the user 4–6 short questions, ONE AT A TIME. Wait for each "
                    "answer before the next:\n\n"
                    "  1. One-paragraph description of what the user does with this "
                    "thing\n"
                    "  2. Tech stack / platform (web app? embedded? API service? mobile?)\n"
                    "  3. Standards or compliance (DO-178C / ISO 26262 / NIST / none)\n"
                    "  4. Approximate scale (5–10 reqs / 15–25 / 30+)\n"
                    "  5. Integrations or external interfaces?\n"
                    "  6. Anything specific that MUST or MUST NOT be included?\n\n"
                    "After answers, confirm a one-line scope back to the user. When "
                    "they say 'yes that's right', call `build_project_next("
                    "current_phase=1, user_signal=<their actual reply>)` to advance "
                    "to Phase 2."),
                2: ("PHASE 2 — REQUIREMENTS (DNG)",
                    "Run BOB.md Step 3b (single-tier) or Step 3g (tiered) per the "
                    "tier_mode you started with. Generate internally → preview-with-"
                    "module-structure (table of all reqs grouped by proposed module "
                    "with rationale per group) → wait for explicit user approval → "
                    "call create_requirements with module_name set so reqs auto-bind. "
                    "Surface module + every requirement URL as markdown links.\n\n"
                    "Server-side validation rejects bodies containing 'Acceptance "
                    "Criteria', 'Business Value', 'Stakeholder Need', 'Test Steps' "
                    "headers — those go in test cases (Phase 4) or higher tiers. Each "
                    "requirement = one 'shall' statement, optionally with a "
                    "'Rationale:' line.\n\n"
                    "After requirements are pushed, call `build_project_next("
                    "current_phase=2, user_signal=<user's approval text>, "
                    "context='<comma-separated requirement URLs>')`."),
                3: ("PHASE 3 — IMPLEMENTATION TASKS (EWM)",
                    "Run BOB.md Step 3d. One EWM Task per System Requirement (skip "
                    "Business/Stakeholder tiers if tiered). Verb-first titles. Brief "
                    "task body — Objective + Deliverables + Dependencies. Don't copy "
                    "the requirement body — it's already linked. Preview → user "
                    "approval → create_task per task with requirement_url set "
                    "verbatim from the requirement URL.\n\n"
                    "After tasks are pushed, call `build_project_next("
                    "current_phase=3, user_signal=<user's reply>, "
                    "context='<task URLs>')`."),
                4: ("PHASE 4 — TEST CASES (ETM)",
                    "Run BOB.md Step 3e. One Test Case per System Requirement, with "
                    "full Preconditions / Test Steps / Pass-Fail Criteria — these DO "
                    "belong in test cases. Optionally also create_test_script for "
                    "detailed numbered procedures linked via test_case_url. Preview "
                    "→ user approval → push linked.\n\n"
                    "After tests are pushed, call `build_project_next("
                    "current_phase=4, user_signal=<user's reply>, "
                    "context='<test case URLs>')`."),
                5: ("PHASE 5 — STOP. USER REVIEWS IN ELM.",
                    "**This is the most important gate. Do NOT write any code yet.**\n\n"
                    "Tell the user verbatim:\n\n"
                    "> 'Phases 2–4 are complete. Open ELM and review:\n"
                    "> - DNG modules: <markdown links>\n"
                    "> - EWM tasks: <markdown links>\n"
                    "> - ETM test cases: <markdown links>\n"
                    ">\n"
                    "> In ELM you can: approve / reject / modify any artifact, mark "
                    "requirement statuses (only Approved reqs drive the code in "
                    "Phase 7), reassign tasks, rewrite tests, add or drop anything.\n"
                    ">\n"
                    "> When you\\'re done — come back and say *continue* / *build it* "
                    "/ *pull latest*. I\\'ll re-fetch the current ELM state and start "
                    "writing the actual app code.'\n\n"
                    "Then **wait silently**. Do NOT poll, do NOT advance to Phase 6 "
                    "until the user explicitly says continue. They may take 5 "
                    "minutes, 5 hours, or 5 days — that's fine.\n\n"
                    "When they signal continue, call `build_project_next("
                    "current_phase=5, user_signal=<their reply>)`."),
                6: ("PHASE 6 — RE-PULL CURRENT ELM STATE + DRIFT DETECTION",
                    "User has reviewed in ELM and signaled continue. NOW perform "
                    "real drift detection — compare current ELM state against the "
                    "artifacts this run created at Phases 2–4.\n\n"
                    "Step 1: discover the project's 'approved' status value.\n"
                    "  - Call `get_attribute_definitions` on the DNG project. "
                    "Look for the 'Status' attribute → Allowed Values. Pick the "
                    "value that semantically means 'approved' for this project "
                    "(could be 'Approved', 'Accepted', 'Ready', etc. — don't guess).\n"
                    "  - If you have a run_id, save it to the run via the next "
                    "`build_project_next` context so subsequent phases can use it.\n\n"
                    "Step 2: drift detection (only meaningful if you have run_id).\n"
                    "  - Call `build_project_status(run_id=...)` to see what was "
                    "created at Phases 2–4.\n"
                    "  - For each requirement URL stored in the run, GET it from "
                    "DNG. Compare current `dcterms:modified` against the run's "
                    "stored `modified_at`. If different → the user edited it.\n"
                    "  - For each task URL, query its current state — was it "
                    "transitioned, reassigned, or closed?\n"
                    "  - For each test URL, check it still exists (404 = deleted).\n"
                    "  - List drift findings: `unchanged: N`, `modified: [REQ-7]`, "
                    "`deleted: [TC-9]`, plus any newly-added artifacts the human "
                    "created in DNG that aren't in the run's records.\n\n"
                    "Step 3: re-pull approved subset.\n"
                    "  - `get_module_requirements` with filter for the approved "
                    "status value.\n"
                    "  - `query_work_items` for active EWM tasks "
                    "(`oslc.where=oslc_cm:closed=false`).\n"
                    "  - Verify test cases via validatesRequirement backlinks.\n\n"
                    "Step 4: show user a current-state summary with drift detail:\n"
                    "  *'After your review:\n"
                    "  - 14 reqs total, 12 Approved, 2 Rejected\n"
                    "  - REQ-7 was edited (text changed since I generated it)\n"
                    "  - 2 new reqs added by you (REQ-15, REQ-16)\n"
                    "  - All 14 tasks still active\n"
                    "  - 1 test case (TC-9) deleted\n"
                    "  Building based on the 12 approved reqs. OK to proceed?'*\n\n"
                    "When user confirms, call `build_project_next(current_phase=6, "
                    "user_signal=<reply>, run_id=<run_id>, context='<approved-state "
                    "value, final URLs>')`."),
                7: ("PHASE 7 — WRITE THE CODE",
                    "User approved Phase 6's current state. NOW write the actual "
                    "application code in the user's IDE using the AI host's "
                    "editing capabilities.\n\n"
                    "Every file gets a header comment listing the requirement IDs "
                    "it implements:\n"
                    "```\n"
                    "# Implements: REQ-005, REQ-007\n"
                    "# Source: <DNG req URLs>\n"
                    "```\n"
                    "Code structure should mirror requirement structure where "
                    "reasonable.\n\n"
                    "When code is written and the user has had a chance to inspect, "
                    "ask the user explicitly: *'Code is written. Want to open a "
                    "PR/code review now (Phase 7.5), or skip the review gate and "
                    "go straight to marking tasks Resolved (Phase 8)?'*\n\n"
                    "On approval to advance, call build_project_next("
                    "current_phase=7, user_signal=<reply>, context='<files written, "
                    "key reqs implemented>'). Phase 7 always advances to "
                    "Phase 7.5 — the review gate."),
                7.5: ("PHASE 7.5 — CODE-REVIEW GATE",
                    "Code is written but not yet marked Resolved. Before "
                    "transitioning tasks (Phase 8), ensure SOMEONE has reviewed "
                    "the code. The team's review surface varies — don't impose:\n\n"
                    "  - **Solo iteration**: paste the diff in chat, user reads, "
                    "    says 'looks good'\n"
                    "  - **GitHub PR workflow**: open the PR via `gh pr create` "
                    "    (or have user open it), share the URL, user reads in "
                    "    GitHub, comes back with 'approved' / 'merged'\n"
                    "  - **Jazz code review**: create an EWM review work item "
                    "    linked to the change set, request reviewers, wait for "
                    "    Approval records to come in\n"
                    "  - **No review needed** (e.g. throwaway prototype): user "
                    "    explicitly says 'skip review'\n\n"
                    "ASK the user: *'Where do you do code review for this "
                    "project? GitHub PR / Jazz code review / chat / skip?'* Then "
                    "wait. Don't poll, don't peek, don't pretend.\n\n"
                    "Once they confirm review is done — *'PR approved'*, *'Sarah "
                    "signed off'*, *'merged'*, *'looks good'* — call "
                    "`build_project_next(current_phase=7.5, user_signal=<their "
                    "reply>, run_id=<run_id>)` to advance to Phase 8.\n\n"
                    "If they say *'skip review'* or *'no review needed'*, that's "
                    "still an explicit signal — pass it as the user_signal and "
                    "the gate accepts it (treats 'skip' as a valid override).\n\n"
                    "**Anti-pattern:** marking tasks Resolved in Phase 8 without "
                    "any human reviewing the code. The whole point of this gate "
                    "is to ensure that doesn't happen."),
                8: ("PHASE 8 — TRACK WORK + RECORD RESULTS",
                    "Walk through each task and test:\n"
                    "  - As each task is implemented: transition_work_item("
                    "workitem_url, 'In Development') when starting, "
                    "transition_work_item(... 'Resolved') when complete.\n"
                    "  - For each test case once code is in place:\n"
                    "    * passes → create_test_result(test_case_url, "
                    "status='passed')\n"
                    "    * fails → create_test_result(... status='failed') AND "
                    "interview the user briefly about the failure (steps, expected "
                    "vs actual, severity), then create_defect linked to the "
                    "requirement and test case URLs.\n\n"
                    "When all tasks/tests are walked, call build_project_next("
                    "current_phase=8, user_signal=<reply>) for the final summary."),
                9: ("PHASE 9 — FINAL SUMMARY + TRACEABILITY MATRIX",
                    "Build complete. The deliverable is the traceability matrix "
                    "plus a state summary.\n\n"
                    "Step 1: call `generate_traceability_matrix(run_id=<run_id>)`. "
                    "It returns a markdown table linking every requirement to "
                    "its tasks, test cases, results, and defects-if-any. Surface "
                    "the table inline.\n\n"
                    "Step 2: short state summary using markdown links:\n\n"
                    "  - DNG: [Module name](url) — N reqs ({M} Approved, {K} "
                    "Rejected)\n"
                    "  - EWM: {N} tasks total — {M} Resolved, {K} In Progress, {J} "
                    "blocked\n"
                    "  - ETM: {N} tests — {M} passed ✅, {K} failed ❌, {J} blocked\n"
                    "  - Defects: [open defect list](url) — {N} open, all linked "
                    "back to source reqs\n"
                    "  - Code: {F} files written, every file has 'Implements REQ-…' "
                    "headers\n\n"
                    "End with: 'The complete trace is in ELM: requirement → task → "
                    "test → result → defect-if-any. Click any link above to "
                    "inspect.'\n\n"
                    "🎬 BUILD COMPLETE. Do not call build_project_next again."),
            }

            if next_phase not in phase_scripts:
                # next_phase == 9 means user just signaled approval after Phase 8
                if next_phase == 9:
                    title, body = phase_scripts[9]
                    return [TextContent(type="text", text=f"{ack}\n\n## {title}\n\n{body}{ctx_block}")]
                return [TextContent(type="text", text=(
                    f"{ack}\n\nThere is no Phase {next_phase}. The build flow ends "
                    f"at Phase 9 (final summary). If you finished Phase 9, the "
                    f"build is complete — do not call this tool again."
                ))]

            title, body = phase_scripts[next_phase]
            return [TextContent(type="text", text=f"{ack}\n\n## {title}\n\n{body}{ctx_block}")]

        # ── build_project_status ──────────────────────────────────
        if name == "build_project_status":
            run_id = (arguments.get("run_id") or "").strip()
            if not run_id:
                # No run_id → list all active runs
                runs = _list_active_runs()
                if not runs:
                    return [TextContent(type="text", text=(
                        "No active build-project runs. Start one with "
                        "`build_new_project` (greenfield) or `build_from_existing` "
                        "(brownfield)."
                    ))]
                lines = [f"# Active build-project runs ({len(runs)})", ""]
                for r in runs:
                    lines.append(
                        f"- **`{r['run_id']}`** [{r['command']}] phase={r['phase']} "
                        f"started={r['started_at'][:19]}\n  idea: {r['idea']}"
                    )
                lines.append("")
                lines.append("Pass `run_id=<id>` to see full state for a specific run.")
                return [TextContent(type="text", text="\n".join(lines))]

            run = _get_run(run_id)
            if not run:
                return [TextContent(type="text", text=(
                    f"Run `{run_id}` not found. Active runs: "
                    f"{[r['run_id'] for r in _list_active_runs()] or 'none'}"
                ))]

            artifacts = run.get("artifacts", {})
            lines = [
                f"# Run `{run['run_id']}` — status",
                "",
                f"- **Command:** {run.get('command', 'unknown')}",
                f"- **Current phase:** {run.get('current_phase', 0)}",
                f"- **Tier mode:** {run.get('tier_mode', 'single')}",
                f"- **Idea:** {run.get('project_idea', '')}",
                f"- **Started:** {run.get('started_at', '')}",
                f"- **Last update:** {run.get('last_updated_at', '')}",
                "",
                "## Project URLs",
            ]
            urls = run.get("project_urls", {}) or {}
            for k in ("dng", "ewm", "etm"):
                v = urls.get(k, "")
                lines.append(f"- {k.upper()}: {v if v else '_(not set)_'}")
            lines.append("")
            lines.append("## Artifacts created so far")
            for kind, items in artifacts.items():
                lines.append(f"### {kind} ({len(items)})")
                for it in items[:50]:
                    lines.append(f"- [{it.get('title', '?')}]({it.get('url', '')})")
                if len(items) > 50:
                    lines.append(f"_(+{len(items)-50} more)_")
                lines.append("")
            sigs = run.get("approval_signals", {})
            if sigs:
                lines.append("## Approval signals received per phase")
                for ph in sorted(sigs.keys(), key=lambda x: float(x)):
                    lines.append(f"- Phase {ph}: \"{sigs[ph]}\"")
                lines.append("")
            drift = run.get("drift")
            if drift:
                lines.append("## Drift detected at Phase 6")
                lines.append(f"- unchanged: {drift.get('unchanged', 0)}")
                lines.append(f"- modified: {drift.get('modified', [])}")
                lines.append(f"- deleted: {drift.get('deleted', [])}")
                lines.append(f"- added externally: {drift.get('added_externally', [])}")
                lines.append("")
            return [TextContent(type="text", text="\n".join(lines))]

        # ── build_project_resume ──────────────────────────────────
        if name == "build_project_resume":
            run_id = (arguments.get("run_id") or "").strip()
            if not run_id:
                runs = _list_active_runs()
                if not runs:
                    return [TextContent(type="text", text=(
                        "No resumable build runs found. State is persisted to "
                        "`~/.elm-mcp/runs/` so previously-active runs survive "
                        "Bob restart. If you expected runs here:\n"
                        "  - Check `~/.elm-mcp/runs/` for `*.json` files\n"
                        "  - Make sure you're using the same install of "
                        "elm-mcp as last time\n\n"
                        "To start fresh, call `build_new_project` (greenfield) "
                        "or `build_from_existing` (brownfield)."
                    ))]
                # Sort by last_updated_at descending so most-recent shows first
                runs.sort(key=lambda r: r.get('last_updated_at', ''), reverse=True)
                lines = [f"# Resumable build runs ({len(runs)})", ""]
                for r in runs:
                    lines.append(
                        f"- **`{r['run_id']}`** [{r['command']}] phase={r['phase']}\n"
                        f"  - idea: {r['idea']}\n"
                        f"  - last update: {r['last_updated_at'][:19]}"
                    )
                lines.append("")
                lines.append(
                    "Tell the user about each run and ask which they want to "
                    "resume. Then call `build_project_resume(run_id=<id>)` to "
                    "load that one's state and get the next-phase instructions."
                )
                return [TextContent(type="text", text="\n".join(lines))]

            run = _get_run(run_id)
            if not run:
                # Try one more time from disk in case the run was created
                # by a different server process
                _load_runs_from_disk()
                run = _get_run(run_id)
            if not run:
                return [TextContent(type="text", text=(
                    f"Run `{run_id}` not found in memory or on disk. "
                    f"Check `~/.elm-mcp/runs/` to see what's available, or "
                    f"call `build_project_resume()` (no arg) to list active runs."
                ))]

            current_phase = run.get('current_phase', 0)
            arts = run.get('artifacts', {}) or {}
            counts = {k: len(v) for k, v in arts.items()}

            # Figure out the natural next action based on current phase
            if current_phase == 0:
                next_action = (
                    "The run hasn't progressed past Phase 0 (project setup). "
                    "Continue by completing Phase 1's intake interview, then "
                    "call `build_project_next(current_phase=1, ..., run_id="
                    f"\"{run_id}\")`."
                )
            elif current_phase >= 9:
                next_action = (
                    "The run completed Phase 9 (final summary). It's done — "
                    "no further phases. Use `generate_traceability_matrix("
                    f"run_id=\"{run_id}\")` to view the matrix again, or "
                    "`build_project_status` for the full state dump."
                )
            else:
                next_action = (
                    f"The run is at Phase {current_phase}. To continue: "
                    f"address whatever was pending at that phase, get the "
                    f"user's verbatim approval signal, then call "
                    f"`build_project_next(current_phase={current_phase}, "
                    f"user_signal=<their reply>, run_id=\"{run_id}\")`."
                )

            return [TextContent(type="text", text=(
                f"# Resumed run `{run['run_id']}`\n\n"
                f"**Project:** {run.get('project_idea', '?')}\n"
                f"**Command:** {run.get('command', 'unknown')}\n"
                f"**Current phase:** {current_phase}\n"
                f"**Tier mode:** {run.get('tier_mode', 'single')}\n"
                f"**Started:** {run.get('started_at', '')}\n"
                f"**Last update:** {run.get('last_updated_at', '')}\n\n"
                f"## Artifacts so far\n"
                f"- modules: {counts.get('modules', 0)}\n"
                f"- requirements: {counts.get('requirements', 0)}\n"
                f"- tasks: {counts.get('tasks', 0)}\n"
                f"- tests: {counts.get('tests', 0)}\n"
                f"- child workitems: {counts.get('child_workitems', 0)}\n\n"
                f"## What to do next\n\n"
                f"{next_action}\n\n"
                f"**Tell the user a brief summary** (project, phase, artifact "
                f"counts) then ask if they want to continue from where they "
                f"left off — or start over fresh."
            ))]

        # ── publish_build_state_to_dng ────────────────────────────
        if name == "publish_build_state_to_dng":
            run_id = (arguments.get("run_id") or "").strip()
            module_url = (arguments.get("module_url") or "").strip()
            shape_url = (arguments.get("shape_url") or "").strip()

            if not run_id:
                return [TextContent(type="text", text="Error: run_id is required.")]
            run = _get_run(run_id)
            if not run:
                return [TextContent(type="text", text=(
                    f"Run `{run_id}` not found. Active: "
                    f"{[r['run_id'] for r in _list_active_runs()] or 'none'}"
                ))]

            existing_artifact_url = run.get('dng_state_artifact_url', '')
            body = _render_run_as_markdown(run)
            title = f"[BOB-BUILD-STATE] {run.get('project_idea', '?')[:60]} ({run_id})"

            if existing_artifact_url:
                # Update existing artifact
                try:
                    upd = client.update_requirement(
                        existing_artifact_url,
                        title=title,
                        content=body,
                    )
                except AttributeError:
                    upd = {'error': 'client lacks update_requirement'}
                if upd and 'error' not in upd:
                    return [TextContent(type="text", text=(
                        f"# Build state updated in DNG\n\n"
                        f"Updated [{title}]({existing_artifact_url}) with "
                        f"current run state. Teammates can open the link to "
                        f"see where the build stands."
                    ))]
                err = upd.get('error', 'unknown') if upd else 'unknown'
                return [TextContent(type="text", text=(
                    f"Couldn't update existing artifact at "
                    f"{existing_artifact_url}: {err}. The run was modified in "
                    f"memory but not synced to DNG. Try with a fresh "
                    f"module_url to create a new artifact."
                ))]

            # Create new artifact
            if not module_url:
                # Need a target. Try to use the run's DNG project_url to find/create an "AI Build State" module.
                dng_url = (run.get('project_urls') or {}).get('dng', '')
                if not dng_url:
                    return [TextContent(type="text", text=(
                        "Error: no module_url provided and the run has no "
                        "DNG project URL recorded. Pass `module_url` to a "
                        "module where the build-state artifact should live "
                        "(typically a dedicated 'AI Build State' module)."
                    ))]
                # First try to find existing module by name
                try:
                    existing_mods = client.get_modules(dng_url) or []
                    target = next(
                        (m for m in existing_mods
                         if m.get('title', '').strip().lower() == 'ai build state'),
                        None,
                    )
                    if target:
                        module_url = target.get('url', '')
                    else:
                        # Create the module
                        new_mod = client.create_module(dng_url, "AI Build State",
                                                        "Auto-created by elm-mcp to track build-project run state for cross-team handoff.")
                        if new_mod and 'error' not in new_mod:
                            module_url = new_mod.get('url', '')
                except Exception as e:
                    return [TextContent(type="text", text=(
                        f"Error: could not find or create 'AI Build State' "
                        f"module: {e}"
                    ))]

            if not module_url:
                return [TextContent(type="text", text=(
                    "Error: could not resolve a target module for the "
                    "build-state artifact. Pass module_url explicitly."
                ))]

            # Resolve shape if not provided — pick System Requirement (any
            # shape works; this is just metadata wrapping a markdown body)
            dng_url = (run.get('project_urls') or {}).get('dng', '')
            if not shape_url and dng_url:
                try:
                    shapes = client.get_artifact_shapes(dng_url) or []
                    sysreq = next(
                        (s for s in shapes
                         if 'system requirement' in s.get('name', '').lower()),
                        None,
                    )
                    if sysreq:
                        shape_url = sysreq.get('url', '')
                    elif shapes:
                        shape_url = shapes[0].get('url', '')
                except Exception:
                    pass

            if not shape_url:
                return [TextContent(type="text", text=(
                    "Error: could not resolve an artifact shape for the "
                    "build-state artifact. Pass shape_url explicitly."
                ))]

            # Create the artifact in the module via create_requirements with module_name path,
            # then set dng_state_artifact_url on the run for future updates.
            try:
                # We use create_requirement (singular) on client to write atomically
                # without going through the create_requirements aggregator.
                new_art = client.create_requirement(
                    project_url=dng_url,
                    title=title,
                    content=body,
                    shape_url=shape_url,
                )
            except Exception as e:
                return [TextContent(type="text", text=(
                    f"Error: failed to create build-state artifact: {e}"
                ))]

            if new_art and 'error' not in new_art:
                art_url = new_art.get('url', '')
                run['dng_state_artifact_url'] = art_url
                _persist_run(run)
                # Try to bind into the module so it shows up there
                try:
                    client.add_to_module(module_url, [art_url])
                except Exception:
                    pass
                return [TextContent(type="text", text=(
                    f"# Build state published to DNG\n\n"
                    f"Created [{title}]({art_url}) in module {module_url}\n\n"
                    f"Teammates can open this URL anytime to see the build's "
                    f"current state — phase, artifacts, drift, approval "
                    f"history. The artifact will be updated in place after "
                    f"each subsequent phase. Pass it as `dng_state_artifact_url` "
                    f"in `build_project_resume(run_id=...)` to recover state "
                    f"from any machine.\n\n"
                    f"_Run state now has `dng_state_artifact_url` set; future "
                    f"`publish_build_state_to_dng` calls update in place._"
                ))]
            err = new_art.get('error', 'unknown') if new_art else 'unknown'
            return [TextContent(type="text", text=f"Error: {err}")]

        # ── generate_traceability_matrix ──────────────────────────
        if name == "generate_traceability_matrix":
            run_id = (arguments.get("run_id") or "").strip()
            if not run_id:
                return [TextContent(type="text", text=(
                    "Error: run_id is required. Pass the id returned by "
                    "`build_new_project` / `build_from_existing` / `build_project`."
                ))]
            run = _get_run(run_id)
            if not run:
                return [TextContent(type="text", text=(
                    f"Run `{run_id}` not found. Active runs: "
                    f"{[r['run_id'] for r in _list_active_runs()] or 'none'}"
                ))]
            arts = run.get("artifacts", {})
            reqs = arts.get("requirements", []) or []
            tasks = arts.get("tasks", []) or []
            tests = arts.get("tests", []) or []
            if not (reqs or tasks or tests):
                return [TextContent(type="text", text=(
                    f"Run `{run_id}` has no recorded artifacts yet. "
                    f"Traceability matrix needs at least requirements + tasks "
                    f"+ tests recorded via build_project_next context."
                ))]
            # Build a simple matrix. Without active link discovery, pair by
            # creation order (which matches the build flow's 1-task-per-req
            # / 1-test-per-req pattern). For cross-link verification, the AI
            # should follow up by querying actual links if needed.
            lines = [
                f"# Traceability Matrix — run `{run_id}`",
                f"_Project: {run.get('project_idea', '?')}_",
                "",
                "| # | Requirement | Task | Test Case |",
                "|---|---|---|---|",
            ]
            n = max(len(reqs), len(tasks), len(tests))
            for i in range(n):
                r = reqs[i] if i < len(reqs) else None
                t = tasks[i] if i < len(tasks) else None
                tc = tests[i] if i < len(tests) else None
                req_cell = f"[{r['title']}]({r['url']})" if r else "—"
                task_cell = f"[{t['title']}]({t['url']})" if t else "—"
                test_cell = f"[{tc['title']}]({tc['url']})" if tc else "—"
                lines.append(f"| {i+1} | {req_cell} | {task_cell} | {test_cell} |")
            lines.append("")
            lines.append(
                f"**Counts:** {len(reqs)} reqs · {len(tasks)} tasks · "
                f"{len(tests)} tests"
            )
            lines.append("")
            lines.append(
                "_Pairing is by creation order, which matches build_project's "
                "1-per-requirement convention. To verify actual cross-links, "
                "follow `oslc_cm:implementsRequirement` from each task and "
                "`oslc_qm:validatesRequirement` from each test._"
            )
            return [TextContent(type="text", text="\n".join(lines))]

        if name in ("build_project", "build_new_project", "build_from_existing"):
            idea = (arguments.get("project_idea") or "").strip()
            command_label = name  # one of build_project / build_new_project / build_from_existing
            source_kind = (arguments.get("source_kind") or "").strip().lower() if name == "build_from_existing" else ""
            source_path = (arguments.get("source_path") or "").strip() if name == "build_from_existing" else ""
            if not idea and name != "build_from_existing":
                return [TextContent(type="text", text=(
                    "Error: project_idea is required. Re-call with the user's "
                    "one-line description, e.g. project_idea='a temperature converter "
                    "web app' or 'a fleet maintenance scheduling service'."
                ))]
            dng = (arguments.get("dng_project") or "").strip()
            ewm = (arguments.get("ewm_project") or "").strip()
            etm = (arguments.get("etm_project") or "").strip()
            tier_mode = (arguments.get("tier_mode") or "single").strip().lower()
            if tier_mode not in ("single", "tiered"):
                tier_mode = "single"

            # Create a persistent run object so phase context survives across
            # build_project_next calls. The run_id is returned in the response
            # for the AI to remember and pass back.
            run = _new_run(
                command=command_label,
                project_idea=idea or (f"(from {source_kind} import)" if source_kind else "(unspecified)"),
                tier_mode=tier_mode,
                project_urls={"dng": dng, "ewm": ewm, "etm": etm},
            )

            # Pre-flight version check — surface at the very top so the user
            # can opt to update before starting a long build flow.
            preflight = _preflight_version_block()

            proj_lines = []
            if dng: proj_lines.append(f"- DNG project: **{dng}**")
            if ewm: proj_lines.append(f"- EWM project: **{ewm}**")
            if etm: proj_lines.append(f"- ETM project: **{etm}**")
            proj_block = "\n".join(proj_lines) if proj_lines else (
                "- DNG/EWM/ETM projects: **NOT SPECIFIED — ask the user before "
                "Phase 0 starts. Offer `list_projects` per domain if they don't know.**"
            )

            tier_text = (
                "Business → Stakeholder → System in 3 modules with Satisfies links between tiers"
                if tier_mode == "tiered"
                else "one System Requirements module"
            )

            # build_from_existing branches at Phase 1 — interview the user
            # about WHAT they have rather than running the greenfield intake.
            existing_branch = ""
            if name == "build_from_existing":
                source_intro = ""
                if source_kind == "pdf" and source_path:
                    source_intro = (
                        f"Source kind: **PDF** at `{source_path}`. Phase 1 "
                        f"will invoke `/import-work-item` to parse it.\n\n"
                    )
                elif source_kind == "text":
                    source_intro = (
                        "Source kind: **pasted requirements**. Phase 1 will "
                        "invoke `/import-requirements`.\n\n"
                    )
                elif source_kind == "module" and source_path:
                    source_intro = (
                        f"Source kind: **existing DNG module** at `{source_path}`. "
                        f"Phase 1 will read it (no creation; reuse).\n\n"
                    )
                else:
                    source_intro = (
                        "Source kind: **NOT SPECIFIED**. In Phase 1, ask the "
                        "user *exactly*: \"What do you have as input — (a) a "
                        "PDF of a work item / Jira epic, (b) requirements "
                        "pasted as text, (c) an existing DNG module URL, or "
                        "(d) a mix?\" Then route accordingly:\n"
                        "  - (a) → invoke /import-work-item, capture the "
                        "  resulting EWM/DNG/ETM URLs into this run via "
                        "  `build_project_next` context\n"
                        "  - (b) → invoke /import-requirements, capture the "
                        "  resulting module + req URLs\n"
                        "  - (c) → call `get_modules` + `get_module_requirements` "
                        "  on the URL, capture the URLs into the run\n"
                        "  - (d) → run multiple of the above sequentially\n\n"
                    )
                existing_branch = (
                    f"## 🌱 BUILD-FROM-EXISTING MODE\n\n"
                    f"This run starts from existing material rather than from "
                    f"scratch. {source_intro}"
                    f"After Phase 1 (import / read), the run converges with "
                    f"the standard flow at Phase 5 (user-review-pause). "
                    f"Phases 2–4 are SKIPPED if all three artifact types "
                    f"(reqs / tasks / tests) already exist; otherwise we "
                    f"fill in what's missing.\n\n"
                    f"---\n\n"
                )

            run_id_block = (
                f"## 🆔 RUN ID: `{run['run_id']}`\n\n"
                f"**Pass this run_id to every `build_project_next` call** so "
                f"phase context (project URLs, tier_mode, every artifact "
                f"created) persists across phases. Without run_id, state lives "
                f"only as long as your conversation memory — which means "
                f"context compaction can lose URLs and break Phase 6 drift "
                f"detection.\n\n"
                f"Helpful tools that use this run_id:\n"
                f"- `build_project_status(run_id=\"{run['run_id']}\")` — see "
                f"all artifacts created so far in any phase\n"
                f"- `generate_traceability_matrix(run_id=\"{run['run_id']}\")` "
                f"— produce the req↔task↔test matrix at Phase 9 (or any time)\n\n"
                f"---\n\n"
            )

            return [TextContent(type="text", text=(
                f"{preflight}"
                f"{existing_branch}"
                f"{run_id_block}"
                f"# 🎬 Agentic Project Build Started\n\n"
                f"**Project idea:** {idea}\n\n"
                f"**Tier mode:** {tier_mode} ({tier_text})\n\n"
                f"{proj_block}\n\n"
                f"---\n\n"
                f"## You are now in BUILD-PROJECT MODE.\n\n"
                f"Follow these 9 phases STRICTLY in order. **Do NOT skip ahead, "
                f"do NOT collapse phases, do NOT start writing code until "
                f"Phase 7.** Each phase has an explicit user-approval gate.\n\n"
                f"### PHASE 0 — Verify connection + projects\n"
                f"Call `connect_to_elm` if not connected. If any of the DNG / EWM "
                f"/ ETM project names above are missing, ask the user now. "
                f"Offer `list_projects` per domain if they don't know.\n\n"
                f"### PHASE 1 — Project intake interview (no tools, just questions)\n"
                f"Ask the user 4–6 short questions, ONE AT A TIME:\n"
                f"  1. One-paragraph description of what the user actually does with this thing\n"
                f"  2. Tech stack / platform (web app? embedded? API service? mobile?)\n"
                f"  3. Standards or compliance (DO-178C / ISO 26262 / NIST / none)\n"
                f"  4. Approximate scale (5–10 reqs / 15–25 / 30+)\n"
                f"  5. Integrations or external interfaces?\n"
                f"  6. Anything specific that MUST or MUST NOT be included?\n\n"
                f"After answers, confirm a one-line scope summary back to the user. "
                f"Get a 'yes' before Phase 2.\n\n"
                f"### PHASE 2 — Requirements (DNG)\n"
                f"Run **BOB.md Step 3b** (single-tier) "
                f"{'or **Step 3g** (tiered) — use Step 3g per the tier_mode arg' if tier_mode == 'tiered' else ''}.\n"
                f"Generate internally → preview-with-module-structure → user approves "
                f"→ call `create_requirements` with `module_name` set so reqs auto-bind. "
                f"Surface module + requirement URLs as markdown links.\n\n"
                f"Server-side validation rejects requirement bodies containing "
                f"'Acceptance Criteria', 'Business Value', 'Stakeholder Need', "
                f"'Test Steps' headers — those go in test cases (or higher tiers in "
                f"tiered mode). Each requirement = one 'shall' statement, optionally "
                f"with a 'Rationale:' line.\n\n"
                f"### PHASE 3 — Implementation tasks (EWM)\n"
                f"Run **BOB.md Step 3d**. One EWM Task per System Requirement. "
                f"Verb-first titles. Brief task body — Objective + Deliverables + "
                f"Dependencies (do NOT copy the requirement body into the task — it's "
                f"already linked). Preview → approval → `create_task` per task with "
                f"`requirement_url` set.\n\n"
                f"### PHASE 4 — Test cases (ETM)\n"
                f"Run **BOB.md Step 3e**. One Test Case per System Requirement, "
                f"with full Preconditions / Test Steps / Pass-Fail Criteria. "
                f"Optionally `create_test_script` for detailed procedure steps. "
                f"Preview → approval → push linked.\n\n"
                f"### PHASE 5 — STOP. User reviews in ELM.\n"
                f"**This is the most important gate. Do NOT write any code. Tell the user "
                f"verbatim:**\n\n"
                f"> 'Phases 2–4 complete. Open ELM and review:\n"
                f"> - DNG: <module markdown links>\n"
                f"> - EWM: <task markdown links>\n"
                f"> - ETM: <test markdown links>\n"
                f">\n"
                f"> In ELM you can: approve / reject / modify any artifact, mark "
                f"requirement statuses (only Approved reqs drive code in Phase 6), "
                f"reassign tasks, rewrite tests.\n"
                f">\n"
                f"> When you\\'re done — come back and say *continue* / *build it* / "
                f"*pull latest*. I\\'ll re-fetch the current ELM state and start writing "
                f"the actual app code based on what you finalized.'\n\n"
                f"Then **wait silently**. Do not poll, do not write code, do not "
                f"advance to Phase 6 until the user explicitly says continue.\n\n"
                f"### PHASE 6 — Re-pull current ELM state\n"
                f"On user 'continue':\n"
                f"  1. Call `get_attribute_definitions` on the DNG project to discover "
                f"the project's actual 'approved' status value (don't guess).\n"
                f"  2. `get_module_requirements` with `filter={{\"Status\": \"<Approved value>\"}}` "
                f"on the System Requirements module(s).\n"
                f"  3. `query_work_items` for active EWM tasks (`oslc.where=oslc_cm:closed=false`).\n"
                f"  4. `query_work_items` for ETM test cases (or follow validatesRequirement "
                f"backlinks).\n"
                f"  5. Show user a current-state summary table: 'You have N approved reqs "
                f"(was M originally), K active tasks, J test cases. Building based on this. OK?'\n\n"
                f"### PHASE 7 — Write the code\n"
                f"On user confirmation of Phase 6: write the actual application code "
                f"in the user's IDE using the AI host's editing capabilities. **Every "
                f"file gets a header comment:**\n"
                f"```\n"
                f"# Implements: REQ-005, REQ-007\n"
                f"# Source: <DNG req URLs>\n"
                f"```\n"
                f"Code structure should mirror requirement structure where reasonable.\n\n"
                f"### PHASE 8 — Track work + record results in ELM as you go\n"
                f"As each task is implemented:\n"
                f"  - `transition_work_item(workitem_url, 'In Development')` when starting\n"
                f"  - `transition_work_item(workitem_url, 'Resolved')` when complete\n"
                f"For each test case once code is in place:\n"
                f"  - `create_test_result(test_case_url, status='passed')` if passes\n"
                f"  - `create_test_result(... status='failed')` AND `create_defect` "
                f"linked to the requirement on failure\n\n"
                f"### PHASE 9 — Final summary with markdown links\n"
                f"Give the user the complete picture:\n"
                f"  - DNG: [Module name](url) — N reqs (M Approved, K Rejected)\n"
                f"  - EWM: N tasks (M Resolved, K In Progress)\n"
                f"  - ETM: M passed ✅, K failed ❌, J blocked\n"
                f"  - Defects: open list — N open, all linked back to source reqs\n"
                f"  - Code: F files written, each with 'Implements REQ-…' headers\n\n"
                f"---\n\n"
                f"**START NOW with Phase 0.** Call `connect_to_elm` if not connected. "
                f"Then ask the user to confirm/specify the DNG / EWM / ETM project names "
                f"if not already set above. Then move to Phase 1's intake questions.\n\n"
                f"## 🚦 PHASE GATE TOOL — `build_project_next`\n\n"
                f"You CANNOT advance from one phase to the next on your own. After "
                f"each phase's user-approval moment, you MUST call "
                f"`build_project_next(current_phase=<N>, user_signal=<verbatim user "
                f"reply>)` to receive the next phase's instructions. The tool "
                f"validates the user_signal — empty / vague / non-approval text "
                f"returns an error and the flow stalls. **This is the only path "
                f"to the next phase.** If you skip ahead without calling "
                f"build_project_next you will be operating on Phase {{N}}'s rules "
                f"forever — no Phase {{N+1}} script will be available to you.\n\n"
                f"After Phase 0 (connection + project selection), call "
                f"`build_project_next(current_phase=0, user_signal=<user said the "
                f"projects to use>, run_id=\"{run['run_id']}\")` to get Phase 1's "
                f"interview questions. **Always include `run_id`** so the gate "
                f"can persist project URLs and tier_mode for later phases.\n\n"
                f"**REMINDER:** the WRITE GATE rule applies to every create_* / update_* "
                f"/ transition_* call inside this flow. Per-phase user approval is "
                f"non-negotiable. The user merely saying 'build a project' was the "
                f"REQUEST — every individual artifact still requires its own "
                f"preview → approval gate before pushing to ELM."
            ))]

        if name == "list_capabilities":
            tools = await list_tools()
            domains = {
                "Server / Updates": ["list_capabilities", "update_elm_mcp", "connect_to_elm"],
                "DNG — Read": [
                    "list_projects", "get_modules", "get_module_requirements",
                    "search_requirements", "get_artifact_types", "get_link_types",
                    "get_attribute_definitions", "list_baselines", "compare_baselines",
                    "save_requirements", "extract_pdf",
                ],
                "DNG — Write": [
                    "create_module", "create_requirements", "update_requirement",
                    "update_requirement_attributes", "create_link", "create_baseline",
                ],
                "EWM (Work Items + Defects)": [
                    "create_task", "create_defect", "update_work_item",
                    "transition_work_item", "query_work_items",
                ],
                "ETM (Test Management)": [
                    "create_test_case", "create_test_script", "create_test_result",
                ],
                "GCM (Global Configuration)": [
                    "list_global_configurations", "list_global_components",
                    "get_global_config_details",
                ],
                "EWM SCM (Code / Reviews)": [
                    "scm_list_projects", "scm_list_changesets", "scm_get_changeset",
                    "scm_get_workitem_changesets", "review_get", "review_list_open",
                ],
                "Visualization": ["generate_chart"],
            }
            tool_descs = {t.name: (t.description or "").split(".")[0].strip() + "." for t in tools}
            lines = [
                f"# ELM MCP — what I can do (v{__version__})\n",
                f"**{len(tools)} tools across {len(domains)} domains.** "
                "Tools subject to the Generation Discipline (interview → preview → "
                "confirm) are marked with ⚠️.\n",
            ]
            write_tools = {
                "create_module", "create_requirements", "update_requirement",
                "update_requirement_attributes", "create_link", "create_baseline",
                "create_task", "create_defect", "update_work_item",
                "transition_work_item", "create_test_case", "create_test_script",
                "create_test_result", "generate_chart",
            }
            seen = set()
            for domain, names_in_domain in domains.items():
                lines.append(f"\n## {domain}\n")
                for n in names_in_domain:
                    if n not in tool_descs:
                        continue
                    seen.add(n)
                    marker = " ⚠️" if n in write_tools else ""
                    lines.append(f"- **`{n}`**{marker} — {tool_descs[n]}")
            uncategorized = [t.name for t in tools if t.name not in seen]
            if uncategorized:
                lines.append("\n## Other (uncategorized — likely added recently)\n")
                for n in uncategorized:
                    lines.append(f"- **`{n}`** — {tool_descs[n]}")
            lines.append(
                "\n---\n"
                "**Quick start:** `connect_to_elm` → `list_projects` → "
                "pick a workflow (read existing reqs / generate new ones / "
                "import PDF / create EWM tasks / create ETM tests / full "
                "lifecycle / tiered Business→Stakeholder→System decomposition).\n\n"
                "**Read-only tools run freely; write tools always show a "
                "preview and ask for your approval before firing.**"
            )
            return [TextContent(type="text", text="\n".join(lines))]

        if name == "update_elm_mcp":
            latest = _fetch_latest_version()
            if not latest:
                return [TextContent(type="text", text=(
                    f"Couldn't reach GitHub to check for updates. "
                    f"You're on **v{__version__}**.\n\n"
                    f"Try again in a moment, or update manually:\n"
                    f"`curl -fsSL https://raw.githubusercontent.com/{GITHUB_REPO}/main/install.sh | bash`"
                ))]
            if latest == __version__:
                return [TextContent(type="text", text=(
                    f"Already on the latest version: **v{__version__}**. "
                    f"Nothing to do."
                ))]
            if not _is_git_managed():
                return [TextContent(type="text", text=(
                    f"**v{latest}** is available (you're on v{__version__}), but this "
                    f"install isn't a git checkout so I can't pull in place. Update with:\n\n"
                    f"`curl -fsSL https://raw.githubusercontent.com/{GITHUB_REPO}/main/install.sh | bash`"
                ))]
            if _git_pull():
                _record_check_now()
                return [TextContent(type="text", text=(
                    f"✓ Pulled **v{latest}** (was v{__version__}).\n\n"
                    f"**Restart your AI assistant** (Bob / Claude Code / etc.) to "
                    f"start using the new version. The currently-running server "
                    f"keeps using v{__version__} until restart — that's deliberate "
                    f"so we don't yank the rug mid-conversation."
                ))]
            return [TextContent(type="text", text=(
                f"v{latest} is available but `git pull` failed. "
                f"Run manually: `cd {_project_dir()} && git pull && python3 setup.py`"
            ))]

        # ── extract_pdf (no connection needed) ────────────────
        if name == "extract_pdf":
            file_path = arguments.get("file_path", "").strip()
            if not file_path:
                return [TextContent(type="text", text="Error: file_path is required.")]

            if not os.path.exists(file_path):
                return [TextContent(type="text", text=f"Error: File not found: {file_path}")]

            try:
                import fitz  # PyMuPDF
            except ImportError:
                return [TextContent(type="text", text=(
                    "Error: PyMuPDF is not installed. Run: pip install PyMuPDF"
                ))]

            try:
                doc = fitz.open(file_path)
                pages = []
                for i, page in enumerate(doc, 1):
                    text = page.get_text().strip()
                    if text:
                        pages.append(f"--- Page {i} ---\n{text}")
                doc.close()

                if not pages:
                    return [TextContent(type="text", text=(
                        f"No text found in '{os.path.basename(file_path)}'. "
                        "The PDF may be image-only (scanned without OCR)."
                    ))]

                full_text = "\n\n".join(pages)
                return [TextContent(type="text", text=(
                    f"# PDF Extracted: {os.path.basename(file_path)}\n"
                    f"**Pages:** {len(pages)}\n\n"
                    f"{full_text}"
                ))]
            except Exception as e:
                return [TextContent(type="text", text=f"Error reading PDF: {e}")]

        # ── All other tools require a connection ──────────────
        client = _get_or_create_client()
        if client is None:
            error_detail = f"\nReason: {_client_error}" if _client_error else ""
            return [TextContent(type="text", text=(
                f"Not connected to ELM.{error_detail}\n\n"
                "Use the `connect_to_elm` tool with your server URL, username, and password."
            ))]

        # ── list_projects ─────────────────────────────────────
        if name == "list_projects":
            domain = arguments.get("domain", "dng").lower()

            if domain == "ewm":
                if not _ewm_projects_cache:
                    _ewm_projects_cache = client.list_ewm_projects()
                projects = _ewm_projects_cache
                label = "EWM (Engineering Workflow Management)"
                hint = "Use `create_task` with an EWM project number or name."
            elif domain == "etm":
                if not _etm_projects_cache:
                    _etm_projects_cache = client.list_etm_projects()
                projects = _etm_projects_cache
                label = "ETM (Engineering Test Management)"
                hint = "Use `create_test_case` with an ETM project number or name."
            else:
                if not _projects_cache:
                    _projects_cache = client.list_projects()
                projects = _projects_cache
                label = "DNG (DOORS Next Generation)"
                hint = "Use `get_modules` with a project number or name to see its modules."

            if not projects:
                return [TextContent(type="text", text=(
                    f"No {domain.upper()} projects found. Check your permissions or server URL."
                ))]

            lines = [f"# {label} Projects ({len(projects)} total)\n"]
            for i, p in enumerate(projects, 1):
                lines.append(f"{i}. **{p['title']}**")

            lines.append(f"\n{hint}")
            return [TextContent(type="text", text="\n".join(lines))]

        # ── compare_baselines (DNG CM) ────────────────────────
        elif name == "compare_baselines":
            proj_id = arguments.get("project_identifier", "")
            mod_id = arguments.get("module_identifier", "")
            bl_url = arguments.get("baseline_url", "")

            if not proj_id or not mod_id or not bl_url:
                return [TextContent(type="text", text=(
                    "Error: project_identifier, module_identifier, and baseline_url are all required."
                ))]

            if not _projects_cache:
                _projects_cache = client.list_projects()

            project = _find_by_identifier(_projects_cache, proj_id)
            if not project:
                return [TextContent(type="text", text=f"Project not found: '{proj_id}'")]

            project_key = project['id']
            if project_key not in _modules_cache:
                modules = client.get_modules(project['url'])
                _modules_cache[project_key] = modules

            modules = _modules_cache.get(project_key, [])
            module = _find_by_identifier(modules, mod_id)
            if not module:
                return [TextContent(type="text", text=f"Module not found: '{mod_id}'")]

            # Read current requirements
            current_reqs = client.get_module_requirements(module['url'])
            # Read baseline requirements
            baseline_reqs = client.get_module_requirements(module['url'], config_url=bl_url)

            # Build lookup maps by title for diffing
            current_map = {r.get('title', ''): r for r in current_reqs}
            baseline_map = {r.get('title', ''): r for r in baseline_reqs}

            all_titles = set(list(current_map.keys()) + list(baseline_map.keys()))

            added = []
            removed = []
            changed = []
            unchanged = []

            for title in sorted(all_titles):
                in_current = title in current_map
                in_baseline = title in baseline_map

                if in_current and not in_baseline:
                    added.append(current_map[title])
                elif in_baseline and not in_current:
                    removed.append(baseline_map[title])
                elif in_current and in_baseline:
                    cur = current_map[title]
                    bl = baseline_map[title]
                    cur_desc = (cur.get('description') or '').strip()
                    bl_desc = (bl.get('description') or '').strip()
                    if cur_desc != bl_desc:
                        changed.append({'title': title, 'baseline': bl_desc, 'current': cur_desc})
                    else:
                        unchanged.append(title)

            lines = [
                f"# Baseline Comparison: '{module['title']}'\n",
                f"**Baseline:** `{bl_url}`\n",
                f"**Current stream** vs **baseline**:\n",
            ]

            if not added and not removed and not changed:
                lines.append("**No changes detected.** The current stream matches the baseline.")
            else:
                if changed:
                    lines.append(f"### Modified ({len(changed)})\n")
                    for c in changed:
                        lines.append(f"- **{c['title']}**")
                        bl_preview = c['baseline'][:100] + '...' if len(c['baseline']) > 100 else c['baseline']
                        cur_preview = c['current'][:100] + '...' if len(c['current']) > 100 else c['current']
                        lines.append(f"  - Baseline: {bl_preview}")
                        lines.append(f"  - Current: {cur_preview}")

                if added:
                    lines.append(f"\n### Added ({len(added)})\n")
                    for a in added:
                        lines.append(f"- **{a.get('title', 'Untitled')}**")

                if removed:
                    lines.append(f"\n### Removed ({len(removed)})\n")
                    for r in removed:
                        lines.append(f"- **{r.get('title', 'Untitled')}**")

                if unchanged:
                    lines.append(f"\n### Unchanged ({len(unchanged)})\n")
                    lines.append(f"_{len(unchanged)} requirement(s) identical to baseline._")

            lines.append(f"\n**Summary:** {len(changed)} modified, {len(added)} added, {len(removed)} removed, {len(unchanged)} unchanged")

            return [TextContent(type="text", text="\n".join(lines))]

        # ── get_modules ───────────────────────────────────────
        elif name == "get_modules":
            identifier = arguments.get("project_identifier", "")
            if not identifier:
                return [TextContent(type="text", text="Error: project_identifier is required.")]

            # Ensure projects are loaded
            if not _projects_cache:
                _projects_cache = client.list_projects()

            project = _find_by_identifier(_projects_cache, identifier)
            if not project:
                names = "\n".join(f"{i}. {p['title']}" for i, p in enumerate(_projects_cache, 1))
                return [TextContent(type="text", text=(
                    f"Project not found: '{identifier}'\n\nAvailable projects:\n{names}"
                ))]

            _last_project_name = project['title']
            project_key = project['id']

            # Fetch modules
            modules = client.get_modules(project['url'])
            _modules_cache[project_key] = modules

            if not modules:
                return [TextContent(type="text", text=(
                    f"No modules found in '{project['title']}'.\n\n"
                    "This could mean the project has no modules, or the API endpoint "
                    "is not available for this project type."
                ))]

            source = modules[0].get('source', '')
            note = ""
            if source == 'oslc_folders':
                note = (
                    "\n\n*Note: These were retrieved via the OSLC folder API. "
                    "Some entries may be organizational folders rather than requirement modules.*"
                )

            lines = [
                f"# Modules in '{project['title']}'\n",
                f"Found **{len(modules)}** module(s):\n",
            ]

            for i, m in enumerate(modules, 1):
                lines.append(f"{i}. **{m['title']}**")
                if m.get('id'):
                    lines.append(f"   - ID: `{m['id']}`")
                if m.get('modified'):
                    lines.append(f"   - Modified: {m['modified']}")

            lines.append(
                f"\nUse `get_module_requirements` with a module number or name "
                f"to get its requirements.{note}"
            )
            return [TextContent(type="text", text="\n".join(lines))]

        # ── get_module_requirements ───────────────────────────
        elif name == "get_module_requirements":
            proj_id = arguments.get("project_identifier", "")
            mod_id = arguments.get("module_identifier", "")

            if not proj_id or not mod_id:
                return [TextContent(type="text", text=(
                    "Error: both project_identifier and module_identifier are required."
                ))]

            # Ensure projects are loaded
            if not _projects_cache:
                _projects_cache = client.list_projects()

            project = _find_by_identifier(_projects_cache, proj_id)
            if not project:
                return [TextContent(type="text", text=f"Project not found: '{proj_id}'")]

            project_key = project['id']
            _last_project_name = project['title']

            # Get modules if not cached for this project
            if project_key not in _modules_cache:
                modules = client.get_modules(project['url'])
                _modules_cache[project_key] = modules

            modules = _modules_cache.get(project_key, [])
            if not modules:
                return [TextContent(type="text", text=(
                    f"No modules found in '{project['title']}'. "
                    "Run get_modules first to see available modules."
                ))]

            module = _find_by_identifier(modules, mod_id)
            if not module:
                names = "\n".join(f"{i}. {m['title']}" for i, m in enumerate(modules, 1))
                return [TextContent(type="text", text=(
                    f"Module not found: '{mod_id}'\n\nAvailable modules:\n{names}"
                ))]

            _last_module_name = module['title']

            # Fetch requirements (with optional filter)
            user_filter = arguments.get("filter") or None
            requirements = client.get_module_requirements(module['url'], filter=user_filter)
            _last_requirements = requirements

            if not requirements:
                filter_note = f" matching filter `{user_filter}`" if user_filter else ""
                return [TextContent(type="text", text=(
                    f"No requirements found in module '{module['title']}'{filter_note}.\n\n"
                    "Either the module is empty, or your filter excluded everything. "
                    "Call get_attribute_definitions on this project to see what attributes "
                    "and values are valid for filtering."
                ))]

            lines = [
                f"# Requirements from '{module['title']}'",
                f"*(Project: {project['title']})*\n",
                f"Found **{len(requirements)}** requirement(s):\n",
            ]

            for i, req in enumerate(requirements, 1):
                # Show artifact type tag if available
                type_tag = f" [{req['artifact_type']}]" if req.get('artifact_type') else ""
                lines.append(f"{i}. **{req['title']}**{type_tag}")
                if req.get('id'):
                    lines.append(f"   - ID: `{req['id']}`")
                if req.get('url'):
                    lines.append(f"   - URL: `{req['url']}`")
                if req.get('description'):
                    desc = req['description']
                    if len(desc) > 200:
                        desc = desc[:200] + "..."
                    lines.append(f"   - Description: {desc}")
                if req.get('status'):
                    lines.append(f"   - Status: {req['status']}")
                # Show custom attributes
                custom = req.get('custom_attributes', {})
                if custom:
                    attrs_str = ", ".join(f"{k}: {v}" for k, v in custom.items())
                    lines.append(f"   - Attributes: {attrs_str}")

            lines.append(
                f"\nWould you like to save these requirements to a file? "
                f"Use `save_requirements` with format 'json', 'csv', or 'markdown'."
            )
            return [TextContent(type="text", text="\n".join(lines))]

        # ── save_requirements ─────────────────────────────────
        elif name == "save_requirements":
            if not _last_requirements:
                return [TextContent(type="text", text=(
                    "No requirements to save. "
                    "Use get_module_requirements first to fetch requirements."
                ))]

            fmt = arguments.get("format", "json")
            filename = arguments.get("filename", "")

            if not filename:
                safe_name = "".join(
                    c if c.isalnum() or c in ('_', '-') else '_'
                    for c in _last_module_name
                )[:50]
                ext = {'json': '.json', 'csv': '.csv', 'markdown': '.md'}.get(fmt, '.json')
                filename = f"requirements_{safe_name}{ext}"

            filepath = os.path.join(os.getcwd(), filename)

            if fmt == 'json':
                client.export_to_json(_last_requirements, filepath)
            elif fmt == 'csv':
                client.export_to_csv(_last_requirements, filepath)
            elif fmt == 'markdown':
                client.export_to_markdown(_last_requirements, filepath)
            else:
                return [TextContent(type="text", text=(
                    f"Unknown format: '{fmt}'. Use json, csv, or markdown."
                ))]

            return [TextContent(type="text", text=(
                f"Saved **{len(_last_requirements)}** requirements to `{filename}`\n\n"
                f"- Format: {fmt}\n"
                f"- Module: {_last_module_name}\n"
                f"- Project: {_last_project_name}"
            ))]

        # ── search_requirements ────────────────────────────────
        elif name == "search_requirements":
            proj_id = arguments.get("project_identifier", "")
            query = arguments.get("query", "")

            if not proj_id or not query:
                return [TextContent(type="text", text="Error: project_identifier and query are required.")]

            if not _projects_cache:
                _projects_cache = client.list_projects()

            project = _find_by_identifier(_projects_cache, proj_id)
            if not project:
                return [TextContent(type="text", text=f"Project not found: '{proj_id}'")]

            results = client.search_requirements(project['url'], query)

            if not results:
                return [TextContent(type="text", text=(
                    f"No results for '{query}' in '{project['title']}'."
                ))]

            lines = [
                f"# Search Results for '{query}' in '{project['title']}'\n",
                f"Found **{len(results)}** result(s):\n",
            ]
            for i, r in enumerate(results, 1):
                lines.append(f"{i}. **{r['title']}**")
                if r.get('url'):
                    lines.append(f"   - URL: `{r['url']}`")
                if r.get('summary'):
                    lines.append(f"   - {r['summary'][:150]}")

            return [TextContent(type="text", text="\n".join(lines))]

        # ── get_link_types ────────────────────────────────────
        elif name == "get_link_types":
            proj_id = arguments.get("project_identifier", "")
            if not proj_id:
                return [TextContent(type="text", text="Error: project_identifier is required.")]

            if not _projects_cache:
                _projects_cache = client.list_projects()

            project = _find_by_identifier(_projects_cache, proj_id)
            if not project:
                return [TextContent(type="text", text=f"Project not found: '{proj_id}'")]

            link_types = client.get_link_types(project['url'])
            if not link_types:
                return [TextContent(type="text", text=(
                    f"Could not retrieve link types for '{project['title']}'."
                ))]

            lines = [
                f"# Link Types in '{project['title']}'\n",
                f"Found **{len(link_types)}** link type(s):\n",
            ]
            for i, lt in enumerate(link_types, 1):
                lines.append(f"{i}. **{lt['name']}**")

            lines.append(
                "\nUse these names with `create_requirements` in the `link_type` field "
                "to create linked requirements."
            )
            return [TextContent(type="text", text="\n".join(lines))]

        # ── get_artifact_types ─────────────────────────────────
        elif name == "get_artifact_types":
            proj_id = arguments.get("project_identifier", "")
            if not proj_id:
                return [TextContent(type="text", text="Error: project_identifier is required.")]

            if not _projects_cache:
                _projects_cache = client.list_projects()

            project = _find_by_identifier(_projects_cache, proj_id)
            if not project:
                return [TextContent(type="text", text=f"Project not found: '{proj_id}'")]

            shapes = client.get_artifact_shapes(project['url'])
            if not shapes:
                return [TextContent(type="text", text=(
                    f"Could not retrieve artifact types for '{project['title']}'."
                ))]

            lines = [
                f"# Artifact Types in '{project['title']}'\n",
                f"Found **{len(shapes)}** type(s):\n",
            ]
            for i, s in enumerate(shapes, 1):
                lines.append(f"{i}. **{s['name']}**")

            lines.append(
                "\nUse these type names with `create_requirements` "
                "(e.g., 'System Requirement', 'Heading', 'User Requirement')."
            )
            return [TextContent(type="text", text="\n".join(lines))]

        # ── create_requirements ───────────────────────────────
        elif name == "create_module":
            proj_id = arguments.get("project_identifier", "")
            title = arguments.get("title", "")
            description = arguments.get("description", "")

            if not proj_id:
                return [TextContent(type="text", text="Error: project_identifier is required.")]
            if not title:
                return [TextContent(type="text", text="Error: title is required.")]

            if not _projects_cache:
                _projects_cache = client.list_projects()
            project = _find_by_identifier(_projects_cache, proj_id)
            if not project:
                return [TextContent(type="text", text=f"Project not found: '{proj_id}'")]

            result = client.create_module(project['url'], title, description)
            if result and 'error' not in result:
                return [TextContent(type="text", text=(
                    f"# Module Created in '{project['title']}'\n\n"
                    f"**Click to open:** [{result['title']}]({result['url']})\n\n"
                    f"- **Title:** {result['title']}\n"
                    f"- **Direct URL:** {result['url']}\n\n"
                    f"**Next step:** call `create_requirements` with "
                    f"`module_name=\"{result['title']}\"` to populate this module.\n\n"
                    f"---\n"
                    f"**Surface this exact module link to the user as a clickable markdown "
                    f"link** — do NOT replace it with a generic `/rm` landing page URL."
                ))]
            err = result.get('error', 'unknown error') if result else 'unknown error'
            return [TextContent(type="text", text=(
                f"Error: failed to create module — {err}\n"
                "Check that you have write permissions in this project and that "
                "the project has a 'Module' artifact type defined."
            ))]

        # ── add_to_module ─────────────────────────────────────────
        elif name == "add_to_module":
            module_url = arguments.get("module_url", "")
            requirement_urls = arguments.get("requirement_urls", []) or []
            if not module_url:
                return [TextContent(type="text", text="Error: module_url is required.")]
            if not requirement_urls:
                return [TextContent(type="text", text="Error: requirement_urls list cannot be empty.")]
            result = client.add_to_module(module_url, requirement_urls)
            if result and 'error' not in result:
                added = result.get('added', 0)
                return [TextContent(type="text", text=(
                    f"# Module Bind Complete\n\n"
                    f"**Bound {added} new requirement(s)** to module {module_url}\n\n"
                    f"(Already-bound requirements in the input list were skipped — "
                    f"the operation is idempotent. Total requested: "
                    f"{len(requirement_urls)}.)"
                ))]
            err = result.get('error', 'unknown error') if result else 'unknown error'
            return [TextContent(type="text", text=(
                f"Error: failed to bind to module — {err}\n"
                "If the error is PHASE_GATE-related, the project's module "
                "structure API may not be enabled. Check probe/MODULE_BINDING_FINDINGS.md."
            ))]

        # ── create_folder ─────────────────────────────────────────
        elif name == "create_folder":
            proj_id = arguments.get("project_identifier", "")
            folder_name = arguments.get("folder_name", "")
            parent_url = arguments.get("parent_folder_url", "") or None
            if not proj_id or not folder_name:
                return [TextContent(type="text", text="Error: project_identifier and folder_name are required.")]
            if not _projects_cache:
                _projects_cache = client.list_projects()
            project = _find_by_identifier(_projects_cache, proj_id)
            if not project:
                return [TextContent(type="text", text=f"Project not found: '{proj_id}'")]
            result = client.create_folder(project['url'], folder_name, parent_url)
            if result and 'error' not in result:
                return [TextContent(type="text", text=(
                    f"# Folder Created\n\n"
                    f"**Click to open:** [{result.get('title', folder_name)}]({result.get('url', '')})\n\n"
                    f"- **Name:** {result.get('title', folder_name)}\n"
                    f"- **URL:** {result.get('url', '')}\n\n"
                    f"Pass `folder_url=\"{result.get('url', '')}\"` to subsequent "
                    f"`create_requirement` calls to drop them in this folder."
                ))]
            err = result.get('error', 'unknown error') if result else 'unknown error'
            return [TextContent(type="text", text=f"Error: failed to create folder — {err}")]

        # ── find_folder ────────────────────────────────────────────
        elif name == "find_folder":
            proj_id = arguments.get("project_identifier", "")
            folder_name = arguments.get("folder_name", "")
            if not proj_id or not folder_name:
                return [TextContent(type="text", text="Error: project_identifier and folder_name are required.")]
            if not _projects_cache:
                _projects_cache = client.list_projects()
            project = _find_by_identifier(_projects_cache, proj_id)
            if not project:
                return [TextContent(type="text", text=f"Project not found: '{proj_id}'")]
            result = client.find_folder(project['url'], folder_name)
            if result:
                return [TextContent(type="text", text=(
                    f"# Folder Found\n\n"
                    f"**Click to open:** [{result.get('title', folder_name)}]({result.get('url', '')})\n\n"
                    f"- **Name:** {result.get('title', folder_name)}\n"
                    f"- **URL:** {result.get('url', '')}"
                ))]
            return [TextContent(type="text", text=(
                f"No folder named '{folder_name}' found in project '{project['title']}'. "
                f"Call `create_folder` to create it (after user approval)."
            ))]

        elif name == "create_requirements":
            proj_id = arguments.get("project_identifier", "")
            folder_name = arguments.get("folder_name", "")
            module_name = arguments.get("module_name", "")
            reqs_data = arguments.get("requirements", [])

            if not proj_id:
                return [TextContent(type="text", text="Error: project_identifier is required.")]
            if not reqs_data:
                return [TextContent(type="text", text="Error: requirements array is empty.")]

            # Default folder name when only module_name was given
            if module_name and not folder_name:
                folder_name = module_name
            if not folder_name and not module_name:
                return [TextContent(type="text", text=(
                    "Error: provide module_name (preferred — makes the requirements "
                    "visible as a navigable document in DNG) and/or folder_name."
                ))]

            if not _projects_cache:
                _projects_cache = client.list_projects()

            project = _find_by_identifier(_projects_cache, proj_id)
            if not project:
                return [TextContent(type="text", text=f"Project not found: '{proj_id}'")]

            # Get artifact type shapes for this project
            shapes = client.get_artifact_shapes(project['url'])
            shape_map = {s['name'].lower(): s['url'] for s in shapes}

            if not shape_map:
                return [TextContent(type="text", text=(
                    f"Could not retrieve artifact types for '{project['title']}'. "
                    "Check your permissions."
                ))]

            # Find or create the target module if requested
            module = None
            if module_name:
                # Re-use cached module if we created it in this session
                module = _folder_cache.get(f"__module__::{module_name}")
                if not module:
                    # Search existing modules in the project
                    try:
                        existing = client.get_modules(project['url'])
                    except Exception:
                        existing = []
                    target = module_name.lower()
                    for m in existing:
                        m_title = (m.get('title') or '').lower()
                        if m_title == target or m_title == f"[ai generated] {target}":
                            module = m
                            break
                if not module:
                    created_mod = client.create_module(project['url'], module_name)
                    if not created_mod or 'error' in created_mod:
                        err = created_mod.get('error', 'unknown') if created_mod else 'unknown'
                        return [TextContent(type="text", text=(
                            f"Error: could not find or create module '{module_name}' — {err}"
                        ))]
                    module = created_mod
                _folder_cache[f"__module__::{module_name}"] = module

            # Find or create the holding folder for the base artifacts
            folder = _folder_cache.get(folder_name)
            if not folder:
                folder = client.find_folder(project['url'], folder_name)
            if not folder:
                folder = client.create_folder(project['url'], folder_name)
                if not folder:
                    return [TextContent(type="text", text=(
                        f"Failed to create '{folder_name}' folder. "
                        "Check your write permissions for this project."
                    ))]
            _folder_cache[folder_name] = folder

            folder_url = folder['url']

            # Resolve link types if any requirements have links
            link_type_map = {}
            has_links = any(req.get('link_type') for req in reqs_data)
            if has_links:
                link_types = client.get_link_types(project['url'])
                link_type_map = {lt['name'].lower(): lt['uri'] for lt in link_types}

            # Create each requirement
            created = []
            failed = []
            for req in reqs_data:
                title = req.get('title', '')
                content = req.get('content', '')
                artifact_type = req.get('artifact_type', 'System Requirement')

                # Find the shape URL for this artifact type
                shape_url = shape_map.get(artifact_type.lower())
                if not shape_url:
                    # Try partial match
                    for name_key, url_val in shape_map.items():
                        if artifact_type.lower() in name_key:
                            shape_url = url_val
                            break

                if not shape_url:
                    failed.append(f"'{title[:40]}' - unknown artifact type '{artifact_type}'")
                    continue

                # Resolve link type if specified
                link_uri = None
                link_target = req.get('link_to')
                link_type_name = req.get('link_type', '')
                if link_type_name and link_target:
                    link_uri = link_type_map.get(link_type_name.lower())
                    if not link_uri:
                        # Try partial match
                        for lt_name, lt_uri in link_type_map.items():
                            if link_type_name.lower() in lt_name:
                                link_uri = lt_uri
                                break

                result = client.create_requirement(
                    project_url=project['url'],
                    title=title,
                    content=content,
                    shape_url=shape_url,
                    folder_url=folder_url,
                    link_uri=link_uri,
                    link_target_url=link_target,
                )

                if result and 'error' not in result:
                    created.append(result)
                else:
                    error_detail = result.get('error', 'API error') if result else 'API error'
                    # Mark shape-rejected items distinctly so the AI sees
                    # "fix and retry", not "permanently failed".
                    prefix = "[CONTENT SHAPE REJECTED — retry with clean shall-statement] " \
                             if result and result.get('rejected_for_content_shape') else ""
                    failed.append(f"{prefix}'{title[:40]}' — {error_detail}")

            # Bind the freshly created requirements to the module in one PUT
            bind_status = None
            if module and created:
                bind_status = client.add_to_module(
                    module['url'],
                    [r['url'] for r in created if r.get('url')],
                )

            # Build response — every artifact url is a markdown link so the
            # user can click straight through to DNG. Do NOT collapse these
            # into a generic "go check DOORS Next" line.
            lines = [
                f"# Requirements Created in '{project['title']}'\n",
            ]
            if module:
                lines.append(f"**Module:** [{module['title']}]({module['url']})  ")
                lines.append(f"  ↳ open this link in your browser to see the module with all its bindings.\n")
            lines.append(f"**Folder:** {folder_name}\n")
            lines.append(f"**Created {len(created)} of {len(reqs_data)} requirement(s):**\n")

            for i, r in enumerate(created, 1):
                if r.get('url'):
                    lines.append(f"{i}. [{r['title']}]({r['url']})")
                else:
                    lines.append(f"{i}. {r['title']}  *(no URL returned)*")

            if failed:
                lines.append(f"\n**Failed ({len(failed)}):**")
                for f_msg in failed:
                    lines.append(f"- {f_msg}")

            if module and bind_status:
                if 'error' in bind_status:
                    lines.append(
                        f"\n**Warning:** requirements were created but binding to module "
                        f"failed: {bind_status['error']}. The requirements still exist in "
                        f"the folder and can be added to the module manually in DNG."
                    )
                else:
                    added = bind_status.get('added', 0)
                    lines.append(
                        f"\n**Bound to module:** {added} requirement(s) added to "
                        f"[{module['title']}]({module['url']}). Click that link to "
                        f"see them in order."
                    )
            elif not module:
                lines.append(
                    f"\n**Note:** no module_name was provided — these requirements live "
                    f"in the folder '{folder_name}' as standalone artifacts. To make them "
                    f"appear in a navigable document, re-run with `module_name` set."
                )

            lines.append(
                "\n---\n"
                "**Surface ALL of the links above to the user as markdown links** — "
                "do NOT paraphrase to a generic '/rm' landing page URL. Each link "
                "above goes directly to the specific artifact."
            )

            return [TextContent(type="text", text="\n".join(lines))]

        # ── update_requirement (DNG) ──────────────────────────
        elif name == "update_requirement":
            req_url = arguments.get("requirement_url", "")
            new_title = arguments.get("title", "")
            new_content = arguments.get("content", "")

            if not req_url:
                return [TextContent(type="text", text="Error: requirement_url is required.")]
            if not new_title and not new_content:
                return [TextContent(type="text", text="Error: provide at least one of title or content to update.")]

            result = client.update_requirement(
                requirement_url=req_url,
                title=new_title or None,
                content=new_content or None,
            )

            if result and 'error' not in result:
                updated_fields = []
                if new_title:
                    updated_fields.append("title")
                if new_content:
                    updated_fields.append("content")
                return [TextContent(type="text", text=(
                    f"# Requirement Updated\n\n"
                    f"- **Title:** {result['title']}\n"
                    f"- **URL:** `{result['url']}`\n"
                    f"- **Updated:** {', '.join(updated_fields)}"
                ))]
            else:
                error_detail = result.get('error', '') if result else ''
                return [TextContent(type="text", text=(
                    f"Failed to update requirement.\n"
                    f"{error_detail}\n\n"
                    "This may be a permissions issue or a version conflict (another user edited it)."
                ))]

        # ── create_baseline (DNG CM) ──────────────────────────
        elif name == "create_baseline":
            proj_id = arguments.get("project_identifier", "")
            bl_title = arguments.get("title", "")
            bl_desc = arguments.get("description", "")

            if not proj_id or not bl_title:
                return [TextContent(type="text", text="Error: project_identifier and title are required.")]

            if not _projects_cache:
                _projects_cache = client.list_projects()

            project = _find_by_identifier(_projects_cache, proj_id)
            if not project:
                return [TextContent(type="text", text=f"Project not found: '{proj_id}'")]

            result = client.create_baseline(
                project_url=project['url'],
                title=bl_title,
                description=bl_desc,
            )

            if result and 'error' not in result:
                return [TextContent(type="text", text=(
                    f"# Baseline Created\n\n"
                    f"- **Title:** {result['title']}\n"
                    f"- **Project:** {project['title']}\n"
                    f"- **Stream:** {result.get('stream_title', 'N/A')}\n"
                    f"- **Status:** Processing (baseline creation is async)\n\n"
                    f"The baseline is being created in the background. "
                    f"Use `list_baselines` to confirm it appears."
                ))]
            else:
                error_detail = result.get('error', '') if result else ''
                return [TextContent(type="text", text=(
                    f"Failed to create baseline for '{project['title']}'.\n"
                    f"{error_detail}"
                ))]

        # ── list_baselines (DNG CM) ──────────────────────────
        elif name == "list_baselines":
            proj_id = arguments.get("project_identifier", "")
            if not proj_id:
                return [TextContent(type="text", text="Error: project_identifier is required.")]

            if not _projects_cache:
                _projects_cache = client.list_projects()

            project = _find_by_identifier(_projects_cache, proj_id)
            if not project:
                return [TextContent(type="text", text=f"Project not found: '{proj_id}'")]

            baselines = client.list_baselines(project['url'])
            if not baselines:
                return [TextContent(type="text", text=(
                    f"No baselines found for '{project['title']}'.\n"
                    "Use `create_baseline` to create one."
                ))]

            lines = [
                f"# Baselines in '{project['title']}'\n",
                f"Found **{len(baselines)}** baseline(s):\n",
            ]
            for i, bl in enumerate(baselines, 1):
                lines.append(f"{i}. **{bl['title']}**")
                if bl.get('url'):
                    lines.append(f"   - URL: `{bl['url']}`")
                if bl.get('created'):
                    lines.append(f"   - Created: {bl['created']}")

            return [TextContent(type="text", text="\n".join(lines))]

        # ── create_task (EWM) ─────────────────────────────────
        elif name == "create_task":
            ewm_proj = arguments.get("ewm_project", "")
            title = arguments.get("title", "")
            description = arguments.get("description", "")
            requirement_url = arguments.get("requirement_url", "")

            if not ewm_proj or not title:
                return [TextContent(type="text", text="Error: ewm_project and title are required.")]

            # Ensure EWM projects are loaded
            if not _ewm_projects_cache:
                _ewm_projects_cache = client.list_ewm_projects()

            if not _ewm_projects_cache:
                return [TextContent(type="text", text=(
                    "No EWM projects found. Ensure the server has a /ccm context root "
                    "and your credentials have EWM access."
                ))]

            project = _find_by_identifier(_ewm_projects_cache, ewm_proj)
            if not project:
                names = "\n".join(f"{i}. {p['title']}" for i, p in enumerate(_ewm_projects_cache, 1))
                return [TextContent(type="text", text=(
                    f"EWM project not found: '{ewm_proj}'\n\nAvailable EWM projects:\n{names}"
                ))]

            result = client.create_ewm_task(
                service_provider_url=project['url'],
                title=title,
                description=description,
                requirement_url=requirement_url or None,
            )

            if result and 'error' not in result:
                link_note = ""
                if requirement_url:
                    link_note = f"\n- Linked to requirement: `{requirement_url}`"
                return [TextContent(type="text", text=(
                    f"# Task Created in EWM\n\n"
                    f"- **Title:** {result['title']}\n"
                    f"- **Project:** {project['title']}\n"
                    f"- **URL:** {result['url']}{link_note}\n\n"
                    f"A project lead can assign it to an iteration and developer."
                ))]
            else:
                error_detail = result.get('error', '') if result else ''
                return [TextContent(type="text", text=(
                    f"Failed to create task in '{project['title']}'.\n"
                    f"{error_detail}\n\n"
                    "This may be a permissions issue — try a different EWM project."
                ))]

        # ── create_test_case (ETM) ────────────────────────────
        elif name == "create_test_case":
            etm_proj = arguments.get("etm_project", "")
            title = arguments.get("title", "")
            description = arguments.get("description", "")
            requirement_url = arguments.get("requirement_url", "")

            if not etm_proj or not title:
                return [TextContent(type="text", text="Error: etm_project and title are required.")]

            # Ensure ETM projects are loaded
            if not _etm_projects_cache:
                _etm_projects_cache = client.list_etm_projects()

            if not _etm_projects_cache:
                return [TextContent(type="text", text=(
                    "No ETM projects found. Ensure the server has a /qm context root "
                    "and your credentials have ETM access."
                ))]

            project = _find_by_identifier(_etm_projects_cache, etm_proj)
            if not project:
                names = "\n".join(f"{i}. {p['title']}" for i, p in enumerate(_etm_projects_cache, 1))
                return [TextContent(type="text", text=(
                    f"ETM project not found: '{etm_proj}'\n\nAvailable ETM projects:\n{names}"
                ))]

            result = client.create_test_case(
                service_provider_url=project['url'],
                title=title,
                description=description,
                requirement_url=requirement_url or None,
            )

            if result and 'error' not in result:
                link_note = ""
                if requirement_url:
                    link_note = f"\n- Validates requirement: `{requirement_url}`"
                return [TextContent(type="text", text=(
                    f"# Test Case Created in ETM\n\n"
                    f"- **Title:** {result['title']}\n"
                    f"- **Project:** {project['title']}\n"
                    f"- **URL:** {result['url']}{link_note}\n\n"
                    f"Use this URL with `create_test_result` to record pass/fail results."
                ))]
            else:
                error_detail = result.get('error', '') if result else ''
                return [TextContent(type="text", text=(
                    f"Failed to create test case in '{project['title']}'.\n"
                    f"{error_detail}\n\n"
                    "This may be a permissions issue — try a different ETM project."
                ))]

        # ── create_test_script (ETM) ──────────────────────────
        elif name == "create_test_script":
            etm_proj = arguments.get("etm_project", "")
            title = arguments.get("title", "")
            steps = arguments.get("steps", "")
            test_case_url = arguments.get("test_case_url", "")

            if not etm_proj or not title:
                return [TextContent(type="text", text="Error: etm_project and title are required.")]

            if not _etm_projects_cache:
                _etm_projects_cache = client.list_etm_projects()
            project = _find_by_identifier(_etm_projects_cache, etm_proj)
            if not project:
                names = "\n".join(f"{i}. {p['title']}" for i, p in enumerate(_etm_projects_cache, 1))
                return [TextContent(type="text", text=(
                    f"ETM project not found: '{etm_proj}'\n\nAvailable ETM projects:\n{names}"
                ))]

            result = client.create_test_script(
                service_provider_url=project['url'],
                title=title,
                steps=steps,
                test_case_url=test_case_url or None,
            )

            if result and 'error' not in result:
                link_note = f"\n- **Linked to test case:** {test_case_url}" if test_case_url else ""
                return [TextContent(type="text", text=(
                    f"# Test Script Created in ETM\n\n"
                    f"- **Title:** {result['title']}\n"
                    f"- **Project:** {project['title']}\n"
                    f"- **URL:** {result['url']}{link_note}"
                ))]
            err = result.get('error', '') if result else ''
            return [TextContent(type="text", text=(
                f"Failed to create test script in '{project['title']}'.\n{err}\n\n"
                "If the error mentions 'No TestScript creation factory', that ETM "
                "project doesn't expose the TestScript factory in its services.xml — "
                "rare but possible on locked-down deployments."
            ))]

        # ── create_test_result (ETM) ──────────────────────────
        elif name == "create_test_result":
            etm_proj = arguments.get("etm_project", "")
            test_case_url = arguments.get("test_case_url", "")
            status = arguments.get("status", "passed")
            title = arguments.get("title", "")

            if not etm_proj or not test_case_url or not status:
                return [TextContent(type="text", text=(
                    "Error: etm_project, test_case_url, and status are required."
                ))]

            # Auto-generate title if not provided
            if not title:
                title = f"Test Result - {status.capitalize()}"

            # Ensure ETM projects are loaded
            if not _etm_projects_cache:
                _etm_projects_cache = client.list_etm_projects()

            project = _find_by_identifier(_etm_projects_cache, etm_proj)
            if not project:
                names = "\n".join(f"{i}. {p['title']}" for i, p in enumerate(_etm_projects_cache, 1))
                return [TextContent(type="text", text=(
                    f"ETM project not found: '{etm_proj}'\n\nAvailable ETM projects:\n{names}"
                ))]

            result = client.create_test_result(
                service_provider_url=project['url'],
                title=title,
                test_case_url=test_case_url,
                status=status,
            )

            if result and 'error' not in result:
                status_emoji = {"passed": "PASS", "failed": "FAIL", "blocked": "BLOCKED",
                                "incomplete": "INCOMPLETE", "error": "ERROR"}.get(status.lower(), status.upper())
                return [TextContent(type="text", text=(
                    f"# Test Result Recorded in ETM\n\n"
                    f"- **Result:** {status_emoji}\n"
                    f"- **Title:** {result['title']}\n"
                    f"- **Project:** {project['title']}\n"
                    f"- **Reports on:** `{test_case_url}`\n"
                    f"- **URL:** {result['url']}"
                ))]
            else:
                error_detail = result.get('error', '') if result else ''
                return [TextContent(type="text", text=(
                    f"Failed to create test result in '{project['title']}'.\n"
                    f"{error_detail}\n\n"
                    "This may be a permissions issue — try a different ETM project."
                ))]

        # ── list_global_configurations (GCM) ─────────────────
        elif name == "list_global_configurations":
            configs = client.list_global_configurations()
            if not configs:
                return [TextContent(type="text", text=(
                    "No global configurations found. "
                    "GCM may not be configured on this server."
                ))]

            lines = [
                f"# Global Configurations ({len(configs)} total)\n",
                "These span across DNG, EWM, and ETM:\n",
            ]
            for i, c in enumerate(configs, 1):
                lines.append(f"{i}. **{c['title']}**")
                lines.append(f"   - URL: `{c['url']}`")

            lines.append(
                "\nUse `get_global_config_details` with a config URL "
                "to see which DNG/EWM/ETM components contribute to it."
            )
            return [TextContent(type="text", text="\n".join(lines))]

        # ── list_global_components (GCM) ──────────────────────
        elif name == "list_global_components":
            components = client.list_global_components()
            if not components:
                return [TextContent(type="text", text=(
                    "No global components found. "
                    "GCM may not be configured on this server."
                ))]

            lines = [
                f"# Global Components ({len(components)} total)\n",
                "Components across all ELM apps:\n",
            ]
            for i, c in enumerate(components, 1):
                lines.append(f"{i}. **{c['title']}**")
                if c.get('url'):
                    lines.append(f"   - URL: `{c['url']}`")
                if c.get('configurations_url'):
                    lines.append(f"   - Configurations: `{c['configurations_url']}`")
                if c.get('created'):
                    lines.append(f"   - Created: {c['created']}")

            return [TextContent(type="text", text="\n".join(lines))]

        # ── get_global_config_details (GCM) ───────────────────
        elif name == "get_global_config_details":
            config_url = arguments.get("config_url", "")
            if not config_url:
                return [TextContent(type="text", text="Error: config_url is required.")]

            details = client.get_global_config_details(config_url)
            if not details:
                return [TextContent(type="text", text=(
                    f"Could not retrieve details for configuration: {config_url}"
                ))]

            lines = [
                f"# Global Configuration Details\n",
                f"- **Title:** {details['title']}",
                f"- **Type:** {details['type']}",
                f"- **URL:** `{details['url']}`",
            ]
            if details.get('component'):
                lines.append(f"- **Component:** `{details['component']}`")

            contribs = details.get('contributions', [])
            if contribs:
                lines.append(f"\n### Contributions ({len(contribs)})\n")
                for c in contribs:
                    lines.append(f"- [{c['app']}] `{c['url']}`")
            else:
                lines.append("\nNo contributions found (this may be a simple configuration).")

            return [TextContent(type="text", text="\n".join(lines))]

        # ── generate_chart ────────────────────────────────────
        elif name == "generate_chart":
            chart_type = arguments.get("chart_type", "").strip().lower()
            title = arguments.get("title", "").strip()
            labels = arguments.get("labels") or []
            values = arguments.get("values") or []
            x_label = arguments.get("x_label", "")
            y_label = arguments.get("y_label", "")
            output_filename = (arguments.get("output_filename") or "").strip()

            if chart_type not in {"bar", "hbar", "pie", "line"}:
                return [TextContent(type="text", text=(
                    "Error: chart_type must be one of: bar, hbar, pie, line."
                ))]
            if not title:
                return [TextContent(type="text", text="Error: title is required.")]
            if not labels or not values:
                return [TextContent(type="text", text=(
                    "Error: labels and values are both required and must be non-empty."
                ))]
            if len(labels) != len(values):
                return [TextContent(type="text", text=(
                    f"Error: labels ({len(labels)}) and values ({len(values)}) "
                    "must have the same length."
                ))]
            try:
                values = [float(v) for v in values]
            except (TypeError, ValueError):
                return [TextContent(type="text", text="Error: values must be numbers.")]

            try:
                import matplotlib
                matplotlib.use("Agg")
                import matplotlib.pyplot as plt
            except ImportError:
                return [TextContent(type="text", text=(
                    "matplotlib is not installed. Run: pip install -r requirements.txt"
                ))]

            import re, time
            charts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "charts")
            os.makedirs(charts_dir, exist_ok=True)
            if not output_filename:
                slug = re.sub(r"[^a-zA-Z0-9]+", "_", title).strip("_").lower()[:60] or "chart"
                output_filename = f"{slug}_{int(time.time())}"
            output_filename = re.sub(r"[^a-zA-Z0-9_\-]+", "_", output_filename)[:80]
            out_path = os.path.join(charts_dir, f"{output_filename}.png")

            fig, ax = plt.subplots(figsize=(10, 6))
            try:
                if chart_type == "bar":
                    ax.bar(labels, values, color="#1f77b4")
                    if x_label: ax.set_xlabel(x_label)
                    if y_label: ax.set_ylabel(y_label)
                    if any(len(str(l)) > 10 for l in labels):
                        plt.xticks(rotation=30, ha="right")
                elif chart_type == "hbar":
                    ax.barh(labels, values, color="#2ca02c")
                    ax.invert_yaxis()
                    if x_label: ax.set_xlabel(x_label)
                    if y_label: ax.set_ylabel(y_label)
                elif chart_type == "line":
                    ax.plot(labels, values, marker="o", color="#ff7f0e", linewidth=2)
                    if x_label: ax.set_xlabel(x_label)
                    if y_label: ax.set_ylabel(y_label)
                    if any(len(str(l)) > 10 for l in labels):
                        plt.xticks(rotation=30, ha="right")
                elif chart_type == "pie":
                    if all(v == 0 for v in values):
                        plt.close(fig)
                        return [TextContent(type="text", text="Error: pie chart needs at least one non-zero value.")]
                    ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=90)
                    ax.set_aspect("equal")

                ax.set_title(title, fontsize=14, fontweight="bold")
                fig.tight_layout()
                fig.savefig(out_path, dpi=150, bbox_inches="tight")
            finally:
                plt.close(fig)

            return [TextContent(type="text", text=(
                f"# Chart saved\n\n"
                f"![{title}]({out_path})\n\n"
                f"- **File:** `{out_path}`\n"
                f"- **Open in Finder:** `open \"{charts_dir}\"`\n"
                f"- **Type:** {chart_type}\n"
                f"- **Title:** {title}\n"
                f"- **Data points:** {len(labels)}\n"
                f"- **Total:** {sum(values):g}\n\n"
                f"The image above is a markdown image link to the absolute path — "
                f"AI hosts that render markdown will display the chart inline. "
                f"Otherwise, click/copy the file path to open it directly."
            ))]

        # ── get_attribute_definitions (DNG) ────────────────────
        elif name == "get_attribute_definitions":
            proj_id = arguments.get("project_identifier", "")
            if not proj_id:
                return [TextContent(type="text", text="Error: project_identifier is required.")]
            if not _projects_cache:
                _projects_cache = client.list_projects()
            project = _find_by_identifier(_projects_cache, proj_id)
            if not project:
                return [TextContent(type="text", text=f"Project not found: '{proj_id}'")]
            defs = client.get_attribute_definitions(project['url'])
            if not defs:
                return [TextContent(type="text", text=(
                    f"No attribute definitions found for '{project['title']}'. "
                    "Either the shapes are empty or the project URL is unreachable."
                ))]
            lines = [f"# Attribute Definitions in '{project['title']}'", ""]
            lines.append(f"**{len(defs)} unique attributes** (across all artifact types):\n")
            enums = [d for d in defs if d['allowed_values']]
            if enums:
                lines.append(f"\n## {len(enums)} enum-valued (selectable):\n")
                for d in enums[:25]:
                    vals = ", ".join(av['label'] for av in d['allowed_values'][:6])
                    lines.append(f"- **{d['title']}** (`{d['name']}`) → {vals}")
                    lines.append(f"  - Predicate: `{d['predicate_uri']}`")
            literals = [d for d in defs if not d['allowed_values']]
            if literals:
                lines.append(f"\n## {len(literals)} literal/free-form:\n")
                for d in literals[:25]:
                    lines.append(f"- **{d['title']}** (`{d['name']}`) → `{d['predicate_uri']}`")
            return [TextContent(type="text", text="\n".join(lines))]

        # ── update_requirement_attributes (DNG) ────────────────
        elif name == "update_requirement_attributes":
            req_url = arguments.get("requirement_url", "")
            attrs = arguments.get("attributes") or {}
            if not req_url or not attrs:
                return [TextContent(type="text", text=(
                    "Error: requirement_url and attributes are required."
                ))]
            result = client.update_requirement_attributes(req_url, attrs)
            if result and 'error' not in result:
                applied = result.get('updated', [])
                return [TextContent(type="text", text=(
                    f"# Requirement Attributes Updated\n\n"
                    f"- **URL:** `{result.get('url', req_url)}`\n"
                    f"- **Applied:** {', '.join(applied) if applied else '(none — keys did not match any shape)'}\n\n"
                    f"For enum-valued attributes, the value is mapped from a friendly label "
                    f"(e.g. 'High') to the corresponding allowed-value URI."
                ))]
            else:
                err = result.get('error', '') if result else ''
                return [TextContent(type="text", text=(
                    f"Failed to update requirement attributes.\n{err}"
                ))]

        # ── update_work_item (EWM) ─────────────────────────────
        elif name == "update_work_item":
            wi_url = arguments.get("workitem_url", "")
            fields = arguments.get("fields") or {}
            if not wi_url or not fields:
                return [TextContent(type="text", text=(
                    "Error: workitem_url and fields are required."
                ))]
            result = client.update_work_item(wi_url, fields)
            if result and 'error' not in result:
                return [TextContent(type="text", text=(
                    f"# Work Item Updated\n\n"
                    f"- **URL:** `{result.get('url', wi_url)}`\n"
                    f"- **Applied:** {', '.join(result.get('updated', []))}"
                ))]
            err = result.get('error', '') if result else ''
            return [TextContent(type="text", text=f"Failed to update work item.\n{err}")]

        # ── transition_work_item (EWM) ─────────────────────────
        elif name == "transition_work_item":
            wi_url = arguments.get("workitem_url", "")
            target = arguments.get("target_state", "")
            if not wi_url or not target:
                return [TextContent(type="text", text=(
                    "Error: workitem_url and target_state are required."
                ))]
            result = client.transition_work_item(wi_url, target)
            if result and 'error' not in result:
                return [TextContent(type="text", text=(
                    f"# Work Item Transitioned\n\n"
                    f"- **URL:** `{result['url']}`\n"
                    f"- **State:** `{result['state'].rsplit('/', 1)[-1]}`\n"
                    f"- **Action used:** `{result.get('action', '?')}`"
                ))]
            err = result.get('error', '') if result else ''
            return [TextContent(type="text", text=f"Failed to transition work item.\n{err}")]

        # ── query_work_items (EWM) ─────────────────────────────
        elif name == "query_work_items":
            ewm_proj = arguments.get("ewm_project", "")
            where = arguments.get("where", "")
            select = arguments.get("select", "*")
            page_size = int(arguments.get("page_size", 25) or 25)
            if not ewm_proj:
                return [TextContent(type="text", text="Error: ewm_project is required.")]
            if not _ewm_projects_cache:
                _ewm_projects_cache = client.list_ewm_projects()
            project = _find_by_identifier(_ewm_projects_cache, ewm_proj)
            if not project:
                return [TextContent(type="text", text=f"EWM project not found: '{ewm_proj}'")]
            items = client.query_work_items(
                ewm_project_url=project['url'],
                where=where,
                select=select,
                page_size=page_size,
            )
            if not items:
                return [TextContent(type="text", text=(
                    f"No work items returned for '{project['title']}' with where=`{where or '(none)'}`."
                ))]
            lines = [f"# Work Items in '{project['title']}'", "",
                     f"**{len(items)} match(es)**" + (f" for `{where}`" if where else ""), ""]
            for it in items[:50]:
                state_local = it['state'].rsplit('.', 1)[-1] if it.get('state') else ''
                type_local = it['type'].rsplit('/', 1)[-1] if it.get('type') else ''
                lines.append(f"- **{it.get('id', '?')}** {it.get('title', '')!r}  "
                              f"state={state_local} type={type_local}")
                lines.append(f"  - {it.get('url', '')}")
            return [TextContent(type="text", text="\n".join(lines))]

        # ── get_ewm_workitem_types ─────────────────────────────
        elif name == "get_ewm_workitem_types":
            ewm_proj_arg = arguments.get("ewm_project", "")
            if not ewm_proj_arg:
                return [TextContent(type="text", text="Error: ewm_project is required.")]
            ewm_projects = client.list_ewm_projects()
            ewm_match = _find_by_identifier(ewm_projects, ewm_proj_arg)
            if not ewm_match:
                return [TextContent(type="text",
                    text=f"EWM project not found: {ewm_proj_arg}. Use list_projects domain='ewm' to see available.")]
            types = client.get_ewm_workitem_types(ewm_match['url'])
            if not types:
                return [TextContent(type="text",
                    text=f"No work item types discoverable for EWM project '{ewm_match.get('title', ewm_proj_arg)}'. The project's services document may not expose creation factories.")]
            lines = [f"# Work item types in {ewm_match.get('title', ewm_proj_arg)}", "",
                     f"**{len(types)} type(s)** — show this list to the user when they need to pick a type:", ""]
            for t in types:
                lines.append(f"- **{t['name']}**")
                lines.append(f"  - creation_url: `{t['creation_url']}`")
                if t.get('shape_url'):
                    lines.append(f"  - shape_url: `{t['shape_url']}`")
            return [TextContent(type="text", text="\n".join(lines))]

        # ── create_link (cross-domain) ─────────────────────────
        elif name == "create_link":
            src = arguments.get("source_url", "")
            ltype = arguments.get("link_type_uri", "")
            tgt = arguments.get("target_url", "")
            if not (src and ltype and tgt):
                return [TextContent(type="text", text=(
                    "Error: source_url, link_type_uri, and target_url are all required."
                ))]
            result = client.create_link(src, ltype, tgt)
            if result and 'error' not in result:
                return [TextContent(type="text", text=(
                    f"# Link Created\n\n"
                    f"- **Source:** `{result['source']}`\n"
                    f"- **Target:** `{result['target']}`\n"
                    f"- **Link type:** `{result['link_type']}`\n\n"
                    f"DNG normalizes custom link-type predicates after PUT — when re-fetching "
                    f"the source, the link will appear under its standard local-name prefix "
                    f"(e.g. `:satisfies`)."
                ))]
            err = result.get('error', '') if result else ''
            return [TextContent(type="text", text=f"Failed to create link.\n{err}")]

        # ── link_workitem_to_external_url ─────────────────────────
        elif name == "link_workitem_to_external_url":
            wi_url = arguments.get("workitem_url", "").strip()
            ext_url = arguments.get("external_url", "").strip()
            label = arguments.get("label", "External link").strip() or "External link"
            comment = arguments.get("comment", "").strip()
            if not wi_url or not ext_url:
                return [TextContent(type="text", text="Error: workitem_url and external_url are required.")]
            result = client.link_workitem_to_external_url(wi_url, ext_url, label, comment)
            if result and 'error' not in result:
                return [TextContent(type="text", text=(
                    f"# External link attached\n\n"
                    f"**EWM work item:** {wi_url}\n"
                    f"**Linked to:** [{label}]({ext_url})\n"
                    + (f"**Note:** {comment}\n" if comment else "")
                    + f"\nIn EWM, this link appears under the work item's "
                    f"**Links → References** panel as `oslc_cm:relatedURL`. "
                    f"Click-through goes directly to the external URL."
                ))]
            err = result.get('error', 'unknown error') if result else 'unknown error'
            if '403' in err or 'permission' in err.lower():
                err += ("\n\nLikely cause: you don't have write access to "
                        "this work item. Permissions are project-scoped — "
                        "ask the EWM project admin to grant your role "
                        "'Modify' on Work Items.")
            return [TextContent(type="text", text=f"Error: {err}")]

        # ── get_workflow_states ────────────────────────────────────
        elif name == "get_workflow_states":
            wi_url = arguments.get("workitem_url", "").strip()
            if not wi_url:
                return [TextContent(type="text", text="Error: workitem_url is required.")]
            result = client.get_workflow_states(wi_url)
            if result and 'error' not in result:
                cur = result.get('current_state', {}) or {}
                states = result.get('available_states', []) or []
                lines = [
                    f"# Workflow states for this work item",
                    "",
                    f"**Workflow:** `{result.get('workflow_id', '?')}`",
                    f"**Current state:** **{cur.get('name', '?')}**",
                    "",
                    f"**Available states ({len(states)}):**",
                ]
                for s in states:
                    marker = " ← current" if s.get('uri') == cur.get('uri') else ""
                    lines.append(f"- {s.get('name', '?')}{marker}")
                lines.append("")
                lines.append(
                    "Use any of these names as `target_state` when calling "
                    "`transition_work_item`. The names ARE case-sensitive — "
                    "copy verbatim."
                )
                return [TextContent(type="text", text="\n".join(lines))]
            err = result.get('error', 'unknown') if result else 'unknown'
            return [TextContent(type="text", text=f"Error: {err}")]

        # ── elm_mcp_health (self-diagnose) ─────────────────────────
        elif name == "elm_mcp_health":
            import datetime as _dt
            now = _dt.datetime.utcnow().isoformat() + "Z"
            # Connection state
            conn_state = "not connected"
            elm_url = ""
            elm_user = ""
            if _client:
                conn_state = "connected"
                elm_url = getattr(_client, 'base_url', '') or getattr(_client, 'url', '')
                elm_user = getattr(_client, 'username', '')
            elif _client_error:
                conn_state = f"error: {_client_error}"

            # Auto-update status
            try:
                last_check_path = _last_check_path()
                if os.path.exists(last_check_path):
                    import time as _t
                    with open(last_check_path) as f:
                        last = float(f.read().strip() or "0")
                    secs_ago = int(_t.time() - last)
                    update_check = (
                        f"last checked {secs_ago // 3600}h "
                        f"{(secs_ago % 3600) // 60}m ago"
                    )
                else:
                    update_check = "never checked yet"
            except Exception:
                update_check = "throttle file unreadable"

            git_status = "git-managed (auto-update available)" if _is_git_managed() else "not git-managed (manual install)"
            auto_update_enabled = (os.environ.get("ELM_MCP_AUTO_UPDATE", "1") != "0")

            # Active runs
            runs = _list_active_runs()
            run_lines = []
            for r in runs[:10]:
                run_lines.append(
                    f"  - `{r['run_id']}` [{r['command']}] phase={r['phase']} "
                    f"started={r['started_at'][:19]}"
                )
            if not runs:
                run_lines = ["  _(none active)_"]
            elif len(runs) > 10:
                run_lines.append(f"  _(+{len(runs)-10} more)_")

            return [TextContent(type="text", text=(
                f"# ELM MCP — Health Check\n\n"
                f"**Time:** {now}\n"
                f"**Version:** v{__version__}\n"
                f"**Install dir:** `{_project_dir()}`\n"
                f"**Git status:** {git_status}\n\n"
                f"## Connection\n"
                f"- **State:** {conn_state}\n"
                f"- **ELM URL:** {elm_url or '_(none)_'}\n"
                f"- **User:** {elm_user or '_(none)_'}\n\n"
                f"## Updates\n"
                f"- **Auto-update enabled:** {auto_update_enabled}\n"
                f"- **Last check:** {update_check}\n"
                f"- To update manually: say *update yourself* (single tool call)\n\n"
                f"## Active build runs ({len(runs)})\n"
                + "\n".join(run_lines) + "\n\n"
                f"## Environment\n"
                f"- **Python:** {sys.version.split()[0]} at `{sys.executable}`\n"
                f"- **Tool count registered:** 51 (run `list_capabilities` for the full inventory)\n\n"
                f"_If something looks wrong above and you can't fix it from "
                f"chat: run `python3 setup.py --diagnose` from a terminal — "
                f"it does the same checks plus a full MCP-handshake test._"
            ))]

        # ── create_defect (EWM) ────────────────────────────────
        elif name == "create_defect":
            ewm_proj = arguments.get("ewm_project", "")
            title = arguments.get("title", "")
            description = arguments.get("description", "")
            severity = arguments.get("severity", "")
            req_url = arguments.get("requirement_url", "")
            tc_url = arguments.get("test_case_url", "")
            if not ewm_proj or not title:
                return [TextContent(type="text", text=(
                    "Error: ewm_project and title are required."
                ))]
            if not _ewm_projects_cache:
                _ewm_projects_cache = client.list_ewm_projects()
            project = _find_by_identifier(_ewm_projects_cache, ewm_proj)
            if not project:
                return [TextContent(type="text", text=f"EWM project not found: '{ewm_proj}'")]
            result = client.create_defect(
                service_provider_url=project['url'],
                title=title, description=description,
                severity=severity or None,
                requirement_url=req_url or None,
                test_case_url=tc_url or None,
            )
            if result and 'error' not in result:
                lines = [
                    "# Defect Created",
                    "",
                    f"- **Title:** {result['title']}",
                    f"- **Project:** {project['title']}",
                    f"- **URL:** {result['url']}",
                ]
                if severity:
                    lines.append(f"- **Severity:** {severity}")
                if req_url:
                    lines.append(f"- **Affects requirement:** `{req_url}`")
                if tc_url:
                    lines.append(f"- **Related test case:** `{tc_url}`")
                return [TextContent(type="text", text="\n".join(lines))]
            err = result.get('error', '') if result else ''
            return [TextContent(type="text", text=(
                f"Failed to create defect in '{project['title']}'.\n{err}"
            ))]

        # ── scm_list_projects ─────────────────────────────────
        elif name == "scm_list_projects":
            projects = client.scm_list_projects()
            if not projects:
                return [TextContent(type="text", text=(
                    "No SCM projects found. Either /ccm/oslc-scm/catalog is unreachable "
                    "or the catalog is empty."
                ))]
            lines = [f"# SCM Projects ({len(projects)} total)", ""]
            for i, p in enumerate(projects[:50], 1):
                lines.append(f"{i}. **{p['name']}**")
                lines.append(f"   - paId: `{p['projectAreaId']}`")
            if len(projects) > 50:
                lines.append(f"\n…and {len(projects) - 50} more.")
            return [TextContent(type="text", text="\n".join(lines))]

        # ── scm_list_changesets ────────────────────────────────
        elif name == "scm_list_changesets":
            project_name = arguments.get("project_name", "") or None
            limit = int(arguments.get("limit", 25) or 25)
            cs = client.scm_list_changesets(project_name=project_name, limit=limit)
            if not cs:
                return [TextContent(type="text", text=(
                    "No change-sets returned. The TRS feed may be empty or the project "
                    f"filter '{project_name}' did not match any change-sets in the recent "
                    "TRS pages."
                ))]
            lines = [f"# Recent SCM Change-Sets ({len(cs)})", ""]
            for x in cs:
                lines.append(f"- **{x['itemId']}** — {x['title']!r}")
                lines.append(f"  - Component: {x['component']}, Author: `{x['author']}`")
                lines.append(f"  - Modified: {x['modified']}, Changes: {x['totalChanges']}")
                if x['workItems']:
                    lines.append(f"  - Linked WIs: " + ", ".join(w['workItemId'] for w in x['workItems']))
            return [TextContent(type="text", text="\n".join(lines))]

        # ── scm_get_changeset ──────────────────────────────────
        elif name == "scm_get_changeset":
            cs_id = arguments.get("changeset_id", "")
            if not cs_id:
                return [TextContent(type="text", text="Error: changeset_id is required.")]
            d = client.scm_get_changeset(cs_id)
            if 'error' in d:
                return [TextContent(type="text", text=f"Failed: {d['error']}")]
            lines = [
                f"# Change-Set {d['itemId']}", "",
                f"- **Title:** {d['title']}",
                f"- **Component:** {d['component']}",
                f"- **Author:** `{d['author']}`",
                f"- **Modified:** {d['modified']}",
                f"- **Total changes:** {d['totalChanges']}",
                f"- **Reportable URL:** {d['reportable_url']}",
                f"- **Canonical URL:** {d['canonical_url']}",
            ]
            if d.get('workItems'):
                lines.append(f"\n### Linked Work Items ({len(d['workItems'])})")
                for w in d['workItems']:
                    lines.append(f"- {w['workItemId']}: {w['url']}")
            return [TextContent(type="text", text="\n".join(lines))]

        # ── scm_get_workitem_changesets ────────────────────────
        elif name == "scm_get_workitem_changesets":
            wi_id = arguments.get("workitem_id", "")
            if not wi_id:
                return [TextContent(type="text", text="Error: workitem_id is required.")]
            cs = client.scm_get_workitem_changesets(wi_id)
            if not cs:
                return [TextContent(type="text", text=(
                    f"Work item {wi_id} has no SCM change-sets attached. "
                    "(That's normal for non-development work.)"
                ))]
            lines = [f"# Change-Sets on Work Item {wi_id} ({len(cs)})", ""]
            for x in cs:
                lines.append(f"- **{x['changeSetId']}** — {x['title']!r}")
                lines.append(f"  - URL: {x['url']}")
            return [TextContent(type="text", text="\n".join(lines))]

        # ── review_get ─────────────────────────────────────────
        elif name == "review_get":
            wi_id = arguments.get("workitem_id", "")
            if not wi_id:
                return [TextContent(type="text", text="Error: workitem_id is required.")]
            r = client.review_get(wi_id)
            if 'error' in r:
                return [TextContent(type="text", text=f"Failed: {r['error']}")]
            lines = [
                f"# Review-View of Work Item {wi_id}", "",
                f"- **Title:** {r.get('title','')}",
                f"- **State:** `{r.get('state','').rsplit('/',1)[-1]}`",
                f"- **Type:** `{r.get('type','').rsplit('/',1)[-1]}`",
                f"- **approved:** {r.get('approved')}",
                f"- **reviewed:** {r.get('reviewed')}",
                f"- **Comments URL:** `{r.get('comments_url','')}`",
            ]
            apps = r.get('approvals', [])
            lines.append(f"\n### Approvals ({len(apps)})")
            for a in apps[:20]:
                lines.append(f"- {a.get('descriptor','')} — approver `{a.get('approver','')}` "
                              f"state {a.get('stateName','')} ({a.get('stateIdentifier','')})")
            cs = r.get('changeSets', [])
            lines.append(f"\n### Linked Change-Sets ({len(cs)})")
            for c in cs[:20]:
                lines.append(f"- {c['changeSetId']}: {c['url']}")
            return [TextContent(type="text", text="\n".join(lines))]

        # ── review_list_open ───────────────────────────────────
        elif name == "review_list_open":
            ewm_proj = arguments.get("ewm_project", "")
            if not ewm_proj:
                return [TextContent(type="text", text="Error: ewm_project is required.")]
            if not _ewm_projects_cache:
                _ewm_projects_cache = client.list_ewm_projects()
            project = _find_by_identifier(_ewm_projects_cache, ewm_proj)
            if not project:
                return [TextContent(type="text", text=f"EWM project not found: '{ewm_proj}'")]
            items = client.review_list_open(project['url'])
            if not items:
                return [TextContent(type="text", text=(
                    f"No open review work items in '{project['title']}'. "
                    "(This is the normal case on this server — review-typed WIs are rare.)"
                ))]
            lines = [f"# Open Reviews in '{project['title']}' ({len(items)})", ""]
            for it in items:
                lines.append(f"- **{it.get('id', '?')}** {it.get('title', '')!r} state="
                              f"`{it.get('state','').rsplit('.',1)[-1]}`")
            return [TextContent(type="text", text="\n".join(lines))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error("Tool %s failed: %s\n%s", name, e, tb)
        return [TextContent(type="text", text=(
            f"Error in {name}: {str(e)}\n\n{tb}"
        ))]


# ── Main ──────────────────────────────────────────────────────

async def main():
    logger.info(f"IBM ELM MCP Server v{__version__} starting (53 tools, 9 prompts, 3 resource templates)")
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
