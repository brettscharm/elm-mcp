# Query Architecture

How elm-mcp turns natural language into the right ELM query. Introduced in v0.25.0.

## The problem it solves

Before v0.25.0, every read tool built its own OSLC/REST query its own way, against a different backend, with different filter semantics. Five backends, five dialects, five places for a bug to hide. That's why two long-standing bugs existed:

- **Enum filtering broke** — `{"Status": "Approved"}` returned nothing because the parser stored the numeric code (`4`) not the label (`Approved`). (Fixed v0.24.2.)
- **`resolve_requirement_id` broke** — it queried the wrong OSLC capability AND omitted the required namespace-prefix declaration. (Fixed v0.25.0.)

The query engine is the structural fix: one normalized path that all queries flow through.

## The four layers

```
natural language  (Bob extracts structured args from the user's sentence)
      │
      ▼
QueryIntent       (project, module?, predicates[], text?, requirement_id?, limit)
      │
      ▼  VocabularyResolver   human terms → canonical attr / op / value
      │
      ▼  QueryPlanner         intent shape → backend
      │
      ▼  Backends             resolve-by-id · full-text · module-scan
      │
      ▼  normalized results   same shape regardless of backend
```

The LLM (Bob) is the natural-language parser — it's good at "approved reqs owned by Sarah without tests" → structured predicates. The engine's job is to make whatever Bob extracts **execute reliably** with **forgiving vocabulary**.

### QueryIntent

```python
QueryIntent(
    project="WatsonX AI POC",
    module="Temperature Converter",     # optional — narrows scope
    predicates=[Pred("Status", "eq", "Approved"),
                Pred("validatedBy", "missing", None)],   # "untested"
    text=None,                          # set → full-text backend
    requirement_id=None,                # set → by-id backend
    limit=200,
)
```

Operators: `eq · neq · contains · in · missing · exists`.

### VocabularyResolver (`query_engine.build_predicates`)

Maps human input to canonical predicates. Three input shapes accepted:

- dict — `{"Status": "Approved", "title_contains": "login"}`
- structured list — `[{"attribute": "Priority", "operator": "eq", "value": "High"}]`
- phrase shortcuts — `["untested", "unowned", "approved"]`

Attribute aliases: `status/state → Status`, `owner/owned by/assignee → Owner`, `type/kind → artifact_type`, `tested by/validated by → validatedBy`, etc.

Phrase shortcuts → complete predicates: `untested/no tests → validatedBy missing`, `unowned/no owner → Owner missing`, `tested → validatedBy exists`, etc.

Value normalization (`Approved` vs `StateApproved` vs the numeric `4`) is handled downstream by the enum-tolerant filter in `doors_client._apply_filter`.

### QueryPlanner (inside `execute`)

| Intent shape | Backend | Why |
|---|---|---|
| `requirement_id` set | resolve-by-id | direct OSLC identifier lookup |
| `text` set | full-text search | only the JFS index does this |
| predicates + module | module scan + filter | one Reportable REST call returns reqs w/ attributes |
| predicates, no module | scan all modules + filter | aggregate across the project |
| op `missing`/`exists` | post-process after fetch | link-absence isn't an OSLC `where` predicate |

### Backends

Each wraps an existing (now-fixed) client method and normalizes results:

- **resolve-by-id** → `client.resolve_requirement_id`
- **full-text** → `client.search_requirements`
- **module-scan** → `client.get_module_requirements(filter=...)` + engine post-filter for `missing`/`exists`/`neq`

## The tool surface

`query_elm` is the one NL-friendly entry point. Bob fills its args from the user's sentence; the engine does the rest. The specialized tools (`get_module_requirements`, `search_requirements`, `resolve_requirement_id`) still exist for direct/programmatic use — `query_elm` routes to all three correctly so callers don't have to choose.

## OSLC gotchas (hard-won — don't re-learn these)

These cost real debugging time; documented so they're not rediscovered:

### 1. Pick the query capability by resourceType, not position

A DNG project's `services.xml` lists MANY `oslc:QueryCapability` entries — AttributeType, LinkType, Folder, View, ReqIF, **and** Requirement. They are NOT ordered with Requirement first. Picking the first one (the old bug) returned `attributeTypeQuery`, so every requirement query 400'd.

**Fix:** select the capability whose `oslc:resourceType` includes `http://open-services.net/ns/rm#Requirement`.

### 2. Declare every namespace prefix via `oslc.prefix`

DNG's OSLC query engine does NOT assume standard prefixes. A `where`/`select` using `dcterms:identifier` without declaring the prefix fails with:

```
HTTP 400 — java.lang.RuntimeException: Undefined namespace prefix: dcterms
```

**Fix:** always send `oslc.prefix=dcterms=<http://purl.org/dc/terms/>` (and any other prefixes used).

### 3. Identifiers are integer literals — no quotes

`oslc.where=dcterms:identifier=990954` works; the quoted string form is unnecessary (both parse, but the integer form matches the datatype).

### 4. Enum attributes carry both a code and a label

Reportable REST returns `<customAttribute name="Status" value="4" literalName="Approved" isEnumeration="true"/>`. Read `literalName`, not `value`, or you get raw codes that don't display or filter sensibly.

### 5. `Status` enum labels diverge between sources

`get_attribute_definitions` reports `StateDraft`/`StateUnderReview` while artifacts store the bare `Draft`. The filter strips a leading `State` so both match.

## Migration status

| Phase | Status |
|---|---|
| QueryIntent + vocab + planner + backends | ✅ v0.25.0 |
| `query_elm` unified tool + Concierge/BOB.md routing | ✅ v0.25.0 |
| `resolve_requirement_id` fixed (correct capability + prefix) | ✅ v0.25.0 |
| EWM + ETM domain backends (`domain=ewm` / `domain=etm`) | ✅ v0.26.0 |
| `query_work_items` fixed (Deliverable vs ChangeRequest capability) | ✅ v0.26.0 |
| Refactor remaining read tools into thin engine facades | ⏳ future |
| Semantic search (embeddings) as a backend | ⏳ future |

## Domains (v0.26.0)

`query_elm` spans all three ELM artifact types via the `domain` arg:

| domain | artifacts | backend | vocabulary |
|---|---|---|---|
| `dng` (default) | requirements | by-id / full-text / module-scan | approved, high, untested, unowned, system requirement, … |
| `ewm` | work items | work-item query + client filter | open/closed, new/in progress/done, tasks/defects/stories, assigned to X |
| `etm` | test cases | test-case query + client filter | passed/failed/blocked, not run |

EWM/ETM results are flat dicts (id/title/state/type/owner); the engine
post-filters them client-side on those fields. EWM `open`/`closed` is
narrowed server-side via `oslc_cm:closed`.

### A 6th OSLC gotcha (EWM)

The EWM `workitems/services.xml` lists TWO query capabilities:
**Deliverable** (`cm#Deliverable`, listed FIRST) and **work items**
(`cm#ChangeRequest`, second). Picking the first — the old
`query_work_items` bug — queried `/deliverables` and always returned 0
work items. Select the `ChangeRequest` capability (or the base ending in
`/workitems`). Same class of bug as the DNG capability-selection one.
