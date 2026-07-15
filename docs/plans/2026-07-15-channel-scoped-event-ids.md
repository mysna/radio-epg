# Channel-scoped Event IDs Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent multi-channel schedule imports from violating D1's `(source_id, source_event_id)` uniqueness constraint.

**Architecture:** Scope event IDs at the common adapter normalization boundary using the upstream channel code. Keep the database schema and Worker ingestion contract unchanged.

**Tech Stack:** Python 3.13, Pydantic, pytest

---

### Task 1: Reproduce cross-channel event ID collisions

**Files:**
- Modify: `tests/adapters/test_html_schedule.py`

1. Add a test that passes the same `ScheduleRow.upstream_id` through two mapped channels.
2. Assert the resulting `source_event_id` values are channel-scoped and distinct.
3. Run the focused test and verify it fails because both IDs currently equal the raw upstream ID.

### Task 2: Scope normalized event IDs

**Files:**
- Modify: `src/radio_epg/adapters/html_schedule.py`

1. Set `source_event_id` to `f"{upstream_code}:{row.upstream_id}"`.
2. Run the focused test and verify it passes.
3. Run all adapter tests and update only expectations whose contract intentionally changes.

### Task 3: Verify the repository

**Files:**
- No additional files expected

1. Run the complete Python test suite.
2. Review the diff for unrelated changes.
3. Report the exact verification results and note that production confirmation requires deployment plus a new collection run.
