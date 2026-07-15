# Channel-scoped event IDs design

## Problem

Schedule rows from different channels can expose the same upstream event ID. The shared adapter normalization currently copies that value directly into `source_event_id`, while D1 requires `(source_id, source_event_id)` to be unique. A multi-channel import can therefore roll back with `import_failed`.

## Design

Scope normalized source event IDs by the adapter's upstream channel code: `<upstream_code>:<upstream_id>`. This keeps IDs deterministic, preserves the original upstream value as a suffix, and satisfies the database uniqueness contract without a schema migration.

The change belongs in `normalize_rows()` so every HTML/JSON schedule adapter receives the same protection. A regression test will normalize two channels carrying the same upstream ID and assert distinct source event IDs.

## Verification

Run the focused regression test, all adapter tests, and the complete Python test suite. Existing fixtures that already embed a channel in their upstream ID remain valid apart from gaining the mapping channel prefix only where they pass through this normalizer.
