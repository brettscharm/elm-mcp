#!/usr/bin/env python3
"""
IBM ELM MCP Server for IBM Bob
Provides tools for Bob to interact with IBM Engineering Lifecycle Management (ELM)
Covers DNG (requirements), EWM (work items), and ETM (test management)

Tools (16):
  1.  connect_to_elm          - Connect with credentials
  2.  list_projects           - List DNG/EWM/ETM projects (domain parameter)
  3.  get_modules             - Get modules from a DNG project
  4.  get_module_requirements - Get requirements from a module
  5.  save_requirements       - Save requirements to a file (JSON/CSV/Markdown)
  6.  get_artifact_types      - Discover artifact types for a DNG project
  7.  get_link_types          - Discover link types for a DNG project
  8.  create_requirements     - Create requirements with links in a descriptive folder
  9.  update_requirement      - Update an existing requirement's title and/or content
  10. create_baseline         - Create a baseline snapshot of a DNG project
  11. list_baselines          - List existing baselines for a DNG project
  12. compare_baselines       - Compare baseline vs current stream (shows diff)
  13. extract_pdf             - Extract text from a PDF file for import into DNG
  14. create_task             - Create an EWM Task with optional DNG requirement link
  15. create_test_case        - Create an ETM Test Case with optional DNG requirement link
  16. create_test_result      - Create an ETM Test Result (pass/fail) for a test case
"""

import os
import asyncio
from typing import Any, Optional, List, Dict
from mcp.server import Server
from mcp.types import Tool, TextContent
import mcp.server.stdio
from dotenv import load_dotenv
from doors_client import DOORSNextClient

load_dotenv()

app = Server("doors-next-server")

# ── Session State ─────────────────────────────────────────────
_client: Optional[DOORSNextClient] = None
_projects_cache: List[Dict] = []              # DNG projects
_ewm_projects_cache: List[Dict] = []          # EWM projects
_etm_projects_cache: List[Dict] = []          # ETM projects
_modules_cache: Dict[str, List[Dict]] = {}    # project_id -> modules
_last_requirements: List[Dict] = []
_last_module_name: str = ""
_last_project_name: str = ""
_folder_cache: Dict[str, Dict] = {}           # folder_name -> {title, url}


def _get_or_create_client() -> Optional[DOORSNextClient]:
    """Get existing client or try to create one from .env"""
    global _client
    if _client is not None:
        return _client

    base_url = os.getenv("DOORS_URL")
    username = os.getenv("DOORS_USERNAME")
    password = os.getenv("DOORS_PASSWORD")

    if all([base_url, username, password]):
        client = DOORSNextClient(base_url, username, password)
        if client.authenticate():
            _client = client
            return _client

    return None


def _find_by_identifier(items: List[Dict], identifier: str, key: str = 'title') -> Optional[Dict]:
    """Find item by 1-based index number or case-insensitive partial name match"""
    # Try as number first
    try:
        idx = int(identifier) - 1
        if 0 <= idx < len(items):
            return items[idx]
    except ValueError:
        pass

    # Partial name match (case-insensitive)
    lower = identifier.lower()
    for item in items:
        if lower in item.get(key, '').lower():
            return item

    return None


# ── Tool Definitions ──────────────────────────────────────────

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="connect_to_elm",
            description=(
                "Connect to an IBM ELM server with credentials. "
                "The URL can be the base server URL (e.g., https://server.com) "
                "or the DNG URL ending in /rm — both work. "
                "This single connection is used for ALL tools (DNG, EWM, and ETM). "
                "Must be called before any other tool."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "ELM server URL (e.g., https://server.com or https://server.com/rm)"
                    },
                    "username": {
                        "type": "string",
                        "description": "ELM username"
                    },
                    "password": {
                        "type": "string",
                        "description": "ELM password"
                    }
                },
                "required": ["url", "username", "password"]
            }
        ),
        Tool(
            name="list_projects",
            description=(
                "List projects from IBM ELM. "
                "Supports three domains: 'dng' (requirements), 'ewm' (work items), 'etm' (test management). "
                "Defaults to 'dng'. Returns a numbered list."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "enum": ["dng", "ewm", "etm"],
                        "description": "Which ELM domain to list projects from: 'dng' (default), 'ewm', or 'etm'"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="get_modules",
            description=(
                "Get all modules from a DOORS Next project. "
                "Modules are containers that hold requirements. "
                "Call list_projects first to get project numbers. "
                "To see actual requirements inside a module, use get_module_requirements next."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_identifier": {
                        "type": "string",
                        "description": "Project number (e.g., '3') or name (partial match supported)"
                    }
                },
                "required": ["project_identifier"]
            }
        ),
        Tool(
            name="get_module_requirements",
            description=(
                "Get all requirements from a specific module within a project. "
                "Call get_modules first to get module numbers. "
                "Returns requirement URLs needed by update_requirement, create_task, and create_test_case."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_identifier": {
                        "type": "string",
                        "description": "Project number or name"
                    },
                    "module_identifier": {
                        "type": "string",
                        "description": "Module number (from get_modules output) or name"
                    }
                },
                "required": ["project_identifier", "module_identifier"]
            }
        ),
        Tool(
            name="save_requirements",
            description=(
                "Save requirements to a file. "
                "Requires get_module_requirements to have been called first in this session. "
                "Supports JSON, CSV, and Markdown formats."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "format": {
                        "type": "string",
                        "enum": ["json", "csv", "markdown"],
                        "description": "Output format: json, csv, or markdown"
                    },
                    "filename": {
                        "type": "string",
                        "description": "Output filename (optional - auto-generated if omitted)"
                    }
                },
                "required": ["format"]
            }
        ),
        Tool(
            name="create_requirements",
            description=(
                "Create requirements in a DOORS Next project. "
                "MUST call get_artifact_types first to get valid type names for this project. "
                "Requirements are placed in a descriptive folder with [AI Generated] prefix auto-added. "
                "Returns created requirement URLs needed by create_task and create_test_case."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_identifier": {
                        "type": "string",
                        "description": "Project number or name"
                    },
                    "folder_name": {
                        "type": "string",
                        "description": "Descriptive folder name. Format: 'AI Generated - [username] - [summary]' (e.g., 'AI Generated - brett.scharmett - Security Requirements')"
                    },
                    "requirements": {
                        "type": "array",
                        "description": "Array of requirements to create",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {
                                    "type": "string",
                                    "description": "Requirement title (will be prefixed with [AI Generated])"
                                },
                                "content": {
                                    "type": "string",
                                    "description": "Requirement body text with details and acceptance criteria"
                                },
                                "artifact_type": {
                                    "type": "string",
                                    "description": "Artifact type name — MUST match a name from get_artifact_types output for this project"
                                },
                                "link_type": {
                                    "type": "string",
                                    "description": "Optional: Link type name (e.g., 'Satisfies', 'Elaborated By') from get_link_types"
                                },
                                "link_to": {
                                    "type": "string",
                                    "description": "Optional: URL of the requirement to link to (from get_module_requirements output). Must be provided together with link_type."
                                }
                            },
                            "required": ["title", "content", "artifact_type"]
                        }
                    }
                },
                "required": ["project_identifier", "folder_name", "requirements"]
            }
        ),
        Tool(
            name="get_link_types",
            description=(
                "Get all available link types for a DOORS Next project. "
                "Use this to find the correct link type when creating linked requirements "
                "(e.g., Satisfies, Elaborated By, etc.)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_identifier": {
                        "type": "string",
                        "description": "Project number or name"
                    }
                },
                "required": ["project_identifier"]
            }
        ),
        Tool(
            name="get_artifact_types",
            description=(
                "Get all available artifact types for a DOORS Next project. "
                "MUST be called before create_requirements — artifact types vary by project. "
                "Returns the exact type names to use in the artifact_type field."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_identifier": {
                        "type": "string",
                        "description": "Project number or name"
                    }
                },
                "required": ["project_identifier"]
            }
        ),
        Tool(
            name="update_requirement",
            description=(
                "Update an existing requirement in DNG. "
                "Provide the requirement URL (from get_module_requirements or create_requirements) "
                "and the new title and/or content. Uses OSLC optimistic locking (ETag). "
                "Use this for PDF re-import workflows where only changed requirements need updating."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "requirement_url": {
                        "type": "string",
                        "description": "Full URL of the requirement to update (from get_module_requirements or create_requirements output)"
                    },
                    "title": {
                        "type": "string",
                        "description": "New title for the requirement (optional — keeps existing if omitted)"
                    },
                    "content": {
                        "type": "string",
                        "description": "New content/description as plain text (optional — keeps existing if omitted)"
                    }
                },
                "required": ["requirement_url"]
            }
        ),
        Tool(
            name="create_baseline",
            description=(
                "Create a baseline (immutable snapshot) of the current state of a DNG project. "
                "Use this after importing requirements to freeze the state before making changes. "
                "Baseline creation is async — the server processes it in the background."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_identifier": {
                        "type": "string",
                        "description": "DNG project number or name"
                    },
                    "title": {
                        "type": "string",
                        "description": "Baseline name (e.g., 'V1 Import Baseline'). Will be prefixed with [AI Generated]."
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional baseline description"
                    }
                },
                "required": ["project_identifier", "title"]
            }
        ),
        Tool(
            name="list_baselines",
            description=(
                "List all baselines for a DNG project. "
                "Returns baseline names, URLs, and creation dates. "
                "Use this to see available baselines for comparison."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_identifier": {
                        "type": "string",
                        "description": "DNG project number or name"
                    }
                },
                "required": ["project_identifier"]
            }
        ),
        Tool(
            name="compare_baselines",
            description=(
                "Compare requirements between a baseline and the current stream. "
                "Reads requirements from a baseline snapshot and the current state, "
                "then returns what changed, was added, or was removed. "
                "Call list_baselines first to get baseline URLs."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_identifier": {
                        "type": "string",
                        "description": "DNG project number or name"
                    },
                    "module_identifier": {
                        "type": "string",
                        "description": "Module number or name (from get_modules)"
                    },
                    "baseline_url": {
                        "type": "string",
                        "description": "URL of the baseline to compare against (from list_baselines output)"
                    }
                },
                "required": ["project_identifier", "module_identifier", "baseline_url"]
            }
        ),
        Tool(
            name="extract_pdf",
            description=(
                "Extract text from a PDF file. "
                "Use this INSTEAD of trying to read PDFs yourself. "
                "Returns clean structured text with page numbers. "
                "Use this as the first step when importing a PDF into DNG."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the PDF file on disk"
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="create_task",
            description=(
                "Create an EWM Task work item. "
                "Optionally links to a DNG requirement via calm:implementsRequirement. "
                "Use list_projects with domain='ewm' first to find the EWM project."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ewm_project": {
                        "type": "string",
                        "description": "EWM project number (from list_projects domain=ewm) or name"
                    },
                    "title": {
                        "type": "string",
                        "description": "Task title (will be prefixed with [AI Generated])"
                    },
                    "description": {
                        "type": "string",
                        "description": "Task description with details and acceptance criteria"
                    },
                    "requirement_url": {
                        "type": "string",
                        "description": "Optional: URL of a DNG requirement (from get_module_requirements or create_requirements output) to link via Implements Requirement"
                    }
                },
                "required": ["ewm_project", "title"]
            }
        ),
        Tool(
            name="create_test_case",
            description=(
                "Create an ETM Test Case. "
                "Optionally links to a DNG requirement via oslc_qm:validatesRequirement. "
                "Use list_projects with domain='etm' first to find the ETM project."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "etm_project": {
                        "type": "string",
                        "description": "ETM project number (from list_projects domain=etm) or name"
                    },
                    "title": {
                        "type": "string",
                        "description": "Test case title (will be prefixed with [AI Generated])"
                    },
                    "description": {
                        "type": "string",
                        "description": "Test case description and test steps"
                    },
                    "requirement_url": {
                        "type": "string",
                        "description": "Optional: URL of a DNG requirement (from get_module_requirements or create_requirements output) to link via Validates Requirement"
                    }
                },
                "required": ["etm_project", "title"]
            }
        ),
        Tool(
            name="create_test_result",
            description=(
                "Create an ETM Test Result for a test case. "
                "Records a pass/fail/blocked/incomplete/error result. "
                "Requires the test case URL from create_test_case output."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "etm_project": {
                        "type": "string",
                        "description": "ETM project number (from list_projects domain=etm) or name"
                    },
                    "test_case_url": {
                        "type": "string",
                        "description": "URL of the Test Case this result reports on (from create_test_case)"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["passed", "failed", "blocked", "incomplete", "error"],
                        "description": "Test result status"
                    },
                    "title": {
                        "type": "string",
                        "description": "Optional result title (auto-generated if omitted)"
                    }
                },
                "required": ["etm_project", "test_case_url", "status"]
            }
        ),
    ]


# ── Tool Handlers ─────────────────────────────────────────────

@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    global _client, _projects_cache, _ewm_projects_cache, _etm_projects_cache
    global _modules_cache, _last_requirements, _last_module_name, _last_project_name
    global _folder_cache

    try:
        # ── connect_to_elm ────────────────────────────────────
        if name == "connect_to_elm":
            url = arguments.get("url", "").strip().rstrip('/')
            username = arguments.get("username", "").strip()
            password = arguments.get("password", "").strip()

            if not all([url, username, password]):
                return [TextContent(type="text", text="Error: url, username, and password are all required.")]

            # Auto-append /rm if the user gave the base server URL
            if not url.endswith('/rm'):
                url = f"{url}/rm"

            client = DOORSNextClient(url, username, password)
            if not client.authenticate():
                return [TextContent(type="text", text=(
                    "Failed to connect. Please check:\n"
                    "- URL is correct (e.g., https://your-server.com)\n"
                    "- Username and password are correct\n"
                    "- The server is reachable from this machine"
                ))]

            _client = client
            # Clear all caches on new connection
            _ewm_projects_cache.clear()
            _etm_projects_cache.clear()
            _modules_cache.clear()
            _folder_cache.clear()
            _last_requirements.clear()

            projects = _client.list_projects()
            _projects_cache = projects

            return [TextContent(type="text", text=(
                f"Successfully connected to IBM ELM!\n\n"
                f"Found **{len(projects)}** DNG projects.\n\n"
                f"**What I can do:**\n"
                f"- **DNG** — Read, create, and update requirements. Import PDFs. Create baselines.\n"
                f"- **EWM** — Create Tasks linked to requirements.\n"
                f"- **ETM** — Create Test Cases and record Test Results (pass/fail).\n"
                f"- **Full Lifecycle** — Requirements → Tasks → Test Cases, all cross-linked.\n\n"
                f"Which project would you like to work with?"
            ))]

        # ── compare_baselines (DNG CM) ────────────────────────
        elif name == "compare_baselines":
            proj_id = arguments.get("project_identifier", "")
            mod_id = arguments.get("module_identifier", "")
            bl_url = arguments.get("baseline_url", "")

            if not proj_id or not mod_id or not bl_url:
                return [TextContent(type="text", text=(
                    "Error: project_identifier, module_identifier, and baseline_url are all required."
                ))]

            if not _projects_cache:
                _projects_cache = client.list_projects()

            project = _find_by_identifier(_projects_cache, proj_id)
            if not project:
                return [TextContent(type="text", text=f"Project not found: '{proj_id}'")]

            project_key = project['id']
            if project_key not in _modules_cache:
                modules = client.get_modules(project['url'])
                _modules_cache[project_key] = modules

            modules = _modules_cache.get(project_key, [])
            module = _find_by_identifier(modules, mod_id)
            if not module:
                return [TextContent(type="text", text=f"Module not found: '{mod_id}'")]

            # Read current requirements
            current_reqs = client.get_module_requirements(module['url'])
            # Read baseline requirements
            baseline_reqs = client.get_module_requirements(module['url'], config_url=bl_url)

            # Build lookup maps by title for diffing
            current_map = {r.get('title', ''): r for r in current_reqs}
            baseline_map = {r.get('title', ''): r for r in baseline_reqs}

            all_titles = set(list(current_map.keys()) + list(baseline_map.keys()))

            added = []
            removed = []
            changed = []
            unchanged = []

            for title in sorted(all_titles):
                in_current = title in current_map
                in_baseline = title in baseline_map

                if in_current and not in_baseline:
                    added.append(current_map[title])
                elif in_baseline and not in_current:
                    removed.append(baseline_map[title])
                elif in_current and in_baseline:
                    cur = current_map[title]
                    bl = baseline_map[title]
                    # Compare descriptions
                    cur_desc = (cur.get('description') or '').strip()
                    bl_desc = (bl.get('description') or '').strip()
                    if cur_desc != bl_desc:
                        changed.append({'title': title, 'baseline': bl_desc, 'current': cur_desc})
                    else:
                        unchanged.append(title)

            lines = [
                f"# Baseline Comparison: '{module['title']}'\n",
                f"**Baseline:** `{bl_url}`\n",
                f"**Current stream** vs **baseline**:\n",
            ]

            if not added and not removed and not changed:
                lines.append("**No changes detected.** The current stream matches the baseline.")
            else:
                if changed:
                    lines.append(f"### Modified ({len(changed)})\n")
                    for c in changed:
                        lines.append(f"- **{c['title']}**")
                        bl_preview = c['baseline'][:100] + '...' if len(c['baseline']) > 100 else c['baseline']
                        cur_preview = c['current'][:100] + '...' if len(c['current']) > 100 else c['current']
                        lines.append(f"  - Baseline: {bl_preview}")
                        lines.append(f"  - Current: {cur_preview}")

                if added:
                    lines.append(f"\n### Added ({len(added)})\n")
                    for a in added:
                        lines.append(f"- **{a.get('title', 'Untitled')}**")

                if removed:
                    lines.append(f"\n### Removed ({len(removed)})\n")
                    for r in removed:
                        lines.append(f"- **{r.get('title', 'Untitled')}**")

                if unchanged:
                    lines.append(f"\n### Unchanged ({len(unchanged)})\n")
                    lines.append(f"_{len(unchanged)} requirement(s) identical to baseline._")

            lines.append(f"\n**Summary:** {len(changed)} modified, {len(added)} added, {len(removed)} removed, {len(unchanged)} unchanged")

            return [TextContent(type="text", text="\n".join(lines))]

        # ── extract_pdf (no connection needed) ────────────────
        if name == "extract_pdf":
            file_path = arguments.get("file_path", "").strip()
            if not file_path:
                return [TextContent(type="text", text="Error: file_path is required.")]

            import os
            if not os.path.exists(file_path):
                return [TextContent(type="text", text=f"Error: File not found: {file_path}")]

            try:
                import fitz  # PyMuPDF
            except ImportError:
                return [TextContent(type="text", text=(
                    "Error: PyMuPDF is not installed. Run: pip install PyMuPDF"
                ))]

            try:
                doc = fitz.open(file_path)
                pages = []
                for i, page in enumerate(doc, 1):
                    text = page.get_text().strip()
                    if text:
                        pages.append(f"--- Page {i} ---\n{text}")
                doc.close()

                if not pages:
                    return [TextContent(type="text", text=(
                        f"No text found in '{os.path.basename(file_path)}'. "
                        "The PDF may be image-only (scanned without OCR)."
                    ))]

                full_text = "\n\n".join(pages)
                return [TextContent(type="text", text=(
                    f"# PDF Extracted: {os.path.basename(file_path)}\n"
                    f"**Pages:** {len(pages)}\n\n"
                    f"{full_text}"
                ))]
            except Exception as e:
                return [TextContent(type="text", text=f"Error reading PDF: {e}")]

        # ── All other tools require a connection ──────────────
        client = _get_or_create_client()
        if client is None:
            return [TextContent(type="text", text=(
                "Not connected to ELM.\n\n"
                "Use the `connect_to_elm` tool with your server URL, username, and password."
            ))]

        # ── list_projects ─────────────────────────────────────
        if name == "list_projects":
            domain = arguments.get("domain", "dng").lower()

            if domain == "ewm":
                if not _ewm_projects_cache:
                    _ewm_projects_cache = client.list_ewm_projects()
                projects = _ewm_projects_cache
                label = "EWM (Engineering Workflow Management)"
                hint = "Use `create_task` with an EWM project number or name."
            elif domain == "etm":
                if not _etm_projects_cache:
                    _etm_projects_cache = client.list_etm_projects()
                projects = _etm_projects_cache
                label = "ETM (Engineering Test Management)"
                hint = "Use `create_test_case` with an ETM project number or name."
            else:
                if not _projects_cache:
                    _projects_cache = client.list_projects()
                projects = _projects_cache
                label = "DNG (DOORS Next Generation)"
                hint = "Use `get_modules` with a project number or name to see its modules."

            if not projects:
                return [TextContent(type="text", text=(
                    f"No {domain.upper()} projects found. Check your permissions or server URL."
                ))]

            lines = [f"# {label} Projects ({len(projects)} total)\n"]
            for i, p in enumerate(projects, 1):
                lines.append(f"{i}. **{p['title']}**")

            lines.append(f"\n{hint}")
            return [TextContent(type="text", text="\n".join(lines))]

        # ── get_modules ───────────────────────────────────────
        elif name == "get_modules":
            identifier = arguments.get("project_identifier", "")
            if not identifier:
                return [TextContent(type="text", text="Error: project_identifier is required.")]

            # Ensure projects are loaded
            if not _projects_cache:
                _projects_cache = client.list_projects()

            project = _find_by_identifier(_projects_cache, identifier)
            if not project:
                names = "\n".join(f"{i}. {p['title']}" for i, p in enumerate(_projects_cache, 1))
                return [TextContent(type="text", text=(
                    f"Project not found: '{identifier}'\n\nAvailable projects:\n{names}"
                ))]

            _last_project_name = project['title']
            project_key = project['id']

            # Fetch modules
            modules = client.get_modules(project['url'])
            _modules_cache[project_key] = modules

            if not modules:
                return [TextContent(type="text", text=(
                    f"No modules found in '{project['title']}'.\n\n"
                    "This could mean the project has no modules, or the API endpoint "
                    "is not available for this project type."
                ))]

            source = modules[0].get('source', '')
            note = ""
            if source == 'oslc_folders':
                note = (
                    "\n\n*Note: These were retrieved via the OSLC folder API. "
                    "Some entries may be organizational folders rather than requirement modules.*"
                )

            lines = [
                f"# Modules in '{project['title']}'\n",
                f"Found **{len(modules)}** module(s):\n",
            ]

            for i, m in enumerate(modules, 1):
                lines.append(f"{i}. **{m['title']}**")
                if m.get('id'):
                    lines.append(f"   - ID: `{m['id']}`")
                if m.get('modified'):
                    lines.append(f"   - Modified: {m['modified']}")

            lines.append(
                f"\nUse `get_module_requirements` with a module number or name "
                f"to get its requirements.{note}"
            )
            return [TextContent(type="text", text="\n".join(lines))]

        # ── get_module_requirements ───────────────────────────
        elif name == "get_module_requirements":
            proj_id = arguments.get("project_identifier", "")
            mod_id = arguments.get("module_identifier", "")

            if not proj_id or not mod_id:
                return [TextContent(type="text", text=(
                    "Error: both project_identifier and module_identifier are required."
                ))]

            # Ensure projects are loaded
            if not _projects_cache:
                _projects_cache = client.list_projects()

            project = _find_by_identifier(_projects_cache, proj_id)
            if not project:
                return [TextContent(type="text", text=f"Project not found: '{proj_id}'")]

            project_key = project['id']
            _last_project_name = project['title']

            # Get modules if not cached for this project
            if project_key not in _modules_cache:
                modules = client.get_modules(project['url'])
                _modules_cache[project_key] = modules

            modules = _modules_cache.get(project_key, [])
            if not modules:
                return [TextContent(type="text", text=(
                    f"No modules found in '{project['title']}'. "
                    "Run get_modules first to see available modules."
                ))]

            module = _find_by_identifier(modules, mod_id)
            if not module:
                names = "\n".join(f"{i}. {m['title']}" for i, m in enumerate(modules, 1))
                return [TextContent(type="text", text=(
                    f"Module not found: '{mod_id}'\n\nAvailable modules:\n{names}"
                ))]

            _last_module_name = module['title']

            # Fetch requirements
            requirements = client.get_module_requirements(module['url'])
            _last_requirements = requirements

            if not requirements:
                return [TextContent(type="text", text=(
                    f"No requirements found in module '{module['title']}'.\n\n"
                    "The module may be empty or the requirements API returned no results."
                ))]

            lines = [
                f"# Requirements from '{module['title']}'",
                f"*(Project: {project['title']})*\n",
                f"Found **{len(requirements)}** requirement(s):\n",
            ]

            for i, req in enumerate(requirements, 1):
                # Show artifact type tag if available
                type_tag = f" [{req['artifact_type']}]" if req.get('artifact_type') else ""
                lines.append(f"{i}. **{req['title']}**{type_tag}")
                if req.get('id'):
                    lines.append(f"   - ID: `{req['id']}`")
                if req.get('url'):
                    lines.append(f"   - URL: `{req['url']}`")
                if req.get('description'):
                    desc = req['description']
                    if len(desc) > 200:
                        desc = desc[:200] + "..."
                    lines.append(f"   - Description: {desc}")
                if req.get('status'):
                    lines.append(f"   - Status: {req['status']}")
                # Show custom attributes
                custom = req.get('custom_attributes', {})
                if custom:
                    attrs_str = ", ".join(f"{k}: {v}" for k, v in custom.items())
                    lines.append(f"   - Attributes: {attrs_str}")

            lines.append(
                f"\nWould you like to save these requirements to a file? "
                f"Use `save_requirements` with format 'json', 'csv', or 'markdown'."
            )
            return [TextContent(type="text", text="\n".join(lines))]

        # ── save_requirements ─────────────────────────────────
        elif name == "save_requirements":
            if not _last_requirements:
                return [TextContent(type="text", text=(
                    "No requirements to save. "
                    "Use get_module_requirements first to fetch requirements."
                ))]

            fmt = arguments.get("format", "json")
            filename = arguments.get("filename", "")

            if not filename:
                safe_name = "".join(
                    c if c.isalnum() or c in ('_', '-') else '_'
                    for c in _last_module_name
                )[:50]
                ext = {'json': '.json', 'csv': '.csv', 'markdown': '.md'}.get(fmt, '.json')
                filename = f"requirements_{safe_name}{ext}"

            filepath = os.path.join(os.getcwd(), filename)

            if fmt == 'json':
                client.export_to_json(_last_requirements, filepath)
            elif fmt == 'csv':
                client.export_to_csv(_last_requirements, filepath)
            elif fmt == 'markdown':
                client.export_to_markdown(_last_requirements, filepath)
            else:
                return [TextContent(type="text", text=(
                    f"Unknown format: '{fmt}'. Use json, csv, or markdown."
                ))]

            return [TextContent(type="text", text=(
                f"Saved **{len(_last_requirements)}** requirements to `{filename}`\n\n"
                f"- Format: {fmt}\n"
                f"- Module: {_last_module_name}\n"
                f"- Project: {_last_project_name}"
            ))]

        # ── get_link_types ────────────────────────────────────
        elif name == "get_link_types":
            proj_id = arguments.get("project_identifier", "")
            if not proj_id:
                return [TextContent(type="text", text="Error: project_identifier is required.")]

            if not _projects_cache:
                _projects_cache = client.list_projects()

            project = _find_by_identifier(_projects_cache, proj_id)
            if not project:
                return [TextContent(type="text", text=f"Project not found: '{proj_id}'")]

            link_types = client.get_link_types(project['url'])
            if not link_types:
                return [TextContent(type="text", text=(
                    f"Could not retrieve link types for '{project['title']}'."
                ))]

            lines = [
                f"# Link Types in '{project['title']}'\n",
                f"Found **{len(link_types)}** link type(s):\n",
            ]
            for i, lt in enumerate(link_types, 1):
                lines.append(f"{i}. **{lt['name']}**")

            lines.append(
                "\nUse these names with `create_requirements` in the `link_type` field "
                "to create linked requirements."
            )
            return [TextContent(type="text", text="\n".join(lines))]

        # ── get_artifact_types ─────────────────────────────────
        elif name == "get_artifact_types":
            proj_id = arguments.get("project_identifier", "")
            if not proj_id:
                return [TextContent(type="text", text="Error: project_identifier is required.")]

            if not _projects_cache:
                _projects_cache = client.list_projects()

            project = _find_by_identifier(_projects_cache, proj_id)
            if not project:
                return [TextContent(type="text", text=f"Project not found: '{proj_id}'")]

            shapes = client.get_artifact_shapes(project['url'])
            if not shapes:
                return [TextContent(type="text", text=(
                    f"Could not retrieve artifact types for '{project['title']}'."
                ))]

            lines = [
                f"# Artifact Types in '{project['title']}'\n",
                f"Found **{len(shapes)}** type(s):\n",
            ]
            for i, s in enumerate(shapes, 1):
                lines.append(f"{i}. **{s['name']}**")

            lines.append(
                "\nUse these type names with `create_requirements` "
                "(e.g., 'System Requirement', 'Heading', 'User Requirement')."
            )
            return [TextContent(type="text", text="\n".join(lines))]

        # ── create_requirements ───────────────────────────────
        elif name == "create_requirements":
            proj_id = arguments.get("project_identifier", "")
            folder_name = arguments.get("folder_name", "")
            reqs_data = arguments.get("requirements", [])

            if not proj_id:
                return [TextContent(type="text", text="Error: project_identifier is required.")]
            if not folder_name:
                return [TextContent(type="text", text="Error: folder_name is required.")]
            if not reqs_data:
                return [TextContent(type="text", text="Error: requirements array is empty.")]

            if not _projects_cache:
                _projects_cache = client.list_projects()

            project = _find_by_identifier(_projects_cache, proj_id)
            if not project:
                return [TextContent(type="text", text=f"Project not found: '{proj_id}'")]

            # Get artifact type shapes for this project
            shapes = client.get_artifact_shapes(project['url'])
            shape_map = {s['name'].lower(): s['url'] for s in shapes}

            if not shape_map:
                return [TextContent(type="text", text=(
                    f"Could not retrieve artifact types for '{project['title']}'. "
                    "Check your permissions."
                ))]

            # Find or create the named folder (check cache first)
            folder = _folder_cache.get(folder_name)
            if not folder:
                folder = client.find_folder(project['url'], folder_name)
            if not folder:
                folder = client.create_folder(project['url'], folder_name)
                if not folder:
                    return [TextContent(type="text", text=(
                        f"Failed to create '{folder_name}' folder. "
                        "Check your write permissions for this project."
                    ))]
            # Cache for subsequent calls in the same session
            _folder_cache[folder_name] = folder

            folder_url = folder['url']

            # Resolve link types if any requirements have links
            link_type_map = {}
            has_links = any(req.get('link_type') for req in reqs_data)
            if has_links:
                link_types = client.get_link_types(project['url'])
                link_type_map = {lt['name'].lower(): lt['uri'] for lt in link_types}

            # Create each requirement
            created = []
            failed = []
            for req in reqs_data:
                title = req.get('title', '')
                content = req.get('content', '')
                artifact_type = req.get('artifact_type', 'System Requirement')

                # Find the shape URL for this artifact type
                shape_url = shape_map.get(artifact_type.lower())
                if not shape_url:
                    # Try partial match
                    for name_key, url_val in shape_map.items():
                        if artifact_type.lower() in name_key:
                            shape_url = url_val
                            break

                if not shape_url:
                    failed.append(f"'{title[:40]}' - unknown artifact type '{artifact_type}'")
                    continue

                # Resolve link type if specified
                link_uri = None
                link_target = req.get('link_to')
                link_type_name = req.get('link_type', '')
                if link_type_name and link_target:
                    link_uri = link_type_map.get(link_type_name.lower())
                    if not link_uri:
                        # Try partial match
                        for lt_name, lt_uri in link_type_map.items():
                            if link_type_name.lower() in lt_name:
                                link_uri = lt_uri
                                break

                result = client.create_requirement(
                    project_url=project['url'],
                    title=title,
                    content=content,
                    shape_url=shape_url,
                    folder_url=folder_url,
                    link_uri=link_uri,
                    link_target_url=link_target,
                )

                if result and 'error' not in result:
                    created.append(result)
                else:
                    error_detail = result.get('error', 'API error') if result else 'API error'
                    failed.append(f"'{title[:40]}' - {error_detail}")

            # Build response
            lines = [
                f"# Requirements Created in '{project['title']}'\n",
                f"Folder: **{folder_name}**\n",
                f"Created **{len(created)}** of {len(reqs_data)} requirement(s):\n",
            ]

            for i, r in enumerate(created, 1):
                lines.append(f"{i}. {r['title']}")
                if r.get('url'):
                    lines.append(f"   - URL: `{r['url']}`")

            if failed:
                lines.append(f"\n**Failed ({len(failed)}):**")
                for f_msg in failed:
                    lines.append(f"- {f_msg}")

            lines.append(
                f"\n**Next step:** Open DNG and review the requirements in the "
                f"'{folder_name}' folder. Move approved ones into the "
                f"appropriate module."
            )

            return [TextContent(type="text", text="\n".join(lines))]

        # ── update_requirement (DNG) ──────────────────────────
        elif name == "update_requirement":
            req_url = arguments.get("requirement_url", "")
            new_title = arguments.get("title", "")
            new_content = arguments.get("content", "")

            if not req_url:
                return [TextContent(type="text", text="Error: requirement_url is required.")]
            if not new_title and not new_content:
                return [TextContent(type="text", text="Error: provide at least one of title or content to update.")]

            result = client.update_requirement(
                requirement_url=req_url,
                title=new_title or None,
                content=new_content or None,
            )

            if result and 'error' not in result:
                updated_fields = []
                if new_title:
                    updated_fields.append("title")
                if new_content:
                    updated_fields.append("content")
                return [TextContent(type="text", text=(
                    f"# Requirement Updated\n\n"
                    f"- **Title:** {result['title']}\n"
                    f"- **URL:** `{result['url']}`\n"
                    f"- **Updated:** {', '.join(updated_fields)}"
                ))]
            else:
                error_detail = result.get('error', '') if result else ''
                return [TextContent(type="text", text=(
                    f"Failed to update requirement.\n"
                    f"{error_detail}\n\n"
                    "This may be a permissions issue or a version conflict (another user edited it)."
                ))]

        # ── create_baseline (DNG CM) ──────────────────────────
        elif name == "create_baseline":
            proj_id = arguments.get("project_identifier", "")
            bl_title = arguments.get("title", "")
            bl_desc = arguments.get("description", "")

            if not proj_id or not bl_title:
                return [TextContent(type="text", text="Error: project_identifier and title are required.")]

            if not _projects_cache:
                _projects_cache = client.list_projects()

            project = _find_by_identifier(_projects_cache, proj_id)
            if not project:
                return [TextContent(type="text", text=f"Project not found: '{proj_id}'")]

            result = client.create_baseline(
                project_url=project['url'],
                title=bl_title,
                description=bl_desc,
            )

            if result and 'error' not in result:
                return [TextContent(type="text", text=(
                    f"# Baseline Created\n\n"
                    f"- **Title:** {result['title']}\n"
                    f"- **Project:** {project['title']}\n"
                    f"- **Stream:** {result.get('stream_title', 'N/A')}\n"
                    f"- **Status:** Processing (baseline creation is async)\n\n"
                    f"The baseline is being created in the background. "
                    f"Use `list_baselines` to confirm it appears."
                ))]
            else:
                error_detail = result.get('error', '') if result else ''
                return [TextContent(type="text", text=(
                    f"Failed to create baseline for '{project['title']}'.\n"
                    f"{error_detail}"
                ))]

        # ── list_baselines (DNG CM) ──────────────────────────
        elif name == "list_baselines":
            proj_id = arguments.get("project_identifier", "")
            if not proj_id:
                return [TextContent(type="text", text="Error: project_identifier is required.")]

            if not _projects_cache:
                _projects_cache = client.list_projects()

            project = _find_by_identifier(_projects_cache, proj_id)
            if not project:
                return [TextContent(type="text", text=f"Project not found: '{proj_id}'")]

            baselines = client.list_baselines(project['url'])
            if not baselines:
                return [TextContent(type="text", text=(
                    f"No baselines found for '{project['title']}'.\n"
                    "Use `create_baseline` to create one."
                ))]

            lines = [
                f"# Baselines in '{project['title']}'\n",
                f"Found **{len(baselines)}** baseline(s):\n",
            ]
            for i, bl in enumerate(baselines, 1):
                lines.append(f"{i}. **{bl['title']}**")
                if bl.get('url'):
                    lines.append(f"   - URL: `{bl['url']}`")
                if bl.get('created'):
                    lines.append(f"   - Created: {bl['created']}")

            return [TextContent(type="text", text="\n".join(lines))]

        # ── create_task (EWM) ─────────────────────────────────
        elif name == "create_task":
            ewm_proj = arguments.get("ewm_project", "")
            title = arguments.get("title", "")
            description = arguments.get("description", "")
            requirement_url = arguments.get("requirement_url", "")

            if not ewm_proj or not title:
                return [TextContent(type="text", text="Error: ewm_project and title are required.")]

            # Ensure EWM projects are loaded
            if not _ewm_projects_cache:
                _ewm_projects_cache = client.list_ewm_projects()

            if not _ewm_projects_cache:
                return [TextContent(type="text", text=(
                    "No EWM projects found. Ensure the server has a /ccm context root "
                    "and your credentials have EWM access."
                ))]

            project = _find_by_identifier(_ewm_projects_cache, ewm_proj)
            if not project:
                names = "\n".join(f"{i}. {p['title']}" for i, p in enumerate(_ewm_projects_cache, 1))
                return [TextContent(type="text", text=(
                    f"EWM project not found: '{ewm_proj}'\n\nAvailable EWM projects:\n{names}"
                ))]

            result = client.create_ewm_task(
                service_provider_url=project['url'],
                title=title,
                description=description,
                requirement_url=requirement_url or None,
            )

            if result and 'error' not in result:
                link_note = ""
                if requirement_url:
                    link_note = f"\n- Linked to requirement: `{requirement_url}`"
                return [TextContent(type="text", text=(
                    f"# Task Created in EWM\n\n"
                    f"- **Title:** {result['title']}\n"
                    f"- **Project:** {project['title']}\n"
                    f"- **URL:** {result['url']}{link_note}\n\n"
                    f"The task has been created with `[AI Generated]` prefix. "
                    f"A project lead can assign it to an iteration and developer."
                ))]
            else:
                error_detail = result.get('error', '') if result else ''
                return [TextContent(type="text", text=(
                    f"Failed to create task in '{project['title']}'.\n"
                    f"{error_detail}\n\n"
                    "This may be a permissions issue — try a different EWM project."
                ))]

        # ── create_test_case (ETM) ────────────────────────────
        elif name == "create_test_case":
            etm_proj = arguments.get("etm_project", "")
            title = arguments.get("title", "")
            description = arguments.get("description", "")
            requirement_url = arguments.get("requirement_url", "")

            if not etm_proj or not title:
                return [TextContent(type="text", text="Error: etm_project and title are required.")]

            # Ensure ETM projects are loaded
            if not _etm_projects_cache:
                _etm_projects_cache = client.list_etm_projects()

            if not _etm_projects_cache:
                return [TextContent(type="text", text=(
                    "No ETM projects found. Ensure the server has a /qm context root "
                    "and your credentials have ETM access."
                ))]

            project = _find_by_identifier(_etm_projects_cache, etm_proj)
            if not project:
                names = "\n".join(f"{i}. {p['title']}" for i, p in enumerate(_etm_projects_cache, 1))
                return [TextContent(type="text", text=(
                    f"ETM project not found: '{etm_proj}'\n\nAvailable ETM projects:\n{names}"
                ))]

            result = client.create_test_case(
                service_provider_url=project['url'],
                title=title,
                description=description,
                requirement_url=requirement_url or None,
            )

            if result and 'error' not in result:
                link_note = ""
                if requirement_url:
                    link_note = f"\n- Validates requirement: `{requirement_url}`"
                return [TextContent(type="text", text=(
                    f"# Test Case Created in ETM\n\n"
                    f"- **Title:** {result['title']}\n"
                    f"- **Project:** {project['title']}\n"
                    f"- **URL:** {result['url']}{link_note}\n\n"
                    f"Use this URL with `create_test_result` to record pass/fail results."
                ))]
            else:
                error_detail = result.get('error', '') if result else ''
                return [TextContent(type="text", text=(
                    f"Failed to create test case in '{project['title']}'.\n"
                    f"{error_detail}\n\n"
                    "This may be a permissions issue — try a different ETM project."
                ))]

        # ── create_test_result (ETM) ──────────────────────────
        elif name == "create_test_result":
            etm_proj = arguments.get("etm_project", "")
            test_case_url = arguments.get("test_case_url", "")
            status = arguments.get("status", "passed")
            title = arguments.get("title", "")

            if not etm_proj or not test_case_url or not status:
                return [TextContent(type="text", text=(
                    "Error: etm_project, test_case_url, and status are required."
                ))]

            # Auto-generate title if not provided
            if not title:
                title = f"Test Result - {status.capitalize()}"

            # Ensure ETM projects are loaded
            if not _etm_projects_cache:
                _etm_projects_cache = client.list_etm_projects()

            project = _find_by_identifier(_etm_projects_cache, etm_proj)
            if not project:
                names = "\n".join(f"{i}. {p['title']}" for i, p in enumerate(_etm_projects_cache, 1))
                return [TextContent(type="text", text=(
                    f"ETM project not found: '{etm_proj}'\n\nAvailable ETM projects:\n{names}"
                ))]

            result = client.create_test_result(
                service_provider_url=project['url'],
                title=title,
                test_case_url=test_case_url,
                status=status,
            )

            if result and 'error' not in result:
                status_emoji = {"passed": "PASS", "failed": "FAIL", "blocked": "BLOCKED",
                                "incomplete": "INCOMPLETE", "error": "ERROR"}.get(status.lower(), status.upper())
                return [TextContent(type="text", text=(
                    f"# Test Result Recorded in ETM\n\n"
                    f"- **Result:** {status_emoji}\n"
                    f"- **Title:** {result['title']}\n"
                    f"- **Project:** {project['title']}\n"
                    f"- **Reports on:** `{test_case_url}`\n"
                    f"- **URL:** {result['url']}"
                ))]
            else:
                error_detail = result.get('error', '') if result else ''
                return [TextContent(type="text", text=(
                    f"Failed to create test result in '{project['title']}'.\n"
                    f"{error_detail}\n\n"
                    "This may be a permissions issue — try a different ETM project."
                ))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        import traceback
        return [TextContent(type="text", text=(
            f"Error in {name}: {str(e)}\n\n{traceback.format_exc()}"
        ))]


# ── Main ──────────────────────────────────────────────────────

async def main():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
