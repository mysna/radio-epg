# Radio EPG 데이터베이스

## 소유권과 저장 위치

Turso(libSQL)는 방송사, 채널, 별칭, 프로그램, 편성과 수집 실행 기록의
진실의 원천이다. 수집기는 데이터를 직접 수정하지 않고 인증된 ingestion API를 통해서만
배치를 전송하며, Worker가 제약조건과 쓰기 범위를 검증한다.

## 핵심 제약조건

- `channel_aliases`는 `(alias_type, alias_value)`를 고유하게 유지한다.
- `schedule_events`는 `ends_at > starts_at`과 0~1 범위의 신뢰도를 강제한다.
- 모든 하위 레코드는 외래키로 소유 레코드를 참조한다.
- 편성은 요일 슬롯으로 저장한다. `weekday`(0=일요일)와 방송일 KST 0시 기준 초
  `start_offset`/`end_offset`은 `broadcast_date`·시각에서 계산하는 VIRTUAL 생성 컬럼이다.
- 날짜별·현재/다음 조회는 `(channel_id, weekday, start_offset)` index를 사용한다.
- `(source_id, channel_id, weekday, broadcast_date)` index는 import 요일 슬롯 교체와
  슬롯 정리에 사용한다.

## 멱등성과 트랜잭션

각 import는 `scrape_runs.idempotency_key`를 고유하게 기록한다. 같은 키의 재전송은 기존
결과를 다시 만들지 않는다. 일정 교체는 검증된 source/channel/요일 슬롯 범위 안에서만
수행하며, batch가 실패하면 배치 전체를 롤백해야 한다. 편성이 없던 실행은
`/v1/admin/runs`로 `event_count = 0`과 메모(`error_summary`)만 남긴다.

## 삭제와 보존

편성 이벤트는 source/channel/요일 슬롯마다 가장 최근 방송일 하나만 보존한다. 새 편성이
오지 않으면 기간과 무관하게 그대로 유지하며, retention 작업은 같은 슬롯의 이전 방송일
편성만 삭제한다. 프로그램과 채널은 편성 삭제와 함께 제거하지 않는다.
별칭은 채널에 종속되어 채널 삭제 시 함께 제거되지만, 운영 중인 채널은 삭제 대신
`active = 0`으로 비활성화한다.
