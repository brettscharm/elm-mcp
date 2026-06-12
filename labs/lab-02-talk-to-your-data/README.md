# Lab 2: Talk to your ELM data

**Part 2 · The basics**
**Time:** 15 minutes · **Prerequisites:** [Lab 1](../lab-01-install-connect/) complete
**Outcome:** Browse, filter, and search your real DNG requirements — in plain English, no tool names to memorize.

---

## The idea

You don't drive elm-mcp by learning tool names. You talk to **🧭 Concierge** — the default mode — in plain English, and it routes your request to the right tool. This lab gets you comfortable doing that against your own data.

Everything here is **read-only**. Nothing changes in ELM.

---

## Step 1 — make sure you're in Concierge

```
/concierge
```

(Or pick 🧭 ELM Concierge in the mode picker. It's the default — you're probably already there.)

## Step 2 — see what you have

```
List my DNG projects.
```

Pick a project to work with — ideally a sandbox or test project. Note its name; you'll use it below as `<your project>`.

```
Show me the modules in <your project>.
```

Pick a module — that's `<your module>`.

## Step 3 — read a module

```
Read the requirements in <your module>.
```

Bob may ask whether you want to filter first — that's intentional (it doesn't want to dump 500 reqs at you). For now say "show everything."

## Step 4 — filter while reading

Filters are how you find what you want without scrolling. Try a few:

```
Show me the requirements in <your module> whose title contains "<word>".
```
```
Show me only the System Requirements in <your module>.
```
```
Show me the approved requirements in <your module>.
```

> **Status / Priority filters** resolve human labels (approved, draft, high) — even though DNG stores them as internal codes under the hood. If a status filter ever comes back empty, the module genuinely has none with that status (read the full list to confirm).

## Step 5 — search across the whole project

Filters work inside one module; search spans the whole project:

```
Search <your project> for "<keyword>".
```

## Step 6 — look up one requirement by ID

If you spot a short ID like `12345` or `REQ-678`:

```
What's requirement <ID> in <your project>?
```

Bob returns the title + URL you can use anywhere.

## Step 7 — discover what you can filter on

```
What attributes does <your project> support?
```

This lists every attribute (Status, Priority, Owner, and any custom ones) with their allowed values — so you know what you can filter by.

---

## Verify checklist

- ✅ Listed your projects and modules
- ✅ Read a module's full requirement list
- ✅ Filtered by title, type, and status
- ✅ Searched the whole project
- ✅ Looked up a requirement by ID
- ✅ Saw the project's attribute definitions

---

## How Concierge decides what to do

You'll notice Bob handles different phrasings differently — that's by design:

| You say | Concierge |
|---|---|
| Clear request ("approved reqs in X") | Just does it |
| Clear intent, missing a detail ("show me the open ones") | Asks the one missing thing |
| Ambiguous ("clean this up") | Offers 2–3 labeled options |
| Not ELM at all ("why is my code crashing") | Steps aside — that's Bob's Code/Ask mode |

You never have to name a tool. Describe the goal; Concierge routes.

---

## Common pitfalls

**Bob dumps hundreds of requirements.** Add a filter, or let Bob run its filter interview. "Read approved reqs in X" beats "read everything in X."

**A status filter returns nothing.** That status genuinely isn't present in that module (e.g. all reqs are Medium, none High). Read the unfiltered list to confirm.

**Search returns odd entries with URL-looking titles.** Some projects have cross-app reference artifacts whose title literally *is* a URL — that's source-data, not a tool bug.

---

## Try it yourself

Combine filters in one ask:

```
Show me the approved System Requirements in <your module> whose title mentions "login".
```

That's three filters at once — Bob handles it.

---

## What's next

→ [Lab 3: Find anything](../lab-03-find-anything/)

You've browsed and filtered. Next: the unified query that searches across requirements, work items, AND tests — plus semantic search that finds things by *meaning*, not just keywords.
