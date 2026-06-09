"""Compliance packet generator.

Used by the `generate_compliance_packet` MCP tool. Loads a framework
template (YAML), scans DNG artifacts for matching control references,
builds a control-by-control mapping with evidence + gap analysis, and
returns the structured data the HTML renderer turns into an audit-ready
packet.

The mapping logic mirrors analyze_change_impact's compliance detection
but operates at module scope instead of single-artifact scope.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import yaml
except ImportError:
    yaml = None


_FRAMEWORK_DIR = Path(__file__).parent / "compliance"


@dataclass
class Control:
    id: str
    title: str
    family: str
    priority: str = "P2"
    applies_to: List[str] = field(default_factory=list)
    evidence_types: List[str] = field(default_factory=list)
    mapped_artifacts: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def is_gap(self) -> bool:
        return len(self.mapped_artifacts) == 0


@dataclass
class ComplianceMapping:
    framework: str
    revision: str
    display_name: str
    project: str
    scope_modules: List[str]
    safety_class: Optional[str]
    families: List[Dict[str, Any]]  # each: {id, name, controls: List[Control]}
    summary: Dict[str, Any] = field(default_factory=dict)
    artifact_inventory: List[Dict[str, Any]] = field(default_factory=list)


def _load_framework(framework_short_name: str) -> Optional[Dict]:
    """Load a framework YAML by short_name (case-insensitive)."""
    if not yaml:
        return None
    target = framework_short_name.lower().replace("-", "_").replace(" ", "_")
    if not _FRAMEWORK_DIR.exists():
        return None
    for f in _FRAMEWORK_DIR.glob("*.yaml"):
        try:
            data = yaml.safe_load(f.read_text())
            short = (data.get("short_name") or "").lower().replace("-", "_")
            if short == target:
                return data
        except Exception:
            continue
    return None


def list_frameworks() -> List[Dict[str, str]]:
    """Inventory of available frameworks for the tool's error messages."""
    if not yaml or not _FRAMEWORK_DIR.exists():
        return []
    out = []
    for f in _FRAMEWORK_DIR.glob("*.yaml"):
        try:
            data = yaml.safe_load(f.read_text())
            out.append({
                "short_name": data.get("short_name", f.stem),
                "display_name": data.get("display_name", f.stem),
                "framework": data.get("framework", "?"),
            })
        except Exception:
            continue
    return out


def generate(
    client: Any,
    project_identifier: str,
    framework_short_name: str,
    module_filter: Optional[List[str]] = None,
    safety_class: Optional[str] = None,
) -> ComplianceMapping:
    """Build the compliance mapping from DNG artifacts + framework template."""
    framework_data = _load_framework(framework_short_name)
    if not framework_data:
        raise ValueError(
            f"Unknown framework: '{framework_short_name}'. "
            f"Available: {[f['short_name'] for f in list_frameworks()]}"
        )

    # Resolve project + modules
    projects = client.list_projects()
    project = _find_project(projects, project_identifier)
    if not project:
        raise ValueError(f"DNG project not found: '{project_identifier}'")

    modules = client.get_modules(project["url"]) or []
    if module_filter:
        wanted = {m.lower() for m in module_filter}
        modules = [m for m in modules
                    if any(w in m.get("title", "").lower() for w in wanted)]

    # Collect artifacts across modules
    artifacts: List[Dict[str, Any]] = []
    for mod in modules:
        try:
            reqs = client.get_module_requirements(mod["url"]) or []
        except Exception:
            reqs = []
        for r in reqs:
            r["_module"] = mod.get("title", "?")
            artifacts.append(r)

    # Build the family/control list with empty mapped lists
    families: List[Dict[str, Any]] = []
    for fam_data in framework_data.get("families", []):
        controls = []
        for c_data in fam_data.get("controls", []):
            controls.append(Control(
                id=c_data["id"],
                title=c_data.get("title", ""),
                family=fam_data["name"],
                priority=c_data.get("priority", "P2"),
                applies_to=c_data.get("applies_to", []),
                evidence_types=c_data.get("evidence_types", []),
            ))
        families.append({
            "id": fam_data["id"],
            "name": fam_data["name"],
            "controls": controls,
        })

    # Build detection patterns
    patterns = [re.compile(p, re.IGNORECASE)
                 for p in framework_data.get("detection_patterns", [])]

    # Map artifacts to controls
    _map_artifacts(artifacts, families, patterns)

    # Filter by safety class if applicable (IEC 62304 etc.)
    if safety_class:
        for fam in families:
            fam["controls"] = [
                c for c in fam["controls"]
                if not c.applies_to or safety_class in c.applies_to
            ]

    # Build summary
    summary = _build_summary(families, artifacts, safety_class)

    mapping = ComplianceMapping(
        framework=framework_data["framework"],
        revision=framework_data.get("revision", ""),
        display_name=framework_data["display_name"],
        project=project["title"],
        scope_modules=[m.get("title", "?") for m in modules],
        safety_class=safety_class,
        families=families,
        summary=summary,
        artifact_inventory=[{
            "id": a.get("id", "?"),
            "title": a.get("title") or "(untitled)",
            "module": a.get("_module", "?"),
            "artifact_type": a.get("artifact_type", "?"),
            "url": a.get("url", ""),
        } for a in artifacts],
    )

    return mapping


def _find_project(projects: List[Dict], identifier: str) -> Optional[Dict]:
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


def _artifact_haystack(art: Dict) -> str:
    """All searchable text from an artifact, joined."""
    custom = art.get("custom_attributes") or {}
    bits = [
        art.get("title", ""),
        art.get("artifact_type", ""),
        str(custom.get("Primary Text", "")),
        str(custom.get("PrimaryText", "")),
    ]
    # Also include any *_refs or compliance attr
    for k, v in custom.items():
        if "compliance" in k.lower() or "_refs" in k.lower():
            bits.append(str(v))
    return " ".join(filter(None, bits))


def _map_artifacts(
    artifacts: List[Dict],
    families: List[Dict],
    patterns: List[re.Pattern],
) -> None:
    """Walk every artifact; for each control ref found, attach the artifact
    to the matching control's mapped_artifacts list.
    """
    # Build control lookup
    by_id: Dict[str, Control] = {}
    for fam in families:
        for c in fam["controls"]:
            by_id[c.id.upper()] = c

    for art in artifacts:
        haystack = _artifact_haystack(art)
        found_refs: Set[str] = set()
        for pat in patterns:
            for m in pat.finditer(haystack):
                # The pattern's first capture group is the control id
                # (or sub-ref). Normalize.
                groups = [g for g in m.groups() if g]
                if not groups:
                    continue
                ref = groups[0].strip().upper()
                # IEC 62304 patterns may produce a class letter or a section
                # number. Normalize:
                if len(ref) == 1 and ref in "ABC":
                    continue  # safety class letter alone — handled elsewhere
                # NIST control IDs come with optional sub-control parens
                # e.g. AC-2(7). Strip parens for lookup.
                lookup = ref.split("(")[0]
                found_refs.add(lookup)

        for ref in found_refs:
            control = by_id.get(ref)
            if control:
                control.mapped_artifacts.append({
                    "id": art.get("id", "?"),
                    "title": art.get("title") or "(untitled)",
                    "module": art.get("_module", "?"),
                    "artifact_type": art.get("artifact_type", "?"),
                    "url": art.get("url", ""),
                    "matched_ref": ref,
                })


def _build_summary(
    families: List[Dict],
    artifacts: List[Dict],
    safety_class: Optional[str],
) -> Dict[str, Any]:
    total_controls = sum(len(f["controls"]) for f in families)
    mapped_controls = sum(
        1 for f in families for c in f["controls"]
        if not c.is_gap
    )
    gap_controls = sum(
        1 for f in families for c in f["controls"]
        if c.is_gap
    )
    p1_gaps = sum(
        1 for f in families for c in f["controls"]
        if c.is_gap and c.priority == "P1"
    )
    total_evidence_links = sum(
        len(c.mapped_artifacts) for f in families for c in f["controls"]
    )

    coverage_pct = (
        round(100 * mapped_controls / total_controls)
        if total_controls else 0
    )

    by_family: List[Dict[str, Any]] = []
    for fam in families:
        f_total = len(fam["controls"])
        f_mapped = sum(1 for c in fam["controls"] if not c.is_gap)
        by_family.append({
            "id": fam["id"],
            "name": fam["name"],
            "total": f_total,
            "mapped": f_mapped,
            "gap": f_total - f_mapped,
            "coverage_pct": round(100 * f_mapped / f_total) if f_total else 0,
        })

    status = "READY"
    if p1_gaps >= 5:
        status = "NEEDS_WORK"
    elif gap_controls >= 10:
        status = "NEEDS_WORK"
    elif gap_controls >= 3:
        status = "READY_WITH_OBSERVATIONS"

    return {
        "total_controls": total_controls,
        "mapped_controls": mapped_controls,
        "gap_controls": gap_controls,
        "p1_gaps": p1_gaps,
        "total_evidence_links": total_evidence_links,
        "coverage_pct": coverage_pct,
        "artifact_inventory_size": len(artifacts),
        "safety_class": safety_class,
        "by_family": by_family,
        "audit_readiness": status,
    }
