# Lab 1: Install elm-mcp

**Time:** 5 minutes
**Prerequisites:** [Lab 0](../lab-00-prerequisites/) complete
**Learning objective:** Get elm-mcp installed, configured, and its modes loaded — in one command.

---

## The one-command install

**macOS / Linux** — open Terminal, paste this, hit Enter:

```bash
curl -fsSL https://raw.githubusercontent.com/brettscharm/elm-mcp/main/install.sh | bash
```

**Windows** — open PowerShell, paste this, hit Enter:

```powershell
irm https://raw.githubusercontent.com/brettscharm/elm-mcp/main/install.ps1 | iex
```

That single command does **everything**:

1. Downloads elm-mcp to `~/.elm-mcp`
2. Installs all Python dependencies
3. Prompts you for your ELM URL, username, and password (typed at the prompt — saved locally only, never sent anywhere except your own ELM server)
4. Writes Bob's MCP config automatically (`~/.bob/settings/mcp_settings.json`)
5. **Auto-installs the 5 custom modes** (Concierge, Plan, Push, Impact Analyst, Compliance Auditor) — merging them into Bob's modes config and copying their playbooks
6. Runs an end-to-end smoke test to confirm it all works

When it finishes, you'll see a green "Setup complete" with next steps.

> **Modes are installed automatically.** In older versions of these labs, Lab 3 walked you through manually pasting YAML and copying playbook folders. As of v0.23.1, the installer does it for you. Lab 3 is now just a verify-and-understand step.

---

## Then: fully quit and reopen Bob

Bob only loads MCP servers and custom modes at startup — you have to actually quit, not just close the window.

- **macOS:** Cmd + Q, then reopen
- **Windows:** right-click the Bob tray/taskbar icon → Quit (or Alt+F4), then reopen
- **VS Code / Cursor (any OS):** reload the window — `Ctrl/Cmd-Shift-P` → "Developer: Reload Window"

---

## Verify

In Bob, type:

```
Run elm_mcp_health
```

Expected output:

```
# ELM MCP — Health Check
Version: v0.23.1 (or later)
Install dir: /Users/<you>/.elm-mcp
Git status: git-managed (auto-update available)

## Connection
- State: connected
- ELM URL: https://...
- User: ...
```

Then check the modes loaded — look at Bob's mode picker (top of the chat panel). You should see:

- 🧭 ELM Concierge
- 📝 Plan Requirements
- 📤 Push Requirements
- 🎯 Impact Analyst
- 📜 Compliance Auditor

If you see the health check pass AND the modes in the picker, **you're done with install.** That's it.

---

## Common pitfalls

### "Bob doesn't see the server after restart"

Some Bob deployments don't auto-load new MCP config entries. The installer prints a JSON block at the end with your exact paths filled in. Open Bob → Settings → MCP Servers → Add Server and use:

- **Name:** `elm-mcp`
- **Command:** (the Python path the installer printed)
- **Args:** (the server path the installer printed)

Then restart Bob again.

### "The one-liner doesn't prompt for my password" / "execution blocked"

The one-liners handle the credential prompt automatically. If your environment blocks them (corporate-locked terminal, no controlling TTY, PowerShell execution policy), use the manual two-step path — works on every OS:

**macOS / Linux:**
```bash
git clone https://github.com/brettscharm/elm-mcp.git ~/.elm-mcp
cd ~/.elm-mcp
python3 setup.py
```

**Windows (PowerShell):**
```powershell
git clone https://github.com/brettscharm/elm-mcp.git $HOME\.elm-mcp
cd $HOME\.elm-mcp
py setup.py
```

Same result — `setup.py` is the cross-platform workhorse the one-liners just wrap.

### "Modes didn't show up in the picker"

Two checks:

1. Did you fully quit Bob and reopen? Modes load at startup only.
2. Re-run just the mode install:
   ```bash
   python3 ~/.elm-mcp/setup.py --modes-only      # macOS/Linux
   py %USERPROFILE%\.elm-mcp\setup.py --modes-only   # Windows
   ```
   This re-installs the 5 modes without redoing the whole setup.

### "ELM connection failed: authentication error"

- Wrong username/password — re-run `python3 ~/.elm-mcp/setup.py` and re-enter
- Your account requires an app password (MFA enabled) — generate one in your ELM profile
- Corporate SAML deployments sometimes need extra config — check with your ELM admin

### "Server version too old"

Tell Bob:

```
Update elm-mcp
```

The `update_elm_mcp` tool pulls the latest release in one shot.

---

## Diagnosing problems

If anything's off, run:

```bash
python3 ~/.elm-mcp/setup.py --diagnose
```

It re-runs the dependency check, MCP handshake test, and credential check, and tells you in plain English what's wrong.

---

## Updating later

Any of these update you to the latest:

```bash
# Re-run the installer (idempotent — updates in place)
curl -fsSL https://raw.githubusercontent.com/brettscharm/elm-mcp/main/install.sh | bash

# OR from the install dir
cd ~/.elm-mcp && git pull && python3 setup.py

# OR just ask Bob
# "update yourself"
```

---

## Try it yourself

Run `list_capabilities` in Bob. You'll see the full tool inventory (80+ tools) grouped by domain. We'll work through the most useful ones in the rest of the series.

---

## What's next

→ [Lab 2: Connect to ELM](../lab-02-connect-to-elm/)

The installer already entered your credentials, so Lab 2 is mostly about confirming you can see your real ELM data through Bob.
