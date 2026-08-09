# TBN Gwangju Region Name Fix Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restore TBN collection after the official Gwangju region label changed to `전남광주`.

**Architecture:** Keep the existing date, page-code, and selected-region validation. Update only the
official Gwangju label contract and add an HTML fixture regression test that exercises the real parser.

**Tech Stack:** Python 3.12, BeautifulSoup, pytest, Ruff, ty

---

### Task 1: Add the Gwangju regression test

**Files:**
- Create: `tests/fixtures/tbn/schedule_gwangju.html`
- Modify: `tests/adapters/test_tbn.py`

**Step 1: Write the failing test**

Add a minimal fixture with `page_code=3`, selected region `전남광주`, and one valid schedule row. Add a
test that parses it with `station_code="gwangju"` and checks the resulting upstream ID.

**Step 2: Run test to verify it fails**

Run: `UV_CACHE_DIR=/tmp/radio-epg-uv-cache uv run pytest tests/adapters/test_tbn.py::test_tbn_html_parser_accepts_official_gwangju_region_name -v`

Expected: FAIL with `TBN response region does not match the requested region`.

### Task 2: Update the official region label

**Files:**
- Modify: `src/radio_epg/adapters/tbn.py`

**Step 1: Write minimal implementation**

Change `_STATION_NAMES["gwangju"]` from `광주` to `전남광주`.

**Step 2: Run focused tests**

Run: `UV_CACHE_DIR=/tmp/radio-epg-uv-cache uv run pytest tests/adapters/test_tbn.py -v`

Expected: all TBN adapter tests PASS.

### Task 3: Verify the repository

**Files:** None

**Step 1: Run all Python tests**

Run: `UV_CACHE_DIR=/tmp/radio-epg-uv-cache uv run pytest`

**Step 2: Run static checks**

Run: `UV_CACHE_DIR=/tmp/radio-epg-uv-cache uv run ruff check .`

Run: `UV_CACHE_DIR=/tmp/radio-epg-uv-cache uv run ruff format --check .`

Run: `UV_CACHE_DIR=/tmp/radio-epg-uv-cache uvx ty check`

Expected: every command exits successfully.
