"""Unified natural-language CREATE — preview-first by design.

The write-side counterpart to query_engine. Bob translates a create
request ("add a task to build the login API", "create test cases for
these reqs") into structured items; this engine previews EXACTLY what
would be created (and lints requirement drafts) WITHOUT writing, then —
only on explicit confirm — performs the create via the existing,
already-tested client methods.

The preview-first default is the whole point: unlike a query, a create
mutates ELM, so it must never happen from a vague sentence without the
user seeing precisely what lands. This mirrors the write-gate discipline
in BOB.md ("ASK QUESTIONS BEFORE YOU CREATE ANYTHING").

Domains:
  - ewm : work items (tasks)        — create_ewm_task
  - etm : test cases                — create_test_case
  - dng : requirements              — PREVIEW + lint here, but the actual
          write is routed to the disciplined create_requirements /
          Plan Mode flow (requirements deserve the full rigor + module
          binding, not a quick-create).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CreateItem:
    title: str
    text: str = ""
    requirement_url: Optional[str] = None   # cross-link target


def normalize_items(raw: Any) -> List[CreateItem]:
    """Accept loose input shapes and normalize to CreateItem list:
      - list of dicts: [{"title": "...", "text": "..."}]
      - list of strings: ["Build login API", "Add rate limiting"]
      - a single dict
    """
    out: List[CreateItem] = []
    if raw is None:
        return out
    if isinstance(raw, dict):
        raw = [raw]
    if isinstance(raw, list):
        for it in raw:
            if isinstance(it, str):
                if it.strip():
                    out.append(CreateItem(title=it.strip()))
            elif isinstance(it, dict):
                title = (it.get("title") or it.get("name") or "").strip()
                text = (it.get("text") or it.get("description")
                        or it.get("content") or "").strip()
                ref = it.get("requirement_url") or it.get("requirement_id")
                if title:
                    out.append(CreateItem(title=title, text=text,
                                           requirement_url=ref))
    return out


def _find(items: List[Dict], identifier: str) -> Optional[Dict]:
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


def preview(domain: str, project: str, items: List[CreateItem],
            artifact_type: str = "", module: str = "",
            lint_fn=None) -> Dict[str, Any]:
    """Build a preview of what WOULD be created. No writes. lint_fn, if
    provided, is called with [{title,text}] and returns lint results
    (used for DNG requirement drafts)."""
    rows = []
    for it in items:
        rows.append({"title": it.title, "text": it.text,
                      "requirement_url": it.requirement_url})

    lint = None
    if domain == "dng" and lint_fn and items:
        try:
            lint = lint_fn([{"title": i.title, "text": i.text or i.title}
                            for i in items])
        except Exception:
            lint = None

    target = {
        "dng": f"requirements in module '{module or '(new)'}' "
               f"(type: {artifact_type or 'System Requirement'})",
        "ewm": "work items (tasks)",
        "etm": "test cases",
    }.get(domain, domain)

    return {"domain": domain, "project": project, "target": target,
            "items": rows, "lint": lint, "count": len(rows)}


def commit_ewm(client, project: str, items: List[CreateItem]) -> Dict[str, Any]:
    """Create EWM tasks. Returns created + errors."""
    ewm_projects = client.list_ewm_projects()
    proj = _find(ewm_projects, project)
    if not proj:
        return {"created": [], "errors": [f"EWM project not found: '{project}'"]}
    created, errors = [], []
    for it in items:
        try:
            res = client.create_ewm_task(
                service_provider_url=proj["url"], title=it.title,
                description=it.text, requirement_url=it.requirement_url)
            if res and not res.get("error"):
                created.append({"title": it.title,
                                 "url": res.get("url", ""),
                                 "id": res.get("id", "")})
            else:
                errors.append(f"{it.title}: {res.get('error') if res else 'unknown'}")
        except Exception as e:
            errors.append(f"{it.title}: {e}")
    return {"created": created, "errors": errors}


def commit_etm(client, project: str, items: List[CreateItem]) -> Dict[str, Any]:
    """Create ETM test cases. Returns created + errors."""
    etm_projects = client.list_etm_projects()
    proj = _find(etm_projects, project)
    if not proj:
        return {"created": [], "errors": [f"ETM project not found: '{project}'"]}
    created, errors = [], []
    for it in items:
        try:
            res = client.create_test_case(
                service_provider_url=proj["url"], title=it.title,
                description=it.text, requirement_url=it.requirement_url)
            if res and not res.get("error"):
                created.append({"title": it.title,
                                 "url": res.get("url", ""),
                                 "id": res.get("id", "")})
            else:
                errors.append(f"{it.title}: {res.get('error') if res else 'unknown'}")
        except Exception as e:
            errors.append(f"{it.title}: {e}")
    return {"created": created, "errors": errors}
