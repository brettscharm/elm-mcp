"""HTML renderer for the generate_compliance_packet tool.

Produces a self-contained polished HTML packet — cover page, executive
summary, family-by-family control matrix with evidence cross-refs, gap
analysis, artifact inventory, sign-off checklist.

Writes to ~/.elm-mcp/reports/. Returns the file path.
"""
from __future__ import annotations
import html
from datetime import datetime
from pathlib import Path
from typing import Any


_REPORTS_DIR = Path.home() / ".elm-mcp" / "reports"

_STATUS_COLOR = {
    "READY": "#16a34a",
    "READY_WITH_OBSERVATIONS": "#ca8a04",
    "NEEDS_WORK": "#dc2626",
}

_STATUS_LABEL = {
    "READY": "READY FOR AUDIT",
    "READY_WITH_OBSERVATIONS": "READY WITH OBSERVATIONS",
    "NEEDS_WORK": "NEEDS WORK BEFORE AUDIT",
}


def _esc(s: Any) -> str:
    return html.escape(str(s)) if s is not None else ""


def render_compliance_packet(mapping, *, version: str = "") -> str:
    summary = mapping.summary
    status = summary.get("audit_readiness", "READY")
    status_color = _STATUS_COLOR.get(status, "#6b7280")
    status_label = _STATUS_LABEL.get(status, status)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Build family sections
    family_sections = ""
    for fam in mapping.families:
        controls = fam["controls"]
        if not controls:
            continue
        f_total = len(controls)
        f_mapped = sum(1 for c in controls if not c.is_gap)
        f_coverage = round(100 * f_mapped / f_total) if f_total else 0

        control_rows = ""
        for c in controls:
            status_icon = "✅" if not c.is_gap else "⚠️"
            evidence_html = ""
            if c.mapped_artifacts:
                items = "".join(
                    f"<li><a href='{_esc(a.get('url', ''))}' target='_blank'>"
                    f"{_esc(a.get('title', '?'))}</a>"
                    f" <span class='meta'>({_esc(a.get('module', '?'))} · "
                    f"{_esc(a.get('artifact_type', '?'))})</span></li>"
                    for a in c.mapped_artifacts
                )
                evidence_html = f"<ul class='evidence'>{items}</ul>"
            else:
                evidence_html = (
                    "<span class='gap-tag'>⚠️ GAP — no mapped evidence</span>"
                )
            applies = ""
            if c.applies_to:
                applies = (f" <span class='class-tag'>"
                            f"Class {'/'.join(c.applies_to)}</span>")
            control_rows += f"""
            <tr class='{'gap' if c.is_gap else 'mapped'}'>
              <td>{status_icon}</td>
              <td><strong>{_esc(c.id)}</strong>{applies}</td>
              <td>{_esc(c.title)}</td>
              <td><span class='priority-{_esc(c.priority).lower()}'>
                {_esc(c.priority)}</span></td>
              <td>{evidence_html}</td>
            </tr>"""

        family_sections += f"""
        <section class='family'>
          <header>
            <h2>
              <span class='family-id'>{_esc(fam['id'])}</span>
              {_esc(fam['name'])}
            </h2>
            <div class='family-coverage'>
              <strong>{f_mapped} / {f_total}</strong> controls mapped
              ({f_coverage}%)
            </div>
          </header>
          <table>
            <thead>
              <tr>
                <th>Status</th><th>Control</th><th>Title</th>
                <th>Priority</th><th>Evidence</th>
              </tr>
            </thead>
            <tbody>{control_rows}</tbody>
          </table>
        </section>"""

    # Gap analysis section
    gap_controls = [
        (fam["name"], c)
        for fam in mapping.families
        for c in fam["controls"]
        if c.is_gap
    ]
    gap_rows = ""
    if gap_controls:
        gap_rows = "".join(
            f"<tr class='{'p1' if c.priority == 'P1' else ''}'>"
            f"<td><strong>{_esc(c.id)}</strong></td>"
            f"<td>{_esc(c.title)}</td>"
            f"<td>{_esc(family)}</td>"
            f"<td><span class='priority-{_esc(c.priority).lower()}'>"
            f"{_esc(c.priority)}</span></td>"
            f"<td>{', '.join(_esc(e) for e in c.evidence_types)}</td>"
            f"</tr>"
            for family, c in gap_controls
        )
        gap_section = f"""
        <section>
          <h2>⚠️ Gap analysis — {len(gap_controls)} controls without evidence</h2>
          <p>These controls are required by the framework but have no
          matching artifacts in the scanned scope. Each represents an
          item to address before the audit.</p>
          <table>
            <thead><tr><th>Control</th><th>Title</th><th>Family</th>
            <th>Priority</th><th>Evidence types expected</th></tr></thead>
            <tbody>{gap_rows}</tbody>
          </table>
        </section>"""
    else:
        gap_section = """
        <section class='success'>
          <h2>✅ No gaps detected</h2>
          <p>Every framework control in scope has at least one mapped
          artifact as evidence.</p>
        </section>"""

    # Family-level summary table
    fam_summary_rows = "".join(
        f"<tr>"
        f"<td><strong>{_esc(f['id'])}</strong></td>"
        f"<td>{_esc(f['name'])}</td>"
        f"<td>{f['mapped']} / {f['total']}</td>"
        f"<td>{f['coverage_pct']}%</td>"
        f"<td class='gap-count'>{f['gap']}</td>"
        f"</tr>"
        for f in summary.get("by_family", [])
    )

    modules_html = ", ".join(_esc(m) for m in mapping.scope_modules) or "—"
    safety_html = ""
    if mapping.safety_class:
        safety_html = (f" · <strong>Safety class:</strong> "
                        f"{_esc(mapping.safety_class)}")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_esc(mapping.framework)} Compliance Packet — {_esc(mapping.project)}</title>
<style>
  :root {{
    --bg: #fafafa;
    --fg: #111827;
    --muted: #6b7280;
    --border: #e5e7eb;
    --card: #ffffff;
    --accent: #1F4E78;
    --status: {status_color};
    --p1: #dc2626;
    --p2: #ea580c;
    --p3: #6b7280;
    --gap: #fef3c7;
    --gap-border: #f59e0b;
    --mapped: transparent;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    background: var(--bg); color: var(--fg); margin: 0;
    line-height: 1.5;
  }}
  .cover {{
    background: linear-gradient(135deg, #1e3a5f 0%, #2c5282 100%);
    color: white; padding: 64px 40px;
  }}
  .cover .container {{ max-width: 1100px; margin: 0 auto; }}
  .cover h1 {{
    margin: 0; font-size: 36px; font-weight: 800;
  }}
  .cover .subtitle {{
    color: rgba(255,255,255,0.85); font-size: 16px;
    margin-top: 8px;
  }}
  .cover .meta {{
    color: rgba(255,255,255,0.7); font-size: 13px;
    margin-top: 24px;
  }}
  .status-bar {{
    background: var(--status); color: white; padding: 16px 0;
    text-align: center; font-size: 18px; font-weight: 700;
    letter-spacing: 0.02em;
  }}
  main {{ max-width: 1100px; margin: 0 auto; padding: 40px; }}
  .dashboard {{
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px;
    margin-bottom: 40px;
  }}
  .stat {{
    background: var(--card); border: 1px solid var(--border);
    border-radius: 12px; padding: 20px;
  }}
  .stat .label {{
    color: var(--muted); font-size: 12px; text-transform: uppercase;
    letter-spacing: 0.05em; font-weight: 600;
  }}
  .stat .value {{
    font-size: 36px; font-weight: 800; color: var(--accent);
    margin-top: 4px; line-height: 1.1;
  }}
  .stat.alert .value {{ color: var(--p1); }}
  section {{
    background: var(--card); border: 1px solid var(--border);
    border-radius: 12px; padding: 28px; margin-bottom: 24px;
  }}
  section.family header {{
    display: flex; justify-content: space-between;
    align-items: baseline; margin-bottom: 16px;
    padding-bottom: 12px; border-bottom: 2px solid var(--border);
  }}
  section h2 {{
    margin: 0; font-size: 20px; font-weight: 700;
  }}
  .family-id {{
    display: inline-block;
    background: var(--accent); color: white; font-size: 14px;
    padding: 4px 10px; border-radius: 6px; margin-right: 8px;
  }}
  .family-coverage {{
    color: var(--muted); font-size: 14px;
  }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  thead th {{
    text-align: left; padding: 10px 12px;
    background: #f3f4f6; border-bottom: 2px solid var(--border);
    color: var(--muted); font-weight: 600;
    text-transform: uppercase; font-size: 11px; letter-spacing: 0.05em;
  }}
  tbody td {{
    padding: 12px; border-bottom: 1px solid var(--border);
    vertical-align: top;
  }}
  tr.gap td {{ background: var(--gap); }}
  tr.p1 td {{ background: #fee2e2; }}
  .gap-tag {{
    color: var(--gap-border); font-weight: 600; font-size: 13px;
  }}
  .class-tag {{
    display: inline-block; background: var(--accent); color: white;
    font-size: 11px; padding: 1px 6px; border-radius: 4px;
    margin-left: 6px;
  }}
  .priority-p1 {{ color: var(--p1); font-weight: 700; }}
  .priority-p2 {{ color: var(--p2); font-weight: 600; }}
  .priority-p3 {{ color: var(--p3); font-weight: 500; }}
  ul.evidence {{ margin: 0; padding-left: 18px; font-size: 13px; }}
  ul.evidence li {{ margin-bottom: 4px; }}
  .meta {{ color: var(--muted); font-size: 12px; }}
  a {{ color: var(--accent); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .gap-count {{ font-weight: 700; }}
  .signoff-grid {{
    display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px;
    margin-top: 16px;
  }}
  .signoff-item {{
    background: #f9fafb; border: 1px solid var(--border);
    border-radius: 8px; padding: 16px;
  }}
  .signoff-item h4 {{
    margin: 0 0 8px; font-size: 14px; font-weight: 600;
    color: var(--muted); text-transform: uppercase;
    letter-spacing: 0.05em;
  }}
  .signoff-line {{
    border-bottom: 1px solid var(--border); padding: 16px 0;
    margin-top: 8px; min-height: 30px;
  }}
  .footer {{
    color: var(--muted); font-size: 12px; text-align: center;
    margin-top: 32px;
  }}
  @media print {{
    body {{ background: white; }}
    section {{ break-inside: avoid; }}
    section.family {{ page-break-inside: avoid; }}
  }}
</style>
</head>
<body>
<div class="cover">
  <div class="container">
    <h1>{_esc(mapping.framework)} Compliance Packet</h1>
    <div class="subtitle">{_esc(mapping.display_name)}</div>
    <div class="meta">
      <strong>Project:</strong> {_esc(mapping.project)} ·
      <strong>Modules in scope:</strong> {modules_html}{safety_html} ·
      <strong>Generated:</strong> {timestamp}
      {f"· elm-mcp v{_esc(version)}" if version else ""}
    </div>
  </div>
</div>
<div class="status-bar">{status_label}</div>

<main>
  <div class="dashboard">
    <div class="stat">
      <div class="label">Coverage</div>
      <div class="value">{summary.get('coverage_pct', 0)}%</div>
    </div>
    <div class="stat">
      <div class="label">Controls mapped</div>
      <div class="value">{summary.get('mapped_controls', 0)}</div>
    </div>
    <div class="stat {'alert' if summary.get('gap_controls', 0) > 0 else ''}">
      <div class="label">Gap controls</div>
      <div class="value">{summary.get('gap_controls', 0)}</div>
    </div>
    <div class="stat {'alert' if summary.get('p1_gaps', 0) > 0 else ''}">
      <div class="label">P1 gaps</div>
      <div class="value">{summary.get('p1_gaps', 0)}</div>
    </div>
  </div>

  <section>
    <h2>Executive summary</h2>
    <p><strong>Framework:</strong> {_esc(mapping.framework)} {_esc(mapping.revision)}</p>
    <p><strong>Audit readiness:</strong> {status_label}</p>
    <p><strong>Scope:</strong> {len(mapping.scope_modules)} module(s),
    {summary.get('artifact_inventory_size', 0)} artifact(s) scanned,
    {summary.get('total_evidence_links', 0)} evidence link(s) established
    across {summary.get('total_controls', 0)} controls.</p>
    <h3 style="margin-top: 24px">Family coverage</h3>
    <table>
      <thead><tr><th>Family</th><th>Name</th><th>Mapped</th>
      <th>Coverage</th><th>Gaps</th></tr></thead>
      <tbody>{fam_summary_rows}</tbody>
    </table>
  </section>

  {gap_section}

  <h2 style="font-size: 24px; margin: 32px 0 16px">Control mapping by family</h2>

  {family_sections}

  <section>
    <h2>Sign-off checklist</h2>
    <p>To finalize this packet for audit submission, complete the following.</p>
    <div class="signoff-grid">
      <div class="signoff-item">
        <h4>Compliance Officer review</h4>
        <div class="signoff-line"></div>
      </div>
      <div class="signoff-item">
        <h4>Quality Assurance review</h4>
        <div class="signoff-line"></div>
      </div>
      <div class="signoff-item">
        <h4>Engineering Lead review</h4>
        <div class="signoff-line"></div>
      </div>
      <div class="signoff-item">
        <h4>Security review</h4>
        <div class="signoff-line"></div>
      </div>
    </div>
  </section>

  <div class="footer">
    elm-mcp · generate_compliance_packet · self-contained · air-gap safe
  </div>
</main>
</body>
</html>"""


def write_report(html_content: str, *, project: str = "",
                  framework: str = "") -> Path:
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    slug_proj = "".join(
        c if c.isalnum() or c in "-_" else "_"
        for c in (project or "project").strip()
    )[:30] or "project"
    slug_fw = "".join(
        c if c.isalnum() or c in "-_" else "_"
        for c in (framework or "framework").strip()
    )[:20] or "framework"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = _REPORTS_DIR / f"compliance-{slug_fw}-{slug_proj}-{ts}.html"
    path.write_text(html_content, encoding="utf-8")
    latest = _REPORTS_DIR / f"latest-compliance-{slug_fw}.html"
    try:
        if latest.exists() or latest.is_symlink():
            latest.unlink()
        latest.symlink_to(path)
    except OSError:
        pass
    return path
