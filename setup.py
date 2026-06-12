#!/usr/bin/env python3
"""
DOORS Next AI Agent — One-command setup

Run:  python3 setup.py
      python3 setup.py --diagnose   (smoke-test only, writes no config)

What it does:
  1. Installs Python dependencies into the chosen interpreter
  2. Validates the chosen interpreter actually has those deps importable
  3. Detects which AI assistants you have (Claude Code, VS Code, Cursor, Windsurf)
     and writes the MCP server config for each one it finds, using each host's
     CURRENT documented schema (URLs cited near each writer)
  4. Creates .env from .env.example if missing, prompts for ELM credentials
  5. Runs a real MCP smoke test: launches doors_mcp_server.py over stdio,
     does the MCP `initialize` handshake, calls `tools/list`, confirms >=1 tool

Re-run any time — it's idempotent. Existing config entries are preserved/updated.

Exit codes:
  0  everything worked, server smoke-test passed
  1  setup failed (no host detected, smoke test failed, auth failed, etc.)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from getpass import getpass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV_FILE = HERE / ".env"
ENV_EXAMPLE = HERE / ".env.example"
REQUIREMENTS = HERE / "requirements.txt"
SERVER_SCRIPT = "doors_mcp_server.py"

# Importable deps the server needs at runtime. Every Python interpreter we
# write into a host config MUST be able to import all of these. If it can't,
# the server will crash on startup and the host shows "MCP server failed"
# with no useful detail. Validate before writing.
REQUIRED_IMPORTS = ("mcp", "requests", "dotenv", "fitz", "matplotlib")

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def step(n: int, total: int, msg: str) -> None:
    print(f"\n{BOLD}[{n}/{total}] {msg}{RESET}")


def ok(msg: str) -> None:
    print(f"  {GREEN}OK{RESET}  {msg}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}!!{RESET}  {msg}")


def fail(msg: str) -> None:
    print(f"  {RED}xx{RESET}  {msg}")


def info(msg: str) -> None:
    print(f"      {DIM}{msg}{RESET}")


# ── Interpreter selection ───────────────────────────────────
#
# Why this is hard: the user runs `python3 setup.py`. That `python3` may be:
#   (a) /usr/bin/python3            — system Python
#   (b) /opt/homebrew/bin/python3   — Homebrew
#   (c) /opt/anaconda3/bin/python3  — Anaconda
#   (d) a venv at /path/to/.venv/bin/python3
#
# When the IDE later launches the MCP server, it does NOT know about (d) —
# venvs aren't activated in the IDE's spawned subprocess. If we write
# sys.executable=(d) into the host config, the host runs the venv python and
# that may fail if the IDE was launched from a shell where the venv isn't on
# PATH. That said, an absolute path to a venv interpreter DOES still work
# even without activation, because the python binary itself knows how to
# locate site-packages relative to its own location.
#
# Our rule: **use the same interpreter the user invoked** (sys.executable),
# always as an absolute path, and verify it has all REQUIRED_IMPORTS. If it
# doesn't, install them into that interpreter. If the interpreter is in a
# venv, print a warning so the user knows the IDE will need that venv to
# survive.

def interpreter_in_venv(py_exe: str) -> bool:
    """Heuristic: is this Python a virtual environment?"""
    try:
        out = subprocess.run(
            [py_exe, "-c",
             "import sys; print(int(sys.prefix != sys.base_prefix))"],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() == "1"
    except Exception:
        return False


def interpreter_can_import(py_exe: str, modules: tuple[str, ...]) -> tuple[bool, list[str]]:
    """Return (all_ok, missing_modules) for the given python exe."""
    code = (
        "import importlib, sys\n"
        f"missing=[]\n"
        f"for m in {list(modules)!r}:\n"
        "    try: importlib.import_module(m)\n"
        "    except Exception: missing.append(m)\n"
        "print('|'.join(missing))\n"
    )
    try:
        out = subprocess.run(
            [py_exe, "-c", code], capture_output=True, text=True, timeout=15
        )
    except Exception as e:
        return False, list(modules)
    missing = [m for m in out.stdout.strip().split("|") if m]
    return (not missing), missing


# ── Step 1: dependencies ─────────────────────────────────────

def install_dependencies(py_exe: str) -> bool:
    if not REQUIREMENTS.exists():
        fail(f"Missing {REQUIREMENTS.name}")
        return False
    info(f"Running: {py_exe} -m pip install -r {REQUIREMENTS.name}")
    # No -q here: if pip fails we want the user to see exactly why.
    # Capture so we can replay both stdout and stderr together on failure.
    result = subprocess.run(
        [py_exe, "-m", "pip", "install", "-r", str(REQUIREMENTS)],
        cwd=HERE,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        fail("pip install failed.")
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return False
    ok("Dependencies installed")
    return True


# ── Step 2: IDE / MCP host detection + config ────────────────

def make_server_entry(py_exe: str, *, with_cwd: bool, include_type: bool) -> dict:
    """Build an MCP stdio entry. Hosts vary in supported fields:
       - cwd is supported by Claude Code (in practice) and Windsurf, NOT by
         VS Code's documented schema. When cwd is omitted, we pass the absolute
         path to doors_mcp_server.py as the args[0] so it runs from anywhere.
       - 'type': 'stdio' is required by VS Code, accepted by Cursor, ignored
         by Claude Code (which infers stdio from presence of `command`).
    """
    if with_cwd:
        entry = {
            "command": py_exe,
            "args": [SERVER_SCRIPT],
            "cwd": str(HERE),
        }
    else:
        # No cwd → use absolute path so the server file is found regardless
        # of where the host launches the process.
        entry = {
            "command": py_exe,
            "args": [str(HERE / SERVER_SCRIPT)],
        }
    if include_type:
        entry = {"type": "stdio", **entry}
    return entry


def merge_into(config_path: Path, root_key: str, server_name: str,
               entry: dict) -> str:
    """Merge a server entry into a host config file under root_key.

    Returns one of: "added", "updated", "exists", "error"
    """
    config_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if config_path.exists():
        try:
            text = config_path.read_text() or "{}"
            data = json.loads(text)
        except json.JSONDecodeError as e:
            fail(f"{config_path} is not valid JSON ({e}). Skipping.")
            return "error"
    servers = data.setdefault(root_key, {})
    if not isinstance(servers, dict):
        fail(f"{config_path} has a non-object '{root_key}'. Skipping.")
        return "error"

    existing = servers.get(server_name)
    if existing == entry:
        return "exists"
    status = "updated" if existing else "added"
    servers[server_name] = entry
    config_path.write_text(json.dumps(data, indent=2) + "\n")
    return status


# ── Per-host writers ────────────────────────────────────────────
#
# Each writer is a thin function that knows the host's documented config
# location, top-level key, and which schema variant of make_server_entry()
# applies. Schema URLs are cited at the function. The hosts are detected
# by looking for evidence of an install (a config dir, an Application
# bundle on macOS, or a CLI on PATH) — never by checking PATH alone, since
# none of these tools auto-add themselves to PATH on macOS.


def host_present_claude_code(home: Path) -> bool:
    # Claude.app on macOS, OR ~/.claude exists (CLI/desktop creates it),
    # OR ~/.claude.json exists (CLI scope storage).
    return (
        (home / ".claude").exists()
        or (home / ".claude.json").exists()
        or Path("/Applications/Claude.app").exists()
        or shutil.which("claude") is not None
    )


def host_present_vscode(home: Path) -> bool:
    return (
        Path("/Applications/Visual Studio Code.app").exists()
        or (home / "Library" / "Application Support" / "Code").exists()
        or shutil.which("code") is not None
    )


def host_present_cursor(home: Path) -> bool:
    return (
        Path("/Applications/Cursor.app").exists()
        or (home / ".cursor").exists()
        or shutil.which("cursor") is not None
    )


def host_present_windsurf(home: Path) -> bool:
    return (
        Path("/Applications/Windsurf.app").exists()
        or (home / ".codeium").exists()
        or shutil.which("windsurf") is not None
    )


def host_present_bob(home: Path) -> bool:
    """IBM Bob detection: ~/.bob exists (Bob creates it on first run), the
    Bob app bundle, or `bob` on PATH. Bob is also commonly run as a VS Code
    extension — in that case ~/.bob may exist alongside VS Code; we still
    write Bob's own .bob configs in addition to VS Code's mcp.json."""
    return (
        (home / ".bob").exists()
        or Path("/Applications/Bob.app").exists()
        or shutil.which("bob") is not None
        or shutil.which("bob-shell") is not None
    )


def write_claude_code(py_exe: str, home: Path) -> list[tuple[str, str, Path]]:
    """Claude Code stores MCP servers in TWO documented places:

    1) ~/.claude.json  (top-level "mcpServers", user scope) — the actual file
       the `claude mcp add --scope user` CLI writes to.
    2) <project>/.mcp.json  (project scope, checked into git, top-level
       "mcpServers") — what `claude mcp add --scope project` writes.

    We write to BOTH so the user gets the server regardless of how Claude
    Code is launched (anywhere, or specifically from this project dir).

    Notable: ~/.claude/settings.json is NOT a documented MCP location and is
    silently ignored in current Claude Code versions
    (https://github.com/anthropics/claude-code/issues/4976). We deliberately
    do NOT write there. If the user has an old entry there we leave it alone.

    Schema URL: https://code.claude.com/docs/en/mcp
    """
    results = []
    # cwd is undocumented but tolerated; safer to omit and use absolute path.
    entry = make_server_entry(py_exe, with_cwd=False, include_type=False)

    # 1) User-scope file: ~/.claude.json
    user_path = home / ".claude.json"
    status = merge_into(user_path, "mcpServers", "elm-mcp", entry)
    results.append(("Claude Code (user, ~/.claude.json)", status, user_path))

    # 2) Project-scope file: <project>/.mcp.json
    proj_path = HERE / ".mcp.json"
    status = merge_into(proj_path, "mcpServers", "elm-mcp", entry)
    results.append(("Claude Code (project, .mcp.json)", status, proj_path))
    return results


def write_vscode(py_exe: str) -> list[tuple[str, str, Path]]:
    """VS Code (with Copilot/Bob) reads .vscode/mcp.json (workspace) using
    the "servers" top-level key, NOT "mcpServers". Each entry must include
    "type": "stdio" | "http" | "sse". `cwd` is NOT in the documented schema
    so we omit it and use absolute paths.

    User-scope config exists too (opened via "MCP: Open User Configuration"
    palette command) but its on-disk location is platform-specific and
    undocumented, so we only write the workspace file.

    NOTE: this is workspace-scoped — the user must open VS Code from this
    project directory for the MCP server to load.

    Schema URLs:
      https://code.visualstudio.com/docs/copilot/customization/mcp-servers
      https://code.visualstudio.com/docs/copilot/reference/mcp-configuration
    """
    entry = make_server_entry(py_exe, with_cwd=False, include_type=True)
    path = HERE / ".vscode" / "mcp.json"
    status = merge_into(path, "servers", "elm-mcp", entry)
    return [("VS Code (workspace, .vscode/mcp.json)", status, path)]


def write_cursor(py_exe: str, home: Path) -> list[tuple[str, str, Path]]:
    """Cursor reads .cursor/mcp.json (workspace) and ~/.cursor/mcp.json
    (user). Top-level key is "mcpServers". Stdio entries take command/args/
    env (and "type": "stdio" is accepted but not strictly required).

    We write BOTH so the server works whether the user opens this project
    in Cursor specifically or just opens Cursor at all.

    Schema URL: https://cursor.com/docs/context/mcp
    """
    entry = make_server_entry(py_exe, with_cwd=False, include_type=False)
    results = []
    proj_path = HERE / ".cursor" / "mcp.json"
    status = merge_into(proj_path, "mcpServers", "elm-mcp", entry)
    results.append(("Cursor (workspace, .cursor/mcp.json)", status, proj_path))

    user_path = home / ".cursor" / "mcp.json"
    status = merge_into(user_path, "mcpServers", "elm-mcp", entry)
    results.append(("Cursor (user, ~/.cursor/mcp.json)", status, user_path))
    return results


# Read-only tools that are safe to auto-approve in Bob — Bob's `alwaysAllow`
# array suppresses the per-call permission prompt for these. Writes still
# require explicit user confirmation because they hit the live ELM server.
_BOB_ALWAYS_ALLOW = [
    "connect_to_elm",
    "list_projects",
    "list_capabilities",
    "get_modules",
    "get_module_requirements",
    "search_requirements",
    "get_artifact_types",
    "get_link_types",
    "get_attribute_definitions",
    "get_ewm_workitem_types",
    "get_workflow_states",
    "find_folder",
    "elm_mcp_health",
    "resolve_requirement_id",
    "resolve_user",
    "list_test_cases",
    "list_test_plans",
    "list_test_execution_records",
    "list_baselines",
    "compare_baselines",
    "extract_pdf",
    "list_global_configurations",
    "list_global_components",
    "get_global_config_details",
    "query_work_items",
    "scm_list_projects",
    "scm_list_changesets",
    "scm_get_changeset",
    "scm_get_workitem_changesets",
    "review_get",
    "review_list_open",
    # Update tooling — auto-approved because the user explicitly asks
    # for an update, and the alternative is Bob shelling out 8 git
    # commands that EACH prompt for approval. One-tool-call update.
    "update_elm_mcp",
    # Build-project orchestration tools — these don't write to ELM
    # themselves; they return phase scripts for the AI to execute.
    # Auto-approve so Bob doesn't gate the orchestration plumbing.
    # The actual writes (create_requirement, create_task, etc.) still
    # prompt because they're not in this list.
    "build_project",
    "build_project_next",
    "build_new_project",
    "build_from_existing",
    "build_project_status",
    "build_project_resume",
    "wrap_up_session",
    "get_team_actions",
]
# Note: generate_chart and save_requirements are intentionally NOT in this
# list. Both write to local disk (PNG / JSON), so they should prompt the
# user before running. See Bob compatibility audit findings (v0.1.13).


def write_bob(py_exe: str, home: Path) -> list[tuple[str, str, Path]]:
    """IBM Bob reads MCP configs from several locations depending on version.
    Older Bob: ~/.bob/mcp_settings.json. Newer Bob: ~/.bob/settings/mcp_settings.json.
    We write to BOTH so the server loads regardless of which version is installed.
    Bob's per-server schema also accepts `alwaysAllow` (array of tool names to skip
    the per-call permission prompt) and `disabled`. We pre-populate alwaysAllow
    with the read-only tools so a Bob session feels snappy on common queries;
    writes still prompt for confirmation.

    Schema URL: https://bob.ibm.com/docs/ide/configuration/mcp/mcp-in-bob
    """
    entry = make_server_entry(py_exe, with_cwd=False, include_type=False)
    entry["alwaysAllow"] = list(_BOB_ALWAYS_ALLOW)
    results = []
    # Newer Bob: ~/.bob/settings/mcp_settings.json (verified in field as
    # the actual file Bob reads on recent versions; writing to the older
    # path alone caused entries to be silently ignored).
    new_global_path = home / ".bob" / "settings" / "mcp_settings.json"
    results.append((
        "Bob (~/.bob/settings/mcp_settings.json, global — newer Bob)",
        merge_into(new_global_path, "mcpServers", "elm-mcp", entry),
        new_global_path,
    ))
    # Older Bob: ~/.bob/mcp_settings.json
    legacy_global_path = home / ".bob" / "mcp_settings.json"
    results.append((
        "Bob (~/.bob/mcp_settings.json, global — older Bob)",
        merge_into(legacy_global_path, "mcpServers", "elm-mcp", entry),
        legacy_global_path,
    ))
    # Project-scoped Bob config
    project_path = HERE / ".bob" / "mcp.json"
    results.append((
        "Bob (<project>/.bob/mcp.json, project)",
        merge_into(project_path, "mcpServers", "elm-mcp", entry),
        project_path,
    ))
    return results


def write_windsurf(py_exe: str, home: Path) -> list[tuple[str, str, Path]]:
    """Windsurf reads ~/.codeium/windsurf/mcp_config.json. Top-level key is
    "mcpServers". Supports command/args/env. cwd is supported in practice
    via the `command` field accepting any executable (we still omit cwd and
    use absolute paths to be safe across versions).

    Schema URL: https://docs.windsurf.com/windsurf/cascade/mcp
    """
    entry = make_server_entry(py_exe, with_cwd=False, include_type=False)
    path = home / ".codeium" / "windsurf" / "mcp_config.json"
    status = merge_into(path, "mcpServers", "elm-mcp", entry)
    return [("Windsurf (~/.codeium/windsurf/mcp_config.json)", status, path)]


def configure_hosts(py_exe: str) -> int:
    """Write MCP config to every host that looks installed.
    Returns total number of files actually touched (added or updated)."""
    home = Path.home()

    plan: list[tuple[str, callable, callable]] = [
        ("Claude Code", lambda: host_present_claude_code(home),
         lambda: write_claude_code(py_exe, home)),
        ("IBM Bob", lambda: host_present_bob(home),
         lambda: write_bob(py_exe, home)),
        ("VS Code (Copilot)", lambda: host_present_vscode(home),
         lambda: write_vscode(py_exe)),
        ("Cursor", lambda: host_present_cursor(home),
         lambda: write_cursor(py_exe, home)),
        ("Windsurf", lambda: host_present_windsurf(home),
         lambda: write_windsurf(py_exe, home)),
    ]

    detected = 0
    written_or_present = 0
    for host_name, present_fn, write_fn in plan:
        if not present_fn():
            info(f"{host_name}: not detected, skipped")
            continue
        detected += 1
        ok(f"{host_name}: detected")
        for label, status, path in write_fn():
            if status == "added":
                ok(f"  added   -> {path}")
                written_or_present += 1
            elif status == "updated":
                ok(f"  updated -> {path}")
                written_or_present += 1
            elif status == "exists":
                ok(f"  already configured: {path}")
                written_or_present += 1
            # error case already printed

    if detected == 0:
        fail(
            "No AI assistants detected. Install one of: Claude Code, "
            "VS Code (with Copilot or Bob), Cursor, or Windsurf. "
            "Then re-run: python3 setup.py"
        )
    return detected


# ── Step 3: .env creation ────────────────────────────────────

def env_has_real_values() -> bool:
    """True if .env has non-placeholder values for URL/USER/PASSWORD.

    Accepts either the new ELM_* names or the legacy DOORS_* names so a
    pre-existing .env from older installs still counts as configured.
    """
    if not ENV_FILE.exists():
        return False
    placeholders = {"your-elm-server.com", "your-doors-server.com",
                    "your_username", "your_password", ""}
    found = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        found[k.strip()] = v.strip().strip('"').strip("'")

    def has(key_pair):
        # key_pair is (new_name, legacy_name); we accept either
        for k in key_pair:
            if k in found and found[k] and not any(p in found[k] for p in placeholders if p):
                return True
        return False

    return (has(("ELM_URL", "DOORS_URL"))
            and has(("ELM_USERNAME", "DOORS_USERNAME"))
            and has(("ELM_PASSWORD", "DOORS_PASSWORD")))


def prompt_for_credentials() -> None:
    print("\n  Enter your IBM ELM credentials.")
    print(f"  {DIM}These are saved to a local .env file (gitignored){RESET}")
    print(f"  {DIM}Press Ctrl-C to skip and edit .env manually later{RESET}\n")
    try:
        url = input("  ELM server URL (e.g. https://yourcompany.elm.ibmcloud.com): ").strip()
        user = input("  Username: ").strip()
        pwd = getpass("  Password (hidden): ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        warn("Skipped. Edit .env manually before running your AI assistant.")
        return

    if not (url and user and pwd):
        warn("Missing values. Skipped.")
        return

    ENV_FILE.write_text(
        "# IBM ELM credentials. The same login covers DNG, EWM, ETM, GCM, SCM.\n"
        "# Legacy DOORS_URL/DOORS_USERNAME/DOORS_PASSWORD are also still read\n"
        "# (with lower priority) so older setups keep working.\n"
        f"ELM_URL={url}\n"
        f"ELM_USERNAME={user}\n"
        f"ELM_PASSWORD={pwd}\n"
    )
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass
    ok(f"Wrote credentials to {ENV_FILE.name}")


def prompt_for_jira_credentials() -> None:
    """Optional: add Jira REST credentials to .env so the native
    /import-jira flow (get_jira_issue, add_jira_comment, etc.) works.

    Appends to .env without clobbering existing ELM credentials. Skipped
    silently if JIRA_API_TOKEN is already set."""
    existing = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip().strip('"').strip("'")
    if existing.get("JIRA_API_TOKEN"):
        ok("Jira credentials already in .env — skipped")
        return

    print(f"  {DIM}Adds Jira credentials to .env (next to your ELM ones).{RESET}")
    print(f"  {DIM}Token: https://id.atlassian.com/manage-profile/security/api-tokens{RESET}")
    print(f"  {DIM}Press Ctrl-C to skip — edit .env manually later if needed{RESET}\n")
    try:
        base = input(
            "  Jira base URL (e.g. https://yourorg.atlassian.net): "
        ).strip()
        email = input("  Jira email (the one tied to the API token): ").strip()
        token = getpass("  Jira API token (hidden): ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        warn("Skipped. Add JIRA_* manually to .env later if you want "
             "/import-jira to work.")
        return

    if not (base and email and token):
        warn("Missing values. Skipped.")
        return

    current = ENV_FILE.read_text() if ENV_FILE.exists() else ""
    if not current.endswith("\n"):
        current += "\n"
    current += (
        "\n# Jira credentials — used by elm-mcp's native /import-jira.\n"
        "# Bypasses Atlassian's hosted MCP; talks to Jira REST directly.\n"
        "# Token: id.atlassian.com/manage-profile/security/api-tokens\n"
        f"JIRA_BASE_URL={base}\n"
        f"JIRA_EMAIL={email}\n"
        f"JIRA_API_TOKEN={token}\n"
    )
    ENV_FILE.write_text(current)
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass
    ok(f"Added Jira credentials to {ENV_FILE.name}")


def setup_env() -> None:
    if env_has_real_values():
        ok(".env already has credentials")
        return
    if not ENV_FILE.exists() and ENV_EXAMPLE.exists():
        shutil.copy(ENV_EXAMPLE, ENV_FILE)
        info("Copied .env.example -> .env")
    prompt_for_credentials()


# ── Step 4: REAL MCP smoke test ──────────────────────────────
#
# The previous setup.py only tested doors_client.authenticate(), which never
# touched doors_mcp_server.py. If the server had an import error, syntax
# error, or stdio-protocol bug, setup happily reported "success" and the IDE
# silently failed.
#
# This smoke test launches doors_mcp_server.py exactly the way an MCP host
# would (stdio transport, fresh subprocess), performs the MCP `initialize`
# handshake, calls `tools/list`, and confirms at least one tool is returned.
# That proves end-to-end: import works, MCP wiring works, tools register.
#
# We use the official `mcp` Python SDK's stdio_client because it handles the
# JSON-RPC framing, content-length headers (none for stdio — it's
# newline-delimited JSON), and lifecycle correctly. Reinventing this would
# be a maintenance liability.

def smoke_test_server(py_exe: str) -> bool:
    """Launch doors_mcp_server.py over stdio and confirm tools/list returns >=1."""
    try:
        # Imported inside the function so a missing mcp module gives a clear
        # error here rather than crashing setup.py at the top.
        import asyncio
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as e:
        fail(f"mcp SDK not importable in this interpreter: {e}")
        info("Re-run: python3 setup.py (will install requirements.txt)")
        return False

    info(f"Launching: {py_exe} {SERVER_SCRIPT}  (cwd={HERE})")

    async def run() -> bool:
        # Pass through DOORS_* env so the server can authenticate at startup
        # if credentials are present. The server itself doesn't *require*
        # creds to register tools, so the smoke test passes even with no
        # .env, but having creds means we exercise more of the startup path.
        env = os.environ.copy()
        params = StdioServerParameters(
            command=py_exe,
            args=[SERVER_SCRIPT],
            cwd=str(HERE),
            env=env,
        )
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    init_result = await asyncio.wait_for(
                        session.initialize(), timeout=20.0
                    )
                    server_name = getattr(
                        getattr(init_result, "serverInfo", None), "name", "?"
                    )
                    ok(f"initialize: server={server_name!r}")
                    tools_result = await asyncio.wait_for(
                        session.list_tools(), timeout=15.0
                    )
                    tools = getattr(tools_result, "tools", [])
                    if not tools:
                        fail("tools/list returned 0 tools")
                        return False
                    ok(f"tools/list: {len(tools)} tools registered")
                    info("first 3: " + ", ".join(t.name for t in tools[:3]))
                    return True
        except asyncio.TimeoutError:
            fail("MCP server did not respond within timeout. "
                 "Check stderr above — usually means the server crashed on import.")
            return False
        except Exception as e:
            fail(f"MCP smoke test failed: {type(e).__name__}: {e}")
            return False

    try:
        return asyncio.run(run())
    except RuntimeError as e:
        # In case we're already inside a running loop (we shouldn't be, but…)
        fail(f"asyncio runtime error: {e}")
        return False


def test_credentials() -> bool:
    """Optional: also exercise the doors_client auth path (prints if creds work).
    Failure here is a warning, not a setup-blocking error — the server still
    works without creds; the user just hasn't set them yet."""
    if not env_has_real_values():
        warn("No credentials in .env yet — skipping ELM auth check.")
        return False
    try:
        from doors_client import DOORSNextClient
    except ImportError as e:
        fail(f"Cannot import doors_client: {e}")
        return False
    try:
        client = DOORSNextClient.from_env()
        result = client.authenticate()
    except Exception as e:
        fail(f"ELM auth raised: {e}")
        return False

    if result.get("success"):
        ok(f"ELM auth OK -> {client.server_root}")
        try:
            n = len(client.list_projects())
            ok(f"Found {n} DNG project(s)")
        except Exception as e:
            warn(f"Connected, but couldn't list projects yet: {e}")
        return True

    fail(f"ELM auth failed: {result.get('error', 'unknown error')}")
    return False


# ── --diagnose mode ──────────────────────────────────────────

def diagnose() -> int:
    """Smoke-test only. No config writes, no pip install, no prompts.

    Use this after setup to verify the MCP server still works (e.g. after
    a Python upgrade, dependency change, or password rotation).
    """
    print(f"{BOLD}DOORS Next AI Agent — diagnose mode{RESET}")
    print(f"{DIM}Project dir: {HERE}{RESET}")
    print(f"{DIM}Interpreter: {sys.executable}{RESET}")
    if interpreter_in_venv(sys.executable):
        info("(this interpreter is in a virtual environment)")

    print(f"\n{BOLD}[1/3] Verify interpreter has required deps{RESET}")
    ok_imports, missing = interpreter_can_import(sys.executable, REQUIRED_IMPORTS)
    if not ok_imports:
        fail(f"Missing modules: {', '.join(missing)}")
        info(f"Fix with: {sys.executable} -m pip install -r {REQUIREMENTS.name}")
        return 1
    ok(f"All required modules importable: {', '.join(REQUIRED_IMPORTS)}")

    print(f"\n{BOLD}[2/3] MCP server smoke test (stdio handshake){RESET}")
    if not smoke_test_server(sys.executable):
        return 1

    print(f"\n{BOLD}[3/3] ELM credentials check (optional){RESET}")
    test_credentials()

    print(f"\n{GREEN}{BOLD}All diagnostics passed.{RESET}")
    return 0


# ── --print-config mode ──────────────────────────────────────

def print_config() -> int:
    """Print the MCP server JSON for the user to copy-paste into Bob (or any
    other AI host's MCP config). Outputs to stdout with both paths pre-filled
    for the current machine. No installs, no prompts, no side effects."""
    py_path = sys.executable
    server_path = str((HERE / SERVER_SCRIPT).resolve())

    # The standard "alwaysAllow" set — read-only tools that don't need
    # per-call confirmation in Bob. MUST stay in sync with _BOB_ALWAYS_ALLOW
    # above (single source of truth: this list mirrors that one).
    always_allow = list(_BOB_ALWAYS_ALLOW) + ["update_elm_mcp"]
    config = {
        "mcpServers": {
            "elm-mcp": {
                "command": py_path,
                "args": [server_path],
                "alwaysAllow": always_allow,
            }
        }
    }

    print(f"{BOLD}# ELM MCP — config for IBM Bob / Claude Code / Cursor / Windsurf{RESET}")
    print(f"{DIM}# Copy the JSON below and paste into your AI host's MCP config file:{RESET}")
    print(f"{DIM}#   IBM Bob:     ~/.bob/mcp_settings.json  (top-level key: mcpServers){RESET}")
    print(f"{DIM}#   Claude Code: ~/.claude.json             (top-level key: mcpServers){RESET}")
    print(f"{DIM}#   Cursor:      ~/.cursor/mcp.json         (top-level key: mcpServers){RESET}")
    print(f"{DIM}#   Windsurf:    ~/.codeium/windsurf/mcp_config.json  (top-level key: mcpServers){RESET}")
    print(f"{DIM}#   VS Code:     <project>/.vscode/mcp.json (use 'servers' instead of 'mcpServers',{RESET}")
    print(f"{DIM}#                 and add type: 'stdio' inside the server entry){RESET}")
    print()
    import json as _json
    print(_json.dumps(config, indent=2))
    print()
    print(f"{DIM}# Then fully quit and reopen your AI assistant for it to load the new MCP server.{RESET}")
    return 0


# ── mode auto-install ────────────────────────────────────────

# elm-mcp custom-mode slugs. The mode installer OWNS these slugs — on
# install it removes any existing copies and re-adds the current version,
# leaving every OTHER mode in the user's Bob config untouched.
_ELM_MODE_SLUGS = (
    "concierge",
    "requirements-planner",
    "requirements-pusher",
    "impact-analyst",
    "compliance-auditor",
)


def _yaml_block_str_representer(dumper, data):
    """Force PyYAML to use literal block style (|) for any multi-line
    string so the big roleDefinition / customInstructions markdown blocks
    stay readable in Bob's custom_modes.yaml (matches Bob's own format)."""
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data,
                                        style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


def install_modes(home: Path) -> bool:
    """Install elm-mcp's 5 custom Bob modes automatically.

    Collapses the old manual dance (paste YAML into Bob's settings + copy
    five rules dirs) into one step:

      1. Merge `modes/custom_modes.yaml` into Bob's global custom modes at
         ~/.bob/settings/custom_modes.yaml — replacing our slugs, keeping
         every other mode the user has.
      2. Copy each `modes/rules/rules-{slug}/` into ~/.bob/rules-{slug}/.

    Skips gracefully (returns False, no error) if Bob isn't detected or
    the modes/ dir is missing. Bob-specific — Claude Code / Cursor don't
    use this mode system.
    """
    if not host_present_bob(home):
        info("Bob not detected — skipping custom-mode install. "
             "(Modes are a Bob feature; other hosts don't use them.)")
        return False

    modes_dir = HERE / "modes"
    src_yaml = modes_dir / "custom_modes.yaml"
    if not src_yaml.exists():
        warn(f"modes/custom_modes.yaml not found — skipping mode install.")
        return False

    try:
        import yaml
    except ImportError:
        warn("PyYAML not importable — skipping mode install. "
             "Run `pip install pyyaml` then re-run setup.")
        return False

    yaml.add_representer(str, _yaml_block_str_representer)

    # ── Load our modes ──────────────────────────────────────────
    try:
        our_doc = yaml.safe_load(src_yaml.read_text(encoding="utf-8"))
        our_modes = our_doc.get("customModes", []) if our_doc else []
    except Exception as e:
        warn(f"Couldn't parse our custom_modes.yaml: {e}")
        return False
    if not our_modes:
        warn("No modes found in modes/custom_modes.yaml.")
        return False

    # ── Locate Bob's global custom-modes file ───────────────────
    # Newer Bob: ~/.bob/settings/custom_modes.yaml. Older: ~/.bob/custom_modes.yaml.
    settings_dir = home / ".bob" / "settings"
    candidates = [
        settings_dir / "custom_modes.yaml",
        home / ".bob" / "custom_modes.yaml",
    ]
    target = next((c for c in candidates if c.exists()), None)
    if target is None:
        settings_dir.mkdir(parents=True, exist_ok=True)
        target = settings_dir / "custom_modes.yaml"
        existing_modes = []
    else:
        try:
            existing_doc = yaml.safe_load(target.read_text(encoding="utf-8"))
            existing_modes = (existing_doc.get("customModes", [])
                              if existing_doc else [])
        except Exception as e:
            warn(f"Couldn't parse existing {target.name}: {e} — "
                 "backing it up and starting fresh.")
            existing_modes = []

    # ── Merge: drop our slugs from existing, then append ours ───
    kept = [m for m in existing_modes
            if m.get("slug") not in _ELM_MODE_SLUGS]
    merged = kept + our_modes

    # Back up before writing (user may have hand-edited modes)
    if target.exists():
        try:
            shutil.copy2(target, target.with_suffix(".yaml.bak"))
        except Exception:
            pass

    try:
        out = yaml.dump({"customModes": merged},
                        default_flow_style=False,
                        sort_keys=False,
                        allow_unicode=True,
                        width=10_000)
        target.write_text(out, encoding="utf-8")
    except Exception as e:
        fail(f"Couldn't write merged modes to {target}: {e}")
        return False

    ok(f"Installed {len(our_modes)} elm-mcp modes into {target}")
    if kept:
        info(f"Preserved {len(kept)} of your other custom mode(s).")

    # ── Copy the rules playbooks ────────────────────────────────
    rules_src = modes_dir / "rules"
    installed_rules = 0
    for slug in _ELM_MODE_SLUGS:
        src = rules_src / f"rules-{slug}"
        if not src.exists():
            continue
        dst = home / ".bob" / f"rules-{slug}"
        try:
            dst.mkdir(parents=True, exist_ok=True)
            for f in src.iterdir():
                if f.is_file():
                    shutil.copy2(f, dst / f.name)
            installed_rules += 1
        except Exception as e:
            warn(f"Couldn't copy rules for {slug}: {e}")
    if installed_rules:
        ok(f"Installed {installed_rules} mode playbook(s) into ~/.bob/rules-*/")

    return True


# ── main ─────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="DOORS Next AI Agent installer / diagnostic tool"
    )
    parser.add_argument(
        "--diagnose", action="store_true",
        help="Run smoke test only — don't install or write any config.",
    )
    parser.add_argument(
        "--print-config", action="store_true",
        help="Print the MCP server JSON config (with absolute paths filled in) "
             "for copy-paste into IBM Bob / Claude Code / VS Code / etc. Doesn't "
             "install or change anything — pure stdout.",
    )
    parser.add_argument(
        "--with-jira", action="store_true",
        help="During setup, also prompt for Jira credentials "
             "(JIRA_BASE_URL / JIRA_EMAIL / JIRA_API_TOKEN). Stored in "
             "your local .env. Powers the native /import-jira flow "
             "(get_jira_issue, add_jira_comment, etc.) which talks to "
             "Jira's REST API directly. No Atlassian MCP / Node / OAuth.",
    )
    parser.add_argument(
        "--no-modes", action="store_true",
        help="Skip auto-installing the 5 elm-mcp custom Bob modes "
             "(Concierge, Plan, Push, Impact Analyst, Compliance Auditor). "
             "By default setup merges them into Bob's custom_modes.yaml and "
             "copies their playbooks. Use this if you manage modes by hand.",
    )
    parser.add_argument(
        "--modes-only", action="store_true",
        help="ONLY (re)install the custom Bob modes — skip deps, host "
             "config, credentials, and smoke test. Handy after editing the "
             "mode files, or to repair a broken mode install.",
    )
    args = parser.parse_args()

    if args.modes_only:
        print(f"{BOLD}DOORS Next AI Agent — modes-only install{RESET}")
        installed = install_modes(Path.home())
        if installed:
            print(f"\n{GREEN}{BOLD}Modes installed.{RESET} "
                  f"Fully quit and reopen Bob to load them.\n")
            return 0
        print(f"\n{YELLOW}No modes installed{RESET} "
              f"(Bob not detected, or modes/ missing).\n")
        return 1

    if args.diagnose:
        return diagnose()

    if args.print_config:
        return print_config()

    print(f"{BOLD}DOORS Next AI Agent — Setup{RESET}")
    print(f"{DIM}Project dir: {HERE}{RESET}")
    print(f"{DIM}Interpreter: {sys.executable}{RESET}")
    if interpreter_in_venv(sys.executable):
        warn("This Python is a virtual environment.")
        info("If your IDE doesn't use this same venv, the MCP server will fail to start.")
        info("If unsure, re-run with the OS-default python: /usr/bin/python3 setup.py")

    py_exe = sys.executable
    install_bob_modes = (not args.no_modes) and host_present_bob(Path.home())
    total = 6 if install_bob_modes else 5

    step(1, total, "Install Python dependencies")
    if not install_dependencies(py_exe):
        return 1

    step(2, total, "Verify the chosen Python can import everything")
    ok_imports, missing = interpreter_can_import(py_exe, REQUIRED_IMPORTS)
    if not ok_imports:
        fail(f"Even after pip install, {py_exe} cannot import: {', '.join(missing)}")
        info("This usually means pip installed into a different Python than the one "
             "you ran setup with. Check `which python3` vs the path printed above.")
        return 1
    ok(f"All required modules importable in {py_exe}")

    step(3, total, "Configure your AI assistant(s)")
    detected = configure_hosts(py_exe)
    if detected == 0:
        return 1

    step(4, total, "ELM credentials (.env)")
    setup_env()

    step(5, total, "Real MCP smoke test (launches the server, calls tools/list)")
    smoke_ok = smoke_test_server(py_exe)
    if not smoke_ok:
        fail("Server smoke test failed. The MCP server will not work in your IDE.")
        return 1

    if install_bob_modes:
        step(6, total, "Install Bob custom modes (Concierge, Plan, Push, "
                        "Impact Analyst, Compliance Auditor)")
        install_modes(Path.home())

    # Credential check is informational only — don't fail setup if creds
    # aren't entered yet, the server still loads its tools without them.
    print()
    test_credentials()

    # ── Optional: Jira credentials for /import-jira ──────────────
    # The native Jira tools talk to Jira's REST API directly using
    # email + API token Basic auth. No Atlassian MCP, no OAuth, no
    # Node — just adds 3 entries to .env.
    if args.with_jira:
        print()
        print(f"{BOLD}Jira credentials (for /import-jira){RESET}")
        prompt_for_jira_credentials()

    print(f"\n{GREEN}{BOLD}Setup complete.{RESET}\n")

    # ── Finale: tell the user EXACTLY what to do next in Bob ────────
    py_path = sys.executable
    server_path = str((HERE / SERVER_SCRIPT).resolve())
    print(f"{BOLD}Next steps:{RESET}\n")
    print(f"  {BOLD}1. Fully quit Bob{RESET} (Cmd+Q on Mac, not just close window),")
    print(f"     {BOLD}then reopen.{RESET}")
    print()
    print(f"  {BOLD}2. In Bob's chat, say:{RESET}")
    print(f"     {GREEN}'Connect to ELM and list my projects'{RESET}")
    print()
    if install_bob_modes:
        print(f"  {DIM}The 5 elm-mcp modes (🧭 Concierge, 📝 Plan, 📤 Push, "
              f"🎯 Impact Analyst,{RESET}")
        print(f"  {DIM}📜 Compliance Auditor) were installed automatically. "
              f"After restart,{RESET}")
        print(f"  {DIM}pick them from Bob's mode menu or just type /plan / "
              f"/concierge.{RESET}")
        print()
    print(f"  {BOLD}3. If Bob doesn't see ELM MCP after restart{RESET} — some Bob versions")
    print(f"     {BOLD}don't auto-pick-up new entries in `~/.bob/mcp_settings.json`. Add it manually:{RESET}\n")
    print(f"     a) Open Bob → Settings → MCP Servers (or equivalent menu)")
    print(f"     b) Click 'Add Server' (or 'New Server' / '+')")
    print(f"     c) Use these exact values:")
    print()
    print(f"        {BOLD}Name:{RESET}    elm-mcp")
    print(f"        {BOLD}Command:{RESET} {py_path}")
    print(f"        {BOLD}Args:{RESET}    {server_path}")
    print()
    print(f"     d) Save. Bob may ask you to restart again.")
    print()
    print(f"  {BOLD}If Bob's UI doesn't have an Add-Server form{RESET}, paste this JSON")
    print(f"  into {DIM}~/.bob/mcp_settings.json{RESET} under the {DIM}mcpServers{RESET} key:\n")
    import json as _json
    config_snippet = {
        "elm-mcp": {
            "command": py_path,
            "args": [server_path],
            "alwaysAllow": list(_BOB_ALWAYS_ALLOW),
        }
    }
    snippet_text = _json.dumps(config_snippet, indent=2)
    # Indent each line for visual clarity
    for line in snippet_text.split("\n"):
        print(f"    {line}")
    print()
    print(f"  {DIM}Re-test any time:        python3 setup.py --diagnose{RESET}")
    print(f"  {DIM}Re-print this config:    python3 setup.py --print-config{RESET}")
    print(f"  {DIM}Network timeout in Bob:  set to 120000 (2 min) so batch creates don't time out{RESET}")
    print()
    print(f"  {BOLD}⚠️  Heads-up about DNG configuration management (CM){RESET}")
    print(f"  {DIM}This MCP is built for CM-enabled DNG projects. Without CM:{RESET}")
    print(f"  {DIM}  • You can still create requirements (in folders){RESET}")
    print(f"  {DIM}  • You CANNOT bind reqs into modules programmatically (DNG limitation){RESET}")
    print(f"  {DIM}  • Baselines, streams, and Phase 5/6 of /build-project won't work fully{RESET}")
    print(f"  {DIM}If your project doesn't have CM, ask your DNG admin to enable it{RESET}")
    print(f"  {DIM}(single project-level setting; non-destructive).{RESET}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
