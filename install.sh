#!/usr/bin/env bash
#
# ELM MCP — one-command installer.
#
# Run this from any terminal:
#
#   curl -fsSL https://raw.githubusercontent.com/brettscharm/elm-mcp/main/install.sh | bash
#
# It clones the repo to a stable location, runs setup.py to wire up your
# AI host (IBM Bob, Claude Code, Cursor, VS Code, Windsurf), and prompts
# for your ELM credentials. Re-running it later updates the clone in
# place and re-runs setup. Idempotent.
#
# NOT an official IBM product. Personal passion project. Use at your
# own risk.

set -euo pipefail

REPO_URL="https://github.com/brettscharm/elm-mcp.git"
INSTALL_DIR="${ELM_MCP_DIR:-$HOME/.elm-mcp}"

# ── Pretty output ────────────────────────────────────────────
if [ -t 1 ]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[92m'; RED=$'\033[91m'; RESET=$'\033[0m'
else
  BOLD=""; DIM=""; GREEN=""; RED=""; RESET=""
fi
say()  { printf "%s\n" "$*"; }
ok()   { printf "  ${GREEN}OK${RESET}  %s\n" "$*"; }
fail() { printf "  ${RED}FAIL${RESET}  %s\n" "$*"; exit 1; }
step() { printf "\n${BOLD}%s${RESET}\n" "$*"; }

say "${BOLD}ELM MCP installer${RESET}"
say "${DIM}Personal passion project — not an official IBM product. Use at your own risk.${RESET}"

# ── Prerequisites ────────────────────────────────────────────
step "[1/4] Checking prerequisites"
command -v git >/dev/null 2>&1 || fail "git is not installed."
ok "git: $(git --version)"

PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" 2>/dev/null; then
      PY="$candidate"; break
    fi
  fi
done
[ -n "$PY" ] || fail "Python 3.9+ is required. Install from https://www.python.org/downloads/ and re-run."
ok "$PY: $($PY --version 2>&1)"

# ── Clone or update ──────────────────────────────────────────
step "[2/4] Clone or update the repo at $INSTALL_DIR"
if [ -d "$INSTALL_DIR/.git" ]; then
  ok "Existing clone found — pulling latest"
  git -C "$INSTALL_DIR" fetch --quiet origin
  git -C "$INSTALL_DIR" reset --hard --quiet origin/main
  ok "Updated: $(git -C "$INSTALL_DIR" rev-parse --short HEAD)"
elif [ -e "$INSTALL_DIR" ]; then
  fail "$INSTALL_DIR exists but isn't a git checkout. Move/delete it and re-run."
else
  git clone --quiet "$REPO_URL" "$INSTALL_DIR"
  ok "Cloned: $(git -C "$INSTALL_DIR" rev-parse --short HEAD)"
fi

# ── Run setup.py ─────────────────────────────────────────────
step "[3/4] Running setup.py (deps + AI host config + smoke test)"
cd "$INSTALL_DIR"
# CRITICAL: when this script is invoked via `curl ... | bash`, bash
# itself is reading the pipe and stdin is already consumed. setup.py's
# input() / getpass() calls would hit EOF immediately and silently
# skip credential entry. Re-attach stdin to the user's terminal so
# prompts actually work. If we're already in a terminal (no pipe),
# do nothing special.
#
# We must test that /dev/tty is actually USABLE, not just that it
# exists. On CI runners, Docker without -t, some SSH sessions, and
# scripted installs, /dev/tty exists but opening it fails with
# "Device not configured" — and `setup.py < /dev/tty` would abort the
# whole install before deps/config/modes ever run. Probe it for real.
# Open the real terminal on fd 3 ONLY if it's genuinely usable, then
# feed that to setup.py. Doing the open in the current shell (not a
# subshell probe) means the test and the use are the SAME operation —
# they can't disagree. A subshell probe like `( : < /dev/tty )` can
# report "openable" in nested pipe contexts where the actual redirect
# then fails with "Device not configured", aborting the install. The
# `{ exec 3<...; } 2>/dev/null` form fails safe: if the open fails the
# condition is false (no abort), and stderr is swallowed.
run_setup() {
  if [ -t 0 ]; then
    # Already attached to a terminal — prompts work as-is.
    "$PY" setup.py
  elif { exec 3</dev/tty; } 2>/dev/null; then
    # Real terminal opened on fd 3 — feed it to setup.py so credential
    # prompts work even though our own stdin is the curl pipe.
    "$PY" setup.py <&3
    exec 3<&-
  else
    # No usable terminal (CI, Docker w/o -t, scripted, nested pipes).
    # Everything still installs — deps, host config, smoke test, AND
    # the modes. Only the interactive credential prompt is skipped
    # (setup.py handles EOF gracefully). Show how to add creds after.
    printf "  %sNo usable terminal — skipping the interactive credential prompt.%s\n" "$DIM" "$RESET"
    printf "  %sEverything else (server + all tools + modes) still installs.%s\n" "$DIM" "$RESET"
    printf "  %sAdd credentials after with: %s%s setup.py%s %s(run from %s)%s\n" "$DIM" "$BOLD" "$PY" "$RESET" "$DIM" "$INSTALL_DIR" "$RESET"
    printf "  %sor edit %s/.env directly (ELM_URL / ELM_USERNAME / ELM_PASSWORD).%s\n" "$DIM" "$INSTALL_DIR" "$RESET"
    "$PY" setup.py < /dev/null
  fi
}
run_setup

# ── Done ─────────────────────────────────────────────────────
step "[4/4] Done — and here's the manual-fallback info"
PY_ABS=$(command -v "$PY")
SERVER_ABS="$INSTALL_DIR/doors_mcp_server.py"
say ""
say "  ${GREEN}✓${RESET} ELM MCP installed at: ${BOLD}$INSTALL_DIR${RESET}"
say "  ${GREEN}✓${RESET} Configs written to every AI host detected."
say "  ${GREEN}✓${RESET} Now: ${BOLD}fully quit and reopen your AI assistant${RESET} (Cmd+Q on macOS), then say:"
say "    ${BOLD}\"Connect to ELM and list my projects\"${RESET}"
say ""
say "${BOLD}If your AI doesn't see the MCP server after restart${RESET} (e.g. some IBM Bob"
say "deployments don't auto-load configs), paste the JSON below into the right"
say "config file for your host. The two paths in it are already filled in for"
say "your machine."
say ""
say "${BOLD}Where the file goes${RESET} (create it if missing):"
say "  • IBM Bob (recommended):  ${BOLD}~/.bob/mcp_settings.json${RESET}"
say "  • Claude Code:            ${BOLD}~/.claude.json${RESET}"
say "  • VS Code:                ${BOLD}<your-project>/.vscode/mcp.json${RESET}  (uses 'servers' key, not 'mcpServers')"
say "  • Cursor:                 ${BOLD}~/.cursor/mcp.json${RESET}"
say "  • Windsurf:               ${BOLD}~/.codeium/windsurf/mcp_config.json${RESET}"
say ""
say "${BOLD}JSON to paste${RESET} (top-level key 'mcpServers' for Bob/Claude/Cursor/Windsurf;"
say "VS Code uses 'servers' instead):"
say ""
cat <<JSON
{
  "mcpServers": {
    "elm-mcp": {
      "command": "$PY_ABS",
      "args": [
        "$SERVER_ABS"
      ],
      "alwaysAllow": [
        "connect_to_elm", "list_projects", "list_capabilities",
        "elm_mcp_health", "update_elm_mcp",
        "get_modules", "get_module_requirements", "search_requirements",
        "get_artifact_types", "get_link_types",
        "get_attribute_definitions", "find_folder",
        "list_baselines", "compare_baselines", "extract_pdf",
        "resolve_requirement_id", "resolve_user",
        "get_ewm_workitem_types", "get_workflow_states",
        "query_work_items",
        "list_test_cases", "list_test_plans",
        "list_test_execution_records",
        "list_global_configurations", "list_global_components",
        "get_global_config_details",
        "scm_list_projects", "scm_list_changesets",
        "scm_get_changeset", "scm_get_workitem_changesets",
        "review_get", "review_list_open",
        "build_new_project", "build_from_existing",
        "build_project_next", "build_project_status",
        "build_project_resume", "wrap_up_session",
        "get_team_actions", "generate_traceability_matrix"
      ]
    }
  }
}
JSON
say ""
say "${BOLD}Your filled-in paths (you can also copy these directly):${RESET}"
say "  Python interpreter:  ${BOLD}$PY_ABS${RESET}"
say "  Server script:       ${BOLD}$SERVER_ABS${RESET}"
say ""
say "  ${DIM}To update later: re-run this same curl command, or:${RESET}"
say "    ${DIM}cd \"$INSTALL_DIR\" && git pull && $PY setup.py${RESET}"
say "  ${DIM}Or just talk to your AI: \"update yourself\" (uses the update_elm_mcp tool).${RESET}"
say ""
