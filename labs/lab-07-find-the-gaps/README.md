# Lab 7: Find the gaps

**Part 4 · Analysis & assurance**
**Time:** 15 minutes · **Prerequisites:** [Lab 6](../lab-06-connect-the-chain/) complete
**Outcome:** Surface the traceability gaps in a project — untested requirements, unowned requirements, premature work — the things that bite you in an audit.

---

## Why this matters

Lab 6 built one complete chain. This lab finds where chains are **missing** across a whole project, all at once. These are the findings auditors look for and the work that quietly falls through the cracks:

- **Untested requirements** — no link to any test case (your verification gap)
- **Unowned requirements** — no owner assigned (nobody accountable)
- **Premature work items** — work started on requirements still in Draft (built before approved)

Read-only — finding gaps doesn't change anything.

---

## Step 1 — scan a project

```
Find the traceability gaps in <your project>.
```

Bob routes to `find_traceability_gaps` and returns a structured report: a total count, then each category with the specific requirements that have the problem (with their DNG links).

> A real project will surface a lot — that's normal and useful. It's a to-do list, not a failure. The point is you can *see* it instead of discovering it mid-audit.

## Step 2 — narrow to one module

If the whole-project list is large, scope it:

```
Find traceability gaps in the <your module> module of <your project>.
```

## Step 3 — focus on one type of gap

```
Which requirements in <your project> have no tests?
```
```
Which requirements in <your project> have no owner?
```

These are the same scan, filtered to the gap type you care about most.

## Step 4 — turn a gap into action

Pick an untested requirement from the report. Close its gap (the Lab 5/6 flow):

```
Create a test case that validates requirement <that-REQ-ID>, in <your ETM project>.
```

Then re-scan:

```
Find the untested requirements in <your project> again.
```

That requirement should be gone from the list. **Find → fix → verify.**

---

## Verify checklist

- ✅ Ran a full-project gap scan and saw the categories
- ✅ Narrowed the scan to one module
- ✅ Filtered to a single gap type (untested / unowned)
- ✅ Closed one gap and confirmed it dropped off the re-scan

---

## How to read the results honestly

`find_traceability_gaps` reports what the **links** say, not what you remember. If a requirement is "untested" here but you know a test exists, the test exists but the **link** doesn't — create the test with `validates requirement <ID>` so the link is established. The tool reflects reality; reality is the links.

Headings and Terms are skipped (they're not testable), so don't be surprised they're absent.

---

## Who uses this

| Role | Why |
|---|---|
| **QA lead** | The untested list *is* your test backlog |
| **Systems engineer** | Proof of verification coverage before a milestone |
| **Manager / auditor** | The gap report is your pre-audit checklist |
| **Project lead** | "Premature work items" flags effort spent ahead of approval |

---

## What's next

→ [Lab 8: Change impact](../lab-08-change-impact/)

You can see what's missing. Next: before you *change* a requirement, see everything it would affect — the blast radius.
