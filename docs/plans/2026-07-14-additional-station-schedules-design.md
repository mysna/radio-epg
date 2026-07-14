# 추가 방송사 편성표 수집 설계

## 목표

사용자가 제공한 공식 편성표 URL을 기존 라디오 EPG 수집 파이프라인에 연결해 OBS, iFM, YTN, TBS FM/eFM, FEBC, BBS, CPBC, WBS, 국방FM, 국악방송, AFN Humphreys의 편성을 수집한다.

## 설계

기존 `source → adapter → mapping → normalized import` 경계를 유지한다. 이미 catalog와 regional/community mapping에 존재하는 canonical channel ID를 재사용하고, 방송사별 URL과 실제 응답 구조를 mapping에 기록한다.

정적 HTML로 날짜·시각·프로그램명이 확인되는 방송사는 공통 HTML 행 파서를 재사용한다. JSON, 날짜별 query, PDF/이미지, 서버 오류 또는 JS 렌더링으로 fixture를 만들 수 없는 방송사는 별도 adapter 경계로 격리하고 `unsupported` 상태로 유지한다. 수집 결과가 비어 있거나 날짜가 맞지 않으면 Collector가 게시하지 않아 기존 데이터가 삭제되지 않는다.

## 검증

각 활성화 mapping은 공식 응답을 고정 fixture로 저장하고 parser 단위 테스트에서 날짜, 시간 순서, 프로그램명, 채널 ID를 검증한다. 모든 URL은 live smoke check 대상으로 기록하되 네트워크 오류가 CI를 깨뜨리지 않게 한다. 설정·mapping·coverage·registry 테스트와 전체 pytest를 실행한다.
