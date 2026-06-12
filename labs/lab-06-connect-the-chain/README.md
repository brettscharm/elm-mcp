# Lab 6: Connect the chain

**Part 3 · Doing the work**
**Time:** 20 minutes · **Prerequisites:** [Lab 5](../lab-05-create-work-items/) complete
**Outcome:** Link requirement → task → test into a traceability chain, then check your coverage.

---

## Why traceability is the whole point of ELM

A requirement nobody implements is a gap. A requirement nobody tests is a risk. The value of ELM is the **chain**: every requirement traces to the work that builds it and the test that verifies it. When the chain is complete, you can answer "is this requirement done and proven?" — and auditors can too.

This lab builds one chain end to end and then shows you how to see where chains are broken.

---

## Step 1 — start from a requirement

Pick a requirement to trace (from Lab 2/3, or one you pushed in Lab 4):

```
What's requirement <REQ-ID> in <your project>?
```

Note its title and URL — this is the anchor of the chain.

## Step 2 — link a task that implements it

Create an EWM task cross-linked to the requirement (preview-first, as in Lab 5):

```
Create a task to implement requirement <REQ-ID> — "Build the <feature>" — in <your EWM project>, linked to that requirement.
```

Review the preview (it shows the link target), then confirm.

## Step 3 — link a test that validates it

Create an ETM test case cross-linked to the same requirement:

```
Create a test case that validates requirement <REQ-ID> — "Verify <feature> behaves correctly" — in <your ETM project>.
```

Confirm. Now you have **requirement → task → test**, all linked.

## Step 4 — see the chain

Ask Bob to walk what's connected to the requirement:

```
What's the traceability chain for requirement <REQ-ID>?
```

You should see the requirement, the task implementing it, and the test validating it.

## Step 5 — find the broken chains

Now the audit view — where are chains *missing*?

```
Find the traceability gaps in <your project>.
```

This routes to `find_traceability_gaps`, which surfaces:
- **Untested requirements** — no link to any test case
- **Unowned requirements** — no owner assigned
- **Premature work items** — work started on requirements still in Draft

Your newly-linked requirement should NOT appear as untested — you just gave it a test. The ones that *do* appear are your real gaps.

## Step 6 — close a gap

Pick an untested requirement from Step 5 and close its gap by creating a test for it:

```
Create a test case that validates requirement <that-REQ-ID>, in <your ETM project>.
```

Re-run the gap check — that requirement drops off the untested list. That's the loop: find the gap, close it, verify it's closed.

---

## Verify checklist

- ✅ Created a task linked to a requirement
- ✅ Created a test case linked to the same requirement
- ✅ Viewed the requirement → task → test chain
- ✅ Ran `find_traceability_gaps` and saw real gaps
- ✅ Closed an untested-requirement gap and confirmed it dropped off

---

## Why this matters per role

| Role | What the chain gives you |
|---|---|
| **Systems engineer** | Proof every requirement is implemented and verified |
| **QA lead** | Instant "what's untested" list — your test backlog |
| **Manager / auditor** | Coverage you can show, not claim |
| **Dev lead** | "If I change this requirement, here's what it touches" (Lab 8) |

---

## Common pitfalls

**The gap check flags a requirement I know is tested.** The test exists but the *link* doesn't. Traceability is about the links, not just the artifacts — create the test with `validates requirement <ID>` so the link is established.

**Headings show up oddly in gap results.** Headings and Terms aren't testable, so the gap finder skips them. If you see structural artifacts, that's expected.

---

## What's next

→ Part 4 · Analysis & assurance *(coming soon)* — **Lab 7: Find the gaps** (deeper), **Lab 8: Change impact**, **Lab 9: Audit-ready compliance**.

You've completed **Parts 1–3** — the core of using elm-mcp: get running, find anything, write requirements, create work items and tests, and connect the traceability chain. That's the productive foundation. The Analysis & Assurance labs (gaps, impact, compliance) and the capstone build go deeper from here.
