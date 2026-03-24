#!/usr/bin/env python3
"""
DOORS Next MCP Server for IBM Bob
Provides tools for Bob to interact with IBM DOORS Next Generation

Tools:
  1. connect_to_dng     - Connect with credentials
  2. list_projects      - List all DNG projects
  3. get_modules        - Get modules from a project
  4. get_module_requirements - Get requirements from a module
  5. save_requirements  - Save requirements to a file
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
_projects_cache: List[Dict] = []
_modules_cache: Dict[str, List[Dict]] = {}   # project_id -> modules
_last_requirements: List[Dict] = []
_last_module_name: str = ""
_last_project_name: str = ""


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
            name="connect_to_dng",
            description=(
                "Connect to IBM DOORS Next Generation with credentials. "
                "Returns the number of available projects. "
                "Use this if no .env file is configured."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "DOORS Next server URL ending in /rm (e.g., https://your-server.com/rm)"
                    },
                    "username": {
                        "type": "string",
                        "description": "DOORS Next username"
                    },
                    "password": {
                        "type": "string",
                        "description": "DOORS Next password"
                    }
                },
                "required": ["url", "username", "password"]
            }
        ),
        Tool(
            name="list_projects",
            description=(
                "List all available DOORS Next projects. "
                "Returns a numbered list. Use the number or name with get_modules."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_modules",
            description=(
                "Get all modules from a DOORS Next project. "
                "Specify the project by its number (from list_projects) or by name."
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
                "Specify both the project and module by number or name."
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
                "Save the last fetched requirements to a file. "
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
                "Create AI-generated requirements in a DOORS Next project. "
                "Requirements are placed in an 'AI Generated Artifacts' folder "
                "with [AI Generated] prefix. The human reviewer then moves them "
                "into the appropriate module in DNG. "
                "Each requirement needs a title, content, and artifact type."
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
                                    "description": "Artifact type name (e.g., 'System Requirement', 'Heading', 'User Requirement')"
                                },
                                "link_type": {
                                    "type": "string",
                                    "description": "Optional: Link type name (e.g., 'Satisfies', 'Elaborated By') from get_link_types"
                                },
                                "link_to": {
                                    "type": "string",
                                    "description": "Optional: URL of the requirement to link to"
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
                "Use this to find the correct artifact type names before creating requirements."
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
    ]


# ── Tool Handlers ─────────────────────────────────────────────

@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    global _client, _projects_cache, _modules_cache
    global _last_requirements, _last_module_name, _last_project_name

    try:
        # ── connect_to_dng ────────────────────────────────────
        if name == "connect_to_dng":
            url = arguments.get("url", "").strip()
            username = arguments.get("username", "").strip()
            password = arguments.get("password", "").strip()

            if not all([url, username, password]):
                return [TextContent(type="text", text="Error: url, username, and password are all required.")]

            client = DOORSNextClient(url, username, password)
            if not client.authenticate():
                return [TextContent(type="text", text=(
                    "Failed to connect to DOORS Next. Please check:\n"
                    "- URL is correct and ends with /rm\n"
                    "- Username and password are correct\n"
                    "- The server is reachable from this machine"
                ))]

            _client = client
            projects = _client.list_projects()
            _projects_cache = projects

            return [TextContent(type="text", text=(
                f"Successfully connected to DOORS Next!\n\n"
                f"There are **{len(projects)}** projects available.\n\n"
                f"Would you like me to list all the projects, or do you know "
                f"which specific one you'd like to work with today?"
            ))]

        # ── All other tools require a connection ──────────────
        client = _get_or_create_client()
        if client is None:
            return [TextContent(type="text", text=(
                "Not connected to DOORS Next.\n\n"
                "Use the `connect_to_dng` tool with your server URL, username, and password."
            ))]

        # ── list_projects ─────────────────────────────────────
        if name == "list_projects":
            if not _projects_cache:
                _projects_cache = client.list_projects()

            if not _projects_cache:
                return [TextContent(type="text", text=(
                    "No projects found. Check your permissions or server URL."
                ))]

            lines = [f"# DOORS Next Projects ({len(_projects_cache)} total)\n"]
            for i, p in enumerate(_projects_cache, 1):
                lines.append(f"{i}. **{p['title']}**")

            lines.append(f"\nUse `get_modules` with a project number or name to see its modules.")
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

            # Find or create the named folder
            folder = client.find_folder(project['url'], folder_name)
            if not folder:
                folder = client.create_folder(project['url'], folder_name)
                if not folder:
                    return [TextContent(type="text", text=(
                        f"Failed to create '{folder_name}' folder. "
                        "Check your write permissions for this project."
                    ))]

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

                if result:
                    created.append(result)
                else:
                    failed.append(f"'{title[:40]}' - API error")

            # Build response
            lines = [
                f"# Requirements Created in '{project['title']}'\n",
                f"Folder: **{folder_name}**\n",
                f"Created **{len(created)}** of {len(reqs_data)} requirement(s):\n",
            ]

            for i, r in enumerate(created, 1):
                lines.append(f"{i}. {r['title']}")

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
