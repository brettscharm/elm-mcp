# Lab 5: Create work items & test cases

**Part 3 · Doing the work**
**Time:** 15 minutes · **Prerequisites:** [Lab 4](../lab-04-write-requirements/) complete
**Outcome:** Create EWM tasks and ETM test cases from plain English — safely, with a preview before anything is written.

---

## ⚠️ This lab writes to ELM

Up to now everything was read-only. This lab creates real work items and test cases. **Use a sandbox project**, and notice the safety design: nothing is created until you explicitly confirm.

---

## The safety model: preview first

`create_elm` is the natural-language create tool. Its **default is preview** — it shows you exactly what *would* be created, runs a quality check, and writes **nothing**. It only creates when you confirm. This is deliberate: a query is harmless, but a create changes ELM, so it never happens from a vague sentence without you seeing the result first.

---

## Step 1 — preview some work items

Point at your Change Management (EWM) project:

```
Add a task to build the login API, and one to add rate limiting, in <your EWM project>.
```

Bob shows a preview:

```
# Preview — would create 2 work items (tasks)
**Nothing has been created yet.** Review below, then say *create them* to write.
1. Build the login API
2. Add rate limiting
```

Read it. **Nothing has been written.**

## Step 2 — confirm to create

```
Yes, create them.
```

Now Bob actually creates them and returns each work item's ID + URL:

```
# Created 2 work item(s)
- ✓ Build the login API (ID 3958)
  https://.../WorkItem/3958
- ✓ Add rate limiting (ID 3959)
```

## Step 3 — verify they landed

```
Show me work items in <your EWM project> whose title contains "login".
```

(That's `query_elm` from Lab 3 — your new task should appear.)

## Step 4 — preview test cases

Point at your Quality Management (ETM) project:

```
Create test cases for "valid login", "invalid password", and "account lockout" in <your ETM project>.
```

Same preview-first flow — review, then confirm to create.

## Step 5 — link as you create (traceability)

You can cross-link while creating — a task to the requirement it implements, a test case to the requirement it validates:

```
Create a test case "verify 200ms response time" that validates requirement <REQ-ID>, in <your ETM project>.
```

The link is what makes traceability work — you'll use it in Lab 6.

---

## Verify checklist

- ✅ Saw a preview that created nothing
- ✅ Confirmed and created real work items (got IDs + URLs)
- ✅ Found the created items via a query
- ✅ Previewed test cases
- ✅ Created a test case linked to a requirement

---

## What about requirements?

Notice this lab creates **work items and test cases**, not requirements. Requirements go through 📝 Plan Mode (Lab 4) — they deserve the full rigor and module binding, not a quick-create. If you ask `create_elm` to make DNG requirements, it previews + lints them but points you to Plan Mode for the actual write. That's intentional.

---

## Common pitfalls

**It created something I didn't want.** You confirmed too fast. Always read the preview first; only say "create them" when it's right. (There's no delete tool by design — destructive actions shouldn't be one careless sentence away.)

**The cross-link didn't attach.** Make sure the requirement ID resolves (try "what's req <ID>" first). The link needs a valid target.

---

## Try it yourself

Preview a batch without creating, just to see the quality check on requirement-style text:

```
Preview requirements: "the system shall respond within 200ms" and "the page should be fast", for <your project>.
```

Watch the lint flag the vague "should be fast" — even in a preview.

---

## What's next

→ [Lab 6: Connect the chain](../lab-06-connect-the-chain/)

You can create reqs, tasks, and tests. Next: link them into a traceability chain — requirement → task → test — and see your coverage.
