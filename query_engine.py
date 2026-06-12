"""Unified query engine for ELM — the layer that makes natural language
"just work" by reducing every read request to one normalized intent and
routing it to the right backend.

The architecture (see docs/QUERY_ARCHITECTURE.md):

    natural language (Bob fills the tool args)
        │
        ▼
    QueryIntent  ── normalized: domain + scope + predicates + text + id
        │
        ▼  VocabularyResolver  (human terms → canonical attrs/ops/values)
        │
        ▼  QueryPlanner        (intent shape → backend)
        │
        ▼  Backends            (resolve-by-id / full-text / module-scan)
        │
        ▼  normalized results  (same shape regardless of backend)

The LLM (Bob) is the natural-language parser — it extracts structured
predicates from a sentence. This engine's job is to make whatever Bob
extracts execute reliably with forgiving vocabulary (so "approved",
"Approved", "StateApproved", "status: approved" all resolve the same).

This wraps the existing, now-fixed client methods rather than
reimplementing OSLC — the value is the consistent intent + vocab +
planner layer on top.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── Predicate operators ───────────────────────────────────────
OP_EQ = "eq"
OP_NEQ = "neq"
OP_CONTAINS = "contains"
OP_IN = "in"
OP_MISSING = "missing"      # attribute / link absent (untested, unowned)
OP_EXISTS = "exists"        # attribute / link present (tested, owned)

_VALID_OPS = {OP_EQ, OP_NEQ, OP_CONTAINS, OP_IN, OP_MISSING, OP_EXISTS}


@dataclass
class Pred:
    """One filter predicate: attribute <op> value."""
    attr: str
    op: str = OP_EQ
    value: Any = None


@dataclass
class QueryIntent:
    """A normalized read request, independent of which ELM backend runs it."""
    project: str
    domain: str = "dng"                  # dng | ewm | etm (dng implemented)
    module: Optional[str] = None         # narrows to a module
    predicates: List[Pred] = field(default_factory=list)
    text: Optional[str] = None           # free-text search
    requirement_id: Optional[str] = None  # by-short-id lookup
    limit: int = 200


# ── Vocabulary: human terms → canonical attribute names ───────
# Maps the words people actually type to the attribute key the filter
# uses. Value normalization (Approved vs StateApproved vs "4") is handled
# downstream by the enum-tolerant filter in doors_client._apply_filter.
_ATTR_ALIASES: Dict[str, str] = {
    "status": "Status", "state": "Status",
    "priority": "Priority", "prio": "Priority",
    "stability": "Stability",
    "owner": "Owner", "owned by": "Owner", "assignee": "Owner",
    "type": "artifact_type", "artifact type": "artifact_type",
    "artifacttype": "artifact_type", "kind": "artifact_type",
    "title": "title", "name": "title",
    "tested by": "validatedBy", "validated by": "validatedBy",
    "test": "validatedBy", "tests": "validatedBy",
    "tracked by": "trackedBy",
}

# Whole-phrase shortcuts → a complete predicate. These capture the
# common "untested" / "unowned" style asks that map to link-absence.
_PHRASE_PREDICATES: Dict[str, Pred] = {
    "untested": Pred("validatedBy", OP_MISSING),
    "no tests": Pred("validatedBy", OP_MISSING),
    "without tests": Pred("validatedBy", OP_MISSING),
    "not tested": Pred("validatedBy", OP_MISSING),
    "tested": Pred("validatedBy", OP_EXISTS),
    "validated": Pred("validatedBy", OP_EXISTS),
    "unowned": Pred("Owner", OP_MISSING),
    "no owner": Pred("Owner", OP_MISSING),
    "without an owner": Pred("Owner", OP_MISSING),
    "owned": Pred("Owner", OP_EXISTS),
    "untracked": Pred("trackedBy", OP_MISSING),
    "no work items": Pred("trackedBy", OP_MISSING),
}


def normalize_attr(name: str) -> str:
    """Canonicalize a human attribute name. Unknown names pass through
    unchanged (so project-specific custom attributes still work)."""
    if not name:
        return name
    key = str(name).strip().lower()
    return _ATTR_ALIASES.get(key, name)


def resolve_phrase(phrase: str) -> Optional[Pred]:
    """Map a whole-phrase shortcut ('untested', 'unowned') to a Pred."""
    if not phrase:
        return None
    return _PHRASE_PREDICATES.get(str(phrase).strip().lower())


def build_predicates(raw: Any) -> List[Pred]:
    """Turn loosely-typed filter input from the tool into canonical Preds.

    Accepts any of:
      - list of dicts: [{"attribute": "Status", "operator": "eq",
                          "value": "Approved"}]
      - dict: {"Status": "Approved", "title_contains": "login"}
      - list of phrase strings: ["untested", "approved"]  (mixed ok)
    """
    out: List[Pred] = []
    if raw is None:
        return out

    if isinstance(raw, dict):
        for k, v in raw.items():
            key = str(k)
            if key.endswith("_contains"):
                out.append(Pred(normalize_attr(key[:-len("_contains")]),
                                 OP_CONTAINS, v))
            else:
                out.append(Pred(normalize_attr(key), OP_EQ, v))
        return out

    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                ph = resolve_phrase(item)
                if ph:
                    out.append(ph)
                continue
            if isinstance(item, dict):
                # structured form
                attr = item.get("attribute") or item.get("attr") or ""
                op = (item.get("operator") or item.get("op") or OP_EQ).lower()
                if op not in _VALID_OPS:
                    op = OP_EQ
                val = item.get("value")
                if attr:
                    out.append(Pred(normalize_attr(attr), op, val))
        return out

    return out


# ── Backends ──────────────────────────────────────────────────

def _split_preds(preds: List[Pred]):
    """Separate predicates the dict-filter can do (eq/contains/in) from
    the ones the engine must post-process (missing/exists/neq)."""
    filterable: Dict[str, Any] = {}
    postproc: List[Pred] = []
    for p in preds:
        if p.op == OP_EQ:
            filterable[p.attr] = p.value
        elif p.op == OP_CONTAINS:
            filterable[f"{p.attr}_contains"] = p.value
        elif p.op == OP_IN:
            filterable[p.attr] = p.value  # _apply_filter handles list = any-of
        else:
            postproc.append(p)
    return filterable, postproc


def _has_attr(req: Dict, attr: str) -> bool:
    """Is an attribute / link present and non-empty on a req?"""
    v = req.get(attr)
    if v is None:
        v = (req.get("custom_attributes") or {}).get(attr)
    if v is None:
        # try case-insensitive custom key
        lower = attr.lower()
        for k, val in (req.get("custom_attributes") or {}).items():
            if k.lower() == lower:
                v = val
                break
    if isinstance(v, (list, tuple)):
        return any(v)
    return bool(v)


def _apply_postproc(reqs: List[Dict], postproc: List[Pred]) -> List[Dict]:
    for p in postproc:
        if p.op == OP_MISSING:
            reqs = [r for r in reqs if not _has_attr(r, p.attr)]
        elif p.op == OP_EXISTS:
            reqs = [r for r in reqs if _has_attr(r, p.attr)]
        elif p.op == OP_NEQ:
            want = str(p.value).strip().lower()
            def _ne(r):
                actual = r.get(p.attr)
                if actual is None:
                    actual = (r.get("custom_attributes") or {}).get(p.attr, "")
                return str(actual).strip().lower() != want
            reqs = [r for r in reqs if _ne(r)]
    return reqs


def execute(client: Any, intent: QueryIntent) -> Dict[str, Any]:
    """Run a QueryIntent and return normalized results.

    Returns:
      {
        "backend": <which path ran>,
        "results": [ {id, title, url, artifact_type, status, ...}, ... ],
        "count": N,
        "notes": [ ... human-readable notes about what happened ],
      }
    """
    notes: List[str] = []

    # Resolve the project (name/number → record)
    projects = client.list_projects()
    project = _find(projects, intent.project)
    if not project:
        return {"backend": "none", "results": [], "count": 0,
                "notes": [f"DNG project not found: '{intent.project}'"]}

    # ── Backend 1: resolve by short ID ───────────────────────
    if intent.requirement_id:
        res = client.resolve_requirement_id(project["url"],
                                              intent.requirement_id)
        if res:
            return {"backend": "resolve_by_id",
                    "results": [res], "count": 1, "notes": notes}
        return {"backend": "resolve_by_id", "results": [], "count": 0,
                "notes": [f"No requirement with id "
                          f"'{intent.requirement_id}' in {project['title']}"]}

    # ── Backend 2: full-text search ──────────────────────────
    if intent.text:
        hits = client.search_requirements(project["url"], intent.text) or []
        return {"backend": "full_text_search",
                "results": hits[:intent.limit],
                "count": len(hits), "notes": notes}

    # ── Backend 3: module / project attribute query ──────────
    filterable, postproc = _split_preds(intent.predicates)

    modules = client.get_modules(project["url"]) or []
    target_modules = modules
    if intent.module:
        m = _find(modules, intent.module)
        if not m:
            names = ", ".join(mm.get("title", "?") for mm in modules[:10])
            return {"backend": "module_scan", "results": [], "count": 0,
                    "notes": [f"Module '{intent.module}' not found. "
                              f"Available: {names}"]}
        target_modules = [m]
    elif len(modules) > 3 and not intent.text:
        notes.append(f"No module specified — scanned all {len(modules)} "
                     f"modules in the project. Narrow with a module name "
                     f"to go faster.")

    results: List[Dict] = []
    for mod in target_modules:
        try:
            reqs = client.get_module_requirements(
                mod["url"],
                filter=filterable if filterable else None,
            ) or []
        except Exception as e:
            notes.append(f"Module '{mod.get('title')}' read failed: {e}")
            continue
        for r in reqs:
            r["_module"] = mod.get("title", "?")
        results.extend(reqs)

    if postproc:
        before = len(results)
        results = _apply_postproc(results, postproc)
        notes.append(f"Applied {len(postproc)} link-absence filter(s): "
                     f"{before} → {len(results)} reqs.")

    return {"backend": "module_scan",
            "results": results[:intent.limit],
            "count": len(results), "notes": notes}


def _find(items: List[Dict], identifier: str) -> Optional[Dict]:
    """Resolve by 1-based ordinal, exact id, or case-insensitive substring."""
    if not identifier:
        return None
    ident = str(identifier).strip()
    try:
        idx = int(ident) - 1
        if 0 <= idx < len(items):
            return items[idx]
    except ValueError:
        pass
    for it in items:
        if str(it.get("id", "")) == ident:
            return it
    low = ident.lower()
    for it in items:
        if low in str(it.get("title", "")).lower():
            return it
    return None
