# Lab 1: Install elm-mcp

**Time:** 10 minutes
**Prerequisites:** [Lab 0](../lab-00-prerequisites/) complete
**Learning objective:** Get the elm-mcp server installed and registered with Bob.

---

## What you're installing

`elm-mcp` is a Python-based MCP server. The install script:

1. Clones the repo to `~/.elm-mcp/` (or updates an existing clone)
2. Installs Python dependencies
3. Writes a config entry to Bob's settings telling it where to find the server
4. Verifies the server starts and Bob can talk to it

Total disk usage: ~30 MB.

---

## Steps

### 1. Clone the repo

Pick a working directory and clone:

```bash
cd ~
git clone https://github.com/brettscharm/elm-mcp.git
cd elm-mcp
```

### 2. Run the setup script

```bash
python3 setup.py
```

What you'll see:

- The script asks for your ELM URL, username, and password (saves them to `~/.elm-mcp/.env`)
- It installs Python dependencies via `pip`
- It writes Bob's MCP config (location varies by host — `~/.claude.json` for Claude Code, `~/.cursor/mcp.json` for Cursor, etc.)
- It verifies the server starts end-to-end

Setup is interactive — answer the prompts. Most defaults are correct.

### 3. Restart your MCP host

For Bob (and most other hosts), you need to restart the app to pick up the new MCP server:

- **IBM Bob** — quit and re-open
- **Cursor / VS Code** — reload the window (Cmd-Shift-P → "Developer: Reload Window")
- **Claude Code** — start a new session

### 4. Verify the server is registered

In Bob, type:

```
What MCP servers are connected?
```

OR check Bob's MCP / settings panel.

You should see `elm-mcp` (or whatever you named it during setup) listed.

### 5. Run the health check

In Bob, type:

```
Run elm_mcp_health
```

Bob calls the `elm_mcp_health` tool. Expected output:

```
# ELM MCP — Health Check
Version: v0.22.1 (or later)
Install dir: /Users/<you>/.elm-mcp
Git status: git-managed (auto-update available)

## Connection
- State: connected
- ELM URL: https://...
- User: ...

## Updates
- Auto-update enabled: True
- Last check: ...
```

---

## Verify

You should see all three of these:

- ✅ `python3 ~/.elm-mcp/setup.py --diagnose` exits without errors
- ✅ `elm_mcp_health` tool returns a "connected" state
- ✅ Bob sees `elm-mcp` listed in its connected MCP servers panel

If any of these fail, see Common Pitfalls below.

---

## Common pitfalls

### "Bob doesn't see the server after restart"

The MCP config got written to the wrong file. Run setup with `--host` to target your specific host:

```bash
python3 setup.py --host bob       # or claude / cursor / vscode
```

### "Setup script complains about missing pip packages"

You might be in a Python virtualenv that doesn't have permissions. Either:

- Run `python3 -m pip install --user -r requirements.txt` first
- Or deactivate the virtualenv and use system Python: `deactivate && python3 setup.py`

### "ELM connection failed: authentication error"

Three likely causes:

- Wrong username or password — re-run setup and re-enter
- Your account requires an app password (MFA-enabled) — generate one in your ELM profile
- Your ELM server requires Form auth, not Basic — setup tries both, but corporate SAML deployments sometimes need extra config. Check with your ELM admin.

### "Server version too old"

If `elm_mcp_health` shows v0.21 or older, tell Bob:

```
Update elm-mcp
```

The `update_elm_mcp` tool pulls the latest release in one shot.

---

## Try it yourself

Run `list_capabilities` in Bob. You'll see all 79 tools grouped by domain — this is the full inventory of what elm-mcp can do. We'll work through the most useful ones in the rest of this series.

---

## What's next

→ [Lab 2: Connect to ELM](../lab-02-connect-to-elm/)
