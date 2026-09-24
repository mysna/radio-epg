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
신뢰도, `stale` 상태와 실제로 수집한 방송일 `broadcast_date`가 포함된다.

편성은 날짜가 아니라 요일 슬롯(일~토)으로 저장한다. 요청한 날짜의 요일 슬롯에 있는
가장 최근 편성을 요청 날짜로 옮겨 돌려주므로, 방송사가 그 날짜 편성을 아직 올리지
않았으면 지난 같은 요일 편성이 나온다. 응답의 `data_date`는 슬롯 편성의 실제 방송일,
`fallback`은 `data_date`가 요청 날짜와 다른지 여부다.

```json
{
  "channel_id": "kbs.1radio.busan",
  "broadcast_date": "2026-07-20",
  "data_date": "2026-07-13",
  "fallback": true,
  "status": "available",
  "stale": true,
  "events": [{ "starts_at": "2026-07-20T03:00:00Z", "source": { "broadcast_date": "2026-07-13" } }]
}
```

## 현재 및 다음 프로그램

```text
GET /v1/now?radio_ids=id1,id2
```

한 번에 최대 100개 radio ID를 쉼표로 전달할 수 있다. 각 결과는 `current`, `next`와
`available`, `unavailable`, 또는 `not_found` 상태를 포함한다. 날짜별 편성과 같이 KST
어제·오늘·내일의 요일 슬롯을 해당 날짜로 옮겨 계산하며, 각 이벤트의
`source.broadcast_date`로 실제 수집 방송일을 확인할 수 있다. 등록되지 않은 radio ID가
있어도 묶음 요청은 실패하지 않으며, 요청 순서의 해당 결과를 `channel_id: null`,
`status: "not_found"`, `current: null`, `next: null`로 반환한다. 응답은 현재 편성이
끝나는 시각까지 캐시하며, 수명은 최소 30초에서 최대 5분으로 제한한다.

## 소스 커버리지

```text
GET /v1/coverage
```

활성 소스별 이벤트 수, 마지막 조회 시각, stale 상태를 반환한다. `no_schedule_since`는
마지막으로 편성을 받은 뒤 "편성표 없음" 실행이 이어진 경우 그 첫 실행 시각이고, 아니면
`null`이다. 값이 오래될수록 방송사가 편성 게시를 멈췄을 가능성이 크다.

## 수집 결과 ingestion

```text
POST /v1/admin/import
Authorization: Bearer <INGEST_TOKEN>
Content-Type: application/json
```

Collector 전용 서버 간 API다. 요청은 1MB 이하의 검증된 batch여야 하며, 채널·프로그램과
`source_id`/`channel_id`/요일 슬롯 범위의 편성을 하나의 DB batch로 반영한다. 화요일
편성을 받으면 그 채널의 이전 화요일 편성(날짜가 달라도)을 교체한다.
동일한 `idempotency_key`와 동일한 payload를 다시 보내면 `200 already_applied`, 같은 키에
다른 payload를 보내면 `409 idempotency_conflict`를 반환한다. 최초 적용은
`201 applied`를 반환한다.

인증 실패는 `401 unauthorized`, schema 실패는 `400 invalid_import`, 크기 초과는
`413 request_too_large`다. 인증 토큰은 Wrangler secret `INGEST_TOKEN`으로만 설정한다.

## 편성 없음 실행 기록

```text
POST /v1/admin/runs
Authorization: Bearer <INGEST_TOKEN>
Content-Type: application/json
```

Collector 전용이다. 방송사가 편성을 올리지 않아 게시할 편성이 없던 실행을
`scrape_runs`에 성공(`event_count = 0`)과 메모(`note`, 예: `편성표 없음`)로 남긴다. 기존
편성은 건드리지 않는다. 본문은 `idempotency_key`, `source`, `started_at`, `finished_at`,
`note`이며, 최초 기록은 `201 applied`, 같은 키 재전송은 `200 already_applied`다.

## 편성 슬롯 정리

```text
POST /v1/admin/retention
Authorization: Bearer <INGEST_TOKEN>
```

요청 본문은 없다. 같은 source/channel/요일 슬롯에 더 최근 방송일 편성이 있으면 이전
방송일 편성을 삭제한다. import가 요일 슬롯을 통째로 교체하므로 평소에는 지울 것이 없는
안전장치이며, 슬롯은 기간과 무관하게 새 편성이 올 때까지 유지한다. 프로그램, 채널,
별칭은 삭제하지 않는다. 반복 호출해도 안전하다.

```json
{ "status": "completed", "deleted": 0 }
```

인증 실패는 `401 unauthorized`, DB 정리 실패는 `500 retention_failed`다. 일일 수집
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
채널과 커버리지는 1시간, 날짜별 편성은 5분 캐시한다. 현재/다음 응답은 편성 경계까지
캐시하되 30초에서 5분 사이로 제한한다.

브라우저 요청은 `CORS_ORIGINS`의 쉼표 구분 allowlist에 있는 정확한 origin만 허용한다.
서버 간 요청처럼 `Origin` 헤더가 없는 요청은 CORS 검사 대상이 아니다.
