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

**Coming next** (staged based on user feedback). Many of these capabilities already SHIP as tools you can use today — the labs just formalize a walkthrough:

| # | Lab | Topic | Tool status |
|---|---|---|---|
| 7 | Natural-language queries | `query_elm` across DNG/EWM/ETM — "approved reqs without tests" | ✅ shipped (v0.26.0) |
| 8 | Semantic search | `find_similar_requirements` — find by meaning, dedup | ✅ shipped (v0.27.0) |
| 9 | Create in natural language | `create_elm` — preview-first task/test creation | ✅ shipped (v0.29.0) |
| 10 | Find traceability gaps | `find_traceability_gaps` audit-readiness check | ✅ shipped (v0.19.0) |
| 11 | Change impact analysis | 🎯 Impact Analyst — HTML report + Cytoscape graph | ✅ shipped (v0.18.0) |
| 12 | Export to Excel | `export_module_to_xlsx` for non-ELM stakeholders | ✅ shipped (v0.15.0) |
| 13 | Compliance packet | 📜 Compliance Auditor — NIST 800-53 or IEC 62304 | ✅ shipped (v0.20.0) |
| 14 | The build-project flow | `/build-new-project` end-to-end | ✅ shipped |
| 15 | Bonus: ELM docs lookup | `get_elm_docs_links` — never get a dead URL again | ✅ shipped (v0.22.0) |
| 16 | Self-test + capstone | `elm_mcp_selftest` + a real-world scenario | ✅ shipped (v0.28.0) |

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

Each lab is pinned to the elm-mcp version it was written against. The current series targets **v0.25.0+** (when the query engine + `resolve_requirement_id` fix landed). If you're on an older version, run `update_elm_mcp` (or follow Lab 1's update steps) before starting.
