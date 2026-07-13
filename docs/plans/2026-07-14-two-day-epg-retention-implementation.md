# Two-Day EPG Collection and Retention Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Collect only KST today and tomorrow, keep only those two broadcast dates in D1, and remove the remaining production import contract failures.

**Architecture:** The Python collector owns the KST two-day request window. The authenticated Worker retention endpoint independently derives KST today and tomorrow and deletes schedule rows outside that closed date range. Source adapters normalize upstream IDs and URLs before the existing publisher partitions validated imports by scope, count, and byte limits.

**Tech Stack:** Python 3.12, Pydantic, httpx, BeautifulSoup, pytest, TypeScript, Hono, Cloudflare D1, Vitest

---

### Task 1: Change the collector to a two-day KST window

**Files:**
- Modify: `src/radio_epg/collector.py:124-128`
- Modify: `tests/test_collector.py:78-104`
- Modify: `tests/integration/test_collection_import.py:113-130`

**Step 1: Write the failing tests**

Change the default-window test to assert exactly today and tomorrow across a UTC/KST boundary:

```python
assert adapter.windows == [CollectionWindow(date(2030, 1, 1), date(2030, 1, 2))]
```

Keep the injected-date test and integration fixture aligned with the same closed two-date window.

**Step 2: Run the tests to verify RED**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q \
  tests/test_collector.py \
  tests/integration/test_collection_import.py
```

Expected: FAIL because `Collector.collect()` still ends the window at `first_day + 7 days`.

**Step 3: Implement the minimal window change**

In `Collector.collect()`:

```python
"""KST 오늘과 내일의 각 adapter를 독립 실행한다."""
first_day = self._today()
window = CollectionWindow(first_day, first_day + timedelta(days=1))
```

Do not change `_korean_today()` or the injectable `today` callback.

**Step 4: Verify GREEN and static checks**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q \
  tests/test_collector.py \
  tests/integration/test_collection_import.py
UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/radio_epg/collector.py tests/test_collector.py
UV_CACHE_DIR=/tmp/uv-cache uv run ty check
git diff --check
```

Expected: all selected tests and checks pass.

**Step 5: Commit**

```bash
git add src/radio_epg/collector.py tests/test_collector.py tests/integration/test_collection_import.py
git commit -m "fix: collect today and tomorrow schedules"
```

### Task 2: Retain only KST today and tomorrow

**Files:**
- Modify: `worker/src/retention.ts:8-26`
- Modify: `worker/test/retention.test.ts`
- Modify: `docs/api.md:70-88`
- Modify: `docs/database.md:28-35`
- Modify: `README.md:200-210`

**Step 1: Rewrite the retention fixture and failing assertions**

Seed four events with broadcast dates relative to a frozen KST date:

- yesterday: delete;
- today: preserve even if `ends_at` is already in the past;
- tomorrow: preserve;
- day after tomorrow: delete.

Freeze `now` at `2026-07-13T15:30:00Z`, which is `2026-07-14 00:30 KST`, and assert:

```typescript
expect(result).toEqual({
  start_date: "2026-07-14",
  end_date: "2026-07-15",
  deleted: 2,
});
expect(remainingIds).toEqual(["retention-today", "retention-tomorrow"]);
```

Update the authenticated endpoint assertion to match `start_date` and `end_date`.

**Step 2: Run the Worker retention test to verify RED**

Run:

```bash
npm --prefix worker test -- --run test/retention.test.ts
```

Expected: FAIL because retention still uses `ends_at < now - 30 days`.

**Step 3: Implement KST calendar bounds**

Replace the 30-day cutoff with helpers that derive a calendar date using
`Intl.DateTimeFormat(..., { timeZone: "Asia/Seoul" }).formatToParts(now)` and add one calendar day safely.

Use this D1 statement:

```sql
DELETE FROM schedule_events
WHERE broadcast_date < ? OR broadcast_date > ?
```

Bind KST today and tomorrow. Return:

```typescript
return { start_date: startDate, end_date: endDate, deleted: result.meta.changes };
```

Programs, channels, aliases, and image metadata remain untouched.

**Step 4: Update documentation**

Replace all operational 30-day retention descriptions in `README.md`,
`docs/api.md`, and `docs/database.md` with the closed KST today/tomorrow range.
Document that retention deletes both older dates and dates after tomorrow.

**Step 5: Verify GREEN**

Run:

```bash
npm --prefix worker test -- --run test/retention.test.ts
npm --prefix worker run typecheck
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_readme.py tests/test_workflows.py
git diff --check
```

Expected: all checks pass.

**Step 6: Commit**

```bash
git add worker/src/retention.ts worker/test/retention.test.ts README.md docs/api.md docs/database.md
git commit -m "fix: retain only today and tomorrow schedules"
```

### Task 3: Make KBS source event IDs globally unique

**Files:**
- Modify: `src/radio_epg/adapters/kbs.py:260-295`
- Modify: `tests/adapters/test_kbs.py`
- Modify: `tests/fixtures/e2e/kbs-import.json`

**Step 1: Write the failing uniqueness test**

Create or mutate fixture payload groups so two canonical channels reuse the same
upstream `schedule_unique_id`. Assert that normalized IDs are unique and retain
the upstream ID as a suffix:

```python
source_event_ids = [event.source_event_id for event in result.schedules]
assert len(source_event_ids) == len(set(source_event_ids))
assert all(event_id and event_id.endswith(":9001") for event_id in selected_ids)
```

Update existing exact-ID assertions and the E2E import fixture to the composite
format.

**Step 2: Run the KBS tests to verify RED**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q \
  tests/adapters/test_kbs.py \
  tests/integration/test_collection_import.py
```

Expected: FAIL because the adapter currently publishes only
`str(schedule_unique_id)`.

**Step 3: Implement the composite source event ID**

Build the ID from canonical channel identity plus upstream schedule identity:

```python
source_event_id = ":".join(
    (
        mapping.channel_id,
        item.program_planned_date,
        item.program_planned_start_time,
        str(item.schedule_unique_id),
    )
)
```

Use that value only for `ScheduleCandidate.source_event_id`; keep KBS program
identity based on `program_code`.

**Step 4: Verify GREEN and live two-day uniqueness**

Run the focused tests, then an opt-in live diagnostic that collects KBS today
and tomorrow and asserts all non-null source event IDs are unique.

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q \
  tests/adapters/test_kbs.py \
  tests/integration/test_collection_import.py
```

Expected: tests pass and live duplicate count is zero.

**Step 5: Commit**

```bash
git add src/radio_epg/adapters/kbs.py tests/adapters/test_kbs.py \
  tests/fixtures/e2e/kbs-import.json
git commit -m "fix: scope KBS event identities"
```

### Task 4: Normalize EBS and CBS homepage URLs

**Files:**
- Modify: `src/radio_epg/adapters/ebs.py:1-75`
- Modify: `src/radio_epg/adapters/cbs.py:1-88`
- Modify: `tests/adapters/test_ebs.py`
- Modify: `tests/adapters/test_cbs.py`
- Modify: `tests/fixtures/ebs/fm.html`
- Modify: `tests/fixtures/cbs/official-schedule.html`

**Step 1: Add failing URL contract tests**

Use a protocol-relative EBS link and a root-relative CBS link in the reduced
official fixtures. Assert absolute results:

```python
assert ebs_rows[0].homepage_url == "https://home.ebs.co.kr/example"
assert cbs_rows[0].homepage_url == "https://www.cbs.co.kr/radio/example"
```

**Step 2: Run the adapter tests to verify RED**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q \
  tests/adapters/test_ebs.py \
  tests/adapters/test_cbs.py
```

Expected: FAIL with the unchanged relative or protocol-relative strings.

**Step 3: Resolve URLs against official HTTPS origins**

Import `urljoin` from `urllib.parse`.

For EBS:

```python
homepage = (
    urljoin("https://www.ebs.co.kr/", str(homepage_node["href"]))
    if homepage_node is not None
    else None
)
```

For CBS:

```python
homepage = (
    urljoin("https://www.cbs.co.kr/", str(title_node["href"]))
    if title_node is not None and title_node.has_attr("href")
    else None
)
```

**Step 4: Verify GREEN and live URL validity**

Run focused tests and collect one KST date from each source. Assert every
non-null homepage URL has an `https` scheme and hostname.

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q \
  tests/adapters/test_ebs.py \
  tests/adapters/test_cbs.py
UV_CACHE_DIR=/tmp/uv-cache uv run ruff check \
  src/radio_epg/adapters/ebs.py src/radio_epg/adapters/cbs.py
```

Expected: tests pass and live invalid URL count is zero.

**Step 5: Commit**

```bash
git add src/radio_epg/adapters/ebs.py src/radio_epg/adapters/cbs.py \
  tests/adapters/test_ebs.py tests/adapters/test_cbs.py \
  tests/fixtures/ebs/fm.html tests/fixtures/cbs/official-schedule.html
git commit -m "fix: normalize broadcaster homepage URLs"
```

### Task 5: Verify, deploy, and prove the production outcome

**Files:**
- Verify only unless a failing check requires a targeted correction.

**Step 1: Run the exact full quality suite**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run ruff check --fix .
UV_CACHE_DIR=/tmp/uv-cache uv run ruff format .
UV_CACHE_DIR=/tmp/uv-cache uv run ty check
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q
npm --prefix worker test -- --run
npm --prefix worker run typecheck
git diff --check
git status --short --branch
```

Expected: all Python and Worker tests pass and the worktree is clean after task
commits.

**Step 2: Run a read-only live two-day collection**

Use all enabled adapters with a no-op publisher. Verify every source succeeds,
the report window is KST today through tomorrow, and the KBS source event IDs
are unique.

**Step 3: Request final code review**

Use `superpowers:requesting-code-review` over the range from `1c0a72c` to the
current HEAD. Resolve every Critical or Important finding before pushing. If the
review subagent is unavailable because of the known model error, record that
fact and perform an explicit local diff review against this plan.

**Step 4: Push and monitor GitHub Actions**

```bash
git push origin main
```

Confirm both `CI` and `Deploy Worker` succeed. Trigger `Collect schedules` and
monitor collection, retention, and diagnostics steps.

**Step 5: Verify production data bounds**

Check public API coverage for every enabled source. Query D1 through Wrangler or
an authenticated diagnostic path and verify:

```sql
SELECT MIN(broadcast_date), MAX(broadcast_date), COUNT(*)
FROM schedule_events;
```

Expected: min is KST today, max is KST tomorrow, and all enabled source IDs are
available. Run the public smoke command for the existing Busan KBS radio ID.

**Step 6: Report the final checkpoint**

Report per-task commits, test totals, live source counts, GitHub run URLs,
production date bounds, and any intentionally deferred work such as image
download/upload wiring.
