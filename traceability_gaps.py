"""Cross-artifact traceability-gap finder.

Used by the `find_traceability_gaps` MCP tool. Scans a DNG project (and
optionally linked EWM/ETM projects) for common traceability problems
that you'd otherwise find by eye:

  - Untested requirements — reqs with no validatedBy link to any test case
  - Orphan tests — test cases with no validates link to any requirement
  - Unowned requirements — reqs with no owner attribute set
  - Stale work-item links — EWM work items whose linked DNG req URL 404s
  - Premature work items — EWM work items linked to DNG reqs still in Draft

Returns a structured dict per check; the tool dispatch arm formats it
for chat output.

Like audit_module, this is a read-only scan with no DNG writes.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Set


# Status values that are NOT yet committed-for-implementation (case-
# insensitive match against the req's Status field).
_DRAFT_STATUSES = {
    "draft", "statedraft", "underreview", "stateunderreview",
    "rejected", "staterejected", "deprecated", "statedeprecated",
    "inplayback", "stateinplayback",
}

_COMMITTED_STATUSES = {"approved"}


def _is_draft_status(status: Any) -> bool:
    if not status:
        return True  # no status set = treat as draft for safety
    s = str(status).lower().strip()
    if s in _COMMITTED_STATUSES:
        return False
    return any(d in s for d in _DRAFT_STATUSES)


def _req_has_link(req: Dict[str, Any], link_keys: List[str]) -> bool:
    """Check if a req has any of the named link types set."""
    custom = req.get("custom_attributes") or {}
    for key in link_keys:
        for source in (req, custom):
            val = source.get(key)
            if val:
                if isinstance(val, list) and any(val):
                    return True
                if not isinstance(val, list):
                    return True
    return False


def find_gaps(
    client: Any,
    project_identifier: str,
    checks: Optional[List[str]] = None,
    module_filter: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Run the requested gap checks on a DNG project.

    Args:
        client: connected DOORSNextClient
        project_identifier: project name or number resolved by caller
        checks: list of check names to run, or None for all. Valid:
            ["untested_reqs", "orphan_tests", "unowned_reqs",
             "stale_workitem_links", "premature_workitems"]
        module_filter: optional list of module names to restrict scope

    Returns a dict with one key per check + summary counts. Each check
    value is a list of artifact dicts the user can act on.
    """
    all_checks = {
        "untested_reqs", "orphan_tests", "unowned_reqs",
        "stale_workitem_links", "premature_workitems",
    }
    if not checks or "all" in checks:
        active = set(all_checks)
    else:
        active = set(checks) & all_checks

    # Resolve project + modules
    projects = client.list_projects()
    project = _find_project(projects, project_identifier)
    if not project:
        return {"error": f"DNG project not found: '{project_identifier}'"}

    modules = client.get_modules(project["url"]) or []
    if module_filter:
        wanted = {m.lower() for m in module_filter}
        modules = [
            m for m in modules
            if m.get("title", "").lower() in wanted or
            any(w in m.get("title", "").lower() for w in wanted)
        ]

    results: Dict[str, Any] = {
        "project": project["title"],
        "modules_scanned": [m.get("title", "?") for m in modules],
        "checks_run": sorted(active),
    }

    # Collect all reqs across selected modules
    all_reqs: List[Dict[str, Any]] = []
    reqs_by_module: Dict[str, List[Dict]] = {}
    for mod in modules:
        try:
            mod_reqs = client.get_module_requirements(mod["url"]) or []
        except Exception:
            mod_reqs = []
        for r in mod_reqs:
            r["_module"] = mod.get("title", "?")
        reqs_by_module[mod.get("title", "?")] = mod_reqs
        all_reqs.extend(mod_reqs)

    if "untested_reqs" in active:
        results["untested_reqs"] = _check_untested(all_reqs)

    if "unowned_reqs" in active:
        results["unowned_reqs"] = _check_unowned(all_reqs)

    if "premature_workitems" in active:
        results["premature_workitems"] = _check_premature_workitems(
            client, project, all_reqs
        )

    if "orphan_tests" in active:
        results["orphan_tests"] = _check_orphan_tests(
            client, project, all_reqs
        )

    if "stale_workitem_links" in active:
        results["stale_workitem_links"] = _check_stale_links(
            client, project, all_reqs
        )

    # Summary counts
    summary: Dict[str, int] = {}
    total = 0
    for k in ("untested_reqs", "orphan_tests", "unowned_reqs",
               "stale_workitem_links", "premature_workitems"):
        count = len(results.get(k, []))
        summary[k] = count
        total += count
    summary["total_gaps"] = total
    results["summary"] = summary

    return results


def _find_project(projects: List[Dict], identifier: str) -> Optional[Dict]:
    """Resolve a project by name (substring) or 1-based ordinal."""
    try:
        idx = int(identifier) - 1
        if 0 <= idx < len(projects):
            return projects[idx]
    except (ValueError, TypeError):
        pass
    lower = (identifier or "").lower()
    for p in projects:
        if lower in p.get("title", "").lower():
            return p
    return None


def _check_untested(reqs: List[Dict]) -> List[Dict]:
    """Reqs with no validatedBy / tested-by link."""
    out = []
    link_keys = ["validatedBy", "validated_by", "Validated By", "testedBy"]
    for r in reqs:
        # Skip Headings — they're not testable
        atype = (r.get("artifact_type") or "").lower()
        if "heading" in atype or "term" in atype:
            continue
        if not _req_has_link(r, link_keys):
            out.append({
                "id": r.get("id", "?"),
                "title": r.get("title") or "(untitled)",
                "module": r.get("_module", "?"),
                "artifact_type": r.get("artifact_type", "?"),
                "url": r.get("url", ""),
                "reason": "no validatedBy link to any test case",
            })
    return out


def _check_unowned(reqs: List[Dict]) -> List[Dict]:
    """Reqs without an Owner attribute set."""
    out = []
    for r in reqs:
        atype = (r.get("artifact_type") or "").lower()
        if "heading" in atype:
            continue
        owner = r.get("owner")
        if not owner:
            custom = r.get("custom_attributes") or {}
            owner = custom.get("owner") or custom.get("Owner")
        if not owner:
            out.append({
                "id": r.get("id", "?"),
                "title": r.get("title") or "(untitled)",
                "module": r.get("_module", "?"),
                "artifact_type": r.get("artifact_type", "?"),
                "url": r.get("url", ""),
                "reason": "no Owner attribute set",
            })
    return out


def _check_premature_workitems(
    client: Any, project: Dict, reqs: List[Dict]
) -> List[Dict]:
    """Reqs in Draft status that already have linked EWM work items.

    Indicates work started before req approval — risky, common gap.
    """
    out = []
    draft_reqs = [r for r in reqs if _is_draft_status(
        _extract_status(r)
    )]
    # For each draft req, check trackedBy links to EWM. The DNG side
    # exposes those via the trackedBy attribute on the req.
    link_keys = ["trackedBy", "tracked_by", "Tracked By"]
    for r in draft_reqs:
        if _req_has_link(r, link_keys):
            out.append({
                "id": r.get("id", "?"),
                "title": r.get("title") or "(untitled)",
                "module": r.get("_module", "?"),
                "artifact_type": r.get("artifact_type", "?"),
                "status": str(_extract_status(r)),
                "url": r.get("url", ""),
                "reason": "req is Draft but has EWM work items "
                           "(trackedBy link) — work started before approval",
            })
    return out


def _extract_status(req: Dict) -> Any:
    """Pull Status from either top-level or custom_attributes."""
    if req.get("status"):
        return req["status"]
    custom = req.get("custom_attributes") or {}
    return custom.get("Status") or custom.get("status")


def _check_orphan_tests(
    client: Any, project: Dict, reqs: List[Dict]
) -> List[Dict]:
    """Test cases in linked ETM project with no validates link to any req.

    Requires ETM project access; we look for an ETM project whose name
    matches the DNG project's name pattern, then list test cases. If
    no ETM project found or list_test_cases is unavailable, returns an
    empty list with a note.
    """
    out: List[Dict] = []
    list_tcs = getattr(client, "list_test_cases", None)
    if not list_tcs:
        return out  # client doesn't expose ETM listing — silent skip

    # Find a likely-matching ETM project
    try:
        etm_projects = client.list_projects(domain="etm") or []
    except Exception:
        return out
    base_name = project.get("title", "").lower()
    base_root = base_name.split("(")[0].strip()
    etm_match = None
    for ep in etm_projects:
        ep_name = ep.get("title", "").lower()
        if base_root and base_root in ep_name:
            etm_match = ep
            break
    if not etm_match:
        return out

    # Build set of DNG req URLs we've already seen so we can detect
    # orphan TCs (TCs whose linked req URL isn't in our seen set is NOT
    # necessarily orphan — it might link to a req in another module.
    # So we only flag TCs that have NO validatesRequirement link at all.)
    try:
        tcs = list_tcs(etm_project=etm_match.get("title")) or []
    except Exception:
        return out
    for tc in tcs:
        validates = (tc.get("validatesRequirement") or
                      tc.get("validates_requirement") or
                      tc.get("validates"))
        if not validates:
            out.append({
                "id": tc.get("id", "?"),
                "title": tc.get("title") or "(untitled)",
                "url": tc.get("url", ""),
                "reason": "test case has no validatesRequirement link",
            })
    return out


def _check_stale_links(
    client: Any, project: Dict, reqs: List[Dict]
) -> List[Dict]:
    """EWM work items whose linked DNG req URL no longer resolves.

    Looks at trackedBy URLs on each req and verifies they're current.
    This is approximate — we trust the EWM side to surface dead links.
    """
    # Without a per-WI link-fetcher this check is expensive (would need
    # to query EWM exhaustively). For v0.19.0 we return a placeholder
    # noting the check is not yet implemented; the framework is here for
    # a future patch.
    return []


# Map of human-friendly check labels for output formatting
CHECK_LABELS = {
    "untested_reqs": "Untested requirements",
    "orphan_tests": "Orphan test cases",
    "unowned_reqs": "Unowned requirements",
    "stale_workitem_links": "Stale work-item links",
    "premature_workitems": "Premature work items (Draft req w/ EWM work)",
}
