# Partial `/v1/now` Batch Results Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Return valid current-program entries even when the same batch contains an unregistered radio ID.

**Architecture:** Preserve the existing sequential lookup and request ordering. Convert a failed channel lookup from a request-level `404` into a result-level `not_found` entry, while leaving request validation and registered-channel behavior unchanged.

**Tech Stack:** TypeScript, Hono, Cloudflare Workers, Vitest

---

### Task 1: Define and implement partial batch behavior

**Files:**
- Modify: `worker/test/public-api.test.ts`
- Modify: `worker/src/routes/now.ts`

**Step 1: Write the failing test**

Add a test that requests `${RADIO_ID},missing`, expects HTTP `200`, two ordered results, the existing valid result, and this second result:

```ts
{
  radio_id: "missing",
  channel_id: null,
  status: "not_found",
  current: null,
  next: null,
}
```

**Step 2: Run the test to verify it fails**

Run: `npm test -- --run worker/test/public-api.test.ts` from `worker/`.

Expected: FAIL because the endpoint currently returns HTTP `404` and no result collection.

**Step 3: Write the minimal implementation**

In `worker/src/routes/now.ts`, replace the early `channel_not_found` response with an appended `not_found` result followed by `continue`.

**Step 4: Run the focused test to verify it passes**

Run: `npm test -- --run test/public-api.test.ts` from `worker/`.

Expected: PASS.

### Task 2: Document and verify the contract

**Files:**
- Modify: `docs/api.md`

**Step 1: Document `not_found`**

State that unregistered IDs do not fail the batch and are returned in request order with `status: "not_found"`, `channel_id: null`, `current: null`, and `next: null`.

**Step 2: Run Worker verification**

Run from `worker/`:

```bash
npm test -- --run
npm run typecheck
```

Expected: all tests pass and TypeScript reports no errors.

**Step 3: Review the diff**

Confirm only the approved route, regression test, API documentation, and plan documents changed for this task.
