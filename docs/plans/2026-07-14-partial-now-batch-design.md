# Partial `/v1/now` Batch Results Design

## Goal

Keep valid current-program results when a `/v1/now` batch contains an unregistered radio ID.

## Response contract

The endpoint continues to return HTTP `200` for a syntactically valid batch of at most 100 IDs. Results remain in request order. A registered channel keeps the existing `available` or `unavailable` shape; an unregistered ID produces:

```json
{
  "radio_id": "unknown-id",
  "channel_id": null,
  "status": "not_found",
  "current": null,
  "next": null
}
```

Request-level validation errors such as a missing `radio_ids` query or more than 100 IDs remain HTTP `400` responses.

## Implementation and verification

Change only the `/v1/now` loop so a failed channel lookup appends the per-item result and continues. Add a public API regression test containing one valid and one unknown ID, then update the API documentation to describe `not_found`.
