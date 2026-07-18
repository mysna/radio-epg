# SBS Date-Scoped Event IDs Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent recurring SBS imports from colliding with the previous day's events while preserving same-day idempotency.

**Architecture:** Add the broadcast date to event IDs at the shared HTML/JSON schedule normalization boundary. Cover both cross-channel and cross-date uniqueness with adapter regression tests; leave the D1 uniqueness contract unchanged.

**Tech Stack:** Python 3.12, pytest, Pydantic, Cloudflare Worker/D1 tests

---

### Task 1: Reproduce cross-date SBS event collisions

**Files:**
- Modify: `tests/adapters/test_sbs.py`

**Step 1: Write the failing test**

Add a test that normalizes the same SBS channel and upstream ID on two dates and asserts distinct date-scoped IDs.

**Step 2: Run test to verify it fails**

Run: `UV_CACHE_DIR=/tmp/radio-epg-uv-cache uv run pytest tests/adapters/test_sbs.py -q`

Expected: FAIL because both normalized values are `power:<upstream-id>`.

### Task 2: Scope normalized event IDs by date

**Files:**
- Modify: `src/radio_epg/adapters/html_schedule.py`
- Modify: `tests/adapters/test_sbs.py`

**Step 1: Write minimal implementation**

Build `source_event_id` as `f"{upstream_code}:{row.broadcast_date.isoformat()}:{row.upstream_id}"`.

**Step 2: Update the existing channel-scope assertion**

Expect the broadcast date in both IDs.

**Step 3: Run focused tests**

Run: `UV_CACHE_DIR=/tmp/radio-epg-uv-cache uv run pytest tests/adapters/test_sbs.py -q`

Expected: PASS.

### Task 3: Verify repository behavior

**Files:**
- Verify only

**Step 1: Run the full Python suite**

Run: `UV_CACHE_DIR=/tmp/radio-epg-uv-cache uv run pytest -q`

Expected: all tests pass.

**Step 2: Run Worker tests**

Run from `worker/`: `XDG_CONFIG_HOME=/tmp/radio-epg-wrangler npm test -- --run`

Expected: all tests pass.

**Step 3: Review the diff**

Confirm only the event-ID contract, regression tests, and plan documents changed.
