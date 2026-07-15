# Disable image publication design

## Decision

Keep image discovery and publication modules available, but disconnect image publication from the scheduled collection path. Schedule collection continues to send the normal import payload, while image candidates are not downloaded, transformed, or posted to `/v1/admin/images`.

This is intentionally reversible: restoring the existing publisher call re-enables the feature without rebuilding the image pipeline.

## Verification

The CLI unit test and collection integration test assert that schedule import occurs and no image API request occurs. Image publisher unit tests remain in place for future reactivation.
