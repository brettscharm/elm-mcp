# Lab 2: Connect to ELM and verify

**Time:** 10 minutes
**Prerequisites:** [Lab 1](../lab-01-install-mcp/) complete (`elm_mcp_health` returns connected)
**Learning objective:** Confirm you can list your real DNG, EWM, and ETM projects through the MCP.

---

## What you're doing

Setup already wired up the credentials. This lab is about *seeing your real ELM data* through Bob so you know everything works end-to-end before we start doing things.

We'll list projects in all three ELM apps:

- **DNG** — DOORS Next, requirements
- **EWM** — Workflow management, work items
- **ETM** — Test management, test cases

---

## Steps

### 1. Health check (refresher)

In Bob:

```
Is elm-mcp connected?
```

Bob calls `elm_mcp_health`. Confirm `State: connected` and `User: <your-username>`.

### 2. List your DNG projects

```
List my DNG projects.
```

Bob calls `list_projects(domain='dng')`. You'll get a numbered list of every DNG project your account has access to. Could be 1 project (a single sandbox) or 100+ (large enterprise deployment).

**Note the project name you'll use throughout the rest of the labs.** Pick a sandbox or test project — Labs 5+6 will read and (with confirmation) write requirements. Don't use a production project the first time through.

### 3. List your EWM projects

```
List my EWM projects.
```

Bob calls `list_projects(domain='ewm')`. Same format — numbered list. EWM projects are often named `<thing> (Change Management)` or `<thing> (Tasks)`.

### 4. List your ETM projects

```
List my ETM projects.
```

Bob calls `list_projects(domain='etm')`. ETM projects are often named `<thing> (Quality Management)` or `<thing> (Tests)`.

### 5. Pick a DNG project and see its modules

Replace `<your project>` with the name (or number from step 2) of the DNG project you'll use:

```
Show me modules in <your project>.
```

Bob calls `get_modules(project_identifier='<your project>')`. You'll see every module in the project with its title and ID.

### 6. Look at one module's requirements

Pick a module from step 5. Replace `<your module>` below:

```
Read requirements in <your module>.
```

Bob calls `get_module_requirements`. **Bob may interview you first about filters** — that's correct behavior. For this lab, say "no filter — show me everything" so you see the full list.

---

## Verify

You should see:

- ✅ A list of your DNG projects matching what you see in DOORS Next browser
- ✅ A list of your EWM projects matching what you see in EWM browser
- ✅ A list of your ETM projects matching what you see in ETM browser
- ✅ Modules in your chosen DNG project
- ✅ Actual requirement titles + URLs in your chosen module

If any of these are blank or look wrong, see Common Pitfalls.

---

## Common pitfalls

### "Bob says no projects in domain X"

Two possibilities:

- Your account genuinely has no projects in that domain. EWM/ETM may not be deployed everywhere; some teams only use DNG.
- Your account doesn't have list-projects permission. Ask your ELM admin to grant Project Reader on the project areas you need.

### "Connection error on every call"

Your session may have expired. Try:

```
Reconnect to ELM
```

Bob calls `connect_to_elm` which forces a fresh auth.

### "Bob shows projects but I can't open the module"

Permissions issue. Confirm in the DNG browser that you can open the module manually. If you can't, you don't have the right project role.

### "Bob is dumping every req in the module without asking about a filter"

That's a behavior bug — Bob's persona is supposed to interview first. Update to the latest version:

```
Update elm-mcp
```

Then restart Bob and try again.

---

## Try it yourself

Use `search_requirements` to find requirements containing a specific keyword across the whole project:

```
Search for "authentication" in <your project>.
```

The full-text search is fast and surfaces results across every module.

---

## What's next

→ [Lab 3: Install the modes](../lab-03-install-modes/)

Now that the raw MCP works, we'll add the **5 custom Bob modes** (Concierge, Plan, Push, Impact Analyst, Compliance Auditor). These are the discoverability + UX layer over the MCP tools.
