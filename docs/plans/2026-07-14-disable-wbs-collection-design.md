# WBS 수집 비활성화 설계

## 배경

WBS 공식 편성표는 로컬에서는 응답하지만 GitHub Actions 실행 환경의 요청에는 HTTP 403을 반환한다. 재시도로 해결할 수 없는 출발지 차단이므로 정기 수집에서 WBS를 일시 제외한다.

## 변경

`data/sources.json`의 WBS source를 비활성화한다. 채널 카탈로그, adapter, parser, fixture는 보존하여 공식 접근 경로가 확보되면 설정 한 줄로 복구할 수 있게 한다.

## 검증

registry 테스트에서 WBS가 등록되어 있지만 비활성 상태임을 확인하고 전체 테스트를 실행한다.
