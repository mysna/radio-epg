# Image ingestion design

## Goal

Connect image candidates discovered during schedule collection to the existing Worker image API so program, channel, and broadcaster images are stored in R2 and linked from D1.

## Architecture

Schedule publication remains the primary operation. After a schedule batch is imported, its image candidates are processed independently: download from the candidate host, validate and transform the source into small, medium, and original PNG variants, then upload each variant to `/v1/admin/images` using the ingestion token.

The existing `ImageCandidate`, `SafeImageDownloader`, and `transform_image` contracts remain the source of truth. The existing Worker endpoint remains responsible for R2 storage, D1 image metadata, and linking `image_asset_id` to the target entity.

## Data flow

1. An adapter returns schedules, programs, and zero or more image candidates.
2. The collector publishes the schedule import first, ensuring referenced entities exist.
3. The image publisher groups candidates by source URL host and builds an exact-host download allowlist for that run.
4. Each candidate is downloaded with existing byte, pixel, redirect, and format checks.
5. The source is transformed into small, medium, and original PNG variants.
6. Each variant is posted to `/v1/admin/images` with provenance, rights metadata, content hash, dimensions, and base64 content.
7. The Worker stores bytes in R2, upserts `image_assets` and `image_variants`, and links the entity's `image_asset_id`.

## Failure behavior

Schedule ingestion is authoritative and must not fail because an image is unavailable. Image candidates use best-effort processing: one candidate or variant failure is recorded in a sanitized image publication summary and processing continues with the remaining candidates. Authentication or configuration errors are still visible in the collection report without exposing tokens, URLs with credentials, or image bytes.

Repeated content uses the existing SHA-256 content identity and Worker upsert behavior. Re-running collection is safe and refreshes verification metadata while replacing the same R2 keys.

## Workflow

The existing `radio-epg collect` command performs both stages, so `.github/workflows/collect.yml` does not need another job or secret. `EPG_API_BASE_URL` and `EPG_INGEST_TOKEN` are reused for the image endpoint.

## Testing

- Unit tests cover image request serialization, authentication, retries, and sanitized best-effort failures.
- Collector tests prove schedules publish before images and image failures do not mark schedule collection failed.
- Integration tests exercise adapter candidate through schedule import and image upload requests.
- Existing Worker image endpoint tests continue to prove R2, D1 metadata, and entity linking behavior.
