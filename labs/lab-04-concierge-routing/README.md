# Lab 4: Natural-language routing with Concierge

**Time:** 15 minutes
**Prerequisites:** [Lab 3](../lab-03-install-modes/) complete (modes installed)
**Learning objective:** Use 🧭 Concierge to interact with elm-mcp without memorizing tool names.

---

## What you're doing

🧭 ELM Concierge is the **default front door**. You type what you want in plain English; it interprets and routes you to the right specialized mode or tool. It uses four confidence levels:

| Level | What | Example |
|---|---|---|
| 1 — Auto-route | Strong signal, switch in one turn | "Generate NIST 800-53 packet for X" → 📜 Compliance Auditor |
| 2 — Suggest + confirm | Clear intent missing one parameter | "What does this change touch?" → "Share the URL and I'll swap to 🎯" |
| 3 — Disambiguate | Ambiguous, ask one labeled question | "Fix the audit thing" → 3 options |
| 4 — Step aside | Out of scope | "Why is my Java NPE?" → "Not elm-mcp territory" |

---

## Steps

### 1. Make sure you're in Concierge

If you're not already, switch:

```
/concierge
```

OR pick 🧭 ELM Concierge in the mode picker.

### 2. Try a Level 1 auto-route — direct project query

```
What DNG projects do I have?
```

Concierge recognizes this as a direct read call. It calls `list_projects(domain='dng')` and returns your project list. **No mode swap.** This is the simplest case: Concierge handles read calls itself.

### 3. Try a Level 1 auto-route — mode swap

```
Help me draft requirements for a temperature converter feature.
```

Concierge detects: "draft requirements" + a feature description = 📝 Plan Requirements. It should swap modes in the same turn. You'll see Plan Mode's entry sequence (risk classifier).

Type `/discard` to exit Plan Mode, then `/concierge` to come back.

### 4. Try a Level 2 suggest-and-confirm

```
What does my code change affect?
```

You didn't give Concierge the artifact. It should respond with something like:

```
Sounds like Impact Analysis — share the file path or req URL and I'll
swap to 🎯 Impact Analyst.
```

You can respond with a real URL or path, OR say "never mind" — Concierge stays put.

### 5. Try a Level 3 disambiguate

```
Make the auth module better.
```

This is ambiguous — "better" could mean quality, coverage, compliance, or rewrite. Concierge should respond with a labeled multiple-choice question:

```
What kind of 'better':
(1) Req quality / wording — audit_module
(2) Test coverage gaps — find_traceability_gaps
(3) Compliance coverage — 📜 Compliance Auditor
(4) Rewrite reqs to be sharper — 📝 Plan Requirements
```

Pick a number, see Concierge route.

### 6. Try a Level 4 step-aside

```
Why is my Java code throwing a NullPointerException?
```

Concierge should respond with something like:

```
That's not elm-mcp territory — outside my routing scope. Switch to
Bob's Code or Ask mode, or just ask without naming a mode.
```

This is correct behavior. Concierge knows its limits.

### 7. Try the power-user bypass

```
/build-new-project
```

Concierge sees a slash command, skips routing, hands off directly to the build flow. (You can `/cancel` if you don't actually want to start a build.)

---

## Verify

You should see all six of these:

- ✅ Direct read call returns data (step 2)
- ✅ Mode swap happens without confirmation when intent is clear (step 3)
- ✅ Concierge asks for the missing parameter (step 4)
- ✅ Disambiguation question with 3-4 labeled options (step 5)
- ✅ Step-aside response for non-ELM questions (step 6)
- ✅ Slash command bypass (step 7)

---

## Common pitfalls

### "Concierge doesn't seem to do anything special — it just answers the question"

You might not be in Concierge. Check the mode picker. If you're in Bob's default Ask mode, you'll get a generic response. Switch to 🧭 ELM Concierge.

### "Concierge tries to handle code questions itself"

Update to the latest version:

```
Update elm-mcp
```

Earlier versions of the Concierge playbook were too eager to help. The step-aside pattern was strengthened in v0.21.0.

### "Concierge routes me to the wrong mode"

Tell it. The playbook explicitly says "if a user pushes back, trust them — they know better than the routing table." Say:

```
No, I want to do [X] instead.
```

Concierge will re-route.

### "Bob asks too many questions before routing"

That's a design tradeoff — Concierge errs on the side of asking when it's not sure, because a wrong route costs more than an extra question. If it's truly excessive, file an issue with the prompt that triggered it.

---

## Try it yourself

Type any of these and see what happens:

- *"Are we audit-ready for NIST?"*
- *"Show me untested requirements in [your project]"*
- *"Export the auth module to Excel"*
- *"Where are the DXL docs?"*
- *"List my open work items"*

Each should auto-route to the right tool or mode in 1-2 turns.

---

## Try a worked example — docs lookup (preview of Lab 15)

```
Where's the IBM doc for DOORS Next baselines?
```

Concierge should auto-route to `get_elm_docs_links(topic="baseline")` and return the verified-live URL. Try this with any feature you wonder about — `get_elm_docs_links` has 79 curated URLs covering all of ELM.

---

## What's next

→ [Lab 5: Read requirements (DNG)](../lab-05-read-requirements/)

Now we'll go deeper into one of the most-used flows: reading and filtering DNG requirements.
