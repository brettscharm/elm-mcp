# Lab 5: Read requirements (DNG)

**Time:** 15 minutes
**Prerequisites:** [Lab 4](../lab-04-concierge-routing/) complete (Concierge routing works)
**Learning objective:** Use Concierge + the underlying tools to browse, filter, and search DNG requirements.

---

## What you're doing

This lab covers the core DNG read flow: navigate projects → modules → requirements, with filtering and search. You'll use Concierge to route, but you'll also see the direct tools so you know what's happening under the hood.

Read-only — no writes to DNG.

> **Shortcut (v0.25.0+):** the steps below use the individual read tools so you understand the pieces. In day-to-day use you can just ask in plain English and Concierge routes to **`query_elm`** — the unified query that resolves vocabulary ("approved", "untested", "high priority") and picks the right backend for you. Example: *"show me the approved requirements about conversion in the temperature converter."* This lab teaches the building blocks; `query_elm` is the fast path once you know them.

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

### 4. Read with a substring filter on title (the most reliable filter)

Pick a word that appears in some of your requirement titles (e.g. "login", "conversion", "security"):

```
Read requirements in <your module> where the title contains "<word>".
```

Concierge routes to `get_module_requirements(filter={"title_contains": "<word>"})`. You see only the matching reqs. **Title-substring filtering works on every project** — it's the filter to reach for first.

### 5. Filter by artifact type

```
Read only System Requirements in <your module>.
```

Concierge routes to `get_module_requirements(filter={"artifact_type": "System Requirement"})`. Use the exact type name from `get_artifact_types` (step 7).

### 6. Filter by Status (or any enum attribute)

```
Read approved requirements in <your module>.
```

Concierge routes to `get_module_requirements(filter={"Status": "Approved"})`. You see only the Approved reqs.

> **Heads-up (fixed in v0.24.2):** older versions stored enum attributes as internal codes — you'd see `Status: 4` and `{"Status": "Approved"}` returned nothing. As of **v0.24.2** the tool resolves enum labels, so the output shows `Status: Approved` and the filter just works. It's also tolerant of the `State` prefix some projects use (both `Approved` and `StateApproved` match). On **v0.24.1 or older?** Run `update_elm_mcp`, or use title/type filters in the meantime.

### 7. Discover what attributes you can filter on

```
What attributes does <your project> support?
```

Concierge routes to `get_attribute_definitions`. You see every attribute the project defines — enum-valued ones (Status, Priority, Stability, …) with their allowed labels, and free-form ones (Owner, Created On, …). Use the exact attribute names here when building `filter={...}` dicts.

### 8. Full-text search across the whole project

```
Search for "authentication" in <your project>.
```

Concierge routes to `search_requirements`. Returns matching reqs from any module in the project, not just one.

### 9. Look up a specific req by short ID

If you saw a req ID like `123` or `REQ-456` in DNG, look it up directly:

```
What's req <ID> in <your project>?
```

Concierge routes to `resolve_requirement_id`. Returns the URL + title.

> **Fixed in v0.25.0:** earlier versions queried the wrong OSLC capability and omitted a required namespace-prefix declaration, so this returned "no requirement found" for valid IDs. As of v0.25.0 it resolves correctly. On an older version? Run `update_elm_mcp`.

---

## Verify

You should see all of:

- ✅ Module list for your project
- ✅ Full requirement list (step 3)
- ✅ Filtered requirement list — title-substring match (step 4)
- ✅ Filtered requirement list — by artifact type (step 5)
- ✅ Filtered requirement list — by Status (step 6, v0.24.2+)
- ✅ Attribute definitions for the project (step 7)
- ✅ Full-text search results across modules (step 8)

---

## Common pitfalls

### "Get_module_requirements returns thousands of reqs and overwhelms the chat"

You skipped the filter interview. Bob is supposed to ASK about filters before dumping everything. Two fixes:

- Use `module_filter` or a `filter` dict to narrow scope before calling
- Update Bob's persona — the v0.16+ persona enforces the interview gate. If you're on an older version, run `update_elm_mcp`

### "A Status / Priority filter returns nothing but I know there are matching reqs"

If you're on **v0.24.2 or newer**, this should just work — enum attributes resolve to their labels (`Approved`, `High`, …) and the filter matches them, including the `State`-prefixed variants (`Approved` and `StateApproved` both work).

If you're on **v0.24.1 or older**, enum attributes were stored as internal codes (`Status: 4`) so `{"Status": "Approved"}` matched nothing. Fix:

- Run `update_elm_mcp` (one tool call) to get the fix, then retry
- In the meantime, use `title_contains` or `artifact_type` filters — those work on every version

### "Search returns artifacts I don't recognize"

That's expected on a project with cross-app references. The DNG full-text search hits everything, including cross-app links to QM test cases that appear with their URL as the title (a data-quality issue at the project level, not a tool bug).

### "Resolve_requirement_id says 'no req found' for a valid ID"

Fixed in **v0.25.0** (wrong OSLC query capability + missing prefix declaration). If you still see this, you're on an older build — run `update_elm_mcp` and retry.

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
