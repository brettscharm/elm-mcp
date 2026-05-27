# 📤 Push Mode — Full Playbook

This file is supplemental long-form instructions for the `requirements-pusher` mode. The condensed rules already live in `custom_modes.yaml`'s `customInstructions:`. This file expands every step.

Push Mode is **deliberately boring**. The interesting work happened in Plan Mode. Push Mode commits.

---

## On entry

The user arrived from Plan Mode with a finalized draft list. Confirm the action in ONE line:

> 📤 **Push Mode active.** About to push **N requirements** to module **<M>** in project **<P>**.
>
> Compliance: <list from plan header>
> Stakeholders: <list>
> Lint summary: avg **X/100**, **Y 🔴** findings remaining
>
> Confirm to push, or `/back` to return to Plan Mode.

If you arrived without a draft list in chat context (the user entered Push Mode cold without a Plan Mode session), tell them to swap to Plan Mode first:

> No plan in context. Push Mode commits what Plan Mode produced — start with `/plan` and a feature description.

---

## Pre-push checks

Run before showing the confirmation line.

### Check 1 — does the target module exist?

Call `get_modules(project_identifier=<P>)`. If `<M>` is not in the list:

> Module **<M>** doesn't exist in **<P>** yet. I'll create it before pushing the requirements. Confirm?

On confirm: call `create_module` first, then push into the resulting module URL.

### Check 2 — is GCM active?

If the project has Global Configuration Management enabled and no stream is locked into the plan metadata, ask:

> This project has multiple GCM streams. Which stream should these push into? Default is the project's active stream.

Lock the user's choice into the push context.

### Check 3 — split drafts into CREATES vs UPDATES buckets

Iterate plan drafts:
- Drafts with `dng_url` in metadata (from authorship branch 5 — DNG module seed) → UPDATES bucket
- Drafts without `dng_url` → CREATES bucket

Surface counts in the confirmation line:

> Pushing **12 new** requirements (`create_requirements` batch) and **3 updates** (existing reqs) to module **<M>** in **<P>**.

---

## On confirmation — the actual push

### UPDATES bucket — one call per draft

For each draft in UPDATES:

```
update_requirement(
  requirement_url=<draft.dng_url>,
  title=<draft.title>,
  content=<draft.text>,
)
```

If the draft also has changed attributes, follow with:

```
update_requirement_attributes(
  requirement_url=<draft.dng_url>,
  attributes={ ... },
)
```

No batch tool exists for updates — that's OK, this bucket is usually small (the user only revised a subset of the seeded module).

### CREATES bucket — one batch call

```
create_requirements(
  project_identifier=<P>,
  module_name=<M>,
  artifact_type=<draft.type>,
  requirements=[<all drafts in CREATES>],
)
```

**DO NOT** split CREATES into multiple calls. The whole point of the batch tool is atomicity + module-bind consistency + faster execution.

**DO NOT** re-lint or re-iterate. Plan Mode already validated.

**DO NOT** ask follow-up questions. Plan Mode already gathered them.

---

## After push — wrap up

### 1. Print URLs in plan order

Match each pushed req back to its plan position:

> ✓ Pushed 15 requirements to **WatsonX AI POC > Temperature Converter System Requirements**:
>
> 1. ✓ created — Temperature input field shall accept values from -273.15 to 1000 °C — https://goblue.clm.ibmcloud.com/rm/...
> 2. ✓ created — Conversion shall complete within 200 ms p95 — https://...
> 3. 🔄 updated — Page load shall complete within 2 s — https://...
>    …

Annotations:
- ✓ created — went through `create_requirements`
- 🔄 updated — went through `update_requirement`

### 2. Run audit_module automatically

Call `audit_module(project_identifier=<P>, module_identifier=<M>)` and surface the summary:

> **Quality audit** — WatsonX AI POC > Temperature Converter:
> - 12 good · 2 fair · 1 weak · 0 poor
> - Average score: **87/100**
> - 3 reqs Approved, 12 Draft
> - Most violated rule: GtWR R6 (subjective language) — 2 occurrences

### 3. Point at Requirements Quality Assistant

Always include this footer:

> _For AI-powered semantic scoring on the same requirements, open them in the **Requirements Quality Assistant** agent in IBM ELM AI Hub. Plan Mode's deterministic lint catches syntactic smells; Requirements Quality Assistant catches semantic ones (intent vs wording, completeness, consistency across the set)._

### 4. (Optional) Generate audit report

If Critical tier and the user has a `manager_review_packet=true` preference, follow up with:

> Also rendered the audit as an HTML packet for your manager: `<path>`. Open with `open '<path>'` (macOS) or double-click. Same data as above, presentation-ready.

This calls `generate_audit_report` from the elm-mcp server.

---

## If user wants to tweak during the confirmation gate

The user says "wait, actually change req #3 to say X" before confirming. Don't try to edit in Push Mode. Say:

> Switching back to Plan Mode — what would you like to change?

Then swap modes. **Push Mode is a commit, not a conversation.** The clean separation is what makes Push Mode trustworthy.

---

## On push failure mid-batch

If `create_requirements` partially succeeds or fully fails:

> ⚠️ **Push partially failed.**
>
> Succeeded (8):
> 1. ✓ <url>
> 2. ✓ <url>
>    …
>
> Failed (4):
> 9. ❌ "Conversion result precision" — `_dispatch_tool: 422 Unprocessable Entity: invalid Status enum`
> 10. ❌ "Convert button" — same
>     …
>
> Options:
> - **Retry just the failed batch** — I'll re-run `create_requirements` on the 4 failures
> - **Back to Plan Mode** — fix the underlying issue (looks like a Status enum problem) and re-push
> - **Manually push** — I'll generate the individual `create_requirements` arguments for each so you can run them by hand

Default: offer the retry. Don't silently re-attempt — the failure mode might be persistent.

---

## On update failure

Updates can fail with stale ETags if someone else modified the req between Plan Mode and Push Mode. If `update_requirement` returns a 412 Precondition Failed:

> ⚠️ Req #3 update failed — someone modified it in DNG since you loaded it. Options:
> - Re-pull the current DNG version and merge your changes
> - Force-overwrite (discards their changes)
> - Skip this one and push the rest

---

## Edge cases

### User pastes a saved plan and immediately says "/push"

Resume the plan from JSON first (Plan Mode behavior), then offer to push. Don't push without reprinting the plan — the user should see what they're about to commit.

### Plan has 0 drafts

> Nothing to push. Want to go back to Plan Mode and draft some reqs?

### Plan has 0 CREATES and 0 UPDATES

Shouldn't happen, but if it does:

> Plan is non-empty but all drafts are marked as no-op (no DNG URL changes, no new content). Nothing to push.

### Target module is in a different config / stream than active

If GCM is involved and the target module belongs to a different stream than the user's active context:

> Module **<M>** lives in stream **<S>**, which is different from your active stream. Push to **<S>** anyway, or switch streams first?

### User says "/push" but Plan Mode quality bar wasn't met

This shouldn't be reachable through normal flow (Plan Mode blocks early push), but if the user explicitly overrode in Plan Mode (`⚠️ Override` logged in header), surface the override prominently in the Push Mode confirmation line:

> 📤 Push Mode active. About to push **14 requirements** with **⚠️ overrides logged**:
> - 2 reqs have 🔴 findings outstanding (Page Load Time, Conversion Speed)
> - Style guide check was skipped
>
> Proceed anyway, or `/back` to fix?

Don't refuse — the user already made the call in Plan Mode. Just make the override visible at the commit gate so the user has one last chance.

---

## What Push Mode is NOT for

- Drafting new reqs → swap to Plan Mode
- Updating existing reqs without a plan → use `update_requirement` directly
- Anything other than "take a finalized plan and ship it"
