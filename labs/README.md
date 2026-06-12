# elm-mcp Lab Series

A hands-on tutorial sequence that takes you from zero to comfortable using elm-mcp with IBM Bob and your real ELM environment.

**Total time for Labs 0-6:** ~70 minutes (install is now a single command)
**Total time for the full series:** ~5.5 hours

---

## Progression

| # | Lab | Time | What you walk away with |
|---|---|---|---|
| 0 | [Prerequisites](lab-00-prerequisites/) | 5 min | Bob installed, IDE ready, ELM creds in hand |
| 1 | [Install elm-mcp](lab-01-install-mcp/) | 5 min | One command → server registered, modes installed, health check passes |
| 2 | [Connect to ELM](lab-02-connect-to-elm/) | 10 min | Logged in, your DNG / EWM / ETM projects listed |
| 3 | [Verify the modes](lab-03-install-modes/) | 5 min | Confirm the 5 auto-installed modes loaded; understand what each does |
| 4 | [Natural-language routing](lab-04-concierge-routing/) | 15 min | Type plain English, Bob routes to the right tool/mode |
| 5 | [Read requirements (DNG)](lab-05-read-requirements/) | 15 min | Browse modules, get + filter + search requirements |
| 6 | [Plan + Push requirements](lab-06-plan-push/) | 30 min | Full Plan Mode session → batch push to DNG → automatic audit |

**Coming in v0.23.x** (staged based on user feedback):

| # | Lab | Topic |
|---|---|---|
| 7 | Work items (EWM) | `query_work_items`, `create_task`, `transition_work_item` |
| 8 | Test cases (ETM) | `list_test_cases`, `create_test_case`, linking to a req |
| 9 | Cross-artifact (req ↔ WI ↔ TC) | The value loop — build a full trace chain |
| 10 | Find traceability gaps | `find_traceability_gaps` audit-readiness check |
| 11 | Change impact analysis | 🎯 Impact Analyst — HTML report + Cytoscape graph |
| 12 | Export to Excel | `export_module_to_xlsx` for non-ELM stakeholders |
| 13 | Compliance packet | 📜 Compliance Auditor — NIST 800-53 or IEC 62304 |
| 14 | The build-project flow | `/build-new-project` end-to-end |
| 15 | Bonus: ELM docs lookup | `get_elm_docs_links` — never get a dead URL again |
| 16 | Capstone | Real-world scenario: Jira → reqs → tests → impact → compliance |

---

## How to use this series

- **Sequential.** Each lab assumes you finished the previous one.
- **Hands-on.** You'll type real commands and prompts against your real ELM environment. Read-only operations only in Labs 0-5; Lab 6 writes real DNG requirements (use a sandbox project the first time).
- **Skim-friendly.** Each lab has a `Verify` section — if your output matches, you're good to move on.
- **No magic.** Every command Bob runs is visible. You can pause to inspect what's happening.

---

## Audience

These labs assume:

- You have an IBM Bob installation (any host: Claude Code, Cursor, VS Code with the Bob extension, etc.)
- You have an IBM ELM deployment to connect to (cloud-hosted goblue, on-prem, or trial)
- You have ELM credentials with read access to at least one DNG project
- You're comfortable with copying/pasting commands in a terminal
- You don't need to be an ELM expert — the labs explain ELM concepts as they come up

---

## Need help?

- **Repo:** https://github.com/brettscharm/elm-mcp
- **Issues:** https://github.com/brettscharm/elm-mcp/issues — including dead doc URLs
- **Health check:** call `elm_mcp_health` in Bob anytime to see connection + version status

---

## Versioning

Each lab is pinned to the elm-mcp version it was written against. The current series targets **v0.22.1+**. If you're on an older version, run `update_elm_mcp` (or follow Lab 1's update steps) before starting.
