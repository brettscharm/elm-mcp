# Lab 9: Audit-ready compliance

**Part 4 · Analysis & assurance**
**Time:** 25 minutes · **Prerequisites:** [Lab 8](../lab-08-change-impact/) complete
**Outcome:** Generate an audit-ready compliance packet that maps your requirements to a framework (NIST 800-53 or IEC 62304), with a coverage dashboard and a gap analysis.

---

## The pain this removes

Audit prep is weeks of manually extracting evidence from DNG/EWM/ETM, building control-mapping matrices, and writing narratives. `generate_compliance_packet` collapses that into one command: it scans your artifacts, maps them to a framework's controls, computes coverage, flags gaps, and writes a polished packet you can hand to an auditor.

Read-only — it reads and reports, never modifies.

---

## Step 1 — generate a packet

```
Generate a NIST 800-53 compliance packet for <your project>.
```

Bob routes to 📜 Compliance Auditor, confirms the scope, and produces:
- an **audit-readiness status** (READY / READY WITH OBSERVATIONS / NEEDS WORK)
- a **coverage percentage** (controls with mapped evidence)
- a **gap list** — controls with no evidence, prioritized
- a self-contained **HTML packet** (cover, control matrix, evidence cross-links, sign-off checklist)

## Step 2 — open the packet

```
open '~/.elm-mcp/reports/compliance-...html'
```
(macOS — or double-click.) This is the artifact you'd actually submit: print-friendly, every control mapped to the DNG artifacts that satisfy it.

## Step 3 — try the medical-device framework

IEC 62304 is class-aware (A / B / C):

```
Generate an IEC 62304 compliance packet for <your project>, safety class B.
```

## Step 4 — scope it to a module

```
Generate a NIST 800-53 packet for just the <your module> module of <your project>.
```

---

## Important: coverage reflects how your artifacts are *tagged*

The honest part — this is detection-based. The tool finds compliance evidence by recognizing references like `NIST 800-53 IA-2` or `IEC 62304 §5.3.3` in your artifacts' titles / attributes / text. So:

- If your requirements **carry those references**, coverage is high and the mapping is rich.
- If they **don't** (common in projects that track compliance in a separate spreadsheet), you'll see low coverage and **NEEDS WORK** — even if the project is actually compliant.

That low number isn't the tool failing — it's telling you the *evidence isn't linked in DNG where an auditor (or this tool) can find it*. The fix is to add the references to the requirements that satisfy each control (do it in 📝 Plan Mode or by updating reqs). Then re-generate — coverage climbs.

> This is a feature, not a limitation: the packet shows you exactly where your audit trail has holes *before* the auditor does.

## Step 5 — close a coverage gap (optional)

Pick a P1 gap control from the packet. Add its reference to a requirement that satisfies it (via Plan Mode or a req update — e.g. put "Satisfies NIST 800-53 IA-2" in the requirement). Re-generate the packet — that control now shows mapped evidence.

---

## Verify checklist

- ✅ Generated a NIST 800-53 packet and opened the HTML
- ✅ Generated an IEC 62304 packet with a safety class
- ✅ Scoped a packet to one module
- ✅ Understood that coverage reflects how artifacts tag compliance refs

---

## Who uses this

| Role | Why |
|---|---|
| **Compliance officer** | The packet is your audit submission, in minutes not weeks |
| **Systems engineer** | See which controls lack evidence while there's still time to fix |
| **Quality / regulatory** | IEC 62304 / NIST mapping straight from the requirements |
| **Manager** | Audit-readiness status at a glance |

> The packet is a starting point for the compliance officer's review, not a substitute for it. It aggregates the evidence; a human still signs off.

---

## What's next

→ [Lab 10: Capstone — build a project end to end](../lab-10-capstone/)

You've used every major capability individually. The capstone ties them together: an idea → requirements → tasks → tests → code, with review gates, in one orchestrated flow.
