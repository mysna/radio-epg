# Radio EPG 공개 API

기본 URL 예시는 `https://radio-epg.<ACCOUNT_SUBDOMAIN>.workers.dev`이다. 모든 공개 응답은
JSON이며, 존재하는 채널에 편성이 없으면 프로그램을 추측하지 않고 `unavailable`을 반환한다.

## 채널

```text
GET /v1/channels
GET /v1/channels/{channel_id-or-alias}
```

두 번째 경로는 정규 ID, 현재 라디오 플레이어 ID, URL 인코딩한 `stn/ch/city` tuple 별칭을
받는다.

```bash
curl 'https://<API_HOST>/v1/channels/kbs.1radio.busan'
curl 'https://<API_HOST>/v1/channels/busan-039-kbs-1radio-busan'
curl 'https://<API_HOST>/v1/channels/kbs%2F1radio%2Fbusan'
```

## 날짜별 편성

```text
GET /v1/schedules?channel_id=kbs.1radio.busan&date=2026-07-13
GET /v1/schedules?radio_id=busan-039-kbs-1radio-busan&date=2026-07-13
```

`date`는 실제 달력에 존재하는 `YYYY-MM-DD` 방송일이어야 한다. 응답 이벤트의
`starts_at`/`ends_at`은 UTC RFC 3339 시각이고, `source`에는 원본 URL, 종류, 조회 시각,
신뢰도와 `stale` 상태가 포함된다.

## 현재 및 다음 프로그램

```text
GET /v1/now?radio_ids=id1,id2
```

한 번에 최대 100개 radio ID를 쉼표로 전달할 수 있다. 각 결과는 `current`, `next`와
`available`, `unavailable`, 또는 `not_found` 상태를 포함한다. 등록되지 않은 radio ID가
있어도 묶음 요청은 실패하지 않으며, 요청 순서의 해당 결과를 `channel_id: null`,
`status: "not_found"`, `current: null`, `next: null`로 반환한다. 응답은 최대 30초 캐시한다.

## 소스 커버리지

```text
GET /v1/coverage
```

활성 소스별 이벤트 수, 마지막 조회 시각, stale 상태를 반환한다.

## 수집 결과 ingestion

```text
POST /v1/admin/import
Authorization: Bearer <INGEST_TOKEN>
Content-Type: application/json
```

Collector 전용 서버 간 API다. 요청은 1MB 이하의 검증된 batch여야 하며, 채널·프로그램과
`source_id`/`channel_id`/`broadcast_date` 범위의 편성을 하나의 D1 batch로 반영한다.
동일한 `idempotency_key`와 동일한 payload를 다시 보내면 `200 already_applied`, 같은 키에
다른 payload를 보내면 `409 idempotency_conflict`를 반환한다. 최초 적용은
`201 applied`를 반환한다.

인증 실패는 `401 unauthorized`, schema 실패는 `400 invalid_import`, 크기 초과는
`413 request_too_large`다. 인증 토큰은 Wrangler secret `INGEST_TOKEN`으로만 설정한다.

## 편성 보존 기간 정리

```text
POST /v1/admin/retention
Authorization: Bearer <INGEST_TOKEN>
```

요청 본문은 없다. 기본적으로 Worker가 계산한 KST 오늘과 내일의 `schedule_events`만 남기고
날짜 범위 밖의 과거 및 먼 미래 편성을 삭제한다. 수집 workflow는 자정 교차에도 같은 날짜를
사용하도록 `?start_date=YYYY-MM-DD`를 전달한다. 안전을 위해 이 값은 Worker 기준 KST 오늘
또는 어제만 허용한다. 오늘 이미 끝난 이벤트와 프로그램, 채널, 별칭, 이미지 asset/variant
메타데이터는 삭제하지 않는다. 같은 날짜에 반복 호출해도 안전하다.

```json
{
  "status": "completed",
  "start_date": "2026-07-14",
  "end_date": "2026-07-15",
  "deleted": 42
}
```

인증 실패는 `401 unauthorized`, D1 정리 실패는 `500 retention_failed`다. 일일 수집
workflow는 일부 source import가 실패해도 수집 시도 뒤에 이 endpoint를 호출하며, 원래
수집 실패는 성공으로 바꾸지 않는다.

## 배포 smoke 검사

```bash
uv run radio-epg smoke \
  --base-url 'https://<API_HOST>' \
  --radio-id 'busan-039-kbs-1radio-busan'
```

`/health`, `/v1/channels`, 지정한 current radio ID의 채널 상세, `/v1/coverage`를 순서대로
검사한다. 채널과 coverage는 각각 한 개 이상의 항목이 있어야 하고, 채널 상세에는 요청한
radio ID 별칭이 유지되어야 한다. 실패 응답의 본문이나 자격증명은 출력하지 않으며 하나라도
HTTP/JSON 계약을 충족하지 않으면 0이 아닌 종료 상태가 된다.

## 오류

오류는 항상 다음 envelope를 사용한다.

```json
{
  "error": {
    "code": "channel_not_found",
    "message": "The requested channel alias is not registered."
  }
}
```

주요 코드는 `invalid_date`, `missing_channel`, `missing_radio_ids`,
`too_many_radio_ids`, `channel_not_found`, `origin_not_allowed`이다.

## 캐시와 CORS

성공한 공개 응답은 `ETag`를 제공하며 같은 `If-None-Match` 요청에는 `304`를 반환한다.
채널은 1시간, 날짜별 편성과 커버리지는 5분, 현재/다음 응답은 30초 캐시한다.

브라우저 요청은 `CORS_ORIGINS`의 쉼표 구분 allowlist에 있는 정확한 origin만 허용한다.
서버 간 요청처럼 `Origin` 헤더가 없는 요청은 CORS 검사 대상이 아니다.
