# Lab 3: Find anything

**Part 2 · The basics**
**Time:** 15 minutes · **Prerequisites:** [Lab 2](../lab-02-talk-to-your-data/) complete
**Outcome:** Query across requirements, work items, AND test cases with one tool — and find things by *meaning*, not just keywords.

---

## Two superpowers

Lab 2 used the individual read tools so you'd understand the pieces. This lab shows the two tools you'll actually reach for day to day:

1. **`query_elm`** — one unified query across all three ELM domains (requirements, work items, tests), with human vocabulary resolved for you.
2. **`find_similar_requirements`** — semantic search that finds requirements by what they *mean*, not the words they contain.

Both are read-only.

---

## Part A — query_elm (unified query)

Concierge routes any "find / show / list … matching …" request to `query_elm`. The point: you don't pick a tool or learn filter syntax — you describe what you want.

### Requirements (DNG)

```
Show me the approved requirements in <your module>.
```
```
Which requirements in <your module> are still in draft?
```
```
Find the untested requirements in <your module>.
```

That last one is special — "untested" means *no link to any test case*. The engine understands that.

### Work items (EWM)

Point it at your Change Management project:

```
Show me the open work items in <your EWM project>.
```
```
What tasks are in the new state?
```
```
Find the work item about "<keyword>".
```

### Test cases (ETM)

Point it at your Quality Management project:

```
List the test cases in <your ETM project>.
```
```
Find test cases about "<keyword>".
```

### Look up by ID

```
Find requirement <ID> in <your project>.
```

> **One tool, three domains.** `query_elm` routes each request to the right backend — by-ID lookup, full-text search, or attribute filter — and tells you which one ran. You just describe the goal.

---

## Part B — semantic search (find by meaning)

`find_similar_requirements` is the complement to keyword search. It finds requirements that mean the same thing as your reference — even with **zero shared words**.

### Dedup before you create

```
Is there already a requirement about how long the system takes to respond, in <your module>?
```

Bob ranks the closest matches with a similarity score. If something scores high, you don't need to write a duplicate.

### Find related requirements

```
Find requirements in <your module> related to helping users who cannot see the screen.
```

Watch what comes back — things like "Screen Reader Compatibility" surface near the top **even though "blind" and "cannot see" never appear in them.** That's semantic understanding; keyword search can't do it.

### Find reqs like an existing one

```
Find requirements similar to requirement <ID>.
```

Uses that requirement's text as the reference.

> **Air-gap safe.** Semantic search runs **fully local** — your requirement text never leaves the machine. (It needs the optional `fastembed` package; if it's not installed Bob tells you the one command to add it. The model downloads once, then works offline.)

---

## Verify checklist

- ✅ `query_elm` returned requirements by status / untested
- ✅ `query_elm` returned work items (EWM) and test cases (ETM)
- ✅ Looked up a requirement by ID through `query_elm`
- ✅ Semantic search ranked requirements by meaning
- ✅ Saw a semantic match with no shared keywords

---

## When to use which

| You want… | Tool |
|---|---|
| Things matching a precise filter (status, type, owner, untested) | `query_elm` |
| Things mentioning an exact word | `query_elm` with `text` (full-text) |
| Things that *mean* something, dedup, "have we written this before" | `find_similar_requirements` |

---

## Common pitfalls

**Semantic search says it's unavailable.** The optional `fastembed` package isn't installed. Run `python3 ~/.elm-mcp/setup.py --with-semantic` (or `pip install fastembed`), then retry. Everything else works without it.

**A query returns nothing.** That's an honest empty — the data genuinely has no matches. The engine never invents results. Loosen the filter or try semantic search for a broader, meaning-based look.

---

## What's next

→ [Lab 4: Write requirements that pass review](../lab-04-write-requirements/)

You can find anything. Now the flagship: drafting requirements with the rigor of a senior systems engineer, then pushing them to DNG.
