# SBS 날짜 범위 이벤트 ID 설계

## 문제

SBS current-day 응답의 이벤트 식별자는 `vod_id`와 시작 시각으로 만들어진다. 공통 정규화 계층은 채널 코드만 추가하므로, 같은 프로그램이 다음 날 같은 시각에 방송되면 D1의 `(source_id, source_event_id)` 유일성 제약과 충돌한다. 정기 실행 뒤 retention이 이전 날짜를 삭제하기 때문에 후속 수동 실행은 성공할 수 있다.

## 결정

공통 HTML/JSON 편성 정규화 계층에서 `source_event_id`를 `<channel>:<broadcast-date>:<upstream-id>`로 만든다. 날짜가 이벤트 발생 범위의 일부이므로 D1 식별자와 `event_key`가 날짜별로 안정되고, 동일 날짜 재수집의 멱등성은 유지된다.

DB 유일성 제약 완화는 중복 이벤트 방어를 약화하므로 사용하지 않는다. import 전에 retention을 실행하는 방식도 수동 재실행과 다른 소스의 식별자 결함을 해결하지 못하므로 사용하지 않는다.

## 검증

동일 채널과 동일 upstream ID를 서로 다른 방송일에 정규화하여 `source_event_id`가 서로 다름을 먼저 실패하는 테스트로 증명한다. 기존 SBS 채널 간 충돌 테스트의 예상값도 날짜 포함 계약으로 갱신하고 전체 Python 및 Worker 테스트를 실행한다.
