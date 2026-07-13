# Two-Day EPG Collection and Retention Design

## Purpose

Keep the radio EPG focused on the only schedules the player needs: the full
Korean calendar day for today and tomorrow. Reduce upstream traffic, GitHub
Actions duration, ingestion payload size, and D1 storage while preserving the
ability to browse all of today's timetable.

This design supersedes the original decisions to collect eight calendar days
and retain 30 days of historical schedule events.

## Confirmed Behavior

- Define dates in `Asia/Seoul`, independent of the runner's local timezone.
- Collect exactly two calendar dates: KST today and KST tomorrow.
- Keep today's entire timetable, including programs that already ended.
- Delete every schedule event whose `broadcast_date` is before KST today.
- Run retention after every collection attempt, including partially successful
  runs, so old data does not accumulate.
- Do not delete today's rows based on the current clock time.
- Continue replacing each successfully imported source/channel/date scope
  atomically.

## Alternatives Considered

### Rolling 48-hour window

This minimizes stored data but cuts off the beginning of today and includes
part of the day after tomorrow. It does not match a timetable organized by
calendar date.

### Delete events as soon as they end

This keeps only current and future programs but prevents users from viewing the
complete timetable for today. It also creates more frequent deletion churn.

### Recommended: today and tomorrow by KST calendar date

This matches the UI concept of "today" and "tomorrow", keeps behavior stable
throughout the day, and reduces the previous eight-day workload by about 75%.

## Data Flow

```text
GitHub Actions
  -> calculate KST today
  -> collect [today, tomorrow]
  -> validate source results
  -> partition imports only when Worker count/byte limits require it
  -> import source/channel/broadcast-date scopes
  -> POST retention
  -> delete broadcast_date < KST today
```

The Worker computes the retention cutoff from KST rather than trusting a date
provided by the caller. This keeps manual runs and scheduled runs consistent.

## Remaining Import Contract Corrections

The first production run exposed issues independent of the collection window.
They are included because a two-day run must still complete successfully.

- KBS `schedule_unique_id` is not globally unique across all channels. Build a
  source event ID scoped by canonical channel, broadcast date, start time, and
  upstream ID before ingestion.
- EBS returns protocol-relative homepage URLs such as
  `//home.ebs.co.kr/example`. Convert them to absolute HTTPS URLs.
- CBS may return relative homepage paths. Resolve them against
  `https://www.cbs.co.kr/`.
- Keep count- and byte-aware publisher partitioning as a safety boundary even
  though the two-day result is smaller.

## Retention API

`POST /v1/admin/retention` remains authenticated. Its response reports:

- the KST cutoff date;
- the number of deleted schedule events;
- a completed status.

Retention deletes by `broadcast_date < cutoff_date`. It does not use
`ends_at < now`, so all rows for today remain available.

## Failure Handling

- One source failure remains isolated from the other sources.
- Retention still runs after collection failure.
- Invalid or relative source metadata is normalized before publishing or fails
  closed with a sanitized error.
- Import batches never split a source/channel/broadcast-date scope, preventing a
  later part from erasing an earlier part of the same timetable.

## Verification

- Collector default window is KST today through tomorrow.
- A UTC/KST midnight boundary test locks the two-day calculation.
- Retention removes yesterday and older dates while preserving all of today and
  tomorrow.
- KBS source event IDs remain unique across channels and dates.
- EBS and CBS homepage URLs are absolute.
- Python and Worker full test suites, lint, formatting, and type checks pass.
- Live two-day collection succeeds for every enabled source.
- GitHub Actions imports data and public coverage contains all enabled sources.
