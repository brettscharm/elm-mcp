# Bob Custom Modes — Plan Requirements + Push Requirements

Two custom modes that turn IBM Bob into a rigorous requirements-engineering partner:

- **📝 Plan Requirements** — staging area where you draft, iterate, lint, and critique requirements. **Nothing goes to DNG.** Bob acts like a senior systems engineer in a requirements review: asks many questions, pushes back on weak language, maintains a running plan with quality scores.
- **📤 Push Requirements** — boring commit mode. Takes the finalized plan, batch-pushes to DNG, runs an audit, hands back the URLs. No iteration here.

The user **swaps modes** when ready: spend as much time as needed in Plan Mode, say `/push` or "ship it", swap to Push Mode, one confirmation, done.

---

## What's in this folder

```
modes/
├── README.md                       ← you are here
├── custom_modes.yaml               ← paste into Bob's modes config
└── rules/
    ├── rules-requirements-planner/
    │   └── 01-playbook.md          ← long-form Plan Mode rules
    └── rules-requirements-pusher/
        └── 01-playbook.md          ← long-form Push Mode rules
```

---

## Installation — 3 steps

### Step 1 — Add the modes to Bob

Open Bob → **Settings → Modes → Edit Global Modes**.

Paste the contents of `custom_modes.yaml` into the editor. Save.

> If you only want these modes in a specific project (not globally), put the YAML at `.bob/custom_modes.yaml` inside that project's repo instead.

### Step 2 — Add the playbook files

Bob reads supplemental long-form instructions from `.bob/rules-{mode-slug}/` directories in the project root.

From the project root where you want these modes active (or your home dir for global), run:

```bash
mkdir -p .bob/rules-requirements-planner .bob/rules-requirements-pusher
cp modes/rules/rules-requirements-planner/01-playbook.md .bob/rules-requirements-planner/
cp modes/rules/rules-requirements-pusher/01-playbook.md .bob/rules-requirements-pusher/
```

Final structure on disk:

```
<your-project>/
├── .bob/
│   ├── custom_modes.yaml                          (optional — only if scoped to this project)
│   ├── rules-requirements-planner/
│   │   └── 01-playbook.md
│   └── rules-requirements-pusher/
│       └── 01-playbook.md
└── ... (rest of your project)
```

### Step 3 — Verify

In Bob, type `/plan` or "plan mode" or "let's plan some requirements." You should see Bob enter Plan Mode and ask the **risk classifier** question:

> Before we start — quick calibration: what's the risk profile of this work? (A) Critical / (B) Important / (C) Light…

If you see that, you're set. If not, check that:

1. The YAML pasted into Bob's modes config has no syntax errors (try `yamllint` on it).
2. The rules files are at the exact paths shown above — Bob is path-sensitive.
3. Bob has access to the elm-mcp MCP server (Plan Mode uses `lint_requirements_batch`, `get_attribute_definitions`, `extract_pdf`, etc.).

---

## How to use Plan Mode

```
User:  /plan
Bob:   📝 Plan Mode active.
       Before we start — quick calibration: what's the risk profile of this work?
       (A) Critical — regulated, safety/security/financial, external audit. FULL RIGOR.
       (B) Important — customer-facing, revenue-impacting, not regulated. STANDARD RIGOR.
       (C) Light — internal tool, low blast radius. LIGHT RIGOR.

User:  B

Bob:   Locked in: Standard rigor. Now — who's writing the first draft?
       (1) I draft a starter set from your feature description
       (2) You write each draft, I critique
       (3) Mixed — you give me 1-2, I extrapolate, you prune
       (4) Extract from a source document — PDF, Word, text, pasted
       (5) Seed from an existing DNG module — I'll read it and load reqs as drafts

User:  4. I have a PDF at /Users/me/Downloads/spec.pdf

Bob:   Calling extract_pdf… found 17 candidate requirements. Here's the list…
       [continues through context gate, discipline interview, drafting, lint,
        running-plan reprint every turn]

User:  /push

Bob:   Switching to Push Requirements mode…

       [Push Mode] 📤 About to push 14 requirements to module
       "Temperature Converter Reqs" in project "WatsonX AI POC".
       Lint summary: avg 89/100, 0 🔴 findings.
       Confirm to push, or /back to keep iterating.

User:  Confirm.

Bob:   [calls create_requirements in one batch]
       ✓ Pushed 14 reqs. URLs:
       1. <dng-url>
       2. <dng-url>
       …
       [calls audit_module automatically]
       Quality audit: 12 good · 2 fair · 0 weak · 0 poor.
       For semantic scoring, open these in Requirements Quality Assistant
       (IBM ELM AI Hub).
```

---

## What you get vs. what you don't

### You get

- 30-50 questions for high-rigor work, 4-8 for light work (risk-classifier-calibrated)
- A persistent **running plan** visible every turn, with lint scores per draft
- **Five authorship paths**: Bob drafts / user drafts / mixed / PDF-or-file import / DNG module seeding
- **Compliance-aware questioning**: ISO 26262, IEC 62304, DO-178C, HIPAA, GDPR, WCAG, SOC2, PCI-DSS unlock standard-specific question banks
- **Contradiction detection** across drafts
- **Persona reviews** (security / UX / compliance / ops)
- **Saturation detection** — interview wraps when answers stop changing the plan
- **Override logging** — if the user fast-paths a gate, it's recorded in the plan header
- **Save / resume** via JSON paste-back across sessions

### You don't get (yet)

- True multi-user collaboration — Plan Mode is per-chat-session
- Multi-module plans — one plan = one target module
- Cross-requirement link metadata (Satisfies / Elaborates) — drafts ship without links; add via `create_link` after push
- A persistent manager review-packet generator — currently the running plan IS the packet; a polished HTML export would be a future MCP tool
- An elicitation sub-mode — Plan Mode helps you DRAFT, not INTERVIEW an SME

---

## How this connects to the rest of elm-mcp

Plan Mode is **persona-only** — it doesn't add new MCP tools. It uses tools that already exist in the elm-mcp server:

| Tool | Used for |
|---|---|
| `lint_requirements_batch` | Per-draft quality scoring (called continuously) |
| `get_attribute_definitions` | Discovering project-specific attributes for the Context Gate |
| `get_artifact_types` | Showing the user what artifact types are valid |
| `get_modules` | Looking up the target module |
| `get_module_requirements` | Authorship branch (5) — seeding the plan from an existing DNG module |
| `extract_pdf` | Authorship branch (4) — PDF source documents |
| `list_projects` | Resolving the target project |
| `create_requirements` | Push Mode only — one batch call |
| `update_requirement` | Push Mode only — for drafts seeded from existing DNG reqs |
| `create_module` | Push Mode only — if the target module doesn't exist yet |
| `audit_module` | Post-push, automatic |

If any of those tools are missing or broken, the mode will degrade gracefully but lose features. The Plan Mode playbook tells Bob to surface the degradation rather than silently skip checks.

---

## Versioning

These modes are versioned with the elm-mcp release they were authored against. Current target: **elm-mcp v0.15.0+**.

If you upgrade elm-mcp and the modes start behaving oddly, re-pull this folder and re-paste — the playbook may have changed to match new tool signatures.
