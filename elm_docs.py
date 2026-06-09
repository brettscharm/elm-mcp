"""Curated IBM ELM documentation URL lookup.

Used by the `get_elm_docs_links` MCP tool. Returns known-good URLs for
common ELM topics so Bob doesn't have to guess from stale training data.

The problem this solves: when a user asks "where are the ELM 7.1 upgrade
docs?", an LLM agent (Bob, Claude, Cursor) typically generates a URL
from training-data knowledge — which goes stale fast because IBM
reorganizes its docs site frequently. This tool returns a curated set
of stable URLs, optionally HEAD-checks them to verify they're still
live, and tells the user when something has rotted.

Schema for entries:
  topic      — short slug ("upgrade", "install", "whatsnew", ...)
  display    — human-readable name
  url        — current known-good URL
  version    — ELM major.minor.patch (or "*" for evergreen)
  product    — "ELM", "DOORS Next", "EWM", "ETM", "GCM", "Bob", "Classic"
  notes      — anything the user should know about following the link
  is_search  — if true, the URL is a search landing page rather than a
                deep link (useful when deep links rot)

Adding new links: just append to _LINKS below. No code changes needed.
"""
from __future__ import annotations
from typing import Dict, List, Optional


# Curated docs links. Seeded from the working URLs verified live in the
# v0.22.0 audit (June 2026). The "elm/7.1.0" path everyone gives is
# DEAD — the actual live pattern is:
#   https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/
#     lifecycle-management/{version}
# Topic-specific deep links (?topic=...) currently redirect to the
# version root — IBM uses JS-driven nav for deep links, so the link
# still gets the user to the TOC for that version. That's good enough.
_LINKS: List[Dict[str, str]] = [

    # ── ELM 7.1 — current release ──────────────────────────────────
    {
        "topic": "elm-home",
        "display": "IBM ELM 7.1 — Knowledge Center (main hub)",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0",
        "version": "7.1",
        "product": "ELM",
        "notes": "Start here for any ELM 7.1 documentation. The /docs/en/elm/7.1.0 URL most people share is dead — this is the live one.",
    },
    {
        "topic": "elm-home-703",
        "display": "IBM ELM 7.0.3 — Knowledge Center (previous release)",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.0.3",
        "version": "7.0.3",
        "product": "ELM",
        "notes": "Use if your deployment is on 7.0.3.",
    },
    {
        "topic": "upgrade-planning",
        "display": "ELM 7.1 — Planning Your Upgrade",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=upgrading-planning-your-upgrade",
        "version": "7.1",
        "product": "ELM",
        "notes": "Lands at the 7.1 TOC; navigate to Upgrading > Planning. IBM's deep links redirect to TOC.",
    },
    {
        "topic": "upgrade-roadmap",
        "display": "ELM 7.1 — Upgrade Roadmap",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=upgrading-upgrade-roadmap",
        "version": "7.1",
        "product": "ELM",
        "notes": "Step-by-step upgrade procedure from supported source versions.",
    },
    {
        "topic": "upgrade-interactive",
        "display": "ELM Interactive Upgrade Guide — search starting point",
        "url": "https://www.ibm.com/support/pages/search?q=interactive+upgrade+guide+ELM",
        "version": "*",
        "product": "ELM",
        "notes": "IBM moves the Interactive Upgrade Guide URL every few releases. This search lands you on the latest version. Look for the most recent 'Interactive Upgrade Guide for IBM ELM' result.",
        "is_search": "true",
    },
    {
        "topic": "system-requirements",
        "display": "ELM 7.1 — System Requirements",
        "url": "https://www.ibm.com/support/pages/node/6593147",
        "version": "7.1",
        "product": "ELM",
        "notes": "Hardware, OS, browser, and database compatibility matrix.",
    },
    {
        "topic": "whatsnew",
        "display": "What's New in ELM 7.1",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=overview-whats-new-in-version-710",
        "version": "7.1",
        "product": "ELM",
        "notes": "Release notes + new features.",
    },

    # ── DOORS Next (Requirements Management) ───────────────────────
    {
        "topic": "doors-next-home",
        "display": "DOORS Next 7.1 — Knowledge Center",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=requirements-management",
        "version": "7.1",
        "product": "DOORS Next",
        "notes": "Full DNG product docs (lands at 7.1 TOC).",
    },
    {
        "topic": "doors-next-oslc",
        "display": "DOORS Next OSLC API reference",
        "url": "https://jazz.net/wiki/bin/view/Main/OSLCRMV2",
        "version": "*",
        "product": "DOORS Next",
        "notes": "OSLC RM v2.0 spec — used by elm-mcp under the hood.",
    },
    {
        "topic": "reportable-rest",
        "display": "DOORS Next Reportable REST API",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=apis-reportable-rest-api",
        "version": "7.1",
        "product": "DOORS Next",
        "notes": "Used by elm-mcp for fast module + req fetching.",
    },

    # ── EWM (Workflow Management) ──────────────────────────────────
    {
        "topic": "ewm-home",
        "display": "EWM 7.1 — Knowledge Center",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=workflow-management",
        "version": "7.1",
        "product": "EWM",
        "notes": "Full EWM product docs.",
    },
    {
        "topic": "ewm-oslc",
        "display": "EWM OSLC Change Management API reference",
        "url": "https://jazz.net/wiki/bin/view/Main/OSLCChangeManagementV2",
        "version": "*",
        "product": "EWM",
        "notes": "OSLC CM v2.0 spec.",
    },

    # ── ETM (Test Management) ──────────────────────────────────────
    {
        "topic": "etm-home",
        "display": "ETM 7.1 — Knowledge Center",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=test-management",
        "version": "7.1",
        "product": "ETM",
        "notes": "Full ETM (Rational Quality Manager successor) docs.",
    },
    {
        "topic": "etm-oslc",
        "display": "ETM OSLC Quality Management API reference",
        "url": "https://jazz.net/wiki/bin/view/Main/OSLCQualityManagementV2",
        "version": "*",
        "product": "ETM",
        "notes": "OSLC QM v2.0 spec.",
    },

    # ── GCM (Global Configuration) ─────────────────────────────────
    {
        "topic": "gcm-home",
        "display": "GCM 7.1 — Knowledge Center",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=configuration-management",
        "version": "7.1",
        "product": "GCM",
        "notes": "Global Configuration Management — streams, baselines, components.",
    },

    # ── Classic DOORS (DOORS 9.x) ──────────────────────────────────
    {
        "topic": "classic-doors-home",
        "display": "Classic DOORS 9.7 — Knowledge Center",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/doors/9.7.0",
        "version": "9.7",
        "product": "Classic",
        "notes": "DOORS 9.x — the older thick-client / DWA stack.",
    },
    {
        "topic": "dxl",
        "display": "DXL (DOORS eXtension Language) reference",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/doors/9.7.0?topic=dxl-reference-manual",
        "version": "9.7",
        "product": "Classic",
        "notes": "DXL scripting reference for DOORS 9.",
    },
    {
        "topic": "classic-to-dng-migration",
        "display": "DOORS Classic → DOORS Next migration utility",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=migration-doors-doors-next",
        "version": "7.1",
        "product": "Classic",
        "notes": "Official path for moving Classic content to DNG.",
    },

    # ── AI Hub / Requirements Quality Assistant ────────────────────
    {
        "topic": "ai-hub",
        "display": "IBM ELM AI Hub",
        "url": "https://www.ibm.com/products/engineering-lifecycle-management-ai-hub",
        "version": "*",
        "product": "ELM",
        "notes": "Hosts the Requirements Quality Assistant agent — semantic scoring beyond deterministic lint.",
    },

    # ── Bob (IBM's AI assistant) ────────────────────────────────────
    {
        "topic": "bob-docs-home",
        "display": "IBM Bob — Documentation",
        "url": "https://bob.ibm.com/docs/",
        "version": "*",
        "product": "Bob",
        "notes": "Main Bob docs site.",
    },
    {
        "topic": "bob-modes",
        "display": "IBM Bob — Custom Modes configuration",
        "url": "https://bob.ibm.com/docs/ide/configuration/custom-modes",
        "version": "*",
        "product": "Bob",
        "notes": "Schema for custom_modes.yaml — used by elm-mcp's mode files.",
    },
    {
        "topic": "bob-mcp",
        "display": "IBM Bob — MCP server integration",
        "url": "https://bob.ibm.com/docs/ide/configuration/mcp/understanding-mcp",
        "version": "*",
        "product": "Bob",
        "notes": "How Bob uses MCP servers like elm-mcp.",
    },

    # ── Support + community (fallbacks when deep links rot) ────────
    {
        "topic": "support-portal",
        "display": "IBM Support Portal (search landing)",
        "url": "https://www.ibm.com/support/pages/",
        "version": "*",
        "product": "ELM",
        "notes": "Search 'ELM 7.1 [topic]' here if a deep link is dead.",
        "is_search": "true",
    },
    {
        "topic": "docs-search",
        "display": "IBM Documentation search landing",
        "url": "https://www.ibm.com/docs/",
        "version": "*",
        "product": "ELM",
        "notes": "Search 'Engineering Lifecycle Management 7.1 [topic]' here if a deep link rots.",
        "is_search": "true",
    },
    {
        "topic": "passport-advantage",
        "display": "IBM Passport Advantage (download installation media)",
        "url": "https://www.ibm.com/software/passportadvantage/",
        "version": "*",
        "product": "ELM",
        "notes": "Where install packages + entitled downloads live.",
    },
    {
        "topic": "community",
        "display": "IBM ELM Community Forums",
        "url": "https://community.ibm.com/community/user/wasdevops/communities/community-home?CommunityKey=5d0e8c6a-ced7-4f6e-9242-b1e8e3c8e0e4",
        "version": "*",
        "product": "ELM",
        "notes": "Active community with real-world upgrade experiences and Q&A.",
    },

    # ── elm-mcp itself ─────────────────────────────────────────────
    {
        "topic": "elm-mcp",
        "display": "elm-mcp GitHub repository",
        "url": "https://github.com/brettscharm/elm-mcp",
        "version": "*",
        "product": "ELM",
        "notes": "This MCP server's source code, issues, and releases.",
    },
]


# Topic synonyms — when the user asks for "patch notes" we match
# "whatsnew", etc.
_SYNONYMS: Dict[str, str] = {
    "release-notes": "whatsnew",
    "patch-notes": "whatsnew",
    "changelog": "whatsnew",
    "new-features": "whatsnew",
    "install": "system-requirements",
    "installation": "system-requirements",
    "requirements": "system-requirements",
    "hardware": "system-requirements",
    "upgrading": "upgrade-roadmap",
    "upgrade-path": "upgrade-roadmap",
    "version-compatibility": "upgrade-planning",
    "doors-next": "doors-next-home",
    "dng": "doors-next-home",
    "rm": "doors-next-home",
    "ewm": "ewm-home",
    "rtc": "ewm-home",
    "ccm": "ewm-home",
    "etm": "etm-home",
    "rqm": "etm-home",
    "qm": "etm-home",
    "gcm": "gcm-home",
    "oslc": "doors-next-oslc",
    "doors9": "classic-doors-home",
    "doors-classic": "classic-doors-home",
    "dwa": "classic-doors-home",
    "rqa": "ai-hub",
    "requirements-quality-assistant": "ai-hub",
    "bob": "bob-docs-home",
    "bob-config": "bob-modes",
    "mcp": "bob-mcp",
    "download": "passport-advantage",
    "media": "passport-advantage",
    "forum": "community",
    "forums": "community",
    "support": "support-portal",
    "search": "docs-search",
    "github": "elm-mcp",
    "source": "elm-mcp",
    "repo": "elm-mcp",
}


def lookup(
    topic: Optional[str] = None,
    version: Optional[str] = None,
    product: Optional[str] = None,
    verify_live: bool = False,
) -> Dict:
    """Return curated docs links matching the filters.

    Args:
        topic: short slug or natural phrase. Matched against:
            (1) exact topic id, (2) synonyms, (3) substring of display
            name. None returns the full curated set.
        version: filter to a specific ELM version (e.g., "7.1"). "*"
            entries always match.
        product: filter to a product family ("ELM", "DOORS Next",
            "EWM", "ETM", "GCM", "Classic", "Bob").
        verify_live: if True, perform a fast HEAD check on each match
            and flag dead links. Off by default — adds latency.

    Returns a dict:
        {
          "query": {...echo of inputs},
          "matches": [ {topic, display, url, version, product, notes,
                         is_search, live?}, ... ],
          "fallbacks": [ {display, url, notes}, ... ]
              (search-landing entries appended if any deep links rotted)
        }
    """
    topic_norm = (topic or "").strip().lower().replace(" ", "-")
    target_topic = _SYNONYMS.get(topic_norm, topic_norm)

    matches: List[Dict] = []
    for entry in _LINKS:
        if version and entry["version"] not in (version, "*"):
            continue
        if product and entry["product"].lower() != product.lower():
            continue
        if target_topic:
            if (target_topic == entry["topic"] or
                target_topic in entry["topic"] or
                target_topic in entry["display"].lower()):
                matches.append(dict(entry))
        else:
            matches.append(dict(entry))

    # If verify_live was requested, check each URL with a GET (HEAD
    # doesn't work for ibm.com/docs — returns 404 even when GET 200s)
    # and a real browser User-Agent (IBM's CDN sniffs UA).
    rotted_count = 0
    if verify_live and matches:
        try:
            import requests
            ua = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36")
            for m in matches:
                try:
                    # Stream + immediate close — we only care about the
                    # status code, not the body
                    r = requests.get(m["url"], allow_redirects=True,
                                      timeout=6,
                                      stream=True,
                                      headers={"User-Agent": ua})
                    r.close()
                    m["live"] = r.status_code < 400
                    if not m["live"]:
                        rotted_count += 1
                except Exception:
                    m["live"] = False
                    rotted_count += 1
        except ImportError:
            for m in matches:
                m["live"] = None  # couldn't check

    # Always include search-landing fallbacks if any results, OR if
    # nothing matched the topic
    fallbacks = []
    if not matches or rotted_count > 0:
        for entry in _LINKS:
            if entry.get("is_search") == "true":
                fallbacks.append({
                    "display": entry["display"],
                    "url": entry["url"],
                    "notes": entry["notes"],
                })

    return {
        "query": {
            "topic": topic,
            "version": version,
            "product": product,
            "verify_live": verify_live,
        },
        "matches": matches,
        "fallbacks": fallbacks,
        "total": len(matches),
        "rotted": rotted_count,
    }


def all_topics() -> List[str]:
    """List every curated topic slug + synonym."""
    seen = set()
    out = []
    for e in _LINKS:
        if e["topic"] not in seen:
            seen.add(e["topic"])
            out.append(e["topic"])
    for syn in _SYNONYMS:
        if syn not in seen:
            seen.add(syn)
            out.append(syn)
    return sorted(out)
