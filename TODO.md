# Radio EPG TODO

구현 상태의 기준은 `docs/plans/2026-07-13-radio-epg-api-implementation.md`이다.

## 현재 체크포인트

- [x] Task 1: Python Collector와 Worker 스캐폴딩
- [x] Task 2: 라디오 채널 카탈로그 가져오기 및 정규화
- [x] Task 3: 정규화 모델과 방송 시간 처리
- [x] Task 4: D1 스키마와 마이그레이션 테스트
- [x] Task 5: 공개 채널 및 편성 API
- [x] Task 6: 인증된 멱등 ingestion

- [x] Task 7: Collector runtime과 adapter protocol
- [x] Task 8: KBS reference adapter
- [x] Task 9: 이미지 수집, 변환, R2 제공 및 takedown

## 이후 작업

- [x] Task 10: 전국 방송사 편성 adapter
- [x] Task 11: 지역 및 독립 방송사 adapter
- [x] Task 12: Community, AFN, wiki fallback, OCR
- [x] Task 13: 일일 수집, Worker 배포, live probe workflow
- [x] Task 14: 배포 및 운영 README
- [ ] Task 15: end-to-end 호환성, retention, 전체 검증
