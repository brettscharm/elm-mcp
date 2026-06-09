# Lab 0: Prerequisites

**Time:** 5 minutes
**Prerequisites:** none
**Learning objective:** Confirm everything you need to run the rest of the labs is in place.

---

## What you need

### IBM Bob (or any MCP-compatible AI host)

This series is written for IBM Bob, but elm-mcp works with any MCP host:

- **IBM Bob** (recommended for this series)
- Claude Code
- Cursor
- VS Code with the Claude extension or Continue
- Windsurf

Confirm Bob is installed and you can open a chat. If you don't have it yet, follow IBM's install guide before continuing.

### Python 3.10 or later

```bash
python3 --version
```

You should see `Python 3.10.x` or newer. If not, install Python from python.org or your system package manager.

### Git

```bash
git --version
```

Any recent version is fine.

### Permission to install Python packages

`pip` must be able to install packages either system-wide or in a virtualenv. If you're on a corporate machine and locked out, talk to IT before continuing — Lab 1 will install a handful of packages (`requests`, `python-dotenv`, `mcp`, `PyMuPDF`, `matplotlib`, `markdown`, `openpyxl`, `pyyaml`).

### IBM ELM credentials

You need:

| Item | Example | Notes |
|---|---|---|
| **ELM URL** | `https://goblue.clm.ibmcloud.com` or `https://elm.yourco.com` | Bare server URL — `/rm` or `/ccm` paths are added automatically |
| **Username** | `your.name@yourco.com` or `jsmith` | Same as your DOORS Next / EWM login |
| **Password** | (your password) | Stored locally only; never sent anywhere except your ELM server |

If you don't have access to an ELM environment, options:

- Ask your ELM admin to provision a sandbox project for you
- Use IBM's hosted trial environment (search "IBM ELM trial")
- Skip Labs 2-6 and come back when you have access

---

## Verify

Run all four checks in your terminal:

```bash
python3 --version       # 3.10+
git --version           # any
pip3 --version          # any
echo "ELM URL: <your URL here>"
echo "ELM user: <your username here>"
```

If all four print without errors, you're ready.

---

## Common pitfalls

- **Python 2.x default.** Some systems still default `python` to Python 2. Always use `python3` explicitly throughout this series.
- **`pip` blocked behind a corporate proxy.** Set `HTTPS_PROXY` and `HTTP_PROXY` environment variables before Lab 1.
- **MFA on your ELM account.** Some ELM deployments require app passwords or tokens instead of your normal password. Check with your admin if regular login doesn't work.

---

## What's next

→ [Lab 1: Install elm-mcp](../lab-01-install-mcp/)
