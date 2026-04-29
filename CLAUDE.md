# Hey Claude — go read BOB.md. That's where everything lives.
#
# To set up this MCP server in Claude Code (and every other AI host on this machine), the user just runs:
#   python3 setup.py
# from this directory. setup.py writes ~/.claude.json + .mcp.json (and the equivalent for VS Code / Cursor / Windsurf), prompts for credentials, and verifies the server starts end-to-end.
#
# To verify the server is working without redoing setup:
#   python3 setup.py --diagnose
