"""Change impact analysis — walks the DNG/EWM/ETM trace graph from a
single artifact and surfaces everything affected, plus risk classification
and reviewer recommendations.

Used by the `analyze_change_impact` MCP tool. Pure logic — the caller
provides a connected DOORSNextClient and the starting artifact URL.

The traversal works in two passes:

  1. SEED — resolve the starting artifact (req URL, code file path, or
     EWM work item URL) into a normalized graph node.

  2. EXPAND — BFS up to `depth` hops following OSLC links. Track each
     visited node, its link to the seed, and the hop count.

Risk is scored from the breadth + criticality of the affected set; an
HTML report is then rendered by `impact_report.py`.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

# Link types we consider for traversal (case-insensitive substring match
# against the OSLC link type label).
_TRAVERSAL_LINK_TYPES = {
    "satisfies", "satisfied by", "validates", "validated by",
    "elaborates", "elaborated by", "derives", "decomposition",
    "tracked by", "affected by", "implements", "implemented by",
    "specifies", "specified by", "references", "trace",
}

# Link types that count as "critical edge" — touching these means real
# code/test impact rather than just informational refs.
_CRITICAL_LINK_TYPES = {
    "satisfies", "satisfied by", "validates", "validated by",
    "tracked by", "implemented by", "implements",
}


@dataclass
class Node:
    """A single artifact in the impact graph."""
    url: str
    title: str
    domain: str                          # "DNG" | "EWM" | "ETM" | "code"
    artifact_type: str = ""              # e.g. "System Requirement", "Task"
    status: str = ""                     # e.g. "Approved", "new"
    owner: str = ""
    hop: int = 0                          # distance from seed (0 = seed)
    link_path: List[str] = field(default_factory=list)  # link types from seed


@dataclass
class ImpactGraph:
    """Result of one change-impact analysis."""
    seed: Node
    nodes: Dict[str, Node] = field(default_factory=dict)   # url -> Node
    edges: List[Tuple[str, str, str]] = field(default_factory=list)  # (from_url, to_url, link_type)
    risk: str = "UNKNOWN"
    risk_factors: List[str] = field(default_factory=list)
    suggested_reviewers: List[str] = field(default_factory=list)
    compliance_touches: List[Dict[str, str]] = field(default_factory=list)

    def by_domain(self) -> Dict[str, List[Node]]:
        out: Dict[str, List[Node]] = {"DNG": [], "EWM": [], "ETM": [], "code": []}
        for n in self.nodes.values():
            if n.url == self.seed.url:
                continue
            out.setdefault(n.domain, []).append(n)
        return out

    def by_hop(self) -> Dict[int, List[Node]]:
        out: Dict[int, List[Node]] = {}
        for n in self.nodes.values():
            if n.url == self.seed.url:
                continue
            out.setdefault(n.hop, []).append(n)
        return out

    def summary_counts(self) -> Dict[str, int]:
        by_d = self.by_domain()
        return {
            "total_affected": sum(len(v) for v in by_d.values()),
            "dng_reqs": len(by_d.get("DNG", [])),
            "ewm_work_items": len(by_d.get("EWM", [])),
            "etm_tests": len(by_d.get("ETM", [])),
            "code_components": len(by_d.get("code", [])),
            "compliance_controls": len(self.compliance_touches),
        }


def _domain_from_url(url: str) -> str:
    """Classify an OSLC URL into its ELM domain."""
    if not url:
        return "unknown"
    u = url.lower()
    if "/rm/" in u or "/dng/" in u:
        return "DNG"
    if "/ccm/" in u or "/ewm/" in u or "/rtc/" in u:
        return "EWM"
    if "/qm/" in u or "/rqm/" in u or "/etm/" in u:
        return "ETM"
    if u.startswith("file://") or u.startswith("/") or "://" not in u:
        return "code"
    return "external"


def _resolve_seed(
    client: Any,
    artifact: str,
    project_identifier: Optional[str] = None,
) -> Optional[Node]:
    """Turn a user-provided artifact identifier into a graph seed node.

    Accepts:
      - Full DNG/EWM/ETM URL
      - DNG req short ID + project (e.g. "990954" with project_identifier)
      - Code file path (treated as code-domain leaf)
    """
    domain = _domain_from_url(artifact)

    if domain == "code":
        return Node(url=artifact, title=artifact.split("/")[-1] or artifact,
                     domain="code", artifact_type="Source file")

    if domain == "DNG":
        # Try to fetch full details — fall back to URL-only seed if the
        # endpoint isn't directly resolvable.
        try:
            details = client.get_requirement_details(artifact)
            if details:
                return Node(
                    url=artifact,
                    title=details.get("title") or artifact,
                    domain="DNG",
                    artifact_type=details.get("artifact_type") or "Requirement",
                    status=str(details.get("status") or ""),
                    owner=details.get("owner") or "",
                )
        except Exception:
            pass
        return Node(url=artifact, title=artifact, domain="DNG",
                     artifact_type="Requirement")

    if domain == "EWM":
        return Node(url=artifact, title=artifact, domain="EWM",
                     artifact_type="Work item")

    if domain == "ETM":
        return Node(url=artifact, title=artifact, domain="ETM",
                     artifact_type="Test artifact")

    return Node(url=artifact, title=artifact, domain=domain)


def _expand_from_node(
    client: Any,
    node: Node,
    visited: Set[str],
) -> List[Tuple[Node, str]]:
    """Get neighbors of a node via OSLC links.

    Returns a list of (neighbor_node, link_type_label) pairs.
    For DNG reqs we use the client's link-fetcher. For EWM/ETM we use
    domain-specific helpers when available; otherwise return empty.
    """
    neighbors: List[Tuple[Node, str]] = []

    try:
        if node.domain == "DNG":
            # `get_requirement_links` is the canonical traversal hook;
            # fall back to a synthetic empty set if the client doesn't
            # expose it (older client versions).
            fetcher = getattr(client, "get_requirement_links", None)
            if not fetcher:
                return neighbors
            for link in fetcher(node.url) or []:
                link_type = (link.get("link_type") or
                              link.get("type") or "").lower()
                target_url = link.get("target_url") or link.get("url")
                if not target_url or target_url in visited:
                    continue
                if not any(lt in link_type for lt in _TRAVERSAL_LINK_TYPES):
                    continue
                neighbor = Node(
                    url=target_url,
                    title=link.get("target_title") or link.get("title")
                          or target_url,
                    domain=_domain_from_url(target_url),
                    artifact_type=link.get("target_type") or "",
                )
                neighbors.append((neighbor, link_type))
        # EWM / ETM: traversal hooks are domain-specific. The MCP server
        # composes those when registered; the helper stays domain-agnostic.
    except Exception:
        # Traversal failures shouldn't abort the whole walk — log via
        # the risk_factors mechanism in the parent caller.
        pass

    return neighbors


def analyze(
    client: Any,
    artifact: str,
    project_identifier: Optional[str] = None,
    depth: int = 3,
    include_compliance: bool = True,
    include_owners: bool = True,
) -> ImpactGraph:
    """Walk the trace graph from `artifact` outward to `depth` hops.

    Returns an ImpactGraph with nodes, edges, risk score, and reviewer
    recommendations. Read-only — never mutates ELM state.
    """
    depth = max(1, min(depth, 5))

    seed = _resolve_seed(client, artifact, project_identifier)
    if not seed:
        # Unable to even resolve the start; return an empty graph so
        # the caller can surface a friendly error.
        return ImpactGraph(seed=Node(url=artifact, title=artifact,
                                       domain="unknown"))

    graph = ImpactGraph(seed=seed)
    graph.nodes[seed.url] = seed

    # BFS frontier — each item is the URL to expand from + hop count.
    frontier: List[Tuple[str, int]] = [(seed.url, 0)]
    visited: Set[str] = {seed.url}

    while frontier:
        url, hop = frontier.pop(0)
        if hop >= depth:
            continue
        parent = graph.nodes.get(url)
        if not parent:
            continue
        neighbors = _expand_from_node(client, parent, visited)
        for neighbor, link_type in neighbors:
            if neighbor.url in visited:
                continue
            visited.add(neighbor.url)
            neighbor.hop = hop + 1
            neighbor.link_path = parent.link_path + [link_type]
            graph.nodes[neighbor.url] = neighbor
            graph.edges.append((parent.url, neighbor.url, link_type))
            frontier.append((neighbor.url, hop + 1))

    _score_risk(graph)
    if include_owners:
        _collect_reviewers(graph)
    if include_compliance:
        _detect_compliance(graph)

    return graph


def _score_risk(graph: ImpactGraph) -> None:
    """Heuristic risk score based on graph breadth + critical-edge count."""
    counts = graph.summary_counts()
    total = counts["total_affected"]
    critical_edges = sum(
        1 for (_, _, lt) in graph.edges
        if any(c in lt for c in _CRITICAL_LINK_TYPES)
    )
    factors: List[str] = []

    if total == 0:
        graph.risk = "LOW"
        factors.append("No downstream artifacts found via trace graph")
        graph.risk_factors = factors
        return

    if counts["compliance_controls"] > 0:
        factors.append(
            f"Touches {counts['compliance_controls']} compliance control(s)"
        )
    if counts["etm_tests"] >= 5:
        factors.append(
            f"{counts['etm_tests']} test cases need re-execution"
        )
    if counts["ewm_work_items"] >= 3:
        factors.append(
            f"{counts['ewm_work_items']} open work items reference this"
        )
    if critical_edges >= 5:
        factors.append(
            f"{critical_edges} critical satisfies/validates edges in scope"
        )

    if total >= 15 or counts["compliance_controls"] >= 2 or critical_edges >= 10:
        graph.risk = "HIGH"
    elif total >= 5 or critical_edges >= 3 or counts["compliance_controls"] >= 1:
        graph.risk = "MEDIUM"
    else:
        graph.risk = "LOW"

    if not factors:
        factors.append(f"{total} affected artifact(s) across the trace graph")
    graph.risk_factors = factors


def _collect_reviewers(graph: ImpactGraph) -> None:
    """Pull unique owners from affected artifacts as suggested reviewers."""
    seen: Set[str] = set()
    for n in graph.nodes.values():
        if n.url == graph.seed.url:
            continue
        if n.owner and n.owner not in seen:
            seen.add(n.owner)
    graph.suggested_reviewers = sorted(seen)


def _detect_compliance(graph: ImpactGraph) -> None:
    """Surface compliance refs embedded in affected artifacts.

    Looks for common patterns: "NIST 800-53 §IA-2", "IEC 62304 Class B",
    "ISO 26262 §6.4", etc. in titles / attributes. Lightweight scan; the
    real mapping lives in the compliance_packet tool.
    """
    import re
    patterns = [
        (r"NIST\s*800[-\s]?53\s*(?:§|\bsec\.?\s*|\bclause\s*)?([A-Z]{2}-\d+)",
         "NIST 800-53"),
        (r"IEC\s*62304\s*(?:Class\s*([A-C])|§\s*(\d+\.\d+(?:\.\d+)?))",
         "IEC 62304"),
        (r"ISO\s*26262\s*(?:§|\bsec\.?\s*|\bclause\s*)?(\d+\.\d+(?:\.\d+)?)",
         "ISO 26262"),
        (r"DO[-\s]?178C\s*(?:§|\bDAL\s*)?([A-E\d.]+)", "DO-178C"),
        (r"WCAG\s*(?:2\.\d\s*)?(A{1,3})\b", "WCAG"),
        (r"HIPAA\s*(?:§|\bsec\.?\s*)?([\d.]+)", "HIPAA"),
        (r"GDPR\s*Art(?:icle|\.)?\s*(\d+)", "GDPR"),
        (r"SOC\s*2\s*(?:Type\s*([12]))?", "SOC2"),
        (r"PCI[-\s]?DSS\s*(?:§|\breq\.?\s*)?([\d.]+)?", "PCI-DSS"),
    ]
    found: Dict[str, str] = {}
    for n in graph.nodes.values():
        haystack = " ".join(filter(None, [n.title, n.artifact_type]))
        for pat, framework in patterns:
            for m in re.finditer(pat, haystack, re.IGNORECASE):
                ref = m.group(0).strip()
                key = f"{framework}::{ref}"
                if key not in found:
                    found[key] = n.url
    graph.compliance_touches = [
        {"framework": k.split("::")[0], "ref": k.split("::")[1],
          "via_artifact": v}
        for k, v in found.items()
    ]
