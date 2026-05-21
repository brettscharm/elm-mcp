"""
Requirements Quality Module for elm-mcp
Pattern-based, deterministic lint of requirement text against
INCOSE Guide to Writing Requirements (GtWR) and IEEE 29148 patterns.

This module does ONLY deterministic checks (regex, word lists,
structural patterns). For AI-powered semantic scoring, ambiguity
detection, and rewrite suggestions, elm-mcp recommends the
Requirements Quality Assistant agent in IBM ELM AI Hub.

Public surface:
  lint_text(text)              -> list[Finding]   (per-rule issues)
  score_text(text)             -> int 0-100       (aggregate quality)
  format_findings(findings)    -> str             (markdown report)
  lint_and_score(text)         -> {findings, score, summary}
  batch_lint(items)            -> list[per-item result]
  audit_summary(per_req_data)  -> str             (module-wide summary)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Tuple


# ── References ─────────────────────────────────────────────────
# GtWR = INCOSE Guide to Writing Requirements (4th ed., 2023)
# IEEE 29148 = ISO/IEC/IEEE 29148:2018 "Systems and software
#              engineering — Life cycle processes — Requirements
#              engineering"
# Each Finding cites the most relevant rule so users learn the
# framework as they fix issues.


@dataclass
class Finding:
    severity: str            # "high" | "medium" | "low"
    category: str            # short tag, e.g. "weasel", "weak_modal"
    rule: str                # e.g. "GtWR R7" or "IEEE 29148 §5.2.5"
    message: str             # plain-English explanation
    span: str = ""           # the offending substring
    suggestion: str = ""     # short fix hint

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Pattern Libraries ──────────────────────────────────────────
#
# Word lists are matched as case-insensitive whole words or phrases.
# Each list maps phrase -> (category, severity, rule, message,
# suggestion). Keeping the data structure consistent so the runner
# stays small.

# Severity scoring weights for the aggregate 0-100 score:
_W_HIGH = 15
_W_MED = 5
_W_LOW = 1


_WEASEL_WORDS: Dict[str, Tuple[str, str, str]] = {
    # phrase: (rule, message, suggestion)
    "appropriate": ("GtWR R6 (Avoid Ambiguity)",
        "'appropriate' is subjective — what counts as appropriate?",
        "Replace with a specific, measurable criterion."),
    "appropriately": ("GtWR R6 (Avoid Ambiguity)",
        "'appropriately' is subjective.",
        "State the exact behavior or threshold."),
    "as needed": ("GtWR R6", "'as needed' has no defined trigger.",
        "State the precise condition that triggers the behavior."),
    "as appropriate": ("GtWR R6", "'as appropriate' is ambiguous.",
        "Specify the exact conditions."),
    "as required": ("GtWR R6", "'as required' is circular.",
        "Specify the criteria explicitly."),
    "where possible": ("GtWR R6", "'where possible' is conditional with no defined scope.",
        "State the conditions where it applies."),
    "if applicable": ("GtWR R6", "'if applicable' begs the question.",
        "State the applicability criteria."),
    "to the extent possible": ("GtWR R6", "Aspirational, not testable.",
        "Replace with a concrete threshold."),
    "user-friendly": ("GtWR R6", "'user-friendly' is subjective.",
        "Replace with a measurable usability target (e.g., 'completable in N steps' or 'WCAG 2.1 AA conformant')."),
    "user friendly": ("GtWR R6", "'user friendly' is subjective.",
        "Replace with a measurable usability target."),
    "robust": ("GtWR R6", "'robust' is subjective.",
        "State the specific failure modes and recovery behaviors."),
    "reasonable": ("GtWR R6", "'reasonable' is subjective.",
        "Specify the numeric threshold."),
    "reasonably": ("GtWR R6", "'reasonably' is subjective.",
        "Specify the numeric threshold."),
    "fast": ("GtWR R6", "'fast' is subjective.",
        "Specify the response time with units (e.g., '≤ 200 ms p95')."),
    "easy": ("GtWR R6", "'easy' is subjective.",
        "Specify a measurable usability or learnability criterion."),
    "intuitive": ("GtWR R6", "'intuitive' is subjective.",
        "Specify a measurable usability criterion or task-completion target."),
    "simple": ("GtWR R6", "'simple' is subjective.",
        "State the specific simplification criterion."),
    "seamless": ("GtWR R6", "'seamless' is a buzzword.",
        "State the exact interoperability or handoff behavior."),
    "smooth": ("GtWR R6", "'smooth' is subjective.",
        "Specify the exact behavior or frame-rate target."),
    "modern": ("GtWR R6", "'modern' is subjective and time-bound.",
        "Cite the specific standard or version."),
    "elegant": ("GtWR R6", "'elegant' is subjective.",
        "Remove or replace with a concrete property."),
    "flexible": ("GtWR R6", "'flexible' is subjective.",
        "State the specific configurability or extensibility points."),
    "transparent": ("GtWR R6", "'transparent' (unless meaning visible) is vague.",
        "State the specific observable behavior or logging requirement."),
    "high quality": ("GtWR R6", "'high quality' is subjective.",
        "Cite the specific quality attribute (e.g., reliability MTBF, defect density)."),
    "good performance": ("GtWR R6", "'good performance' is subjective.",
        "Specify the performance metric and threshold."),
    "minimal": ("GtWR R6", "'minimal' is subjective.",
        "Specify the maximum value with units."),
    "minimal impact": ("GtWR R6", "'minimal impact' is subjective.",
        "Specify what the bounded impact is (e.g., '<5% CPU')."),
    "etc.": ("GtWR R7 (Avoid 'etc.')",
        "'etc.' makes the requirement unbounded.",
        "Enumerate all cases explicitly."),
    "and so on": ("GtWR R7", "'and so on' is open-ended.",
        "Enumerate every case."),
    "and/or": ("GtWR R7 (Avoid 'and/or')",
        "'and/or' is logically ambiguous.",
        "Choose either AND or OR and split into multiple requirements if needed."),
}


_WEAK_MODALS: Dict[str, Tuple[str, str, str]] = {
    "should": ("IEEE 29148 §5.2.5",
        "'should' is a recommendation, not a requirement.",
        "Use 'shall' (or 'must' / 'will' per your project's verb policy) for binding requirements; otherwise remove."),
    "may": ("IEEE 29148 §5.2.5",
        "'may' is permissive, not a requirement.",
        "Promote to 'shall' if mandatory, or move to a Notes section."),
    "could": ("IEEE 29148 §5.2.5",
        "'could' is hypothetical.",
        "Use 'shall' for actual requirements; remove otherwise."),
    "might": ("IEEE 29148 §5.2.5",
        "'might' is speculative.",
        "Use 'shall' for actual requirements; remove otherwise."),
    "preferably": ("GtWR R5",
        "'preferably' suggests a preference, not a requirement.",
        "If mandatory, use 'shall'. If preference only, move to design rationale."),
    "ideally": ("GtWR R5",
        "'ideally' is aspirational.",
        "State the mandatory behavior with 'shall', or remove."),
    "tends to": ("GtWR R5",
        "'tends to' is non-binding.",
        "State the exact behavior."),
    "is intended to": ("GtWR R5",
        "'is intended to' is aspirational, not testable.",
        "State what the system shall do."),
    "is supposed to": ("GtWR R5",
        "'is supposed to' is informal and non-binding.",
        "Use 'shall'."),
}


_IMPL_LEAK: Dict[str, Tuple[str, str, str]] = {
    "via REST": ("GtWR R4 (No design)",
        "Mentioning REST is an implementation choice in a requirement.",
        "Describe WHAT, not HOW — e.g. 'the system shall expose <function> via a documented API.'"),
    "the database": ("GtWR R4",
        "'the database' presupposes a storage technology.",
        "Replace with 'persistent storage' or describe the data lifecycle requirement."),
    "via Kafka": ("GtWR R4",
        "Kafka is an implementation choice.",
        "Describe the messaging requirement abstractly."),
    "using Java": ("GtWR R4",
        "Programming language is design.",
        "Remove language reference unless it's a contractual constraint."),
    "using Python": ("GtWR R4",
        "Programming language is design.",
        "Remove unless contractual."),
    "in JavaScript": ("GtWR R4",
        "Programming language is design.",
        "Remove unless contractual."),
    "via HTTP": ("GtWR R4",
        "Protocol is design.",
        "Describe the integration requirement abstractly."),
    "via GraphQL": ("GtWR R4",
        "GraphQL is an implementation choice.",
        "Describe the API requirement abstractly."),
    "running on Docker": ("GtWR R4",
        "Docker is an implementation choice.",
        "State the operational requirement abstractly."),
    "via Kubernetes": ("GtWR R4",
        "Kubernetes is an implementation choice.",
        "State the operational requirement abstractly."),
    "in the cloud": ("GtWR R4",
        "Deployment topology is design.",
        "State the operational property (availability, scaling) instead."),
    "via lambda": ("GtWR R4",
        "Lambda is an implementation choice.",
        "Describe the function-as-a-service requirement abstractly."),
}


_ABSOLUTES: Dict[str, Tuple[str, str, str]] = {
    "always": ("GtWR R5 (Testable)",
        "'always' is an unbounded universal claim.",
        "Specify the operational conditions under which the behavior applies."),
    "never": ("GtWR R5",
        "'never' is hard to verify exhaustively.",
        "State the prohibited behavior with measurable detection."),
    "all users": ("GtWR R5",
        "'all users' may be too broad to test.",
        "Define the user population precisely."),
    "every request": ("GtWR R5",
        "'every request' may be too broad to test.",
        "Define the request population precisely."),
    "100%": ("GtWR R5",
        "100% is rarely achievable; verify the bound is realistic.",
        "Specify the achievable threshold (e.g., 99.9%) with operating conditions."),
    "completely": ("GtWR R5",
        "'completely' is absolute and hard to verify.",
        "Specify the measurable bound."),
    "fully": ("GtWR R5",
        "'fully' is absolute and hard to verify.",
        "Specify the measurable scope."),
    "totally": ("GtWR R5",
        "'totally' is absolute and informal.",
        "Specify the measurable scope."),
}


_FUTURE_TENSE: Dict[str, Tuple[str, str, str]] = {
    "will eventually": ("GtWR R4 (Necessary)",
        "'will eventually' is a plan, not a requirement.",
        "Remove from the requirement, or schedule the work explicitly."),
    "in the future": ("GtWR R4",
        "'in the future' is unscheduled aspiration.",
        "Remove or schedule explicitly."),
    "down the road": ("GtWR R4",
        "Informal future planning, not a requirement.",
        "Remove."),
    "at some point": ("GtWR R4",
        "Vague timeline.",
        "Remove or specify the schedule."),
    "long-term": ("GtWR R4",
        "Vague timeline.",
        "Replace with a specific milestone."),
}


# Compound-shall (multiple actions joined by 'and') — heuristic pattern.
_COMPOUND_SHALL = re.compile(
    r"\b(shall|must|will)\b[^.]+\b(?:and|or)\b[^.]+\b(?:and|or)\b",
    re.IGNORECASE,
)

# Single shall + "and" + verb-shaped continuation (lighter compound)
_AND_VERB = re.compile(
    r"\b(shall|must|will)\b[^.]+\band\b\s+(?:also\s+)?(provide|send|store|"
    r"validate|process|generate|create|delete|update|notify|log|encrypt|"
    r"display|render|accept|reject|expose|publish|subscribe|index|cache|"
    r"queue|retry|return|emit|raise|trigger|invoke|execute|run|start|stop|"
    r"pause|resume|enable|disable|allow|deny|persist|load|save|sync)",
    re.IGNORECASE,
)

# Numeric value without units (very rough — catches the obvious cases)
_NUM_NO_UNIT = re.compile(
    r"\b(within|under|over|at\s+most|at\s+least|≤|≥|<=|>=|<|>)\s+\d+(?:\.\d+)?\b"
    r"(?!\s*(?:ms|millisec|s|sec|second|min|hour|day|week|month|year|"
    r"%|percent|mb|gb|tb|kb|byte|request|qps|rps|user|item|row|record|"
    r"px|em|character|word|kg|m|cm|mm|km|°|degree))",
    re.IGNORECASE,
)

# Numeric thresholds WITH units — positive signal (boosts score floor)
_NUM_WITH_UNIT = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:ms|millisec|sec(?:ond)?s?|min(?:ute)?s?|hours?|"
    r"days?|weeks?|months?|years?|%|percent|MB|GB|TB|KB|bytes?|"
    r"requests?/s|qps|rps|users?|items?|rows?|records?)\b",
    re.IGNORECASE,
)

# Explicit verification language — positive signal
_VERIFICATION = re.compile(
    r"\b(verified\s+by|validated\s+by|tested\s+by|inspected\s+by|"
    r"demonstrated\s+by|analyzed\s+by|measured\s+by)\b",
    re.IGNORECASE,
)

# Has a strong modal ('shall'/'must'/'will') — required for a true req
_STRONG_MODAL = re.compile(r"\b(shall|must|will)\b", re.IGNORECASE)


def _scan_dict(text: str, lookups: Dict[str, Tuple[str, str, str]],
               severity: str, category: str) -> List[Finding]:
    out: List[Finding] = []
    low = text.lower()
    for phrase, (rule, msg, sugg) in lookups.items():
        # whole-phrase match (word-boundary on each side when possible)
        if any(ch.isalnum() for ch in phrase):
            pattern = r"(?<![A-Za-z])" + re.escape(phrase.lower()) + r"(?![A-Za-z])"
        else:
            pattern = re.escape(phrase.lower())
        if re.search(pattern, low):
            out.append(Finding(
                severity=severity, category=category, rule=rule,
                message=msg, span=phrase, suggestion=sugg,
            ))
    return out


def lint_text(text: str) -> List[Finding]:
    """Run every deterministic check against a single requirement text.
    Returns a list of Finding records, possibly empty.
    """
    if not text or not text.strip():
        return [Finding(
            severity="high", category="empty",
            rule="GtWR R4 (Necessary)",
            message="Requirement text is empty.",
            suggestion="Write the requirement.",
        )]

    findings: List[Finding] = []

    # Strong modal check — every binding requirement needs one.
    if not _STRONG_MODAL.search(text):
        findings.append(Finding(
            severity="high", category="no_modal",
            rule="IEEE 29148 §5.2.5",
            message="Requirement lacks a strong modal ('shall', 'must', or 'will'). "
                    "Without one, it's a statement of fact or aspiration, not a binding requirement.",
            suggestion="Rewrite using 'shall' (or your project's mandated modal verb).",
        ))

    # Weasel words (high severity)
    findings.extend(_scan_dict(text, _WEASEL_WORDS, "high", "weasel"))

    # Weak modals (medium)
    findings.extend(_scan_dict(text, _WEAK_MODALS, "medium", "weak_modal"))

    # Implementation leakage (medium)
    findings.extend(_scan_dict(text, _IMPL_LEAK, "medium", "impl_leak"))

    # Untestable absolutes (medium)
    findings.extend(_scan_dict(text, _ABSOLUTES, "medium", "absolute"))

    # Future-tense aspirations (medium)
    findings.extend(_scan_dict(text, _FUTURE_TENSE, "medium", "future"))

    # Compound shall (high)
    if _COMPOUND_SHALL.search(text):
        findings.append(Finding(
            severity="high", category="compound",
            rule="GtWR R3 (Singular)",
            message="Multiple obligations joined by 'and'/'or' in one requirement. "
                    "Compound requirements are harder to verify, trace, and update.",
            suggestion="Split into one requirement per atomic obligation.",
        ))
    elif _AND_VERB.search(text):
        # Lighter compound — verb-after-'and' heuristic
        findings.append(Finding(
            severity="medium", category="compound_light",
            rule="GtWR R3 (Singular)",
            message="Looks like multiple actions in one requirement.",
            suggestion="Consider splitting into atomic requirements.",
        ))

    # Numbers without units (high)
    m = _NUM_NO_UNIT.search(text)
    if m:
        findings.append(Finding(
            severity="high", category="num_no_unit",
            rule="GtWR R23 (Use Units)",
            message=f"Numeric threshold '{m.group(0)}' has no unit.",
            span=m.group(0),
            suggestion="Add the unit (ms, %, MB, requests/s, etc.).",
        ))

    # Length sanity (low)
    word_count = len(text.split())
    if word_count > 50:
        findings.append(Finding(
            severity="low", category="too_long",
            rule="GtWR R3 (Singular)",
            message=f"Requirement is {word_count} words long. "
                    f"Long requirements tend to compound multiple obligations.",
            suggestion="Aim for ≤ 30 words. Split if necessary.",
        ))

    return findings


def positive_signals(text: str) -> Dict[str, bool]:
    """Return a dict of positive quality signals present in the text.
    Not used to penalize — used to surface what's GOOD about the req,
    and to bump the floor of an otherwise mediocre score.
    """
    return {
        "has_numeric_threshold": bool(_NUM_WITH_UNIT.search(text)),
        "has_verification_clause": bool(_VERIFICATION.search(text)),
        "has_strong_modal": bool(_STRONG_MODAL.search(text)),
    }


def score_text(text: str) -> int:
    """Compute a 0-100 quality score from the findings + positive signals.
    100 = no detected issues; 0 = many high-severity issues.
    """
    findings = lint_text(text)
    deductions = 0
    for f in findings:
        if f.severity == "high":
            deductions += _W_HIGH
        elif f.severity == "medium":
            deductions += _W_MED
        else:
            deductions += _W_LOW
    score = 100 - deductions

    # Positive signals: small boost for verified-by clauses (max +5)
    signals = positive_signals(text)
    if signals["has_verification_clause"]:
        score += 5
    if signals["has_numeric_threshold"]:
        score += 3

    return max(0, min(100, score))


def severity_bucket(score: int) -> str:
    """Label a score in plain English."""
    if score >= 85:
        return "good"
    if score >= 65:
        return "fair"
    if score >= 40:
        return "weak"
    return "poor"


def lint_and_score(text: str) -> Dict[str, Any]:
    findings = lint_text(text)
    score = score_text(text)
    return {
        "score": score,
        "bucket": severity_bucket(score),
        "findings": [f.to_dict() for f in findings],
        "signals": positive_signals(text),
    }


# ── Formatting ─────────────────────────────────────────────────

def format_findings(findings: List[Finding], *, indent: str = "") -> str:
    """Format a single requirement's findings as a markdown bullet list."""
    if not findings:
        return f"{indent}- ✅ No issues detected.\n"
    by_sev = {"high": [], "medium": [], "low": []}
    for f in findings:
        by_sev.setdefault(f.severity, []).append(f)

    icons = {"high": "🔴", "medium": "🟡", "low": "🔵"}
    lines = []
    for sev in ("high", "medium", "low"):
        for f in by_sev.get(sev, []):
            line = f"{indent}- {icons[sev]} **{f.rule}** — {f.message}"
            if f.span:
                line += f"  _(found: `{f.span}`)_"
            if f.suggestion:
                line += f"\n{indent}  → {f.suggestion}"
            lines.append(line)
    return "\n".join(lines) + "\n"


# ── Batch / Module-Level ───────────────────────────────────────

def batch_lint(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Lint a batch of requirements. Each input item should have at
    least {'title': str, 'text': str}; optional 'url' is passed through.
    Returns a list of {title, url, score, bucket, findings, signals}.
    """
    out = []
    for it in items:
        text = it.get("text") or it.get("content") or ""
        res = lint_and_score(text)
        out.append({
            "title": it.get("title", ""),
            "url": it.get("url", ""),
            **res,
        })
    return out


def audit_summary(batch_results: List[Dict[str, Any]]) -> str:
    """Produce a module-level markdown summary from batch_lint output.
    Designed to be the body of the audit_module tool response.
    """
    if not batch_results:
        return "_(no requirements to audit)_\n"

    n = len(batch_results)
    scores = [r["score"] for r in batch_results]
    avg = sum(scores) / n if n else 0

    buckets = {"good": 0, "fair": 0, "weak": 0, "poor": 0}
    for r in batch_results:
        buckets[r["bucket"]] = buckets.get(r["bucket"], 0) + 1

    high_count = sum(
        1 for r in batch_results
        for f in r["findings"] if f["severity"] == "high"
    )
    med_count = sum(
        1 for r in batch_results
        for f in r["findings"] if f["severity"] == "medium"
    )

    lines = [
        "## Module Quality Summary",
        "",
        f"- **Requirements scored:** {n}",
        f"- **Average score:** {avg:.0f}/100",
        f"- **Distribution:** {buckets['good']} good · "
        f"{buckets['fair']} fair · {buckets['weak']} weak · "
        f"{buckets['poor']} poor",
        f"- **Total findings:** "
        f"🔴 {high_count} high · 🟡 {med_count} medium",
        "",
    ]

    # Flag the worst offenders
    worst = sorted(batch_results, key=lambda r: r["score"])[:5]
    if worst and worst[0]["score"] < 85:
        lines.append("### Lowest-scoring requirements (top 5)")
        lines.append("")
        for r in worst:
            t = (r.get("title") or "(no title)")[:80]
            url = r.get("url", "")
            lines.append(f"- **{r['score']}/100** "
                         f"[{t}]({url}) — {r['bucket']}")
        lines.append("")

    # Surface the most common rule violations
    rule_counts: Dict[str, int] = {}
    for r in batch_results:
        for f in r["findings"]:
            rule_counts[f["rule"]] = rule_counts.get(f["rule"], 0) + 1
    if rule_counts:
        lines.append("### Most-violated rules")
        lines.append("")
        for rule, c in sorted(rule_counts.items(),
                              key=lambda kv: -kv[1])[:5]:
            lines.append(f"- **{rule}** — {c} occurrences")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("**For AI-powered semantic scoring, rewrite suggestions, "
                 "and ambiguity detection beyond what pattern matching can "
                 "find**, open these requirements in the **Requirements "
                 "Quality Assistant** agent in IBM ELM AI Hub. The "
                 "deterministic findings above catch syntactic smells; "
                 "Requirements Quality Assistant catches semantic ones "
                 "(intent vs. wording, completeness, consistency across "
                 "the set).")
    lines.append("")
    return "\n".join(lines)
