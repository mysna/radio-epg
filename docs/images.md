# 이미지 수집 및 권리 처리

이미지는 Wikimedia/Wikipedia, Namuwiki, 공식 방송사·프로그램 page 순서로 발견한다.
Wikimedia 파일은 API가 제공하는 저자, 라이선스, attribution을 보존한다. Namuwiki와 공식
page의 `og:image`는 발견 경로일 뿐 권리 확인으로 간주하지 않으며 `unknown`으로 기록한다.

## 안전한 download와 변환

- adapter별 exact-host allowlist에 포함된 HTTPS URL만 요청한다.
- redirect마다 목적 host를 다시 검증한다.
- 응답 byte 수와 decode pixel 수를 제한한다.
- HTTP `Content-Type`을 신뢰하지 않고 PNG, JPEG, WebP, GIF, SVG signature를 확인한다.
- raster 입력은 다시 인코딩하고 SVG는 script가 제공되지 않도록 PNG로 rasterize한다.
- alpha와 종횡비를 보존한 `small`, `medium`, `original` PNG variant를 만든다.
- 원본 SHA-256 content hash로 중복을 제거한다.

## 저장과 제공

`POST /v1/admin/images`는 `INGEST_TOKEN` Bearer 인증을 요구하며 한 요청에 검증된 variant
하나만 받는다. Worker는 R2 object를 먼저 쓴 뒤 D1 metadata와 entity 연결을 batch로
반영한다. D1 반영이 실패하면 방금 쓴 R2 object를 삭제한다.

공개 이미지는 `GET /v1/images/{asset_id}/{small|medium|original}`로 제공하며 immutable
cache header와 ETag를 반환한다. 외부 원본 URL을 proxy하지 않는다.

## Takedown과 영구 차단

`POST /v1/admin/takedown`은 asset을 즉시 unavailable로 표시하고 entity 연결을 해제하며,
source URL과 content hash를 영구 blocklist에 함께 기록한 다음 모든 R2 variant를 삭제한다.
같은 URL 또는 hash는 이후 ingestion에서 `409 image_blocked`로 거부한다. 삭제 요청의 이유와
처리 시각은 운영 감사 목적으로 D1에 남긴다.
