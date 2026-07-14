# Additional Station Schedules Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Connect the user-provided official schedule URLs to the radio EPG source and regional mapping configuration, enabling verified stations while preserving existing data for unverified sources.

**Architecture:** Reuse the existing source registry and family adapters. Add exact official URLs to `data/sources.json` and `data/mappings/regional.json`; only change a mapping from unsupported to enabled after a fixture proves the common parser contract. Keep each source isolated so an unavailable page cannot publish an empty batch.

**Tech Stack:** Python 3.12, Pydantic, httpx, pytest, JSON configuration, existing HTML schedule normalizer.

---

### Task 1: Add source URL configuration

**Files:**
- Modify: `data/sources.json`
- Test: `tests/test_registry.py`

**Step 1:** Add source entries for OBS, iFM, YTN, TBS, FEBC, BBS, CPBC, WBS, KFN, Gugak, and AFN using the supplied URLs and existing adapter families.

**Step 2:** Extend configuration tests to assert exact URLs, unique source IDs, and disabled-by-default status until fixture verification.

**Step 3:** Run `PYTHONPATH=src uv run pytest -q tests/test_registry.py tests/test_workflows.py`.

**Step 4:** Commit configuration and tests with `git commit -m "feat: register additional schedule sources"`.

### Task 2: Correct canonical mapping URLs

**Files:**
- Modify: `data/mappings/regional.json`
- Test: `tests/adapters/test_independent.py`, `tests/adapters/test_religious.py`, `tests/adapters/test_afn.py`

**Step 1:** Replace placeholder homepages with the user-provided schedule endpoints for existing channel IDs.

**Step 2:** Add assertions for the exact endpoint, including separate TBS FM/eFM and AFN Humphreys mapping.

**Step 3:** Run family mapping tests and coverage validation.

**Step 4:** Commit mapping changes.

### Task 3: Verify and implement parsers incrementally

**Files:**
- Create or modify: `src/radio_epg/adapters/*.py`
- Create: `tests/fixtures/<station>/*`
- Create or modify: `tests/adapters/test_*.py`

**Step 1:** Save representative official responses for each page that returns stable schedule markup.

**Step 2:** Write failing parser tests covering requested date, overnight times, program title, and canonical channel ownership.

**Step 3:** Implement the smallest station-specific parser or mapping parser needed for the fixture.

**Step 4:** Leave inaccessible, JS-only, image-only, or schema-unverified pages marked unsupported with the exact URL and a reason.

**Step 5:** Run each station test before enabling its source.

**Step 6:** Commit each verified station group.

### Task 4: Full validation and operational report

**Files:**
- Modify: `docs/source-coverage.md` if generated coverage changes
- Test: `tests/`

**Step 1:** Run `PYTHONPATH=src uv run pytest -q`.

**Step 2:** Run source loading, coverage, and fixture validation commands.

**Step 3:** Run a non-failing live smoke check against the 11 official URLs and record HTTP/parse status.

**Step 4:** Confirm no unsupported or empty result can delete prior schedule rows.

**Step 5:** Report enabled stations, deferred stations, tests, and any inability to commit caused by the workspace Git restriction.
