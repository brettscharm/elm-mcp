# DOORS Next AI Agent

An MCP server that lets Bob (or any AI coding assistant) pull requirements from IBM DOORS Next Generation.

**This is NOT an official IBM product.** Built by Brett Scharmett and Bob for demo purposes.

---

## Setup

```bash
git clone https://github.com/brettscharm/doors-next-bob-integration.git
```

Open the project in VS Code with Bob, then say:

```
Bob, connect to DNG
```

Bob handles everything from there — installs dependencies, configures the MCP server, asks for your credentials, and connects.

You'll need to **restart VS Code once** after the first setup so the MCP server activates. After that, just say "connect to DNG" and you're in.

---

## What Happens

1. **Connect** — Bob asks for your DNG server URL, username, and password
2. **Projects** — "There are 107 projects. Want me to list them?"
3. **Modules** — "What are the modules in [project name]?"
4. **Requirements** — "Get requirements from [module name]"
5. **Save** — "Want me to save these?" (JSON, CSV, or Markdown)

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
├── README.md              # This file
├── doors_client.py        # DNG API client
├── doors_mcp_server.py    # MCP server (5 tools)
├── requirements.txt       # Python dependencies
└── .env.example           # Credential template
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Bob can't see the MCP server | Restart VS Code after first setup |
| Authentication fails | URL must end with `/rm` (e.g., `https://server.com/rm`) |
| No modules found | Check your DNG permissions for that project |

---

## Support

- GitHub Issues: https://github.com/brettscharm/doors-next-bob-integration/issues
- Email: brett.scharmett@ibm.com
