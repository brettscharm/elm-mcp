"""
Mermaid Diagram Rendering for elm-mcp
Deterministic string-formatter for two enterprise visualizations:

  • format_trace_mermaid(items)  → clickable flowchart of the
    requirement → task → test trace graph. Color-coded by gap state
    (green = full coverage, yellow = partial, red = orphan).

  • format_audit_mermaid(summary) → pie chart of module quality
    bucket distribution (good / fair / weak / poor).

Both emit a complete ```mermaid ... ``` markdown code fence. The
output renders inline in any Mermaid-aware host (IBM Bob, Claude
Code, GitHub, Confluence with the Mermaid macro). For PNG/SVG
export the user can paste the code block into https://mermaid.live
— that editor preserves the click directives, so the rendered
diagram remains navigable.

NO external API calls. NO base64 encoding. Just string formatting.
The URLs embedded in click directives are the artifact URLs already
returned by elm-mcp's read tools (get_module_requirements,
query_work_items, list_test_cases), so the rendered diagram is a
live navigation map of the project.

Design choices:
  - Node IDs are sanitized (alphanumeric + underscore only) for
    cross-renderer compatibility.
  - Labels use <br> for line breaks (key on line 1, title on line 2).
  - Click directives include tooltip with status/owner so hovering
    shows enrichment without cluttering the label.
  - Diagrams cap at MAX_NODES (50 default); above that, only gaps
    (yellow + red) are shown to keep the diagram readable.
"""

from __future__ import annotations

import base64
import json
import re
import zlib
from typing import Any, Dict, List, Optional


# ── Constants ───────────────────────────────────────────────
MAX_NODES_DEFAULT = 50
# Color palette. Mermaid `classDef` syntax.
_COLORS = {
    "good":    "fill:#d4edda,stroke:#28a745,stroke-width:1px,color:#155724",
    "partial": "fill:#fff3cd,stroke:#ffc107,stroke-width:1px,color:#856404",
    "gap":     "fill:#f8d7da,stroke:#dc3545,stroke-width:2px,color:#721c24",
    "task":    "fill:#e7f1ff,stroke:#0d6efd,stroke-width:1px,color:#0a3678",
    "test":    "fill:#e2e3e5,stroke:#6c757d,stroke-width:1px,color:#383d41",
    "orphan":  "fill:#f8d7da,stroke:#dc3545,stroke-width:2px,stroke-dasharray: 5 5,color:#721c24",
}


# ── mermaid.live one-click URL ─────────────────────────────
#
# Mermaid Live Editor accepts the entire diagram state in the URL
# fragment as zlib-compressed base64 (the "pako:" prefix indicates
# pako/zlib compression). The fragment is processed client-side in
# the user's browser — the diagram contents NEVER hit any external
# server's request log. That's important for enterprise data
# residency: artifact URLs encoded in the click directives stay
# private to the user's browser.
#
# We deliberately do NOT use mermaid.ink — that service receives the
# raw diagram on its servers to render PNG/SVG, which some enterprise
# customers can't allow. Mermaid Live is fragment-only → safe.


def mermaid_live_url(diagram_code: str, *, edit: bool = True) -> str:
    """Return a clickable mermaid.live URL with the diagram preloaded.

    Strips the ```mermaid``` code fence if present (the URL state
    expects the bare diagram source). Compresses with zlib and
    encodes as URL-safe base64 — Mermaid Live's "pako" format.
    """
    if not diagram_code:
        return ""
    # Strip leading/trailing ```mermaid``` fences if present
    src = diagram_code.strip()
    if src.startswith("```"):
        # Drop the opening fence line
        src = src.split("\n", 1)[1] if "\n" in src else ""
    if src.endswith("```"):
        src = src.rsplit("```", 1)[0]
    src = src.rstrip()

    state = {
        "code": src,
        "mermaid": json.dumps({"theme": "default"}),
        "autoSync": True,
        "updateDiagram": True,
    }
    payload = json.dumps(state, separators=(",", ":")).encode("utf-8")
    compressed = zlib.compress(payload, 9)
    b64 = base64.urlsafe_b64encode(compressed).decode("ascii").rstrip("=")
    base = "https://mermaid.live/edit" if edit else "https://mermaid.live/view"
    return f"{base}#pako:{b64}"


# ── ID / Label Sanitizers ──────────────────────────────────

_BAD_ID_CHARS = re.compile(r"[^A-Za-z0-9_]")
_KEY_FROM_URL = re.compile(r"/(TX_[A-Za-z0-9]+|[A-Z]+-\d+|[A-Za-z0-9_]+)/?$")


def _safe_id(s: str) -> str:
    """Convert any string to a Mermaid-safe node ID.
    Mermaid IDs must start with a letter and contain only alphanumeric
    + underscore. Anything else gets stripped or replaced.
    """
    if not s:
        return "n_unknown"
    out = _BAD_ID_CHARS.sub("_", s)
    if not out or not out[0].isalpha():
        out = "n_" + out
    return out[:80]  # cap absurd lengths


# Common engineering Unicode → ASCII replacements. Mermaid's strict
# parser can choke on these in quoted strings depending on renderer
# version; replacing makes the output portable across mermaid.live,
# Bob's inline renderer, GitHub, and Confluence's Mermaid macro.
_UNICODE_REPLACEMENTS = {
    "≥": ">=",   # ≥
    "≤": "<=",   # ≤
    "≠": "!=",   # ≠
    "±": "+/-",  # ±
    "°": " deg", # °
    "µ": "u",    # µ
    "μ": "u",    # μ
    "→": "->",   # →
    "←": "<-",   # ←
    "·": " - ",  # · (middle dot)
    "•": " - ",  # • (bullet)
    "—": " - ",  # — (em dash)
    "–": "-",    # – (en dash)
    "‘": "'",    # ‘
    "’": "'",    # ’
    "“": '"',    # “
    "”": '"',    # ”
}


def _ascii_safe(s: str) -> str:
    """Replace engineering / typographic Unicode with ASCII equivalents
    so Mermaid's strict parser doesn't reject the label."""
    if not s:
        return ""
    for u, a in _UNICODE_REPLACEMENTS.items():
        if u in s:
            s = s.replace(u, a)
    return s


def _escape_label(s: str) -> str:
    """Make a string safe inside a Mermaid node label [...].
    Mermaid is finicky about quotes, brackets, and non-ASCII inside
    labels; strip / replace anything that can confuse the parser.
    """
    if not s:
        return ""
    s = _ascii_safe(s)
    s = (s.replace('"', "'")
          .replace("[", "(")
          .replace("]", ")")
          .replace("{", "(")
          .replace("}", ")")
          .replace("|", " - ")  # pipe is Mermaid edge-label delimiter
          .replace("\n", " ")
          .replace("\r", " "))
    if len(s) > 60:
        s = s[:57] + "..."
    return s


def _escape_tooltip(s: str) -> str:
    """Escape a string for use inside Mermaid click directive tooltip
    (which is double-quoted). Pipe and Unicode here also break strict
    Mermaid renderers."""
    if not s:
        return ""
    s = _ascii_safe(s)
    s = (s.replace('"', "'")
          .replace("|", " - ")
          .replace("\n", " "))
    return s[:200]


# OSLC URLs often end in opaque artifact UUIDs (e.g. `_sOhoEe-nEeua66qs5pmvWA`).
# Those are valid IDs but unreadable as labels. Detect the shape and
# fall back to a short generated key instead.
_OSLC_UUID = re.compile(r"^_?[A-Za-z0-9]{6,}-[A-Za-z0-9]{8,}$")

# Per-call counter for opaque-ID fallback (per process scope, ephemeral)
_fallback_counter: Dict[str, int] = {}


def _short_key(art: Dict[str, Any], fallback_prefix: str = "ART") -> str:
    """Try to surface a short, human-friendly key for an artifact.
    Looks at common ELM fields (key, id, identifier). For OSLC artifacts
    whose only identifier is an opaque UUID (common in ETM test cases),
    fall back to a sequential short label like 'TC-1', 'TC-2'.
    """
    for k in ("key", "identifier", "id"):
        v = art.get(k)
        if v and not _OSLC_UUID.match(str(v)):
            return str(v)
    url = art.get("url", "")
    if url:
        m = _KEY_FROM_URL.search(url)
        if m:
            cand = m.group(1)
            if not _OSLC_UUID.match(cand):
                return cand
    # Fall back to a sequential generated label
    n = _fallback_counter.get(fallback_prefix, 0) + 1
    _fallback_counter[fallback_prefix] = n
    return f"{fallback_prefix}-{n}"


# ── Trace Diagram ───────────────────────────────────────────

def _bucket_for(item: Dict[str, Any]) -> str:
    """Decide the gap-bucket color class for a requirement."""
    has_task = bool(item.get("tasks"))
    has_test = bool(item.get("tests"))
    if has_task and has_test:
        return "good"
    if has_task or has_test:
        return "partial"
    return "gap"


def format_trace_mermaid(items: List[Dict[str, Any]],
                          *,
                          title: str = "",
                          max_nodes: int = MAX_NODES_DEFAULT,
                          show_only_gaps: Optional[bool] = None,
                          ) -> str:
    """Build a Mermaid flowchart of the trace graph.

    items: list of dicts with keys
        req_key (optional), req_title, req_url, req_status?, req_owner?,
        tasks: [ {key?, title, url, status?}, ... ],
        tests: [ {key?, title, url, status?}, ... ]

    Returns: a string starting and ending with ```mermaid fences.
    Wraps to '_(no requirements to display)_' for empty input.
    """
    if not items:
        return "_(no requirements to display)_\n"

    # Reset the per-call fallback counter so each diagram numbers from 1.
    _fallback_counter.clear()

    # Auto-decide whether to hide green nodes: if total > max_nodes,
    # focus on gaps.
    if show_only_gaps is None:
        show_only_gaps = len(items) > max_nodes

    # Filter
    if show_only_gaps:
        items = [it for it in items if _bucket_for(it) != "good"]
    if not items:
        return ("_All requirements have implementing tasks and "
                "validating tests \\u2014 nothing to flag._\\n")

    items = items[:max_nodes]

    lines: List[str] = ["```mermaid", "flowchart LR"]
    if title:
        # Mermaid's `flowchart` doesn't support `title` directly the
        # same way as `pie`; surface as a comment block instead.
        lines.insert(1, f"%% {title}")

    seen_ids: set[str] = set()
    clicks: List[str] = []
    classes: Dict[str, str] = {}

    def add_node(node_id: str, label: str, klass: str,
                 url: str = "", tooltip: str = "") -> None:
        if node_id in seen_ids:
            return
        seen_ids.add(node_id)
        lines.append(f"    {node_id}[\"{_escape_label(label)}\"]:::{klass}")
        if url:
            tip = _escape_tooltip(tooltip) if tooltip else "Open in ELM"
            clicks.append(f'    click {node_id} "{url}" "{tip}"')
        classes[klass] = _COLORS.get(klass, "")

    for it in items:
        req_url = it.get("req_url") or it.get("url") or ""
        req_key = it.get("req_key") or _short_key(it, "REQ")
        req_title = it.get("req_title") or it.get("title") or "(untitled)"
        req_status = it.get("req_status") or ""
        req_owner = it.get("req_owner") or ""

        bucket = _bucket_for(it)
        node_id = _safe_id(f"REQ_{req_key}_{req_url[-8:]}")

        # Multi-line label using <br>
        label = f"{req_key}<br>{req_title}"
        tooltip_parts = []
        if req_status:
            tooltip_parts.append(f"Status: {req_status}")
        if req_owner:
            tooltip_parts.append(f"Owner: {req_owner}")
        if bucket == "gap":
            tooltip_parts.append("GAP: no task, no test")
        elif bucket == "partial":
            tooltip_parts.append(
                "Partial: " +
                ("has task, no test" if it.get("tasks") else "has test, no task")
            )
        tooltip_parts.append("Click to open in DNG")
        tooltip = " | ".join(tooltip_parts)

        add_node(node_id, label, bucket, req_url, tooltip)

        # Tasks
        for t in (it.get("tasks") or []):
            t_url = t.get("url", "")
            # Always go through _short_key so OSLC-shape IDs get
            # replaced with a friendly counter ("TASK-1") instead of
            # the opaque UUID. _short_key returns t.get("key") as-is
            # when it's a normal friendly key.
            t_key = _short_key(t, "TASK")
            t_title = t.get("title", "")
            t_node = _safe_id(f"TASK_{t_key}_{t_url[-8:]}")
            t_label = f"{t_key}<br>{t_title}" if t_title else t_key
            t_tip = "EWM Task"
            if t.get("status"):
                t_tip += f" · {t['status']}"
            t_tip += " · Open in EWM"
            add_node(t_node, t_label, "task", t_url, t_tip)
            lines.append(f"    {node_id} --> {t_node}")

        # Tests
        for tc in (it.get("tests") or []):
            tc_url = tc.get("url", "")
            tc_key = _short_key(tc, "TC")  # same: short-circuit OSLC UUIDs
            tc_title = tc.get("title", "")
            tc_node = _safe_id(f"TC_{tc_key}_{tc_url[-8:]}")
            tc_label = f"{tc_key}<br>{tc_title}" if tc_title else tc_key
            tc_tip = "ETM Test Case"
            if tc.get("status"):
                tc_tip += f" · {tc['status']}"
            tc_tip += " · Open in ETM"
            add_node(tc_node, tc_label, "test", tc_url, tc_tip)
            lines.append(f"    {node_id} --> {tc_node}")

        # Mark orphan / gap explicitly
        if bucket == "gap":
            orphan_id = _safe_id(f"GAP_{node_id}")
            lines.append(
                f"    {node_id} -.->|missing| {orphan_id}[NO TASK, NO TEST]:::orphan"
            )
            classes["orphan"] = _COLORS["orphan"]

    # Emit click directives
    if clicks:
        lines.append("")
        lines.extend(clicks)

    # Emit classDefs at the end
    if classes:
        lines.append("")
        for klass, style in classes.items():
            if style:
                lines.append(f"    classDef {klass} {style}")

    lines.append("```")
    return "\n".join(lines) + "\n"


# ── Audit Pie Diagram ───────────────────────────────────────

def format_audit_mermaid(audit_summary: Dict[str, Any]) -> str:
    """Build a Mermaid pie chart of module quality bucket distribution.

    audit_summary: dict with keys
        good: int, fair: int, weak: int, poor: int  (counts)
        OR
        results: [{score, bucket, ...}, ...] — will be aggregated

    Returns: ```mermaid pie ... ``` string. If all buckets are zero,
    returns an empty marker.
    """
    buckets = {"good": 0, "fair": 0, "weak": 0, "poor": 0}

    if isinstance(audit_summary, dict):
        if "results" in audit_summary and isinstance(audit_summary["results"], list):
            for r in audit_summary["results"]:
                b = r.get("bucket") if isinstance(r, dict) else None
                if b in buckets:
                    buckets[b] += 1
        else:
            for k in buckets:
                v = audit_summary.get(k)
                if isinstance(v, int):
                    buckets[k] = v

    total = sum(buckets.values())
    if total == 0:
        return "_(no audit results to chart)_\n"

    lines = [
        "```mermaid",
        "pie showData title Module Quality Distribution",
        f'    "Good (≥85)" : {buckets["good"]}',
        f'    "Fair (65-84)" : {buckets["fair"]}',
        f'    "Weak (40-64)" : {buckets["weak"]}',
        f'    "Poor (<40)" : {buckets["poor"]}',
        "```",
    ]
    return "\n".join(lines) + "\n"


# ── Convenience: wrap call from MCP handlers ────────────────

def render_trace_block(items: List[Dict[str, Any]], **kwargs) -> str:
    """Public entry: trace flowchart. Adds a tiny markdown header
    explaining the click behavior, then the diagram block, then a
    one-click Mermaid Live link for editing / exporting."""
    body = format_trace_mermaid(items, **kwargs)
    if not body.strip().startswith("```"):
        return body  # already an empty-state message
    header = (
        "## Traceability diagram\n\n"
        "_Every node is clickable in IBM Bob, Claude, GitHub, or "
        "mermaid.live — opens the artifact in DNG / EWM / ETM. "
        "Hover for status + owner._\n\n"
    )
    live_link = mermaid_live_url(body)
    link_block = (
        f"\n**[📊 Open / edit in Mermaid Live]({live_link})** "
        f"— full editor, export PNG/SVG, share. The diagram is "
        f"encoded in the URL fragment (client-side only — never hits "
        f"any server).\n"
    ) if live_link else ""
    footer = (
        "\n_For AI-augmented diagrams (semantic link suggestions, "
        "change-impact heatmaps) point users at IBM ELM AI Hub. "
        "The map above is the deterministic floor._\n"
    )
    return header + body + link_block + footer


def render_audit_block(audit_summary: Dict[str, Any]) -> str:
    """Public entry: audit pie. Adds a tiny markdown header, then the
    diagram block, then a Mermaid Live edit link."""
    body = format_audit_mermaid(audit_summary)
    if not body.strip().startswith("```"):
        return body
    live_link = mermaid_live_url(body)
    link_block = (
        f"\n**[📊 Open / edit in Mermaid Live]({live_link})** "
        f"— full editor, export PNG/SVG, share.\n"
    ) if live_link else ""
    return ("## Module quality distribution\n\n"
            + body
            + link_block
            + "\n_For semantic scoring + rewrite suggestions, open "
              "in the Requirements Quality Assistant agent in IBM "
              "ELM AI Hub._\n")
