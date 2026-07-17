# Remove Images Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove all image collection, storage, management, and public API behavior from radio_epg.

**Architecture:** Reduce the Python collection contract to channels, programs, and schedules; reduce the Worker to D1-backed textual EPG APIs. Remove R2 routes and bindings, then migrate existing D1 databases away from image tables and foreign-key columns.

**Tech Stack:** Python 3.12, Pydantic, pytest, TypeScript, Hono, Cloudflare Workers/D1, Vitest

---

### Task 1: Remove images from the Python domain contract

**Files:**
- Modify: `tests/test_models.py`
- Modify: `tests/test_collector.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/integration/test_collection_import.py`
- Modify: `src/radio_epg/models.py`
- Modify: `src/radio_epg/collector.py`
- Modify: `src/radio_epg/cli.py`
- Modify: `src/radio_epg/publisher.py`

1. Change tests to construct `AdapterResult` and `ImportBatch` without `images`, assert serialized imports contain no `images`, and assert run summaries contain no image counters.
2. Run `UV_CACHE_DIR=/tmp/radio-epg-uv-cache uv run pytest -q tests/test_models.py tests/test_collector.py tests/test_cli.py tests/integration/test_collection_import.py` and confirm failures identify the old image contract.
3. Delete `ImageCandidate`, both `images` fields, image counters, excluded-image serialization, and image-specific CLI naming.
4. Re-run the targeted tests and confirm they pass.

### Task 2: Remove adapter image extraction and image modules

**Files:**
- Modify: `src/radio_epg/adapters/html_schedule.py`
- Modify: `src/radio_epg/adapters/kbs.py`
- Modify: `src/radio_epg/adapters/mbc.py`
- Modify: `src/radio_epg/adapters/ebs.py`
- Modify: `src/radio_epg/adapters/sbs.py`
- Modify: affected files under `tests/adapters/` and `tests/fixtures/`
- Delete: `src/radio_epg/image_publisher.py`
- Delete: `src/radio_epg/images/`
- Delete: `tests/test_image_publisher.py`
- Delete: `tests/images/`

1. Update adapter tests to assert only schedule/program metadata and remove image fixtures/assertions.
2. Run affected adapter tests and confirm they fail against image-bearing results or fixture fields.
3. Remove image parsing/candidate construction from adapters and delete the unused image implementation and dedicated tests.
4. Run `UV_CACHE_DIR=/tmp/radio-epg-uv-cache uv run pytest -q tests/adapters tests/test_models.py tests/test_collector.py tests/test_cli.py tests/test_publisher.py tests/integration`.

### Task 3: Remove image fields and routes from the Worker API

**Files:**
- Modify: `worker/test/public-api.test.ts`
- Modify: `worker/test/e2e.test.ts`
- Modify: `worker/test/index.test.ts`
- Modify: `worker/src/types.ts`
- Modify: `worker/src/repositories/channels.ts`
- Modify: `worker/src/repositories/schedules.ts`
- Modify: `worker/src/import-schema.ts`
- Modify: `worker/src/index.ts`
- Delete: `worker/src/routes/admin-images.ts`
- Delete: `worker/src/routes/admin-takedown.ts`
- Delete: `worker/src/routes/images.ts`
- Delete: `worker/test/images.test.ts`

1. Change API tests to require the absence of `image_url` and `program_image_url`, reject import payloads containing `images`, and expect removed image routes to return 404.
2. Run the targeted Worker tests and confirm failures expose the existing fields/routes.
3. Remove public types/repository joins and mappings, delete image schemas/routes, and stop mounting them.
4. Run the targeted Worker tests and confirm they pass.

### Task 4: Remove R2 and migrate D1 schema

**Files:**
- Create: `worker/migrations/0005_remove_images.sql`
- Modify: `worker/wrangler.toml`
- Modify: `worker/src/types.ts`
- Modify: `worker/test/migrations.test.ts`
- Modify: `worker/test/retention.test.ts`
- Modify: any Worker test environment declarations containing `IMAGES`

1. Add a migration test asserting `image_assets`, `image_variants`, `image_takedowns`, entity `image_asset_id` columns, and `scrape_runs.image_count` are absent after all migrations.
2. Run the migration test and confirm it fails against the current schema.
3. Add a foreign-key-safe table-rebuild migration preserving non-image data; drop image tables/indexes; remove the R2 binding and TypeScript binding.
4. Remove image retention fixtures/assertions and run all Worker tests.

### Task 5: Update current documentation and verify no functional remnants

**Files:**
- Modify: `README.md`
- Modify: `docs/api.md`
- Modify: `docs/database.md`
- Modify: `TODO.md`
- Delete: `docs/images.md`

1. Remove setup, architecture, API, operations, monitoring, and troubleshooting guidance for images/R2 while retaining historical plan documents.
2. Run `rg -n -S "ImageCandidate|image_publisher|radio_epg.images|admin-images|admin/takedown|/v1/images|image_url|program_image_url|image_asset_id|image_count|image_variant|image_error|R2Bucket|binding = \"IMAGES\"" src tests worker README.md docs/api.md docs/database.md TODO.md` and require no functional references.
3. Run `UV_CACHE_DIR=/tmp/radio-epg-uv-cache uv run pytest -q`.
4. Run the Worker package's full test and type-check commands from `worker/package.json`.
5. Review `git diff --check`, `git status --short`, and the complete diff before reporting completion.
