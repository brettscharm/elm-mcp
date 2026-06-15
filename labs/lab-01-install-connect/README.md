# Lab 1: Install & connect

**Part 1 · Get running**
**Time:** 15 minutes · **Prerequisites:** none
**Outcome:** elm-mcp installed, the 5 modes loaded, connected to ELM, and you can see your real projects.

---

## What you need first

- **IBM Bob** (or any MCP host: Claude Code, Cursor, VS Code with the Claude extension, Windsurf). This series is written for Bob.
- **Python 3.9+** — `python3 --version` (macOS/Linux) or `py --version` (Windows). 3.11+ recommended.
- **Git** — `git --version`. On Windows, get it from [git-scm.com](https://git-scm.com/download/win).
- **ELM credentials** — your server URL (e.g. `https://yourco.elm.ibmcloud.com`), username, and password. Same login that works in the DOORS Next browser.

> On Windows: when you install Python, **check "Add Python to PATH"** in the installer.

If you don't have an ELM environment, ask your admin for a sandbox project, or use IBM's hosted trial. You can do Lab 1 either way; Labs 2+ need live access.

---

## Step 1 — install (one command)

**macOS / Linux** — open Terminal, paste, Enter:

```bash
curl -fsSL https://raw.githubusercontent.com/brettscharm/elm-mcp/main/install.sh | bash
```

**Windows** — open PowerShell, paste, Enter:

```powershell
irm https://raw.githubusercontent.com/brettscharm/elm-mcp/main/install.ps1 | iex
```

That single command:
1. Downloads elm-mcp to `~/.elm-mcp`
2. Installs dependencies
3. Prompts for your ELM URL / username / password (saved locally only — never sent anywhere except your own ELM server)
4. Writes Bob's MCP config automatically
5. **Installs the 5 custom modes** (Concierge, Plan, Push, Impact Analyst, Compliance Auditor) — your other modes are preserved
6. Runs an end-to-end smoke test

---

## Step 2 — fully quit and reopen Bob

Bob only loads MCP servers and modes at startup.

- **macOS:** Cmd + Q, then reopen
- **Windows:** right-click the tray/taskbar icon → Quit (or Alt+F4), then reopen
- **VS Code / Cursor:** reload the window — `Ctrl/Cmd-Shift-P` → "Developer: Reload Window"

---

## Step 3 — verify

In Bob, type:

```
Run elm_mcp_health
```

You want to see `State: connected` and a version number.

Then check the mode picker (top of the chat panel) — you should see the 5 modes:
🧭 ELM Concierge · 📝 Plan Requirements · 📤 Push Requirements · 🎯 Impact Analyst · 📜 Compliance Auditor

Finally, the real test:

```
Connect to ELM and list my projects.
```

Bob should respond with your DNG projects. **If you see your projects, you're done.**

---

## Verify checklist

- ✅ `elm_mcp_health` returns `State: connected`
- ✅ 5 custom modes appear in Bob's mode picker
- ✅ "list my projects" shows your real DNG projects

---

## Common pitfalls

**Bob doesn't see the server after restart.** Some Bob deployments don't auto-load new MCP config. The installer printed a JSON block with your exact paths — open Bob → Settings → MCP Servers → Add Server and paste the Name / Command / Args from it, then restart again.

**"Missing dependencies" / Bob can't figure out what to install.** You don't have to — the server **self-heals**. The first time it starts with a Python that's missing dependencies, it installs them into that exact interpreter and restarts itself (you'll see `[elm-mcp] Auto-installing…` in Bob's MCP output panel; it takes ~20–30s the first time, then it's instant). If you ever see it give up after that, it prints the one command to run by hand — copy it as-is (it already points at the right Python).

**The one-liner didn't prompt for my password / execution blocked.** Use the manual path (every OS):
```bash
git clone https://github.com/brettscharm/elm-mcp.git ~/.elm-mcp
cd ~/.elm-mcp && python3 setup.py      # py setup.py on Windows
```

**Modes didn't show up.** Did you fully quit Bob? If still missing, re-install just the modes:
```bash
python3 ~/.elm-mcp/setup.py --modes-only
```

**Authentication error.** Wrong password, an MFA account that needs an app password, or a SAML deployment that needs admin help. Re-run `setup.py` to re-enter credentials.

**Something's off and I can't tell what.** Run the built-in diagnostics:
```bash
python3 ~/.elm-mcp/setup.py --diagnose
```
Or, once connected, ask Bob to **"run a self test"** — it exercises ~20 read paths and gives you a green/red scorecard.

---

## Updating later

Any of these get you the latest:
```bash
curl -fsSL https://raw.githubusercontent.com/brettscharm/elm-mcp/main/install.sh | bash   # re-run, idempotent
# or just ask Bob: "update yourself"
```

---

## What's next

→ [Lab 2: Talk to your ELM data](../lab-02-talk-to-your-data/)

Now the fun part — ask Bob about your real ELM data in plain English.
