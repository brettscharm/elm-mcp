"""HTML renderer for the analyze_change_impact tool.

Produces a self-contained polished HTML report — risk dashboard, interactive
Cytoscape impact graph, affected-artifact tables grouped by domain,
compliance touches, reviewer recommendations. Same air-gap-safe pattern as
generate_trace_report.

Writes to ~/.elm-mcp/reports/. Returns the file path.
"""
from __future__ import annotations
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


_REPORTS_DIR = Path.home() / ".elm-mcp" / "reports"

_RISK_COLOR = {
    "HIGH": "#dc2626",
    "MEDIUM": "#ea580c",
    "LOW": "#16a34a",
    "UNKNOWN": "#6b7280",
}

_DOMAIN_COLOR = {
    "DNG": "#1F4E78",
    "EWM": "#7c3aed",
    "ETM": "#0891b2",
    "code": "#374151",
    "external": "#6b7280",
    "unknown": "#9ca3af",
}


def _esc(s: Any) -> str:
    return html.escape(str(s)) if s is not None else ""


def _node_to_cyto(node) -> Dict[str, Any]:
    return {
        "data": {
            "id": node.url,
            "label": (node.title or node.url)[:70],
            "url": node.url,
            "domain": node.domain,
            "type": node.artifact_type,
            "status": node.status,
            "hop": node.hop,
        }
    }


def _edge_to_cyto(from_url: str, to_url: str, link_type: str) -> Dict[str, Any]:
    return {
        "data": {
            "id": f"{from_url}|{to_url}|{link_type}",
            "source": from_url,
            "target": to_url,
            "label": link_type,
        }
    }


def render_impact_report(graph, *, project: str = "", version: str = "") -> str:
    """Render the full HTML report as a string."""
    counts = graph.summary_counts()
    risk = graph.risk or "UNKNOWN"
    risk_color = _RISK_COLOR.get(risk, _RISK_COLOR["UNKNOWN"])
    by_domain = graph.by_domain()

    # Build Cytoscape data
    elements: List[Dict[str, Any]] = [_node_to_cyto(graph.seed)]
    for n in graph.nodes.values():
        if n.url == graph.seed.url:
            continue
        elements.append(_node_to_cyto(n))
    for (f, t, lt) in graph.edges:
        elements.append(_edge_to_cyto(f, t, lt))

    elements_json = json.dumps(elements)
    risk_factors_html = "".join(
        f"<li>{_esc(f)}</li>" for f in graph.risk_factors
    ) or "<li>—</li>"

    reviewers_html = (
        "".join(f"<li>{_esc(r)}</li>" for r in graph.suggested_reviewers)
        if graph.suggested_reviewers else "<li>—</li>"
    )

    compliance_html = ""
    if graph.compliance_touches:
        rows = "".join(
            f"<tr><td>{_esc(c['framework'])}</td>"
            f"<td>{_esc(c['ref'])}</td>"
            f"<td><a href='{_esc(c['via_artifact'])}' target='_blank'>"
            f"link</a></td></tr>"
            for c in graph.compliance_touches
        )
        compliance_html = f"""
        <section>
          <h2>Compliance touches</h2>
          <table>
            <thead><tr><th>Framework</th><th>Reference</th>
            <th>Via artifact</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </section>"""

    domain_sections = ""
    for domain in ("DNG", "EWM", "ETM", "code"):
        nodes = by_domain.get(domain, [])
        if not nodes:
            continue
        domain_color = _DOMAIN_COLOR.get(domain, "#6b7280")
        rows = "".join(
            f"<tr>"
            f"<td><span class='hop'>{n.hop}</span></td>"
            f"<td>{_esc(n.title)}</td>"
            f"<td>{_esc(n.artifact_type)}</td>"
            f"<td>{_esc(n.status)}</td>"
            f"<td><a href='{_esc(n.url)}' target='_blank'>open ↗</a></td>"
            f"</tr>"
            for n in sorted(nodes, key=lambda x: (x.hop, x.title))
        )
        domain_sections += f"""
        <section>
          <h2>
            <span class='dot' style='background:{domain_color}'></span>
            {domain} — {len(nodes)} affected
          </h2>
          <table>
            <thead><tr><th>Hop</th><th>Title</th><th>Type</th>
            <th>Status</th><th>Link</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </section>"""

    seed_block = f"""
      <div class='seed'>
        <div class='seed-label'>SEED</div>
        <div class='seed-title'>{_esc(graph.seed.title)}</div>
        <div class='seed-meta'>
          {_esc(graph.seed.domain)} · {_esc(graph.seed.artifact_type or "—")}
          {f" · status {_esc(graph.seed.status)}" if graph.seed.status else ""}
        </div>
        <div class='seed-url'>
          <a href='{_esc(graph.seed.url)}' target='_blank'>
            {_esc(graph.seed.url)}
          </a>
        </div>
      </div>
    """

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    project_label = _esc(project) if project else "—"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Change Impact — {_esc(graph.seed.title)}</title>
<script src="https://unpkg.com/cytoscape@3.28.1/dist/cytoscape.min.js"></script>
<style>
  :root {{
    --bg: #fafafa;
    --fg: #111827;
    --muted: #6b7280;
    --border: #e5e7eb;
    --card: #ffffff;
    --accent: #1F4E78;
    --risk: {risk_color};
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    background: var(--bg); color: var(--fg); margin: 0;
    line-height: 1.5;
  }}
  header {{
    background: var(--card); border-bottom: 1px solid var(--border);
    padding: 24px 40px;
  }}
  header h1 {{ margin: 0; font-size: 24px; font-weight: 700; }}
  header .meta {{ color: var(--muted); font-size: 14px; margin-top: 4px; }}
  main {{ max-width: 1280px; margin: 0 auto; padding: 32px 40px; }}
  .grid {{
    display: grid; grid-template-columns: 2fr 3fr; gap: 24px;
    margin-bottom: 32px;
  }}
  .card {{
    background: var(--card); border: 1px solid var(--border);
    border-radius: 12px; padding: 24px;
  }}
  .risk-card {{ border-left: 6px solid var(--risk); }}
  .risk-label {{
    color: var(--muted); font-size: 12px; text-transform: uppercase;
    letter-spacing: 0.05em; font-weight: 600;
  }}
  .risk-value {{
    color: var(--risk); font-size: 48px; font-weight: 800;
    line-height: 1.1; margin-top: 4px;
  }}
  .risk-factors {{ margin: 12px 0 0; padding-left: 20px; color: var(--fg); }}
  .risk-factors li {{ margin-bottom: 4px; }}
  .counts {{
    display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px;
    margin-top: 16px;
  }}
  .count {{ font-size: 14px; }}
  .count .num {{
    font-size: 28px; font-weight: 700; color: var(--accent); display: block;
  }}
  .seed {{
    background: var(--card); border: 2px solid var(--accent);
    border-radius: 12px; padding: 24px;
  }}
  .seed-label {{
    color: var(--accent); font-size: 12px; text-transform: uppercase;
    letter-spacing: 0.05em; font-weight: 700;
  }}
  .seed-title {{ font-size: 20px; font-weight: 700; margin-top: 6px; }}
  .seed-meta {{ color: var(--muted); font-size: 14px; margin-top: 4px; }}
  .seed-url {{
    margin-top: 12px; font-family: monospace; font-size: 12px;
    word-break: break-all;
  }}
  .seed-url a {{ color: var(--accent); text-decoration: none; }}
  .seed-url a:hover {{ text-decoration: underline; }}
  #cy {{
    width: 100%; height: 560px; background: #fff;
    border: 1px solid var(--border); border-radius: 12px;
  }}
  section {{
    background: var(--card); border: 1px solid var(--border);
    border-radius: 12px; padding: 24px; margin-bottom: 24px;
  }}
  section h2 {{
    margin: 0 0 16px; font-size: 18px; font-weight: 700;
    display: flex; align-items: center; gap: 8px;
  }}
  .dot {{
    display: inline-block; width: 12px; height: 12px; border-radius: 50%;
  }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  thead th {{
    text-align: left; padding: 8px 12px;
    background: #f3f4f6; border-bottom: 2px solid var(--border);
    color: var(--muted); font-weight: 600; text-transform: uppercase;
    font-size: 12px; letter-spacing: 0.03em;
  }}
  tbody td {{
    padding: 10px 12px; border-bottom: 1px solid var(--border);
    vertical-align: top;
  }}
  tbody tr:last-child td {{ border-bottom: none; }}
  .hop {{
    display: inline-block; width: 24px; height: 24px;
    background: #f3f4f6; border-radius: 50%; text-align: center;
    line-height: 24px; font-weight: 700; font-size: 12px;
  }}
  a {{ color: var(--accent); }}
  .reviewers {{ margin: 0; padding-left: 20px; }}
  .footer {{
    color: var(--muted); font-size: 12px; text-align: center;
    margin-top: 32px;
  }}
</style>
</head>
<body>
<header>
  <h1>Change Impact Analysis</h1>
  <div class="meta">
    {project_label} · Generated {timestamp}
    {f" · elm-mcp v{_esc(version)}" if version else ""}
  </div>
</header>
<main>
  <div class="grid">
    <div class="card risk-card">
      <div class="risk-label">Risk classification</div>
      <div class="risk-value">{_esc(risk)}</div>
      <ul class="risk-factors">{risk_factors_html}</ul>
      <div class="counts">
        <div class="count">
          <span class="num">{counts['total_affected']}</span>
          total affected artifacts
        </div>
        <div class="count">
          <span class="num">{counts['dng_reqs']}</span>
          DNG requirements
        </div>
        <div class="count">
          <span class="num">{counts['ewm_work_items']}</span>
          EWM work items
        </div>
        <div class="count">
          <span class="num">{counts['etm_tests']}</span>
          ETM test cases
        </div>
        <div class="count">
          <span class="num">{counts['compliance_controls']}</span>
          compliance refs
        </div>
        <div class="count">
          <span class="num">{len(graph.suggested_reviewers)}</span>
          suggested reviewers
        </div>
      </div>
    </div>
    {seed_block}
  </div>

  <section>
    <h2>Impact graph</h2>
    <div id="cy"></div>
    <p style="color:var(--muted); font-size:13px; margin-top:12px">
      Drag nodes to rearrange. Click a node to open the artifact in a
      new tab. Edge labels show OSLC link type.
    </p>
  </section>

  {domain_sections}

  {compliance_html}

  <section>
    <h2>Suggested reviewers</h2>
    <ul class="reviewers">{reviewers_html}</ul>
  </section>

  <div class="footer">
    elm-mcp · analyze_change_impact · self-contained · air-gap safe
  </div>
</main>
<script>
  const elements = {elements_json};
  const cy = cytoscape({{
    container: document.getElementById('cy'),
    elements: elements,
    layout: {{ name: 'breadthfirst', directed: true, padding: 30,
                 spacingFactor: 1.2 }},
    style: [
      {{
        selector: 'node',
        style: {{
          'background-color': (e) => ({{
              'DNG': '#1F4E78', 'EWM': '#7c3aed', 'ETM': '#0891b2',
              'code': '#374151'
          }})[e.data('domain')] || '#6b7280',
          'label': 'data(label)',
          'color': '#fff',
          'font-size': '11px',
          'text-valign': 'center',
          'text-halign': 'center',
          'text-wrap': 'wrap',
          'text-max-width': '120px',
          'width': '160px',
          'height': '60px',
          'shape': 'round-rectangle',
          'border-width': 2,
          'border-color': '#fff',
        }}
      }},
      {{
        selector: 'node[hop = 0]',
        style: {{
          'border-color': '{risk_color}',
          'border-width': 5,
          'width': '200px',
          'height': '80px',
          'font-weight': 'bold',
        }}
      }},
      {{
        selector: 'edge',
        style: {{
          'width': 2,
          'line-color': '#9ca3af',
          'target-arrow-color': '#9ca3af',
          'target-arrow-shape': 'triangle',
          'curve-style': 'bezier',
          'label': 'data(label)',
          'font-size': '9px',
          'color': '#6b7280',
          'text-rotation': 'autorotate',
          'text-background-color': '#fff',
          'text-background-opacity': 1,
          'text-background-padding': '3px',
        }}
      }}
    ]
  }});
  cy.on('tap', 'node', (e) => {{
    const url = e.target.data('url');
    if (url) window.open(url, '_blank');
  }});
</script>
</body>
</html>"""


def write_report(html_content: str, *, seed_title: str = "",
                  project: str = "") -> Path:
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    slug = "".join(
        c if c.isalnum() or c in "-_" else "_"
        for c in (seed_title or "impact").strip()
    )[:60] or "impact"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = _REPORTS_DIR / f"impact-{slug}-{ts}.html"
    path.write_text(html_content, encoding="utf-8")
    latest = _REPORTS_DIR / "latest-impact.html"
    try:
        if latest.exists() or latest.is_symlink():
            latest.unlink()
        latest.symlink_to(path)
    except OSError:
        pass
    return path
