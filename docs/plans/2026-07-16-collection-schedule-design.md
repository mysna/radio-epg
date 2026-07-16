# Collection Schedule Design

## Goal

Run daily schedule collection early enough to avoid the observed SBS failures after 05:00 KST.

## Design

Move the GitHub Actions schedule from 04:17 KST to 01:17 KST. The workflow continues to derive `EPG_COLLECTION_DATE` in `Asia/Seoul` once and reuse it for collection and retention, so moving the run earlier does not change the broadcast-date contract. Update the operations documentation to show the matching UTC cron and KST time.

## Verification

Validate the workflow YAML, assert that the cron converts to 01:17 KST, and run the repository test suite before committing and pushing.
