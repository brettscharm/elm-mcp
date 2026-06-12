"""On-demand self-test — exercises every major read path against a live
ELM server and returns a pass/fail scorecard.

Exposed as the `elm_mcp_selftest` MCP tool ("run a self test" / "is
everything working?") and runnable from setup.py. Read-only and safe:
it only LISTS / READS / QUERIES — never creates or mutates anything.

This is the reusable regression sweep — run it after an update, when
debugging a customer issue, or to prove the server is healthy. It's the
kind of check that would have caught the enum-filter, resolve, and
work-item bugs without hand-testing each tool.

Each check is isolated (its own try/except) so one failure doesn't abort
the rest. The scorecard records pass / fail / skip with a one-line
detail per check.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional


PASS = "pass"
FAIL = "fail"
SKIP = "skip"


class _Scorecard:
    def __init__(self):
        self.rows: List[Dict[str, str]] = []

    def add(self, name: str, status: str, detail: str = ""):
        self.rows.append({"name": name, "status": status, "detail": detail})

    def summary(self) -> Dict[str, int]:
        s = {PASS: 0, FAIL: 0, SKIP: 0}
        for r in self.rows:
            s[r["status"]] = s.get(r["status"], 0) + 1
        return s


def _pick_test_project(client) -> Optional[Dict]:
    """Find a DNG project that has modules with requirements — preferring
    a known-good sandbox, else the first that qualifies."""
    projects = client.list_projects()
    preferred = ["WatsonX AI POC (Requirements)",
                 "Tractor Supply Agentic Engineering"]
    ordered = []
    for name in preferred:
        for p in projects:
            if name.lower() in p.get("title", "").lower():
                ordered.append(p)
    ordered += [p for p in projects if p not in ordered]
    for p in ordered[:8]:
        try:
            mods = client.get_modules(p["url"]) or []
            for m in mods:
                reqs = client.get_module_requirements(m["url"]) or []
                if reqs:
                    return {"project": p, "module": m, "reqs": reqs}
        except Exception:
            continue
    return None


def run_selftest(client, server_module=None) -> Dict[str, Any]:
    """Run the full read-path sweep. `server_module` (optional) lets the
    test exercise the higher-level tools that live in the server dispatch
    (query_elm, find_traceability_gaps, etc.) via their helper modules.

    Returns {"scorecard": [...], "summary": {...}, "context": {...}}.
    """
    sc = _Scorecard()
    ctx: Dict[str, Any] = {}

    if client is None:
        sc.add("connection", FAIL, "no client — call connect_to_elm first")
        return {"scorecard": sc.rows, "summary": sc.summary(), "context": ctx}

    # 1. DNG project listing
    try:
        dng = client.list_projects()
        sc.add("list_projects (DNG)", PASS if dng else FAIL,
               f"{len(dng)} projects")
    except Exception as e:
        sc.add("list_projects (DNG)", FAIL, str(e)[:80])
        dng = []

    # 2. EWM / ETM listing
    for label, fn in [("list EWM projects", "list_ewm_projects"),
                       ("list ETM projects", "list_etm_projects")]:
        try:
            items = getattr(client, fn)()
            sc.add(label, PASS if items else SKIP, f"{len(items)} projects")
        except Exception as e:
            sc.add(label, FAIL, str(e)[:80])

    # Pick a working DNG project for the deeper checks
    picked = _pick_test_project(client)
    if not picked:
        sc.add("find testable project", SKIP,
               "no DNG project with reqs found — deeper checks skipped")
        return {"scorecard": sc.rows, "summary": sc.summary(), "context": ctx}

    proj = picked["project"]
    mod = picked["module"]
    reqs = picked["reqs"]
    ctx = {"project": proj["title"], "module": mod["title"],
           "req_count": len(reqs)}
    sc.add("find testable project", PASS,
           f"{proj['title']} > {mod['title']} ({len(reqs)} reqs)")

    pname = proj["title"]
    sample_req = reqs[0]
    # Prefer a req that actually carries a Status enum so the enum-label
    # checks below genuinely exercise the v0.24.2 fix.
    status_req = next(
        (r for r in reqs
         if (r.get("custom_attributes") or {}).get("Status")),
        sample_req)

    # 3. get_modules
    try:
        mods = client.get_modules(proj["url"])
        sc.add("get_modules", PASS if mods else FAIL, f"{len(mods)} modules")
    except Exception as e:
        sc.add("get_modules", FAIL, str(e)[:80])

    # 4. get_module_requirements (no filter)
    try:
        all_reqs = client.get_module_requirements(mod["url"])
        sc.add("get_module_requirements", PASS if all_reqs else FAIL,
               f"{len(all_reqs)} reqs")
    except Exception as e:
        sc.add("get_module_requirements", FAIL, str(e)[:80])

    # 5. enum-attribute display (the v0.24.2 fix — Status should be a
    #    label, not a numeric code)
    try:
        status = (status_req.get("custom_attributes") or {}).get("Status", "")
        if status and not str(status).isdigit():
            sc.add("enum attr labels (Status)", PASS, f"Status={status!r}")
        elif status:
            sc.add("enum attr labels (Status)", FAIL,
                   f"Status shows raw code {status!r} (should be a label)")
        else:
            sc.add("enum attr labels (Status)", SKIP,
                   "no req in this module carries a Status attribute")
    except Exception as e:
        sc.add("enum attr labels (Status)", FAIL, str(e)[:80])

    # 6. enum filter (the v0.24.2 fix — filtering by label should work)
    try:
        status = (status_req.get("custom_attributes") or {}).get("Status", "")
        if status and not str(status).isdigit():
            filtered = client.get_module_requirements(
                mod["url"], filter={"Status": status})
            sc.add("enum filter", PASS if filtered else FAIL,
                   f"filter Status={status} -> {len(filtered)} reqs")
        else:
            sc.add("enum filter", SKIP, "no usable Status label")
    except Exception as e:
        sc.add("enum filter", FAIL, str(e)[:80])

    # 7. title_contains filter
    try:
        word = (sample_req.get("title") or "").split()[0] if sample_req.get("title") else ""
        if word:
            tf = client.get_module_requirements(
                mod["url"], filter={"title_contains": word})
            sc.add("title_contains filter", PASS if tf else FAIL,
                   f"title~{word} -> {len(tf)} reqs")
        else:
            sc.add("title_contains filter", SKIP, "no title word")
    except Exception as e:
        sc.add("title_contains filter", FAIL, str(e)[:80])

    # 8. attribute / artifact / link type discovery
    #    (the get_artifact_types TOOL is backed by the client's
    #    get_artifact_shapes method — friendly name vs internal name)
    for label, fn in [("get_attribute_definitions", "get_attribute_definitions"),
                       ("get_artifact_types", "get_artifact_shapes"),
                       ("get_link_types", "get_link_types")]:
        try:
            res = getattr(client, fn)(proj["url"])
            sc.add(label, PASS if res else FAIL,
                   f"{len(res) if hasattr(res,'__len__') else '?'} items")
        except Exception as e:
            sc.add(label, FAIL, str(e)[:80])

    # 9. search_requirements
    try:
        word = (sample_req.get("title") or "test").split()[0]
        hits = client.search_requirements(proj["url"], word)
        sc.add("search_requirements", PASS if hits else SKIP,
               f"'{word}' -> {len(hits)} hits")
    except Exception as e:
        sc.add("search_requirements", FAIL, str(e)[:80])

    # 10. resolve_requirement_id (the v0.25.0 fix)
    try:
        rid = sample_req.get("id", "")
        if rid:
            r = client.resolve_requirement_id(proj["url"], rid)
            if r and r.get("title"):
                sc.add("resolve_requirement_id", PASS,
                       f"id {rid} -> {r['title'][:40]!r}")
            else:
                sc.add("resolve_requirement_id", FAIL,
                       f"id {rid} did not resolve")
        else:
            sc.add("resolve_requirement_id", SKIP, "no sample id")
    except Exception as e:
        sc.add("resolve_requirement_id", FAIL, str(e)[:80])

    # 11. list_baselines (read-only, ok if empty)
    try:
        bl = client.list_baselines(proj["url"]) if hasattr(client, "list_baselines") else None
        sc.add("list_baselines", PASS, f"{len(bl) if bl else 0} baselines")
    except Exception as e:
        sc.add("list_baselines", FAIL, str(e)[:80])

    # 12. GCM components
    try:
        comps = client.list_global_components()
        sc.add("list_global_components", PASS if comps else SKIP,
               f"{len(comps)} components")
    except Exception as e:
        sc.add("list_global_components", FAIL, str(e)[:80])

    # 13. EWM work-item query (the v0.26.0 fix) — find an EWM project
    try:
        ewm = client.list_ewm_projects()
        # try to find a matching CM project for the same base name
        base = pname.split("(")[0].strip().lower()
        ewm_match = next((p for p in ewm
                          if base and base[:10] in p.get("title", "").lower()), None)
        if ewm_match:
            wis = client.query_work_items(ewm_project_url=ewm_match["url"],
                                           where="", select="*", page_size=10)
            sc.add("query_work_items (EWM)", PASS if wis else SKIP,
                   f"{ewm_match['title'][:30]} -> {len(wis)} items")
        else:
            sc.add("query_work_items (EWM)", SKIP, "no matching EWM project")
    except Exception as e:
        sc.add("query_work_items (EWM)", FAIL, str(e)[:80])

    # 14. query engine (DNG attribute filter) — exercises the v0.25.0 layer
    try:
        from query_engine import QueryIntent, execute, build_predicates
        word = (sample_req.get("title") or "").split()[0]
        out = execute(client, QueryIntent(
            project=pname, module=mod["title"],
            predicates=build_predicates({"title_contains": word}) if word else []))
        sc.add("query_engine (module scan)", PASS if out["results"] else FAIL,
               f"backend={out['backend']} -> {out['count']}")
    except Exception as e:
        sc.add("query_engine (module scan)", FAIL, str(e)[:80])

    # 15. find_traceability_gaps
    try:
        from traceability_gaps import find_gaps
        gaps = find_gaps(client, pname, module_filter=[mod["title"]])
        if "error" in gaps:
            sc.add("find_traceability_gaps", FAIL, gaps["error"][:80])
        else:
            sc.add("find_traceability_gaps", PASS,
                   f"{gaps['summary']['total_gaps']} gaps found")
    except Exception as e:
        sc.add("find_traceability_gaps", FAIL, str(e)[:80])

    # 16. compliance packet (NIST) — generation only, no write
    try:
        from compliance_packet import generate
        mapping = generate(client, pname, "NIST_800_53",
                            module_filter=[mod["title"]])
        sc.add("generate_compliance_packet", PASS,
               f"{mapping.summary['coverage_pct']}% coverage, "
               f"{mapping.summary['audit_readiness']}")
    except Exception as e:
        sc.add("generate_compliance_packet", FAIL, str(e)[:80])

    # 17. xlsx export (writes a local file, not ELM)
    try:
        from xlsx_export import export_artifacts_to_xlsx
        path = export_artifacts_to_xlsx(
            [{"name": mod["title"], "requirements": reqs}],
            project_name=pname + " (selftest)")
        ok = path.exists() and path.stat().st_size > 0
        sc.add("export_module_to_xlsx", PASS if ok else FAIL,
               f"{path.stat().st_size//1024} KB")
        try:
            path.unlink()  # clean up the selftest artifact
        except Exception:
            pass
    except Exception as e:
        sc.add("export_module_to_xlsx", FAIL, str(e)[:80])

    # 18. docs links (curated, no ELM call)
    try:
        from elm_docs import lookup
        r = lookup(topic="upgrade")
        sc.add("get_elm_docs_links", PASS if r["total"] else FAIL,
               f"{r['total']} curated links")
    except Exception as e:
        sc.add("get_elm_docs_links", FAIL, str(e)[:80])

    # 19. semantic search (optional dep)
    try:
        import semantic
        if not semantic.is_available():
            sc.add("find_similar_requirements", SKIP,
                   "fastembed not installed (optional)")
        else:
            ranked = semantic.rank_by_similarity(
                sample_req.get("title", "test"),
                reqs, text_key="title", top_k=3)
            sc.add("find_similar_requirements", PASS if ranked else FAIL,
                   f"top score {ranked[0]['_score']:.2f}" if ranked else "no results")
    except Exception as e:
        sc.add("find_similar_requirements", FAIL, str(e)[:80])

    return {"scorecard": sc.rows, "summary": sc.summary(), "context": ctx}


def format_scorecard(result: Dict[str, Any], version: str = "") -> str:
    """Render the scorecard as markdown."""
    rows = result["scorecard"]
    s = result["summary"]
    ctx = result.get("context", {})
    icon = {PASS: "✅", FAIL: "❌", SKIP: "⊘"}

    total = len(rows)
    health = "HEALTHY" if s.get(FAIL, 0) == 0 else "ISSUES FOUND"
    health_icon = "🟢" if s.get(FAIL, 0) == 0 else "🔴"

    lines = [
        f"# ELM MCP Self-Test {('— v' + version) if version else ''}",
        f"\n### {health_icon} {health}",
        f"**{s.get(PASS,0)} passed · {s.get(FAIL,0)} failed · "
        f"{s.get(SKIP,0)} skipped** (of {total} checks)\n",
    ]
    if ctx:
        lines.append(f"_Tested against: {ctx.get('project','?')} > "
                     f"{ctx.get('module','?')} ({ctx.get('req_count','?')} reqs)_\n")

    for r in rows:
        detail = f" — {r['detail']}" if r["detail"] else ""
        lines.append(f"- {icon.get(r['status'],'?')} **{r['name']}**{detail}")

    if s.get(FAIL, 0):
        lines.append("\n_Failures above are real — investigate each. "
                     "Skips (⊘) are expected when a feature isn't applicable "
                     "(e.g. no EWM project, fastembed not installed)._")
    else:
        lines.append("\n_All applicable checks passed. Skips (⊘) are "
                     "features that don't apply to this project/install._")
    return "\n".join(lines)
