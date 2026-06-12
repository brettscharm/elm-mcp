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

Concierge routes to `get_module_requirements(filter={"artifact_type": "System Requirement"})`. Use the exact type name from `get_artifact_types` (step 6).

> **About filtering by Status / Priority:** these are *enum* attributes, and on many DNG projects the stored value is an internal code (you'll see `Status: 4` in the output rather than `Status: Approved`). That means `{"Status": "Approved"}` can come back empty even when reqs ARE approved — the filter is matching the label against the stored code. Title-substring and artifact-type filters are the dependable ones. If you need status filtering and it returns empty, read the full list (no filter) and eyeball the `Status:` codes, or open the module in the DNG browser. (Improving enum-status filtering is tracked on the repo.)

### 6. Discover what attributes you can filter on

```
What attributes does <your project> support?
```

Concierge routes to `get_attribute_definitions`. You see every attribute the project defines — enum-valued ones (Status, Priority, Stability, …) with their allowed labels, and free-form ones (Owner, Created On, …). Use the exact attribute names here when building `filter={...}` dicts.

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
- ✅ Filtered requirement list — title-substring match (step 4)
- ✅ Filtered requirement list — by artifact type (step 5)
- ✅ Attribute definitions for the project (step 6)
- ✅ Full-text search results across modules (step 7)

---

## Common pitfalls

### "Get_module_requirements returns thousands of reqs and overwhelms the chat"

You skipped the filter interview. Bob is supposed to ASK about filters before dumping everything. Two fixes:

- Use `module_filter` or a `filter` dict to narrow scope before calling
- Update Bob's persona — the v0.16+ persona enforces the interview gate. If you're on an older version, run `update_elm_mcp`

### "A Status / Priority filter returns nothing but I know there are matching reqs"

This is the enum-code limitation from step 5. On many projects, enum attributes are stored as internal codes (`Status: 4`) rather than labels (`Status: Approved`), so `{"Status": "Approved"}` matches nothing. **Workarounds:**

- Use a `title_contains` or `artifact_type` filter instead — those always work
- Read the full list (no filter) and scan the `Status:` codes yourself
- Open the module in the DNG browser to filter by status visually

Enum-status filtering is a known rough edge tracked at https://github.com/brettscharm/elm-mcp/issues — title and type filters are the dependable path today.

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
