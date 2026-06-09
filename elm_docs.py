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

    # ── DOORS Next features ────────────────────────────────────────
    {
        "topic": "dng-modules",
        "display": "DNG — Working with modules",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=requirements-managing-modules",
        "version": "7.1",
        "product": "DOORS Next",
        "notes": "Creating, structuring, and editing modules in DOORS Next.",
    },
    {
        "topic": "dng-create-requirements",
        "display": "DNG — Creating and editing requirements",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=requirements-creating-managing",
        "version": "7.1",
        "product": "DOORS Next",
        "notes": "How to author requirements + rich text + attributes in DNG.",
    },
    {
        "topic": "dng-links",
        "display": "DNG — Linking artifacts (traceability)",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=management-linking-artifacts",
        "version": "7.1",
        "product": "DOORS Next",
        "notes": "Establishing OSLC links between requirements, design, tests.",
    },
    {
        "topic": "dng-link-types",
        "display": "DNG — Link types and validity",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=artifacts-link-types-validity",
        "version": "7.1",
        "product": "DOORS Next",
        "notes": "Built-in link types (satisfies, validates, elaborates, etc.) + defining custom ones.",
    },
    {
        "topic": "dng-baselines",
        "display": "DNG — Baselines (versioning)",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=management-baselines",
        "version": "7.1",
        "product": "DOORS Next",
        "notes": "Creating + comparing baselines; required for milestone reviews.",
    },
    {
        "topic": "dng-streams",
        "display": "DNG — Streams and configuration management",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=management-using-configurations",
        "version": "7.1",
        "product": "DOORS Next",
        "notes": "Branching reqs with streams; enables parallel work + variant management.",
    },
    {
        "topic": "dng-reviews",
        "display": "DNG — Reviews and approvals",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=management-reviews",
        "version": "7.1",
        "product": "DOORS Next",
        "notes": "Setting up review workflows + collecting approvals.",
    },
    {
        "topic": "dng-attributes",
        "display": "DNG — Attributes and artifact types",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=customizations-defining-types-attributes",
        "version": "7.1",
        "product": "DOORS Next",
        "notes": "Customizing the type system — define custom attributes per artifact type.",
    },
    {
        "topic": "dng-filters",
        "display": "DNG — Filters and views",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=artifacts-filters-views",
        "version": "7.1",
        "product": "DOORS Next",
        "notes": "Saved filters + module views for narrowing scope.",
    },
    {
        "topic": "dng-import",
        "display": "DNG — Importing requirements (ReqIF, CSV, Word)",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=management-importing",
        "version": "7.1",
        "product": "DOORS Next",
        "notes": "Bringing reqs in from external sources.",
    },
    {
        "topic": "dng-reqif",
        "display": "DNG — ReqIF round-trip import / export",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=management-reqif-round-trip",
        "version": "7.1",
        "product": "DOORS Next",
        "notes": "Standardized req interchange with suppliers + other RM tools.",
    },
    {
        "topic": "dng-permissions",
        "display": "DNG — Permissions and roles",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=management-permissions",
        "version": "7.1",
        "product": "DOORS Next",
        "notes": "Project-area roles + per-artifact access control.",
    },
    {
        "topic": "dng-templates",
        "display": "DNG — Process and project templates",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=management-process-templates",
        "version": "7.1",
        "product": "DOORS Next",
        "notes": "Starting projects from SAFe / Automotive SPICE / custom templates.",
    },
    {
        "topic": "dng-richtext",
        "display": "DNG — Rich text, tables, and embedded images",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=artifacts-rich-text-content",
        "version": "7.1",
        "product": "DOORS Next",
        "notes": "Formatting + inserting images / tables in requirement content.",
    },

    # ── EWM features ───────────────────────────────────────────────
    {
        "topic": "ewm-work-items",
        "display": "EWM — Work items (Tasks, Defects, Stories, etc.)",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=workflow-managing-work-items",
        "version": "7.1",
        "product": "EWM",
        "notes": "Creating + editing work items of all types.",
    },
    {
        "topic": "ewm-workflow",
        "display": "EWM — Customizing workflows and states",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=process-workflows",
        "version": "7.1",
        "product": "EWM",
        "notes": "Defining state machines + transitions for each work-item type.",
    },
    {
        "topic": "ewm-plans",
        "display": "EWM — Plans and iterations",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=workflow-managing-plans",
        "version": "7.1",
        "product": "EWM",
        "notes": "Sprint / iteration planning + backlog management.",
    },
    {
        "topic": "ewm-categories",
        "display": "EWM — Categories and 'filed against'",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=process-categories",
        "version": "7.1",
        "product": "EWM",
        "notes": "Organizing work items by category; required for routing.",
    },
    {
        "topic": "ewm-approvals",
        "display": "EWM — Approvals and reviews on work items",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=workflow-approving-work-items",
        "version": "7.1",
        "product": "EWM",
        "notes": "Setting up approval gates inside the work-item workflow.",
    },
    {
        "topic": "ewm-build",
        "display": "EWM — Build engines and CI integration",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=workflow-build",
        "version": "7.1",
        "product": "EWM",
        "notes": "Connecting Jenkins / GitHub Actions / other CI to EWM.",
    },
    {
        "topic": "ewm-scm",
        "display": "EWM — Source Control Management (Jazz SCM)",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=workflow-source-control",
        "version": "7.1",
        "product": "EWM",
        "notes": "Jazz SCM + change sets; alternative to Git for some teams.",
    },
    {
        "topic": "ewm-process-template",
        "display": "EWM — Process templates (Scrum, SAFe, etc.)",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=process-process-templates",
        "version": "7.1",
        "product": "EWM",
        "notes": "Starting projects from a process template.",
    },

    # ── ETM features ───────────────────────────────────────────────
    {
        "topic": "etm-test-plans",
        "display": "ETM — Test plans",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=test-creating-test-plans",
        "version": "7.1",
        "product": "ETM",
        "notes": "Test plans hold strategy + scope + reference test cases.",
    },
    {
        "topic": "etm-test-cases",
        "display": "ETM — Test cases",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=test-creating-test-cases",
        "version": "7.1",
        "product": "ETM",
        "notes": "Authoring test cases with steps + expected results.",
    },
    {
        "topic": "etm-test-scripts",
        "display": "ETM — Test scripts (manual + automated)",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=test-creating-test-scripts",
        "version": "7.1",
        "product": "ETM",
        "notes": "Scripts hold the actual steps; cases reference scripts.",
    },
    {
        "topic": "etm-test-execution-records",
        "display": "ETM — Test execution records (TERs)",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=test-creating-test-execution",
        "version": "7.1",
        "product": "ETM",
        "notes": "An instance of running a test case in a particular release / iteration.",
    },
    {
        "topic": "etm-test-results",
        "display": "ETM — Test results",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=test-creating-test-results",
        "version": "7.1",
        "product": "ETM",
        "notes": "Pass / fail outcomes attached to TERs.",
    },
    {
        "topic": "etm-automation",
        "display": "ETM — Test automation integration",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=test-automation",
        "version": "7.1",
        "product": "ETM",
        "notes": "Connecting Selenium / JUnit / other automation frameworks.",
    },
    {
        "topic": "etm-defect-integration",
        "display": "ETM — Defect tracking integration with EWM",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=test-defect-integration",
        "version": "7.1",
        "product": "ETM",
        "notes": "File defects from failed tests + link back to TERs.",
    },

    # ── GCM features ───────────────────────────────────────────────
    {
        "topic": "gcm-components",
        "display": "GCM — Creating components",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=configuration-components",
        "version": "7.1",
        "product": "GCM",
        "notes": "Components are the building blocks of global configurations.",
    },
    {
        "topic": "gcm-streams",
        "display": "GCM — Global configurations and streams",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=configuration-global-configurations",
        "version": "7.1",
        "product": "GCM",
        "notes": "Coordinating streams across DNG / EWM / ETM.",
    },
    {
        "topic": "gcm-baselines",
        "display": "GCM — Global baselines",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=configuration-global-baselines",
        "version": "7.1",
        "product": "GCM",
        "notes": "Snapshotting an entire configuration across apps.",
    },

    # ── Admin + Operations ─────────────────────────────────────────
    {
        "topic": "admin-ldap",
        "display": "Admin — LDAP / SSO setup",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=administering-user-authentication",
        "version": "7.1",
        "product": "ELM",
        "notes": "Connecting ELM to enterprise directory + SSO.",
    },
    {
        "topic": "admin-users",
        "display": "Admin — User management and licensing",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=administering-users-licenses",
        "version": "7.1",
        "product": "ELM",
        "notes": "Adding users + assigning client access licenses (CALs).",
    },
    {
        "topic": "admin-backup",
        "display": "Admin — Backup and restore",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=administering-backups",
        "version": "7.1",
        "product": "ELM",
        "notes": "Database + repository backup procedures.",
    },
    {
        "topic": "admin-performance",
        "display": "Admin — Performance tuning",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=administering-performance",
        "version": "7.1",
        "product": "ELM",
        "notes": "JVM / heap / database tuning for production deployments.",
    },
    {
        "topic": "admin-logs",
        "display": "Admin — Logs and troubleshooting",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=administering-logs-troubleshooting",
        "version": "7.1",
        "product": "ELM",
        "notes": "Finding logs + common error patterns + diagnostic tools.",
    },
    {
        "topic": "admin-security",
        "display": "Admin — Security configuration",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=administering-security",
        "version": "7.1",
        "product": "ELM",
        "notes": "SSL / certificates / encryption / hardening.",
    },
    {
        "topic": "admin-server",
        "display": "Admin — Server administration overview",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=administering-servers",
        "version": "7.1",
        "product": "ELM",
        "notes": "Starting / stopping / configuring the Jazz application server.",
    },

    # ── APIs / Integration ─────────────────────────────────────────
    {
        "topic": "api-oslc-core",
        "display": "OSLC Core 2.0 specification",
        "url": "https://jazz.net/wiki/bin/view/Main/OslcCoreSpecification",
        "version": "*",
        "product": "ELM",
        "notes": "The base OSLC spec all other ELM OSLC APIs build on.",
    },
    {
        "topic": "api-jfs",
        "display": "Jazz Foundation Services (JFS) APIs",
        "url": "https://jazz.net/wiki/bin/view/Main/RootServicesSpec",
        "version": "*",
        "product": "ELM",
        "notes": "Root services + service provider discovery for ELM apps.",
    },
    {
        "topic": "api-lqe",
        "display": "Lifecycle Query Engine (LQE)",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=reporting-lifecycle-query-engine",
        "version": "7.1",
        "product": "ELM",
        "notes": "TRS-based query engine — for cross-app reports + SPARQL.",
    },
    {
        "topic": "api-rpe",
        "display": "Reporting (RPE / Document Builder)",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=reporting-document-builder",
        "version": "7.1",
        "product": "ELM",
        "notes": "Generate Word / PDF / HTML reports from ELM data.",
    },
    {
        "topic": "api-jira-integration",
        "display": "Jira integration with ELM",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=integrating-jira",
        "version": "7.1",
        "product": "ELM",
        "notes": "Bidirectional Jira ↔ EWM / DNG sync.",
    },
    {
        "topic": "api-github-integration",
        "display": "GitHub integration with ELM",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=integrating-github",
        "version": "7.1",
        "product": "ELM",
        "notes": "Link EWM work items to GitHub PRs + commits.",
    },
    {
        "topic": "api-eclipse",
        "display": "Eclipse client for ELM",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=client-eclipse",
        "version": "7.1",
        "product": "ELM",
        "notes": "Developer-facing Eclipse client for EWM (and SCM).",
    },

    # ── Compliance / standards mapping ─────────────────────────────
    {
        "topic": "compliance-cmmi",
        "display": "ELM for CMMI processes",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=processes-cmmi",
        "version": "7.1",
        "product": "ELM",
        "notes": "Using ELM templates for CMMI-aligned processes.",
    },
    {
        "topic": "compliance-aspice",
        "display": "Automotive SPICE template for ELM",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=processes-automotive-spice",
        "version": "7.1",
        "product": "ELM",
        "notes": "Out-of-the-box Automotive SPICE process template.",
    },
    {
        "topic": "compliance-safe",
        "display": "SAFe (Scaled Agile Framework) on ELM",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=processes-safe",
        "version": "7.1",
        "product": "ELM",
        "notes": "SAFe artifact types + workflow templates for ELM.",
    },

    # ── Migration + Interop ────────────────────────────────────────
    {
        "topic": "migration-doors-classic",
        "display": "Migrating DOORS Classic to DOORS Next",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=migration-doors-doors-next",
        "version": "7.1",
        "product": "Classic",
        "notes": "Official DOORS 9 → DNG migration utility + procedures.",
    },
    {
        "topic": "migration-rtc-ewm",
        "display": "RTC → EWM rebrand history + migration",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=migration-rtc-to-ewm",
        "version": "7.1",
        "product": "EWM",
        "notes": "RTC was renamed to EWM; data is preserved across upgrades.",
    },
    {
        "topic": "migration-rqm-etm",
        "display": "RQM → ETM rebrand history + migration",
        "url": "https://www.ibm.com/docs/en/engineering-lifecycle-management-suite/lifecycle-management/7.1.0?topic=migration-rqm-to-etm",
        "version": "7.1",
        "product": "ETM",
        "notes": "RQM was renamed to ETM; data is preserved across upgrades.",
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

    # DNG feature aliases
    "modules": "dng-modules",
    "create-req": "dng-create-requirements",
    "edit-req": "dng-create-requirements",
    "authoring": "dng-create-requirements",
    "linking": "dng-links",
    "traceability": "dng-links",
    "link-type": "dng-link-types",
    "link-types": "dng-link-types",
    "satisfies": "dng-link-types",
    "validatedby": "dng-link-types",
    "baseline": "dng-baselines",
    "baselines": "dng-baselines",
    "versioning": "dng-baselines",
    "snapshot": "dng-baselines",
    "stream": "dng-streams",
    "streams": "dng-streams",
    "config-management": "dng-streams",
    "cm": "dng-streams",
    "review": "dng-reviews",
    "reviews": "dng-reviews",
    "approval": "dng-reviews",
    "approvals": "dng-reviews",
    "attribute": "dng-attributes",
    "attributes": "dng-attributes",
    "type-system": "dng-attributes",
    "custom-attribute": "dng-attributes",
    "filter": "dng-filters",
    "filters": "dng-filters",
    "view": "dng-filters",
    "views": "dng-filters",
    "import": "dng-import",
    "reqif": "dng-reqif",
    "permissions": "dng-permissions",
    "roles": "dng-permissions",
    "access-control": "dng-permissions",
    "template": "dng-templates",
    "templates": "dng-templates",
    "project-template": "dng-templates",
    "richtext": "dng-richtext",
    "rich-text": "dng-richtext",
    "images": "dng-richtext",
    "tables": "dng-richtext",
    "embedded": "dng-richtext",

    # EWM feature aliases
    "work-items": "ewm-work-items",
    "workitem": "ewm-work-items",
    "workitems": "ewm-work-items",
    "task": "ewm-work-items",
    "defect": "ewm-work-items",
    "story": "ewm-work-items",
    "workflow": "ewm-workflow",
    "state-machine": "ewm-workflow",
    "transitions": "ewm-workflow",
    "plan": "ewm-plans",
    "plans": "ewm-plans",
    "iteration": "ewm-plans",
    "sprint": "ewm-plans",
    "backlog": "ewm-plans",
    "category": "ewm-categories",
    "categories": "ewm-categories",
    "filed-against": "ewm-categories",
    "build": "ewm-build",
    "ci": "ewm-build",
    "cicd": "ewm-build",
    "jazz-scm": "ewm-scm",
    "scm": "ewm-scm",
    "changeset": "ewm-scm",
    "change-set": "ewm-scm",
    "process-template": "ewm-process-template",
    "scrum": "ewm-process-template",

    # ETM feature aliases
    "test-plan": "etm-test-plans",
    "test-plans": "etm-test-plans",
    "test-case": "etm-test-cases",
    "test-cases": "etm-test-cases",
    "test-script": "etm-test-scripts",
    "test-scripts": "etm-test-scripts",
    "ter": "etm-test-execution-records",
    "ters": "etm-test-execution-records",
    "test-execution": "etm-test-execution-records",
    "test-result": "etm-test-results",
    "test-results": "etm-test-results",
    "test-automation": "etm-automation",
    "selenium": "etm-automation",
    "junit": "etm-automation",
    "automated-testing": "etm-automation",

    # GCM feature aliases
    "component": "gcm-components",
    "components": "gcm-components",
    "global-config": "gcm-streams",
    "global-configurations": "gcm-streams",
    "global-baseline": "gcm-baselines",

    # Admin aliases
    "ldap": "admin-ldap",
    "sso": "admin-ldap",
    "auth": "admin-ldap",
    "authentication": "admin-ldap",
    "users": "admin-users",
    "user-management": "admin-users",
    "license": "admin-users",
    "licenses": "admin-users",
    "cal": "admin-users",
    "backup": "admin-backup",
    "restore": "admin-backup",
    "performance": "admin-performance",
    "tuning": "admin-performance",
    "jvm": "admin-performance",
    "logs": "admin-logs",
    "logging": "admin-logs",
    "troubleshooting": "admin-logs",
    "security": "admin-security",
    "ssl": "admin-security",
    "certificate": "admin-security",
    "encryption": "admin-security",
    "server": "admin-server",
    "server-admin": "admin-server",

    # API aliases
    "oslc-core": "api-oslc-core",
    "oslc-spec": "api-oslc-core",
    "jfs": "api-jfs",
    "jazz-foundation": "api-jfs",
    "root-services": "api-jfs",
    "lqe": "api-lqe",
    "sparql": "api-lqe",
    "rpe": "api-rpe",
    "document-builder": "api-rpe",
    "reports": "api-rpe",
    "reporting": "api-rpe",
    "jira": "api-jira-integration",
    "jira-integration": "api-jira-integration",
    "github-integration": "api-github-integration",
    "eclipse": "api-eclipse",
    "eclipse-client": "api-eclipse",

    # Compliance / process aliases
    "cmmi": "compliance-cmmi",
    "aspice": "compliance-aspice",
    "automotive-spice": "compliance-aspice",
    "automotivespice": "compliance-aspice",
    "safe-framework": "compliance-safe",
    "safe-template": "compliance-safe",

    # Migration aliases
    "doors-migration": "migration-doors-classic",
    "classic-migration": "migration-doors-classic",
    "rtc-to-ewm": "migration-rtc-ewm",
    "rqm-to-etm": "migration-rqm-etm",
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
