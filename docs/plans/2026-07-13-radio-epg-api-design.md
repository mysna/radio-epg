# Radio EPG API Design

## 1. Purpose

Build a free-to-operate Korean radio electronic program guide API for the
existing `radio` player. The service collects schedules once per day, stores
normalized schedule data, and serves broadcaster, channel, and program images
from its own cache.

The first release targets the current `radio` catalog and low traffic. It must
preserve compatibility with that catalog while allowing stable identifiers that
do not depend on the catalog's array order.

## 2. Confirmed Decisions

- Use the current `/home/mysna/workspace/radio/src/channels.js` catalog as the
  initial scope.
- Collect schedules once per day.
- Expose today plus the next seven calendar days when the source provides them.
- Retain past schedule events for 30 days.
- Prefer official broadcaster sources. Use current third-party portal or wiki
  schedule information when an official schedule is unavailable.
- Discover broadcaster, channel, and program images from Wikipedia/Wikimedia or
  Namuwiki first, then use official broadcaster and schedule pages.
- Serve images whose rights are not fully known, while retaining provenance and
  supporting prompt takedown and permanent re-import blocking.
- Use GitHub Actions for collection and Cloudflare Workers, D1, and R2 for the
  public service.
- Document complete GitHub Actions and Cloudflare setup procedures in
  `README.md`.

## 3. Scope

### In Scope

- The 226 catalog rows and 194 unique `(stn, ch, city)` identities currently in
  the radio player.
- Daily schedule collection through source-specific adapters.
- HTML, JSON, JSONP, PDF, and image-based schedule inputs.
- OCR as an adapter-specific last resort for image schedules.
- Current and next program lookup.
- Cached broadcaster, channel, and program images with generated variants.
- Source freshness, coverage, and collection health reporting.
- Public read-only API and authenticated ingestion API.

### Out of Scope for the First Release

- User accounts or personalized schedules.
- Stream hosting or stream URL discovery.
- Real-time schedule polling more than once per day.
- Historical retention longer than 30 days.
- A public administration UI.
- Automatic legal determination for images with incomplete rights metadata.

## 4. Existing Radio Compatibility

The radio player currently generates an ID in this form:

```text
{regionId}-{arrayIndex}-{stn}-{ch|main}-{city|main}
```

The array index makes that ID unsuitable as a permanent database key. The EPG
service therefore assigns a stable canonical `channel_id` and stores all player
identifiers in a `channel_aliases` table.

Each channel record exposes:

- `channel_id`: stable EPG identifier, for example `kbs.1radio.busan`.
- `radio_id`: the current generated player ID.
- `stn`, `ch`, `city`: the original player lookup tuple.
- `region_id`: the player region.

The API accepts either `channel_id`, `radio_id`, or the `stn/ch/city` tuple.
Catalog synchronization is explicit: importing a new radio catalog creates new
aliases without silently deleting old aliases.

## 5. Source Coverage Strategy

| Source family | Unique identities | Primary method | Initial confidence |
| --- | ---: | --- | --- |
| KBS | 46 | Official weekly JSON used by the KBS schedule site, including regional station codes | High |
| MBC | 36 | Seoul JSONP plus per-region MBC HTML or internal JSON adapters | Medium |
| SBS and affiliates | 13 | SBS daily JSON plus one adapter per regional affiliate site | Medium |
| EBS | 2 | Official schedule page; separate discovery for the Bandi foreign-language channel | Medium |
| TBN | 13 | Official regional schedules; public-data files as a secondary source | Medium |
| CBS | 19 | Central schedule pages/PDF and regional CBS sites | Medium |
| FEBC | 13 | Regional subdomains on the shared FEBC CMS | Medium |
| BBS | 5 | Central and regional schedule pages | Medium |
| CPBC | 4 | Central and regional station pages | Medium |
| WBS | 5 | Central and regional pages or published schedule files | Medium/Low |
| KFN and Gugak | 4 | Official KFN and Gugak schedule pages | High/Medium |
| TBS, iFM, YTN, OBS, Arirang, BeFM, GGN | 8 | Individual official HTML or JSON adapters | High/Medium |
| AFN | 3 | AFN Eagle schedule plus local inserts when published | Low |
| Community stations | 23 | Individual HTML, CMS posts, PDFs, or schedule images with OCR | Low/Mixed |

Representative confirmed official sources include:

- KBS schedule: <https://schedule.kbs.co.kr/>
- MBC schedule: <https://schedule.imbc.com/>
- SBS radio: <https://www.sbs.co.kr/radio>
- EBS schedule: <https://www.ebs.co.kr/schedule?channelCd=IRADIO>
- CBS radio: <https://www.cbs.co.kr/radio/radio/main>
- TBS FM schedule: <https://tbs.seoul.kr/fm/schedule.do>
- Arirang schedule: <https://www.arirang.com/schedule?lang=en-US%2F>
- Mapo FM schedule: <https://www.mapofm.net/timetable>
- Namhae FM: <https://namhaefm.com/>

The KBS, MBC, and SBS JSON endpoints found during research are site-internal
interfaces, not contractual public APIs. Adapters must be fixture-tested and
must fail closed when upstream schemas change.

### Source Priority

For each channel and broadcast date, choose data in this order:

1. Official structured API or embedded JSON.
2. Official HTML, PDF, or schedule image.
3. Official program page, notice, or social post.
4. Current third-party portal or wiki schedule.
5. A previously verified recurring weekly schedule, marked `inferred`.
6. No event data, represented as `unavailable`; never invent a program title.

Every event records `source_id`, `source_url`, `source_kind`, `fetched_at`, and
`confidence`. Lower-priority data can fill gaps but cannot overwrite valid
higher-priority data for the same time range.

## 6. Architecture

```text
GitHub Actions scheduled workflow (daily 04:17 KST)
  -> Python collector and source adapters
  -> normalization, validation, image discovery, image variants
  -> authenticated Worker ingestion endpoints
  -> D1 transaction for schedule and metadata
  -> R2 uploads for source snapshots and cached images

Radio player / API consumer
  -> Cloudflare Worker public API
  -> D1 indexed reads
  -> R2/CDN image responses
```

GitHub Actions runs the collectors because Python has mature HTML, PDF, image,
and OCR tooling. A free Worker has a small CPU budget and should only validate
ingestion requests and serve the API.

The scheduled workflow runs at an off-hour minute to reduce GitHub scheduler
contention. A run may retry failed network operations internally, but there is
only one scheduled collection run per day.

## 7. Components

### Python Collector

- Catalog importer: converts `channels.js` into deterministic seed data.
- Adapter protocol: fetches one source and returns normalized candidates.
- HTTP client: timeouts, bounded retries, polite rate limiting, user agent, and
  conditional requests.
- Parsers: JSON/JSONP, HTML, PDF text/table, and optional OCR.
- Normalizer: converts broadcast-day times, including `24:00` and later, to
  timezone-aware instants.
- Validator: rejects invalid overlaps, missing titles, impossible durations,
  and unexpected channel mappings.
- Image pipeline: discovers images, stores provenance, deduplicates by hash, and
  creates fixed local variants before upload.
- Publisher: submits idempotent batches to the ingestion API.

Adapters are grouped by shared platform, not only by broadcaster. Regional
stations using the same CMS share a parser with station-specific configuration.

### Cloudflare Worker

- Public routes for channels, schedules, current programs, images, and coverage.
- Private HMAC or bearer-authenticated ingestion routes.
- Request validation, pagination, CORS, conditional responses, and cache headers.
- D1 batch writes within a transaction-like import boundary.
- R2 object reads and deletion hooks.

### D1

Stores normalized entities and operational metadata. Raw images and large source
snapshots are not stored as BLOBs in D1.

### R2

Stores original cached images, generated variants, and short-lived raw source
snapshots needed to diagnose parser failures. Public images are served through
the Worker or an attached R2 custom/public domain with immutable content hashes.

## 8. Data Model

### Core Tables

- `broadcasters`: identity, name, homepage, image ID.
- `channels`: stable ID, broadcaster, display name, region, active status, image.
- `channel_aliases`: alias type/value, including player IDs and tuple keys.
- `programs`: stable source-aware identity, title, description, hosts, genre,
  homepage, image.
- `schedule_events`: channel, program, broadcast date, start/end UTC, displayed
  title/subtitle, live/rerun flags, confidence, source, timestamps.
- `sources`: adapter name, priority, source URLs, terms note, enabled status.
- `scrape_runs`: start/end, adapter result, counts, error summary, artifact key.

### Image Tables

- `image_assets`: entity type, entity ID, content hash, rights status, source URL,
  source page, author, license, attribution, first/last verified timestamps.
- `image_variants`: asset, variant name, MIME type, dimensions, byte size, R2 key.
- `image_takedowns`: content hash, source URL, reason, request time, completion
  time, and permanent block status.

### Important Constraints and Indexes

- Unique alias key on `(alias_type, alias_value)`.
- Unique source event identity where an upstream event ID exists.
- Otherwise idempotency key based on channel, broadcast date, start time, title,
  and source.
- Index schedules on `(channel_id, starts_at)` and `(channel_id, broadcast_date)`.
- Index runs on `(source_id, started_at)`.
- Validate `ends_at > starts_at`.

## 9. Time Model

- Interpret source schedules in `Asia/Seoul` unless an adapter declares another
  timezone.
- Store instants in UTC and expose RFC 3339 timestamps with offsets.
- Preserve `broadcast_date` separately from the calendar date of `starts_at`.
- Parse extended broadcast times such as `25:30` as the next calendar day while
  retaining the original broadcast date.
- A current-program query uses `starts_at <= now < ends_at`.

## 10. Public API

```text
GET /v1/channels
GET /v1/channels/{channel_id-or-alias}
GET /v1/schedules?channel_id=...&date=YYYY-MM-DD
GET /v1/schedules?radio_id=...&date=YYYY-MM-DD
GET /v1/now?radio_ids=id1,id2,...
GET /v1/coverage
GET /v1/images/{image_id}/{variant}
```

Schedule responses include channel identity, event/program fields, image URLs,
source kind, confidence, `fetched_at`, and `stale`. The current-program response
includes both `current` and `next` per requested channel.

Errors use a stable JSON envelope:

```json
{
  "error": {
    "code": "channel_not_found",
    "message": "The requested channel alias is not registered."
  }
}
```

Public responses use ETags. Channel and historical schedule responses may be
cached for hours; current-program responses are cached for no more than one
minute. CORS initially permits the production radio player and configured local
development origins.

## 11. Image Acquisition and Rights Handling

Image discovery order is:

1. Wikipedia/Wikimedia and Namuwiki pages.
2. Official broadcaster brand or channel pages.
3. Official program and schedule pages.

Within wiki candidates, prefer Wikimedia Commons files with machine-readable
author and license metadata. Commons requires checking each file's individual
license and notes that trademark and personality rights can remain independent
of copyright: <https://commons.wikimedia.org/wiki/Commons%3AReusing_content_outside_Wikimedia/en>.

Namuwiki is a discovery source, not proof that an individual image is freely
licensed. Unknown assets are stored with `rights_status = unknown` and still
served under the confirmed project policy.

The pipeline retains the original response hash and provenance. It generates
small, medium, and original-size-preserving variants without depending on a
paid image transformation service. Logos preserve transparency.

Takedown processing must:

1. Mark the asset unavailable immediately.
2. Delete all R2 originals and variants.
3. Remove entity references in D1 without deleting schedule data.
4. Record both content hash and source URL in a permanent blocklist.
5. Prevent later collectors from re-importing the same asset.

## 12. Collection and Failure Behavior

- Fetch today through today plus seven days when supported.
- Keep events whose end time is within the last 30 days.
- Stage and validate a source batch before publishing it.
- Do not replace a previous valid schedule when the new batch is empty or fails
  structural validation.
- Mark the affected source and channel stale and retain the last successful data.
- Isolate adapters so one broadcaster failure does not stop the remaining run.
- Save a bounded raw response or diagnostic sample for failed parsers, with
  secrets and personal data excluded.
- Publish per-source counts, duration, freshness, and sanitized error messages
  through `/v1/coverage`.

## 13. Security

- Public API routes are read-only.
- Ingestion requires a rotated secret stored in GitHub Actions secrets and a
  Cloudflare Worker secret.
- Validate ingestion size and schemas before D1/R2 writes.
- Reject arbitrary upstream URLs at ingestion; image hosts must match an adapter
  allowlist to prevent SSRF.
- Strip active formats such as SVG scripts and reject HTML masquerading as an
  image. Re-encode raster images before serving.
- Apply public rate limits and Cloudflare caching.
- Never commit Cloudflare API tokens, account IDs, ingestion secrets, or R2
  credentials.

## 14. Free Deployment

The initial stack fits within the current free tiers for low traffic:

- Workers Free: 100,000 requests per day.
- D1 Free: 500 MB per database, five million rows read per day, and 100,000 rows
  written per day.
- R2 Standard: 10 GB-month storage, one million Class A operations, ten million
  Class B operations, and free Internet egress per month.
- GitHub-hosted standard runners are free for public repositories.

References:

- <https://developers.cloudflare.com/workers/platform/limits/>
- <https://developers.cloudflare.com/d1/platform/pricing/>
- <https://developers.cloudflare.com/d1/platform/limits/>
- <https://developers.cloudflare.com/r2/pricing/>
- <https://docs.github.com/en/actions/concepts/billing-and-usage>

The service must fail with an observable error instead of incurring an automatic
paid overage. Usage alerts and a monthly storage audit are required operational
tasks. Images use R2 Standard because the R2 free tier does not apply to the
Infrequent Access class.

## 15. README Requirements

`README.md` must be sufficient for a new maintainer to deploy the service without
hidden steps. It must include:

1. Architecture and repository layout.
2. Prerequisites: Python, `uv`, Node.js, Wrangler, Cloudflare, and GitHub.
3. Local installation, environment variables, tests, lint, format, and type
   checking commands.
4. Cloudflare account setup and the exact commands to create D1 and R2 resources.
5. `wrangler.toml` binding configuration and D1 migration commands.
6. Worker secret creation and deployment commands.
7. Creation of a least-privilege Cloudflare API token.
8. GitHub repository secrets and variables, with exact names and purposes.
9. Enabling and manually testing the scheduled GitHub Actions workflow.
10. Daily cron time in UTC and its KST equivalent.
11. CORS origin configuration for the radio player.
12. Adding or repairing a source adapter using stored fixtures.
13. Image provenance, attribution, takedown, and blocklist procedures.
14. Monitoring free-tier usage, collection health, and common failure recovery.
15. API examples using both canonical IDs and existing radio player IDs.

The README must distinguish commands that are safe to copy directly from values
that must be replaced by the operator.

## 16. Testing Strategy

- Unit tests for identifiers, time parsing, normalization, validation, source
  priority, and image metadata.
- Fixture-based contract tests for every enabled adapter without live network
  dependency.
- Parser regression fixtures with sensitive or copyrighted bulk content reduced
  to the minimum structure needed for testing.
- Integration tests against local SQLite/D1-compatible migrations and an R2
  fake.
- Worker route tests for aliases, schedules, current/next, CORS, ETags, errors,
  and ingestion authentication.
- End-to-end smoke test that imports a small fixture batch and queries it by a
  current radio player ID.
- A non-blocking live-source probe workflow for detecting upstream changes; it
  does not replace deterministic tests.
- Required Python quality sequence: `ruff check --fix`, `ruff format`, `ty check`,
  then the full test suite.

## 17. Delivery Order

1. Repository scaffold, schema, identifiers, and catalog importer.
2. Worker public API and authenticated ingestion.
3. KBS adapter as the structured-source reference implementation.
4. Image cache and rights/takedown pipeline.
5. MBC, SBS, EBS, and high-coverage national adapters.
6. Shared regional CMS adapters.
7. Community, PDF, image, and OCR adapters.
8. Coverage reporting, operational workflows, and radio player integration.

Each adapter is enabled only after its fixtures and channel mappings pass. The
API can launch with partial coverage because it exposes coverage explicitly and
never represents missing data as confirmed programming.
