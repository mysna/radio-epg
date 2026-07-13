# Radio EPG API Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a daily Korean radio schedule collector and a free Cloudflare-hosted API that is compatible with the existing radio player and serves cached broadcaster, channel, and program images.

**Architecture:** A Python application running in GitHub Actions collects and normalizes broadcaster data, then sends idempotent authenticated batches to a TypeScript Cloudflare Worker. The Worker stores relational data in D1, stores image objects in R2, and exposes cached public read APIs using both stable channel IDs and current radio player aliases.

**Tech Stack:** Python 3.12, uv, httpx, Pydantic, Beautiful Soup, pypdf, Pillow, CairoSVG, pytest, Ruff, ty, TypeScript, Hono, Zod, Cloudflare Workers, D1, R2, Wrangler, Vitest, GitHub Actions

---

## Implementation Rules

- Follow `../AGENTS.md`, especially documentation-first development and the
  verification order `ruff check --fix`, `ruff format`, `ty check`, tests.
- Never use a live broadcaster response as the only test input. Reduce and
  commit deterministic fixtures for every enabled adapter.
- Never replace a valid schedule with an empty or structurally invalid batch.
- Do not enable an adapter until its catalog mappings and fixtures pass.
- Use structured parsers for JSON, JSONP, HTML, PDF, and XML. Do not parse those
  formats with ad hoc regular expressions.
- Keep the current `/home/mysna/workspace/radio` checkout read-only. Copy only a
  generated channel snapshot into this repository.
- Re-check current Cloudflare and GitHub documentation before writing commands
  that depend on product UI names or quotas.

### Task 1: Scaffold the Python Collector and Worker

**Files:**
- Create: `pyproject.toml`
- Create: `src/radio_epg/__init__.py`
- Create: `src/radio_epg/cli.py`
- Create: `tests/test_cli.py`
- Create: `worker/package.json`
- Create: `worker/tsconfig.json`
- Create: `worker/wrangler.toml`
- Create: `worker/src/index.ts`
- Create: `worker/test/index.test.ts`
- Create: `.gitignore`
- Create: `TODO.md`

**Step 1: Write failing Python and Worker smoke tests**

```python
# tests/test_cli.py
from radio_epg.cli import app_name


def test_app_name() -> None:
    assert app_name() == "radio-epg"
```

```ts
// worker/test/index.test.ts
import { describe, expect, it } from "vitest";
import app from "../src/index";

describe("health", () => {
  it("returns the service name", async () => {
    const response = await app.request("http://example.test/health");
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ service: "radio-epg" });
  });
});
```

**Step 2: Run the tests and verify they fail**

Run:

```bash
uv run pytest tests/test_cli.py -q
npm --prefix worker test -- --run
```

Expected: Python import failure and missing Worker package configuration.

**Step 3: Add the minimal project configuration**

Configure `pyproject.toml` with Python 3.12, a `src` package, and these runtime
dependencies: `beautifulsoup4`, `cairosvg`, `defusedxml`, `httpx`, `pillow`,
`pydantic`, `pypdf`. Add `pytest`, `respx`, `ruff`, and `ty` as development
dependencies. Configure Ruff for Python 3.12 and a 100-column limit.

Configure the Worker with `hono` and `zod`, and development dependencies
`@cloudflare/vitest-pool-workers`, `typescript`, `vitest`, and `wrangler`.
Export a Hono app with only `GET /health` implemented.

`worker/wrangler.toml` must declare placeholder D1 and R2 bindings named `DB`
and `IMAGES`; do not commit a real database ID.

**Step 4: Run smoke tests and quality checks**

Run:

```bash
uv run ruff check --fix .
uv run ruff format .
uvx ty check
uv run pytest -q
npm --prefix worker test -- --run
npm --prefix worker run typecheck
```

Expected: all commands pass.

**Step 5: Commit**

```bash
git add pyproject.toml uv.lock src tests worker .gitignore TODO.md
git commit -m "chore: scaffold collector and worker"
```

### Task 2: Import and Normalize the Radio Channel Catalog

**Files:**
- Create: `scripts/sync_radio_catalog.mjs`
- Create: `data/radio_channels.json`
- Create: `src/radio_epg/ids.py`
- Create: `src/radio_epg/catalog.py`
- Create: `tests/test_ids.py`
- Create: `tests/test_catalog.py`

**Step 1: Write failing identifier tests**

```python
from radio_epg.ids import canonical_channel_id, tuple_alias


def test_canonical_channel_id_includes_city() -> None:
    assert canonical_channel_id("kbs", "1radio", "busan") == "kbs.1radio.busan"


def test_canonical_channel_id_uses_main_defaults() -> None:
    assert canonical_channel_id("obs", None, None) == "obs.main.main"


def test_tuple_alias_distinguishes_missing_values() -> None:
    assert tuple_alias("tbn", None, "busan") == "tbn/main/busan"
```

Write catalog tests asserting 226 radio aliases, 194 canonical channel records,
and preservation of a known current player ID.

**Step 2: Run tests and verify they fail**

Run: `uv run pytest tests/test_ids.py tests/test_catalog.py -q`

Expected: missing modules and data file.

**Step 3: Implement a structured catalog export**

The Node script must dynamically import the `channels.js` module passed as its
first argument and serialize only `CHANNELS` fields. It must not parse JavaScript
source text. Run it explicitly:

```bash
node scripts/sync_radio_catalog.mjs /home/mysna/workspace/radio/src/channels.js data/radio_channels.json
```

Implement lowercase ASCII ID segments, `main` defaults, tuple aliases, duplicate
canonical-channel folding, and preservation of every radio ID as an alias.

**Step 4: Verify catalog compatibility**

Run:

```bash
uv run pytest tests/test_ids.py tests/test_catalog.py -q
git diff --exit-code -- data/radio_channels.json
```

Expected: 226 aliases, 194 canonical channels, and deterministic generated JSON.

**Step 5: Commit**

```bash
git add scripts data src/radio_epg/ids.py src/radio_epg/catalog.py tests
git commit -m "feat: import radio channel catalog"
```

### Task 3: Define Normalized Models and Broadcast Time Handling

**Files:**
- Create: `src/radio_epg/models.py`
- Create: `src/radio_epg/broadcast_time.py`
- Create: `src/radio_epg/validation.py`
- Create: `tests/test_models.py`
- Create: `tests/test_broadcast_time.py`
- Create: `tests/test_validation.py`

**Step 1: Write failing model and time tests**

Cover:

- `2026-07-13 25:30` becoming `2026-07-14T01:30:00+09:00` while keeping
  `broadcast_date = 2026-07-13`.
- events whose end time crosses midnight.
- rejection of zero/negative duration.
- rejection of empty titles.
- detection of conflicting overlaps from one source.
- acceptance of nested or adjacent events only when the adapter declares them.

Example:

```python
def test_extended_hour_preserves_broadcast_date() -> None:
    parsed = parse_broadcast_time(date(2026, 7, 13), "25:30")
    assert parsed.isoformat() == "2026-07-14T01:30:00+09:00"
```

**Step 2: Run tests and verify they fail**

Run: `uv run pytest tests/test_models.py tests/test_broadcast_time.py tests/test_validation.py -q`

Expected: missing model and parser modules.

**Step 3: Implement minimal typed models**

Create Pydantic models for `Channel`, `ProgramCandidate`, `ScheduleCandidate`,
`ImageCandidate`, `AdapterResult`, `SourceMetadata`, and `ImportBatch`. Use aware
datetimes only. Store UTC instants in serialized batches and the original KST
broadcast date separately.

**Step 4: Run focused and full checks**

Run:

```bash
uv run pytest tests/test_models.py tests/test_broadcast_time.py tests/test_validation.py -q
uv run ruff check --fix .
uv run ruff format .
uvx ty check
```

Expected: all pass.

**Step 5: Commit**

```bash
git add src/radio_epg tests
git commit -m "feat: add schedule domain models"
```

### Task 4: Create the D1 Schema and Migration Tests

**Files:**
- Create: `worker/migrations/0001_initial.sql`
- Create: `worker/src/db.ts`
- Create: `worker/test/migrations.test.ts`
- Create: `docs/database.md`

**Step 1: Write a failing migration integration test**

The test must apply migrations to the Worker test D1 binding and verify:

- the core and image tables from the design document exist;
- duplicate aliases fail;
- invalid schedule duration fails;
- repeated import idempotency keys fail;
- schedule lookup uses the `(channel_id, starts_at)` index.

**Step 2: Run the migration test and verify it fails**

Run: `npm --prefix worker test -- --run migrations.test.ts`

Expected: missing migration/table errors.

**Step 3: Implement the schema**

Create tables `broadcasters`, `channels`, `channel_aliases`, `programs`,
`schedule_events`, `sources`, `scrape_runs`, `image_assets`, `image_variants`, and
`image_takedowns`. Use foreign keys, unique constraints, explicit indexes, and
`CHECK (ends_at > starts_at)`.

Document ownership, retention, idempotency, and why image bytes do not belong in
D1.

**Step 4: Run Worker tests and type checking**

Run:

```bash
npm --prefix worker test -- --run
npm --prefix worker run typecheck
```

Expected: all pass.

**Step 5: Commit**

```bash
git add worker/migrations worker/src/db.ts worker/test docs/database.md
git commit -m "feat: add D1 data model"
```

### Task 5: Implement Public Channel and Schedule APIs

**Files:**
- Create: `worker/src/types.ts`
- Create: `worker/src/errors.ts`
- Create: `worker/src/repositories/channels.ts`
- Create: `worker/src/repositories/schedules.ts`
- Create: `worker/src/routes/channels.ts`
- Create: `worker/src/routes/schedules.ts`
- Create: `worker/src/routes/now.ts`
- Create: `worker/src/routes/coverage.ts`
- Modify: `worker/src/index.ts`
- Create: `worker/test/public-api.test.ts`
- Create: `docs/api.md`

**Step 1: Write failing route tests**

Test canonical lookup, current `radio_id` lookup, tuple alias lookup, date range,
current/next selection, multiple `radio_ids`, missing schedule data, stable error
envelopes, CORS allow/deny behavior, ETag/304, and stale/source metadata.

```ts
expect(await response.json()).toMatchObject({
  channel_id: "kbs.1radio.busan",
  current: { title: "KBS 뉴스" },
  next: { title: "다음 프로그램" },
});
```

**Step 2: Run tests and verify they fail**

Run: `npm --prefix worker test -- --run public-api.test.ts`

Expected: route-not-found failures.

**Step 3: Implement repository and route modules**

Implement only the routes approved in the design. Limit batch `radio_ids` to 100,
validate `YYYY-MM-DD`, use indexed queries, return `unavailable` rather than a
fabricated event, and set cache headers appropriate to each route.

**Step 4: Document and verify the API contract**

Add request/response examples and error codes to `docs/api.md`.

Run:

```bash
npm --prefix worker test -- --run
npm --prefix worker run typecheck
```

Expected: all pass.

**Step 5: Commit**

```bash
git add worker/src worker/test docs/api.md
git commit -m "feat: expose radio schedule API"
```

### Task 6: Add Authenticated Idempotent Ingestion

**Files:**
- Create: `worker/src/auth.ts`
- Create: `worker/src/import-schema.ts`
- Create: `worker/src/routes/admin-import.ts`
- Create: `worker/test/admin-import.test.ts`
- Modify: `worker/src/index.ts`
- Create: `src/radio_epg/publisher.py`
- Create: `tests/test_publisher.py`

**Step 1: Write failing authentication and idempotency tests**

Cover missing/wrong bearer tokens, request size limit, schema rejection, first
import, identical re-import, changed source batch, partial failure rollback, and
the rule that an empty invalid batch cannot erase existing events.

**Step 2: Run tests and verify they fail**

Run:

```bash
npm --prefix worker test -- --run admin-import.test.ts
uv run pytest tests/test_publisher.py -q
```

Expected: missing route and publisher.

**Step 3: Implement the ingestion boundary**

Use `Authorization: Bearer <INGEST_TOKEN>`, constant-time comparison, Zod body
validation, bounded batch sizes, and D1 batch operations. Upsert stable entities
and replace events only inside the validated source/channel/date scope.

Implement an `httpx` publisher with explicit timeouts and bounded retries for
transient errors only. Never log the token or full imported payload.

**Step 4: Run all ingestion checks**

Run:

```bash
npm --prefix worker test -- --run
npm --prefix worker run typecheck
uv run pytest tests/test_publisher.py -q
uvx ty check
```

Expected: all pass.

**Step 5: Commit**

```bash
git add worker/src worker/test src/radio_epg/publisher.py tests/test_publisher.py
git commit -m "feat: add authenticated schedule ingestion"
```

### Task 7: Build the Collector Runtime and Adapter Protocol

**Files:**
- Create: `src/radio_epg/config.py`
- Create: `src/radio_epg/http.py`
- Create: `src/radio_epg/adapters/__init__.py`
- Create: `src/radio_epg/adapters/base.py`
- Create: `src/radio_epg/registry.py`
- Create: `src/radio_epg/collector.py`
- Modify: `src/radio_epg/cli.py`
- Create: `data/sources.json`
- Create: `tests/test_http.py`
- Create: `tests/test_registry.py`
- Create: `tests/test_collector.py`

**Step 1: Write failing orchestration tests**

Use fake adapters to prove:

- one adapter failure does not stop later adapters;
- per-host rate limiting is applied;
- only validated results are published;
- empty results preserve prior data and report failure;
- today plus seven days is requested;
- a scrape-run summary contains counts, timing, and sanitized errors.

**Step 2: Run tests and verify they fail**

Run: `uv run pytest tests/test_http.py tests/test_registry.py tests/test_collector.py -q`

Expected: missing runtime modules.

**Step 3: Implement explicit interfaces and configuration**

Define an adapter `Protocol` with source metadata and `collect(window)` methods.
Add an HTTP client with a descriptive user agent, connect/read timeouts,
conditional request headers, bounded exponential retry, and per-host delay.
Load credentials only from environment variables.

Add CLI commands:

```text
radio-epg collect --all
radio-epg collect --source kbs
radio-epg validate-fixtures
radio-epg coverage
```

**Step 4: Run focused and quality checks**

Run:

```bash
uv run pytest tests/test_http.py tests/test_registry.py tests/test_collector.py -q
uv run ruff check --fix .
uv run ruff format .
uvx ty check
```

Expected: all pass.

**Step 5: Commit**

```bash
git add src/radio_epg data/sources.json tests
git commit -m "feat: add collection runtime"
```

### Task 8: Implement KBS as the Reference Adapter

**Files:**
- Create: `src/radio_epg/adapters/kbs.py`
- Create: `data/mappings/kbs.json`
- Create: `tests/fixtures/kbs/weekly.json`
- Create: `tests/fixtures/kbs/empty.json`
- Create: `tests/fixtures/kbs/schema-change.json`
- Create: `tests/adapters/test_kbs.py`
- Modify: `data/sources.json`

**Step 1: Capture and reduce legal test fixtures**

Use the official KBS weekly endpoint used by <https://schedule.kbs.co.kr/>. Keep
only the minimum fields and a few synthetic/redacted program records needed to
exercise channel codes, regional station codes, extended hours, images, and
rerun/live flags.

**Step 2: Write failing adapter contract tests**

Assert mapping for national and regional KBS channels, stable upstream event IDs,
program image candidates, extended-hour parsing, empty response rejection, and a
clear schema-change error.

**Step 3: Run tests and verify they fail**

Run: `uv run pytest tests/adapters/test_kbs.py -q`

Expected: missing KBS adapter.

**Step 4: Implement and register the adapter**

Call the structured endpoint with `local_station_code`, `channel_code`,
`program_planned_date_from`, and `program_planned_date_to`. Parse JSON with
Pydantic boundary models and map every covered KBS catalog identity.

**Step 5: Run deterministic tests and an opt-in live probe**

Run:

```bash
uv run pytest tests/adapters/test_kbs.py -q
RADIO_EPG_LIVE_TESTS=1 uv run pytest tests/live/test_kbs.py -q
```

Expected: fixture tests always pass; the live probe passes when network access is
available and otherwise remains excluded from the normal suite.

**Step 6: Commit**

```bash
git add src/radio_epg/adapters/kbs.py data tests
git commit -m "feat: collect KBS schedules"
```

### Task 9: Implement Image Discovery, Transformation, and Takedown

**Files:**
- Create: `src/radio_epg/images/__init__.py`
- Create: `src/radio_epg/images/discovery.py`
- Create: `src/radio_epg/images/download.py`
- Create: `src/radio_epg/images/transform.py`
- Create: `src/radio_epg/images/rights.py`
- Create: `tests/images/test_discovery.py`
- Create: `tests/images/test_download.py`
- Create: `tests/images/test_transform.py`
- Create: `worker/src/routes/admin-images.ts`
- Create: `worker/src/routes/admin-takedown.ts`
- Create: `worker/src/routes/images.ts`
- Create: `worker/test/images.test.ts`
- Create: `docs/images.md`

**Step 1: Write failing security and provenance tests**

Cover Wikimedia metadata, Namuwiki `og:image`, official-page fallback, unknown
rights, author/license attribution, host allowlisting, redirect revalidation,
MIME sniffing, decompression limits, SVG rasterization, transparent logos,
content-hash deduplication, three variants, R2 access, and takedown blocklisting.

**Step 2: Run tests and verify they fail**

Run:

```bash
uv run pytest tests/images -q
npm --prefix worker test -- --run images.test.ts
```

Expected: missing pipeline and routes.

**Step 3: Implement discovery and safe transformation**

Use the Wikimedia MediaWiki API for file metadata. Parse Namuwiki and official
pages as HTML, respect rate limits, and stop cleanly when blocked. Validate each
redirect host, cap bytes and pixels, re-encode raster inputs, and rasterize SVG
inputs before serving. Generate `small`, `medium`, and `original` variants while
preserving aspect ratio and transparency.

**Step 4: Implement R2 upload/read/delete and permanent blocking**

Image ingestion accepts metadata plus one validated variant per request. The
Worker writes R2 first, records D1 metadata second, and removes orphaned objects
if the metadata step fails. Takedown marks the asset unavailable before deleting
all objects and records both source URL and content hash.

**Step 5: Document policy and verify**

Run:

```bash
uv run pytest tests/images -q
npm --prefix worker test -- --run images.test.ts
uv run ruff check --fix .
uv run ruff format .
uvx ty check
npm --prefix worker run typecheck
```

Expected: all pass.

**Step 6: Commit**

```bash
git add src/radio_epg/images tests/images worker/src/routes worker/test docs/images.md
git commit -m "feat: cache and serve EPG images"
```

### Task 10: Add Major National Schedule Adapters

**Files:**
- Create: `src/radio_epg/adapters/mbc.py`
- Create: `src/radio_epg/adapters/sbs.py`
- Create: `src/radio_epg/adapters/ebs.py`
- Create: `src/radio_epg/adapters/cbs.py`
- Create: `src/radio_epg/adapters/tbn.py`
- Create: `src/radio_epg/adapters/html_schedule.py`
- Create: `src/radio_epg/adapters/pdf_schedule.py`
- Create: `data/mappings/{mbc,sbs,ebs,cbs,tbn}.json`
- Create: `tests/adapters/test_{mbc,sbs,ebs,cbs,tbn}.py`
- Create: `tests/fixtures/{mbc,sbs,ebs,cbs,tbn}/...`
- Modify: `data/sources.json`

**Step 1: Add reduced fixtures and failing adapter tests**

For each family, cover the currently supported channel codes, future-date
limitations, regional variants, image candidates, malformed inputs, and empty
responses. Treat JSONP with a real JSONP parser boundary that extracts exactly
one callback argument and then uses `json.loads`; do not evaluate JavaScript.

**Step 2: Run tests and verify they fail**

Run: `uv run pytest tests/adapters/test_mbc.py tests/adapters/test_sbs.py tests/adapters/test_ebs.py tests/adapters/test_cbs.py tests/adapters/test_tbn.py -q`

Expected: missing adapters.

**Step 3: Implement shared parsers and family adapters**

- MBC: central FM/FM4U/All That JSONP; regional pages stay disabled until their
  mappings are tested in Task 11.
- SBS: `power`, `love`, and `dmb` daily data; report unavailable future days
  rather than repeating today's special schedule.
- EBS: official FM schedule and separately verified Bandi data.
- CBS: central pages or PDFs for Standard FM, Music FM, and JOY4U.
- TBN: official regional schedules, with the public-data file only as a lower
  priority fallback.

**Step 4: Verify mappings and fixtures**

Run:

```bash
uv run radio-epg validate-fixtures
uv run pytest tests/adapters -q
uvx ty check
```

Expected: all enabled mappings pass and no adapter claims unsupported dates.

**Step 5: Commit**

```bash
git add src/radio_epg/adapters data tests/adapters tests/fixtures
git commit -m "feat: add national broadcaster adapters"
```

### Task 11: Add Regional and Independent Broadcaster Adapters

**Files:**
- Create: `src/radio_epg/adapters/regional_mbc.py`
- Create: `src/radio_epg/adapters/sbs_affiliates.py`
- Create: `src/radio_epg/adapters/febc.py`
- Create: `src/radio_epg/adapters/religious.py`
- Create: `src/radio_epg/adapters/independent.py`
- Create: `data/mappings/regional.json`
- Create: `tests/adapters/test_regional_mbc.py`
- Create: `tests/adapters/test_sbs_affiliates.py`
- Create: `tests/adapters/test_febc.py`
- Create: `tests/adapters/test_religious.py`
- Create: `tests/adapters/test_independent.py`
- Create: `tests/fixtures/regional/...`
- Modify: `data/sources.json`

**Step 1: Group stations by actual shared CMS**

Record source URL, parser type, covered `stn/ch/city` tuples, and evidence date in
`data/mappings/regional.json`. Do not create a separate parser class when two
stations use the same page structure.

**Step 2: Add fixtures and failing mapping tests**

Cover all catalog identities for regional MBCs, SBS affiliates, FEBC, BBS, CPBC,
WBS, KFN, Gugak, TBS, iFM, YTN, OBS, Arirang, BeFM, and GGN. A mapping may be
explicitly `unsupported`, but no identity may be silently omitted.

**Step 3: Implement shared-CMS adapters**

Use configuration for selectors, station/channel codes, and URLs. Keep parser
logic in shared modules and broadcaster-specific mapping in data files. Apply
official-source priority before any fallback data.

**Step 4: Verify full regional coverage accounting**

Run:

```bash
uv run radio-epg coverage --require-accounted
uv run pytest tests/adapters/test_regional_mbc.py tests/adapters/test_sbs_affiliates.py tests/adapters/test_febc.py tests/adapters/test_religious.py tests/adapters/test_independent.py -q
```

Expected: every relevant catalog identity is either fixture-tested and enabled
or explicitly marked unsupported with a reason and last investigation date.

**Step 5: Commit**

```bash
git add src/radio_epg/adapters data tests/adapters tests/fixtures/regional
git commit -m "feat: add regional radio adapters"
```

### Task 12: Add Community, AFN, Wiki Fallback, and OCR Sources

**Files:**
- Create: `src/radio_epg/adapters/community.py`
- Create: `src/radio_epg/adapters/afn.py`
- Create: `src/radio_epg/adapters/wiki_fallback.py`
- Create: `src/radio_epg/adapters/ocr_schedule.py`
- Create: `data/mappings/community.json`
- Create: `tests/adapters/test_community.py`
- Create: `tests/adapters/test_afn.py`
- Create: `tests/adapters/test_wiki_fallback.py`
- Create: `tests/adapters/test_ocr_schedule.py`
- Create: `tests/fixtures/community/...`
- Create: `docs/source-coverage.md`
- Modify: `data/sources.json`

**Step 1: Account for all 23 community identities and three AFN identities**

For each identity, record the official site, actual schedule format, primary and
fallback source, confidence, and the last verified date. Include current known
HTML sites, shared `communityradio.kr` CMS pages, PDF/image posts, and explicit
unsupported entries.

**Step 2: Write failing fallback and OCR tests**

Prove that official data wins, fallback fills only uncovered time ranges,
inferred recurring data is labeled, stale wiki pages are rejected, OCR rows must
pass strict time/title validation, and low-confidence OCR never overwrites valid
data.

**Step 3: Implement conservative fallback adapters**

Parse wiki pages only when a mapping declares the exact page and a freshness
check passes. AFN may use a common Eagle schedule with separately published
local inserts, but must not claim local content without evidence. OCR requires
Korean Tesseract support and emits candidates only above the configured
confidence threshold.

**Step 4: Generate the source coverage report and verify**

Run:

```bash
uv run radio-epg coverage --write docs/source-coverage.md --require-accounted
uv run pytest tests/adapters/test_community.py tests/adapters/test_afn.py tests/adapters/test_wiki_fallback.py tests/adapters/test_ocr_schedule.py -q
```

Expected: 194 canonical identities are accounted for; unsupported identities
remain visible and do not receive fabricated schedules.

**Step 5: Commit**

```bash
git add src/radio_epg/adapters data tests docs/source-coverage.md
git commit -m "feat: add fallback and community sources"
```

### Task 13: Add Daily Collection, Deployment, and Live-Probe Workflows

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/collect.yml`
- Create: `.github/workflows/deploy-worker.yml`
- Create: `.github/workflows/live-probe.yml`
- Create: `tests/test_workflows.py`

**Step 1: Write failing workflow structure tests**

Parse workflow YAML and assert:

- CI runs Python and Worker tests plus required quality checks.
- collection runs at `17 19 * * *`, supports `workflow_dispatch`, uses concurrency,
  and references only `EPG_API_BASE_URL` and `EPG_INGEST_TOKEN` for ingestion.
- deployment uses `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`.
- live probes are non-blocking and separate from deterministic CI.
- permissions are read-only except where strictly required.

**Step 2: Run tests and verify they fail**

Run: `uv run pytest tests/test_workflows.py -q`

Expected: missing workflows.

**Step 3: Implement workflows**

CI installs locked Python and Node dependencies. Collection installs Korean
Tesseract and Cairo runtime packages, runs exactly one daily collection, uploads
sanitized diagnostic artifacts on failure, and uses GitHub concurrency to
prevent overlapping imports. Deployment applies D1 migrations before deploying
the Worker and requires a protected GitHub environment when available.

**Step 4: Verify workflow syntax and tests**

Run:

```bash
uv run pytest tests/test_workflows.py -q
npm --prefix worker run typecheck
```

Expected: all pass.

**Step 5: Commit**

```bash
git add .github tests/test_workflows.py
git commit -m "ci: automate EPG collection and deployment"
```

### Task 14: Write the Complete README Deployment Guide

**Files:**
- Create: `README.md`
- Create: `.env.example`
- Create: `worker/.dev.vars.example`
- Create: `tests/test_readme.py`
- Modify: `TODO.md`

**Step 1: Write failing documentation contract tests**

Assert the README contains all of these exact configuration names and command
families:

```text
CLOUDFLARE_ACCOUNT_ID
CLOUDFLARE_API_TOKEN
EPG_API_BASE_URL
EPG_INGEST_TOKEN
INGEST_TOKEN
CORS_ORIGINS
wrangler d1 create
wrangler r2 bucket create
wrangler d1 migrations apply
wrangler secret put
wrangler deploy
workflow_dispatch
17 19 * * *
04:17 KST
```

Also assert it contains image takedown, free-tier monitoring, source adapter,
troubleshooting, and API example sections.

**Step 2: Run tests and verify they fail**

Run: `uv run pytest tests/test_readme.py -q`

Expected: missing README.

**Step 3: Write local development instructions**

Document prerequisites, repository layout, `uv sync`, Worker `npm install`, local
D1 migrations, `wrangler dev`, collector dry runs, fixture tests, the mandatory
quality command order, and example environment files. Mark placeholders such as
`<ACCOUNT_ID>` visibly and never include real credentials.

**Step 4: Write exact Cloudflare setup instructions**

Verify commands against current official docs, then document:

1. Create a Cloudflare account and enable Workers/R2.
2. Install/authenticate Wrangler.
3. Run `wrangler d1 create radio-epg` and copy its ID into the D1 binding.
4. Run `wrangler r2 bucket create radio-epg-images` and configure `IMAGES`.
5. Apply local and remote D1 migrations.
6. Run `wrangler secret put INGEST_TOKEN` with the same generated value later
   stored as GitHub `EPG_INGEST_TOKEN`.
7. Configure `CORS_ORIGINS` for `https://radio.bsod.kr` and local origins.
8. Create a least-privilege API token for Worker deployment and record current
   scope names.
9. Deploy and run health/API smoke requests.
10. Configure free-tier usage alerts and explain R2 Standard selection.

**Step 5: Write exact GitHub Actions setup instructions**

Document repository settings for:

- Secret `CLOUDFLARE_API_TOKEN`.
- Variable `CLOUDFLARE_ACCOUNT_ID`.
- Variable `EPG_API_BASE_URL`.
- Secret `EPG_INGEST_TOKEN`.
- Actions enablement, protected deployment environment, manual collection via
  `workflow_dispatch`, daily cron UTC/KST conversion, delayed-schedule caveat,
  and how to inspect artifacts and rerun a failed job.

**Step 6: Document operation and extension**

Add API curl examples for canonical and existing radio IDs, source coverage and
stale semantics, adding an adapter from fixtures, image provenance/attribution,
takedown/blocklist commands, D1/R2 backup considerations, quota monitoring, and
common Cloudflare/GitHub failure recovery.

**Step 7: Verify README and all docs**

Run:

```bash
uv run pytest tests/test_readme.py -q
git diff --check
```

Expected: documentation contract passes and no whitespace errors exist.

**Step 8: Commit**

```bash
git add README.md .env.example worker/.dev.vars.example TODO.md tests/test_readme.py
git commit -m "docs: add deployment and operations guide"
```

### Task 15: Add End-to-End Compatibility and Retention Tests

**Files:**
- Create: `tests/integration/test_collection_import.py`
- Create: `worker/test/e2e.test.ts`
- Create: `worker/src/retention.ts`
- Create: `worker/test/retention.test.ts`
- Modify: `src/radio_epg/cli.py`
- Modify: `docs/api.md`
- Modify: `README.md`

**Step 1: Write failing end-to-end tests**

Use a small fixture set to collect, validate, serialize, import, and query by a
real current radio player ID. Assert `current`, `next`, channel/program images,
source freshness, and stable aliases. Add retention tests that delete events
older than 30 days without deleting active programs, image metadata, or newer
events.

**Step 2: Run tests and verify they fail**

Run:

```bash
uv run pytest tests/integration/test_collection_import.py -q
npm --prefix worker test -- --run e2e.test.ts retention.test.ts
```

Expected: missing retention and end-to-end wiring.

**Step 3: Implement retention and smoke commands**

Add authenticated maintenance ingestion for retention, invoked at the end of the
daily workflow. Add CLI smoke checks for `/health`, `/v1/channels`, a known
`radio_id`, and `/v1/coverage`. Keep cleanup idempotent.

**Step 4: Run the mandatory complete verification sequence**

Run in this exact order:

```bash
uv run ruff check --fix .
uv run ruff format .
uvx ty check
uv run pytest -q
npm --prefix worker test -- --run
npm --prefix worker run typecheck
git diff --check
```

Expected: every command exits 0.

**Step 5: Run local Cloudflare smoke verification**

Apply migrations to local D1, start `wrangler dev`, import the small fixture
batch, and query it by both canonical ID and current radio ID. Verify returned
image bytes have the advertised MIME type and non-zero size.

**Step 6: Synchronize documentation and TODO state**

Update coverage counts, any unsupported source notes, actual commands, and known
limitations in `README.md`, `docs/api.md`, `docs/source-coverage.md`, and
`TODO.md` before the final commit.

**Step 7: Commit**

```bash
git add src worker tests README.md docs TODO.md
git commit -m "test: verify EPG service end to end"
```

## Completion Criteria

- All 226 current player aliases resolve to 194 accounted canonical channels.
- Every canonical channel is either supported by a tested adapter or explicitly
  reported as unsupported with a reason and verification date.
- Today plus seven days is returned when an upstream source provides it.
- Past events are retained for 30 days.
- Current and next program lookup works with current radio player IDs.
- Broadcaster, channel, and program image responses include provenance and
  support takedown/blocklisting.
- Daily collection and Worker deployment workflows pass deterministic tests.
- `README.md` contains complete, current GitHub Actions and Cloudflare setup and
  operating procedures.
- Python lint, format, type checks, Python tests, Worker tests, TypeScript type
  checking, and local D1/R2 smoke tests all pass.
