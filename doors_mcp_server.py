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
logger = logging.getLogger("elm-mcp")
from mcp.server import Server
from mcp.types import (
    Tool, TextContent,
    Resource, ResourceTemplate, BlobResourceContents, TextResourceContents,
    Prompt, PromptMessage, PromptArgument,
)
import mcp.server.stdio
from dotenv import load_dotenv
from doors_client import DOORSNextClient

# Jira client is lazy-imported inside the handlers so the server starts
# fine even if a user hasn't configured Jira creds yet (it's optional).
# See jira_client.py for the direct-REST approach + why we don't use
# Atlassian's hosted MCP server.

load_dotenv()

# Bumped on each release. The auto-update logic below uses this to
# decide if a newer GitHub release exists; the `connect_to_elm`
# response also surfaces it so users always know what version they're
# running.
__version__ = "0.16.1"
GITHUB_REPO = "brettscharm/elm-mcp"

app = Server("elm-mcp")

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


def _version_tuple(v: str) -> tuple:
    """Parse 'X.Y.Z' (or 'vX.Y.Z') into a comparable tuple. Returns
    (0,0,0) on any parse failure so 'unknown' versions compare equal
    to the floor. Used to guarantee we never auto-DOWNGRADE because
    the latest GitHub Release tag is older than the installed version."""
    try:
        s = (v or "").lstrip("v")
        parts = s.split(".")
        return tuple(int(p) for p in parts[:3] if p.isdigit()) or (0, 0, 0)
    except Exception:
        return (0, 0, 0)


def _is_newer_version(latest: Optional[str], current: str) -> bool:
    """True if `latest` is strictly newer than `current`. Both should be
    semver-ish 'X.Y.Z' strings. Returns False if equal, older, or
    unparseable — never auto-downgrade."""
    if not latest:
        return False
    return _version_tuple(latest) > _version_tuple(current)


def _git_pull() -> bool:
    """Hard-reset the install dir to origin/main. Handles the detached-
    HEAD case (e.g. after a `revert_elm_mcp` checkout) by force-checking
    out main first. Returns True on success."""
    import subprocess
    pd = _project_dir()
    try:
        subprocess.run(["git", "-C", pd, "fetch", "--quiet", "origin"],
                       check=True, timeout=15)
        # If we're in detached HEAD (after a revert), switch back to main
        # before resetting so the branch ref advances cleanly.
        head_ref = subprocess.run(
            ["git", "-C", pd, "symbolic-ref", "--quiet", "HEAD"],
            capture_output=True, text=True,
        )
        if head_ref.returncode != 0:
            # Detached HEAD — re-attach to main first.
            subprocess.run(
                ["git", "-C", pd, "-c", "advice.detachedHead=false",
                 "checkout", "main"],
                check=True, timeout=10, capture_output=True,
            )
        subprocess.run(["git", "-C", pd, "reset", "--hard", "--quiet",
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
    if not _is_newer_version(latest, __version__):
        # latest is either equal to current OR OLDER (rare, but happens
        # when the latest GitHub Release hasn't caught up with main).
        # In either case: nothing to do — never auto-downgrade.
        sys.stderr.write(
            f"[elm-mcp] v{__version__}: up to date "
            f"(latest release v{latest}).\n"
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
        if not _is_newer_version(latest, __version__):
            # Equal OR running ahead of latest published release —
            # both are "fine, nothing to do" from the user's POV.
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


# ── BOB Team Actions — auto session logging ─────────────────────
# Per-process session tracker. Each session represents one user × one
# DNG project, started when the user first does material work in that
# session. Auto-log entries get appended (throttled) to a per-user
# artifact in the BOB Team Actions module. Anyone else's Bob can read
# the module to see what the team is doing across the project.

_TEAM_ACTIONS_ENABLED = os.environ.get("ELM_MCP_TEAM_ACTIONS", "1") != "0"
_TEAM_ACTIONS_MODULE_NAME = os.environ.get(
    "ELM_MCP_TEAM_ACTIONS_MODULE", "BOB Team Actions"
)
try:
    _TEAM_ACTIONS_INTERVAL_SEC = int(
        os.environ.get("ELM_MCP_TEAM_ACTIONS_INTERVAL_MIN", "10")
    ) * 60
except ValueError:
    _TEAM_ACTIONS_INTERVAL_SEC = 600

# session_key (user@project_url) -> session dict
_TEAM_SESSIONS: Dict[str, Dict] = {}


def _team_session_key(user: str, project_url: str) -> str:
    return f"{user}@@{project_url}"


def _get_or_start_team_session(user: str, project_url: str) -> Dict:
    """Return the live session for (user, project), creating one if
    none exists yet."""
    import datetime as _dt
    import uuid as _uuid
    key = _team_session_key(user, project_url)
    sess = _TEAM_SESSIONS.get(key)
    if sess is not None:
        return sess
    now = _dt.datetime.utcnow().isoformat() + "Z"
    sess = {
        "session_id": _uuid.uuid4().hex[:10],
        "user": user,
        "project_url": project_url,
        "started_at": now,
        "last_log_at": "",  # never flushed yet
        "last_activity_at": now,
        "status": "in_progress",
        "activity_buffer": [],
        "module_url": "",
        "artifact_url": "",
        "summary_so_far": [],  # list of past flush summaries (most recent last)
    }
    _TEAM_SESSIONS[key] = sess
    return sess


def _record_team_activity(kind: str, summary: str,
                           user: str = "", project_url: str = "") -> None:
    """Buffer an activity entry. Called from write-tool handlers. Cheap —
    just appends to memory. The actual DNG write happens later via
    _maybe_flush_team_log on the throttle interval."""
    if not _TEAM_ACTIONS_ENABLED:
        return
    if not user or not project_url:
        return  # need both to identify a session
    import datetime as _dt
    sess = _get_or_start_team_session(user, project_url)
    sess["last_activity_at"] = _dt.datetime.utcnow().isoformat() + "Z"
    sess["activity_buffer"].append({
        "ts": sess["last_activity_at"],
        "kind": kind,
        "summary": summary,
    })


def _team_session_for_current_user(project_url: str = "") -> Optional[Dict]:
    """Look up the active team-actions session for the currently-
    authenticated user against the given project (or any project if
    not given). Returns None if no auth or no session yet."""
    if not _TEAM_ACTIONS_ENABLED:
        return None
    if _client is None:
        return None
    user = getattr(_client, "username", "") or ""
    if not user:
        return None
    if project_url:
        return _TEAM_SESSIONS.get(_team_session_key(user, project_url))
    # Return the most recent session for this user across any project
    matches = [s for s in _TEAM_SESSIONS.values() if s["user"] == user]
    if not matches:
        return None
    return max(matches, key=lambda s: s.get("last_activity_at", ""))


def _maybe_flush_team_log(force: bool = False) -> None:
    """If any active session is past its throttle interval, flush its
    buffer to DNG. Cheap when not flushing (just timestamp checks)."""
    if not _TEAM_ACTIONS_ENABLED:
        return
    if _client is None:
        return
    import datetime as _dt
    now = _dt.datetime.utcnow()
    for sess in list(_TEAM_SESSIONS.values()):
        if sess["status"] != "in_progress":
            continue
        if not sess["activity_buffer"] and not force:
            continue
        # Throttle check
        if not force and sess["last_log_at"]:
            try:
                last = _dt.datetime.fromisoformat(
                    sess["last_log_at"].rstrip("Z"))
                if (now - last).total_seconds() < _TEAM_ACTIONS_INTERVAL_SEC:
                    continue
            except (ValueError, TypeError):
                pass
        try:
            _flush_session_to_dng(sess)
        except Exception as e:
            sys.stderr.write(
                f"[elm-mcp] team-actions flush failed for session "
                f"{sess['session_id']}: {e}\n"
            )


def _ensure_team_actions_module(sess: Dict) -> str:
    """Find the BOB Team Actions module in the session's project, or
    create it. Caches the URL on the session. Returns the module URL or
    empty string on failure."""
    if sess.get("module_url"):
        return sess["module_url"]
    if _client is None:
        return ""
    project_url = sess["project_url"]
    try:
        modules = _client.get_modules(project_url) or []
        target = next(
            (m for m in modules
             if m.get("title", "").strip().lower()
             == _TEAM_ACTIONS_MODULE_NAME.lower()),
            None,
        )
        if target:
            sess["module_url"] = target.get("url", "")
            return sess["module_url"]
        new_mod = _client.create_module(
            project_url,
            _TEAM_ACTIONS_MODULE_NAME,
            "Auto-created by elm-mcp. Per-user session entries — "
            "anyone on the team can read this module to see what "
            "everyone is doing across the project.",
        )
        if new_mod and "error" not in new_mod:
            sess["module_url"] = new_mod.get("url", "")
            return sess["module_url"]
    except Exception:
        pass
    return ""


def _summarize_buffer(buffer: List[Dict]) -> str:
    """Human-readable summary of buffered activity entries."""
    if not buffer:
        return "(no activity in this window)"
    counts: Dict[str, int] = {}
    notes: List[str] = []
    for e in buffer:
        kind = e.get("kind", "other")
        counts[kind] = counts.get(kind, 0) + 1
        s = e.get("summary", "").strip()
        if s and len(notes) < 5:
            notes.append(s)
    parts = []
    for kind, n in counts.items():
        parts.append(f"{n}× {kind}")
    summary = " · ".join(parts)
    if notes:
        summary += "\n  - " + "\n  - ".join(notes)
    return summary


def _render_session_artifact_body(sess: Dict) -> str:
    """Render the session as the body of its team-actions artifact."""
    lines = [
        f"# {sess['user']} — session {sess['session_id']}",
        "",
        f"**Status:** {sess.get('status', 'in_progress')}",
        f"**Project:** {sess['project_url']}",
        f"**Started:** {sess['started_at']}",
        f"**Last activity:** {sess['last_activity_at']}",
        "",
        "## Recent activity",
    ]
    summaries = sess.get("summary_so_far", []) or []
    for s in summaries[-20:]:  # last 20 flush windows
        lines.append(f"- **{s.get('flushed_at', '?')[:19]}Z** — {s.get('summary', '')}")
        for note in s.get("notes", [])[:3]:
            lines.append(f"  - {note}")
    if sess.get("activity_buffer"):
        lines.append("")
        lines.append("## Activity since last flush (not yet rolled into history)")
        for e in sess["activity_buffer"][-10:]:
            lines.append(f"- {e.get('summary', '?')}")
    return "\n".join(lines)


def _flush_session_to_dng(sess: Dict) -> None:
    """Write or update the per-session artifact in BOB Team Actions module.
    Does not raise — caller wraps in try/except."""
    if _client is None:
        return
    import datetime as _dt
    module_url = _ensure_team_actions_module(sess)
    if not module_url:
        return  # couldn't find or create module; skip silently

    # Roll buffer into summary_so_far
    buf = sess.get("activity_buffer", [])
    if buf:
        notes = [e.get("summary", "") for e in buf if e.get("summary")]
        sess["summary_so_far"].append({
            "flushed_at": _dt.datetime.utcnow().isoformat() + "Z",
            "summary": _summarize_buffer(buf).split("\n")[0],
            "notes": notes,
        })
        sess["activity_buffer"] = []

    body = _render_session_artifact_body(sess)
    title = f"[BOB-TEAM] {sess['user']} — session {sess['session_id']}"

    if sess.get("artifact_url"):
        # Update existing artifact in place
        try:
            _client.update_requirement(
                sess["artifact_url"],
                title=title,
                content=body,
            )
        except Exception:
            pass
    else:
        # Create new — find a shape (System Requirement or first available)
        try:
            shapes = _client.get_artifact_shapes(sess["project_url"]) or []
            shape = next(
                (s for s in shapes
                 if "system requirement" in s.get("name", "").lower()),
                shapes[0] if shapes else None,
            )
            if not shape:
                return
            new_art = _client.create_requirement(
                project_url=sess["project_url"],
                title=title,
                content=body,
                shape_url=shape.get("url", ""),
            )
            if new_art and "error" not in new_art:
                sess["artifact_url"] = new_art.get("url", "")
                # Best-effort: bind to the BOB Team Actions module
                try:
                    _client.add_to_module(module_url, [sess["artifact_url"]])
                except Exception:
                    pass
        except Exception:
            pass

    sess["last_log_at"] = _dt.datetime.utcnow().isoformat() + "Z"


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
            name="getting-started",
            description=(
                "Use-case-first orientation for users new to the ELM "
                "MCP. Routes the user's natural-language intent ('I "
                "want to import a Jira epic', 'I want to build a new "
                "service end-to-end', 'show me what's already in "
                "DNG', etc.) to the right prompt or tool. The output "
                "is a single guided question + a recommended next "
                "step — not an enumerated tool list. Call this "
                "whenever the user says 'help', 'what can you do', "
                "'where do I start', or otherwise signals they don't "
                "know which prompt fits their need."
            ),
            arguments=[
                PromptArgument(
                    name="intent",
                    description="What the user wants to do, in their own words. Optional — if missing, the AI asks one clarifying question.",
                    required=False,
                ),
            ],
        ),
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
                "Brownfield work-item import — user provides EITHER a PDF "
                "path OR pasted text (Jira epic export, Azure DevOps work "
                "item, copy-paste from any source) and AI parses the "
                "complete work-item graph into ELM: an EWM work item for the "
                "main item, DNG requirements for the functional/NFR sections, "
                "ETM test cases for the acceptance criteria, EWM child stories "
                "for linked sub-items, and proper cross-tool links between "
                "all of them. Performs gap detection (vague NFRs, untestable "
                "ACs, missing fields) and surfaces decision points (work item "
                "type — picked from the project's actual list, NEVER guessed). "
                "Pasted-text path is the workaround for hosts (like IBM Bob) "
                "whose chat UI doesn't natively extract PDF attachments. "
                "Composes naturally with /build-project for code generation "
                "after import."
            ),
            arguments=[
                PromptArgument(
                    name="pdf_path",
                    description="Absolute path to the work-item PDF on the user's machine. Optional. Use this when the user can give you a path; otherwise prefer `content` for pasted text. AI will ask if neither is provided.",
                    required=False,
                ),
                PromptArgument(
                    name="content",
                    description="Raw text of the work item (e.g. user copy-pasted the body of a Jira epic into chat). Optional; alternative to `pdf_path`. Use this whenever the user provides text directly — IBM Bob in particular doesn't auto-extract PDF attachments, so paste is often the only path.",
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
            name="import-jira",
            description=(
                "Live Jira import — pulls a Jira issue via elm-mcp's native "
                "`get_jira_issue` tool (direct REST, API-token auth), runs "
                "interview discipline on the ticket body, creates DNG "
                "requirements with a `Source: JIRA-XXX` back-reference "
                "stamped per req, and posts a Jira back-link via "
                "`add_jira_comment`. Bidirectional Jira ↔ DNG traceability "
                "without depending on Atlassian's hosted MCP server (which "
                "uses OAuth and doesn't complete in IBM Bob's embedded "
                "webview). Requires JIRA_BASE_URL / JIRA_EMAIL / "
                "JIRA_API_TOKEN in .env — run `python3 ~/.elm-mcp/setup.py "
                "--with-jira` to set them up. See BOB.md Step 3l."
            ),
            arguments=[
                PromptArgument(
                    name="issue_key",
                    description="Jira issue key like 'PROJ-123' OR a full Atlassian URL. Optional — AI will ask if not provided.",
                    required=False,
                ),
                PromptArgument(
                    name="dng_project",
                    description="DNG project where the requirements module should be created. Optional.",
                    required=False,
                ),
                PromptArgument(
                    name="module_name",
                    description="Name for the new DNG module. Optional.",
                    required=False,
                ),
                PromptArgument(
                    name="walk_graph",
                    description="'parent', 'children', 'both', or 'none'. Optional — default is to ask when ambiguous.",
                    required=False,
                ),
            ],
        ),
        Prompt(
            name="audit-requirements",
            description=(
                "Audit a DNG module's requirements for quality and "
                "status. Runs deterministic INCOSE GtWR + IEEE 29148 "
                "lint on every req's text, plus status-awareness "
                "checks (Approved vs Draft, missing owners, missing "
                "verification methods). Returns a module health "
                "report and recommends opening the Requirements "
                "Quality Assistant agent in IBM ELM AI Hub for "
                "semantic scoring. Read-only; safe to run any time."
            ),
            arguments=[
                PromptArgument(
                    name="project",
                    description="DNG project name or number. Optional — AI uses currently-connected project or asks.",
                    required=False,
                ),
                PromptArgument(
                    name="module",
                    description="Module title, ID, or URL. Optional — AI lists modules and asks if not given.",
                    required=False,
                ),
            ],
        ),
        Prompt(
            name="trace-gaps",
            description=(
                "Cross-domain traceability gap finder. Walks DNG -> "
                "EWM -> ETM and reports: requirements without an "
                "implementing task, requirements without a "
                "validating test case, orphan tasks, orphan test "
                "cases. Read-only. Ends with a pointer to "
                "Requirements Quality Assistant in IBM ELM AI Hub "
                "for semantic gap analysis."
            ),
            arguments=[
                PromptArgument(name="project", description="DNG project. Optional.", required=False),
                PromptArgument(name="module", description="DNG module. Optional.", required=False),
                PromptArgument(name="ewm_project", description="EWM project for task scan. Optional.", required=False),
                PromptArgument(name="etm_project", description="ETM project for test scan. Optional.", required=False),
            ],
        ),
        Prompt(
            name="init-do-178c",
            description=(
                "Walk through DO-178C (aerospace / defense software) "
                "project initialization in ELM: artifact types "
                "(System Reqs -> HLR -> LLR + Software Verification), "
                "attribute schema (DAL A-E, Verification Method "
                "I/A/R/T), link types, lifecycle states. Most schema "
                "work is manual in DNG admin; this prompt surfaces "
                "the exact values + creates the modules where the "
                "API allows."
            ),
            arguments=[
                PromptArgument(name="dng_project", description="DNG project name. Optional.", required=False),
                PromptArgument(name="dal", description="Design Assurance Level: A/B/C/D/E. Optional.", required=False),
                PromptArgument(name="system_name", description="Short system name. Optional.", required=False),
            ],
        ),
        Prompt(
            name="init-iso-26262",
            description=(
                "Walk through ISO 26262 (automotive functional "
                "safety) project initialization: artifact types "
                "(Hazards -> Safety Goals -> FSR -> TSR -> SwSR / "
                "HwSR), ASIL-graded attributes, hazard analysis "
                "context, lifecycle, DIA constraints. Includes "
                "explicit prompt for HARA prerequisite."
            ),
            arguments=[
                PromptArgument(name="dng_project", description="DNG project. Optional.", required=False),
                PromptArgument(name="asil", description="ASIL level: A/B/C/D. Optional.", required=False),
                PromptArgument(name="system_name", description="Short system name. Optional.", required=False),
            ],
        ),
        Prompt(
            name="project-scaffold",
            description=(
                "Pre-flight interview before the first requirement "
                "gets written. Captures organizational context, "
                "regulatory context, ELM project structure decisions, "
                "and cross-tool linking strategy across four layers. "
                "Saves answers as a Project Charter artifact in DNG. "
                "Run this before /build-new-project for any real "
                "enterprise project."
            ),
            arguments=[
                PromptArgument(name="dng_project", description="DNG project. Optional.", required=False),
                PromptArgument(name="methodology", description="Agile/SAFe/V-Model/DO-178C/ISO 26262/IEC 62304/Custom. Optional.", required=False),
                PromptArgument(name="domain", description="Brief domain (e.g. 'fleet tracking'). Optional.", required=False),
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

    if name == "getting-started":
        intent = (args.get("intent", "") or "").strip()
        if not intent:
            return [PromptMessage(
                role="user",
                content=TextContent(type="text", text=(
                    "The user invoked /getting-started without an "
                    "intent. Ask them ONE question, no longer than two "
                    "lines:\n\n"
                    "*\"What are you trying to do? A few common starting "
                    "points: (a) build a new project from scratch, (b) "
                    "import existing requirements / Jira epic / PDF, "
                    "(c) read or edit existing reqs in DNG, (d) check "
                    "what the team's been doing, (e) something else — "
                    "tell me in your own words.\"*\n\n"
                    "When they answer, route their intent using the "
                    "table below. Don't enumerate tools — just take "
                    "them straight to the right starting point.\n\n"
                    "Routing table (intent → next action):\n"
                    "- *build a new project / new service / from scratch* → invoke `/build-new-project`\n"
                    "- *import a Jira epic / work-item PDF / paste reqs* → invoke `/import-work-item` (multi-artifact) or `/import-requirements` (just reqs)\n"
                    "- *read / show / list reqs in [module]* → call `connect_to_elm` if needed, then `list_projects` → `get_modules` → `get_module_requirements`\n"
                    "- *what's the team doing / who's stuck / status* → call `get_team_actions`\n"
                    "- *resume a paused build* → call `build_project_resume`\n"
                    "- *create tasks / tests for existing reqs* → invoke `/full-lifecycle` (covers tasks + tests for reqs already created)\n"
                    "- *find a requirement by ID (REQ-123)* → call `resolve_requirement_id`\n"
                    "- *check ELM connection / version / what's installed* → call `elm_mcp_health` or `list_capabilities`\n"
                    "- *something else* → ask one more clarifying question; do NOT dump a tool list"
                )),
            )]
        # Intent provided — route directly
        return [PromptMessage(
            role="user",
            content=TextContent(type="text", text=(
                f"User's intent: \"{intent}\"\n\n"
                f"Match this intent to the right starting point and "
                f"invoke it. Use this routing table:\n\n"
                f"- *build a new project / new service / from scratch* → invoke `/build-new-project` with their idea\n"
                f"- *import a Jira epic / work-item PDF / paste reqs / brownfield* → invoke `/import-work-item` (multi-artifact) or `/import-requirements` (just reqs) depending on what they have\n"
                f"- *read / show / list reqs in a module* → call `connect_to_elm` if needed, then `list_projects` → `get_modules` → `get_module_requirements`\n"
                f"- *what's the team doing / who's stuck / status* → call `get_team_actions`\n"
                f"- *resume a paused build* → call `build_project_resume`\n"
                f"- *create tasks / tests for existing reqs* → `/full-lifecycle`\n"
                f"- *find a requirement by ID* → `resolve_requirement_id`\n"
                f"- *check ELM connection / version* → `elm_mcp_health` or `list_capabilities`\n"
                f"- *anything else* → ask ONE more clarifying question, never dump a tool list\n\n"
                f"DO NOT enumerate every tool. The user came here to "
                f"start a task, not browse an inventory. Take them "
                f"straight to the right starting point."
            )),
        )]

    if name == "generate-requirements":
        system_desc = args.get("system_description", "")
        req_type = args.get("requirement_type", "system")
        standards = args.get("standards", "")
        count = args.get("count", "10-15")

        standards_note = f"\n\nApplicable standards: {standards}. Include compliance references in each requirement." if standards else ""

        return [PromptMessage(
            role="user",
            content=TextContent(type="text", text=(
                f"The user wants {req_type} requirements for: {system_desc}\n\n"
                f"Target count: {count}.{standards_note}\n\n"
                f"**INTERVIEW FIRST. DO NOT GENERATE YET.**\n\n"
                f"The system description above is a starting point, "
                f"NOT a complete spec. Run a deep, user-friendly "
                f"interview, ONE QUESTION AT A TIME, before writing "
                f"any 'shall' statements. The user is the domain "
                f"expert; your job is to extract what they know.\n\n"
                f"**Phrase every question like a senior engineer "
                f"talking to a stakeholder who isn't fluent in "
                f"jargon. Use this verbatim shape:**\n\n"
                f"    > **[topic]** — [plain question]\n"
                f"    > Examples: [a], [b], [c]\n"
                f"    > *(Why I'm asking: [what this informs].)*\n"
                f"    > If unsure: [a sane default they can pick].\n\n"
                f"**ASK ONE. WAIT. Then ask the next.** Don't dump all "
                f"12 at once.\n\n"
                f"**The 12 question areas:**\n\n"
                f"  **1. Who uses it — and what's the #1 job they want "
                f"done?** Examples: 'Internal ops staff reconciling "
                f"shipments.' / 'External customers tracking their "
                f"order.' / 'Other services calling our API.' *(Why: "
                f"tells me whether to write user-facing reqs or "
                f"system-to-system reqs.)* If unsure: name the loudest "
                f"user — the one who'd complain first if it broke.\n\n"
                f"  **2. Is this new, a replacement, or an addition?** "
                f"Examples: 'Greenfield — nothing exists today.' / "
                f"'Replaces our 2018 Java monolith.' / 'Adds search "
                f"to the existing product.' *(Why: replacements "
                f"inherit backward-compat reqs; greenfield doesn't.)* "
                f"If unsure: 'augmenting something existing' is most "
                f"common.\n\n"
                f"  **3. Tech stack — language, framework, where it "
                f"runs.** Examples: 'Python 3.11 + FastAPI on AWS "
                f"Lambda.' / 'Go 1.22 + Echo on EKS.' / 'Node 20 + "
                f"Express on bare-metal VMs.' *(Why: performance "
                f"reqs depend on runtime — cold-start latency, memory "
                f"ceilings, package availability.)* If unsure: 'same "
                f"stack as your other services' is the safe default.\n\n"
                f"  **4. How fast does it need to feel — in "
                f"milliseconds?** Examples: 'p95 < 200ms for the "
                f"search endpoint.' / 'Batch under 30 min wall-"
                f"clock.' / 'Page load < 2s on a phone.' *(Why: 'fast' "
                f"isn't testable — without a number, I can't write a "
                f"verifiable AC.)* If unsure: '< 1s for user-facing, "
                f"< 5 min for batch' is a starting line.\n\n"
                f"  **5. How many users / requests at once?** Examples: "
                f"'5 internal users, ~10 RPM.' / '500 concurrent at "
                f"peak, 50 RPS sustained.' / '1M events/day, batched "
                f"hourly.' *(Why: drives scale + concurrency reqs.)* "
                f"If unsure: reference an existing service of similar "
                f"shape — same scale, more, or less?\n\n"
                f"  **6. What other systems does it talk to?** "
                f"Examples: 'Pulls from Stripe, writes to Snowflake.' "
                f"/ 'Reads from Azure Service Bus.' / 'Calls internal "
                f"/auth service.' Protocol per integration (REST / "
                f"gRPC / MQ / DB)? Auth model? *(Why: every "
                f"integration is a requirement and a failure mode.)* "
                f"If unsure: name the systems even without protocol — "
                f"I'll follow up.\n\n"
                f"  **7. What data flows through it, and is any of it "
                f"sensitive?** Examples: 'Order records with names + "
                f"partial card numbers (PCI scope).' / 'Public catalog "
                f"data — no PII.' / 'Health data — HIPAA applies.' "
                f"Retention? Encryption at-rest/in-transit? *(Why: PII "
                f"triggers compliance + security reqs that wouldn't "
                f"otherwise exist.)* If unsure: 'no PII, no PCI, no "
                f"PHI' is the safe default — but say it explicitly.\n\n"
                f"  **8. Security story — what are you defending "
                f"against?** Examples: 'Internal-only behind VPN — "
                f"minimal threat.' / 'Public-facing — assume hostile "
                f"internet, OWASP Top 10.' / 'Payment data — PCI "
                f"controls.' Secrets mgmt? Auth (OAuth / SAML / "
                f"mTLS)? *(Why: 'secure' is meaningless without "
                f"naming the threat.)* If unsure: 'OWASP Top 10 + "
                f"secrets in managed vault' is the modern baseline.\n\n"
                f"  **9. How will you know it's working in prod?** "
                f"Examples: 'Datadog metrics + PagerDuty on "
                f"error-rate > 1%.' / 'JSON logs to Splunk, traces in "
                f"Honeycomb.' / 'We don't have observability — need to "
                f"add it.' *(Why: observability becomes its own set "
                f"of reqs — what metrics, what SLOs, what alerts.)* "
                f"If unsure: 'request rate + error rate + p95 "
                f"latency, alert on error spikes' is the minimum "
                f"trio.\n\n"
                f"  **10. What MUST keep working if something "
                f"breaks?** Examples: 'If DB down, reads serve from "
                f"cache.' / 'If payments API down, accept order + "
                f"retry.' / 'Fail fast — no degraded mode.' *(Why: "
                f"failure-mode reqs are the ones bugs exploit; "
                f"making them explicit catches whole bug classes.)* "
                f"If unsure: 'reads stay up, writes can queue' is a "
                f"common pattern worth considering.\n\n"
                f"  **11. How do you want acceptance criteria "
                f"written?** Examples: 'Given/When/Then "
                f"(Gherkin).' / 'Numbered bullet list of verifiable "
                f"conditions.' / 'Prose paragraphs — test by hand.' "
                f"*(Why: the format flows directly into test cases "
                f"later.)* If unsure: 'Given/When/Then' is cleanest "
                f"for tooling.\n\n"
                f"  **12. What does this project NOT do? "
                f"(Out-of-scope — most-missed.)** Examples: 'No "
                f"mobile yet — web only.' / 'No real-time — batch "
                f"every 5 min is fine.' / 'No admin UI — admin "
                f"happens elsewhere.' *(Why: out-of-scope reqs are "
                f"the ones engineers add anyway and balloon the "
                f"build.)* Push: name **three things** this won't do.\n\n"
                f"**Vague-answer rule — push for measurable:**\n"
                f"  - 'fast'     → 'p95 in ms?'\n"
                f"  - 'secure'   → 'threat model? PII? PCI? GDPR?'\n"
                f"  - 'scalable' → 'concurrent users? RPS?'\n"
                f"  - 'reliable' → 'uptime target? RPO/RTO?'\n"
                f"  - 'simple'   → 'how few clicks / endpoints / "
                f"screens?'\n"
                f"  - 'modern'   → 'which year/version baseline?'\n\n"
                f"**'I don't know' rule:** never skip. Offer 3 "
                f"concrete options + your recommendation, let them "
                f"pick. The picking IS the decision and becomes a "
                f"recorded assumption.\n\n"
                f"**After the interview:**\n\n"
                f"1. Summarize the scope back in ONE paragraph "
                f"reflecting EVERY answer. Wait for confirmation.\n"
                f"2. `get_artifact_types` to learn the project's "
                f"shape vocabulary.\n"
                f"3. Generate {count} requirements following IEEE "
                f"29148 / INCOSE — 'shall' for mandatory, atomic, "
                f"testable, **measurable acceptance criteria drawn "
                f"from the interview answers (NOT hallucinated "
                f"thresholds)**, grouped by functional area.\n"
                f"4. Preview in a clean table — Type | Title | "
                f"Acceptance Criteria.\n"
                f"5. Wait for explicit approval. Edits → re-preview.\n"
                f"6. On approval, `create_requirements` with "
                f"`module_name` set so reqs auto-bind.\n\n"
                f"Better to ask 15 questions and generate accurate "
                f"requirements than ask 3 and hallucinate "
                f"plausible-but-wrong ones."
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
                f"**INTERVIEW BEFORE EACH PHASE. DO NOT STAMP OUT "
                f"ARTIFACTS.** Each phase has its own interview shaped "
                f"like Phase 1: plain question, concrete examples, why "
                f"I'm asking, safe default if stuck.\n\n"
                f"**Question shape — use this at every phase:**\n\n"
                f"    > **[topic]** — [plain question]\n"
                f"    > Examples: [a], [b], [c]\n"
                f"    > *(Why I'm asking: [what this informs].)*\n"
                f"    > If unsure: [a sane default].\n\n"
                f"━━━ PHASE 1 — REQUIREMENTS (DNG) ━━━\n\n"
                f"Ask 12–15 questions ONE AT A TIME. Cover: primary "
                f"user + #1 job, context (new/replace/augment), tech "
                f"stack + deploy target, performance in milliseconds, "
                f"scale (users/RPS), integrations + protocols, data + "
                f"PII handling, regulations, security threat model, "
                f"observability, failure modes, AC style, scope count, "
                f"and **explicit out-of-scope** (most-missed; push "
                f"for three things).\n\n"
                f"Vague-answer rule: 'fast'→p95 in ms; 'secure'→threat "
                f"model; 'scalable'→concurrent users; 'reliable'→"
                f"uptime/RPO/RTO. 'I don't know'→offer 3 options + "
                f"recommendation, have them pick.\n\n"
                f"Generate → preview as table → wait for approval → "
                f"`create_requirements` with `module_name` set so reqs "
                f"auto-bind.\n\n"
                f"━━━ PHASE 2 — TASKS (EWM) ━━━\n\n"
                f"Don't stamp 1 task per req. Ask 8–12 questions ONE "
                f"AT A TIME first, each with examples + why + safe "
                f"default:\n\n"
                f"  1. **Decomposition** — strict 1:1, or split big reqs "
                f"into spike+build+harden, or collapse trivials? "
                f"If unsure: 1:1 unless I flag a req as too big.\n"
                f"  2. **Cross-cutting tasks** — CI/CD, infra-as-code, "
                f"observability, secrets, runbooks, feature flags. "
                f"Read the list; user picks which apply. (Most users "
                f"forget ≥2 of these.)\n"
                f"  3. **Effort estimates** — points / t-shirt / "
                f"hours / we-don't-estimate? Use team's currency.\n"
                f"  4. **Foundation set** — which tasks block "
                f"everything else? schema, scaffolding, auth.\n"
                f"  5. **Spike vs build** — any reqs where the "
                f"approach is unclear? Those get a research task "
                f"FIRST with a time-box.\n"
                f"  6. **Definition of Done** — merged? deployed to "
                f"staging? demo'd? Get the checklist; goes in every "
                f"task body.\n"
                f"  7. **Owner / assignment** — assign now? leave "
                f"unassigned? `resolve_user` to verify if named.\n"
                f"  8. **Risky tasks** — new tech, flaky third-party, "
                f"security-sensitive, unclear AC. Flag with **Risk:** "
                f"line.\n"
                f"  9. **Iteration target** — Backlog or specific "
                f"sprint?\n"
                f"  10. **Team area** — which EWM area owns it?\n"
                f"  11. **Extra links** — design docs, ADRs, Figma, "
                f"external tickets?\n"
                f"  12. **Out-of-scope tasks** — push.\n\n"
                f"Preview as table (title | covers req | est | owner | "
                f"deps | risk | DoD). Wait for approval. Use "
                f"`create_tasks` (BATCH/plural) — ONE call, ONE "
                f"approval click.\n\n"
                f"Task body per task: Objective / Deliverables / "
                f"Dependencies / DoD / Risks. Don't copy the req body "
                f"— it's already linked.\n\n"
                f"━━━ PHASE 3 — TEST CASES (ETM) ━━━\n\n"
                f"Tests catch bad reqs — design them. Ask 8–12 "
                f"questions ONE AT A TIME, each with examples + why + "
                f"safe default:\n\n"
                f"  1. **Test levels** — unit / integration / system / "
                f"acceptance / perf / security? Which go in ETM? "
                f"(Usually system + acceptance.)\n"
                f"  2. **Automation** — manual / automated (pytest / "
                f"JUnit / Cypress / Playwright)? Name the framework.\n"
                f"  3. **Coverage per req** — happy only, or pos + "
                f"neg + boundary (≥3 tests/req typical)?\n"
                f"  4. **Edge cases** — empty / max-length / "
                f"malformed / unicode / concurrent / downstream-down "
                f"/ slow-DB / expired-auth. Walk req list; user picks "
                f"per req.\n"
                f"  5. **Test data** — synthetic / fixture / "
                f"anonymized prod / mocked? PII scrubbing?\n"
                f"  6. **Environment** — local / staging / "
                f"prod-mirror? external services live or mocked? "
                f"feature flags?\n"
                f"  7. **Pass/Fail style** — exact / tolerance / "
                f"checksum / log assertion / p95 ms? Measurable.\n"
                f"  8. **NFR tests** — each performance/scale req "
                f"needs threshold + load profile (steady/ramp/spike/"
                f"soak).\n"
                f"  9. **Security tests** — every threat from Phase 1 "
                f"threat model needs ≥1 negative test.\n"
                f"  10. **GWT mapping** — if reqs use Given/When/Then, "
                f"map directly to test steps?\n"
                f"  11. **Traceability granularity** — 1 test ↔ 1 "
                f"req, or 1 test ↔ many reqs?\n"
                f"  12. **Out-of-scope tests** — push.\n\n"
                f"Vague-answer rule: 'works'→measurable criterion; "
                f"'should fail'→with what error?; 'reasonable'→p95 < "
                f"what ms?; 'normal data'→name 3 representative "
                f"records.\n\n"
                f"Preview as table (title | covers req(s) | "
                f"pos/neg/boundary/perf | env | automated? | pass "
                f"criterion). Wait for approval. Use "
                f"`create_test_cases` (BATCH/plural).\n\n"
                f"Test case body per test: Preconditions / Test Steps "
                f"/ Pass/Fail Criteria / Test Data / Cleanup. Tie "
                f"pass criteria to the AC from the source req.\n\n"
                f"━━━ DISCIPLINE AT EVERY PHASE ━━━\n\n"
                f"- Interview BEFORE generating. Many questions.\n"
                f"- Plain question + concrete examples + why + safe "
                f"default for every question.\n"
                f"- One question at a time. Wait for the answer.\n"
                f"- Follow up on every vague answer.\n"
                f"- Preview in a table before pushing.\n"
                f"- Wait for explicit approval.\n"
                f"- Use BATCH tools (`create_requirements`, "
                f"`create_tasks`, `create_test_cases`) — one approval "
                f"click each, not N.\n"
                f"- Pass Phase 1 requirement URLs verbatim into Phase "
                f"2 (`requirement_url`) and Phase 3 "
                f"(`requirement_url`) so traceability is preserved.\n\n"
                f"Better to ask 30 questions across all three phases "
                f"and ship accurate artifacts than ask 3 and "
                f"hallucinate plausible-but-wrong ones."
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
        content = args.get("content", "")
        dng_proj = args.get("dng_project", "")
        ewm_proj = args.get("ewm_project", "")
        etm_proj = args.get("etm_project", "")
        source_hint = args.get("source_hint", "")

        intro = (
            "The user wants to import a complete work-item graph (epic + "
            "stories + reqs + tests + cross-links) into ELM from EITHER a "
            "PDF path OR pasted text. This is the BROWNFIELD-COMPLETE "
            "path — multi-artifact, multi-tool. The source is typically a "
            "Jira epic export, an Azure DevOps work item, or similar. You "
            "preserve the user's wording wherever possible — you "
            "structure, don't rewrite.\n\n"
        )

        if content:
            preview = content[:400] + ("…" if len(content) > 400 else "")
            input_block = (
                f"## Source: pasted text ({len(content)} chars)\n\n"
                f"The user already pasted the work-item body. Skip "
                f"`extract_pdf` entirely — go straight to parsing.\n\n"
                f"--- PASTED CONTENT (preview, first 400 chars) ---\n"
                f"{preview}\n"
                f"--- END PREVIEW (full text is in your prompt context) ---\n\n"
                f"Parse the FULL pasted text below into the five categories "
                f"described in the next section. Don't truncate to the "
                f"preview.\n\n"
                f"--- FULL PASTED CONTENT ---\n{content}\n"
                f"--- END FULL CONTENT ---\n\n"
            )
        elif pdf_path:
            input_block = (
                f"## Source: PDF at `{pdf_path}`\n\n"
                f"Step 1: call `extract_pdf(file_path=\"{pdf_path}\")`. "
                f"You'll get the full text including title, metadata, "
                f"sections, comments. Don't ask the user — just extract.\n\n"
                f"If `extract_pdf` errors with 'file not found' or similar, "
                f"the user may have given a wrong path. Tell them: *'I "
                f"couldn't read the PDF at that path. Two options: (a) "
                f"send me the right absolute path, or (b) open the PDF in "
                f"Preview/Acrobat, Cmd-A → Cmd-C → paste the text into "
                f"chat — I'll parse it just fine.'*\n\n"
            )
        else:
            input_block = (
                "## Source: not yet provided\n\n"
                "The user hasn't given a PDF path or pasted content. Ask "
                "them once, OFFERING BOTH OPTIONS:\n\n"
                "  *'I can import a work item two ways:*\n"
                "  *1. Tell me the absolute path to the PDF (e.g. "
                "  `~/Downloads/OMS-28894.pdf`) and I'll extract it.*\n"
                "  *2. Open the PDF, copy all the text, paste it here. "
                "  Works for IBM Bob too where PDF attachments aren't "
                "  auto-readable.*\n"
                "  *Which do you prefer?'*\n\n"
                "Wait for their answer. If they paste text, treat it as "
                "the `content` arg path. If they give a path, call "
                "`extract_pdf` with it.\n\n"
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
            "## 🛑 MANDATORY: Ask about scope before push — tasks + tests gate\n\n"
            "Before the approval gate, you MUST ask the user "
            "whether they want the FULL multi-artifact build "
            "(reqs + EWM tasks + ETM test cases all cross-linked) "
            "or just the requirements for now. Verbatim prompt:\n\n"
            "> *\"Drafted N requirements. Before I push to DNG — "
            "do you also want me to:*\n"
            "> *  • Create EWM tasks for each requirement (one "
            "task per req, linked back via implementsRequirement)?*\n"
            "> *  • Create ETM test cases from the acceptance "
            "criteria (linked back via validatesRequirement)?*\n"
            "> *Or just push the requirements for now and leave "
            "tasks/tests for a separate session?\"*\n\n"
            "Wait for an explicit choice (full / reqs-only / "
            "reqs+tasks / reqs+tests). Skip this question and you "
            "rob the user of the scope decision. Common BA "
            "workflow: requirements first, tasks/tests after the "
            "IT architect has designed.\n\n"
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

    # `build-project` prompt removed in v0.5.0. Use /build-new-project
    # (greenfield) or /build-from-existing (brownfield) instead.

    # ── Legacy /build-project prompt removed in v0.5.0 ──
    # Use /build-new-project (greenfield) or /build-from-existing (brownfield).

    elif name == "import-jira":
        issue_key = args.get("issue_key", "").strip()
        dng_proj = args.get("dng_project", "").strip()
        module_name = args.get("module_name", "").strip()
        walk_graph = args.get("walk_graph", "").strip().lower()

        intro = (
            "The user wants to import a LIVE Jira issue into DNG, with "
            "bidirectional links: DNG requirements stamped with a "
            "`Source: JIRA-XXX` reference + a comment posted back to the "
            "Jira issue listing the created DNG URLs.\n\n"
            "**This is Step 3l in BOB.md.**\n\n"
            "**Architecture:** elm-mcp talks to Jira's REST API DIRECTLY "
            "via the native `get_jira_issue` / `search_jira_issues` / "
            "`add_jira_comment` / `add_jira_remote_link` tools (Basic "
            "auth with the user's API token). NO Atlassian MCP server, "
            "NO `mcp-remote` bridge, NO OAuth. Credentials live in .env "
            "as JIRA_BASE_URL / JIRA_EMAIL / JIRA_API_TOKEN. If the user "
            "hasn't set those yet, `get_jira_issue` returns a clear "
            "configuration error — surface it verbatim and tell them to "
            "run `python3 ~/.elm-mcp/setup.py --with-jira`.\n\n"
        )

        if issue_key:
            display_key = issue_key
            if "/browse/" in issue_key:
                try:
                    display_key = issue_key.rstrip("/").split("/browse/")[-1].split("?")[0].split("#")[0]
                except Exception:
                    display_key = issue_key
            input_block = (
                f"## Target issue: `{display_key}`\n\n"
                f"Pass `{issue_key}` verbatim as `issue_key=` to "
                f"`get_jira_issue`. The tool accepts bare keys "
                f"(PROJ-123) and full browse URLs.\n\n"
            )
        else:
            input_block = (
                "## Target issue: not yet provided\n\n"
                "Ask once: *\"Which Jira issue should I pull? Send the "
                "key (e.g. `PROJ-123`) or the full browse URL.\"*\n\n"
            )

        if walk_graph in ("parent", "children", "both"):
            walk_block = f"## Graph walk: `{walk_graph}`\n\n"
            if walk_graph in ("parent", "both"):
                walk_block += (
                    "- Pull parent for context via `get_jira_issue` "
                    "(use `parent.key` from main issue result). Context "
                    "only — don't create separate DNG reqs from it "
                    "unless asked.\n"
                )
            if walk_graph in ("children", "both"):
                walk_block += (
                    "- Pull children via "
                    "`search_jira_issues(jql=\"parent = <key>\")`. "
                    "Preview ALL of them BEFORE creating anything in DNG.\n"
                )
            walk_block += "\n"
        elif walk_graph == "none":
            walk_block = (
                "## Graph walk: NONE — use only the main issue's body.\n\n"
            )
        else:
            walk_block = (
                "## Graph walk: ASK after main pull\n\n"
                "- If issue has children (Epic with stories), ASK before "
                "pulling them.\n"
                "- If issue has a parent (Story under Epic), ASK before "
                "pulling parent.\n"
                "- Default: don't auto-walk.\n\n"
            )

        target_block = "## DNG target\n\n"
        target_block += (
            f"DNG project: `{dng_proj}`.\n" if dng_proj
            else "DNG project: not specified. Use currently-connected "
                 "project or call `connect_to_elm` first.\n"
        )
        target_block += (
            f"Module name: `{module_name}`.\n\n" if module_name
            else "Module name: suggest one based on Jira summary, e.g. "
                 "`JIRA-1234: Tracking Service - System Requirements`.\n\n"
        )

        workflow = (
            "## Workflow (native elm-mcp Jira tools)\n\n"
            "1. **Pull** — `get_jira_issue(issue_key=...)`. Surface "
            "compact summary: key, type, status, summary, assignee, "
            "counts. If config error, stop and surface credential "
            "setup.\n\n"
            "2. **Walk graph** (see above — optional, ask first).\n\n"
            "3. **🛑 MANDATORY DECISION GATE — present the menu and "
            "STOP.** After surfacing the issue summary, do NOT "
            "start parsing or generating anything. Instead, ask "
            "the user EXACTLY this:\n\n"
            "   > *\"Pulled JIRA-XXXX — `<summary>`. What would "
            "you like to do with it in ELM?\"*\n\n"
            "   Then present these options (markdown bullet list, "
            "numbered for easy reference):\n\n"
            "   **1. Break into DNG requirements** (single-tier, "
            "default). Parse into atomic shall-statements + NFRs, "
            "interview gaps, push to a new DNG module with "
            "`Source: JIRA-XXX` stamp + back-link comment on Jira. "
            "Use this for a typical Story / Feature ticket.\n\n"
            "   **2. Tiered decomposition** (Business → Stakeholder "
            "→ System reqs across 3 DNG modules with cross-tier "
            "links). Use this for an Epic or initiative-level "
            "ticket where you want explicit decomposition layers. "
            "Chains into the `/tiered-decomposition` (Step 3g) "
            "playbook with the Jira ticket as the business goal.\n\n"
            "   **3. Multi-artifact build** (EWM work item + DNG "
            "reqs + ETM test cases from ACs, all cross-linked in "
            "one round). Use this for a complete Epic that "
            "bundles reqs, tasks, AND acceptance criteria. "
            "Chains into the `/import-work-item` (Step 3k) "
            "playbook with the Jira content as input.\n\n"
            "   **4. Test cases only** (extract ACs and create "
            "ETM test cases, skip DNG). Use this when the ticket "
            "is primarily verification work — the reqs already "
            "exist in DNG and you just need tests.\n\n"
            "   **5. EWM task only** (create a single EWM work "
            "item linked back to the Jira ticket, no req "
            "decomposition). Use this when the ticket is an "
            "engineering task that doesn't decompose into "
            "requirements.\n\n"
            "   **6. Full agentic build** (run the full "
            "`/build-new-project` flow with the Jira ticket as "
            "the project idea — generates reqs, tasks, tests, "
            "AND code with phase-gated reviews). Use this for a "
            "greenfield project kicked off from a Jira ticket.\n\n"
            "   **7. Project Scaffold first** (run "
            "`/project-scaffold` to capture organizational + "
            "regulatory + ELM structure decisions BEFORE doing "
            "anything else; come back to this menu with full "
            "context). Recommended if this is a NEW project — "
            "the scaffold captures sponsor, compliance regime, "
            "artifact types, link types, lifecycle states "
            "first.\n\n"
            "   **8. Just summarize** (read-only — review the "
            "ticket and stop; no writes to DNG/EWM/ETM or back to "
            "Jira). Use this for a quick check.\n\n"
            "   **9. Walk the graph first** (pull parent epic / "
            "child stories from Jira for more context, then come "
            "back to this menu).\n\n"
            "   **WAIT for an explicit choice (1-9 or a phrase "
            "like 'break it down', 'just summarize', 'full "
            "build').** Do NOT pick a default. Do NOT proceed "
            "without an explicit answer. The user might want "
            "something we haven't listed — accept free-form "
            "answers too and route accordingly.\n\n"
            "4. **Route to the chosen sub-flow.** Once the user "
            "picks, follow these continuations:\n\n"
            "   - **Option 1** → continue with steps 5-11 below "
            "(parse → interview → preview → push → back-link).\n"
            "   - **Option 2** → invoke the `/tiered-"
            "decomposition` prompt (Step 3g) with the Jira "
            "ticket body as the seed business goal.\n"
            "   - **Option 3** → invoke `/import-work-item` "
            "(Step 3k) with `content=<jira_body>`.\n"
            "   - **Option 4** → extract ACs from the ticket, "
            "invoke `create_test_cases` against the user's ETM "
            "project, each test case linked back to the relevant "
            "DNG req (ask which) AND with `Source: JIRA-XXX` in "
            "the description.\n"
            "   - **Option 5** → call `create_task` (EWM) with "
            "the ticket summary as title, `link_workitem_to_"
            "external_url` to back-link to the Jira issue.\n"
            "   - **Option 6** → invoke `/build-new-project` "
            "with `project_idea=<jira_summary>`.\n"
            "   - **Option 7** → invoke `/project-scaffold`, "
            "and after the charter is saved, return here with "
            "the user's choice from this menu.\n"
            "   - **Option 8** → just present a nice summary in "
            "chat. No tool calls. No writes.\n"
            "   - **Option 9** → call `search_jira_issues(jql="
            "'parent = <key>')` for children and/or `get_jira_"
            "issue(<parent_key>)` for the parent, then return "
            "to this menu with the additional context.\n\n"
            "5. **Parse into FIVE buckets** (only for options 1, "
            "2, 3 — when the chosen flow needs DNG-shaped "
            "requirements):\n"
            "   - Functional reqs (atomic 'shall' statements)\n"
            "   - Non-functional reqs (perf, security, retention)\n"
            "   - Acceptance criteria → HOLD for ETM\n"
            "   - Constraints/Risks/Assumptions → ask once, "
            "default skip\n"
            "   - Skipped (Business Goal, DoD, sprint metadata)\n\n"
            "6. **🛑 MANDATORY: Multi-Dimensional Coverage "
            "Interview.** Run the process from BOB.md's "
            "'🎯 Multi-Dimensional Coverage Interview' section "
            "using the 18-dimension **Requirements** list. The "
            "Jira ticket is SEED material — re-elicit the parts "
            "the author assumed context for. Track ✅/🟡/⬜/🚫 in "
            "chat as you go, show progress UI, catch "
            "inconsistencies, surface a live draft preview after "
            "dimension 4 with running lint scores. Stop when all "
            "18 dimensions are ✅ or 🚫. Cap at 35 questions.\n\n"
            "Open with the contract: *\"I'll cover 18 dimensions "
            "of a complete requirements spec for this Jira "
            "ticket. Some will be waived if they don't apply. "
            "I'll show progress as we go; stop me anytime.\"*\n\n"
            "**Jira-specific add-ons** (ask once for the whole "
            "import, in addition to the 18 dimensions):\n\n"
            "   **Per-batch (asked once for the whole import):**\n"
            "   - *\"Who's the engineering owner for these reqs? "
            "(for the Owner attribute.)\"*\n"
            "   - *\"Default Verification Method — Test / "
            "Inspection / Analysis / Demonstration?\"*\n"
            "   - *\"Priority bar — MoSCoW (Must / Should / "
            "Could / Won't)?\"*\n"
            "   - *\"Source document for traceability — Jira "
            "ticket only, or also PSAC / RFP / contract §?\"*\n"
            "   - *\"Quality target — what avg lint score do you "
            "want before we push? BOB recommends 85+; safety-"
            "critical 90+.\"*\n"
            "   - *\"Are these all functional, or split NFRs "
            "into a separate module?\"*\n"
            "   - *\"Lifecycle — Draft → Review → Approved → "
            "Baselined, or custom?\"*\n\n"
            "   **Scope clarifiers per vague bucket:**\n"
            "   - Performance-sounding NFR → EXACT threshold + "
            "unit + measurement conditions ('p95 latency, "
            "nominal load' vs. 'p99 under peak').\n"
            "   - 'shall not' / negative req → what counts as "
            "detection + how it's logged.\n"
            "   - Absolute ('always', 'never', '100%') → "
            "realistic SLA target.\n\n"
            "   **HARD MINIMUM — at least 12 substantive "
            "questions answered before drafting any req.** If "
            "you've asked fewer than 12, KEEP ASKING. "
            "Substantive = \"What's the response-time budget "
            "under peak load?\"; trivial = \"OK to proceed?\".\n\n"
            "   **ONE question at a time. Wait for each answer. "
            "NEVER batch.** If user gets impatient ('just "
            "generate them'), don't cave. Say: *\"I'd be "
            "guessing. 30 seconds of interview saves an hour "
            "of rework when these go into a baseline. Three "
            "more questions then draft.\"*\n\n"
            "7. **Draft requirements** from the interview "
            "answers. Preserve the user's wording where they "
            "answered explicitly; only add shall-syntax "
            "scaffolding. NEVER invent NFRs from thin air.\n\n"
            "8. **Lint the drafts** — `lint_requirements_batch"
            "(items=[{title, text} for each draft])`. Surface "
            "per-req scores in the chat.\n\n"
            "9. **🛑 PER-WEAK-REQ FOLLOW-UP LOOP** — for EVERY "
            "req scoring < 70, ask 2-3 SPECIFIC follow-up "
            "questions about that req's issues before pushing. "
            "Examples:\n\n"
            "   - Weasel word (GtWR R6): *\"REQ-5 says 'user-"
            "friendly'. Measurable as completion time? clicks? "
            "WCAG conformance level? Pick one.\"*\n"
            "   - Missing units (GtWR R23): *\"REQ-7 says "
            "'within 500' — 500 what? ms? business days?\"*\n"
            "   - Compound shall (GtWR R3): *\"REQ-12 has "
            "three obligations joined by 'and'. Split into 3 "
            "separate reqs — confirm?\"*\n"
            "   - Untestable absolute (GtWR R5): *\"REQ-14 "
            "says 'always' — what's the realistic SLA? "
            "99.9%? 99.99%?\"*\n\n"
            "   Keep looping until either (a) every req scores "
            "≥ 70, or (b) the user explicitly tells you to "
            "push anyway (which gets stamped on the module "
            "as `[AI Generated] Note: derived from non-"
            "tightened requirements`).\n\n"
            "10. **Preview** — counts + every item in full + "
            "lint score + Jira source per item.\n\n"
            "11. **Wait for explicit approval.**\n\n"
            "12. **Push to DNG via `create_requirements`** with "
            "`module_name=...` and a `Source:` line prefix on "
            "each requirement's content:\n"
            "   ```\n"
            "   Source: JIRA-1234 — https://yourorg.atlassian.net/browse/JIRA-1234\n"
            "\n"
            "   <the requirement text>\n"
            "   ```\n\n"
            "13. **Post Jira back-link via `add_jira_comment`** "
            "with a markdown body listing the DNG URLs. Tool "
            "converts paragraphs + bullets + links to ADF.\n\n"
            "14. **Optional: `add_jira_remote_link`** with the "
            "DNG module URL for a clean entry in Jira's Links "
            "panel.\n\n"
            "15. **Surface URLs both sides + generate HTML "
            "report** via `generate_trace_report` if there's "
            "enough cross-domain data (reqs + tasks + tests).\n\n"
            "16. **Offer post-push next steps** — EWM tasks "
            "(Step 3d), ETM test cases (Step 3e), baseline, "
            "audit (`/audit-requirements`).\n\n"
        )

        antipatterns = (
            "## Anti-patterns\n\n"
            "- ❌ **SKIPPING THE MENU.** After pulling the issue "
            "you MUST present options 1-9 and wait for the user's "
            "choice. Do NOT assume 'they probably want option 1' "
            "and start parsing. The user might want a tiered "
            "decomp, a multi-artifact build, or just a summary — "
            "ASK FIRST.\n"
            "- ❌ Reach for Atlassian's hosted MCP. Use elm-mcp's "
            "`get_jira_issue` (snake_case), not `getJiraIssue` "
            "(camelCase).\n"
            "- ❌ Skip the interview because the ticket has a "
            "description.\n"
            "- ❌ Forget the Jira back-link.\n"
            "- ❌ Push Jira ACs as DNG reqs (ACs → ETM).\n"
            "- ❌ Auto-walk child stories — ask first.\n"
            "- ❌ Re-word user's Jira content — preserve phrasing.\n"
            "- ❌ Call `create_module` then `create_requirements` "
            "separately — use `module_name=` for auto-bind.\n"
        )

        return [PromptMessage(
            role="user",
            content=TextContent(type="text", text=(
                intro + input_block + walk_block + target_block
                + workflow + antipatterns
            )),
        )]

    elif name == "audit-requirements":
        proj = args.get("project", "").strip()
        mod = args.get("module", "").strip()

        intro = (
            "🛑 **HARD RULES — READ BOTH BEFORE YOU DO ANYTHING:**\n\n"
            "**(1) DO NOT emit any diagrams inline in chat — only the HTML report path** — the "
            "output of `generate_audit_report` (verbatim). DO NOT "
            "add 'supplementary' bar charts, risk-distribution "
            "pies, or other improvised Mermaid. ONE quality pie. "
            "Done.\n\n"
            "**(2) NEVER emit Mermaid, ASCII art, or improvised diagrams inline in chat.** If you type "
            "`pie`, `pie title`, `flowchart`, `graph`, or any "
            "Mermaid keyword directly into your response, STOP and "
            "call `generate_audit_report`. Hand-rolling loses the "
            "copy block, the RQA pointer footer, and consistent "
            "styling.\n\n"
            "The user wants a quality audit of a DNG module. Run "
            "the deterministic INCOSE GtWR + IEEE 29148 lint on "
            "every requirement, plus status-awareness checks. The "
            "audit is read-only — never write back to DNG from "
            "this flow.\n\n"
            "**This is the deterministic floor.** For semantic "
            "scoring, rewrite suggestions, and ambiguity detection "
            "beyond pattern matching, point the user to the "
            "**Requirements Quality Assistant** agent in IBM ELM "
            "AI Hub at the end of your response.\n\n"
        )

        if proj and mod:
            target = (
                f"## Target\n\n"
                f"Project: `{proj}`\nModule: `{mod}`\n\n"
                f"Call `audit_module(project_identifier=\"{proj}\", "
                f"module_identifier=\"{mod}\")` and surface the "
                f"result.\n\n"
            )
        elif proj:
            target = (
                f"## Target\n\n"
                f"Project: `{proj}`. Module not specified — call "
                f"`get_modules(project_identifier=\"{proj}\")`, "
                f"present the list, ask the user which module to "
                f"audit, then call `audit_module(...)`.\n\n"
            )
        else:
            target = (
                "## Target\n\n"
                "Neither project nor module specified. If a DNG "
                "client is connected and `_projects_cache` has "
                "entries, ask the user which project + module to "
                "audit (don't dump the full list — ask by name). "
                "If not connected, instruct the user to call "
                "`connect_to_elm` first.\n\n"
            )

        steps = (
            "## Workflow\n\n"
            "1. **Resolve target** — see above.\n"
            "2. **Run `audit_module(project_identifier, "
            "module_identifier)`** — returns markdown with module "
            "quality summary, lowest-scoring reqs, most-violated "
            "rules, and a status block (Approved % and owner gaps).\n"
            "3. **Surface the audit verbatim** to the user. Don't "
            "paraphrase — the rule citations are valuable.\n"
            "4. **🛑 MANDATORY: call `generate_audit_report` with the "
            "audit's bucket counts** to emit a quality-distribution "
            "pie chart. Pass `audit_summary={good: <n>, fair: <n>, "
            "weak: <n>, poor: <n>}` extracted from the audit's "
            "Distribution line. Do NOT hand-roll a pie chart "
            "yourself — the tool emits the right Mermaid syntax + "
            "a one-click Mermaid Live edit link. Surface the "
            "output verbatim.\n"
            "5. **End with the Requirements Quality Assistant "
            "pointer.** Phrase it exactly: *\"For AI-powered "
            "rewrite suggestions and semantic scoring on these "
            "specific requirements, open the Requirements Quality "
            "Assistant agent in IBM ELM AI Hub. The pattern lint "
            "above is the deterministic floor; RQA is the AI "
            "ceiling.\"*\n"
            "6. **Offer concrete next steps** based on findings:\n"
            "   - If many reqs scored < 65 (`weak`/`poor`): suggest "
            "running `coach_requirement(text=...)` per req, OR "
            "open them in RQA in batch.\n"
            "   - If <80% Approved: suggest a review cycle before "
            "creating any downstream tasks/tests.\n"
            "   - If many missing owners: suggest using "
            "`update_requirement_attributes` to assign owners.\n\n"
        )

        antipatterns = (
            "## Anti-patterns\n\n"
            "- ❌ **Hand-rolling Mermaid output.** ALWAYS call "
            "`generate_audit_report` for the quality pie chart. "
            "You lose the Mermaid Live edit link and consistent "
            "styling if you hand-roll.\n"
            "- ❌ Don't push fixes during an audit. Audits are "
            "read-only; surface issues and let the user decide.\n"
            "- ❌ Don't claim the lint is comprehensive. Pattern "
            "matching misses semantic issues. Always end with the "
            "RQA pointer.\n"
            "- ❌ Don't paraphrase the rule citations away. "
            "'INCOSE GtWR R6' is more useful to an engineer than "
            "'vague language'.\n"
        )

        return [PromptMessage(
            role="user",
            content=TextContent(type="text",
                                 text=intro + target + steps + antipatterns),
        )]

    elif name == "trace-gaps":
        proj = args.get("project", "").strip()
        mod = args.get("module", "").strip()
        ewm = args.get("ewm_project", "").strip()
        etm = args.get("etm_project", "").strip()
        parts = []
        parts.append(
            "🛑 **HARD RULES — READ ALL THREE BEFORE YOU DO ANYTHING:**\n\n"
            "**(1) DO NOT emit any diagrams inline in chat — only the HTML report path.** That "
            "block is the output of `generate_trace_report` (verbatim). "
            "DO NOT add 'supplementary' pie charts, gap-analysis "
            "flowcharts, risk-distribution charts, category "
            "breakdowns, or any other Mermaid block. If you think "
            "'a pie chart would also be nice' or 'let me visualize "
            "the risk levels too' — STOP. ONE diagram. If the user "
            "later explicitly asks for a quality pie chart, call "
            "`generate_audit_report` for THAT (never hand-roll).\n\n"
            "**(2) NEVER emit Mermaid, ASCII art, or improvised diagrams inline in chat.** If you type "
            "`flowchart`, `graph TB`, `graph LR`, `pie`, `gantt`, "
            "`sequenceDiagram`, or any Mermaid diagram-type keyword "
            "directly in your response, STOP — call the right tool. "
            "Hand-rolled output loses click-to-ELM nav, correct "
            "color palette, ASCII safety for engineering Unicode, "
            "friendly OSLC key replacement, AND the copy block for "
            "mermaid.live. The tools exist exactly to spare you "
            "from re-deriving this.\n\n"
            "**(3) Do NOT invent data not in the tool output.** "
            "'Risk levels' (CRITICAL/HIGH/MEDIUM/LOW), 'categories' "
            "(Basic Aircraft Functionality, Target Tracking, "
            "Communication), or any other taxonomy NOT present in "
            "the trace data — that's improvisation, not analysis. "
            "Stick to what the tools return: req status, "
            "task/test presence, ownership, lint scores. Don't "
            "graft on classification schemes the user didn't ask "
            "for and the data doesn't support.\n\n"
            "The user wants a cross-domain TRACEABILITY GAP report. "
            "Walk DNG -> EWM -> ETM and surface orphans on both sides. "
            "Director-level read: 'where are we missing implementing "
            "tasks / validating tests?' Use existing tools.\n\n"
        )
        parts.append("## Target\n\n")
        if proj and mod:
            parts.append(f"DNG project: `{proj}`. Module: `{mod}`.\n")
        else:
            parts.append("DNG project/module not fully specified — ask "
                         "the user; offer `connect_to_elm` then "
                         "`list_projects` if needed.\n")
        if ewm:
            parts.append(f"EWM project: `{ewm}`.\n")
        else:
            parts.append("EWM project not specified — ask which one to "
                         "scan for tasks. If user says 'skip', skip "
                         "task-side checks.\n")
        if etm:
            parts.append(f"ETM project: `{etm}`.\n\n")
        else:
            parts.append("ETM project not specified — ask which one to "
                         "scan for tests. If user says 'skip', skip "
                         "test-side checks.\n\n")
        parts.append(
            "## Workflow\n\n"
            "1. **Pull module reqs** — call `get_module_requirements` "
            "with the project + module identifiers. Save the (key, "
            "title, url) tuples.\n\n"
            "2. **For each req, check EWM for implementing tasks** — "
            "call `query_work_items` against the EWM project, filtering "
            "where `calm:implementsRequirement` equals the req's URL. "
            "If results are empty, the req has NO implementing task. "
            "Flag it.\n\n"
            "3. **For each req, check ETM for validating test cases** "
            "— call `list_test_cases` for the ETM project, then check "
            "each test case for a link to the req's URL. ETM reverse-"
            "link queries are fuzzy in OSLC; if you can't determine "
            "cleanly, say so honestly and surface 'unknown' for that "
            "side rather than guessing.\n\n"
            "4. **Surface counts in a markdown table:**\n"
            "   - Total reqs in module: N\n"
            "   - Reqs WITH implementing task: X (X/N = %)\n"
            "   - Reqs WITHOUT implementing task: N - X\n"
            "   - Reqs WITH validating test case: Y (Y/N = %)\n"
            "   - Reqs WITHOUT validating test case: N - Y\n\n"
            "5. **Top offenders (10 each)** — list the 10 worst as "
            "markdown links: `[REQ-007: <title>](<url>) — no task / "
            "no test`.\n\n"
            "6. **Orphan tasks/tests (if user asked)** — query EWM "
            "for tasks where `implementsRequirement` is empty; same "
            "for ETM tests with no req link. List as markdown.\n\n"
            "7. **🛑 MANDATORY: call `generate_trace_report` with the "
            "assembled trace data.** Do NOT hand-roll a Mermaid "
            "diagram yourself. The tool emits the correct Mermaid "
            "block (with click directives that open each artifact "
            "in DNG / EWM / ETM, color-coded by gap state) PLUS a "
            "one-click Mermaid Live editor link the user can click "
            "to open the diagram in their browser for export. Pass "
            "the assembled list as `items=[{req_key, req_title, "
            "req_url, req_status, req_owner, tasks: [...], tests: "
            "[...]}, ...]` and a `title` like "
            "'<Project> - <Module>'. Surface the tool's output "
            "verbatim — it includes the inline ```mermaid``` block, "
            "the Mermaid Live link, AND the ELM AI Hub pointer "
            "footer. Don't paraphrase any of it.\n\n"
            "8. **Action list** — for each gap, suggest the "
            "concrete next step: `/create-tasks` for a missing "
            "task, `/create-test-cases` for a missing test.\n\n"
            "## Anti-patterns\n\n"
            "- ❌ **Hand-rolling Mermaid syntax.** ALWAYS call "
            "`generate_trace_report`. It produces clickable nodes "
            "(opens artifacts in DNG/EWM/ETM), the right color "
            "palette, the Mermaid Live edit link, and the RQA "
            "pointer. If you hand-roll, you lose all of that.\n"
            "- ❌ Don't claim 100% accuracy on the orphan-test "
            "side — ETM reverse-link queries are fuzzy. Be honest "
            "about methodology limitations.\n"
            "- ❌ Don't auto-create tasks/tests to 'fix' the gaps. "
            "Read-only report.\n"
            "- ❌ Don't paraphrase the URL list — engineers need "
            "clickable links.\n"
        )
        return [PromptMessage(
            role="user",
            content=TextContent(type="text", text="".join(parts)),
        )]

    elif name == "init-do-178c":
        proj = args.get("dng_project", "").strip()
        dal = args.get("dal", "").strip().upper()
        sys_name = args.get("system_name", "").strip() or "<System>"
        parts = []
        parts.append(
            "The user wants to initialize a DO-178C compliant ELM "
            "project. DO-178C is THE software certification standard "
            "for airborne systems (FAA, EASA). This prompt walks "
            "through artifact-type / attribute / link-type / "
            "lifecycle decisions and creates what's creatable via "
            "API. **Most schema work happens in DNG admin (Project "
            "→ Manage Project Properties → Types) — those are "
            "MANUAL steps; surface them with the exact values.**\n\n"
            "**Sales position at the end:** the scaffold is the "
            "starting structure; IBM ELM AI Hub keeps the "
            "certification evidence alive.\n\n"
        )
        if dal in ("A", "B", "C", "D", "E"):
            parts.append(f"## DAL: **{dal}**\n\n")
        else:
            parts.append(
                "## DAL not specified — ASK first\n\n"
                "DO-178C Design Assurance Levels (most → least "
                "rigorous):\n\n"
                "- **A** — catastrophic failure prevention. MC/DC "
                "structural coverage. Independence required.\n"
                "- **B** — hazardous. Decision coverage. "
                "Independence required.\n"
                "- **C** — major. Statement coverage. Trace to "
                "code.\n"
                "- **D** — minor. LLR not strictly required.\n"
                "- **E** — no safety effect. DO-178C objectives "
                "do not apply.\n\n"
                "DAL drives EVERY downstream choice. Don't proceed "
                "until the user answers.\n\n"
            )
        parts.append(
            "## DO-178C ELM Scaffold\n\n"
            "### 1. Artifact Types (DNG admin)\n\n"
            "Have the user create in DNG admin → Manage Project "
            "Properties → Types:\n\n"
            "- **System Requirement** — what the system shall do "
            "at system level (PSAC scope).\n"
            "- **High-Level Requirement (HLR)** — software-level "
            "behavior derived from System Reqs.\n"
            "- **Low-Level Requirement (LLR)** — design-level reqs, "
            "~one per software function.\n"
            "- **Software Verification Requirement** — what to "
            "test + how (Inspection / Analysis / Review / Test per "
            "DO-178C §6.3).\n"
            "- **Software Design Description** — design artifact.\n\n"
            "### 2. Attribute Schema (DNG admin)\n\n"
            "Attach to System Req / HLR / LLR types:\n\n"
            "- **DAL** (enum A-E) — per-req DAL.\n"
            "- **Verification Method** (enum: Inspection / "
            "Analysis / Review / Test) — IART per §6.3.\n"
            "- **Verification Evidence Location** (string) — link "
            "to test report / analysis doc / review record.\n"
            "- **Source Document** (string) — PSAC §, SDP §, "
            "customer contract §.\n"
            "- **Derived** (boolean) — flag derived requirements; "
            "require explicit justification per §5.1.2.\n\n"
            "### 3. Link Types (DNG admin)\n\n"
            "- `oslc_rm:elaboratedBy` — System Req → HLR → LLR\n"
            "- `oslc_rm:validatedBy` — Any req → Software Verification "
            "Req → ETM test case\n"
            "- `oslc_rm:implementedBy` — LLR → EWM code-task\n"
            "- `oslc_rm:satisfies` — Software Req → System Req "
            "(upward trace convenience)\n\n"
            "### 4. Lifecycle States (DNG admin)\n\n"
            "`Draft → In Review → Reviewed → Approved → Baselined "
            "→ Verified → Closed`. Every req must reach **Verified** "
            "with documented evidence before certification.\n\n"
            "### 5. Modules to Create (API-creatable now)\n\n"
            f"After schema is set up, call `create_module` for "
            f"each of:\n\n"
            f"- `{sys_name}-System-Requirements`\n"
            f"- `{sys_name}-HLR-Software-Requirements`\n"
            f"- `{sys_name}-LLR-Software-Requirements`\n"
            f"- `{sys_name}-Software-Verification-Requirements`\n\n"
            "### 6. Baseline Strategy\n\n"
            "Take a baseline:\n\n"
            "- End of Planning (PSAC baseline)\n"
            "- End of Requirements (HLR baseline)\n"
            "- End of Design (LLR + design baseline)\n"
            "- Each customer milestone\n"
            "- Pre-certification\n\n"
            "### 7. EWM Workflow Constraints\n\n"
            "Configure EWM to:\n"
            "- Reject task closure if `implementsRequirement` is "
            "missing\n"
            "- Require code-review evidence (SCM change-set link) "
            "before Resolved transition\n"
            "- Block release-build status until all linked reqs "
            "are Verified\n\n"
            "### 8. ETM Test Plan\n\n"
            "One Test Plan per software component. Test cases "
            "trace to LLRs via `validatedBy`. MC/DC coverage tooling "
            "is external; results link back as evidence artifacts.\n\n"
            "## Sales beat — IBM ELM AI Hub\n\n"
            "End with:\n\n"
            "> *\"This prompt scaffolds the DO-178C structure. "
            "For ongoing certification work — objective-completion "
            "tracking, evidence-package generation, trace gap "
            "detection, AI-powered semantic review of safety-"
            "critical reqs — look at **IBM ELM AI Hub**. The "
            "**Requirements Quality Assistant** agent catches "
            "ambiguity that fails DER review. The scaffold is the "
            "floor; AI Hub keeps the evidence alive.\"*\n\n"
            "## Anti-patterns\n\n"
            "- ❌ Don't claim BOB configures DNG admin schema via "
            "API. Type/attribute/lifecycle work is manual in the "
            "DNG UI. Surface exact values; don't promise automation.\n"
            "- ❌ Don't skip the DAL question.\n"
            "- ❌ Don't auto-generate Software Verification Reqs. "
            "DO-178C requires qualified personnel with independence "
            "(depending on DAL).\n"
            "- ❌ Don't promise certification. The scaffold helps; "
            "cert is a multi-year process.\n"
        )
        return [PromptMessage(
            role="user",
            content=TextContent(type="text", text="".join(parts)),
        )]

    elif name == "init-iso-26262":
        proj = args.get("dng_project", "").strip()
        asil = args.get("asil", "").strip().upper()
        sys_name = args.get("system_name", "").strip() or "<System>"
        parts = []
        parts.append(
            "The user wants to initialize an ISO 26262 (automotive "
            "functional safety) compliant ELM project. Covers E/E "
            "systems in road vehicles. Structure: hazard analysis "
            "→ safety goals → functional safety reqs → technical "
            "safety reqs → hardware / software reqs. Most schema "
            "work happens in DNG admin.\n\n"
        )
        if asil in ("A", "B", "C", "D"):
            parts.append(f"## ASIL: **{asil}**\n\n")
        else:
            parts.append(
                "## ASIL not specified — ASK first\n\n"
                "- **D** — highest risk; electronic power steering, "
                "ADAS. Maximum rigor.\n"
                "- **C** — engine / transmission control.\n"
                "- **B** — body electronics with safety relevance.\n"
                "- **A** — lower-criticality functions.\n\n"
                "ASIL drives downstream rigor: independence of "
                "review (DIA for ASIL ≥ B), coverage targets, "
                "decomposition rules (ISO 26262-9). Don't proceed "
                "until ASIL is known.\n\n"
            )
        parts.append(
            "## ISO 26262 ELM Scaffold\n\n"
            "### 1. Artifact Types (DNG admin)\n\n"
            "- **Hazard** — identified hazard with severity / "
            "exposure / controllability (S/E/C) → ASIL\n"
            "- **Safety Goal** — top-level safety req from hazard "
            "analysis\n"
            "- **Functional Safety Requirement (FSR)** — system-"
            "level behavior to achieve safety goals\n"
            "- **Technical Safety Requirement (TSR)** — hardware / "
            "software allocation\n"
            "- **Software Safety Requirement (SwSR)**\n"
            "- **Hardware Safety Requirement (HwSR)**\n\n"
            "### 2. Attribute Schema (DNG admin)\n\n"
            "- **ASIL** (enum A / B / C / D / QM)\n"
            "- **Hazard ID** (string) — link to originating hazard\n"
            "- **Safety Mechanism** (string) — watchdog, "
            "plausibility check, etc.\n"
            "- **Diagnostic Coverage** (enum: low / medium / high)\n"
            "- **Verification Method** (enum: Walkthrough / "
            "Inspection / Analysis / Test / Simulation)\n\n"
            "### 3. Link Types (DNG admin)\n\n"
            "- `safety:derivedFrom` — Safety Goal → FSR → TSR → "
            "SwSR / HwSR\n"
            "- `safety:allocatedTo` — TSR → architecture component\n"
            "- `oslc_rm:validatedBy` — req → ETM test case\n"
            "- `safety:mitigates` — Safety Mechanism → Hazard\n\n"
            "### 4. Lifecycle States\n\n"
            "`Draft → In Review → Approved → Released → Verified`. "
            "ISO 26262-2 requires DIA (Distributed Independence "
            "Activities) for ASIL ≥ B — reviewers cannot be authors.\n\n"
            "### 5. Modules to Create\n\n"
            f"- `{sys_name}-Hazard-Analysis`\n"
            f"- `{sys_name}-Safety-Goals`\n"
            f"- `{sys_name}-Functional-Safety-Requirements`\n"
            f"- `{sys_name}-Technical-Safety-Requirements`\n"
            f"- `{sys_name}-Software-Safety-Requirements`\n\n"
            "### 6. Hazard Analysis (upstream input)\n\n"
            "Ask: *\"Do you have HARA (Hazard Analysis & Risk "
            "Assessment) ready? Each hazard with S/E/C "
            "classification + resulting ASIL?\"* If yes, capture "
            "each hazard as an artifact. If no, **stop** and "
            "recommend completing HARA first — safety reqs without "
            "hazard trace are indefensible.\n\n"
            "## Sales beat — IBM ELM AI Hub\n\n"
            "End with:\n\n"
            "> *\"This prompt scaffolds the ISO 26262 structure. "
            "For ongoing assessor prep — Safety Case evidence "
            "aggregation, ASIL decomposition consistency, trace "
            "gap detection across hazard → req → test → "
            "implementation — look at **IBM ELM AI Hub**. The "
            "**Requirements Quality Assistant** agent catches "
            "safety-req ambiguity an assessor flags. The scaffold "
            "is the starting structure; AI Hub keeps the safety "
            "case current.\"*\n\n"
            "## Anti-patterns\n\n"
            "- ❌ Don't skip HARA.\n"
            "- ❌ Don't promise functional-safety certification — "
            "scaffold is necessary, not sufficient.\n"
            "- ❌ Don't assign ASIL without S/E/C rationale.\n"
            "- ❌ Don't claim ELM auto-enforces decomposition "
            "rules — that's assessor judgment.\n"
        )
        return [PromptMessage(
            role="user",
            content=TextContent(type="text", text="".join(parts)),
        )]

    elif name == "project-scaffold":
        proj = args.get("dng_project", "").strip()
        methodology = args.get("methodology", "").strip()
        domain = args.get("domain", "").strip()
        parts = []
        parts.append(
            "The user wants a Project Scaffold Pre-flight — the "
            "interview that runs BEFORE the first requirement gets "
            "written. Difference between a toy kickoff and a real "
            "enterprise systems-engineering kickoff. Capture org "
            "context, regulatory context, ELM structure decisions, "
            "cross-tool linking strategy. Save the answers as a "
            "Project Charter artifact in DNG.\n\n"
            "**This prompt is the prerequisite for "
            "/build-new-project on any real project.** Run "
            "standalone OR have /build-new-project chain into it.\n\n"
        )
        if methodology:
            parts.append(f"## Methodology: **{methodology}**\n\n"
                         "Skipping the methodology question; jump "
                         "to Layer 1.\n\n")
        if domain:
            parts.append(f"## Domain: **{domain}**\n\n"
                         "Use as context throughout the interview.\n\n")
        parts.append(
            "## Layer 1 — Organizational Context\n\n"
            "Ask ONE QUESTION AT A TIME (don't dump):\n\n"
            "1. *\"Which business unit / program is this under?\"*\n"
            "2. *\"Project sponsor? (Person + title)\"*\n"
            "3. *\"Product owner / requirements owner?\"*\n"
            "4. *\"Lead architect / technical lead?\"*\n"
            "5. *\"QA / test lead?\"*\n"
            "6. *\"Compliance / safety / security officer "
            "involved?\"*\n"
            "7. *\"Target customer — internal? External? Both?\"*\n"
            "8. *\"Delivery milestone — what date / which "
            "release?\"*\n"
            "9. *\"What's the existing world we're improving on?\"*\n\n"
            "Capture each answer verbatim.\n\n"
            "## Layer 2 — Regulatory + Quality Context\n\n"
            "1. *\"Which compliance regime applies?\"* Options: "
            "HIPAA / PCI-DSS / SOC 2 / FedRAMP / DO-178C (DAL?) / "
            "ISO 26262 (ASIL?) / IEC 62304 (Class A/B/C?) / ITAR "
            "/ GDPR / None.\n"
            "2. *\"Evidence package required at delivery?\"*\n"
            "3. *\"Signing authority?\"*\n"
            "4. *\"Quality target — avg lint score?\"* BOB "
            "recommends 85+; safety-critical 90+.\n"
            "5. *\"Test coverage target?\"* (% reqs validated)\n"
            "6. *\"Approval target before downstream work?\"* (% "
            "reqs that must reach Approved)\n\n"
            "**If a regulated regime is named, point the user at "
            "/init-do-178c, /init-iso-26262, /init-iec-62304 to "
            "scaffold the right artifact types / attributes / "
            "links / lifecycle.**\n\n"
            "## Layer 3 — ELM Project Structure Decisions\n\n"
            "1. *\"DNG folder hierarchy and naming convention?\"* "
            "Default: `/Requirements/<Tier>/<Module>`.\n"
            "2. *\"Standard artifact types or custom?\"*\n"
            "3. *\"Required attributes per req?\"* Always: Title, "
            "Description, Status, Owner. Often: Priority, "
            "Verification Method, Source Document. Compliance: "
            "DAL / ASIL / Software Safety Class.\n"
            "4. *\"Link types?\"* Defaults: `elaboratedBy`, "
            "`validatedBy`, `implementedBy`. Compliance adds: "
            "`derivedFrom`, `mitigates`, `satisfies`.\n"
            "5. *\"Lifecycle states?\"* Defaults: `Draft → "
            "Reviewed → Approved → Baselined → Verified → "
            "Closed`. Agile lighter: `Draft → Ready → Done`.\n"
            "6. *\"Baseline cadence?\"* (per milestone / per "
            "release / weekly / never)\n"
            "7. *\"DNG CM enabled?\"* — call `elm_mcp_health` "
            "to check. If not, warn module binding + baselines + "
            "streams won't work programmatically.\n"
            "8. *\"Stream strategy?\"* (single mainline vs. "
            "parallel feature streams)\n\n"
            "## Layer 4 — Cross-Tool Linking Strategy\n\n"
            "1. *\"Jira / EWM for issue tracking?\"* If Jira, "
            "confirm JIRA_* env vars. Plan: each issue → DNG req "
            "via /import-jira; back-link via add_jira_comment.\n"
            "2. *\"GitHub / GitLab / IBM RTC for code?\"* Plan: "
            "PR/commit → EWM task via SCM link.\n"
            "3. *\"Test management — ETM or external (Xray, "
            "TestRail, jUnit)?\"* If ETM, plan: verification req → "
            "ETM test case → execution result.\n"
            "4. *\"Comms channel?\"* Teams / Slack URL — captured "
            "for future notifications.\n"
            "5. *\"Document storage for evidence?\"* DNG "
            "attachments / SharePoint / S3 — affects Verification "
            "Evidence Location.\n\n"
            "## Capture as a Project Charter artifact\n\n"
            "After all four layers, summarize the answers in a "
            "structured Markdown block:\n\n"
            "```markdown\n"
            "# Project Charter — <name>\n"
            "\n"
            "## Organization\n"
            "- BU / Program: ...\n"
            "- Sponsor: ...\n"
            "- Owners: ...\n"
            "\n"
            "## Regulatory\n"
            "- Regime: ...\n"
            "- Evidence: ...\n"
            "- Quality target: ...\n"
            "\n"
            "## ELM Structure\n"
            "- Folders: ...\n"
            "- Artifact types: ...\n"
            "- Link types: ...\n"
            "- Lifecycle: ...\n"
            "- Baseline cadence: ...\n"
            "\n"
            "## Cross-Tool Strategy\n"
            "- Jira: ...\n"
            "- SCM: ...\n"
            "- ETM: ...\n"
            "- Comms: ...\n"
            "```\n\n"
            "Wait for user approval of the charter. On approval, "
            "call `create_requirements` with the charter as the "
            "body, in a module named `<system>-Project-Charter`. "
            "Use artifact type `Information` or `Project Plan` "
            "(whatever the project's types allow). **The charter "
            "is the source of truth for context that all "
            "subsequent flows reference.**\n\n"
            "## After scaffold — offer next steps\n\n"
            "- *\"Write the first requirements now? I'll run "
            "/build-new-project with the charter as context.\"*\n"
            "- *\"Compliance regime is [DO-178C / ISO 26262 / IEC "
            "62304] — run /init-[regime] to scaffold artifact "
            "types / attributes / links / lifecycle?\"*\n"
            "- *\"Want to import existing reqs from a Jira epic "
            "or PDF? /import-jira or /import-work-item.\"*\n\n"
            "## Anti-patterns\n\n"
            "- ❌ Don't ask all 30 questions at once. ONE at a "
            "time. Conversational.\n"
            "- ❌ Don't skip layers. Each depends on the previous.\n"
            "- ❌ Don't push the charter before user approval.\n"
            "- ❌ Don't claim the charter is comprehensive — "
            "it's a starting point; projects evolve.\n"
            "- ❌ Don't run the full flow when the user just "
            "wants a quick MVP. If layers 1-2 answer 'small "
            "internal MVP, no compliance', skip ahead to "
            "/build-new-project.\n"
        )
        return [PromptMessage(
            role="user",
            content=TextContent(type="text", text="".join(parts)),
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


# Artifact-specific write gates. Same INTERVIEW → PREVIEW → CONFIRM
# discipline as `_WRITE_GATE`, but each one names the BOB.md section
# whose 8-15 question interview template MUST be run first. Hallucinated
# requirements / tasks / tests are the #1 failure mode — these gates push
# the model into the per-artifact checklist every time it considers the
# tool, not just when the user happens to enter an orchestrated flow.

_REQ_GATE = (
    "🛑 REQUIREMENT WRITE GATE — Bob's #1 rule. "
    "DO NOT CALL THIS TOOL until you have, in order: "
    "(1) RUN THE MULTI-DIMENSIONAL COVERAGE INTERVIEW from BOB.md's "
    "'🎯 Multi-Dimensional Coverage Interview' section — use the "
    "**18-dimension Requirements list**. Track ✅/🟡/⬜/🚫 in chat. "
    "Show progress UI after every answer. Stop when all 18 are ✅ or "
    "🚫. Catch inconsistencies as they surface. Detect gaps "
    "proactively (after every 4 answers, check what's missing for "
    "the domain). Show a live draft preview with running lint scores "
    "once 4+ dimensions are ✅. THIS APPLIES REGARDLESS OF HOW YOU "
    "GOT HERE — through /import-jira, /build-new-project, "
    "/generate-requirements, OR a natural-language request. The "
    "interview is not optional. (Legacy reference: this used to "
    "point at Step 3b — the 18-dim framework supersedes it.) "
    "(2) PREVIEWED — Markdown table with Type | Title | Lint Score | "
    "Acceptance Criteria | Link target — BEFORE this tool fires. "
    "Re-preview after any edit. "
    "(3) CONFIRMED — explicit 'yes / ship it / go ahead / push them'. "
    "The user saying 'I need some requirements' is a REQUEST, not "
    "approval. If you call this tool without all three steps and the "
    "user later notices reqs they didn't approve, that's a failure. "
    "Hallucinated NFRs ship and break things. — "
)

_WORKITEM_GATE = (
    "🛑 WORK ITEM WRITE GATE — Bob's #1 rule. "
    "DO NOT CALL THIS TOOL until you have, in order: "
    "(1) RUN THE MULTI-DIMENSIONAL COVERAGE INTERVIEW from BOB.md's "
    "'🎯 Multi-Dimensional Coverage Interview' section — use the "
    "**12-dimension Tasks/Work Items list**. For defects, use the "
    "**8-dimension Defects list** instead. Track ✅/🟡/⬜/🚫. ONE "
    "question at a time. Show progress UI. Catch inconsistencies. "
    "Detect gaps proactively. THIS APPLIES REGARDLESS OF HOW YOU "
    "GOT HERE. (Legacy reference: this used to point at Step 3d — "
    "the new dimension lists supersede it.) "
    "(2) PREVIEWED — table with Title | Covers Req | Est | Owner | "
    "Deps | Risk | DoD — BEFORE this tool fires. Re-preview after "
    "any edit. "
    "(3) CONFIRMED — explicit approval. "
    "ALWAYS pass `requirement_url` when the work item implements a "
    "DNG requirement — without it, traceability breaks. — "
)

_TESTCASE_GATE = (
    "🛑 TEST CASE WRITE GATE — Bob's #1 rule. "
    "DO NOT CALL THIS TOOL until you have, in order: "
    "(1) RUN THE MULTI-DIMENSIONAL COVERAGE INTERVIEW from BOB.md's "
    "'🎯 Multi-Dimensional Coverage Interview' section — use the "
    "**10-dimension Test Cases list** (validates which req, "
    "category, preconditions, steps, expected results, test data, "
    "environment, pass/fail criteria, tear-down, verification "
    "method). Track ✅/🟡/⬜/🚫. ONE question at a time. Show "
    "progress UI. Follow up on every vague answer ('works' → what's "
    "the measurable criterion?; 'should fail' → with what error "
    "code?; 'reasonable' → p95 < what ms?). THIS APPLIES REGARDLESS "
    "OF HOW YOU GOT HERE. (Legacy reference: this used to point at "
    "Step 3e — the 10-dim framework supersedes it.) "
    "(2) PREVIEWED — table with Title | Covers Req(s) | Pos/Neg/"
    "Boundary/Perf | Env | Automated? | Pass criterion — BEFORE "
    "this tool fires. Re-preview after any edit. "
    "(3) CONFIRMED — explicit approval. "
    "ALWAYS pass `requirement_url` when the test validates a DNG "
    "requirement. Bad tests catch nothing. — "
)


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        # `build_project` legacy tool removed in v0.5.0 — use
        # build_new_project (greenfield) or build_from_existing
        # (brownfield) instead.
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
                "in run X?'*. Mostly read-only. The optional "
                "`clear_phase_2_bind_failed` flag is the recovery path "
                "when a Phase 2 bind failure has been resolved — it "
                "clears the lock so `build_project_next` will advance "
                "from Phase 2 to Phase 3 again."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "run_id": {"type": "string", "description": "Run id (optional). If omitted, lists all active runs."},
                    "clear_phase_2_bind_failed": {
                        "type": "boolean",
                        "description": "Set true after manually resolving a Phase 2 bind failure (e.g. user ran add_to_module successfully or bound reqs in DNG UI). Clears the gate that blocks Phase 3 advance. Verify the reqs are actually in the module before clearing."
                    }
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
            name="wrap_up_session",
            description=(
                "End the current BOB Team Actions session and flush a "
                "final entry to the BOB Team Actions module. Call this "
                "when the user signals they're done for now: *'wrap up'*, "
                "*'I'm done'*, *'good for today'*, *'pausing for "
                "review'*, etc. The final entry captures: any unflushed "
                "activity since the last auto-log, plus the user's "
                "verbatim wrap-up notes if they gave any. After wrap-up, "
                "the session is marked completed/handed-off — subsequent "
                "activity in the same process starts a fresh session."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "notes": {
                        "type": "string",
                        "description": "Free-text notes from the user about where they're stopping, what's pending, who's picking up. Optional. Surfaced verbatim in the final entry."
                    },
                    "status": {
                        "type": "string",
                        "description": "Final status of the session: 'Completed', 'Hand-off', 'Stuck', 'Blocked', 'Paused'. Default 'Completed'."
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="get_team_actions",
            description=(
                "Read recent entries from the BOB Team Actions module — "
                "what everyone on the team has been doing across the "
                "project. Use this when the user asks 'what's the team "
                "doing?', 'what did Sarah work on yesterday?', 'who's "
                "stuck?'. Filters by recency (default last 7d), by user, "
                "by status. Read-only."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "DNG project name or number. Optional — if omitted, uses the connected project."
                    },
                    "since": {
                        "type": "string",
                        "description": "Time window: '24h', '7d', '30d'. Default '7d'."
                    },
                    "who": {
                        "type": "string",
                        "description": "Filter to a specific user. Optional."
                    },
                    "status": {
                        "type": "string",
                        "description": "Filter by status: 'In Progress', 'Completed', 'Stuck', etc. Optional."
                    }
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
        # `save_requirements` removed in v0.5.0 — local-disk export is
        # better handled by your AI host's own file-write tools. Use
        # get_module_requirements + paste/copy if you need text out.
        Tool(
            name="export_module_to_xlsx",
            description=(
                "Export DNG artifacts + their attributes to a polished .xlsx "
                "workbook. Use this when the user asks for a 'spreadsheet', "
                "'Excel', 'xlsx', 'dump to Excel', 'export module', or wants "
                "to share requirements with non-ELM stakeholders. RUN THE "
                "INTERACTIVE INTERVIEW FIRST (see BOB.md 'Exporting Artifacts "
                "to Excel'): ask the user which module(s) and which attribute "
                "columns to include before calling. Defaults to one sheet per "
                "module + every attribute that appears on any requirement. "
                "Writes to ~/.elm-mcp/exports/ and returns the file path; the "
                "user opens it with `open '<path>'` or a double-click. "
                "Read-only against ELM (no DNG writes)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_identifier": {
                        "type": "string",
                        "description": "DNG project number or name."
                    },
                    "module_identifiers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional list of module numbers or names "
                            "(from get_modules). If omitted, exports every "
                            "module in the project. Each entry follows the "
                            "same resolution rules as get_module_requirements "
                            "— ordinal or case-insensitive name."
                        )
                    },
                    "columns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional list of attribute column names to include "
                            "beyond ID/Title/Type/URL (those four are always "
                            "added). Use get_attribute_definitions to discover "
                            "valid names. If omitted, every attribute that "
                            "appears on any requirement is included."
                        )
                    },
                    "combined_sheet": {
                        "type": "boolean",
                        "description": (
                            "If true, all requirements land on a single sheet "
                            "with a Module column. If false (default), one "
                            "sheet per module."
                        )
                    }
                },
                "required": ["project_identifier"]
            }
        ),
        Tool(
            name="create_module",
            description=(_REQ_GATE +
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
            description=(_REQ_GATE +
                "🎯 **THIS IS THE TOOL FOR REQUIREMENTS — NOT YOUR "
                "HOST'S WRITE TOOL.** If the user asks for "
                "requirements, a requirements document, an SRS, a "
                "Jira-ticket import, an epic decomposition, or "
                "ANYTHING resembling requirements work, call THIS "
                "tool. Do NOT write to a local `.md` file using "
                "Write/create_file/edit_file — that's the wrong tool. "
                "Requirements live in DNG so they have URLs, link "
                "into modules, get traced to tasks/tests, and survive "
                "baselines. A local `requirements_document.md` is "
                "garbage in a week. Push to DNG via this tool. "
                "Always.\\n\\n"
                "Create requirements in a DOORS Next project AND bind "
                "them to a module so they appear in DNG's module/"
                "document view. STRONGLY PREFER providing "
                "module_name — module_name is what makes requirements "
                "visible as a navigable document; folder-only "
                "requirements (no module_name) end up as orphan "
                "artifacts most users can't find. MUST call "
                "get_artifact_types first to get valid type names for "
                "this project. Returns created requirement URLs "
                "needed by create_task and create_test_case."
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
            description=(_REQ_GATE +
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
            description=(_WORKITEM_GATE +
                "📋 Interview anchor: ≥6 of the Step 3d question areas answered + preview table shown + explicit approval received, BEFORE this tool fires. — "
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
            name="create_tasks",
            description=(_WORKITEM_GATE +
                "📋 Interview anchor: ≥6 of the Step 3d question areas answered + preview table shown + explicit approval received, BEFORE this tool fires. The batch nature is NOT a shortcut around the interview — it's a shortcut around clicking N approvals after one interview. — "
                "BATCH version of create_task — creates N EWM tasks in "
                "ONE tool call (one user-approval click instead of N). "
                "Use this in build_project Phase 3, /full-lifecycle "
                "Phase 2, or any time you're creating multiple tasks "
                "at once. Each task in the list takes the same args as "
                "create_task (title, description, requirement_url). "
                "Returns the full list of created URLs plus aggregate "
                "stats. Loops internally; same per-task error handling. "
                "ALWAYS pass requirement_url on each item when the task "
                "implements a DNG requirement."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ewm_project": {
                        "type": "string",
                        "description": "EWM project number or name. Applies to every task in the batch."
                    },
                    "tasks": {
                        "type": "array",
                        "description": "List of tasks to create. Each item is {title, description, requirement_url}.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "description": {"type": "string"},
                                "requirement_url": {
                                    "type": "string",
                                    "description": "STRONGLY RECOMMENDED. Full URL of the DNG requirement this task implements. Without it the task is unlinked."
                                }
                            },
                            "required": ["title"]
                        }
                    }
                },
                "required": ["ewm_project", "tasks"]
            }
        ),
        Tool(
            name="create_test_case",
            description=(_TESTCASE_GATE +
                "📋 Interview anchor: ≥6 of the Step 3e question areas answered + preview table shown + explicit approval received, BEFORE this tool fires. — "
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
            name="create_test_cases",
            description=(_TESTCASE_GATE +
                "📋 Interview anchor: ≥6 of the Step 3e question areas answered + preview table shown + explicit approval received, BEFORE this tool fires. The batch nature is NOT a shortcut around the interview — it's a shortcut around clicking N approvals after one interview. — "
                "BATCH version of create_test_case — creates N ETM "
                "test cases in ONE tool call (one user-approval click "
                "instead of N). Use this in build_project Phase 4, "
                "/full-lifecycle Phase 3, or any time you're creating "
                "multiple test cases at once. Each item takes the same "
                "args as create_test_case (title, description, "
                "requirement_url). Returns the full list of created "
                "URLs plus aggregate stats. Loops internally; same "
                "per-test error handling. ALWAYS pass requirement_url "
                "on each item when the test validates a DNG requirement."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "etm_project": {
                        "type": "string",
                        "description": "ETM project number or name. Applies to every test case in the batch."
                    },
                    "test_cases": {
                        "type": "array",
                        "description": "List of test cases to create. Each item is {title, description, requirement_url}.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "description": {"type": "string"},
                                "requirement_url": {
                                    "type": "string",
                                    "description": "STRONGLY RECOMMENDED. Full URL of the DNG requirement this test validates."
                                }
                            },
                            "required": ["title"]
                        }
                    }
                },
                "required": ["etm_project", "test_cases"]
            }
        ),
        Tool(
            name="create_test_script",
            description=(_TESTCASE_GATE +
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
            description=(_TESTCASE_GATE +
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
            name="revert_elm_mcp",
            description=(
                "Roll back the local ELM MCP install to any prior "
                "released version via git tag checkout. Use when the "
                "user says 'revert to v0.12.7', 'roll back to v0.10.0', "
                "'go back to the previous version', or 'undo the last "
                "update'. Without arguments: lists every available "
                "version tag so the user can pick. With a version "
                "argument: checks out that tag (detached HEAD — fine "
                "for running the server). The user must restart their "
                "AI host for the revert to take effect. To return to "
                "the latest version afterward, call `update_elm_mcp` "
                "which detects detached HEAD and re-checks out main."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "version": {
                        "type": "string",
                        "description": "Target version tag (e.g. '0.12.7', 'v0.12.7', 'v0.10.0'). Optional — call without args to list available versions."
                    }
                },
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
            description=(_REQ_GATE +
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
            description=(_WORKITEM_GATE +
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
            description=(_WORKITEM_GATE +
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
            name="resolve_requirement_id",
            description=(
                "Look up a DNG requirement by its short ID (e.g. '123' or "
                "'REQ-123' or 'NFR-7') and return the full URL plus title. "
                "Use this when the user references a requirement by its "
                "human-readable ID and you need the URL for a subsequent "
                "tool call. Strips optional letter prefixes (REQ-, NFR-, "
                "etc.) and tries the numeric portion. Read-only."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_identifier": {
                        "type": "string",
                        "description": "DNG project number or name"
                    },
                    "requirement_id": {
                        "type": "string",
                        "description": "Short ID — '123', 'REQ-123', 'NFR-7', etc."
                    }
                },
                "required": ["project_identifier", "requirement_id"]
            }
        ),
        Tool(
            name="resolve_user",
            description=(
                "Resolve a user identifier (URI, username, or display "
                "name) to a structured record. Bidirectional: pass "
                "either form. Useful when a tool returns a contributor "
                "URI like '.../users/abc123' and you want to surface a "
                "human name, OR when the user mentions a name and you "
                "need the URI for assigning ownership. Read-only."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "identifier": {
                        "type": "string",
                        "description": "User URI (https://.../users/...) OR display name OR username"
                    }
                },
                "required": ["identifier"]
            }
        ),
        Tool(
            name="list_test_cases",
            description=(
                "List test cases in an ETM project. Optional `where` is "
                "an OSLC where clause (e.g. dcterms:title=\"Login flow\", "
                "or oslc:status=\"passed\"). Use this to inventory the "
                "test suite, find existing tests for a feature, etc. "
                "Read-only."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "etm_project": {"type": "string", "description": "ETM project name or number"},
                    "where": {"type": "string", "description": "Optional OSLC where clause"},
                    "max_results": {"type": "integer", "description": "Max items (default 50)"}
                },
                "required": ["etm_project"]
            }
        ),
        Tool(
            name="list_test_plans",
            description=(
                "List test plans in an ETM project. Test plans hold "
                "test strategy / scope, typically referencing many test "
                "cases. Read-only."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "etm_project": {"type": "string", "description": "ETM project name or number"},
                    "where": {"type": "string", "description": "Optional OSLC where clause"},
                    "max_results": {"type": "integer", "description": "Max items (default 50)"}
                },
                "required": ["etm_project"]
            }
        ),
        Tool(
            name="list_test_execution_records",
            description=(
                "List test execution records (TERs) in an ETM project. "
                "A TER is an instance of running a test case in a "
                "particular release/iteration; test results attach to "
                "TERs. Read-only."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "etm_project": {"type": "string", "description": "ETM project name or number"},
                    "where": {"type": "string", "description": "Optional OSLC where clause"},
                    "max_results": {"type": "integer", "description": "Max items (default 50)"}
                },
                "required": ["etm_project"]
            }
        ),
        Tool(
            name="create_test_plan",
            description=(_TESTCASE_GATE +
                "Create a Test Plan in ETM. Use for organizing test "
                "execution at the release / sprint / feature level. "
                "Test plans typically reference many test cases."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "etm_project": {"type": "string", "description": "ETM project name or number"},
                    "title": {"type": "string", "description": "Test plan title"},
                    "description": {"type": "string", "description": "Strategy / scope text"}
                },
                "required": ["etm_project", "title"]
            }
        ),
        Tool(
            name="create_test_execution_record",
            description=(_TESTCASE_GATE +
                "Create a Test Execution Record (TER) in ETM. A TER is "
                "a runnable instance of a test case for a specific "
                "release/iteration. Test results then attach to the TER. "
                "Pair with create_test_result to actually record pass/fail."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "etm_project": {"type": "string", "description": "ETM project name or number"},
                    "title": {"type": "string", "description": "TER title"},
                    "test_case_url": {"type": "string", "description": "Full URL of the test case this TER runs"},
                    "description": {"type": "string", "description": "Optional description"}
                },
                "required": ["etm_project", "title", "test_case_url"]
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
        # ── Jira (direct REST, API-token auth) ─────────────────
        #
        # These tools talk to Atlassian Jira Cloud directly via the
        # REST API using the user's email + API token (set in .env
        # as JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN). They power
        # the /import-jira workflow without depending on Atlassian's
        # hosted MCP server (which uses OAuth and doesn't complete
        # auth reliably in IBM Bob's embedded webview).
        Tool(
            name="get_jira_issue",
            description=(
                "Fetch a single Jira issue by key (e.g. 'PROJ-123') or by "
                "the full browse URL. Returns key, url, summary, "
                "description (flattened from ADF to markdown), status, "
                "type, priority, assignee, reporter, parent, subtasks, "
                "labels, last 5 comments, and counts. Entry point for "
                "/import-jira. Read-only. Requires JIRA_BASE_URL, "
                "JIRA_EMAIL, JIRA_API_TOKEN in .env."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "issue_key": {
                        "type": "string",
                        "description": "Jira issue key (e.g. 'PROJ-123') OR a full browse URL. Both accepted."
                    }
                },
                "required": ["issue_key"]
            }
        ),
        Tool(
            name="search_jira_issues",
            description=(
                "JQL search across Jira. Returns up to `max_results` "
                "slim summaries (key, url, summary, status, type, "
                "priority, assignee, updated). Useful for walking an "
                "epic's children ('parent = EPIC-123'). Read-only."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "jql": {"type": "string", "description": "Jira Query Language."},
                    "max_results": {"type": "integer", "description": "1-100. Default 25.", "default": 25}
                },
                "required": ["jql"]
            }
        ),
        Tool(
            name="add_jira_comment",
            description=(
                "Post a comment on a Jira issue. Body accepts a "
                "markdown-ish string: paragraphs, '- ' bullet lists, "
                "'1. ' numbered lists, and [label](url) links are "
                "converted to Atlassian Document Format. WRITES to Jira."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "issue_key": {"type": "string", "description": "Jira issue key or browse URL."},
                    "body": {"type": "string", "description": "Comment body in markdown-ish form."}
                },
                "required": ["issue_key", "body"]
            }
        ),
        Tool(
            name="add_jira_remote_link",
            description=(
                "Add a structured remote link on a Jira issue — renders "
                "in Jira's 'Links' panel. Best for one-URL-with-a-title "
                "cross-references. WRITES to Jira."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "issue_key": {"type": "string", "description": "Jira issue key or browse URL."},
                    "url": {"type": "string", "description": "Target URL (e.g. DNG module URL)."},
                    "title": {"type": "string", "description": "Short title shown in Jira's Links panel."},
                    "summary": {"type": "string", "description": "Optional longer description."}
                },
                "required": ["issue_key", "url", "title"]
            }
        ),
        Tool(
            name="jira_health",
            description=(
                "Diagnose Jira REST connection. Checks credentials "
                "(JIRA_BASE_URL / JIRA_EMAIL / JIRA_API_TOKEN), calls "
                "/rest/api/3/myself, returns the authenticated profile. "
                "Read-only."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        # ── Requirements Quality (deterministic lint + audit) ─
        #
        # These tools do PATTERN-BASED checks against INCOSE GtWR
        # and IEEE 29148 rules. They catch syntactic smells (weasel
        # words, weak modals, compound shalls, missing units).
        # For semantic scoring, rewrite suggestions, and ambiguity
        # detection, the user should be directed to the
        # Requirements Quality Assistant agent in IBM ELM AI Hub.
        Tool(
            name="lint_requirement_text",
            description=(
                "Run deterministic quality lint against a single "
                "requirement text. Checks INCOSE Guide to Writing "
                "Requirements (GtWR) and IEEE 29148 patterns: "
                "weasel words, weak modals, compound shalls, "
                "implementation leakage, untestable absolutes, "
                "numbers missing units. Returns a 0-100 score, "
                "findings list, and positive signals. Pure pattern "
                "matching; no AI. For semantic scoring direct the "
                "user to the Requirements Quality Assistant agent "
                "in IBM ELM AI Hub."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The requirement text to lint."
                    }
                },
                "required": ["text"]
            }
        ),
        Tool(
            name="lint_requirements_batch",
            description=(
                "Lint a batch of draft requirements at once. Each "
                "item should be {title, text, url?}. Returns a list "
                "of per-item results plus a module-level summary. "
                "Use this in /import-jira and /import-requirements "
                "previews BEFORE pushing to DNG to surface quality "
                "issues for user review."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "Array of {title, text, url?} objects.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "text": {"type": "string"},
                                "url": {"type": "string"}
                            },
                            "required": ["text"]
                        }
                    }
                },
                "required": ["items"]
            }
        ),
        Tool(
            name="audit_module",
            description=(
                "Audit a DNG module's requirements for quality and "
                "status. Pulls every requirement from the named "
                "module, runs the deterministic lint against each, "
                "and adds status-awareness checks: how many are "
                "Approved vs Draft, how many lack owners or "
                "verification methods. Returns a module health "
                "report with the lowest-scoring reqs surfaced and "
                "most-violated rules. Recommend the user open the "
                "Requirements Quality Assistant agent in IBM ELM AI "
                "Hub for semantic scoring beyond what pattern "
                "matching catches. Read-only."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_identifier": {
                        "type": "string",
                        "description": "DNG project name or number."
                    },
                    "module_identifier": {
                        "type": "string",
                        "description": "Module title, ID, or URL."
                    }
                },
                "required": ["project_identifier", "module_identifier"]
            }
        ),
        Tool(
            name="coach_requirement",
            description=(
                "Coach a single draft requirement: returns the "
                "deterministic lint findings plus a prompt to open "
                "the Requirements Quality Assistant agent in IBM "
                "ELM AI Hub for AI-powered rewrite suggestions. Use "
                "when a user asks 'how can I improve this requirement?' "
                "or when reviewing a single problematic req from an "
                "audit."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The requirement text to coach."
                    },
                    "context": {
                        "type": "string",
                        "description": "Optional context (project domain, the parent capability, etc.)."
                    }
                },
                "required": ["text"]
            }
        ),
        Tool(
            name="generate_trace_report",
            description=(
                "ALWAYS USE THIS for trace / gap visualizations — "
                "do not hand-roll diagrams or generate inline "
                "diagrams in the chat. Writes a self-contained "
                "polished HTML report (Inter typography, "
                "interactive Cytoscape trace graph, Chart.js "
                "coverage pie, gap detail tables) to "
                "~/.elm-mcp/reports/. Returns the file path. The "
                "user double-clicks the file to open in any "
                "browser — every node in the graph is clickable "
                "and opens the corresponding DNG / EWM / ETM "
                "artifact in a new tab. ~1.5 MB self-contained, "
                "air-gap safe, looks identical every time. "
                "Use this whenever the user asks for a trace "
                "diagram, gap visualization, or after /trace-gaps "
                "assembles per-req trace data."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "Per-req trace data. Each item: req_key, req_title, req_url, req_status, req_owner, tasks (array of {key, title, url, status}), tests (array of {key, title, url, status}).",
                        "items": {"type": "object"}
                    },
                    "project": {"type": "string", "description": "DNG project name (for the report header)."},
                    "module": {"type": "string", "description": "DNG module name (for the report header)."},
                },
                "required": ["items"]
            }
        ),
        Tool(
            name="generate_audit_report",
            description=(
                "ALWAYS USE THIS for module quality / audit "
                "visualizations. Writes a self-contained HTML "
                "audit report to ~/.elm-mcp/reports/: stat cards, "
                "quality distribution doughnut chart, lowest-"
                "scoring requirements table (each clickable to "
                "DNG), most-violated INCOSE/IEEE rules table, "
                "pointer to Requirements Quality Assistant in "
                "ELM AI Hub. Returns the file path. Same modern "
                "styling, air-gap safe, identical every time."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "audit": {
                        "type": "object",
                        "description": "Audit summary. Expected keys: good, fair, weak, poor (bucket counts), total, avg_score, approved_pct, worst (list of {title, url, score, bucket}), rule_counts (dict of rule -> count). Extract from audit_module output.",
                    },
                    "project": {"type": "string", "description": "DNG project name."},
                    "module": {"type": "string", "description": "DNG module name."},
                },
                "required": ["audit"]
            }
        ),
        # ── EWM: defect creation ───────────────────────────────
        Tool(
            name="create_defect",
            description=(_WORKITEM_GATE +
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

# Tools whose runs are MILESTONE-WORTHY for team-actions auto-log.
# Pure reads (list_*, get_*, list_capabilities, elm_mcp_health, etc.) are
# skipped — they're navigation noise, not state changes. Search/query
# tools that take a real filter ARE captured because they signal
# intentional research, not casual browsing.
_TEAM_LOG_TOOLS_WRITE = {
    "create_module", "create_requirements", "update_requirement",
    "update_requirement_attributes", "create_baseline", "add_to_module",
    "create_folder", "create_task", "create_tasks", "create_defect",
    "update_work_item", "transition_work_item",
    "create_test_case", "create_test_cases", "create_test_script",
    "create_test_result", "create_link", "link_workitem_to_external_url",
    "publish_build_state_to_dng", "generate_chart",
    "create_test_plan", "create_test_execution_record",
    # Jira writes — cross-system back-link events worth logging.
    "add_jira_comment", "add_jira_remote_link",
}
_TEAM_LOG_TOOLS_PHASE = {"build_project", "build_new_project",
                         "build_from_existing", "build_project_next"}
_TEAM_LOG_TOOLS_RESEARCH = {"search_requirements", "query_work_items"}
_TEAM_LOG_TOOLS_SESSION = {"connect_to_elm", "wrap_up_session"}
# Quality / review tools — show up in "what has the team done" so a
# director can see who ran a module audit, when, and what came back.
# lint_requirement_text / coach_requirement / lint_requirements_batch
# are intentionally NOT here — they fire many times per coaching
# session and would drown out the signal.
_TEAM_LOG_TOOLS_QUALITY = {"audit_module"}

_TEAM_LOG_TOOLS_ALL = (
    _TEAM_LOG_TOOLS_WRITE | _TEAM_LOG_TOOLS_PHASE
    | _TEAM_LOG_TOOLS_RESEARCH | _TEAM_LOG_TOOLS_SESSION
    | _TEAM_LOG_TOOLS_QUALITY
)


def _summarize_tool_call(name: str, arguments: Any,
                         result_text: str) -> str:
    """Produce a one-line summary of a tool invocation suitable for the
    team-actions activity log. Look for known-error markers in the
    response text so we can flag stuck-state."""
    err_marker = ("error" in result_text.lower()[:200]
                  or "🚦 GATE LOCKED" in result_text
                  or "403" in result_text or "404" in result_text)
    args = arguments or {}
    # Pick a reasonable per-tool label
    if name == "connect_to_elm":
        label = f"connected to {args.get('url', '')}"
    elif name in ("build_new_project", "build_from_existing", "build_project"):
        label = f"started build flow ({name}): \"{args.get('project_idea', '')[:60]}\""
    elif name == "build_project_next":
        label = f"phase advance: phase {args.get('current_phase', '?')} → {int(args.get('current_phase', 0)) + 1 if isinstance(args.get('current_phase'), int) else '?'}"
    elif name == "create_module":
        label = f"created module \"{args.get('title', '?')}\""
    elif name == "create_requirements":
        reqs = args.get("requirements") or []
        label = f"created {len(reqs)} requirements"
        m = args.get("module_name") or ""
        if m:
            label += f" in module \"{m}\""
    elif name == "create_task":
        label = f"created task \"{args.get('title', '?')}\""
    elif name == "create_defect":
        label = f"created defect \"{args.get('title', '?')}\""
    elif name == "create_test_case":
        label = f"created test case \"{args.get('title', '?')}\""
    elif name == "create_test_result":
        label = f"recorded test result: {args.get('status', '?')}"
    elif name == "transition_work_item":
        label = f"transitioned work item to \"{args.get('target_state', '?')}\""
    elif name == "update_requirement":
        label = "updated requirement"
    elif name == "create_link":
        label = "created cross-tool link"
    elif name == "link_workitem_to_external_url":
        label = f"linked work item to {args.get('external_url', '')}"
    elif name == "add_jira_comment":
        label = f"posted Jira comment on {args.get('issue_key', '')}"
    elif name == "add_jira_remote_link":
        label = f"added Jira remote link on {args.get('issue_key', '')} → {args.get('title', '')}"
    elif name == "audit_module":
        label = (f"audited module quality: "
                 f"{args.get('module_identifier', '')} "
                 f"(project {args.get('project_identifier', '')})")
    elif name == "publish_build_state_to_dng":
        label = "published build state to DNG"
    elif name == "wrap_up_session":
        label = "wrapped up session"
    elif name in _TEAM_LOG_TOOLS_RESEARCH:
        where = args.get("where") or args.get("query") or ""
        label = f"searched ({name}): {where[:80]}"
    else:
        label = f"called {name}"
    if err_marker:
        label = "❌ " + label + " — error"
    return label


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Outer wrapper: dispatches to the real handler logic (now in
    `_dispatch_tool`), then auto-logs the call into BOB Team Actions
    if it's a milestone-worthy event AND the user has team-actions
    enabled."""
    result = await _dispatch_tool(name, arguments)

    # Auto-log into BOB Team Actions (best-effort, never raises)
    try:
        if (_TEAM_ACTIONS_ENABLED and _client is not None
                and name in _TEAM_LOG_TOOLS_ALL):
            user = getattr(_client, "username", "") or ""
            # Resolve the project URL we should attach this activity to.
            # Use the active build run's DNG URL if there is one;
            # otherwise the most recent connected project.
            project_url = ""
            for r in _RUNS.values():
                if r.get("current_phase", 0) < 9:
                    project_url = (r.get("project_urls") or {}).get("dng", "")
                    if project_url:
                        break
            if not project_url:
                # Fallback: use the first DNG project as the project_url
                # for team-action logging (not perfect; project-specific
                # logging would need explicit context from the user).
                if _projects_cache:
                    project_url = _projects_cache[0].get("services_url", "") \
                        or _projects_cache[0].get("url", "")
            if user and project_url:
                # Combine result-text from all return TextContents for
                # error detection
                result_text = ""
                for tc in result:
                    if hasattr(tc, "text"):
                        result_text += tc.text + "\n"
                summary = _summarize_tool_call(name, arguments, result_text)
                _record_team_activity(
                    kind=name,
                    summary=summary,
                    user=user,
                    project_url=project_url,
                )
                _maybe_flush_team_log()
    except Exception as e:
        sys.stderr.write(f"[elm-mcp] team-actions hook failed: {e}\n")

    return result


async def _dispatch_tool(name: str, arguments: Any) -> list[TextContent]:
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
            # Word lists balance two failure modes:
            #   (a) too STRICT → user types natural approvals ("continue",
            #       "correct, go") and the gate rejects them. Was the v0.1.13
            #       overcorrection — fixed in v0.5.3 by re-adding common
            #       affirmatives.
            #   (b) too LOOSE → user asks a question containing approval-
            #       shaped tokens and the gate auto-advances ("can I
            #       continue showing me the table?"). Handled by the
            #       rejection-phrase check below — phrases like "don't
            #       continue" and "wait" win over any approval token.
            # Result: bare common affirmatives are allowed as approval; any
            # rejection phrase or question-shape (handled separately) wins.
            approval_words = {
                # Direct affirmatives
                "yes", "yeah", "yep", "yup", "ya", "yah",
                "ok", "okay", "k", "lgtm",
                "approved", "approve", "approves",
                # Action verbs that read as approval in build-flow context
                "continue", "proceed", "ship", "ships",
                "go",  # Single "go" — still requires non-rejection context
                # Confirmations of a summary
                "correct", "right", "exactly", "yep", "yes",
                "confirmed", "confirm",
                # Vibes
                "looks", "perfect", "great", "awesome", "alright",
                "absolutely", "definitely", "sure", "totally",
            }
            approval_phrases = {
                # Multi-word affirmatives
                "go ahead", "push it", "push them", "ship it", "build it",
                "looks good", "looks great", "let's go", "lets go",
                "do it", "make it so", "go for it",
                # Natural conversational approvals
                "sounds good", "sounds great", "yes please",
                "all good", "good to go", "good with it",
                "i agree", "agreed", "approved that",
                "go for it", "ship them",
                # Confirming a summary
                "that's right", "thats right", "that's correct",
                "thats correct", "correct - continue", "correct continue",
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
                # Question-shape guards — if the user is asking rather
                # than approving, treat as non-approval. The strict
                # markers below catch obvious questions; ambiguous
                # cases ("right?") still pass through approval check
                # and are caught by sentence shape downstream.
                "what is", "what's", "whats",
                "show me", "tell me", "explain",
                "can i", "should i", "do i", "do i need",
                "before we", "before you",
                "why is", "why are", "why do",
            }
            signal_lower = user_signal.lower()
            signal_tokens = set(t.strip(".,!?;:") for t in signal_lower.split())

            # Bare question-mark guard: if the message looks like a
            # question (ends in '?' OR the only "approval" word is
            # at the start of a clause that's clearly interrogative),
            # treat it as not-approval. Belt-and-braces with the
            # rejection phrases above.
            ends_in_question = signal_lower.rstrip().endswith("?")

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
            # Question-shaped messages also count as non-approval — user
            # is asking, not approving.
            rejection_phrase_hit = any(rp in signal_lower for rp in rejection_phrases)
            rejection_token_hit = bool(signal_tokens & rejection_words)
            approval_phrase_hit = any(ap in signal_lower for ap in approval_phrases)
            approval_token_hit = bool(signal_tokens & approval_words)

            # Rejection wins if there's a rejection phrase, OR a rejection
            # token without any approval signal at all, OR the message is
            # purely a question (ends in '?' with no approval phrase).
            is_pure_question = ends_in_question and not approval_phrase_hit
            if (rejection_phrase_hit
                    or (rejection_token_hit and not (approval_phrase_hit or approval_token_hit))
                    or is_pure_question):
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

            # ── HARD GATE: if Phase 2 had a bind failure, refuse to
            # advance to Phase 3. Bob has been observed barreling past
            # bind warnings as if they were footnotes; this gate
            # guarantees the build flow halts until the reqs are
            # actually in a module.
            if (run is not None
                    and current_phase == 2
                    and run.get("phase_2_bind_failed")):
                bind_err = run.get("last_bind_failure", "(unknown)")
                return [TextContent(type="text", text=(
                    "🛑 PHASE GATE LOCKED — Phase 2 had a module-bind "
                    "failure that hasn't been resolved.\n\n"
                    "Phase 2 created the requirements but FAILED to "
                    "bind them to a module. The error was:\n\n"
                    f"```\n{bind_err}\n```\n\n"
                    "Advancing to Phase 3 (creating EWM tasks linked to "
                    "these requirements) would silently break the rest "
                    "of the flow:\n"
                    "- Phase 5 user-review depends on the user opening "
                    "the module in DNG\n"
                    "- Phase 6 drift detection compares against module "
                    "contents\n"
                    "- Without binding, the reqs are invisible from the "
                    "module view\n\n"
                    "**You MUST resolve the bind first.** Three options:\n"
                    "1. Retry programmatically: call `add_to_module("
                    "module_url, [requirement_urls])` with the URLs from "
                    "the run state (`build_project_status(run_id="
                    f"\"{run['run_id']}\")`).\n"
                    "2. If `add_to_module` errors with config-management "
                    "or PHASE_GATE issues, the project doesn't have DNG "
                    "configuration management enabled. Tell the user to "
                    "either enable it (DNG admin task), or open the "
                    "module in DNG and drag the reqs in manually.\n"
                    "3. Once the bind is resolved (you confirm via "
                    "`get_module_requirements` showing the reqs in the "
                    "module), call `build_project_status(run_id=..., "
                    "clear_phase_2_bind_failed=true)` to clear the gate "
                    "and re-attempt this advance.\n\n"
                    "**Do not paraphrase this away. Do not advance. "
                    "Tell the user explicitly that Phase 2 isn't done.**"
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
                1: ("PHASE 1 — PROJECT INTAKE INTERVIEW (DEEP, USER-FRIENDLY)",
                    "Ask 12–18 questions ONE AT A TIME. Wait for each "
                    "answer before the next. **Phrase every question "
                    "the way a senior engineer would talk to a "
                    "stakeholder who isn't fluent in jargon.** That "
                    "means: plain question, 2–3 concrete examples, a "
                    "one-line 'why I'm asking', and a safe default the "
                    "user can pick if they're stuck.\n\n"
                    "**The format for EVERY question — use this verbatim "
                    "shape when you ask:**\n\n"
                    "    > **[topic]** — [plain question]\n"
                    "    > Examples: [a], [b], [c]\n"
                    "    > *(Why I'm asking: [what this informs in the "
                    "requirements].)*\n"
                    "    > If unsure: [a sane default you can fall back "
                    "on].\n\n"
                    "Don't dump all 15 questions at once. ASK ONE. WAIT. "
                    "Then ask the next.\n\n"
                    "**The 15 question areas — adapt phrasing to the "
                    "user's domain:**\n\n"
                    "  **1. What does it do, in one paragraph?** "
                    "Examples: 'A REST API that converts uploaded CSVs "
                    "into PDF reports.' / 'A dashboard showing real-time "
                    "device telemetry for fleet ops.' "
                    "*(Why: the rest of the questions stay anchored to "
                    "this.)* If unsure: ask the user to describe the "
                    "ONE thing it must do well.\n\n"
                    "  **2. Who uses it — and what's the #1 job they "
                    "want done?** Examples: 'Internal ops staff "
                    "reconciling shipments.' / 'External customers "
                    "tracking their order.' / 'Other services calling "
                    "our API.' *(Why: tells me whether to write "
                    "user-facing reqs or system-to-system reqs.)* If "
                    "unsure: name the loudest user — the one who'd "
                    "complain first if it broke.\n\n"
                    "  **3. Is this new, a replacement, or an addition?** "
                    "Examples: 'Greenfield — nothing exists today.' / "
                    "'Replaces our 2018 Java monolith.' / 'Adds a search "
                    "feature to the existing product.' *(Why: a "
                    "replacement inherits backward-compat reqs; "
                    "greenfield doesn't.)* If unsure: 'augmenting "
                    "something existing' is the most common answer.\n\n"
                    "  **4. Tech stack — language, framework, where it "
                    "runs.** Examples: 'Python 3.11 + FastAPI, deployed "
                    "to AWS Lambda.' / 'Go 1.22 + Echo, Kubernetes on "
                    "EKS.' / 'Node 20 + Express, on-prem VM.' *(Why: "
                    "performance / scale reqs depend heavily on "
                    "runtime — cold-start latency, memory ceilings, "
                    "package availability.)* If unsure: 'Same stack as "
                    "your other services' is the safe default.\n\n"
                    "  **5. How many users / requests at once?** "
                    "Examples: '5 internal users, ~10 requests/min.' / "
                    "'500 concurrent users at peak, 50 RPS sustained.' / "
                    "'1 million events per day, batched hourly.' *(Why: "
                    "drives the scale + concurrency reqs.)* If unsure: "
                    "the team's other similar service is the reference "
                    "point — same scale, more, or less?\n\n"
                    "  **6. How fast does it need to feel — in "
                    "milliseconds?** Examples: 'p95 < 200 ms for the "
                    "search endpoint.' / 'Batch job under 30 minutes "
                    "wall-clock.' / 'Page load under 2 seconds on a "
                    "phone.' *(Why: 'fast' is unmeasurable — without a "
                    "number, I can't write a testable AC.)* If unsure: "
                    "'< 1 second for anything user-facing, < 5 min for "
                    "any batch' is a reasonable starting line.\n\n"
                    "  **7. What other systems does it talk to?** "
                    "Examples: 'Pulls from Stripe, writes to Snowflake.' "
                    "/ 'Reads from an Azure Service Bus topic.' / "
                    "'Calls an internal /auth service.' For each: "
                    "REST / gRPC / message queue / DB driver? How is "
                    "auth done? *(Why: every integration is a "
                    "requirement and a failure mode.)* If unsure: list "
                    "the systems even if you don't know the protocol "
                    "yet — I'll ask follow-ups.\n\n"
                    "  **8. What data flows through it, and is any of "
                    "it sensitive?** Examples: 'Order records — names, "
                    "addresses, partial card numbers (PCI scope).' / "
                    "'Just public catalog data — no PII.' / 'Health "
                    "data — HIPAA applies.' Retention period? "
                    "Encryption needs? *(Why: PII triggers compliance "
                    "+ security reqs that wouldn't otherwise exist.)* "
                    "If unsure: 'no PII, no PCI, no PHI' is the safe "
                    "default — but say it explicitly.\n\n"
                    "  **9. Any regulations to satisfy?** Examples: "
                    "'None — internal tool.' / 'GDPR for the EU "
                    "tenant.' / 'SOC 2 Type II audit next quarter.' / "
                    "'FDA 21 CFR Part 820 — this is medical device "
                    "software.' *(Why: regulated systems need explicit "
                    "audit-trail / traceability / approval reqs.)* If "
                    "unsure: ask your security or compliance lead "
                    "before answering — wrong answer here is "
                    "expensive.\n\n"
                    "  **10. What's the security story?** Examples: "
                    "'Internal-only, behind VPN — minimal threat "
                    "model.' / 'Public-facing — assume hostile internet, "
                    "OWASP Top 10 in scope.' / 'Handles payment data — "
                    "PCI controls required.' Secrets management? Auth "
                    "model (OAuth / SAML / mTLS)? *(Why: 'secure' is "
                    "meaningless without naming what you're defending "
                    "against.)* If unsure: 'OWASP Top 10 + secrets in "
                    "a managed vault' is the modern baseline.\n\n"
                    "  **11. How will you know it's working in "
                    "production?** Examples: 'Datadog metrics + PagerDuty "
                    "on error-rate > 1%.' / 'Structured JSON logs to "
                    "Splunk, traces in Honeycomb.' / 'We don't have "
                    "observability yet — need to add it.' *(Why: "
                    "observability is itself a set of requirements — "
                    "what metrics, what SLOs, what alert thresholds.)* "
                    "If unsure: 'request rate + error rate + p95 "
                    "latency, with an alert on error-rate spikes' is "
                    "the minimum viable trio.\n\n"
                    "  **12. What MUST keep working if something "
                    "breaks?** Examples: 'If the DB is down, reads "
                    "must still serve from cache.' / 'If the payments "
                    "API is down, accept the order and retry.' / 'If "
                    "anything breaks, fail fast — no degraded mode.' "
                    "*(Why: failure-mode reqs are the ones bugs "
                    "exploit; making them explicit catches whole bug "
                    "classes.)* If unsure: 'reads stay up, writes can "
                    "queue' is a common pattern worth considering.\n\n"
                    "  **13. How do you want acceptance criteria "
                    "written?** Examples: 'Given/When/Then scenarios "
                    "(Gherkin style).' / 'Numbered bullet list of "
                    "verifiable conditions.' / 'Prose paragraphs — we "
                    "test by hand.' *(Why: the format flows directly "
                    "into the test cases later.)* If unsure: "
                    "'Given/When/Then' is the cleanest for tooling.\n\n"
                    "  **14. About how many requirements do you "
                    "want?** Examples: 'Handful — 5–10, just the "
                    "must-haves.' / 'Moderate — 15–25, with NFRs and "
                    "edge cases.' / 'Comprehensive — 30+, full IEEE "
                    "29148 style.' *(Why: prevents me from generating "
                    "70 reqs when you wanted 12.)* If unsure: 'moderate "
                    "— 15–25' covers most projects.\n\n"
                    "  **15. What does this project NOT do? "
                    "(Out-of-scope — most-missed.)** Examples: 'No "
                    "mobile app yet — web only.' / 'No real-time "
                    "updates — batch refresh every 5 min is fine.' / "
                    "'No user-facing admin — admin happens in the "
                    "existing back-office tool.' *(Why: out-of-scope "
                    "reqs are the ones a junior engineer adds anyway "
                    "and balloons the build. Naming them blocks "
                    "scope creep.)* If unsure: push the user — name "
                    "**three things** this won't do.\n\n"
                    "**Vague-answer rule — if the user says any of "
                    "these, do NOT accept and move on. Push for "
                    "measurable:**\n"
                    "  - 'fast'      → 'p95 in ms?'\n"
                    "  - 'secure'    → 'threat model? PII? PCI? GDPR?'\n"
                    "  - 'scalable'  → 'concurrent users? RPS?'\n"
                    "  - 'reliable'  → 'uptime target? RPO/RTO?'\n"
                    "  - 'simple'    → 'how few clicks / endpoints / "
                    "screens?'\n"
                    "  - 'modern'    → 'which year/version baseline?'\n\n"
                    "**'I don't know' rule:** never skip a question. "
                    "Offer 3 concrete options + your recommendation, "
                    "let them pick. The picking IS the decision and "
                    "becomes a recorded assumption in the rationale.\n\n"
                    "**After all questions:** summarize the full scope "
                    "back in ONE paragraph that reflects EVERY answer — "
                    "this is the user's last chance to catch a "
                    "miscommunication. Wait for explicit approval. Only "
                    "then call `build_project_next(current_phase=1, "
                    "user_signal=<their actual reply>)`."),
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
                3: ("PHASE 3 — IMPLEMENTATION TASKS (EWM) — DEEP, USER-FRIENDLY",
                    "**Do NOT stamp out one task per requirement and ship it.** "
                    "Tasks decompose how the work gets done — they need real "
                    "thought. Interview the user FIRST. Ask 8–12 questions "
                    "ONE AT A TIME using the same friendly shape as Phase 1: "
                    "plain question, concrete examples, why it matters, safe "
                    "default if they're stuck.\n\n"
                    "**Question shape — use this verbatim:**\n\n"
                    "    > **[topic]** — [plain question]\n"
                    "    > Examples: [a], [b], [c]\n"
                    "    > *(Why I'm asking: [what this changes about the "
                    "task list].)*\n"
                    "    > If unsure: [a sane default].\n\n"
                    "**Question areas — adapt phrasing to the project:**\n\n"
                    "  **1. Should each requirement become exactly one "
                    "task, or do some need to split?** Examples: 'Strict "
                    "1:1 — keep traceability clean.' / 'Big reqs split into "
                    "spike + build + harden.' / 'Trivial reqs (like "
                    "logging) collapse 3 reqs → 1 task.' *(Why: 1:1 is "
                    "simple but unrealistic for complex reqs; splitting "
                    "captures real work but bloats the task list.)* If "
                    "unsure: '1:1 unless I flag a req as too big' is the "
                    "safe default.\n\n"
                    "  **2. What cross-cutting work isn't tied to a single "
                    "req?** Examples: 'CI/CD pipeline setup.' / 'Infra-as-"
                    "code (Terraform / Helm).' / 'Observability — metrics, "
                    "logs, dashboards.' / 'Secrets in Vault / AWS Secrets "
                    "Manager.' / 'Deployment runbook + on-call doc.' / "
                    "'Feature-flag plumbing.' *(Why: these are real "
                    "tasks but they don't link to one req — most users "
                    "forget ≥2 of them and they show up as 'why is "
                    "deploy broken' bugs later.)* Read the list above to "
                    "the user — they pick which apply. If unsure: all of "
                    "them apply to any non-trivial service.\n\n"
                    "  **3. How does your team estimate effort?** "
                    "Examples: 'Story points (Fibonacci: 1/2/3/5/8).' / "
                    "'T-shirt sizes (XS / S / M / L / XL).' / 'Hours (4h, "
                    "1d, 2d).' / 'We don't estimate.' *(Why: I'll write "
                    "estimates in the task body using your team's "
                    "currency — don't want to put 'M' into a team that "
                    "speaks in points.)* If unsure: 'we don't estimate' "
                    "is a fine answer — I'll skip the estimate field.\n\n"
                    "  **4. Which tasks block everything else? Name the "
                    "must-be-first set.** Examples: 'DB schema first, "
                    "then everything else can parallelize.' / 'Auth + CI "
                    "pipeline + base scaffolding before any feature "
                    "work.' / 'Nothing blocks — all parallel.' *(Why: "
                    "captures real dependencies so the team doesn't trip "
                    "over them in sprint planning.)* If unsure: schema + "
                    "scaffolding + auth is the foundation set 90% of the "
                    "time.\n\n"
                    "  **5. Any requirements where you don't yet know "
                    "the implementation approach?** Examples: 'REQ-7 — "
                    "we need to pick between Kafka and SQS, no decision "
                    "yet.' / 'REQ-11 — performance target may need a "
                    "rewrite of the indexing layer, unclear.' / 'No — all "
                    "implementations are obvious.' *(Why: those reqs get "
                    "a research/spike task FIRST with a time-box and a "
                    "concrete deliverable like an ADR.)* If unsure: walk "
                    "the req list with the user; flag anything they "
                    "hesitate on.\n\n"
                    "  **6. What does 'Resolved' mean on your team?** "
                    "Examples: 'Code merged to main + CI green.' / "
                    "'Merged + deployed to staging + smoke-test passed.' "
                    "/ 'Merged + demo'd in standup + docs updated.' / "
                    "'Merged + PM-signed-off.' *(Why: I write the "
                    "Definition of Done checklist verbatim into every "
                    "task body — without it, 'done' means different "
                    "things to different people.)* If unsure: 'merged + "
                    "tests green + deployed to staging' is the most "
                    "common modern bar.\n\n"
                    "  **7. Who owns these tasks — assign now or leave "
                    "open?** Examples: 'Assign all to me.' / 'Assign by "
                    "team area, not individual.' / 'Leave unassigned — "
                    "the team pulls from Backlog.' / 'Brett gets the API "
                    "tasks, Sarah gets the UI tasks.' *(Why: "
                    "preassignment changes priority signaling. If you "
                    "name specific people, I'll call `resolve_user` to "
                    "verify they exist in ELM before assigning.)* If "
                    "unsure: 'leave unassigned in Backlog' is the safe "
                    "default — team pulls when ready.\n\n"
                    "  **8. Any tasks you already know are risky?** "
                    "Examples: 'New tech — we've never used this "
                    "queue.' / 'Third-party API with flaky uptime.' / "
                    "'Security-sensitive — handling raw credit cards.' / "
                    "'Unclear AC — stakeholder still deciding.' *(Why: "
                    "I add a **Risk:** line to the task body so "
                    "reviewers slow down on those.)* If unsure: walk the "
                    "task list with the user once it's drafted — risks "
                    "become obvious when you see them in context.\n\n"
                    "  **9. Schedule into a sprint, or leave in "
                    "Backlog?** Examples: 'Backlog — no iteration set.' "
                    "/ 'Target Sprint 24 (Jan 15–29).' / 'All into "
                    "current iteration.' *(Why: scheduled tasks signal "
                    "commitment; unscheduled stays as proposed work.)* "
                    "If unsure: 'Backlog' is correct unless your "
                    "planning meeting is today.\n\n"
                    "  **10. Which EWM team area owns this work?** "
                    "Examples: 'Backend / API team.' / 'Platform team.' "
                    "/ 'Mobile.' / 'Don't know — I'll set it later.' "
                    "*(Why: team area routes the task to the right "
                    "queue and respects existing workflow rules.)* If "
                    "unsure: the default team area on the EWM project "
                    "works — they can re-route later.\n\n"
                    "  **11. Any links to add beyond the req?** "
                    "Examples: 'Design doc on Confluence.' / 'ADR in "
                    "the repo.' / 'Figma frame for the new UI.' / "
                    "'Existing Jira ticket we're migrating from.' "
                    "*(Why: makes EWM the hub instead of a dead end — "
                    "engineers click through to the design.)* If "
                    "unsure: skip — we can link later if needed.\n\n"
                    "  **12. What do you explicitly NOT want as tasks "
                    "this round?** Examples: 'No tasks for non-"
                    "functional reqs — those become test cases only.' "
                    "/ 'No documentation tasks — handled separately.' / "
                    "'No infra tasks yet — DevOps will handle in "
                    "parallel.' *(Why: out-of-scope tasks are the ones "
                    "I'd create-by-default and clutter the board.)* "
                    "Push hard for at least one answer here.\n\n"
                    "**Vague-answer rule:**\n"
                    "  - 'small'      → 'closer to 2 hours or 2 days?'\n"
                    "  - 'depends'    → 'on what specifically? name the "
                    "blocker.'\n"
                    "  - 'just do it' → 'what does Resolved look like? "
                    "merged? deployed? tested?'\n"
                    "  - 'whoever'    → 'unassigned in Backlog is fine — "
                    "confirming that's what you want?'\n\n"
                    "**'I don't know' rule:** offer 3 concrete options + "
                    "your recommendation, have them pick. The picking IS "
                    "the decision.\n\n"
                    "After interview: generate task list internally → "
                    "preview as a table (title | covers req | est | owner "
                    "| deps | risk | DoD summary) → wait for explicit "
                    "approval.\n\n"
                    "Task body template (apply per task):\n"
                    "  - **Objective:** one line on what success looks "
                    "like\n"
                    "  - **Deliverables:** bullet list (code, tests, "
                    "docs, infra)\n"
                    "  - **Dependencies:** other tasks / external "
                    "blockers\n"
                    "  - **Definition of Done:** the team-agreed checklist "
                    "from Q6\n"
                    "  - **Risks / unknowns:** if flagged in Q8\n"
                    "Don't copy the requirement body — it's already "
                    "linked.\n\n"
                    "**Use `create_tasks` (BATCH/plural), NOT `create_task` "
                    "per req.** With 14+ requirements, calling create_task "
                    "in a loop forces the user to approve each one "
                    "individually in Bob. create_tasks creates all N in "
                    "ONE tool call → ONE approval click. Pass `tasks=[...]` "
                    "with {title, description, requirement_url} per item, "
                    "requirement_url verbatim from the Phase 2 output. "
                    "Cross-cutting tasks (no specific req) can use any of "
                    "the foundational reqs or be linked separately after.\n\n"
                    "After tasks are pushed, call `build_project_next("
                    "current_phase=3, user_signal=<user's reply>, "
                    "context='<task URLs>')`."),
                4: ("PHASE 4 — TEST CASES (ETM) — DEEP, USER-FRIENDLY",
                    "**Do NOT generate happy-path tests and ship them.** Tests "
                    "are where bad requirements get caught — they need to be "
                    "designed, not stamped out. Interview FIRST. Ask 8–12 "
                    "questions ONE AT A TIME using the same friendly shape "
                    "as Phase 1: plain question, concrete examples, why it "
                    "matters, safe default if stuck.\n\n"
                    "**Question shape — use this verbatim:**\n\n"
                    "    > **[topic]** — [plain question]\n"
                    "    > Examples: [a], [b], [c]\n"
                    "    > *(Why I'm asking: [what this changes about the "
                    "test set].)*\n"
                    "    > If unsure: [a sane default].\n\n"
                    "**Question areas:**\n\n"
                    "  **1. Which test levels go in ETM?** Examples: "
                    "'System + acceptance only — unit tests live in the "
                    "repo.' / 'Acceptance only — devs own everything "
                    "else.' / 'Include integration + system + "
                    "acceptance.' *(Why: ETM is meant for "
                    "human-meaningful tests, not every assert in a "
                    "unit-test file — without scoping I'd generate "
                    "noise.)* If unsure: 'system + acceptance' is the "
                    "industry default.\n\n"
                    "  **2. Manual procedure or automated tests?** "
                    "Examples: 'Manual — QA follows the steps by "
                    "hand.' / 'Automated — pytest, results posted via "
                    "CI.' / 'Hybrid — happy paths automated, edge "
                    "cases manual.' If automated, name the framework "
                    "(pytest / JUnit / Cypress / Robot / Playwright). "
                    "*(Why: automated test cases reference a test ID or "
                    "file path so engineers can find the code; manual "
                    "ones spell out steps for a human.)* If unsure: "
                    "'manual procedure documented in ETM, automation "
                    "lives in repo' is the cleanest split.\n\n"
                    "  **3. How many tests per requirement — happy path "
                    "only, or also negative + boundary?** Examples: "
                    "'One happy-path test per req (minimum).' / "
                    "'Happy + at least one failure case per req.' / "
                    "'Full set: positive + negative + boundary value "
                    "per req (typically 3+ tests/req).' *(Why: a single "
                    "happy-path test catches almost nothing — most "
                    "production bugs hit the failure path or the "
                    "boundary.)* If unsure: 'positive + negative + "
                    "boundary' is the standard for any req that matters "
                    "in production.\n\n"
                    "  **4. What edge cases worry you? Walk through "
                    "the worst-input list.** Examples: 'Empty input.' / "
                    "'Max-length input (10MB upload).' / 'Malformed "
                    "JSON.' / 'Unicode emoji / RTL text.' / "
                    "'Concurrent requests for the same record.' / "
                    "'Downstream API returns 503.' / 'DB latency "
                    "spike.' / 'Auth token expires mid-request.' "
                    "*(Why: most production incidents are 'we never "
                    "tested for X' — surface the X now, not after "
                    "rollback.)* Walk the req list aloud with the user; "
                    "they'll think of 2–3 per req. If unsure: read them "
                    "the standard worst-input list above and have them "
                    "pick which apply.\n\n"
                    "  **5. Where does test data come from?** "
                    "Examples: 'Synthetic data we generate per test.' "
                    "/ 'Fixture file checked into the repo.' / "
                    "'Anonymized snapshot from prod, refreshed weekly.' "
                    "/ 'Mocked entirely — no real data.' If PII is in "
                    "play: how is it scrubbed? *(Why: 'use valid data' "
                    "is not a precondition — the test case body needs "
                    "actual values or a fixture name to be "
                    "reproducible.)* If unsure: 'synthetic, generated "
                    "per test' is the cleanest for CI.\n\n"
                    "  **6. What environment does the test run in?** "
                    "Examples: 'Local dev — docker-compose stack.' / "
                    "'Shared staging env.' / 'Dedicated test "
                    "environment refreshed nightly.' / 'Prod-mirror "
                    "with synthetic traffic.' What external services "
                    "must be live (or mocked)? Auth tokens? Feature "
                    "flags on/off? *(Why: 'system is available' is "
                    "useless as a precondition — preconditions must be "
                    "specific enough that two engineers reproduce the "
                    "same setup.)* If unsure: 'shared staging with "
                    "real downstream services' is the most common.\n\n"
                    "  **7. What does 'pass' actually look like?** "
                    "Examples: 'Exact value match — output equals "
                    "expected.' / 'Tolerance band — value within ±5% "
                    "of expected.' / 'Log line X appears within 2s.' "
                    "/ 'HTTP 200 + specific JSON shape.' / 'p95 "
                    "latency < 200ms over 100 runs.' *(Why: 'looks "
                    "right' / 'works correctly' aren't testable — "
                    "without a measurable criterion, the test will "
                    "drift over time.)* If unsure: 'exact-value match "
                    "for functional tests, p95-threshold for "
                    "performance tests' is the standard.\n\n"
                    "  **8. Any requirements are non-functional "
                    "(performance, scale, reliability)? Each needs its "
                    "own test with thresholds + load profile.** "
                    "Examples: 'p95 < 200ms at 100 RPS, 10-min steady "
                    "load.' / 'Sustain 1000 concurrent users for 30 "
                    "min without OOM.' / 'Spike to 10× normal for 60s, "
                    "auto-recover.' Load profiles: steady, ramp, "
                    "spike, soak. *(Why: NFRs that ship without "
                    "explicit thresholds always degrade silently.)* "
                    "If unsure: pick the highest-traffic endpoint, set "
                    "p95 threshold from your SLO, run 10-min steady "
                    "load — that's the minimum-viable perf test.\n\n"
                    "  **9. What's the security threat surface — every "
                    "threat needs at least one negative test.** "
                    "Examples: 'Auth bypass — call API without "
                    "token.' / 'Authz escalation — user A tries to "
                    "read user B's data.' / 'SQL injection — "
                    "malicious input in query params.' / 'Rate-limit "
                    "evasion — flood from N IPs.' *(Why: if Phase 1 "
                    "flagged a threat model, the test set must mirror "
                    "it — otherwise the model is theatre.)* If unsure: "
                    "OWASP Top 10 as a checklist is the modern "
                    "baseline.\n\n"
                    "  **10. If your reqs use Given/When/Then, should I "
                    "map them straight to test steps?** Examples: 'Yes "
                    "— Given → Precondition, When → Step, Then → "
                    "Expected Result.' / 'No — the GWT was for "
                    "communication only, write test steps fresh.' / "
                    "'We didn't use GWT — write steps fresh.' *(Why: "
                    "mapping preserves traceability between AC and "
                    "test step verbatim.)* If unsure: map directly — "
                    "that's the whole point of GWT.\n\n"
                    "  **11. One test per req, or can one test cover "
                    "multiple reqs?** Examples: 'Strict 1:1.' / 'An "
                    "integration test naturally covers 3-4 reqs at "
                    "once — that's fine, link to all of them.' *(Why: "
                    "many-to-many tests are realistic but they need "
                    "explicit `validatesRequirement` links to every "
                    "req they cover — otherwise traceability lies.)* "
                    "If unsure: '1:1 for unit-level, many-to-many "
                    "allowed for integration-level' is the practical "
                    "rule.\n\n"
                    "  **12. What do you explicitly NOT want tested "
                    "this round?** Examples: 'No load tests yet — "
                    "perf comes after MVP.' / 'No security pen test — "
                    "scheduled separately with the security team.' / "
                    "'No cross-browser matrix — Chrome only for v1.' "
                    "/ 'No exploratory testing — only automated.' "
                    "*(Why: out-of-scope tests are the ones I'd "
                    "generate by default and bloat the suite.)* Push "
                    "hard for at least one answer.\n\n"
                    "**Vague-answer rule:**\n"
                    "  - 'works'      → 'pass criterion: exact value? "
                    "tolerance? what's measurable?'\n"
                    "  - 'should fail'→ 'with what error code / "
                    "message? no crash? specific log line?'\n"
                    "  - 'reasonable' → 'reasonable = p95 < what ms? "
                    "error rate < what %?'\n"
                    "  - 'normal data'→ 'name 3 representative records "
                    "— what's typical input shape?'\n\n"
                    "**'I don't know' rule:** offer 3 concrete options + "
                    "your recommendation. Examples:\n"
                    "  - 'For empty-input behavior — return 400, return "
                    "empty list, or treat as error? Pick one.'\n"
                    "  - 'For login throttling threshold — 5 attempts / "
                    "min, 10 / 5min, or no throttle? Pick one.'\n\n"
                    "After interview: generate the test set internally → "
                    "preview as a table (test title | covers req(s) | "
                    "type: pos/neg/boundary/perf | env | automated? | "
                    "key pass criterion) → wait for explicit approval.\n\n"
                    "Test case body template (apply per case):\n"
                    "  - **Preconditions:** environment, data, auth "
                    "state, feature flags — all explicit, no 'system "
                    "is ready'\n"
                    "  - **Test Steps:** numbered, each with action + "
                    "expected observable result\n"
                    "  - **Pass/Fail Criteria:** measurable; ties to "
                    "the AC from the req\n"
                    "  - **Test Data:** specific values or fixture "
                    "reference\n"
                    "  - **Cleanup:** anything to revert (DB rows, "
                    "feature flags)\n\n"
                    "**Use `create_test_cases` (BATCH/plural), NOT "
                    "`create_test_case` per req.** Same reasoning as "
                    "Phase 3 — one tool call instead of N approval clicks. "
                    "Pass `test_cases=[...]` with {title, description, "
                    "requirement_url} per item. If a test covers multiple "
                    "reqs, pick the primary one for the batch call and "
                    "use `create_link` afterward to add the rest as "
                    "validates links.\n\n"
                    "Optionally also `create_test_script` for detailed "
                    "numbered procedures linked via test_case_url (this "
                    "stays singular; scripts are typically one-per-test, "
                    "not batch). Recommend scripts when test steps are "
                    "non-trivial (>5 steps or environment-sensitive).\n\n"
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
            clear_bind_lock = bool(arguments.get("clear_phase_2_bind_failed", False))

            # Recovery path: caller is clearing the Phase 2 bind-failed
            # lock after manually resolving the bind. Verify the run
            # exists and surface what was cleared.
            if clear_bind_lock and run_id:
                run = _get_run(run_id)
                if not run:
                    return [TextContent(type="text", text=(
                        f"Cannot clear bind lock — run `{run_id}` not found."
                    ))]
                had_lock = run.get("phase_2_bind_failed", False)
                run["phase_2_bind_failed"] = False
                run["last_bind_failure"] = ""
                _persist_run(run)
                return [TextContent(type="text", text=(
                    f"# Phase 2 bind lock cleared\n\n"
                    f"Run `{run_id}` is no longer blocked at Phase 2. "
                    f"{'(Lock was set; cleared.)' if had_lock else '(Lock was not set; no-op.)'} "
                    f"You can now call `build_project_next(current_phase=2, "
                    f"user_signal=<verbatim approval>, run_id=\"{run_id}\")` "
                    f"to advance to Phase 3.\n\n"
                    f"⚠️ Only do this if you've actually verified the reqs "
                    f"are in the module (e.g. via "
                    f"`get_module_requirements`). Clearing the lock without "
                    f"resolving the bind silently breaks the rest of the flow."
                ))]

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

        # ── wrap_up_session ───────────────────────────────────────
        if name == "wrap_up_session":
            notes = (arguments.get("notes") or "").strip()
            status = (arguments.get("status") or "Completed").strip()
            sess = _team_session_for_current_user()
            if not sess:
                return [TextContent(type="text", text=(
                    "No active BOB Team Actions session found for the "
                    "current user. Either nothing material was done yet "
                    "(no auto-log fired) or team-actions is disabled "
                    "(`ELM_MCP_TEAM_ACTIONS=0`). Nothing to wrap up."
                ))]
            # Append the wrap-up note as a final activity entry
            if notes:
                _record_team_activity(
                    kind="wrap_up_session",
                    summary=f"wrap-up: \"{notes[:200]}\"",
                    user=sess["user"],
                    project_url=sess["project_url"],
                )
            sess["status"] = status
            try:
                _flush_session_to_dng(sess)
            except Exception as e:
                return [TextContent(type="text", text=(
                    f"Wrap-up flush failed: {e}. Session marked "
                    f"'{status}' in memory but the final DNG entry "
                    f"didn't get written."
                ))]
            artifact_url = sess.get("artifact_url", "")
            return [TextContent(type="text", text=(
                f"# Session wrapped up\n\n"
                f"**User:** {sess['user']}\n"
                f"**Status:** {status}\n"
                f"**Session ID:** {sess['session_id']}\n"
                f"**Final entry:** [{artifact_url or 'DNG'}]({artifact_url})\n\n"
                f"Future tool calls in this process start a fresh team-"
                f"actions session. Anyone on the team can read the BOB "
                f"Team Actions module to see this session's record."
            ))]

        # ── get_team_actions ──────────────────────────────────────
        if name == "get_team_actions":
            since = (arguments.get("since") or "7d").strip().lower()
            who_filter = (arguments.get("who") or "").strip().lower()
            status_filter = (arguments.get("status") or "").strip().lower()
            project_arg = (arguments.get("project") or "").strip()

            # Resolve project
            project_url = ""
            if project_arg:
                if not _projects_cache:
                    _projects_cache = client.list_projects()
                proj = _find_by_identifier(_projects_cache, project_arg)
                if proj:
                    project_url = proj.get("services_url", "") or proj.get("url", "")
            if not project_url:
                # Use the active session's project, or the most recent
                # team-actions session
                sess = _team_session_for_current_user()
                if sess:
                    project_url = sess["project_url"]
            if not project_url and _projects_cache:
                project_url = _projects_cache[0].get("services_url", "") or _projects_cache[0].get("url", "")
            if not project_url:
                return [TextContent(type="text", text=(
                    "Error: couldn't resolve a DNG project. Pass "
                    "`project` or call `connect_to_elm` + `list_projects` "
                    "first."
                ))]

            # Find the BOB Team Actions module
            try:
                modules = client.get_modules(project_url) or []
            except Exception as e:
                return [TextContent(type="text", text=f"Error: failed to list modules — {e}")]
            target_mod = next(
                (m for m in modules
                 if m.get("title", "").strip().lower()
                 == _TEAM_ACTIONS_MODULE_NAME.lower()),
                None,
            )
            if not target_mod:
                return [TextContent(type="text", text=(
                    f"No '{_TEAM_ACTIONS_MODULE_NAME}' module found in "
                    f"this project yet. The module is auto-created the "
                    f"first time anyone on the team does material work "
                    f"(creates a requirement, transitions a task, "
                    f"advances a build phase). If everyone has just been "
                    f"reading, the module won't exist yet — that's "
                    f"expected."
                ))]

            # Read entries
            try:
                entries = client.get_module_requirements(target_mod.get("url", "")) or []
            except Exception as e:
                return [TextContent(type="text", text=f"Error: failed to read module — {e}")]

            # Filter to [BOB-TEAM] artifacts; apply who / status / since filters
            import datetime as _dt
            now = _dt.datetime.utcnow()
            since_delta_h = 7 * 24
            if since.endswith("h"):
                try: since_delta_h = int(since[:-1])
                except ValueError: pass
            elif since.endswith("d"):
                try: since_delta_h = int(since[:-1]) * 24
                except ValueError: pass
            cutoff = now - _dt.timedelta(hours=since_delta_h)

            filtered = []
            for e in entries:
                title = e.get("title", "") or ""
                if "[BOB-TEAM]" not in title:
                    continue
                if who_filter and who_filter not in title.lower():
                    continue
                # Status filter — pull from body if there
                body = e.get("content", "") or e.get("primary_text", "") or ""
                if status_filter and status_filter not in body.lower():
                    continue
                # Modified-time filter (best-effort — not all reads return it)
                mod_str = e.get("modified", "") or ""
                if mod_str:
                    try:
                        mod_dt = _dt.datetime.fromisoformat(mod_str.replace("Z", ""))
                        if mod_dt < cutoff:
                            continue
                    except (ValueError, TypeError):
                        pass
                filtered.append({
                    "title": title.replace("[BOB-TEAM]", "").strip(),
                    "url": e.get("url", ""),
                    "modified": mod_str,
                    "body_excerpt": body[:300] + ("…" if len(body) > 300 else ""),
                })

            if not filtered:
                return [TextContent(type="text", text=(
                    f"No team actions in the last {since}"
                    + (f" by {who_filter}" if who_filter else "")
                    + (f" with status {status_filter}" if status_filter else "")
                    + ". The BOB Team Actions module exists but no "
                    f"entries match. (Total entries in module: {len(entries)}.)"
                ))]

            lines = [
                f"# Team Actions — last {since}",
                f"_Module: [{target_mod.get('title')}]({target_mod.get('url')})_",
                "",
                f"**{len(filtered)} entries**",
                "",
            ]
            for f in sorted(filtered, key=lambda x: x.get("modified", ""), reverse=True):
                lines.append(f"### [{f['title']}]({f['url']})")
                if f.get("modified"):
                    lines.append(f"_Modified: {f['modified'][:19]}_")
                lines.append("")
                excerpt = f.get("body_excerpt", "").strip()
                if excerpt:
                    lines.append(excerpt)
                lines.append("")
            return [TextContent(type="text", text="\n".join(lines))]

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

        if name in ("build_new_project", "build_from_existing"):
            idea = (arguments.get("project_idea") or "").strip()
            command_label = name  # one of build_new_project / build_from_existing
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
            tool_names = {t.name for t in tools}

            # Use-case-first layout. Each section answers a USER intent
            # ("I want to..."), shows the FIRST thing to call, then the
            # follow-on tools that flow from it. Reduces "60 tools" to
            # ~10 entry points the user actually picks from.
            lines = [
                f"# ELM MCP — what I can do (v{__version__})",
                "",
                f"**{len(tools)} tools registered.** This list is "
                f"organized by what you want to DO, not by domain. Pick "
                f"the row that matches your intent — each starting "
                f"point handles the rest.",
                "",
                "## Common starting points",
                "",
                "| I want to... | Start here | Then the flow handles the rest |",
                "|---|---|---|",
                "| **Build a new project end-to-end** (idea → reqs → tasks → tests → code) | `/build-new-project` (or call `build_new_project` tool) | Phases 0–9 with user-approval gates between each |",
                "| **Build from existing material** (Jira epic PDF, pasted reqs, existing DNG module) | `/build-from-existing` (or call `build_from_existing` tool) | Imports source → converges with the standard flow at Phase 5 |",
                "| **Import a Jira epic / work-item PDF** standalone (no code yet) | `/import-work-item` | EWM epic + DNG reqs + ETM test cases + cross-links in one round |",
                "| **Import existing reqs** as plain text (bullets, prose, Notion paste) | `/import-requirements` | Parses to atomic shall-statements → DNG module |",
                "| **Pull a LIVE Jira issue into DNG** with bidirectional links (requires Atlassian MCP installed alongside elm-mcp) | `/import-jira` | Round-trips: `getJiraIssue` → interview → `create_requirements` with `Source:` line → `addCommentToJiraIssue` back-link |",
                "| **Read what's in DNG already** | `connect_to_elm` → `list_projects` → `get_modules` → `get_module_requirements` | Browse, search, export the existing project |",
                "| **Resume a paused build** | `build_project_resume` (no args lists active runs) | Picks up at the right phase using stored state |",
                "| **Check what the team's been doing** | `get_team_actions` | Reads BOB Team Actions module; filter by who/since/status |",
                "| **End your work session cleanly** | `wrap_up_session` | Final entry to BOB Team Actions; teammates can pick up |",
                "| **Generate the trace matrix for a finished build** | `generate_traceability_matrix` | req↔task↔test markdown table with clickable URLs |",
                "| **Look up a req by its short ID** (REQ-123) | `resolve_requirement_id` | Returns URL for use in subsequent calls |",
                "| **Diagnose: am I connected, what version, what's open** | `elm_mcp_health` | Connection state, MCP version, auto-update status, active runs |",
                "| **Update yourself** | `update_elm_mcp` | One tool call → fetch + pull + restart instructions |",
                "",
                "## I'm new — where do I start?",
                "",
                "Just say *what you want to do*. Don't read the full "
                "tool list — invoke `/getting-started` and the AI "
                "routes you to the right starting point with one "
                "clarifying question. The 50+ underlying tools are "
                "the implementation detail; you don't browse them.",
                "",
            ]

            # If the user really wants the full inventory (advanced),
            # surface it as an appendix grouped by domain. Most users
            # never read past the use-case table above.
            domains = {
                "Server / Diagnostics": [
                    "connect_to_elm", "elm_mcp_health", "list_capabilities",
                    "update_elm_mcp",
                ],
                "DNG — Read": [
                    "list_projects", "get_modules", "get_module_requirements",
                    "search_requirements", "get_artifact_types", "get_link_types",
                    "get_attribute_definitions", "list_baselines",
                    "compare_baselines", "extract_pdf", "find_folder",
                    "resolve_requirement_id",
                ],
                "DNG — Write": [
                    "create_module", "create_requirements", "update_requirement",
                    "update_requirement_attributes", "create_link",
                    "create_baseline", "add_to_module", "create_folder",
                ],
                "EWM (Work Items)": [
                    "query_work_items", "get_ewm_workitem_types",
                    "get_workflow_states", "create_task", "create_defect",
                    "update_work_item", "transition_work_item",
                    "link_workitem_to_external_url",
                ],
                "ETM (Test Management)": [
                    "list_test_cases", "list_test_plans",
                    "list_test_execution_records", "create_test_case",
                    "create_test_script", "create_test_result",
                    "create_test_plan", "create_test_execution_record",
                ],
                "GCM (Global Configuration)": [
                    "list_global_configurations", "list_global_components",
                    "get_global_config_details",
                ],
                "Jazz SCM + Code Reviews": [
                    "scm_list_projects", "scm_list_changesets",
                    "scm_get_changeset", "scm_get_workitem_changesets",
                    "review_get", "review_list_open",
                ],
                "User Resolution": ["resolve_user"],
                "Build orchestration": [
                    "build_new_project", "build_from_existing",
                    "build_project_next", "build_project_status",
                    "build_project_resume", "generate_traceability_matrix",
                    "publish_build_state_to_dng",
                ],
                "Team coordination": [
                    "wrap_up_session", "get_team_actions",
                ],
                "Visualization": ["generate_chart"],
                "Export": ["export_module_to_xlsx"],
            }

            tool_descs = {
                t.name: (t.description or "").split(".")[0].strip() + "."
                for t in tools
            }
            write_tools = {
                "create_module", "create_requirements", "update_requirement",
                "update_requirement_attributes", "create_link",
                "create_baseline", "add_to_module", "create_folder",
                "create_task", "create_defect", "update_work_item",
                "transition_work_item", "link_workitem_to_external_url",
                "create_test_case", "create_test_script",
                "create_test_result", "create_test_plan",
                "create_test_execution_record", "generate_chart",
                "publish_build_state_to_dng",
            }

            lines.append("---")
            lines.append("")
            lines.append("## Full tool inventory (appendix)")
            lines.append("")
            lines.append(
                "_If you're an LLM looking at this: you DON'T need to "
                "read this section to do useful work. Use the table "
                "above to find your starting point. This appendix is "
                "for completeness only. ⚠️ marks tools that ALWAYS "
                "preview-and-confirm before firing._"
            )
            lines.append("")

            seen = set()
            for domain, names_in_domain in domains.items():
                names_present = [n for n in names_in_domain if n in tool_names]
                if not names_present:
                    continue
                lines.append(f"### {domain}")
                for n in names_present:
                    seen.add(n)
                    marker = " ⚠️" if n in write_tools else ""
                    lines.append(
                        f"- **`{n}`**{marker} — "
                        f"{tool_descs.get(n, 'no description')}"
                    )
                lines.append("")

            uncategorized = [n for n in tool_names if n not in seen]
            if uncategorized:
                lines.append("### Other (recent additions)")
                for n in uncategorized:
                    lines.append(
                        f"- **`{n}`** — {tool_descs.get(n, 'no description')}"
                    )
                lines.append("")

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
            if not _is_newer_version(latest, __version__):
                # Either equal OR you're running AHEAD of latest published
                # release (a tag/release wasn't created yet for the
                # version on main). Don't downgrade — just report.
                if _version_tuple(latest) == _version_tuple(__version__):
                    return [TextContent(type="text", text=(
                        f"Already on the latest version: **v{__version__}**. "
                        f"Nothing to do."
                    ))]
                # latest < current: you're ahead of the latest tagged release.
                return [TextContent(type="text", text=(
                    f"You're running **v{__version__}**, which is AHEAD of "
                    f"the latest published GitHub release "
                    f"(**v{latest}**). Nothing to update — auto-update "
                    f"refuses to downgrade. (If a newer release was "
                    f"supposed to exist, ask the maintainer to publish "
                    f"a Release at "
                    f"https://github.com/{GITHUB_REPO}/releases.)"
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

        # ── revert_elm_mcp (roll back to a prior version) ─────
        if name == "revert_elm_mcp":
            import subprocess as _sub
            project_dir = _project_dir()
            if not _is_git_managed():
                return [TextContent(type="text", text=(
                    f"This install isn't git-managed (e.g. installed via "
                    f"Smithery as a frozen bundle) so version rollback "
                    f"isn't supported. Reinstall the desired version "
                    f"manually:\n\n"
                    f"`curl -fsSL https://raw.githubusercontent.com/"
                    f"{GITHUB_REPO}/main/install.sh | bash`"
                ))]

            # Fetch tags first so we have the full list (and any newly-
            # published releases since the install).
            try:
                _sub.run(["git", "-C", project_dir, "fetch", "--tags",
                          "--quiet", "origin"],
                         check=True, timeout=15)
            except Exception as e:
                return [TextContent(type="text", text=(
                    f"Failed to fetch tags from origin: {e}\n\n"
                    f"You may be offline or the remote may be "
                    f"misconfigured. You can still revert to any "
                    f"locally-known tag listed below."
                ))]

            # Enumerate available version tags
            try:
                out = _sub.run(
                    ["git", "-C", project_dir, "tag", "-l", "v*",
                     "--sort=-version:refname"],
                    capture_output=True, text=True, check=True, timeout=10,
                )
                tags = [t.strip() for t in out.stdout.split("\n") if t.strip()]
            except Exception as e:
                return [TextContent(type="text",
                                     text=f"Failed to list tags: {e}")]

            if not tags:
                return [TextContent(type="text", text=(
                    "No version tags found locally. Are you on a fresh "
                    "install? Try `git fetch --tags origin` from a "
                    "terminal and retry."
                ))]

            target = (arguments.get("version") or "").strip()

            # No target: list available versions
            if not target:
                lines = [
                    "# ELM MCP — Available Versions",
                    "",
                    f"**Current:** v{__version__}",
                    "",
                    "**Available tags (latest first):**",
                    "",
                ]
                for t in tags[:25]:
                    marker = "  ← current" if t == f"v{__version__}" else ""
                    lines.append(f"- `{t}`{marker}")
                if len(tags) > 25:
                    lines.append(f"- _(... {len(tags) - 25} older versions)_")
                lines += [
                    "",
                    "## To revert",
                    "",
                    "Call `revert_elm_mcp(version='0.12.7')` (or any "
                    "tag above) to check that version out. The current "
                    "server keeps running until you restart your AI "
                    "host.",
                    "",
                    "## To return to latest after a revert",
                    "",
                    "Call `update_elm_mcp` — it detects detached HEAD "
                    "and re-checks out main.",
                ]
                return [TextContent(type="text", text="\n".join(lines))]

            # Normalize the target tag
            tag = target if target.startswith("v") else f"v{target}"

            if tag not in tags:
                close = [t for t in tags if target.lstrip("v") in t][:5]
                hint = (f"\n\nDid you mean one of: "
                        f"{', '.join(close)}?") if close else ""
                return [TextContent(type="text", text=(
                    f"Version `{tag}` not found in available tags."
                    f"{hint}\n\n"
                    f"Call `revert_elm_mcp` without arguments to see "
                    f"the full list."
                ))]

            # Check the target is actually older / different — if equal,
            # no-op gracefully.
            if tag == f"v{__version__}":
                return [TextContent(type="text", text=(
                    f"You're already on **{tag}**. Nothing to revert."
                ))]

            # Perform the checkout
            try:
                _sub.run(
                    ["git", "-C", project_dir,
                     "-c", "advice.detachedHead=false",
                     "checkout", tag],
                    check=True, timeout=20,
                    capture_output=True, text=True,
                )
            except _sub.CalledProcessError as e:
                stderr = (e.stderr or "")[:400]
                return [TextContent(type="text", text=(
                    f"`git checkout {tag}` failed.\n\n"
                    f"```\n{stderr}\n```\n\n"
                    f"This usually means you have uncommitted local "
                    f"changes. From a terminal:\n\n"
                    f"```\ncd {project_dir}\n"
                    f"git stash      # save local changes\n"
                    f"git checkout {tag}\n```\n\n"
                    f"Then restart your AI host."
                ))]
            except Exception as e:
                return [TextContent(type="text",
                                     text=f"Unexpected checkout error: {e}"
                                     )]

            _record_check_now()
            return [TextContent(type="text", text=(
                f"✓ Reverted to **{tag}** (was v{__version__}).\n\n"
                f"**Restart your AI assistant** (Bob / Claude Code / "
                f"etc.) to load this version. The currently-running "
                f"server keeps using v{__version__} until restart.\n\n"
                f"**To return to the latest version later:** call "
                f"`update_elm_mcp` — it detects detached HEAD and "
                f"re-checks out main + pulls the latest tag."
            ))]

        # ── extract_pdf (no connection needed) ────────────────
        if name == "extract_pdf":
            file_path = arguments.get("file_path", "").strip()
            if not file_path:
                return [TextContent(type="text", text=(
                    "Error: file_path is required.\n\n"
                    "**Bob workaround:** if the user attached a PDF to chat "
                    "but Bob can't access the file content, ask them to "
                    "either (a) tell you the absolute path on their machine "
                    "(e.g. `~/Downloads/their-file.pdf`), or (b) open the "
                    "PDF in Preview/Acrobat, Cmd-A → Cmd-C → paste the text "
                    "into chat. For pasted text, route to "
                    "`/import-requirements` (single-artifact) or "
                    "`/import-work-item` with the `content` argument "
                    "(multi-artifact)."
                ))]

            if not os.path.exists(file_path):
                return [TextContent(type="text", text=(
                    f"Error: File not found: {file_path}\n\n"
                    f"**Likely causes & fixes:**\n"
                    f"- Path is relative — pass an absolute path "
                    f"(e.g. `/Users/<you>/Downloads/file.pdf`).\n"
                    f"- Tilde wasn't expanded — replace `~/` with the full "
                    f"home dir.\n"
                    f"- Bob's chat shows a PDF attachment but the actual "
                    f"file isn't on disk — Bob's UI doesn't auto-save "
                    f"attachments. Ask the user to save the PDF to disk "
                    f"and share the path.\n"
                    f"- File doesn't exist — confirm with `ls` or have the "
                    f"user double-check.\n\n"
                    f"**Paste workaround:** if the path is broken or Bob "
                    f"can't see the file at all, ask the user to copy-"
                    f"paste the PDF's text into chat. `/import-requirements` "
                    f"and `/import-work-item` both accept pasted content "
                    f"directly."
                ))]

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
                        "The PDF may be image-only (scanned without OCR). "
                        "Workaround: if the user can see the PDF content "
                        "themselves, ask them to copy-paste the text into "
                        "chat — `/import-requirements` and `/import-work-item` "
                        "both accept pasted content directly."
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
        # save_requirements handler removed in v0.5.0


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

            # Build response. CRITICAL: when bind fails, the warning
            # must be the FIRST thing the AI sees — not buried at the
            # bottom under 35 success lines. Same for the "no module"
            # case. Anything else is too easy for the AI to skim past.
            bind_failed = bool(module and bind_status and 'error' in bind_status)
            no_module = (not module)

            lines: list[str] = []

            # ── HALT-LEVEL HEADER (when something went wrong) ──────
            if bind_failed:
                lines.append(
                    f"# 🛑 PHASE INCOMPLETE — MODULE BIND FAILED\n"
                )
                lines.append(
                    f"**{len(created)} requirements were created in folder "
                    f"`{folder_name}`, but they are NOT IN ANY MODULE.** Bind "
                    f"to module `{module['title']}` failed:\n\n"
                    f"```\n{bind_status['error']}\n```\n"
                )
                lines.append(
                    f"## ⛔ DO NOT ADVANCE THE BUILD FLOW\n\n"
                    f"If this is part of a `/build-new-project` or "
                    f"`/build-from-existing` run, **DO NOT call "
                    f"`build_project_next(current_phase=2, ...)`** until "
                    f"the bind is resolved. Phase 5 (user review in ELM) and "
                    f"Phase 6 (drift detection) both depend on the reqs "
                    f"being in the module — proceeding now silently breaks "
                    f"the rest of the flow.\n\n"
                    f"## Recovery options (in order)\n\n"
                    f"1. **Retry the bind:** call `add_to_module("
                    f"module_url=\"{module['url']}\", "
                    f"requirement_urls=[<the URLs below>])`. If it "
                    f"succeeds, proceed.\n"
                    f"2. **If `add_to_module` errors with a config-management "
                    f"or `PHASE_GATE` issue:** this project doesn't have "
                    f"DNG configuration management enabled, so the Module "
                    f"Structure API isn't available. Tell the user: *'Your "
                    f"DNG project doesn't support programmatic module "
                    f"binding. Either (a) ask your DNG admin to enable "
                    f"configuration management on this project, or (b) "
                    f"open the module link below in DNG, drag the 35 "
                    f"requirements into it manually, then come back and "
                    f"say continue.'*\n"
                    f"3. **Module link to open in DNG for manual binding:** "
                    f"[{module['title']}]({module['url']})\n"
                )

            elif no_module:
                lines.append(
                    f"# ⚠️ REQUIREMENTS CREATED WITHOUT A MODULE\n"
                )
                lines.append(
                    f"**{len(created)} requirements were created in folder "
                    f"`{folder_name}`, but the caller did NOT pass "
                    f"`module_name`** — so they are loose-folder artifacts, "
                    f"not visible from any module view in DNG.\n\n"
                    f"## Was this intentional?\n\n"
                    f"In 95% of cases the answer is no — the user wanted "
                    f"these in a module. **Recommended action: ask the "
                    f"user *'Should I bind these {len(created)} "
                    f"requirements to a module? If yes, what should the "
                    f"module be called?'* and then call `add_to_module` "
                    f"with the URLs below.**\n\n"
                    f"If the user really did want loose-folder reqs (rare; "
                    f"e.g. they're appending to an existing module manually "
                    f"in DNG), then proceed without binding.\n"
                )

            else:
                # Happy path
                lines.append(f"# Requirements Created in '{project['title']}'\n")
                lines.append(f"**Module:** [{module['title']}]({module['url']})  ")
                lines.append(f"  ↳ open this link in your browser to see the module with all its bindings.\n")
                added = bind_status.get('added', 0) if bind_status else 0
                lines.append(
                    f"**Bound to module:** {added} requirement(s) added.\n"
                )

            # ── Common: the actual list of URLs (always present so
            #    recovery / handoff can use them) ──────────────────
            lines.append(f"**Folder:** {folder_name}")
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

            lines.append(
                "\n---\n"
                "**Surface ALL of the links above to the user as markdown links** — "
                "do NOT paraphrase to a generic '/rm' landing page URL. Each link "
                "above goes directly to the specific artifact."
            )

            # Mark the active run state so build_project_next can refuse
            # to advance past Phase 2 when bind failed.
            if bind_failed or no_module:
                for run in _RUNS.values():
                    if run.get("current_phase", 0) == 2:
                        run["phase_2_bind_failed"] = True
                        run["last_bind_failure"] = (
                            bind_status.get('error', '') if bind_status
                            else 'no module_name passed; reqs are loose'
                        )
                        _persist_run(run)
                        break

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

        # ── create_tasks (BATCH version) ───────────────────────
        elif name == "create_tasks":
            ewm_proj = arguments.get("ewm_project", "")
            tasks_data = arguments.get("tasks", []) or []
            if not ewm_proj or not tasks_data:
                return [TextContent(type="text", text=(
                    "Error: ewm_project and tasks (non-empty list) are required."
                ))]
            if not _ewm_projects_cache:
                _ewm_projects_cache = client.list_ewm_projects()
            project = _find_by_identifier(_ewm_projects_cache, ewm_proj)
            if not project:
                return [TextContent(type="text", text=(
                    f"EWM project not found: '{ewm_proj}'."
                ))]

            created = []
            failed = []
            for t in tasks_data:
                t_title = (t.get("title") or "").strip()
                if not t_title:
                    failed.append({"title": "(no title)", "error": "missing title"})
                    continue
                t_desc = t.get("description") or ""
                t_req = t.get("requirement_url") or None
                result = client.create_ewm_task(
                    service_provider_url=project['url'],
                    title=t_title,
                    description=t_desc,
                    requirement_url=t_req,
                )
                if result and 'error' not in result:
                    created.append({
                        "title": result.get('title', t_title),
                        "url": result.get('url', ''),
                        "requirement_url": t_req or '',
                        "backlink_warning": result.get('backlink_warning', ''),
                    })
                else:
                    failed.append({
                        "title": t_title,
                        "error": result.get('error', 'unknown') if result else 'unknown',
                    })

            lines = [
                f"# Created {len(created)} of {len(tasks_data)} tasks in '{project['title']}'\n",
            ]
            if failed:
                lines.append(f"## ⚠️ {len(failed)} failed\n")
                for f in failed:
                    lines.append(f"- **{f['title']}** — {f['error']}")
                lines.append("")
            lines.append("## Created tasks\n")
            for c in created:
                req_note = (
                    f" → linked to {c['requirement_url']}"
                    if c['requirement_url'] else " (unlinked — no requirement_url provided)"
                )
                lines.append(f"- [{c['title']}]({c['url']}){req_note}")
                if c.get('backlink_warning'):
                    lines.append(f"  ⚠️ back-link warning: {c['backlink_warning']}")
            lines.append("")
            lines.append(
                "**Surface every URL above as a markdown link to the user.** "
                "If you're in build_project Phase 3, the run state has captured "
                "these URLs automatically; advance via build_project_next when "
                "the user confirms."
            )
            return [TextContent(type="text", text="\n".join(lines))]

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

        # ── create_test_cases (BATCH version) ─────────────────
        elif name == "create_test_cases":
            etm_proj = arguments.get("etm_project", "")
            cases_data = arguments.get("test_cases", []) or []
            if not etm_proj or not cases_data:
                return [TextContent(type="text", text=(
                    "Error: etm_project and test_cases (non-empty list) are required."
                ))]
            if not _etm_projects_cache:
                _etm_projects_cache = client.list_etm_projects()
            project = _find_by_identifier(_etm_projects_cache, etm_proj)
            if not project:
                return [TextContent(type="text", text=(
                    f"ETM project not found: '{etm_proj}'."
                ))]

            created = []
            failed = []
            for tc in cases_data:
                tc_title = (tc.get("title") or "").strip()
                if not tc_title:
                    failed.append({"title": "(no title)", "error": "missing title"})
                    continue
                tc_desc = tc.get("description") or ""
                tc_req = tc.get("requirement_url") or None
                result = client.create_test_case(
                    service_provider_url=project['url'],
                    title=tc_title,
                    description=tc_desc,
                    requirement_url=tc_req,
                )
                if result and 'error' not in result:
                    created.append({
                        "title": result.get('title', tc_title),
                        "url": result.get('url', ''),
                        "requirement_url": tc_req or '',
                        "backlink_warning": result.get('backlink_warning', ''),
                    })
                else:
                    failed.append({
                        "title": tc_title,
                        "error": result.get('error', 'unknown') if result else 'unknown',
                    })

            lines = [
                f"# Created {len(created)} of {len(cases_data)} test cases in '{project['title']}'\n",
            ]
            if failed:
                lines.append(f"## ⚠️ {len(failed)} failed\n")
                for f in failed:
                    lines.append(f"- **{f['title']}** — {f['error']}")
                lines.append("")
            lines.append("## Created test cases\n")
            for c in created:
                req_note = (
                    f" → validates {c['requirement_url']}"
                    if c['requirement_url'] else " (unlinked — no requirement_url provided)"
                )
                lines.append(f"- [{c['title']}]({c['url']}){req_note}")
                if c.get('backlink_warning'):
                    lines.append(f"  ⚠️ back-link warning: {c['backlink_warning']}")
            lines.append("")
            lines.append(
                "**Surface every URL above as a markdown link to the user.** "
                "If you're in build_project Phase 4, the run state has captured "
                "these URLs automatically; advance via build_project_next when "
                "the user confirms."
            )
            return [TextContent(type="text", text="\n".join(lines))]

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
        elif name == "resolve_requirement_id":
            proj_arg = arguments.get("project_identifier", "")
            req_id = arguments.get("requirement_id", "")
            if not proj_arg or not req_id:
                return [TextContent(type="text", text="Error: project_identifier and requirement_id are required.")]
            if not _projects_cache:
                _projects_cache = client.list_projects()
            project = _find_by_identifier(_projects_cache, proj_arg)
            if not project:
                return [TextContent(type="text", text=f"Project not found: '{proj_arg}'")]
            project_url = project.get('services_url') or project.get('url', '')
            result = client.resolve_requirement_id(project_url, req_id)
            if result:
                return [TextContent(type="text", text=(
                    f"# Requirement {result.get('id', req_id)}\n\n"
                    f"**Title:** {result.get('title', '?')}\n"
                    f"**URL:** [{result.get('url', '')}]({result.get('url', '')})\n"
                    f"**Project:** {project.get('title', '?')}\n\n"
                    f"Use this URL in any subsequent tool that needs a "
                    f"`requirement_url` argument."
                ))]
            return [TextContent(type="text", text=(
                f"No requirement with id '{req_id}' found in project "
                f"'{project.get('title', proj_arg)}'. Try without the "
                f"prefix, or check spelling."
            ))]

        elif name == "resolve_user":
            ident = arguments.get("identifier", "").strip()
            if not ident:
                return [TextContent(type="text", text="Error: identifier is required.")]
            result = client.resolve_user(ident)
            if result:
                return [TextContent(type="text", text=(
                    f"# User\n\n"
                    f"- **Name:** {result.get('name', '?')}\n"
                    f"- **Username:** {result.get('username', '?')}\n"
                    f"- **URI:** {result.get('uri', '')}\n"
                    f"- **Email:** {result.get('email', '_(not exposed)_')}\n"
                ))]
            return [TextContent(type="text", text=(
                f"No user matching '{ident}' found. Tried both display "
                f"name and username queries against the JTS user "
                f"catalog. The user may not exist in this Jazz install."
            ))]

        elif name == "list_test_cases":
            etm_proj = arguments.get("etm_project", "").strip()
            where = arguments.get("where", "").strip() or None
            max_results = int(arguments.get("max_results", 50) or 50)
            etm_projects = client.list_etm_projects()
            etm_match = _find_by_identifier(etm_projects, etm_proj)
            if not etm_match:
                return [TextContent(type="text",
                    text=f"ETM project not found: {etm_proj}.")]
            tcs = client.list_test_cases(etm_match['url'], where, max_results)
            if not tcs:
                return [TextContent(type="text", text=(
                    f"No test cases in ETM project '{etm_match['title']}'"
                    + (f" matching `{where}`" if where else "") + "."
                ))]
            lines = [f"# Test Cases in {etm_match['title']}", "",
                     f"**{len(tcs)} test case(s)**" + (f" (filter: `{where}`)" if where else ""), ""]
            for tc in tcs:
                lines.append(f"- **{tc.get('identifier', '?')}** — [{tc.get('title', '?')}]({tc.get('url', '')})")
                if tc.get('state'):
                    lines.append(f"  - state: {tc['state']}")
            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "list_test_plans":
            etm_proj = arguments.get("etm_project", "").strip()
            where = arguments.get("where", "").strip() or None
            max_results = int(arguments.get("max_results", 50) or 50)
            etm_projects = client.list_etm_projects()
            etm_match = _find_by_identifier(etm_projects, etm_proj)
            if not etm_match:
                return [TextContent(type="text",
                    text=f"ETM project not found: {etm_proj}.")]
            plans = client.list_test_plans(etm_match['url'], where, max_results)
            if not plans:
                return [TextContent(type="text", text=(
                    f"No test plans in ETM project '{etm_match['title']}'."
                ))]
            lines = [f"# Test Plans in {etm_match['title']}", "",
                     f"**{len(plans)} test plan(s)**", ""]
            for p in plans:
                lines.append(f"- **{p.get('identifier', '?')}** — [{p.get('title', '?')}]({p.get('url', '')})")
            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "list_test_execution_records":
            etm_proj = arguments.get("etm_project", "").strip()
            where = arguments.get("where", "").strip() or None
            max_results = int(arguments.get("max_results", 50) or 50)
            etm_projects = client.list_etm_projects()
            etm_match = _find_by_identifier(etm_projects, etm_proj)
            if not etm_match:
                return [TextContent(type="text",
                    text=f"ETM project not found: {etm_proj}.")]
            ters = client.list_test_execution_records(etm_match['url'], where, max_results)
            if not ters:
                return [TextContent(type="text", text=(
                    f"No test execution records in ETM project "
                    f"'{etm_match['title']}'."
                ))]
            lines = [f"# Test Execution Records in {etm_match['title']}", "",
                     f"**{len(ters)} TER(s)**", ""]
            for t in ters:
                lines.append(f"- **{t.get('identifier', '?')}** — [{t.get('title', '?')}]({t.get('url', '')})")
            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "create_test_plan":
            etm_proj = arguments.get("etm_project", "").strip()
            title = arguments.get("title", "").strip()
            description = arguments.get("description", "").strip()
            if not etm_proj or not title:
                return [TextContent(type="text", text="Error: etm_project and title are required.")]
            etm_projects = client.list_etm_projects()
            etm_match = _find_by_identifier(etm_projects, etm_proj)
            if not etm_match:
                return [TextContent(type="text", text=f"ETM project not found: {etm_proj}.")]
            result = client.create_test_plan(etm_match['url'], title, description)
            if result and 'error' not in result:
                return [TextContent(type="text", text=(
                    f"# Test Plan Created\n\n"
                    f"**Click to open:** [{result['title']}]({result['url']})"
                ))]
            err = result.get('error', 'unknown') if result else 'unknown'
            return [TextContent(type="text", text=f"Error: failed to create test plan — {err}")]

        elif name == "create_test_execution_record":
            etm_proj = arguments.get("etm_project", "").strip()
            title = arguments.get("title", "").strip()
            tc_url = arguments.get("test_case_url", "").strip()
            description = arguments.get("description", "").strip()
            if not etm_proj or not title or not tc_url:
                return [TextContent(type="text", text="Error: etm_project, title, and test_case_url are required.")]
            etm_projects = client.list_etm_projects()
            etm_match = _find_by_identifier(etm_projects, etm_proj)
            if not etm_match:
                return [TextContent(type="text", text=f"ETM project not found: {etm_proj}.")]
            result = client.create_test_execution_record(etm_match['url'], title, tc_url, description)
            if result and 'error' not in result:
                return [TextContent(type="text", text=(
                    f"# Test Execution Record Created\n\n"
                    f"**Click to open:** [{result['title']}]({result['url']})\n"
                    f"**Runs test case:** {tc_url}\n\n"
                    f"Pair with `create_test_result` to record pass/fail."
                ))]
            err = result.get('error', 'unknown') if result else 'unknown'
            return [TextContent(type="text", text=f"Error: failed to create TER — {err}")]

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

        # ── Jira (direct REST) — these don't need ELM connection ─
        elif name in ("get_jira_issue", "search_jira_issues",
                       "add_jira_comment", "add_jira_remote_link",
                       "jira_health"):
            try:
                from jira_client import JiraClient
                jira = JiraClient()
            except RuntimeError as e:
                return [TextContent(type="text", text=(
                    f"Jira is not configured.\n\n{e}\n\n"
                    "Quick fix: edit `~/.elm-mcp/.env` and add:\n"
                    "```\n"
                    "JIRA_BASE_URL=https://yourorg.atlassian.net\n"
                    "JIRA_EMAIL=your-email@example.com\n"
                    "JIRA_API_TOKEN=ATATT...\n"
                    "```\n"
                    "Get a token: "
                    "https://id.atlassian.com/manage-profile/security/api-tokens\n\n"
                    "Or run: python3 ~/.elm-mcp/setup.py --with-jira\n\n"
                    "Then restart your AI host (Cmd+Q + reopen)."
                ))]
            except Exception as e:
                return [TextContent(type="text", text=(
                    f"Failed to initialize Jira client: {e}"
                ))]

            try:
                if name == "get_jira_issue":
                    key = arguments.get("issue_key", "").strip()
                    if not key:
                        return [TextContent(type="text", text=(
                            "Error: issue_key is required."
                        ))]
                    issue = jira.get_issue(key)
                    lines = [
                        f"# {issue['key']} — {issue['summary']}",
                        "",
                        f"**URL:** {issue['url']}",
                        f"**Type:** {issue['type'] or 'n/a'}    "
                        f"**Status:** {issue['status'] or 'n/a'}    "
                        f"**Priority:** {issue['priority'] or 'n/a'}",
                        f"**Assignee:** {issue['assignee'] or 'unassigned'}    "
                        f"**Reporter:** {issue['reporter'] or 'n/a'}",
                        f"**Created:** {issue['created'] or 'n/a'}    "
                        f"**Updated:** {issue['updated'] or 'n/a'}",
                    ]
                    if issue.get('labels'):
                        lines.append(f"**Labels:** {', '.join(issue['labels'])}")
                    if issue.get('parent'):
                        p_ = issue['parent']
                        lines.append(
                            f"**Parent:** [{p_['key']}: {p_['summary']}]"
                            f"({jira.base_url}/browse/{p_['key']}) "
                            f"({p_.get('type', '')} / {p_.get('status', '')})"
                        )
                    if issue.get('subtasks'):
                        lines.append(f"**Subtasks ({len(issue['subtasks'])}):**")
                        for st in issue['subtasks']:
                            lines.append(
                                f"  - [{st['key']}: {st['summary']}]"
                                f"({jira.base_url}/browse/{st['key']}) "
                                f"({st.get('status', '')})"
                            )
                    lines += ["", "## Description", "",
                              issue.get('description') or "_(empty)_"]
                    if issue.get('comments_preview'):
                        lines += ["", f"## Last {len(issue['comments_preview'])} "
                                       f"comments (of {issue.get('comments_count', 0)})",
                                  ""]
                        for c in issue['comments_preview']:
                            lines.append(f"**{c['author']}** — {c['created']}")
                            lines.append("")
                            lines.append((c.get('body') or '').rstrip())
                            lines.append("")
                    elif issue.get('comments_count', 0):
                        lines += ["", f"_({issue['comments_count']} comments — "
                                       f"not previewed)_"]
                    return [TextContent(type="text", text="\n".join(lines))]

                if name == "search_jira_issues":
                    jql = arguments.get("jql", "").strip()
                    max_results = arguments.get("max_results", 25)
                    if not jql:
                        return [TextContent(type="text", text="Error: jql is required.")]
                    issues = jira.search_issues(jql, max_results=max_results)
                    if not issues:
                        return [TextContent(type="text", text=f"No issues match JQL: `{jql}`")]
                    lines = [f"# Jira Search Results ({len(issues)} issues)", "",
                             f"_JQL:_ `{jql}`", ""]
                    for it in issues:
                        lines.append(
                            f"- [`{it['key']}`]({it['url']}) **{it['summary']}** "
                            f"— {it.get('type', '')} / {it.get('status', '')} / "
                            f"{it.get('assignee') or 'unassigned'}"
                        )
                    return [TextContent(type="text", text="\n".join(lines))]

                if name == "add_jira_comment":
                    key = arguments.get("issue_key", "").strip()
                    body = arguments.get("body", "")
                    if not key or not body:
                        return [TextContent(type="text", text=(
                            "Error: issue_key and body are required."
                        ))]
                    result = jira.add_comment(key, body)
                    return [TextContent(type="text", text=(
                        f"✅ Posted comment on {jira._normalize_key(key)}.\n\n"
                        f"**Comment URL:** {result['url']}"
                    ))]

                if name == "add_jira_remote_link":
                    key = arguments.get("issue_key", "").strip()
                    target = arguments.get("url", "").strip()
                    title = arguments.get("title", "").strip()
                    summary = arguments.get("summary", "").strip() or None
                    if not (key and target and title):
                        return [TextContent(type="text", text=(
                            "Error: issue_key, url, and title are required."
                        ))]
                    jira.add_remote_link(key, target, title, summary=summary)
                    return [TextContent(type="text", text=(
                        f"✅ Added remote link on {jira._normalize_key(key)}:\n"
                        f"  - **{title}** → {target}\n\n"
                        f"Renders in the Jira issue's 'Links' panel."
                    ))]

                if name == "jira_health":
                    profile = jira.whoami()
                    return [TextContent(type="text", text=(
                        f"# Jira — Health Check\n\n"
                        f"✅ Connected.\n\n"
                        f"- **Base URL:** {profile['base_url']}\n"
                        f"- **Authenticated as:** "
                        f"{profile.get('displayName') or 'n/a'} "
                        f"({profile.get('emailAddress') or 'n/a'})\n"
                        f"- **Account ID:** {profile.get('accountId') or 'n/a'}\n"
                    ))]
            except RuntimeError as e:
                return [TextContent(type="text", text=f"Jira error: {e}")]
            except Exception as e:
                return [TextContent(type="text",
                                     text=f"Unexpected Jira error: {e}")]

        # ── Requirements Quality (deterministic lint + audit) ─
        elif name in ("lint_requirement_text",
                       "lint_requirements_batch",
                       "coach_requirement"):
            try:
                from req_quality import (lint_and_score, batch_lint,
                                          audit_summary, format_findings,
                                          Finding)
            except Exception as e:
                return [TextContent(type="text",
                                     text=f"Failed to load req_quality: {e}")]

            if name == "lint_requirement_text":
                text = arguments.get("text", "").strip()
                if not text:
                    return [TextContent(type="text",
                                         text="Error: text is required.")]
                r = lint_and_score(text)
                findings = [Finding(**f) for f in r["findings"]]
                lines = [
                    f"# Requirement Quality Lint",
                    "",
                    f"**Score:** {r['score']}/100 ({r['bucket']})",
                    "",
                    f"**Text:** _{text[:200]}{'...' if len(text)>200 else ''}_",
                    "",
                    "## Findings",
                    "",
                    format_findings(findings),
                ]
                signals = r.get("signals", {})
                pos = [k.replace("has_", "").replace("_", " ")
                       for k, v in signals.items() if v]
                if pos:
                    lines.append("**Positive signals:** " + ", ".join(pos))
                    lines.append("")
                lines.append("---")
                lines.append("")
                lines.append("For AI-powered rewrite suggestions and "
                             "semantic scoring beyond pattern matching, "
                             "open this requirement in the **Requirements "
                             "Quality Assistant** agent in IBM ELM AI Hub.")
                return [TextContent(type="text", text="\n".join(lines))]

            if name == "lint_requirements_batch":
                items = arguments.get("items", []) or []
                if not items:
                    return [TextContent(type="text",
                                         text="Error: items array is required."
                                         )]
                results = batch_lint(items)
                summary = audit_summary(results)
                # Also include per-req findings for the LLM to surface
                per_req_lines = ["", "## Per-requirement findings", ""]
                for r in results:
                    title = (r.get("title") or "(no title)")[:80]
                    per_req_lines.append(
                        f"### {r['score']}/100 — {title}"
                    )
                    findings = [Finding(**f) for f in r["findings"]]
                    per_req_lines.append(format_findings(findings, indent=""))
                return [TextContent(type="text",
                                     text=summary + "\n".join(per_req_lines))]

            if name == "coach_requirement":
                text = arguments.get("text", "").strip()
                context = arguments.get("context", "").strip()
                if not text:
                    return [TextContent(type="text",
                                         text="Error: text is required.")]
                r = lint_and_score(text)
                findings = [Finding(**f) for f in r["findings"]]
                lines = [
                    "# Requirement Coaching",
                    "",
                    f"**Score:** {r['score']}/100 ({r['bucket']})",
                    "",
                ]
                if context:
                    lines += [f"**Context:** {context}", ""]
                lines += [
                    "## Deterministic findings (INCOSE GtWR + IEEE 29148)",
                    "",
                    format_findings(findings),
                    "",
                    "## For AI-powered rewrites — open Requirements Quality Assistant",
                    "",
                    "The deterministic checks above catch syntactic smells. "
                    "For semantic rewriting — restructuring intent, "
                    "tightening ambiguity, generating 2-3 candidate "
                    "rewrites you can pick from — open this requirement "
                    "in the **Requirements Quality Assistant** agent in "
                    "IBM ELM AI Hub. That's the AI tier; this is the "
                    "deterministic floor.",
                ]
                return [TextContent(type="text", text="\n".join(lines))]

        elif name == "export_module_to_xlsx":
            try:
                from xlsx_export import export_artifacts_to_xlsx
            except Exception as e:
                return [TextContent(type="text", text=(
                    f"Failed to load xlsx_export: {e}. "
                    "Install openpyxl: `pip install openpyxl>=3.1.0` "
                    "(it's in requirements.txt)."
                ))]
            if not client:
                return [TextContent(type="text", text=(
                    "Not connected to ELM. Call `connect_to_elm` first."
                ))]

            proj_id = (arguments.get("project_identifier") or "").strip()
            if not proj_id:
                return [TextContent(type="text",
                                     text="Error: project_identifier is required.")]

            if not _projects_cache:
                _projects_cache = client.list_projects()
            project = _find_by_identifier(_projects_cache, proj_id)
            if not project:
                return [TextContent(type="text",
                                     text=f"DNG project not found: '{proj_id}'")]

            project_key = project["id"]
            if project_key not in _modules_cache:
                _modules_cache[project_key] = client.get_modules(project["url"])
            all_modules = _modules_cache.get(project_key, [])
            if not all_modules:
                return [TextContent(type="text", text=(
                    f"No modules found in '{project['title']}'."
                ))]

            requested = arguments.get("module_identifiers") or []
            if requested:
                selected = []
                missing = []
                for ident in requested:
                    m = _find_by_identifier(all_modules, str(ident).strip())
                    if m:
                        if m not in selected:
                            selected.append(m)
                    else:
                        missing.append(str(ident))
                if missing:
                    names = "\n".join(f"  {i}. {m['title']}"
                                       for i, m in enumerate(all_modules, 1))
                    return [TextContent(type="text", text=(
                        f"Could not resolve module(s): {', '.join(missing)}.\n\n"
                        f"Available modules in '{project['title']}':\n{names}"
                    ))]
            else:
                selected = list(all_modules)

            columns = arguments.get("columns") or None
            combined = bool(arguments.get("combined_sheet"))

            modules_payload = []
            empty_modules = []
            for mod in selected:
                try:
                    reqs = client.get_module_requirements(mod["url"]) or []
                except Exception as e:
                    return [TextContent(type="text", text=(
                        f"Failed to fetch requirements from module "
                        f"'{mod.get('title')}': {e}"
                    ))]
                modules_payload.append({"name": mod.get("title") or "(untitled)",
                                          "requirements": reqs})
                if not reqs:
                    empty_modules.append(mod.get("title") or "(untitled)")

            if not any(m["requirements"] for m in modules_payload):
                return [TextContent(type="text", text=(
                    "No requirements found in the selected module(s) — "
                    "nothing to export."
                ))]

            try:
                path = export_artifacts_to_xlsx(
                    modules_payload,
                    project_name=project["title"],
                    columns=columns,
                    combined=combined,
                )
            except Exception as e:
                return [TextContent(type="text",
                                     text=f"export_module_to_xlsx failed: {e}")]

            size_kb = path.stat().st_size / 1024
            total_reqs = sum(len(m["requirements"]) for m in modules_payload)
            sheets_note = ("one combined sheet with a Module column"
                            if combined else
                            f"{len(modules_payload)} sheet(s) + a Summary tab")
            empty_note = ""
            if empty_modules:
                empty_note = ("\n_Note: these modules were empty and produced "
                                f"no rows: {', '.join(empty_modules)}._")

            return [TextContent(type="text", text=(
                f"✓ Exported {total_reqs} requirement(s) across "
                f"{len(modules_payload)} module(s) to Excel.\n\n"
                f"**File:** `{path}`\n"
                f"**Size:** {size_kb:.1f} KB · {sheets_note}\n\n"
                f"**Open it:** `open '{path}'` (macOS) — or double-click.\n\n"
                f"Header row is frozen, auto-filter is on, columns are "
                f"auto-sized. Ready to share."
                f"{empty_note}"
            ))]

        elif name in ("generate_trace_report", "generate_audit_report"):
            try:
                from html_report import (render_trace_report,
                                          render_audit_report, write_report)
            except Exception as e:
                return [TextContent(type="text",
                                     text=f"Failed to load html_report: {e}")]

            if name == "generate_trace_report":
                items = arguments.get("items", []) or []
                project = (arguments.get("project") or "").strip()
                module = (arguments.get("module") or "").strip()
                if not items:
                    return [TextContent(type="text", text=(
                        "Error: items array is required — assemble per-req "
                        "trace data first (req_key, req_title, req_url, "
                        "tasks=[...], tests=[...])."
                    ))]
                try:
                    html = render_trace_report(
                        items, project=project, module=module,
                        version=__version__,
                    )
                    path = write_report(html, kind="trace",
                                         project=project, module=module)
                except Exception as e:
                    return [TextContent(type="text",
                                         text=f"generate_trace_report failed: {e}")]
                size_mb = path.stat().st_size / (1024 * 1024)
                return [TextContent(type="text", text=(
                    f"✓ Traceability report generated.\n\n"
                    f"**File:** `{path}`\n"
                    f"**Size:** {size_mb:.2f} MB (self-contained, "
                    f"air-gap safe)\n\n"
                    f"**Open it:** `open '{path}'` (macOS) — or "
                    f"double-click the file.\n\n"
                    f"The report includes: coverage stats, an "
                    f"interactive trace graph where every node is "
                    f"clickable (opens DNG / EWM / ETM in a new tab), "
                    f"a coverage distribution doughnut, and a gap "
                    f"detail table. Same modern visual style every "
                    f"time — share by emailing the file, dropping "
                    f"into Confluence, or attaching to a review.\n\n"
                    f"_For AI-powered semantic scoring on the same "
                    f"requirements, open them in the **Requirements "
                    f"Quality Assistant** agent in IBM ELM AI Hub. "
                    f"This report is the deterministic floor._"
                ))]

            if name == "generate_audit_report":
                audit = arguments.get("audit", {}) or {}
                project = (arguments.get("project") or "").strip()
                module = (arguments.get("module") or "").strip()
                if not audit:
                    return [TextContent(type="text", text=(
                        "Error: audit summary is required — pass the "
                        "audit_module output's bucket counts + worst "
                        "list + rule_counts."
                    ))]
                try:
                    html = render_audit_report(
                        audit, project=project, module=module,
                        version=__version__,
                    )
                    path = write_report(html, kind="audit",
                                         project=project, module=module)
                except Exception as e:
                    return [TextContent(type="text",
                                         text=f"generate_audit_report failed: {e}")]
                size_mb = path.stat().st_size / (1024 * 1024)
                return [TextContent(type="text", text=(
                    f"✓ Quality audit report generated.\n\n"
                    f"**File:** `{path}`\n"
                    f"**Size:** {size_mb:.2f} MB\n\n"
                    f"**Open it:** `open '{path}'` (macOS) — or "
                    f"double-click.\n\n"
                    f"Includes stat cards, quality-distribution "
                    f"doughnut, lowest-scoring requirements (each "
                    f"clickable to DNG), and most-violated INCOSE/IEEE "
                    f"rules.\n\n"
                    f"_Open these same requirements in the **Requirements "
                    f"Quality Assistant** agent in IBM ELM AI Hub for "
                    f"AI-powered rewrite suggestions and semantic scoring._"
                ))]

        elif name == "audit_module":
            try:
                from req_quality import batch_lint, audit_summary
            except Exception as e:
                return [TextContent(type="text",
                                     text=f"Failed to load req_quality: {e}")]
            if not client:
                return [TextContent(type="text", text=(
                    "Not connected to ELM. Call `connect_to_elm` first."
                ))]
            proj_id = arguments.get("project_identifier", "").strip()
            mod_id = arguments.get("module_identifier", "").strip()
            if not (proj_id and mod_id):
                return [TextContent(type="text", text=(
                    "Error: project_identifier and module_identifier "
                    "are required."
                ))]
            try:
                if not _projects_cache:
                    _projects_cache = client.list_projects()
                project = _find_by_identifier(_projects_cache, proj_id)
                if not project:
                    return [TextContent(type="text",
                                         text=f"DNG project not found: '{proj_id}'")]

                # Resolve module
                modules = client.list_modules(project['url'])
                module = _find_by_identifier(modules, mod_id)
                if not module:
                    return [TextContent(type="text",
                                         text=f"Module not found in '{project['title']}': '{mod_id}'")]

                # Fetch reqs in module
                reqs = client.get_module_requirements(module['url'])
            except Exception as e:
                return [TextContent(type="text",
                                     text=f"Failed to fetch module reqs: {e}"
                                     )]

            if not reqs:
                return [TextContent(type="text", text=(
                    f"No requirements found in module '{module.get('title', mod_id)}'."
                ))]

            # Lint each requirement's text
            items = []
            statuses = {}
            no_owner = 0
            for r in reqs:
                # The req may carry 'content' (primary text) or 'description'
                text = r.get("content") or r.get("description") or r.get("title") or ""
                items.append({
                    "title": r.get("title", ""),
                    "text": text,
                    "url": r.get("url", ""),
                })
                status = (r.get("status")
                          or (r.get("custom_attributes") or {}).get("Accepted")
                          or "Unknown")
                statuses[status] = statuses.get(status, 0) + 1
                # Owner heuristic — check common owner field names
                owner = (r.get("owner")
                         or (r.get("custom_attributes") or {}).get("Owner")
                         or "")
                if not owner:
                    no_owner += 1

            results = batch_lint(items)
            summary = audit_summary(results)

            # Status block
            n = len(reqs)
            approved = statuses.get("Approved", 0)
            status_pct = (approved / n * 100) if n else 0
            status_lines = [
                "## Status & Attribute Completeness",
                "",
                f"- **Total requirements:** {n}",
                f"- **Approved:** {approved} ({status_pct:.0f}%)",
                "- **Status breakdown:** " +
                ", ".join(f"{k}: {v}" for k, v in sorted(statuses.items())),
                f"- **Missing owner:** {no_owner}",
                "",
            ]
            if status_pct < 80:
                status_lines.append(
                    f"⚠️ **Status warning:** Only {status_pct:.0f}% of "
                    f"requirements are Approved. Downstream work (tasks, "
                    f"test cases) generated from non-Approved requirements "
                    f"may need rework when reqs change. Have a domain "
                    f"expert review before proceeding."
                )
                status_lines.append("")

            header = [
                f"# Module Audit — {module.get('title', mod_id)}",
                "",
                f"**Project:** {project.get('title', proj_id)}",
                f"**Module URL:** {module.get('url', 'n/a')}",
                "",
            ]
            return [TextContent(type="text", text="\n".join(header)
                                + "\n".join(status_lines) + summary)]

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
    logger.info(f"IBM ELM MCP Server v{__version__} starting (62 tools, 10 prompts, 3 resource templates)")
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
