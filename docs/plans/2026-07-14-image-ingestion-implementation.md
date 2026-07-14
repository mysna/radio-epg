# Image Ingestion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upload adapter image candidates through the existing Worker image endpoint during every schedule collection run.

**Architecture:** Keep schedule import and image import as separate HTTP contracts. Add a Python image publisher that safely downloads and transforms candidates, uploads each variant with bounded retries, and returns a sanitized best-effort summary; wire it into the existing CLI publisher after schedule import and expose its counts in the collection report.

**Tech Stack:** Python 3.12, httpx, Pillow/CairoSVG, Pydantic, pytest, Hono Worker, Vitest

---

### Task 1: Image API request publisher

**Files:**
- Create: `src/radio_epg/image_publisher.py`
- Create: `tests/test_image_publisher.py`

**Step 1: Write the failing tests**

Cover these observable behaviors with `httpx.MockTransport` and a fake downloader:

- a candidate is downloaded and transformed, then three requests are posted to `/v1/admin/images`;
- each request carries the bearer token, provenance fields, SHA-256 content hash, dimensions, byte size, and base64 bytes;
- identical candidate source bytes reuse the same content hash while each entity is still linked;
- transient API responses are retried with bounded backoff;
- a download, transform, or permanent API failure increments a sanitized failure count and does not stop later candidates;
- an empty candidate tuple performs no HTTP requests.

**Step 2: Run the tests and verify RED**

Run: `UV_CACHE_DIR=/tmp/radio-epg-uv-cache uv run pytest -q tests/test_image_publisher.py`

Expected: FAIL because `radio_epg.image_publisher` does not exist.

**Step 3: Implement the minimal publisher**

Create immutable `ImagePublishSummary` fields `candidate_count`, `uploaded_variant_count`, and `failed_candidate_count`. Implement `publish_images(...)` with dependency injection for the downloader/transport, exact-host allowlisting derived from candidate HTTPS URLs, existing `transform_image`, base64 request serialization, bearer authentication, and the same bounded transient status set used by schedule publication.

Do not include response bodies, bearer tokens, image bytes, or source URLs in raised or reported errors. Catch candidate-level download/transform/upload failures and continue.

**Step 4: Run tests and verify GREEN**

Run: `UV_CACHE_DIR=/tmp/radio-epg-uv-cache uv run pytest -q tests/test_image_publisher.py`

Expected: all image publisher tests pass.

**Step 5: Commit**

Commit message: `feat: publish collected image variants`

### Task 2: Collection report and CLI wiring

**Files:**
- Modify: `src/radio_epg/collector.py`
- Modify: `src/radio_epg/cli.py`
- Modify: `tests/test_collector.py`
- Modify: `tests/test_cli.py`

**Step 1: Write the failing tests**

- prove the CLI publisher calls schedule publication before image publication;
- prove it passes the original batch images to `publish_images`;
- prove image publication failures return a summary instead of failing the schedule run;
- prove `ScrapeRunSummary` reports discovered `image_count`, uploaded `image_variant_count`, and `image_error_count` from publisher output.

**Step 2: Run the focused tests and verify RED**

Run: `UV_CACHE_DIR=/tmp/radio-epg-uv-cache uv run pytest -q tests/test_collector.py tests/test_cli.py`

Expected: FAIL because the image publisher is not wired and report fields are absent.

**Step 3: Implement the minimal wiring**

Add a CLI-level `publish_collection_batch` helper that awaits `publish_batch` first and `publish_images` second. Return schedule status plus sanitized image counts. Update the collector to read optional count keys from the publisher result, defaulting to zero for existing publishers and tests.

Keep schedule status successful when image errors are nonzero. A schedule import failure must prevent image publication because target entities may not exist.

**Step 4: Run focused tests and verify GREEN**

Run: `UV_CACHE_DIR=/tmp/radio-epg-uv-cache uv run pytest -q tests/test_collector.py tests/test_cli.py tests/test_image_publisher.py`

Expected: all focused tests pass.

**Step 5: Commit**

Commit message: `feat: ingest images during schedule collection`

### Task 3: End-to-end contract and workflow verification

**Files:**
- Modify: `tests/integration/test_collection_import.py`
- Modify only if required by a demonstrated contract gap: `.github/workflows/collect.yml`

**Step 1: Write the failing integration test**

Use a KBS fixture containing an image candidate and mock schedule/image endpoints. Assert request order is schedule import followed by three image variant uploads, and assert the collection report remains successful with correct image counts.

**Step 2: Run the integration test and verify RED**

Run: `UV_CACHE_DIR=/tmp/radio-epg-uv-cache uv run pytest -q tests/integration/test_collection_import.py`

Expected: the new test fails before its integration wiring is complete.

**Step 3: Complete only demonstrated integration gaps**

Preserve the existing `collect.yml` command and credentials unless the test proves a missing environment handoff. Do not send images through `/v1/admin/import`; its zero-image contract remains intentional.

**Step 4: Run all verification**

Run:

- `UV_CACHE_DIR=/tmp/radio-epg-uv-cache uv run pytest -q`
- `UV_CACHE_DIR=/tmp/radio-epg-uv-cache uv run ruff check .`
- `npm test -- --run` from `worker/`
- `npm run typecheck` from `worker/`

Expected: all checks pass.

**Step 5: Commit**

Commit message: `test: verify collection image ingestion`
