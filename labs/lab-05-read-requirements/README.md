# Lab 5: Read requirements (DNG)

**Time:** 15 minutes
**Prerequisites:** [Lab 4](../lab-04-concierge-routing/) complete (Concierge routing works)
**Learning objective:** Use Concierge + the underlying tools to browse, filter, and search DNG requirements.

---

## What you're doing

This lab covers the core DNG read flow: navigate projects → modules → requirements, with filtering and search. You'll use Concierge to route, but you'll also see the direct tools so you know what's happening under the hood.

Read-only — no writes to DNG.

---

## Steps

### 1. Confirm you're in Concierge

```
/concierge
```

### 2. List modules in your DNG project

Pick the DNG project from Lab 2. Replace `<your project>` below:

```
Show me modules in <your project>.
```

Concierge routes to `get_modules`. You'll see a numbered list of modules with titles and IDs.

### 3. Read a module's requirements with NO filter

Pick a module from step 2:

```
Read all requirements in <your module>.
```

Concierge routes to `get_module_requirements`. Bob may interview you about filters first — say "no filter" or "show everything" to see the full list.

### 4. Read with a filter — only Approved requirements

```
Read approved requirements in <your module>.
```

Concierge routes to `get_module_requirements(filter={"Status": "Approved"})`. You see only Approved reqs.

### 5. Read with a substring filter on title

```
Read requirements in <your module> where the title contains "security".
```

Concierge routes to `get_module_requirements(filter={"title_contains": "security"})`. You see only matching reqs.

### 6. Discover what attributes you can filter on

```
What attributes does <your project> support?
```

Concierge routes to `get_attribute_definitions`. You see every attribute the project has defined: built-in ones (Status, Priority, Owner) and project-specific custom attributes. **You can filter on any of these.**

### 7. Full-text search across the whole project

```
Search for "authentication" in <your project>.
```

Concierge routes to `search_requirements`. Returns matching reqs from any module in the project, not just one.

### 8. Look up a specific req by short ID

If you saw a req ID like `123` or `REQ-456` in DNG, look it up directly:

```
What's req <ID> in <your project>?
```

Concierge routes to `resolve_requirement_id`. Returns the URL + title.

> Note: This tool has a known issue (see audit notes) where some DNG deployments need a specific OSLC query variant. If you get a "no requirement found" response on an ID you know exists, that's the known bug — it's tracked at https://github.com/brettscharm/elm-mcp/issues.

---

## Verify

You should see all of:

- ✅ Module list for your project
- ✅ Full requirement list (step 3)
- ✅ Filtered requirement list — only Approved (step 4)
- ✅ Filtered requirement list — title-substring match (step 5)
- ✅ Attribute definitions for the project
- ✅ Full-text search results across modules

---

## Common pitfalls

### "Get_module_requirements returns thousands of reqs and overwhelms the chat"

You skipped the filter interview. Bob is supposed to ASK about filters before dumping everything. Two fixes:

- Use `module_filter` or a `filter` dict to narrow scope before calling
- Update Bob's persona — the v0.16+ persona enforces the interview gate. If you're on an older version, run `update_elm_mcp`

### "Filter returns nothing but I know there are Approved reqs"

The filter value is case-sensitive and project-specific. Use `get_attribute_definitions` (step 6) to see the EXACT enum value. For some projects, "Approved" might be stored as `StateApproved` or similar — check the output of step 6 to see the literal value to use.

### "Search returns artifacts I don't recognize"

That's expected on a project with cross-app references. The DNG full-text search hits everything, including cross-app links to QM test cases that appear with their URL as the title (a data-quality issue at the project level, not a tool bug).

### "Resolve_requirement_id says 'no req found' for a valid ID"

Known issue. Track at https://github.com/brettscharm/elm-mcp/issues. Workaround: use `search_requirements` with the ID as a search term, or use the full URL directly in subsequent calls.

---

## Try it yourself

### Combine filters

```
Read requirements in <your module> where Status is Approved and Priority is High.
```

The filter dict supports multiple keys AND'd together.

### Save results to a file

```
Export the <your module> module to Excel.
```

This routes to `export_module_to_xlsx`, which we cover properly in Lab 12. For now, just note that the same module reads can be exported instead of dumped to chat.

### Look up artifact types

```
What artifact types does <your project> support?
```

Returns every artifact type defined (System Requirement, Non-Functional, Heading, etc.). You'll use this in Lab 6 when planning.

---

## What's next

→ [Lab 6: Plan + Push requirements](../lab-06-plan-push/)

The biggest single workflow we built. You'll go from a feature description through full Plan Mode discipline (risk classifier → decomposition → per-candidate elicitation) and end with a batch push of polished requirements into DNG.
