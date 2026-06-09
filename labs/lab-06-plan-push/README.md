# Lab 6: Plan + Push requirements

**Time:** 30 minutes
**Prerequisites:** [Lab 5](../lab-05-read-requirements/) complete (DNG read flow understood)
**Learning objective:** Run a full Plan Mode session against a feature description and push the polished requirements to a sandbox DNG module.

---

## ⚠️ This lab WRITES to DNG

Up until now everything has been read-only. This lab pushes real requirements to a real DNG module. **Use a sandbox project for the first run.** If you don't have a sandbox, create a test module in any project you have write access to — Plan Mode's discipline keeps the output high-quality regardless.

You can also stop after the planning phase and `/discard` without ever pushing. The plan exists only in chat context.

---

## What you're doing

Plan + Push is the highest-value workflow elm-mcp adds. It replaces "type a req → Bob writes it → push" (which produces vague reqs) with:

1. **Phase 1 — Setup** (5-6 batched questions)
2. **Phase 2 — Decomposition** (Bob enumerates ~10-35 candidate reqs from your input)
3. **Phase 3 — Deep-drill loop** (one candidate at a time, batched elicitation, draft strictly, lint, lock, next)
4. **Phase 4 — Wrap** (out-of-scope, contradiction check, ready-for-push)
5. **Then 📤 Push Mode** — one confirmation, batch-creates everything in DNG, runs an audit

Total turn count: ~10-15 turns from "start" to "shipped + audited."

---

## Steps

### 1. Enter Plan Mode

```
/plan
```

OR through Concierge:

```
Help me draft requirements for a feature.
```

Plan Mode's entry sequence starts:

```
📝 Plan Mode active. Risk tier? (A) Critical (B) Important (C) Light.
```

### 2. Answer the risk classifier

For this lab, pick **(B) Important**. This calibrates Plan Mode to ask 3-6 elicitation questions per candidate — enough rigor to see how the flow works without being exhausting.

### 3. Answer the setup batch

Plan Mode asks 5 questions in one batch. Paste these answers (adapted for your environment):

```
a. Source: building from a feature description.
b. Domain: e-commerce backend.
c. Compliance: none.
d. Stakeholders: dev team + QA + tech lead.
e. Target: <your DNG project> > <a sandbox module — give a name like "Lab 6 Practice">.
```

If you specify a module that doesn't exist yet, Push Mode will create it for you in step 9.

### 4. Provide the feature description

When Plan Mode asks "what are we building?", paste this practice feature:

```
A real-time stock availability API for an e-commerce site. The backend
must call our supplier's inventory system (Blue Yonder), with a
local cache (Couchbase) for fallback when Blue Yonder is slow. The API
needs to support manual overrides for business users to mark SKUs
unavailable. Built on Spring WebFlux, deployed to AKS.
```

This is similar to a real Jira ticket — meaty enough to produce ~20-25 candidate requirements.

### 5. Confirm the decomposition

Plan Mode will respond with a list like:

```
📋 I count ~22 candidate requirements:

A. Availability Check API (4)
  A1. Endpoint contract
  A2. Latency SLA
  A3. Source of truth resolution
  A4. Response shape

B. Business Overrides (5)
  B1. Override CRUD
  ...
```

Review the list. Add anything missing, remove anything irrelevant, or just say `go` to start drilling.

### 6. Run through the deep-drill loop

For each candidate, Plan Mode will:

- Print a header with the candidate's category and any tech-stack hints
- Ask 3-6 elicitation questions in ONE batched turn
- Wait for your answers
- Draft the requirement strictly (`shall`, quantified, testable)
- Run lint via `lint_requirements_batch`
- Show the polished req + lint score
- Move to the next candidate

**Answer the questions as if you were the product owner.** Pick reasonable numbers (200 ms p95, 5000 RPS peak, etc.). You don't have to be 100% right — Plan Mode's job is to extract YOUR intent.

You'll see the running plan footer update after every locked requirement:

```
📋 Plan — Stock Availability API (4/22 · avg 89/100)
A. Availability Check API
  A1. ✅ Endpoint contract — 95/100
  A2. ✅ Latency SLA — 92/100
  A3. ⏳ next: Source of truth
  ...
```

### 7. Pause whenever you want (optional)

If you need to stop, type `/save`. Plan Mode prints the entire plan as a JSON blob. Paste it back in a future session with `/resume <JSON>` to continue exactly where you left off.

For this lab, push through to ~10 locked requirements (you don't need all 22 — partial is fine).

### 8. Wrap-up phase

When you've locked enough requirements, type:

```
That's enough — wrap it up.
```

Plan Mode runs the wrap phase: out-of-scope prompt → contradiction check → coverage check → ready-for-push check.

### 9. Push to DNG

```
/push
```

OR Concierge / mode picker → 📤 Push Requirements.

Push Mode shows a single confirmation line:

```
📤 Push Mode active. About to push 10 requirements to module
"Lab 6 Practice" in project <your project>. Lint summary: avg 89/100,
0 🔴 findings. Confirm to push, or /back to keep iterating.
```

If you want to actually push, type:

```
Confirm
```

Push Mode will:

- Create the module if it doesn't exist
- Make one batch `create_requirements` call
- Print every DNG URL for the new reqs
- Automatically call `audit_module` and show the quality distribution
- Point you at the Requirements Quality Assistant agent in IBM ELM AI Hub for AI semantic scoring

If you DON'T want to push (this is a lab after all), type:

```
/back
```

You're back in Plan Mode with the plan intact.

---

## Verify

You should have seen:

- ✅ Risk classifier + 5-question setup batch (in one turn)
- ✅ Decomposition list with ~22 candidates organized into ~6-8 categories
- ✅ Per-candidate deep-drill — batched elicitation questions, polished draft, lint score
- ✅ Running plan footer updating after every locked requirement
- ✅ Wrap phase (out-of-scope, contradictions, coverage)
- ✅ Push confirmation line in 📤 mode
- ✅ (If you pushed) DNG URLs + automatic audit report

---

## Common pitfalls

### "Plan Mode is asking too many questions"

Down-shift the risk tier with `/downgrade`. Critical = 5-10 Qs per candidate, Important = 3-6, Light = 2-4.

### "Bob drafted user stories instead of requirements"

That's a v0.16.0 bug. Update to v0.16.1+. Plan Mode is now locked to System Requirement + Non-Functional Requirement + Stakeholder Requirement only — no user stories, no epics, no test cases.

### "I want to add more reqs after pushing"

Just run /plan again with a follow-up description. The new plan can target the same module — Push Mode appends.

### "Push said 'module doesn't exist'"

Confirm "yes" when Push Mode offers to create it. The flow is automatic.

### "I want to skip the interview and just generate reqs"

You can say "fast-path the setup" — Plan Mode will use defaults and log the override in the plan header. Not recommended for the first time through, but available.

### "The reqs look generic / vague"

Three possibilities:
- You answered the elicitation questions vaguely. Plan Mode mirrors what you give it. Be specific.
- You're on the Light tier with too few elicitation Qs. Use `/upgrade` to bump to Important.
- The draft is fine but you need more context. Tell Bob: "Req #3 needs more about the failure mode" — Plan Mode will re-ask.

---

## Try it yourself

### Use a real Jira PDF instead

If you have a real Jira story PDF on disk, restart Plan Mode and answer step 3 with:

```
a. Source: PDF at /Users/me/Downloads/JIRA-123.pdf
```

Plan Mode will call `extract_pdf` and decompose from the actual content. This is the workflow you'll use in production.

### Resume across sessions

Run `/save` mid-session. Close Bob. Reopen tomorrow. Paste the JSON back with:

```
/resume <paste JSON>
```

You're back exactly where you left off, with the discipline interview skipped.

### Seed from an existing DNG module

If you want to revise existing reqs (not draft new ones), pick authorship option (5) "Seed from an existing DNG module" in the entry sequence. Plan Mode will pull the current reqs from DNG and load them as drafts you can edit. Push Mode then does `update_requirement` for the edits — no duplicates.

---

## What's next

You finished the v0.23.0 onboarding series. 🎉

**Coming next** in upcoming releases:

- **Lab 7** — Work items (EWM): query + create + transition workflow states
- **Lab 8** — Test cases (ETM): list + create + link to a req
- **Lab 9** — Cross-artifact (req ↔ WI ↔ TC): build the trace chain
- **Lab 10** — Traceability gaps: audit-readiness check
- **Lab 11** — Change impact analysis: 🎯 Impact Analyst
- **Lab 12** — Excel export
- **Lab 13** — Compliance packets: 📜 Compliance Auditor
- **Lab 14** — The build-project flow
- **Lab 15** — Bonus: ELM docs lookup
- **Lab 16** — Capstone: real-world scenario

Check https://github.com/brettscharm/elm-mcp/releases for new lab releases. Each release adds 1-3 labs.
