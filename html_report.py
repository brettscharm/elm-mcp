"""
HTML Report Generator for elm-mcp.

Produces self-contained .html files that look identical every time —
modern minimalist styling (Linear / Vercel / Stripe school), Inter
typography, interactive Cytoscape.js trace diagrams with clickable
nodes that open ELM artifacts in new tabs, and Chart.js quality
distribution pies.

EVERYTHING is inlined into the output file — Inter variable font,
Cytoscape.js, dagre layout, Chart.js. Zero external dependencies at
view time. Air-gap safe. ~1.5 MB per report. Looks identical whether
opened today or in five years.

Public surface:
  render_trace_report(items, project, module, ...)  -> str (HTML)
  render_audit_report(audit_data, project, module)  -> str (HTML)
  write_report(html, slug)                           -> Path

Design tokens (frozen, no theming):
  Modern minimalist palette, Inter typography, soft shadows, 16px
  border-radius on cards, generous whitespace.
"""

from __future__ import annotations

import base64
import datetime as _dt
import json
import re
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── Asset paths (relative to this file) ───────────────────────

_HERE = Path(__file__).resolve().parent
_ASSETS = _HERE / "assets"

# Pinned asset versions — change deliberately, never via floating CDN
_ASSET_FILES = {
    "cytoscape": _ASSETS / "cytoscape.min.js",
    "dagre": _ASSETS / "dagre.min.js",
    "cytoscape_dagre": _ASSETS / "cytoscape-dagre.js",
    "chart": _ASSETS / "chart.min.js",
    "inter_font": _ASSETS / "inter-variable.woff2",
}


def _load_text(path: Path) -> str:
    """Read a text asset (JS, etc.). Returns empty string on failure
    so report generation still works if an asset is missing — the
    diagram just won't render, but the rest of the HTML is intact."""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_b64(path: Path) -> str:
    """Read a binary asset and return base64 string for data: URIs."""
    try:
        return base64.b64encode(path.read_bytes()).decode("ascii")
    except Exception:
        return ""


# ── Frozen design tokens — same look every report ─────────────

_CSS = """
:root {
  --bg: #ffffff;
  --surface: #fafafa;
  --surface-2: #f4f4f5;
  --text: #0a0a0a;
  --text-muted: #6b7280;
  --text-soft: #9ca3af;
  --border: #e5e7eb;
  --border-soft: #f3f4f6;
  --accent: #6366f1;
  --accent-soft: #eef2ff;
  --good: #10b981;
  --good-bg: #ecfdf5;
  --partial: #f59e0b;
  --partial-bg: #fffbeb;
  --gap: #ef4444;
  --gap-bg: #fef2f2;
  --task: #3b82f6;
  --task-bg: #eff6ff;
  --test: #8b5cf6;
  --test-bg: #f5f3ff;
  --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.04);
  --shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.05), 0 2px 4px -2px rgb(0 0 0 / 0.05);
  --shadow-lg: 0 10px 15px -3px rgb(0 0 0 / 0.06), 0 4px 6px -4px rgb(0 0 0 / 0.06);
  --radius: 12px;
  --radius-sm: 8px;
  --radius-lg: 16px;
}

@font-face {
  font-family: 'Inter';
  font-style: normal;
  font-weight: 100 900;
  font-display: swap;
  src: url(data:font/woff2;base64,__INTER_FONT_B64__) format('woff2-variations');
}

* { box-sizing: border-box; }

html, body {
  margin: 0;
  padding: 0;
  font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
  font-feature-settings: 'cv11', 'ss01', 'ss03';
  color: var(--text);
  background: var(--bg);
  line-height: 1.55;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

body {
  max-width: 1280px;
  margin: 0 auto;
  padding: 64px 48px 96px;
}

header.hero {
  margin-bottom: 56px;
}
header.hero .eyebrow {
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-muted);
  margin: 0 0 12px;
}
header.hero h1 {
  font-size: 48px;
  font-weight: 700;
  letter-spacing: -0.025em;
  line-height: 1.1;
  margin: 0 0 16px;
}
header.hero .subtitle {
  font-size: 18px;
  color: var(--text-muted);
  margin: 0;
}
header.hero .meta {
  margin-top: 24px;
  font-size: 13px;
  color: var(--text-soft);
}

section {
  margin-bottom: 56px;
}
section h2 {
  font-size: 24px;
  font-weight: 600;
  letter-spacing: -0.015em;
  margin: 0 0 8px;
}
section .section-desc {
  color: var(--text-muted);
  margin: 0 0 24px;
  font-size: 15px;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 16px;
}
.stat-card {
  background: var(--surface);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius);
  padding: 20px 22px;
  transition: box-shadow 150ms ease;
}
.stat-card:hover {
  box-shadow: var(--shadow-md);
}
.stat-card .value {
  font-size: 36px;
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1;
  margin-bottom: 8px;
}
.stat-card .label {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.stat-card.accent-good .value { color: var(--good); }
.stat-card.accent-partial .value { color: var(--partial); }
.stat-card.accent-gap .value { color: var(--gap); }
.stat-card.accent-info .value { color: var(--accent); }

.chart-container {
  background: var(--surface);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius);
  padding: 32px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 32px;
  align-items: center;
}
.chart-container canvas {
  max-width: 100%;
}
.chart-container .chart-legend {
  font-size: 14px;
}
.chart-container .chart-legend ul {
  list-style: none;
  padding: 0;
  margin: 0;
}
.chart-container .chart-legend li {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 0;
  border-bottom: 1px solid var(--border-soft);
}
.chart-container .chart-legend li:last-child { border-bottom: none; }
.chart-container .chart-legend .swatch {
  width: 12px;
  height: 12px;
  border-radius: 3px;
  flex-shrink: 0;
}
.chart-container .chart-legend .count {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
  color: var(--text-muted);
  font-weight: 500;
}

#cy {
  width: 100%;
  height: 720px;
  background: var(--surface);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius);
  position: relative;
}

.diagram-toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.diagram-toolbar button {
  font-family: inherit;
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 8px 14px;
  cursor: pointer;
  transition: all 120ms ease;
}
.diagram-toolbar button:hover {
  background: var(--surface);
  border-color: var(--text-muted);
}
.diagram-toolbar .legend-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  padding: 6px 10px;
  border-radius: 999px;
  background: var(--surface-2);
  color: var(--text-muted);
}
.diagram-toolbar .legend-pill .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

table.report-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
  background: var(--bg);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius);
  overflow: hidden;
}
table.report-table th {
  text-align: left;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  padding: 14px 18px;
  background: var(--surface);
  border-bottom: 1px solid var(--border-soft);
}
table.report-table td {
  padding: 14px 18px;
  border-bottom: 1px solid var(--border-soft);
  vertical-align: top;
}
table.report-table tr:last-child td { border-bottom: none; }
table.report-table tr:hover td { background: var(--surface); }
table.report-table a {
  color: var(--accent);
  text-decoration: none;
  font-weight: 500;
}
table.report-table a:hover {
  text-decoration: underline;
}

.badge {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.badge.good { background: var(--good-bg); color: var(--good); }
.badge.partial { background: var(--partial-bg); color: var(--partial); }
.badge.gap { background: var(--gap-bg); color: var(--gap); }
.badge.task { background: var(--task-bg); color: var(--task); }
.badge.test { background: var(--test-bg); color: var(--test); }
.badge.neutral { background: var(--surface-2); color: var(--text-muted); }

.callout {
  background: var(--accent-soft);
  border-left: 3px solid var(--accent);
  border-radius: var(--radius-sm);
  padding: 16px 20px;
  margin: 24px 0;
  font-size: 14px;
  color: var(--text);
}
.callout strong { color: var(--accent); }

footer {
  margin-top: 96px;
  padding-top: 24px;
  border-top: 1px solid var(--border-soft);
  font-size: 13px;
  color: var(--text-soft);
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 12px;
}

@media (max-width: 768px) {
  body { padding: 32px 24px 64px; }
  header.hero h1 { font-size: 36px; }
  .chart-container { grid-template-columns: 1fr; }
}
"""


# ── Status / bucket helpers ───────────────────────────────────

def _bucket_for(item: Dict[str, Any]) -> str:
    has_task = bool(item.get("tasks"))
    has_test = bool(item.get("tests"))
    if has_task and has_test:
        return "good"
    if has_task or has_test:
        return "partial"
    return "gap"


def _short_key(art: Dict[str, Any], fallback_prefix: str, counter: List[int]) -> str:
    """Pick a friendly short key. Fall back to a sequential counter
    for OSLC-UUID-shape opaque identifiers (common in ETM)."""
    oslc_uuid = re.compile(r"^_?[A-Za-z0-9]{6,}-[A-Za-z0-9]{8,}$")
    for k in ("key", "identifier", "id"):
        v = art.get(k)
        if v and not oslc_uuid.match(str(v)):
            return str(v)
    counter[0] += 1
    return f"{fallback_prefix}-{counter[0]}"


def _safe_id(s: str) -> str:
    """Make a string safe to use as a Cytoscape node ID."""
    s = re.sub(r"[^A-Za-z0-9_]", "_", s or "")
    if not s or not s[0].isalpha():
        s = "n_" + s
    return s[:80]


def _esc_html(s: str) -> str:
    """Minimal HTML escape for text content (not attributes)."""
    if not s:
        return ""
    return (s.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


# ── Cytoscape data builder ────────────────────────────────────

def _build_cytoscape_elements(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert the trace items into a Cytoscape elements array."""
    elements: List[Dict[str, Any]] = []
    seen: set = set()
    tc_counter = [0]
    task_counter = [0]

    for it in items:
        req_url = it.get("req_url") or it.get("url") or ""
        req_key = it.get("req_key") or _short_key(it, "REQ", [0])
        req_title = it.get("req_title") or it.get("title") or "(untitled)"
        req_status = it.get("req_status") or ""
        bucket = _bucket_for(it)

        rid = _safe_id(f"REQ_{req_key}_{req_url[-8:]}")
        if rid not in seen:
            elements.append({
                "data": {
                    "id": rid,
                    "label": f"{req_key}",
                    "sublabel": req_title[:60],
                    "kind": bucket,
                    "url": req_url,
                    "tooltip": f"REQ {req_key} — {req_title}\nStatus: {req_status}\nBucket: {bucket}",
                }
            })
            seen.add(rid)

        for t in (it.get("tasks") or []):
            t_url = t.get("url", "")
            t_key = _short_key(t, "TASK", task_counter)
            t_title = t.get("title", "")
            tid = _safe_id(f"TASK_{t_key}_{t_url[-8:]}")
            if tid not in seen:
                elements.append({
                    "data": {
                        "id": tid,
                        "label": t_key,
                        "sublabel": t_title[:60],
                        "kind": "task",
                        "url": t_url,
                        "tooltip": f"EWM Task {t_key} — {t_title}\nStatus: {t.get('status', 'n/a')}",
                    }
                })
                seen.add(tid)
            elements.append({"data": {"source": rid, "target": tid, "kind": "implements"}})

        for tc in (it.get("tests") or []):
            tc_url = tc.get("url", "")
            tc_key = _short_key(tc, "TC", tc_counter)
            tc_title = tc.get("title", "")
            ttid = _safe_id(f"TC_{tc_key}_{tc_url[-8:]}")
            if ttid not in seen:
                elements.append({
                    "data": {
                        "id": ttid,
                        "label": tc_key,
                        "sublabel": tc_title[:60],
                        "kind": "test",
                        "url": tc_url,
                        "tooltip": f"ETM Test {tc_key} — {tc_title}\nStatus: {tc.get('status', 'n/a')}",
                    }
                })
                seen.add(ttid)
            elements.append({"data": {"source": rid, "target": ttid, "kind": "validates"}})

    return elements


_CYTOSCAPE_STYLE = [
    {
        "selector": "node",
        "style": {
            "background-color": "#ffffff",
            "border-width": 2,
            "label": "data(label)",
            "color": "#0a0a0a",
            "font-family": "Inter, system-ui, sans-serif",
            "font-size": "12px",
            "font-weight": "600",
            "text-valign": "center",
            "text-halign": "center",
            "text-wrap": "wrap",
            "text-max-width": "150px",
            "shape": "round-rectangle",
            "width": "180px",
            "height": "44px",
            "padding": "8px",
            "shadow-blur": 8,
            "shadow-color": "#000",
            "shadow-opacity": 0.06,
            "shadow-offset-y": 2,
        },
    },
    {"selector": "node[kind = 'good']", "style": {"border-color": "#10b981", "background-color": "#ecfdf5"}},
    {"selector": "node[kind = 'partial']", "style": {"border-color": "#f59e0b", "background-color": "#fffbeb"}},
    {"selector": "node[kind = 'gap']", "style": {"border-color": "#ef4444", "background-color": "#fef2f2", "border-width": 3}},
    {"selector": "node[kind = 'task']", "style": {"border-color": "#3b82f6", "background-color": "#eff6ff"}},
    {"selector": "node[kind = 'test']", "style": {"border-color": "#8b5cf6", "background-color": "#f5f3ff"}},
    {
        "selector": "node:active, node:hover",
        "style": {
            "shadow-opacity": 0.18,
            "shadow-blur": 16,
            "border-width": 3,
        },
    },
    {
        "selector": "edge",
        "style": {
            "width": 1.5,
            "line-color": "#d1d5db",
            "target-arrow-color": "#9ca3af",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            "arrow-scale": 0.9,
        },
    },
    {
        "selector": "edge[kind = 'validates']",
        "style": {
            "line-color": "#c4b5fd",
            "target-arrow-color": "#a78bfa",
            "line-style": "dashed",
        },
    },
]


# ── Stat / coverage helpers ───────────────────────────────────

def _coverage_stats(items: List[Dict[str, Any]]) -> Dict[str, int]:
    good = partial = gap = 0
    n_tasks = n_tests = 0
    for it in items:
        b = _bucket_for(it)
        if b == "good": good += 1
        elif b == "partial": partial += 1
        else: gap += 1
        n_tasks += len(it.get("tasks") or [])
        n_tests += len(it.get("tests") or [])
    return {
        "total": len(items),
        "good": good,
        "partial": partial,
        "gap": gap,
        "tasks": n_tasks,
        "tests": n_tests,
    }


def _gap_rows(items: List[Dict[str, Any]]) -> str:
    """HTML <tr> rows for the gap detail table — only reqs that aren't 'good'."""
    rows = []
    for it in items:
        b = _bucket_for(it)
        if b == "good":
            continue
        req_key = _esc_html(it.get("req_key") or "?")
        req_title = _esc_html(it.get("req_title") or "(untitled)")
        req_url = it.get("req_url") or "#"
        status = _esc_html(it.get("req_status") or "n/a")
        n_tasks = len(it.get("tasks") or [])
        n_tests = len(it.get("tests") or [])
        bucket_label = "Gap" if b == "gap" else "Partial"
        bucket_class = "gap" if b == "gap" else "partial"
        missing = []
        if not it.get("tasks"): missing.append("task")
        if not it.get("tests"): missing.append("test")
        missing_str = " &amp; ".join(missing) or "—"
        rows.append(
            f"<tr>"
            f"<td><a href=\"{_esc_html(req_url)}\" target=\"_blank\" rel=\"noopener\">{req_key}</a></td>"
            f"<td>{req_title}</td>"
            f"<td><span class=\"badge {bucket_class}\">{bucket_label}</span></td>"
            f"<td>{status}</td>"
            f"<td>{n_tasks}</td>"
            f"<td>{n_tests}</td>"
            f"<td>Missing: {missing_str}</td>"
            f"</tr>"
        )
    if not rows:
        return "<tr><td colspan=\"7\" style=\"text-align:center;color:var(--text-muted);padding:32px\">No gaps — every requirement has both an implementing task and a validating test. 🎉</td></tr>"
    return "\n".join(rows)


# ── Main report rendering ─────────────────────────────────────

def render_trace_report(
    items: List[Dict[str, Any]],
    *,
    project: str = "",
    module: str = "",
    version: str = "",
    timestamp: Optional[str] = None,
) -> str:
    """Build a complete self-contained HTML document for the trace
    report. Returns the full HTML as a string."""
    stats = _coverage_stats(items)
    elements = _build_cytoscape_elements(items)
    ts = timestamp or _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # Inline assets
    cytoscape_js = _load_text(_ASSET_FILES["cytoscape"])
    dagre_js = _load_text(_ASSET_FILES["dagre"])
    cy_dagre_js = _load_text(_ASSET_FILES["cytoscape_dagre"])
    chart_js = _load_text(_ASSET_FILES["chart"])
    inter_b64 = _load_b64(_ASSET_FILES["inter_font"])

    css = _CSS.replace("__INTER_FONT_B64__", inter_b64)

    cy_elements_json = json.dumps(elements, separators=(",", ":"))
    cy_style_json = json.dumps(_CYTOSCAPE_STYLE, separators=(",", ":"))

    chart_data = {
        "labels": ["Full coverage", "Partial", "Gap"],
        "values": [stats["good"], stats["partial"], stats["gap"]],
        "colors": ["#10b981", "#f59e0b", "#ef4444"],
    }
    chart_json = json.dumps(chart_data, separators=(",", ":"))

    title_html = _esc_html(f"{module or 'Module'} — Traceability Report")
    project_html = _esc_html(project or "—")
    module_html = _esc_html(module or "—")

    # ── Assemble ────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title_html}</title>
<style>{css}</style>
<script>{cytoscape_js}</script>
<script>{dagre_js}</script>
<script>{cy_dagre_js}</script>
<script>{chart_js}</script>
</head>
<body>

<header class="hero">
  <p class="eyebrow">elm-mcp · Traceability Report</p>
  <h1>{module_html}</h1>
  <p class="subtitle">Project: {project_html}</p>
  <p class="meta">Generated {_esc_html(ts)} · elm-mcp v{_esc_html(version)}</p>
</header>

<section>
  <h2>Coverage Summary</h2>
  <p class="section-desc">Snapshot of how many requirements are covered by implementing tasks and validating tests.</p>
  <div class="stat-grid">
    <div class="stat-card"><div class="value">{stats['total']}</div><div class="label">Requirements</div></div>
    <div class="stat-card accent-good"><div class="value">{stats['good']}</div><div class="label">Full coverage</div></div>
    <div class="stat-card accent-partial"><div class="value">{stats['partial']}</div><div class="label">Partial</div></div>
    <div class="stat-card accent-gap"><div class="value">{stats['gap']}</div><div class="label">Gap</div></div>
    <div class="stat-card accent-info"><div class="value">{stats['tasks']}</div><div class="label">Tasks linked</div></div>
    <div class="stat-card accent-info"><div class="value">{stats['tests']}</div><div class="label">Tests linked</div></div>
  </div>
</section>

<section>
  <h2>Coverage Distribution</h2>
  <p class="section-desc">Where the requirements sit on the coverage spectrum.</p>
  <div class="chart-container">
    <canvas id="coverageChart" width="320" height="320"></canvas>
    <div class="chart-legend">
      <ul>
        <li><span class="swatch" style="background:#10b981"></span> Full coverage<span class="count">{stats['good']}</span></li>
        <li><span class="swatch" style="background:#f59e0b"></span> Partial<span class="count">{stats['partial']}</span></li>
        <li><span class="swatch" style="background:#ef4444"></span> Gap<span class="count">{stats['gap']}</span></li>
      </ul>
    </div>
  </div>
</section>

<section>
  <h2>Traceability Graph</h2>
  <p class="section-desc">Every node is clickable — opens the artifact in DNG / EWM / ETM in a new tab. Drag to pan, scroll to zoom.</p>
  <div class="diagram-toolbar">
    <button onclick="window.cy.fit()">Fit to screen</button>
    <button onclick="window.cy.center()">Center</button>
    <button onclick="window.cy.zoom(1); window.cy.center()">Reset zoom</button>
    <span class="legend-pill"><span class="dot" style="background:#10b981"></span> Full coverage</span>
    <span class="legend-pill"><span class="dot" style="background:#f59e0b"></span> Partial</span>
    <span class="legend-pill"><span class="dot" style="background:#ef4444"></span> Gap</span>
    <span class="legend-pill"><span class="dot" style="background:#3b82f6"></span> EWM Task</span>
    <span class="legend-pill"><span class="dot" style="background:#8b5cf6"></span> ETM Test</span>
  </div>
  <div id="cy"></div>
</section>

<section>
  <h2>Gap Detail</h2>
  <p class="section-desc">Requirements that aren't fully covered. Click any requirement key to open it in DNG.</p>
  <table class="report-table">
    <thead>
      <tr>
        <th>Req</th>
        <th>Title</th>
        <th>Coverage</th>
        <th>Status</th>
        <th>Tasks</th>
        <th>Tests</th>
        <th>Notes</th>
      </tr>
    </thead>
    <tbody>
      {_gap_rows(items)}
    </tbody>
  </table>
</section>

<section>
  <div class="callout">
    <strong>For AI-powered semantic scoring</strong> — does each requirement actually capture intent? Are they consistent across the set? What's the best rewrite for the weak ones? — open this module in the <strong>Requirements Quality Assistant</strong> agent in <strong>IBM ELM AI Hub</strong>. This report is the deterministic floor; AI Hub is the AI ceiling.
  </div>
</section>

<footer>
  <span>elm-mcp v{_esc_html(version)} · Self-contained report · Air-gap safe</span>
  <span>Generated {_esc_html(ts)}</span>
</footer>

<script>
  // ── Cytoscape ──────────────────────────────────────────
  cytoscape.use(window.cytoscapeDagre);
  window.cy = cytoscape({{
    container: document.getElementById('cy'),
    elements: {cy_elements_json},
    style: {cy_style_json},
    layout: {{
      name: 'dagre',
      rankDir: 'LR',
      nodeSep: 22,
      rankSep: 110,
      edgeSep: 14,
    }},
    minZoom: 0.2,
    maxZoom: 2.5,
    wheelSensitivity: 0.25,
  }});
  window.cy.on('tap', 'node', function(evt) {{
    var url = evt.target.data('url');
    if (url) window.open(url, '_blank', 'noopener');
  }});
  window.cy.nodes().forEach(function(n) {{
    var t = n.data('tooltip');
    if (t) n.qtip = t;
  }});

  // ── Coverage Chart ─────────────────────────────────────
  (function(){{
    var d = {chart_json};
    var ctx = document.getElementById('coverageChart').getContext('2d');
    new Chart(ctx, {{
      type: 'doughnut',
      data: {{
        labels: d.labels,
        datasets: [{{
          data: d.values,
          backgroundColor: d.colors,
          borderColor: '#ffffff',
          borderWidth: 4,
          hoverOffset: 8,
        }}]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: true,
        plugins: {{
          legend: {{ display: false }},
          tooltip: {{
            backgroundColor: '#0a0a0a',
            titleFont: {{ family: 'Inter', size: 13, weight: '600' }},
            bodyFont: {{ family: 'Inter', size: 13 }},
            padding: 12,
            cornerRadius: 8,
            displayColors: false,
          }}
        }},
        cutout: '62%',
        animation: {{
          animateScale: true,
          animateRotate: true,
          duration: 900,
        }}
      }}
    }});
  }})();
</script>

</body>
</html>"""
    return html


def render_audit_report(
    audit: Dict[str, Any],
    *,
    project: str = "",
    module: str = "",
    version: str = "",
    timestamp: Optional[str] = None,
) -> str:
    """Quality-audit report — module-level lint findings + status.
    `audit` shape:
      {
        good: int, fair: int, weak: int, poor: int,  # bucket counts
        avg_score: int, approved_pct: int, total: int,
        worst: [{title, url, score, bucket}],
        rule_counts: {"GtWR R6": int, ...},
      }
    """
    ts = timestamp or _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    inter_b64 = _load_b64(_ASSET_FILES["inter_font"])
    chart_js = _load_text(_ASSET_FILES["chart"])
    css = _CSS.replace("__INTER_FONT_B64__", inter_b64)

    g = int(audit.get("good", 0))
    f = int(audit.get("fair", 0))
    w = int(audit.get("weak", 0))
    p = int(audit.get("poor", 0))
    total = int(audit.get("total", g + f + w + p))
    avg = int(audit.get("avg_score", 0))
    approved_pct = int(audit.get("approved_pct", 0))

    chart_data = {
        "labels": ["Good (>=85)", "Fair (65-84)", "Weak (40-64)", "Poor (<40)"],
        "values": [g, f, w, p],
        "colors": ["#10b981", "#3b82f6", "#f59e0b", "#ef4444"],
    }
    chart_json = json.dumps(chart_data, separators=(",", ":"))

    # Worst-scoring requirements table
    worst_rows = []
    for r in audit.get("worst", [])[:10]:
        title = _esc_html((r.get("title") or "(no title)")[:80])
        url = r.get("url") or "#"
        score = int(r.get("score", 0))
        bucket = r.get("bucket", "weak")
        worst_rows.append(
            f"<tr>"
            f"<td><a href=\"{_esc_html(url)}\" target=\"_blank\" rel=\"noopener\">{title}</a></td>"
            f"<td><strong>{score}</strong>/100</td>"
            f"<td><span class=\"badge {bucket}\">{_esc_html(bucket)}</span></td>"
            f"</tr>"
        )
    worst_html = "\n".join(worst_rows) or (
        '<tr><td colspan="3" style="text-align:center;color:var(--text-muted);padding:32px">'
        'All requirements scoring 85+. 🎉</td></tr>'
    )

    # Rule violations table
    rule_rows = []
    rc = audit.get("rule_counts", {}) or {}
    for rule, count in sorted(rc.items(), key=lambda kv: -kv[1])[:8]:
        rule_rows.append(
            f"<tr><td>{_esc_html(rule)}</td><td><strong>{int(count)}</strong> occurrences</td></tr>"
        )
    rule_html = "\n".join(rule_rows) or (
        '<tr><td colspan="2" style="text-align:center;color:var(--text-muted);padding:32px">'
        'No rule violations recorded.</td></tr>'
    )

    title_html = _esc_html(f"{module or 'Module'} — Quality Audit")
    project_html = _esc_html(project or "—")
    module_html = _esc_html(module or "—")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title_html}</title>
<style>{css}</style>
<script>{chart_js}</script>
</head>
<body>

<header class="hero">
  <p class="eyebrow">elm-mcp · Quality Audit</p>
  <h1>{module_html}</h1>
  <p class="subtitle">Project: {project_html} · INCOSE GtWR + IEEE 29148 pattern lint</p>
  <p class="meta">Generated {_esc_html(ts)} · elm-mcp v{_esc_html(version)}</p>
</header>

<section>
  <h2>At a Glance</h2>
  <div class="stat-grid">
    <div class="stat-card"><div class="value">{total}</div><div class="label">Requirements</div></div>
    <div class="stat-card accent-good"><div class="value">{avg}</div><div class="label">Avg score</div></div>
    <div class="stat-card accent-info"><div class="value">{approved_pct}%</div><div class="label">Approved</div></div>
    <div class="stat-card accent-gap"><div class="value">{w + p}</div><div class="label">Weak / Poor</div></div>
  </div>
</section>

<section>
  <h2>Quality Distribution</h2>
  <p class="section-desc">Where the requirements sit on the quality bucket spectrum.</p>
  <div class="chart-container">
    <canvas id="qualityChart" width="320" height="320"></canvas>
    <div class="chart-legend">
      <ul>
        <li><span class="swatch" style="background:#10b981"></span> Good (&ge;85)<span class="count">{g}</span></li>
        <li><span class="swatch" style="background:#3b82f6"></span> Fair (65-84)<span class="count">{f}</span></li>
        <li><span class="swatch" style="background:#f59e0b"></span> Weak (40-64)<span class="count">{w}</span></li>
        <li><span class="swatch" style="background:#ef4444"></span> Poor (&lt;40)<span class="count">{p}</span></li>
      </ul>
    </div>
  </div>
</section>

<section>
  <h2>Lowest-Scoring Requirements</h2>
  <p class="section-desc">Worst 10 requirements by pattern-based quality score. Click any to open in DNG.</p>
  <table class="report-table">
    <thead><tr><th>Requirement</th><th>Score</th><th>Bucket</th></tr></thead>
    <tbody>{worst_html}</tbody>
  </table>
</section>

<section>
  <h2>Most-Violated Rules</h2>
  <p class="section-desc">INCOSE Guide to Writing Requirements (GtWR) and IEEE 29148 patterns triggered most often.</p>
  <table class="report-table">
    <thead><tr><th>Rule</th><th>Frequency</th></tr></thead>
    <tbody>{rule_html}</tbody>
  </table>
</section>

<section>
  <div class="callout">
    <strong>This is the deterministic floor.</strong> Pattern matching catches syntactic smells. For semantic scoring — does each requirement actually capture intent? Is it consistent with the rest of the set? What's the best rewrite? — open this module in the <strong>Requirements Quality Assistant</strong> agent in <strong>IBM ELM AI Hub</strong>.
  </div>
</section>

<footer>
  <span>elm-mcp v{_esc_html(version)} · Self-contained report · Air-gap safe</span>
  <span>Generated {_esc_html(ts)}</span>
</footer>

<script>
  (function(){{
    var d = {chart_json};
    var ctx = document.getElementById('qualityChart').getContext('2d');
    new Chart(ctx, {{
      type: 'doughnut',
      data: {{
        labels: d.labels,
        datasets: [{{
          data: d.values,
          backgroundColor: d.colors,
          borderColor: '#ffffff',
          borderWidth: 4,
          hoverOffset: 8,
        }}]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: true,
        plugins: {{
          legend: {{ display: false }},
          tooltip: {{
            backgroundColor: '#0a0a0a',
            titleFont: {{ family: 'Inter', size: 13, weight: '600' }},
            bodyFont: {{ family: 'Inter', size: 13 }},
            padding: 12,
            cornerRadius: 8,
            displayColors: false,
          }}
        }},
        cutout: '62%',
        animation: {{ animateScale: true, animateRotate: true, duration: 900 }}
      }}
    }});
  }})();
</script>

</body>
</html>"""
    return html


# ── File writing ──────────────────────────────────────────────

_REPORTS_DIR = Path.home() / ".elm-mcp" / "reports"


def _slugify(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9-]+", "-", (s or "").strip()).strip("-").lower()
    return s[:60] or "report"


def write_report(html: str, *, kind: str, project: str = "",
                 module: str = "") -> Path:
    """Write the HTML to ~/.elm-mcp/reports/ with a slugified filename.
    Returns the absolute Path. Also updates a `latest.html` symlink
    (best effort).
    """
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.utcnow().strftime("%Y-%m-%d-%H%M")
    slug_parts = [_slugify(project), _slugify(module), kind, ts]
    slug = "-".join(p for p in slug_parts if p) + ".html"
    path = _REPORTS_DIR / slug
    path.write_text(html, encoding="utf-8")

    latest = _REPORTS_DIR / f"latest-{kind}.html"
    try:
        if latest.exists() or latest.is_symlink():
            latest.unlink()
        latest.symlink_to(path.name)
    except Exception:
        # Some filesystems (FAT, certain mounts) don't support symlinks.
        # Not critical — the dated file is the source of truth.
        pass

    return path
