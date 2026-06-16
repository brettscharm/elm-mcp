# Lab 1: Install & connect

**Part 1 · Get running**
**Time:** 15 minutes · **Prerequisites:** none
**Outcome:** elm-mcp installed, the 5 modes loaded, connected to ELM, and you can see your real projects.

---

## What you need first

- **IBM Bob** (or any MCP host: Claude Code, Cursor, VS Code with the Claude extension, Windsurf). This series is written for Bob.
- **Python 3.10+** — `python3 --version` (macOS/Linux) or `py --version` (Windows). 3.11+ recommended. (The MCP SDK has no build for 3.9 — and macOS often ships an old 3.9, so install a newer one if `python3 --version` shows 3.9.x.)
- **Git** — `git --version`. On Windows, get it from [git-scm.com](https://git-scm.com/download/win).
- **ELM credentials** — your server URL (e.g. `https://yourco.elm.ibmcloud.com`), username, and password. Same login that works in the DOORS Next browser.

> On Windows: when you install Python, **check "Add Python to PATH"** in the installer.

If you don't have an ELM environment, ask your admin for a sandbox project, or use IBM's hosted trial. You can do Lab 1 either way; Labs 2+ need live access.

---

## Step 1 — install

### macOS / Linux — one command

Open Terminal, paste, Enter:

```bash
curl -fsSL https://raw.githubusercontent.com/brettscharm/elm-mcp/main/install.sh | bash
```

### Windows — 3 steps

The Windows one-liner is fragile on locked-down / corporate machines (a proxy can intercept the download and hand back a web page instead of the script, and an old bundled Python fails outright). Do these 3 steps instead — they always work:

1. **Install Python 3.10+.** Skip if `py --version` already prints 3.10 or newer. Otherwise get it from [python.org/downloads](https://www.python.org/downloads/windows/), run the installer, and **check "Add python.exe to PATH"** at the bottom *before* clicking Install. Close and reopen PowerShell afterward.
2. **Download the code.** [github.com/brettscharm/elm-mcp](https://github.com/brettscharm/elm-mcp) → green **Code** button → **Download ZIP** → right-click → **Extract All**. You'll get a folder named `elm-mcp-main`. **Keep it** — Bob runs the server from there.
3. **Run setup** in PowerShell:
   ```powershell
   cd $HOME\Downloads\elm-mcp-main
   py setup.py
   ```

### Either way, it:
1. Puts elm-mcp on your machine
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

**The installer failed on "externally-managed-environment" / pip install.** This is PEP 668 — on a fresh Mac, Homebrew/python.org Python 3.12+ refuses a plain `pip install`. As of **v0.31.1** the installer handles this automatically: it falls back through `--user`, `--break-system-packages`, and finally creates a dedicated virtualenv (`~/.elm-mcp/.venv`) and points Bob at it — no system packages touched. If you hit this on an older version, run `update_elm_mcp` (or re-run the installer) to get the fix.

**"Missing dependencies" / Bob can't figure out what to install.** You don't have to — the server **self-heals**. The first time it starts with a Python that's missing dependencies, it installs them into that exact interpreter and restarts itself (you'll see `[elm-mcp] Auto-installing…` in Bob's MCP output panel; ~20–30s the first time, then instant). If it gives up after that, it prints the one command to run by hand — copy it as-is (it already points at the right Python).

**Windows: the one-liner closed the window instantly, or printed a wall of red errors / "Redirecting…".** That's the `irm … | iex` one-liner failing, and it has two flavors:
- **Window closes instantly** → it hit an error and exited (most often: no Python 3.10+ installed).
- **Wall of red JavaScript errors, or `<title>Redirecting…</title>`** → a proxy (or a mistyped URL — note the dot in `raw.githubusercontent.com`) handed back a *web page* instead of the script, and PowerShell tried to run the page's HTML/JS.

Don't retry the one-liner — use the **3-step Windows path in Step 1** (install Python → download ZIP → `py setup.py`). It can't hit either problem.

**The one-liner didn't prompt for my password / execution blocked (any OS).** Use the manual path:
```bash
git clone https://github.com/brettscharm/elm-mcp.git ~/.elm-mcp
cd ~/.elm-mcp && python3 setup.py      # py setup.py on Windows
```
On Windows without git, download the ZIP instead (Step 1 → Windows → 3 steps) and run `py setup.py` from the extracted folder.

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
