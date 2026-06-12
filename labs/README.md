# elm-mcp Lab Series

A linear, hands-on path that takes you from zero to productive with elm-mcp and your real ELM environment. Start at Lab 1 and go in order — each lab builds on the last, and the *value* escalates: the early labs are for everyone, the later ones go deeper into role-specific workflows.

Whatever your role — business analyst, systems engineer, QA or dev lead, or just evaluating — you get off at your stop. Evaluators see the headline value by the end of Part 2; authors and engineers continue into the workflows that matter to them.

---

## The series

### Part 1 · Get running
| # | Lab | Time | Outcome |
|---|---|---|---|
| 1 | [Install & connect](lab-01-install-connect/) | 15 min | One command → server + modes installed, connected, seeing your real projects |

### Part 2 · The basics
| # | Lab | Time | Outcome |
|---|---|---|---|
| 2 | [Talk to your ELM data](lab-02-talk-to-your-data/) | 15 min | Browse, filter, and search requirements in plain English |
| 3 | [Find anything](lab-03-find-anything/) | 15 min | Unified query across DNG/EWM/ETM + semantic search (find by meaning) |

### Part 3 · Doing the work
| # | Lab | Time | Outcome |
|---|---|---|---|
| 4 | [Write requirements that pass review](lab-04-write-requirements/) | 30 min | Plan + Push — the flagship deep-drill workflow |
| 5 | [Create work items & test cases](lab-05-create-work-items/) | 15 min | `create_elm` — preview-first, linked to requirements |
| 6 | [Connect the chain](lab-06-connect-the-chain/) | 20 min | req → task → test traceability + find the gaps |

### Part 4 · Analysis & assurance *(coming soon)*
| # | Lab | Topic | Tool status |
|---|---|---|---|
| 7 | Find the gaps | `find_traceability_gaps` — untested / unowned / orphans | ✅ ships today |
| 8 | Change impact | `analyze_change_impact` — blast radius before you modify | ✅ ships today |
| 9 | Audit-ready compliance | `generate_compliance_packet` — NIST 800-53 / IEC 62304 | ✅ ships today |

### Part 5 · Putting it together *(coming soon)*
| # | Lab | Topic | Tool status |
|---|---|---|---|
| 10 | Import a document | PDF / Word / pasted spec → DNG | ✅ ships today |
| 11 | Capstone — build a project end to end | `/build-new-project` (or build from the doc in Lab 10) | ✅ ships today |

> **"Coming soon" means the lab walkthrough, not the capability.** Every tool above already ships and is tested live — Labs 7–11 just formalize a guided walkthrough. Parts 1–3 (Labs 1–6) are written and verified.

---

## Total time

- **Parts 1–2 (Labs 1–3):** ~45 min — get running + the headline value. Enough for an evaluator.
- **Parts 1–3 (Labs 1–6):** ~95 min — the full productive foundation.
- **Full series (Labs 1–11):** ~4 hours.

---

## How to use this series

- **Linear.** Start at Lab 1 and go in order. Each lab assumes the previous one is done.
- **Hands-on.** You run real commands against your real ELM environment. Labs 1–3 are read-only; Labs 4–6 write to ELM (use a sandbox project the first time).
- **Skim-friendly.** Each lab has a **Verify** checklist — if your output matches, move on.
- **Safe writes.** Every tool that writes shows a preview and requires confirmation first.

---

## Audience

These labs assume:

- An IBM Bob installation (any host: Claude Code, Cursor, VS Code with the Bob/Claude extension, etc.)
- An IBM ELM deployment (cloud goblue, on-prem, or trial) with read access to at least one DNG project
- Comfort copying/pasting commands in a terminal
- No ELM expertise required — concepts are explained as they come up

Works on **macOS, Linux, and Windows** (Lab 1 covers all three).

---

## Need help?

- **Repo:** https://github.com/brettscharm/elm-mcp
- **Issues:** https://github.com/brettscharm/elm-mcp/issues
- **Health / self-test:** ask Bob to *"run a self test"* anytime — it exercises ~20 read paths and returns a green/red scorecard

---

## Versioning

The series targets **elm-mcp v0.25.0+** (when the unified query engine landed). If you're on an older version, run `update_elm_mcp` or re-run the installer before starting.
