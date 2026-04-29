#!/usr/bin/env python3
"""
DOORS Next AI Agent — MCP Server
Provides tools for AI assistants to interact with IBM Engineering Lifecycle Management (ELM)
Covers DNG (requirements), EWM (work items), ETM (test management), and SCM (change-sets).

Tools (33):
  Existing (21):
    1.  connect_to_elm              - Connect with credentials
    2.  list_projects               - List DNG/EWM/ETM projects (domain parameter)
    3.  get_modules                 - Get modules from a DNG project
    4.  get_module_requirements     - Get requirements from a module
    5.  save_requirements           - Save requirements to a file (JSON/CSV/Markdown)
    6.  search_requirements         - Full-text search across all artifacts in a project
    7.  get_artifact_types          - Discover artifact types for a DNG project
    8.  get_link_types              - Discover link types for a DNG project
    9.  create_requirements         - Create requirements with links in a descriptive folder
   10. update_requirement          - Update an existing requirement's title and/or content
   11. create_baseline             - Create a baseline snapshot of a DNG project
   12. list_baselines              - List existing baselines for a DNG project
   13. compare_baselines           - Compare baseline vs current stream (shows diff)
   14. extract_pdf                 - Extract text from a PDF file for import into DNG
   15. create_task                 - Create an EWM Task with optional DNG requirement link
   16. create_test_case            - Create an ETM Test Case with optional DNG requirement link
   17. create_test_result          - Create an ETM Test Result (pass/fail) for a test case
   18. list_global_configurations  - List all global configs (streams/baselines) from GCM
   19. list_global_components      - List all components across DNG/EWM/ETM from GCM
   20. get_global_config_details   - Get details + contributions for a global configuration
   21. generate_chart              - Render a bar/hbar/pie/line chart as PNG (visualize ELM data)

  New (12 — OSLC + SCM/Reviews):
   22. get_attribute_definitions   - Discover DNG attribute predicates + allowed enum values
   23. update_requirement_attributes - Set arbitrary DNG attributes (Status, Priority, etc.)
   24. update_work_item            - PUT-with-If-Match arbitrary fields on an EWM WI
   25. transition_work_item        - Move WI through workflow via _action= query param
   26. query_work_items            - OSLC CM query (oslc.where / oslc.select)
   27. create_link                 - Generic OSLC link between two existing artifacts
   28. create_defect               - Create EWM Defect (auto-resolves filedAgainst category)
   29. scm_list_projects           - SCM service-providers from /ccm/oslc-scm/catalog
   30. scm_list_changesets         - Recent change-sets via TRS feed
   31. scm_get_changeset           - Single change-set + linked work items
   32. scm_get_workitem_changesets - Change-sets on a given WI
   33. review_get                  - Review-relevant WI fields (approvals, change-sets, etc.)
   34. review_list_open            - Open review-typed WIs in a project
"""

import os
import sys
import logging
import asyncio
from typing import Any, Optional, List, Dict

# MCP stdio servers must log to stderr, never stdout
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("doors-next")
from mcp.server import Server
from mcp.types import (
    Tool, TextContent,
    Resource, ResourceTemplate, BlobResourceContents, TextResourceContents,
    Prompt, PromptMessage, PromptArgument,
)
import mcp.server.stdio
from dotenv import load_dotenv
from doors_client import DOORSNextClient

load_dotenv()

# Bumped on each release. Used by the GitHub-release update check below
# and surfaced in the connect_to_elm response so users know which version
# they're running.
__version__ = "0.1.0"
GITHUB_REPO = "brettscharm/elm-mcp"

app = Server("doors-next-server")

# Update-check state — populated lazily on first tool call so we don't
# block server startup on a network call. None means "not checked yet";
# empty string means "checked, no update available"; non-empty means
# "checked, here's the notice to surface to the user once".
_update_notice: Optional[str] = None
_update_notice_shown: bool = False


def _check_for_update() -> str:
    """Hit the GitHub releases API and return a one-line update notice
    if a newer version is available. Empty string otherwise. Fails silent
    on any error so an offline user is never blocked."""
    global _update_notice
    if _update_notice is not None:
        return _update_notice
    _update_notice = ""  # default: no notice
    try:
        import urllib.request, json as _json
        req = urllib.request.Request(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": f"elm-mcp/{__version__}"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        latest = (data.get("tag_name") or "").lstrip("v")
        if latest and latest != __version__:
            _update_notice = (
                f"\n\n> ELM MCP v{latest} is available (you're on v{__version__}). "
                f"Update with `smithery update elm-mcp` or `git pull` in your clone."
            )
    except Exception:
        # Offline / rate-limited / repo not yet released — just stay quiet.
        pass
    return _update_notice


def _maybe_append_update_notice(text: str) -> str:
    """Append the update notice exactly once per session, on the first
    tool that calls this. Avoids spamming every response."""
    global _update_notice_shown
    if _update_notice_shown:
        return text
    notice = _check_for_update()
    if notice:
        _update_notice_shown = True
        return text + notice
    return text

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


_client_error: str = ""


def _get_or_create_client() -> Optional[DOORSNextClient]:
    """Get existing client or try to create one from .env.

    Sets _client_error with the reason if connection fails.
    """
    global _client, _client_error
    if _client is not None:
        return _client

    # Read ELM_* (preferred) with DOORS_* fallback for legacy installs.
    base_url = os.getenv("ELM_URL") or os.getenv("DOORS_URL")
    username = os.getenv("ELM_USERNAME") or os.getenv("DOORS_USERNAME")
    password = os.getenv("ELM_PASSWORD") or os.getenv("DOORS_PASSWORD")

    if not all([base_url, username, password]):
        missing = []
        if not base_url:
            missing.append("ELM_URL")
        if not username:
            missing.append("ELM_USERNAME")
        if not password:
            missing.append("ELM_PASSWORD")
        _client_error = f"Missing .env variables: {', '.join(missing)}"
        return None

    # The client itself normalizes the URL (strips /rm, /ccm, /qm, /gc, /jts
    # variants and re-attaches per-domain paths). Don't mangle it here.
    client = DOORSNextClient(base_url.strip(), username, password)
    auth_result = client.authenticate()
    if auth_result['success']:
        _client = client
        _client_error = ""
        return _client

    _client_error = auth_result['error']
    logger.warning("Auto-connect from .env failed: %s", _client_error)
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


# ── Prompts ───────────────────────────────────────────────────

@app.list_prompts()
async def list_prompts() -> list[Prompt]:
    return [
        Prompt(
            name="generate-requirements",
            description=(
                "Generate IEEE 29148-compliant requirements for a system or feature. "
                "Walks through a structured interview, generates requirements with "
                "measurable acceptance criteria, and pushes to DNG."
            ),
            arguments=[
                PromptArgument(
                    name="system_description",
                    description="What system or feature are these requirements for?",
                    required=True,
                ),
                PromptArgument(
                    name="requirement_type",
                    description="Type of requirements: stakeholder, system, software, hardware, security, performance",
                    required=False,
                ),
                PromptArgument(
                    name="standards",
                    description="Applicable standards or regulations (e.g., DO-178C, ISO 26262, MIL-STD-882)",
                    required=False,
                ),
                PromptArgument(
                    name="count",
                    description="How many requirements: 'few' (5-10) or 'comprehensive' (20+)",
                    required=False,
                ),
            ],
        ),
        Prompt(
            name="full-lifecycle",
            description=(
                "Create a complete lifecycle: Requirements in DNG -> Tasks in EWM -> "
                "Test Cases in ETM, all cross-linked for full traceability."
            ),
            arguments=[
                PromptArgument(
                    name="system_description",
                    description="What system or feature to build the lifecycle for?",
                    required=True,
                ),
                PromptArgument(
                    name="dng_project",
                    description="DNG project name or number for requirements",
                    required=False,
                ),
                PromptArgument(
                    name="ewm_project",
                    description="EWM project name or number for tasks",
                    required=False,
                ),
                PromptArgument(
                    name="etm_project",
                    description="ETM project name or number for test cases",
                    required=False,
                ),
            ],
        ),
        Prompt(
            name="import-pdf",
            description=(
                "Import a PDF document into DNG as structured requirements. "
                "Extracts text, parses into requirements, previews, and pushes to DNG. "
                "Supports re-import with diff detection for updated PDFs."
            ),
            arguments=[
                PromptArgument(
                    name="file_path",
                    description="Absolute path to the PDF file",
                    required=True,
                ),
                PromptArgument(
                    name="project",
                    description="DNG project name or number",
                    required=False,
                ),
            ],
        ),
        Prompt(
            name="review-requirements",
            description=(
                "Read requirements from a DNG module and review them for quality: "
                "checks for ambiguity, missing acceptance criteria, testability, "
                "and IEEE 29148 compliance."
            ),
            arguments=[
                PromptArgument(
                    name="project",
                    description="DNG project name or number",
                    required=True,
                ),
                PromptArgument(
                    name="module",
                    description="Module name or number to review",
                    required=True,
                ),
            ],
        ),
    ]


@app.get_prompt()
async def get_prompt(name: str, arguments: dict | None = None) -> list[PromptMessage]:
    args = arguments or {}

    if name == "generate-requirements":
        system_desc = args.get("system_description", "")
        req_type = args.get("requirement_type", "system")
        standards = args.get("standards", "")
        count = args.get("count", "10-15")

        standards_note = f"\n\nApplicable standards: {standards}. Include compliance references in each requirement." if standards else ""

        return [PromptMessage(
            role="user",
            content=TextContent(type="text", text=(
                f"Generate {req_type} requirements for the following system:\n\n"
                f"{system_desc}\n\n"
                f"Target count: {count} requirements.{standards_note}\n\n"
                f"Follow IEEE 29148 / INCOSE best practices:\n"
                f"- Use 'shall' for mandatory behavior\n"
                f"- Each requirement must be atomic and testable\n"
                f"- Include measurable acceptance criteria (numeric thresholds, time limits)\n"
                f"- Group under Heading artifacts by functional area\n"
                f"- Specify condition -> action -> expected result\n\n"
                f"First connect to ELM (if not connected), then:\n"
                f"1. Call get_artifact_types to get valid type names\n"
                f"2. Generate the requirements following the rules above\n"
                f"3. Present in a preview table with Type, Title, and Acceptance Criteria columns\n"
                f"4. Wait for my approval before pushing to DNG"
            )),
        )]

    elif name == "full-lifecycle":
        system_desc = args.get("system_description", "")
        dng = args.get("dng_project", "")
        ewm = args.get("ewm_project", "")
        etm = args.get("etm_project", "")

        project_notes = ""
        if dng:
            project_notes += f"\nDNG project: {dng}"
        if ewm:
            project_notes += f"\nEWM project: {ewm}"
        if etm:
            project_notes += f"\nETM project: {etm}"

        return [PromptMessage(
            role="user",
            content=TextContent(type="text", text=(
                f"Create a full engineering lifecycle for:\n\n{system_desc}\n"
                f"{project_notes}\n\n"
                f"Phase 1: Generate requirements in DNG (IEEE 29148 compliant, with acceptance criteria)\n"
                f"Phase 2: Create implementation tasks in EWM linked to requirements\n"
                f"Phase 3: Create test cases in ETM linked to requirements (with preconditions, steps, pass/fail criteria)\n\n"
                f"At each phase:\n"
                f"- Preview what will be created in a table\n"
                f"- Wait for my approval before pushing\n"
                f"- Use the requirement URLs from Phase 1 for cross-linking in Phases 2 and 3"
            )),
        )]

    elif name == "import-pdf":
        file_path = args.get("file_path", "")
        project = args.get("project", "")

        return [PromptMessage(
            role="user",
            content=TextContent(type="text", text=(
                f"Import this PDF into DNG as structured requirements:\n\n"
                f"File: {file_path}\n"
                f"{'Project: ' + project if project else 'Ask me which project to use.'}\n\n"
                f"Steps:\n"
                f"1. Call extract_pdf to get the text\n"
                f"2. Parse into structured requirements (identify headings, sections, individual requirements)\n"
                f"3. Call get_artifact_types to get valid type names\n"
                f"4. Present in a preview table\n"
                f"5. Wait for my approval before pushing to DNG\n"
                f"6. After creation, offer to create a baseline snapshot"
            )),
        )]

    elif name == "review-requirements":
        project = args.get("project", "")
        module = args.get("module", "")

        return [PromptMessage(
            role="user",
            content=TextContent(type="text", text=(
                f"Review the requirements in project '{project}', module '{module}' for quality.\n\n"
                f"1. Call get_module_requirements to read all requirements\n"
                f"2. Analyze each requirement against IEEE 29148 criteria:\n"
                f"   - Uses 'shall' for mandatory behavior?\n"
                f"   - Atomic (one testable behavior)?\n"
                f"   - Has measurable acceptance criteria?\n"
                f"   - Unambiguous (no vague terms like 'fast', 'reliable')?\n"
                f"   - Verifiable and testable?\n"
                f"3. Present a quality report:\n"
                f"   - Overall score (% compliant)\n"
                f"   - Table of issues found per requirement\n"
                f"   - Suggested rewrites for non-compliant requirements\n"
                f"4. Ask if I want to update the non-compliant requirements in DNG"
            )),
        )]

    raise ValueError(f"Unknown prompt: {name}")


# ── Resources ────────────────────────────────────────────────

@app.list_resource_templates()
async def list_resource_templates() -> list[ResourceTemplate]:
    return [
        ResourceTemplate(
            uriTemplate="elm://projects/{domain}",
            name="elm-projects",
            description="List all projects in an ELM domain (dng, ewm, or etm)",
            mimeType="application/json",
        ),
        ResourceTemplate(
            uriTemplate="elm://project/{project_name}/modules",
            name="elm-modules",
            description="List modules in a DNG project",
            mimeType="application/json",
        ),
        ResourceTemplate(
            uriTemplate="elm://project/{project_name}/module/{module_name}/requirements",
            name="elm-requirements",
            description="Get all requirements from a specific module",
            mimeType="application/json",
        ),
    ]


@app.list_resources()
async def list_resources() -> list[Resource]:
    """List static resources — connected project info if available."""
    resources = []
    client = _get_or_create_client()
    if client and _projects_cache:
        resources.append(Resource(
            uri="elm://connection/status",
            name="ELM Connection Status",
            description=f"Connected to {client.base_url} with {len(_projects_cache)} DNG projects",
            mimeType="application/json",
        ))
    return resources


@app.read_resource()
async def read_resource(uri: str) -> str:
    import json as _json

    # elm://connection/status
    if uri == "elm://connection/status":
        client = _get_or_create_client()
        if client:
            return _json.dumps({
                "connected": True,
                "server": client.base_url,
                "dng_projects": len(_projects_cache),
                "ewm_projects": len(_ewm_projects_cache),
                "etm_projects": len(_etm_projects_cache),
            }, indent=2)
        return _json.dumps({"connected": False, "error": _client_error})

    # elm://projects/{domain}
    if uri.startswith("elm://projects/"):
        domain = uri.split("/")[-1]
        client = _get_or_create_client()
        if not client:
            return _json.dumps({"error": "Not connected to ELM"})

        if domain == "ewm":
            projects = client.list_ewm_projects()
        elif domain == "etm":
            projects = client.list_etm_projects()
        else:
            projects = client.list_projects()

        return _json.dumps([{"title": p["title"], "id": p.get("id", "")} for p in projects], indent=2)

    # elm://project/{name}/modules
    if "/modules" in uri and uri.startswith("elm://project/"):
        parts = uri.replace("elm://project/", "").split("/")
        project_name = parts[0]
        client = _get_or_create_client()
        if not client:
            return _json.dumps({"error": "Not connected to ELM"})

        if not _projects_cache:
            _projects_cache.extend(client.list_projects())

        project = _find_by_identifier(_projects_cache, project_name)
        if not project:
            return _json.dumps({"error": f"Project not found: {project_name}"})

        modules = client.get_modules(project["url"])
        return _json.dumps([{"title": m["title"], "id": m.get("id", "")} for m in modules], indent=2)

    # elm://project/{name}/module/{module}/requirements
    if "/requirements" in uri and "/module/" in uri:
        parts = uri.replace("elm://project/", "").split("/")
        # parts: [project_name, "module", module_name, "requirements"]
        project_name = parts[0]
        module_name = parts[2] if len(parts) > 2 else ""
        client = _get_or_create_client()
        if not client:
            return _json.dumps({"error": "Not connected to ELM"})

        if not _projects_cache:
            _projects_cache.extend(client.list_projects())

        project = _find_by_identifier(_projects_cache, project_name)
        if not project:
            return _json.dumps({"error": f"Project not found: {project_name}"})

        project_key = project["id"]
        if project_key not in _modules_cache:
            _modules_cache[project_key] = client.get_modules(project["url"])

        modules = _modules_cache.get(project_key, [])
        module = _find_by_identifier(modules, module_name)
        if not module:
            return _json.dumps({"error": f"Module not found: {module_name}"})

        reqs = client.get_module_requirements(module["url"])
        return _json.dumps([{
            "title": r.get("title", ""),
            "id": r.get("id", ""),
            "url": r.get("url", ""),
            "artifact_type": r.get("artifact_type", ""),
            "description": (r.get("description") or "")[:200],
        } for r in reqs], indent=2)

    return _json.dumps({"error": f"Unknown resource: {uri}"})


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
            name="create_module",
            description=(
                "Create a new DOORS Next module (a navigable document that holds requirements). "
                "Use this when the user wants a fresh module to house requirements. "
                "After creating the module, call create_requirements with module_name set "
                "to bind requirements into it. Returns the module URL."
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
                        "description": "Module title"
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional module description"
                    }
                },
                "required": ["project_identifier", "title"]
            }
        ),
        Tool(
            name="create_requirements",
            description=(
                "Create requirements in a DOORS Next project AND bind them to a module so they "
                "appear in DNG's module/document view. STRONGLY PREFER providing module_name — "
                "module_name is what makes requirements visible as a navigable document; folder-only "
                "requirements (no module_name) end up as orphan artifacts most users can't find. "
                "MUST call get_artifact_types first to get valid type names for this project. "
                "Returns created requirement URLs needed by create_task and create_test_case."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_identifier": {
                        "type": "string",
                        "description": "Project number or name"
                    },
                    "module_name": {
                        "type": "string",
                        "description": "Module name to bind requirements into. If a module with this name exists it's reused; otherwise it's created. STRONGLY RECOMMENDED — without it, requirements are orphans in a folder."
                    },
                    "folder_name": {
                        "type": "string",
                        "description": "Optional folder for the underlying base artifacts (DNG stores every artifact in a folder, even module-bound ones). Defaults to a folder named after the module."
                    },
                    "requirements": {
                        "type": "array",
                        "description": "Array of requirements to create",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {
                                    "type": "string",
                                    "description": "Requirement title"
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
                "required": ["project_identifier", "requirements"]
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
            name="search_requirements",
            description=(
                "Full-text search across all artifacts in a DNG project. "
                "Finds requirements, modules, and other artifacts matching the search terms. "
                "Use this to quickly find specific requirements by keyword."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_identifier": {
                        "type": "string",
                        "description": "DNG project number or name"
                    },
                    "query": {
                        "type": "string",
                        "description": "Search terms (e.g., 'security', 'power backup', 'login')"
                    }
                },
                "required": ["project_identifier", "query"]
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
                        "description": "Baseline name (e.g., 'V1 Import Baseline')."
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
                        "description": "Task title"
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
                        "description": "Test case title"
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
        Tool(
            name="list_global_configurations",
            description=(
                "List all global configurations from GCM (Global Configuration Management). "
                "Shows streams and baselines that span across DNG, EWM, and ETM. "
                "These are the top-level configurations that tie together components from all ELM apps."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="list_global_components",
            description=(
                "List all components registered in GCM across DNG, EWM, and ETM. "
                "Shows every component in the ELM deployment with its project area and configuration URLs."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_global_config_details",
            description=(
                "Get details for a specific global configuration from GCM. "
                "Shows the configuration type (stream/baseline), component, and which "
                "DNG/EWM/ETM local configurations contribute to it. "
                "Use list_global_configurations first to get config URLs."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "config_url": {
                        "type": "string",
                        "description": "URL of the global configuration (from list_global_configurations)"
                    }
                },
                "required": ["config_url"]
            }
        ),
        Tool(
            name="generate_chart",
            description=(
                "Generate a chart (bar, horizontal bar, pie, or line) from data and save it as a PNG. "
                "Use this to visualize ELM data — e.g., requirements by status, test results pass/fail, "
                "tasks by priority, requirements per module. The host LLM should aggregate the data first "
                "(from get_module_requirements, search_requirements, etc.), then call this tool with the "
                "summary numbers. Returns the absolute path to the saved PNG."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "chart_type": {
                        "type": "string",
                        "enum": ["bar", "hbar", "pie", "line"],
                        "description": "Chart type: 'bar' (vertical), 'hbar' (horizontal — best for long category names), 'pie', or 'line'"
                    },
                    "title": {
                        "type": "string",
                        "description": "Chart title shown at the top"
                    },
                    "labels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Category labels (x-axis for bar/line, slice labels for pie)"
                    },
                    "values": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Numeric values, one per label (same length as labels)"
                    },
                    "x_label": {
                        "type": "string",
                        "description": "X-axis label (ignored for pie). Optional."
                    },
                    "y_label": {
                        "type": "string",
                        "description": "Y-axis label (ignored for pie). Optional."
                    },
                    "output_filename": {
                        "type": "string",
                        "description": "Output filename (no path, no extension). Optional — auto-generated from title + timestamp if omitted."
                    }
                },
                "required": ["chart_type", "title", "labels", "values"]
            }
        ),
        # ── DNG: arbitrary attribute updates ────────────────────
        Tool(
            name="get_attribute_definitions",
            description=(
                "List all DNG attribute property definitions for a project — name, "
                "predicate URI, value type, and (for enums) allowed values. "
                "Use this BEFORE update_requirement_attributes to see what attributes "
                "exist on the project's artifact shapes (e.g. Priority, Status, Stability) "
                "and what enum labels are valid. "
                "Call list_projects with domain='dng' first to find the project."
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
            name="update_requirement_attributes",
            description=(
                "Set arbitrary DNG attributes on a requirement (e.g. Priority='High', "
                "Status='Approved'). Uses optimistic locking (GET ETag → PUT If-Match). "
                "Pass attribute keys by friendly name OR full predicate URI. For enum-valued "
                "attributes, pass the human-readable label (resolved via the project's "
                "shape definitions). Call get_attribute_definitions first to discover "
                "valid attribute names and their allowed values. "
                "NOTE: this tool updates standalone artifact attributes; module-bound "
                "writes are restricted on this DNG server (see add_to_module)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "requirement_url": {
                        "type": "string",
                        "description": "Full URL of the requirement (from get_module_requirements / create_requirements)"
                    },
                    "attributes": {
                        "type": "object",
                        "description": "Dict mapping attribute name (e.g. 'Priority') or predicate URI to its new value (string literal, resource URI, or enum label like 'High')",
                        "additionalProperties": True
                    }
                },
                "required": ["requirement_url", "attributes"]
            }
        ),
        # ── EWM: work-item operations ──────────────────────────
        Tool(
            name="update_work_item",
            description=(
                "Update arbitrary fields on an EWM work item via PUT-with-If-Match. "
                "Friendly aliases: title, description, owner (user URI), severity / priority "
                "(enum URIs), subject (tag list), filedAgainst (category URI). "
                "Predicate URIs are also accepted. To change state, use transition_work_item."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "workitem_url": {
                        "type": "string",
                        "description": "Full work-item URL (e.g. .../resource/itemName/com.ibm.team.workitem.WorkItem/3583 — output from create_task)"
                    },
                    "fields": {
                        "type": "object",
                        "description": "Dict of {field_name: new_value}. Friendly names: title, description, owner, severity, priority, subject, filedAgainst. Resource-valued fields take URIs.",
                        "additionalProperties": True
                    }
                },
                "required": ["workitem_url", "fields"]
            }
        ),
        Tool(
            name="transition_work_item",
            description=(
                "Move an EWM work item through its workflow (e.g. New → In Development → Done). "
                "Looks up the project's workflow actions and PUTs with `?_action=<actionId>`. "
                "Pass `target_state` as a state title ('In Development', 'Done') or identifier. "
                "On servers where multiple actions can reach the same state, the tool tries "
                "ranked candidates until one succeeds — the response includes which action was used."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "workitem_url": {
                        "type": "string",
                        "description": "Full work-item URL (from create_task / query_work_items)"
                    },
                    "target_state": {
                        "type": "string",
                        "description": "Desired state name (e.g. 'In Development', 'Done', 'New')"
                    }
                },
                "required": ["workitem_url", "target_state"]
            }
        ),
        Tool(
            name="query_work_items",
            description=(
                "Query EWM work items via OSLC CM. Use this to find work items matching "
                "filters such as `oslc_cm:closed=false` or `dcterms:creator=\"<user-uri>\"`. "
                "Supports OSLC where syntax. Resolves project name → project area, then "
                "calls /ccm/oslc/contexts/<paId>/workitems?oslc.where=...&oslc.select=...&oslc.pageSize=N. "
                "Use list_projects domain='ewm' to find the EWM project name."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ewm_project": {
                        "type": "string",
                        "description": "EWM project number or name"
                    },
                    "where": {
                        "type": "string",
                        "description": "OSLC where clause (e.g. 'oslc_cm:closed=false', 'rtc_cm:type=\"...task\"')"
                    },
                    "select": {
                        "type": "string",
                        "description": "OSLC select clause (default '*')"
                    },
                    "page_size": {
                        "type": "integer",
                        "description": "Max items per page (default 25)"
                    }
                },
                "required": ["ewm_project"]
            }
        ),
        # ── Cross-domain link creation ─────────────────────────
        Tool(
            name="create_link",
            description=(
                "Create an OSLC link of any type between two existing artifacts. "
                "Auto-detects source domain (DNG / EWM / ETM) from the URL prefix and uses "
                "GET-ETag → PUT-If-Match on the source. Pass the source URL, the link type "
                "URI (e.g. a Satisfies link from get_link_types, or http://open-services.net/ns/cm#implementsRequirement), "
                "and the target URL. NOTE: DNG normalizes custom link-type predicates after PUT."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "source_url": {
                        "type": "string",
                        "description": "Full URL of the source artifact (DNG req, EWM workitem, or ETM resource)"
                    },
                    "link_type_uri": {
                        "type": "string",
                        "description": "Link-type URI — for DNG, a custom LT_ URL from get_link_types or a standard OSLC predicate (e.g. http://open-services.net/ns/rm#satisfies)"
                    },
                    "target_url": {
                        "type": "string",
                        "description": "Full URL of the target artifact"
                    }
                },
                "required": ["source_url", "link_type_uri", "target_url"]
            }
        ),
        # ── EWM: defect creation ───────────────────────────────
        Tool(
            name="create_defect",
            description=(
                "Create an EWM Defect work item. Resolves the project category for "
                "`rtc_cm:filedAgainst` automatically (process rules typically reject the "
                "Unassigned default — this tool picks the first concrete category). Severity "
                "can be a friendly name (Minor/Moderate/Major/Critical) or a literal URI. "
                "Optional cross-links: requirement_url (calm:affectedByDefect) and "
                "test_case_url (oslc_cm:relatedTestCase). "
                "Use list_projects domain='ewm' first."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ewm_project": {
                        "type": "string",
                        "description": "EWM project number or name"
                    },
                    "title": {
                        "type": "string",
                        "description": "Defect title"
                    },
                    "description": {
                        "type": "string",
                        "description": "Description / repro steps"
                    },
                    "severity": {
                        "type": "string",
                        "description": "Optional severity label (Minor / Moderate / Major / Critical / Blocker / Unclassified)"
                    },
                    "requirement_url": {
                        "type": "string",
                        "description": "Optional DNG requirement URL — links via calm:affectedByDefect"
                    },
                    "test_case_url": {
                        "type": "string",
                        "description": "Optional ETM test case URL — links via oslc_cm:relatedTestCase"
                    }
                },
                "required": ["ewm_project", "title"]
            }
        ),
        # ── SCM (read-only) ────────────────────────────────────
        Tool(
            name="scm_list_projects",
            description=(
                "List all CCM/EWM project areas that have an SCM service provider. "
                "Reads /ccm/oslc-scm/catalog (note the hyphen — not underscore). "
                "Returns name, projectAreaId, providerUrl. Use this before scm_list_changesets "
                "to filter by project."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        Tool(
            name="scm_list_changesets",
            description=(
                "List recent SCM change-sets via the TRS feed at "
                "/ccm/rtcoslc/scm/reportable/trs/cs. Each TRS page exposes ~5 most-recent "
                "items so this tool walks <trs:previous> until `limit` is reached. "
                "For each change-set, returns itemId, title, component, author, modified, "
                "totalChanges, and any work-item links (resolved via /ccm/rtcoslc/scm/cslink/trs). "
                "Optional `project_name` filter restricts to one project area."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "Optional project name (substring match) — call scm_list_projects to see options"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max change-sets to return (default 25)"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="scm_get_changeset",
            description=(
                "Fetch a single SCM change-set by its itemId (the `_xxx...` token). "
                "GETs /ccm/rtcoslc/scm/reportable/cs/<id> for metadata and constructs the "
                "canonical /ccm/resource/itemOid/com.ibm.team.scm.ChangeSet/<id> URL. "
                "Returns full metadata + linked work items + raw RDF. "
                "Pass an itemId obtained from scm_list_changesets."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "changeset_id": {
                        "type": "string",
                        "description": "Change-set item ID (e.g. '_UrB4WENEEfGL3a8XuCNang' — leading underscore optional)"
                    }
                },
                "required": ["changeset_id"]
            }
        ),
        Tool(
            name="scm_get_workitem_changesets",
            description=(
                "List the SCM change-sets attached to a single EWM work item. "
                "GETs /ccm/resource/itemName/com.ibm.team.workitem.WorkItem/<id> and parses "
                "the rtc_cm:com.ibm.team.filesystem.workitems.change_set.com.ibm.team.scm.ChangeSet "
                "triples. Returns [{changeSetId, title, url}]. Empty list if the WI has no "
                "code attached — that's normal."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "workitem_id": {
                        "type": "string",
                        "description": "Numeric work-item ID (e.g. '3323')"
                    }
                },
                "required": ["workitem_id"]
            }
        ),
        Tool(
            name="review_get",
            description=(
                "Fetch review-relevant fields for an EWM work item: title, state, type, "
                "approved/reviewed booleans, approval records, linked change-sets, and the "
                "comments URL. Approval shape: {approver, descriptor, stateName, stateIdentifier}. "
                "Works on any work item — review-typed work items are not required (the "
                "approval shape is universal)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "workitem_id": {
                        "type": "string",
                        "description": "Numeric work-item ID"
                    }
                },
                "required": ["workitem_id"]
            }
        ),
        Tool(
            name="review_list_open",
            description=(
                "List open EWM review work items in a project (type = "
                "com.ibm.team.review.workItemType.review and oslc_cm:closed=false). "
                "Most projects on this server have zero review-typed WIs — that's not an "
                "error, the OSLC query simply returns an empty list. Use review_get on any "
                "work item to read its approvals."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ewm_project": {
                        "type": "string",
                        "description": "EWM project number or name"
                    }
                },
                "required": ["ewm_project"]
            }
        ),
    ]


# ── Tool Handlers ─────────────────────────────────────────────

@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    global _client, _projects_cache, _ewm_projects_cache, _etm_projects_cache
    global _modules_cache, _last_requirements, _last_module_name, _last_project_name
    global _folder_cache

    logger.info("Tool called: %s", name)

    try:
        # ── connect_to_elm ────────────────────────────────────
        if name == "connect_to_elm":
            url = arguments.get("url", "").strip().rstrip('/')
            username = arguments.get("username", "").strip()
            password = arguments.get("password", "").strip()

            if not all([url, username, password]):
                return [TextContent(type="text", text="Error: url, username, and password are all required.")]

            # Pass the URL as-is — the client normalizes it and sets up all endpoints
            client = DOORSNextClient(url, username, password)
            auth_result = client.authenticate()
            if not auth_result['success']:
                return [TextContent(type="text", text=(
                    f"Failed to connect: {auth_result['error']}\n\n"
                    "Please check:\n"
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

            body = (
                f"Successfully connected to IBM ELM (ELM MCP v{__version__}).\n\n"
                f"**Endpoints configured:**\n"
                f"- DNG (requirements): `{client.base_url}`\n"
                f"- EWM (work items / SCM): `{client.ccm_url}`\n"
                f"- ETM (test mgmt): `{client.qm_url}`\n\n"
                f"Found **{len(projects)}** DNG projects.\n\n"
                f"**What I can do:**\n"
                f"- **DNG** — Read, create, and update requirements. Create modules and "
                f"automatically populate them with requirements (no manual drag-bind needed). "
                f"Import PDFs. Create and compare baselines.\n"
                f"- **EWM** — Create Tasks and Defects, transition workflow states, "
                f"query work items, update arbitrary fields.\n"
                f"- **ETM** — Create Test Cases and record Test Results (pass/fail).\n"
                f"- **SCM** — Inspect change-sets and code reviews linked to work items.\n"
                f"- **Full Lifecycle** — Requirements → Tasks → Test Cases → Defects, "
                f"all cross-linked.\n\n"
                f"Which project would you like to work with?"
            )
            return [TextContent(type="text", text=_maybe_append_update_notice(body))]

        # ── extract_pdf (no connection needed) ────────────────
        if name == "extract_pdf":
            file_path = arguments.get("file_path", "").strip()
            if not file_path:
                return [TextContent(type="text", text="Error: file_path is required.")]

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
            error_detail = f"\nReason: {_client_error}" if _client_error else ""
            return [TextContent(type="text", text=(
                f"Not connected to ELM.{error_detail}\n\n"
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

        # ── search_requirements ────────────────────────────────
        elif name == "search_requirements":
            proj_id = arguments.get("project_identifier", "")
            query = arguments.get("query", "")

            if not proj_id or not query:
                return [TextContent(type="text", text="Error: project_identifier and query are required.")]

            if not _projects_cache:
                _projects_cache = client.list_projects()

            project = _find_by_identifier(_projects_cache, proj_id)
            if not project:
                return [TextContent(type="text", text=f"Project not found: '{proj_id}'")]

            results = client.search_requirements(project['url'], query)

            if not results:
                return [TextContent(type="text", text=(
                    f"No results for '{query}' in '{project['title']}'."
                ))]

            lines = [
                f"# Search Results for '{query}' in '{project['title']}'\n",
                f"Found **{len(results)}** result(s):\n",
            ]
            for i, r in enumerate(results, 1):
                lines.append(f"{i}. **{r['title']}**")
                if r.get('url'):
                    lines.append(f"   - URL: `{r['url']}`")
                if r.get('summary'):
                    lines.append(f"   - {r['summary'][:150]}")

            return [TextContent(type="text", text="\n".join(lines))]

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
        elif name == "create_module":
            proj_id = arguments.get("project_identifier", "")
            title = arguments.get("title", "")
            description = arguments.get("description", "")

            if not proj_id:
                return [TextContent(type="text", text="Error: project_identifier is required.")]
            if not title:
                return [TextContent(type="text", text="Error: title is required.")]

            if not _projects_cache:
                _projects_cache = client.list_projects()
            project = _find_by_identifier(_projects_cache, proj_id)
            if not project:
                return [TextContent(type="text", text=f"Project not found: '{proj_id}'")]

            result = client.create_module(project['url'], title, description)
            if result and 'error' not in result:
                return [TextContent(type="text", text=(
                    f"# Module Created in '{project['title']}'\n\n"
                    f"- **Title:** {result['title']}\n"
                    f"- **URL:** `{result['url']}`\n\n"
                    f"**Next step:** call `create_requirements` with `module_name` set to "
                    f"`{result['title']}` to populate this module."
                ))]
            err = result.get('error', 'unknown error') if result else 'unknown error'
            return [TextContent(type="text", text=(
                f"Error: failed to create module — {err}\n"
                "Check that you have write permissions in this project and that "
                "the project has a 'Module' artifact type defined."
            ))]

        elif name == "create_requirements":
            proj_id = arguments.get("project_identifier", "")
            folder_name = arguments.get("folder_name", "")
            module_name = arguments.get("module_name", "")
            reqs_data = arguments.get("requirements", [])

            if not proj_id:
                return [TextContent(type="text", text="Error: project_identifier is required.")]
            if not reqs_data:
                return [TextContent(type="text", text="Error: requirements array is empty.")]

            # Default folder name when only module_name was given
            if module_name and not folder_name:
                folder_name = module_name
            if not folder_name and not module_name:
                return [TextContent(type="text", text=(
                    "Error: provide module_name (preferred — makes the requirements "
                    "visible as a navigable document in DNG) and/or folder_name."
                ))]

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

            # Find or create the target module if requested
            module = None
            if module_name:
                # Re-use cached module if we created it in this session
                module = _folder_cache.get(f"__module__::{module_name}")
                if not module:
                    # Search existing modules in the project
                    try:
                        existing = client.get_modules(project['url'])
                    except Exception:
                        existing = []
                    target = module_name.lower()
                    for m in existing:
                        m_title = (m.get('title') or '').lower()
                        if m_title == target or m_title == f"[ai generated] {target}":
                            module = m
                            break
                if not module:
                    created_mod = client.create_module(project['url'], module_name)
                    if not created_mod or 'error' in created_mod:
                        err = created_mod.get('error', 'unknown') if created_mod else 'unknown'
                        return [TextContent(type="text", text=(
                            f"Error: could not find or create module '{module_name}' — {err}"
                        ))]
                    module = created_mod
                _folder_cache[f"__module__::{module_name}"] = module

            # Find or create the holding folder for the base artifacts
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

            # Bind the freshly created requirements to the module in one PUT
            bind_status = None
            if module and created:
                bind_status = client.add_to_module(
                    module['url'],
                    [r['url'] for r in created if r.get('url')],
                )

            # Build response
            lines = [
                f"# Requirements Created in '{project['title']}'\n",
            ]
            if module:
                lines.append(f"Module: **{module['title']}**  `{module['url']}`")
            lines.append(f"Folder: **{folder_name}**\n")
            lines.append(f"Created **{len(created)}** of {len(reqs_data)} requirement(s):\n")

            for i, r in enumerate(created, 1):
                lines.append(f"{i}. {r['title']}")
                if r.get('url'):
                    lines.append(f"   - URL: `{r['url']}`")

            if failed:
                lines.append(f"\n**Failed ({len(failed)}):**")
                for f_msg in failed:
                    lines.append(f"- {f_msg}")

            if module and bind_status:
                if 'error' in bind_status:
                    lines.append(
                        f"\n**Warning:** requirements were created but binding to module "
                        f"failed: {bind_status['error']}. The requirements still exist in "
                        f"the folder and can be added to the module manually in DNG."
                    )
                else:
                    added = bind_status.get('added', 0)
                    lines.append(
                        f"\n**Bound to module:** {added} requirement(s) added to "
                        f"'{module['title']}'. Open the module in DNG to see them in order."
                    )
            elif not module:
                lines.append(
                    f"\n**Note:** no module_name was provided, so these requirements live in "
                    f"the folder '{folder_name}' as standalone artifacts. To make them appear "
                    f"in a navigable document, re-run with `module_name` set, or move them in DNG."
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

        # ── list_global_configurations (GCM) ─────────────────
        elif name == "list_global_configurations":
            configs = client.list_global_configurations()
            if not configs:
                return [TextContent(type="text", text=(
                    "No global configurations found. "
                    "GCM may not be configured on this server."
                ))]

            lines = [
                f"# Global Configurations ({len(configs)} total)\n",
                "These span across DNG, EWM, and ETM:\n",
            ]
            for i, c in enumerate(configs, 1):
                lines.append(f"{i}. **{c['title']}**")
                lines.append(f"   - URL: `{c['url']}`")

            lines.append(
                "\nUse `get_global_config_details` with a config URL "
                "to see which DNG/EWM/ETM components contribute to it."
            )
            return [TextContent(type="text", text="\n".join(lines))]

        # ── list_global_components (GCM) ──────────────────────
        elif name == "list_global_components":
            components = client.list_global_components()
            if not components:
                return [TextContent(type="text", text=(
                    "No global components found. "
                    "GCM may not be configured on this server."
                ))]

            lines = [
                f"# Global Components ({len(components)} total)\n",
                "Components across all ELM apps:\n",
            ]
            for i, c in enumerate(components, 1):
                lines.append(f"{i}. **{c['title']}**")
                if c.get('url'):
                    lines.append(f"   - URL: `{c['url']}`")
                if c.get('configurations_url'):
                    lines.append(f"   - Configurations: `{c['configurations_url']}`")
                if c.get('created'):
                    lines.append(f"   - Created: {c['created']}")

            return [TextContent(type="text", text="\n".join(lines))]

        # ── get_global_config_details (GCM) ───────────────────
        elif name == "get_global_config_details":
            config_url = arguments.get("config_url", "")
            if not config_url:
                return [TextContent(type="text", text="Error: config_url is required.")]

            details = client.get_global_config_details(config_url)
            if not details:
                return [TextContent(type="text", text=(
                    f"Could not retrieve details for configuration: {config_url}"
                ))]

            lines = [
                f"# Global Configuration Details\n",
                f"- **Title:** {details['title']}",
                f"- **Type:** {details['type']}",
                f"- **URL:** `{details['url']}`",
            ]
            if details.get('component'):
                lines.append(f"- **Component:** `{details['component']}`")

            contribs = details.get('contributions', [])
            if contribs:
                lines.append(f"\n### Contributions ({len(contribs)})\n")
                for c in contribs:
                    lines.append(f"- [{c['app']}] `{c['url']}`")
            else:
                lines.append("\nNo contributions found (this may be a simple configuration).")

            return [TextContent(type="text", text="\n".join(lines))]

        # ── generate_chart ────────────────────────────────────
        elif name == "generate_chart":
            chart_type = arguments.get("chart_type", "").strip().lower()
            title = arguments.get("title", "").strip()
            labels = arguments.get("labels") or []
            values = arguments.get("values") or []
            x_label = arguments.get("x_label", "")
            y_label = arguments.get("y_label", "")
            output_filename = (arguments.get("output_filename") or "").strip()

            if chart_type not in {"bar", "hbar", "pie", "line"}:
                return [TextContent(type="text", text=(
                    "Error: chart_type must be one of: bar, hbar, pie, line."
                ))]
            if not title:
                return [TextContent(type="text", text="Error: title is required.")]
            if not labels or not values:
                return [TextContent(type="text", text=(
                    "Error: labels and values are both required and must be non-empty."
                ))]
            if len(labels) != len(values):
                return [TextContent(type="text", text=(
                    f"Error: labels ({len(labels)}) and values ({len(values)}) "
                    "must have the same length."
                ))]
            try:
                values = [float(v) for v in values]
            except (TypeError, ValueError):
                return [TextContent(type="text", text="Error: values must be numbers.")]

            try:
                import matplotlib
                matplotlib.use("Agg")
                import matplotlib.pyplot as plt
            except ImportError:
                return [TextContent(type="text", text=(
                    "matplotlib is not installed. Run: pip install -r requirements.txt"
                ))]

            import re, time
            charts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "charts")
            os.makedirs(charts_dir, exist_ok=True)
            if not output_filename:
                slug = re.sub(r"[^a-zA-Z0-9]+", "_", title).strip("_").lower()[:60] or "chart"
                output_filename = f"{slug}_{int(time.time())}"
            output_filename = re.sub(r"[^a-zA-Z0-9_\-]+", "_", output_filename)[:80]
            out_path = os.path.join(charts_dir, f"{output_filename}.png")

            fig, ax = plt.subplots(figsize=(10, 6))
            try:
                if chart_type == "bar":
                    ax.bar(labels, values, color="#1f77b4")
                    if x_label: ax.set_xlabel(x_label)
                    if y_label: ax.set_ylabel(y_label)
                    if any(len(str(l)) > 10 for l in labels):
                        plt.xticks(rotation=30, ha="right")
                elif chart_type == "hbar":
                    ax.barh(labels, values, color="#2ca02c")
                    ax.invert_yaxis()
                    if x_label: ax.set_xlabel(x_label)
                    if y_label: ax.set_ylabel(y_label)
                elif chart_type == "line":
                    ax.plot(labels, values, marker="o", color="#ff7f0e", linewidth=2)
                    if x_label: ax.set_xlabel(x_label)
                    if y_label: ax.set_ylabel(y_label)
                    if any(len(str(l)) > 10 for l in labels):
                        plt.xticks(rotation=30, ha="right")
                elif chart_type == "pie":
                    if all(v == 0 for v in values):
                        plt.close(fig)
                        return [TextContent(type="text", text="Error: pie chart needs at least one non-zero value.")]
                    ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=90)
                    ax.set_aspect("equal")

                ax.set_title(title, fontsize=14, fontweight="bold")
                fig.tight_layout()
                fig.savefig(out_path, dpi=150, bbox_inches="tight")
            finally:
                plt.close(fig)

            return [TextContent(type="text", text=(
                f"Chart saved: {out_path}\n\n"
                f"- Type: {chart_type}\n"
                f"- Title: {title}\n"
                f"- Data points: {len(labels)}\n"
                f"- Total: {sum(values):g}"
            ))]

        # ── get_attribute_definitions (DNG) ────────────────────
        elif name == "get_attribute_definitions":
            proj_id = arguments.get("project_identifier", "")
            if not proj_id:
                return [TextContent(type="text", text="Error: project_identifier is required.")]
            if not _projects_cache:
                _projects_cache = client.list_projects()
            project = _find_by_identifier(_projects_cache, proj_id)
            if not project:
                return [TextContent(type="text", text=f"Project not found: '{proj_id}'")]
            defs = client.get_attribute_definitions(project['url'])
            if not defs:
                return [TextContent(type="text", text=(
                    f"No attribute definitions found for '{project['title']}'. "
                    "Either the shapes are empty or the project URL is unreachable."
                ))]
            lines = [f"# Attribute Definitions in '{project['title']}'", ""]
            lines.append(f"**{len(defs)} unique attributes** (across all artifact types):\n")
            enums = [d for d in defs if d['allowed_values']]
            if enums:
                lines.append(f"\n## {len(enums)} enum-valued (selectable):\n")
                for d in enums[:25]:
                    vals = ", ".join(av['label'] for av in d['allowed_values'][:6])
                    lines.append(f"- **{d['title']}** (`{d['name']}`) → {vals}")
                    lines.append(f"  - Predicate: `{d['predicate_uri']}`")
            literals = [d for d in defs if not d['allowed_values']]
            if literals:
                lines.append(f"\n## {len(literals)} literal/free-form:\n")
                for d in literals[:25]:
                    lines.append(f"- **{d['title']}** (`{d['name']}`) → `{d['predicate_uri']}`")
            return [TextContent(type="text", text="\n".join(lines))]

        # ── update_requirement_attributes (DNG) ────────────────
        elif name == "update_requirement_attributes":
            req_url = arguments.get("requirement_url", "")
            attrs = arguments.get("attributes") or {}
            if not req_url or not attrs:
                return [TextContent(type="text", text=(
                    "Error: requirement_url and attributes are required."
                ))]
            result = client.update_requirement_attributes(req_url, attrs)
            if result and 'error' not in result:
                applied = result.get('updated', [])
                return [TextContent(type="text", text=(
                    f"# Requirement Attributes Updated\n\n"
                    f"- **URL:** `{result.get('url', req_url)}`\n"
                    f"- **Applied:** {', '.join(applied) if applied else '(none — keys did not match any shape)'}\n\n"
                    f"For enum-valued attributes, the value is mapped from a friendly label "
                    f"(e.g. 'High') to the corresponding allowed-value URI."
                ))]
            else:
                err = result.get('error', '') if result else ''
                return [TextContent(type="text", text=(
                    f"Failed to update requirement attributes.\n{err}"
                ))]

        # ── update_work_item (EWM) ─────────────────────────────
        elif name == "update_work_item":
            wi_url = arguments.get("workitem_url", "")
            fields = arguments.get("fields") or {}
            if not wi_url or not fields:
                return [TextContent(type="text", text=(
                    "Error: workitem_url and fields are required."
                ))]
            result = client.update_work_item(wi_url, fields)
            if result and 'error' not in result:
                return [TextContent(type="text", text=(
                    f"# Work Item Updated\n\n"
                    f"- **URL:** `{result.get('url', wi_url)}`\n"
                    f"- **Applied:** {', '.join(result.get('updated', []))}"
                ))]
            err = result.get('error', '') if result else ''
            return [TextContent(type="text", text=f"Failed to update work item.\n{err}")]

        # ── transition_work_item (EWM) ─────────────────────────
        elif name == "transition_work_item":
            wi_url = arguments.get("workitem_url", "")
            target = arguments.get("target_state", "")
            if not wi_url or not target:
                return [TextContent(type="text", text=(
                    "Error: workitem_url and target_state are required."
                ))]
            result = client.transition_work_item(wi_url, target)
            if result and 'error' not in result:
                return [TextContent(type="text", text=(
                    f"# Work Item Transitioned\n\n"
                    f"- **URL:** `{result['url']}`\n"
                    f"- **State:** `{result['state'].rsplit('/', 1)[-1]}`\n"
                    f"- **Action used:** `{result.get('action', '?')}`"
                ))]
            err = result.get('error', '') if result else ''
            return [TextContent(type="text", text=f"Failed to transition work item.\n{err}")]

        # ── query_work_items (EWM) ─────────────────────────────
        elif name == "query_work_items":
            ewm_proj = arguments.get("ewm_project", "")
            where = arguments.get("where", "")
            select = arguments.get("select", "*")
            page_size = int(arguments.get("page_size", 25) or 25)
            if not ewm_proj:
                return [TextContent(type="text", text="Error: ewm_project is required.")]
            if not _ewm_projects_cache:
                _ewm_projects_cache = client.list_ewm_projects()
            project = _find_by_identifier(_ewm_projects_cache, ewm_proj)
            if not project:
                return [TextContent(type="text", text=f"EWM project not found: '{ewm_proj}'")]
            items = client.query_work_items(
                ewm_project_url=project['url'],
                where=where,
                select=select,
                page_size=page_size,
            )
            if not items:
                return [TextContent(type="text", text=(
                    f"No work items returned for '{project['title']}' with where=`{where or '(none)'}`."
                ))]
            lines = [f"# Work Items in '{project['title']}'", "",
                     f"**{len(items)} match(es)**" + (f" for `{where}`" if where else ""), ""]
            for it in items[:50]:
                state_local = it['state'].rsplit('.', 1)[-1] if it.get('state') else ''
                type_local = it['type'].rsplit('/', 1)[-1] if it.get('type') else ''
                lines.append(f"- **{it.get('id', '?')}** {it.get('title', '')!r}  "
                              f"state={state_local} type={type_local}")
                lines.append(f"  - {it.get('url', '')}")
            return [TextContent(type="text", text="\n".join(lines))]

        # ── create_link (cross-domain) ─────────────────────────
        elif name == "create_link":
            src = arguments.get("source_url", "")
            ltype = arguments.get("link_type_uri", "")
            tgt = arguments.get("target_url", "")
            if not (src and ltype and tgt):
                return [TextContent(type="text", text=(
                    "Error: source_url, link_type_uri, and target_url are all required."
                ))]
            result = client.create_link(src, ltype, tgt)
            if result and 'error' not in result:
                return [TextContent(type="text", text=(
                    f"# Link Created\n\n"
                    f"- **Source:** `{result['source']}`\n"
                    f"- **Target:** `{result['target']}`\n"
                    f"- **Link type:** `{result['link_type']}`\n\n"
                    f"DNG normalizes custom link-type predicates after PUT — when re-fetching "
                    f"the source, the link will appear under its standard local-name prefix "
                    f"(e.g. `:satisfies`)."
                ))]
            err = result.get('error', '') if result else ''
            return [TextContent(type="text", text=f"Failed to create link.\n{err}")]

        # ── create_defect (EWM) ────────────────────────────────
        elif name == "create_defect":
            ewm_proj = arguments.get("ewm_project", "")
            title = arguments.get("title", "")
            description = arguments.get("description", "")
            severity = arguments.get("severity", "")
            req_url = arguments.get("requirement_url", "")
            tc_url = arguments.get("test_case_url", "")
            if not ewm_proj or not title:
                return [TextContent(type="text", text=(
                    "Error: ewm_project and title are required."
                ))]
            if not _ewm_projects_cache:
                _ewm_projects_cache = client.list_ewm_projects()
            project = _find_by_identifier(_ewm_projects_cache, ewm_proj)
            if not project:
                return [TextContent(type="text", text=f"EWM project not found: '{ewm_proj}'")]
            result = client.create_defect(
                service_provider_url=project['url'],
                title=title, description=description,
                severity=severity or None,
                requirement_url=req_url or None,
                test_case_url=tc_url or None,
            )
            if result and 'error' not in result:
                lines = [
                    "# Defect Created",
                    "",
                    f"- **Title:** {result['title']}",
                    f"- **Project:** {project['title']}",
                    f"- **URL:** {result['url']}",
                ]
                if severity:
                    lines.append(f"- **Severity:** {severity}")
                if req_url:
                    lines.append(f"- **Affects requirement:** `{req_url}`")
                if tc_url:
                    lines.append(f"- **Related test case:** `{tc_url}`")
                return [TextContent(type="text", text="\n".join(lines))]
            err = result.get('error', '') if result else ''
            return [TextContent(type="text", text=(
                f"Failed to create defect in '{project['title']}'.\n{err}"
            ))]

        # ── scm_list_projects ─────────────────────────────────
        elif name == "scm_list_projects":
            projects = client.scm_list_projects()
            if not projects:
                return [TextContent(type="text", text=(
                    "No SCM projects found. Either /ccm/oslc-scm/catalog is unreachable "
                    "or the catalog is empty."
                ))]
            lines = [f"# SCM Projects ({len(projects)} total)", ""]
            for i, p in enumerate(projects[:50], 1):
                lines.append(f"{i}. **{p['name']}**")
                lines.append(f"   - paId: `{p['projectAreaId']}`")
            if len(projects) > 50:
                lines.append(f"\n…and {len(projects) - 50} more.")
            return [TextContent(type="text", text="\n".join(lines))]

        # ── scm_list_changesets ────────────────────────────────
        elif name == "scm_list_changesets":
            project_name = arguments.get("project_name", "") or None
            limit = int(arguments.get("limit", 25) or 25)
            cs = client.scm_list_changesets(project_name=project_name, limit=limit)
            if not cs:
                return [TextContent(type="text", text=(
                    "No change-sets returned. The TRS feed may be empty or the project "
                    f"filter '{project_name}' did not match any change-sets in the recent "
                    "TRS pages."
                ))]
            lines = [f"# Recent SCM Change-Sets ({len(cs)})", ""]
            for x in cs:
                lines.append(f"- **{x['itemId']}** — {x['title']!r}")
                lines.append(f"  - Component: {x['component']}, Author: `{x['author']}`")
                lines.append(f"  - Modified: {x['modified']}, Changes: {x['totalChanges']}")
                if x['workItems']:
                    lines.append(f"  - Linked WIs: " + ", ".join(w['workItemId'] for w in x['workItems']))
            return [TextContent(type="text", text="\n".join(lines))]

        # ── scm_get_changeset ──────────────────────────────────
        elif name == "scm_get_changeset":
            cs_id = arguments.get("changeset_id", "")
            if not cs_id:
                return [TextContent(type="text", text="Error: changeset_id is required.")]
            d = client.scm_get_changeset(cs_id)
            if 'error' in d:
                return [TextContent(type="text", text=f"Failed: {d['error']}")]
            lines = [
                f"# Change-Set {d['itemId']}", "",
                f"- **Title:** {d['title']}",
                f"- **Component:** {d['component']}",
                f"- **Author:** `{d['author']}`",
                f"- **Modified:** {d['modified']}",
                f"- **Total changes:** {d['totalChanges']}",
                f"- **Reportable URL:** {d['reportable_url']}",
                f"- **Canonical URL:** {d['canonical_url']}",
            ]
            if d.get('workItems'):
                lines.append(f"\n### Linked Work Items ({len(d['workItems'])})")
                for w in d['workItems']:
                    lines.append(f"- {w['workItemId']}: {w['url']}")
            return [TextContent(type="text", text="\n".join(lines))]

        # ── scm_get_workitem_changesets ────────────────────────
        elif name == "scm_get_workitem_changesets":
            wi_id = arguments.get("workitem_id", "")
            if not wi_id:
                return [TextContent(type="text", text="Error: workitem_id is required.")]
            cs = client.scm_get_workitem_changesets(wi_id)
            if not cs:
                return [TextContent(type="text", text=(
                    f"Work item {wi_id} has no SCM change-sets attached. "
                    "(That's normal for non-development work.)"
                ))]
            lines = [f"# Change-Sets on Work Item {wi_id} ({len(cs)})", ""]
            for x in cs:
                lines.append(f"- **{x['changeSetId']}** — {x['title']!r}")
                lines.append(f"  - URL: {x['url']}")
            return [TextContent(type="text", text="\n".join(lines))]

        # ── review_get ─────────────────────────────────────────
        elif name == "review_get":
            wi_id = arguments.get("workitem_id", "")
            if not wi_id:
                return [TextContent(type="text", text="Error: workitem_id is required.")]
            r = client.review_get(wi_id)
            if 'error' in r:
                return [TextContent(type="text", text=f"Failed: {r['error']}")]
            lines = [
                f"# Review-View of Work Item {wi_id}", "",
                f"- **Title:** {r.get('title','')}",
                f"- **State:** `{r.get('state','').rsplit('/',1)[-1]}`",
                f"- **Type:** `{r.get('type','').rsplit('/',1)[-1]}`",
                f"- **approved:** {r.get('approved')}",
                f"- **reviewed:** {r.get('reviewed')}",
                f"- **Comments URL:** `{r.get('comments_url','')}`",
            ]
            apps = r.get('approvals', [])
            lines.append(f"\n### Approvals ({len(apps)})")
            for a in apps[:20]:
                lines.append(f"- {a.get('descriptor','')} — approver `{a.get('approver','')}` "
                              f"state {a.get('stateName','')} ({a.get('stateIdentifier','')})")
            cs = r.get('changeSets', [])
            lines.append(f"\n### Linked Change-Sets ({len(cs)})")
            for c in cs[:20]:
                lines.append(f"- {c['changeSetId']}: {c['url']}")
            return [TextContent(type="text", text="\n".join(lines))]

        # ── review_list_open ───────────────────────────────────
        elif name == "review_list_open":
            ewm_proj = arguments.get("ewm_project", "")
            if not ewm_proj:
                return [TextContent(type="text", text="Error: ewm_project is required.")]
            if not _ewm_projects_cache:
                _ewm_projects_cache = client.list_ewm_projects()
            project = _find_by_identifier(_ewm_projects_cache, ewm_proj)
            if not project:
                return [TextContent(type="text", text=f"EWM project not found: '{ewm_proj}'")]
            items = client.review_list_open(project['url'])
            if not items:
                return [TextContent(type="text", text=(
                    f"No open review work items in '{project['title']}'. "
                    "(This is the normal case on this server — review-typed WIs are rare.)"
                ))]
            lines = [f"# Open Reviews in '{project['title']}' ({len(items)})", ""]
            for it in items:
                lines.append(f"- **{it.get('id', '?')}** {it.get('title', '')!r} state="
                              f"`{it.get('state','').rsplit('.',1)[-1]}`")
            return [TextContent(type="text", text="\n".join(lines))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error("Tool %s failed: %s\n%s", name, e, tb)
        return [TextContent(type="text", text=(
            f"Error in {name}: {str(e)}\n\n{tb}"
        ))]


# ── Main ──────────────────────────────────────────────────────

async def main():
    logger.info("IBM ELM MCP Server starting (33 tools, 4 prompts, 3 resource templates)")
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
