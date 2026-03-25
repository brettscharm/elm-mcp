# IBM ELM AI Agent

An MCP server that lets Bob (or any AI coding assistant) read and write engineering artifacts across the IBM Engineering Lifecycle Management (ELM) suite -- DOORS Next (DNG), Engineering Workflow Management (EWM), and Engineering Test Management (ETM).

**16 MCP tools** covering the full requirements-to-test lifecycle with read+write capabilities across DNG, EWM, and ETM.

**This is NOT an official IBM product.** Built by Brett Scharmett and Bob for demo purposes.

---

## Setup

```bash
git clone https://github.com/brettscharm/doors-next-bob-integration.git
```

Open the project in VS Code with Bob, then say:

```
Bob, connect to ELM
```

Bob handles everything from there — installs dependencies, configures the MCP server, asks for your credentials, and connects.

You'll need to **restart VS Code once** after the first setup so the MCP server activates. After that, just say "connect to ELM" and you're in.

---

## What It Does

**Read (DNG):**
1. **Connect** — Bob asks for your ELM server URL, username, and password
2. **Projects** — List all 107 DNG projects, 101 EWM projects, or 77 ETM projects
3. **Modules** — Browse modules from any project
4. **Requirements** — Read requirements with full attributes, custom fields, and 26 artifact types
5. **Link Types** — Discover all 25 link types (Satisfies, Elaborated By, etc.)
6. **Save** — Export to JSON, CSV, or Markdown

**Write (DNG):**
7. **Create** — Generate requirements with [AI Generated] prefix, rich XHTML content, and links
8. **Organize** — Create descriptive folders for AI-generated artifacts

**Full Lifecycle (DNG + EWM + ETM):**
- Create a requirement in DNG
- Create a Task in EWM linked to that requirement
- Create a Test Case, Test Script, Test Execution Record, and Test Result in ETM linked back to the requirement
- All 6 lifecycle artifacts confirmed working against live IBM ELM server

---

## Optional: .env File

To skip entering credentials every session, create a `.env` file:

```bash
cp .env.example .env
# Edit .env with your actual credentials
```

---

## Project Structure

```
doors-next-bob-integration/
├── BOB.md                 # Instructions Bob reads automatically
├── CLAUDE.md              # Instructions for Claude Code
├── LIFECYCLE.md           # Full lifecycle vision and status tracker
├── README.md              # This file
├── doors_client.py        # ELM API client (DNG + EWM + ETM)
├── doors_mcp_server.py    # MCP server (16 tools)
├── requirements.txt       # Python dependencies
└── .env.example           # Credential template
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Bob can't see the MCP server | Restart VS Code after first setup |
| Authentication fails | Check username/password. The tool auto-appends `/rm` so either `https://server.com` or `https://server.com/rm` works. |
| No modules found | Check your DNG permissions for that project |

---

## Support

- GitHub Issues: https://github.com/brettscharm/doors-next-bob-integration/issues
- Email: brett.scharmett@ibm.com
