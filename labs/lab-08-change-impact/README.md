# Lab 8: Change impact

**Part 4 · Analysis & assurance**
**Time:** 20 minutes · **Prerequisites:** [Lab 7](../lab-07-find-the-gaps/) complete
**Outcome:** Before you modify a requirement or a piece of code, see everything it would affect — the blast radius — as a risk summary and an interactive graph.

---

## The question this answers

"If I change this, what breaks?" Every engineer asks it before a change; most answer it by guessing. `analyze_change_impact` walks the trace graph outward from one artifact and tells you: which requirements, tests, and work items are downstream, which compliance controls are touched, and who should review it.

Read-only — it analyzes, never modifies.

---

## Step 1 — analyze a requirement

```
What would be affected if I change requirement <REQ-ID> in <your project>?
```

Bob routes to 🎯 Impact Analyst and returns:
- a **risk classification** (LOW / MEDIUM / HIGH) with the reasons
- counts of affected requirements / tests / work items
- any **compliance controls** touched
- **suggested reviewers** (the owners of affected artifacts)
- a path to a self-contained **HTML graph** you open in a browser — every node clickable to the artifact

## Step 2 — open the graph

```
open '~/.elm-mcp/reports/impact-...html'
```
(macOS — or double-click the file.) Drag the nodes around; click any node to jump to that artifact in DNG/EWM/ETM.

## Step 3 — analyze a code file

Impact analysis isn't just for requirements — point it at code:

```
What does changing /path/to/SomeService.java affect?
```

(Use a real path on your machine.) This is the "is it safe to merge?" check before a refactor.

## Step 4 — go deeper or shallower

```
Give me the deep impact of requirement <REQ-ID>.     (depth 5 — broader)
```
```
Just the direct impact of requirement <REQ-ID>.       (depth 1 — first-order only)
```

---

## Important: impact is only as rich as your trace links

This is the honest part. Impact analysis walks **OSLC links** — satisfies, validates, tracked-by, etc. If your project is **richly linked**, you get a deep, useful blast radius. If a requirement has **no links** (common in sandboxes and early-stage projects), you'll see:

```
🟢 Risk: LOW — No downstream artifacts found via trace graph
Affected artifacts (0 total)
```

That's not a bug — it's the truth: nothing is linked to that requirement *yet*, so changing it affects nothing traceable. The tool never invents connections.

**To see impact analysis shine,** run it on a requirement that's part of a linked chain (e.g. one you connected in Lab 6, or a mature module with real traceability). The richer the links, the more valuable the analysis.

---

## Verify checklist

- ✅ Got a risk summary for a requirement
- ✅ Opened the interactive HTML graph
- ✅ Ran it on a code file path
- ✅ Tried different depths
- ✅ Understood that an empty/LOW result means "no trace links," not a failure

---

## Who uses this

| Role | Why |
|---|---|
| **Dev / tech lead** | "Is this change safe to merge? Who needs to review?" |
| **Systems engineer** | Ripple analysis before a requirement change |
| **Change board** | A documented blast-radius report for the review |
| **Compliance owner** | See immediately if a change touches a controlled requirement |

---

## What's next

→ [Lab 9: Audit-ready compliance](../lab-09-compliance/)

You can see what a change affects. Next: generate an audit-ready compliance packet mapping your artifacts to a framework like NIST 800-53 or IEC 62304.
