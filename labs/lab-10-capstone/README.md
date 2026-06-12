# Lab 10: Capstone — build a project end to end

**Part 5 · Putting it together**
**Time:** 30–45 minutes · **Prerequisites:** Labs 1–9 complete
**Outcome:** Take a single idea all the way to a tracked, traceable project — requirements → tasks → tests → code — in one orchestrated flow with review gates.

---

## ⚠️ This creates real artifacts

The build flow writes requirements, tasks, and test cases to ELM (and can generate code). **Use a sandbox project.** Every phase has an approval gate — nothing happens without your go-ahead — but the end result is real artifacts in a real project.

---

## What the capstone does

Everything in Labs 1–9 was a single capability. `/build-new-project` orchestrates them into the full lifecycle, starting from **a plain idea** (not a document — that keeps it clean and repeatable):

```
Idea → Requirements (DNG) → Tasks (EWM) → Tests (ETM)
     → [you review] → Code → Traceability matrix
```

It's a phase-gated flow: Bob does one phase, pauses for your approval, then continues. You stay in control the whole way.

---

## Step 1 — start the build

```
/build-new-project
```

Bob asks for your idea. Give it something small and self-contained so the lab stays manageable — for example:

```
A URL shortener service: users submit a long URL and get a short code back;
visiting the short code redirects to the original. Include basic analytics
(click counts) and rate limiting.
```

## Step 2 — work the phases

Bob runs the flow phase by phase, pausing at each gate. Expect roughly:

| Phase | What happens | Your move |
|---|---|---|
| Requirements | Bob drafts requirements (with the Plan Mode rigor from Lab 4) | Review, refine, approve |
| Tasks | Generates EWM tasks per requirement | Approve |
| Tests | Generates ETM test cases per requirement | Approve |
| **Review pause** | Bob stops so you can inspect everything in ELM | Look at the real artifacts |
| Code | (Optional) scaffolds code in your IDE | Approve / skip |
| Tracking | Produces the traceability matrix | Done |

At each gate you can refine, skip, or stop. It's not a runaway — it's an assistant working through the lifecycle with you.

## Step 3 — resume if you step away

The build state persists. If you close Bob mid-flow:

```
Resume my last build.
```

Bob picks up at the phase you left.

## Step 4 — see the traceability matrix

When the build completes (or anytime mid-build):

```
Show me the traceability matrix for this build.
```

This is the payoff — every requirement traced to its tasks, tests, and results, with clickable links. The complete chain, generated for you.

## Step 5 — bring it full circle

Now apply the analysis labs to what you just built:

```
Find the traceability gaps in <your sandbox project>.      (Lab 7)
What would changing requirement <REQ-ID> affect?           (Lab 8)
```

You'll see the build produced a *linked* project — so impact analysis and gap-finding now have real chains to work with (unlike a sparse sandbox).

---

## Verify checklist

- ✅ Started a build from a one-line idea
- ✅ Worked through the requirement → task → test phases with approvals
- ✅ Saw the artifacts land in ELM
- ✅ Generated the traceability matrix
- ✅ Ran gap/impact analysis on the built project and saw real chains

---

## What you've learned across the series

| Part | You can now… |
|---|---|
| 1–2 | Install, connect, and find anything in plain English (incl. semantic search) |
| 3 | Write review-grade requirements, create work items + tests, connect the chain |
| 4 | Find traceability gaps, analyze change impact, generate compliance packets |
| 5 | Orchestrate the whole lifecycle from a single idea |

That's the full surface of elm-mcp — driven entirely by natural language, with every write previewed and gated.

---

## Where to go from here

- **Use it on real work.** Point Bob at your actual projects.
- **Run a self-test** anytime to confirm everything's healthy: *"run a self test."*
- **Keep it updated:** *"update yourself"* pulls the latest.
- **Found a rough edge?** File it: https://github.com/brettscharm/elm-mcp/issues

🎉 You've completed the elm-mcp lab series.
