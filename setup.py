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
    status = merge_into(user_path, "mcpServers", "doors-next", entry)
    results.append(("Claude Code (user, ~/.claude.json)", status, user_path))

    # 2) Project-scope file: <project>/.mcp.json
    proj_path = HERE / ".mcp.json"
    status = merge_into(proj_path, "mcpServers", "doors-next", entry)
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
    status = merge_into(path, "servers", "doors-next", entry)
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
    status = merge_into(proj_path, "mcpServers", "doors-next", entry)
    results.append(("Cursor (workspace, .cursor/mcp.json)", status, proj_path))

    user_path = home / ".cursor" / "mcp.json"
    status = merge_into(user_path, "mcpServers", "doors-next", entry)
    results.append(("Cursor (user, ~/.cursor/mcp.json)", status, user_path))
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
    status = merge_into(path, "mcpServers", "doors-next", entry)
    return [("Windsurf (~/.codeium/windsurf/mcp_config.json)", status, path)]


def configure_hosts(py_exe: str) -> int:
    """Write MCP config to every host that looks installed.
    Returns total number of files actually touched (added or updated)."""
    home = Path.home()

    plan: list[tuple[str, callable, callable]] = [
        ("Claude Code", lambda: host_present_claude_code(home),
         lambda: write_claude_code(py_exe, home)),
        ("VS Code (Copilot/Bob)", lambda: host_present_vscode(home),
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
    """True if .env exists and has non-placeholder values for the 3 keys."""
    if not ENV_FILE.exists():
        return False
    needed = {"DOORS_URL", "DOORS_USERNAME", "DOORS_PASSWORD"}
    placeholders = {"your-doors-server.com", "your_username", "your_password", ""}
    found = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        found[k.strip()] = v.strip().strip('"').strip("'")
    if not needed.issubset(found):
        return False
    return all(found[k] and not any(p in found[k] for p in placeholders if p) for k in needed)


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
        f"DOORS_URL={url}\n"
        f"DOORS_USERNAME={user}\n"
        f"DOORS_PASSWORD={pwd}\n"
    )
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass
    ok(f"Wrote credentials to {ENV_FILE.name}")


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


# ── main ─────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="DOORS Next AI Agent installer / diagnostic tool"
    )
    parser.add_argument(
        "--diagnose", action="store_true",
        help="Run smoke test only — don't install or write any config.",
    )
    args = parser.parse_args()

    if args.diagnose:
        return diagnose()

    print(f"{BOLD}DOORS Next AI Agent — Setup{RESET}")
    print(f"{DIM}Project dir: {HERE}{RESET}")
    print(f"{DIM}Interpreter: {sys.executable}{RESET}")
    if interpreter_in_venv(sys.executable):
        warn("This Python is a virtual environment.")
        info("If your IDE doesn't use this same venv, the MCP server will fail to start.")
        info("If unsure, re-run with the OS-default python: /usr/bin/python3 setup.py")

    py_exe = sys.executable
    total = 5

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

    # Credential check is informational only — don't fail setup if creds
    # aren't entered yet, the server still loads its tools without them.
    print()
    test_credentials()

    print(f"\n{GREEN}{BOLD}Setup complete.{RESET}")
    print("  Open your AI assistant (reload its window if it was already open) and say:")
    print(f"  {BOLD}'Connect to ELM and list projects'{RESET}\n")
    print(f"  {DIM}Re-test any time:  python3 setup.py --diagnose{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
