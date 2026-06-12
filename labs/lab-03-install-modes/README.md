# Lab 3: Verify the custom modes

**Time:** 5 minutes
**Prerequisites:** [Lab 2](../lab-02-connect-to-elm/) complete (can list ELM projects)
**Learning objective:** Confirm the 5 custom Bob modes loaded, and understand what each one does.

---

## Good news: the modes are already installed

The installer in Lab 1 (`install.sh` / `setup.py`) **auto-installs the modes** — it merges them into Bob's `custom_modes.yaml` and copies the playbook files. You don't have to paste or copy anything.

This lab just confirms they loaded and explains what they're for.

> **Manual install only if you skipped it:** if you ran setup with `--no-modes`, or you're on a host that isn't Bob, see the "Manual install" section at the bottom.

---

## The 5 modes

| Mode | What it does | You'll use it in |
|---|---|---|
| 🧭 **ELM Concierge** | Default front door — interprets plain English, routes to the right mode/tool | Lab 4 |
| 📝 **Plan Requirements** | Staging area for drafting requirements with rigor before they touch DNG | Lab 6 |
| 📤 **Push Requirements** | Boring commit step — batch-pushes a finalized plan to DNG | Lab 6 |
| 🎯 **Impact Analyst** | Analyzes a change's blast radius across the trace graph | Lab 11 |
| 📜 **Compliance Auditor** | Generates audit-ready compliance packets (NIST 800-53, IEC 62304) | Lab 13 |

Together they're the discoverability + UX layer over the 79 raw MCP tools. Without them you'd have to know tool names. With them, you type plain English.

---

## Steps

### 1. Open Bob's mode picker

It's usually at the top of the chat panel, or under Settings → Modes.

### 2. Confirm all 5 modes are listed

You should see all of these alongside Bob's built-in modes (Code, Ask, Plan, Advanced, Orchestrator):

- 🧭 ELM Concierge
- 📝 Plan Requirements
- 📤 Push Requirements
- 🎯 Impact Analyst
- 📜 Compliance Auditor

### 3. Activate Plan Mode to test

```
/plan
```

You should see 📝 Plan Requirements activate with its risk-classifier question:

```
📝 Plan Mode active. Risk tier? (A) Critical (B) Important (C) Light.
```

### 4. Exit cleanly

```
/discard
```

then switch to Concierge:

```
/concierge
```

---

## Verify

- ✅ All 5 modes appear in the mode picker
- ✅ `/plan` activates 📝 Plan Requirements with the risk-classifier question
- ✅ You can switch between modes

If all three pass, you're ready for Lab 4.

---

## Common pitfalls

### "I don't see the modes in the picker"

Most likely: you didn't fully quit Bob after install. Cmd+Q and reopen — modes load at startup only.

If they're still missing, re-run just the mode install:

```bash
python3 ~/.elm-mcp/setup.py --modes-only
```

Then quit + reopen Bob.

### "`/plan` enters Bob's built-in Plan mode, not the elm-mcp one"

Bob has its own built-in Plan mode for general planning. Ours is "📝 Plan Requirements" — same slash command, different mode. If you see Bob asking "what should I plan?" instead of the risk-classifier (A/B/C) question, you got the built-in. Pick "📝 Plan Requirements" specifically from the mode picker.

### "I see old/duplicate versions of the modes"

The installer replaces its own modes on each run (it owns the slugs `concierge`, `requirements-planner`, `requirements-pusher`, `impact-analyst`, `compliance-auditor`) and preserves all your other modes. If you see duplicates, you may have hand-pasted them before. Re-run:

```bash
python3 ~/.elm-mcp/setup.py --modes-only
```

It de-dupes by replacing.

---

## Manual install (only if you skipped auto-install)

If you ran setup with `--no-modes`, or you want to install modes into a project-scoped `.bob/` instead of global:

### Option A — re-run the auto-installer

```bash
python3 ~/.elm-mcp/setup.py --modes-only
```

### Option B — fully manual

1. Open `~/.elm-mcp/modes/custom_modes.yaml`
2. In Bob → Settings → Modes → Edit Global Modes, paste its `customModes:` entries (merge with any existing modes — don't clobber)
3. Copy the playbooks:
   ```bash
   for slug in concierge requirements-planner requirements-pusher impact-analyst compliance-auditor; do
     mkdir -p ~/.bob/rules-$slug
     cp ~/.elm-mcp/modes/rules/rules-$slug/01-playbook.md ~/.bob/rules-$slug/
   done
   ```
4. Quit + reopen Bob

---

## Try it yourself

In Concierge, type:

```
What can you help me with?
```

You'll get a curated list of what elm-mcp can do — Concierge knows the whole toolset.

---

## What's next

→ [Lab 4: Natural-language routing with Concierge](../lab-04-concierge-routing/)

Now we'll see the whole point of the modes — typing plain English and watching Bob route to the right place.
