# Lab 3: Install the custom modes

**Time:** 10 minutes
**Prerequisites:** [Lab 2](../lab-02-connect-to-elm/) complete (can list ELM projects)
**Learning objective:** Install elm-mcp's 5 custom Bob modes so plain-English requests get routed correctly.

---

## What you're installing

elm-mcp ships **5 custom Bob modes** that work together as a discoverability + UX layer over the 79 raw MCP tools:

| Mode | What it does |
|---|---|
| 🧭 **ELM Concierge** | Default front door — interprets natural language and routes to the right mode or tool |
| 📝 **Plan Requirements** | Staging area for drafting requirements with rigor, before they touch DNG |
| 📤 **Push Requirements** | Deliberately boring commit step — batch-pushes a finalized plan to DNG |
| 🎯 **Impact Analyst** | Analyzes a change's blast radius across the trace graph |
| 📜 **Compliance Auditor** | Generates audit-ready compliance packets (NIST 800-53, IEC 62304) |

Without these modes, users have to know tool names. *With* them, users type plain English and Bob figures out what to do.

---

## Steps

### 1. Find the modes files in your clone

In Lab 1 you cloned the repo to `~/elm-mcp` (or wherever you chose). The files you need are at:

```
~/elm-mcp/modes/
├── custom_modes.yaml                              ← paste into Bob's modes config
└── rules/
    ├── rules-concierge/01-playbook.md             ← copy to .bob/rules-concierge/
    ├── rules-requirements-planner/01-playbook.md
    ├── rules-requirements-pusher/01-playbook.md
    ├── rules-impact-analyst/01-playbook.md
    └── rules-compliance-auditor/01-playbook.md
```

### 2. Paste the YAML into Bob's modes config

In Bob:

1. Open Settings → Modes → **Edit Global Modes**
2. Open `~/elm-mcp/modes/custom_modes.yaml` in a text editor
3. Copy the entire file contents
4. Paste into Bob's modes editor
5. Save

> If you only want these modes in one specific project (not globally), put the YAML at `.bob/custom_modes.yaml` inside that project's root instead. Global is recommended for the labs.

### 3. Drop the playbook files into `.bob/`

The mode YAML references long-form playbooks. Bob looks for them at `.bob/rules-{slug}/` in your project root, OR `~/.bob/rules/` for global.

For global install (recommended):

```bash
mkdir -p ~/.bob/rules-concierge ~/.bob/rules-requirements-planner ~/.bob/rules-requirements-pusher ~/.bob/rules-impact-analyst ~/.bob/rules-compliance-auditor

cp ~/elm-mcp/modes/rules/rules-concierge/01-playbook.md ~/.bob/rules-concierge/
cp ~/elm-mcp/modes/rules/rules-requirements-planner/01-playbook.md ~/.bob/rules-requirements-planner/
cp ~/elm-mcp/modes/rules/rules-requirements-pusher/01-playbook.md ~/.bob/rules-requirements-pusher/
cp ~/elm-mcp/modes/rules/rules-impact-analyst/01-playbook.md ~/.bob/rules-impact-analyst/
cp ~/elm-mcp/modes/rules/rules-compliance-auditor/01-playbook.md ~/.bob/rules-compliance-auditor/
```

For project-scoped install, replace `~/.bob/` with `<your-project>/.bob/`.

### 4. Reload Bob

How you reload depends on the host:

- **Bob native app** — quit and re-open
- **VS Code with Bob extension** — reload window (Cmd-Shift-P → "Developer: Reload Window")
- **Cursor** — same as VS Code

### 5. Confirm the modes are loaded

In Bob, look at the mode picker (usually at the top of the chat panel) or settings. You should see:

- 🧭 ELM Concierge
- 📝 Plan Requirements
- 📤 Push Requirements
- 🎯 Impact Analyst
- 📜 Compliance Auditor

…alongside Bob's built-in modes (Code, Ask, Plan, Advanced, Orchestrator).

---

## Verify

In Bob, type:

```
/plan
```

You should see 📝 Plan Requirements mode activate and Bob start its risk-classifier question:

```
📝 Plan Mode active. Risk tier? (A) Critical (B) Important (C) Light.
```

If yes — you're done. If Bob doesn't recognize `/plan` or stays in its default mode, the install didn't pick up.

Now exit Plan mode by typing `/discard` then `/concierge` (or just switch in the mode picker).

---

## Common pitfalls

### "Mode picker doesn't show the new modes"

Most common cause: YAML wasn't valid. Open the file in a YAML linter:

```bash
python3 -c "import yaml; yaml.safe_load(open('~/elm-mcp/modes/custom_modes.yaml'))"
```

If it errors, the file is corrupt. Re-pull:

```bash
cd ~/elm-mcp && git pull
```

Then re-paste.

### "`/plan` enters Bob's built-in Plan mode instead of mine"

Bob has its own built-in Plan mode for general planning. Our custom one is `requirements-planner` — same slash command, different mode. The mode picker disambiguates. If you see Bob asking "what should I plan?" instead of the risk-classifier question, you got the built-in. Look for "📝 Plan Requirements" specifically in the mode picker.

### "Playbook files at wrong path"

Bob is path-sensitive. The dir name MUST be `rules-{slug}` matching exactly the slug in the YAML. Check:

```bash
ls ~/.bob/
```

You should see exactly five `rules-*` directories matching the slugs above.

---

## Try it yourself

While in the default mode (or 🧭 Concierge), type:

```
What can you help me with?
```

If you're in Concierge, you'll get a curated list of what elm-mcp can do. If you're in another mode, the response will be more general.

---

## What's next

→ [Lab 4: Natural-language routing with Concierge](../lab-04-concierge-routing/)

Now that the modes are installed, we'll see the whole point of having a front door — typing plain English and watching Bob route to the right place.
