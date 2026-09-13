# Vision-assisted 편성표 데이터

편성표를 이미지(또는 사람이 읽어야 하는 형태)로만 공개해서 결정적으로 파싱할 수
없는 채널은, Cowork 세션이 주기적으로 이미지를 읽어 이 디렉터리에 아래 스키마의
JSON을 채널당 하나씩 커밋한다. `src/radio_epg/adapters/additional.py`의
`vision_json()`과 `src/radio_epg/regional_mapping.py`의 `_vision_json` parser가
이 파일을 읽어 수집 파이프라인에 흘려보낸다(네트워크 요청 없이 로컬 파일만 읽음).

## 파일명

`<channel_id>.json` — `channel_id`는 `data/radio_channels.json`의 canonical
channel id와 정확히 같아야 한다(예: `mbc.sfm.andong.json`).

## 스키마

```json
{
  "week_of": "2026-09-14",
  "read_at": "2026-09-13T12:00:00Z",
  "source_note": "이미지를 찾은 실제 게시글 URL(참고용, 파이프라인은 읽지 않음)",
  "days": {
    "monday": [{"start": "06:00", "title": "생방송 아침이좋다"}],
    "tuesday": [],
    "wednesday": [],
    "thursday": [],
    "friday": [],
    "saturday": [],
    "sunday": []
  }
}
```

- `week_of`: 이 편성표가 적용되는 주의 **월요일** 날짜(`YYYY-MM-DD`). 수집
  파이프라인은 요청한 날짜가 속한 주의 월요일과 이 값이 다르면(아직 이번 주
  편성표를 못 읽었거나 갱신을 안 함) 그 채널을 조용히 건너뛴다 - 즉, 매주
  이 파일을 최신 주로 갱신해야 계속 반영된다.
- `days`: 요일별(영어 소문자, `monday`~`sunday`) 편성 목록. 각 항목은
  `start`(`HH:MM`, 24시간제)와 `title`만 있으면 된다 - 종료 시각은 다음 항목의
  시작 시각으로 자동 계산되고, 마지막 항목은 관례적인 기본값으로 채워진다.
  시간이 자정을 넘기는 항목(예: 새벽 1시 프로그램)도 그냥 `01:00`처럼 그날의
  실제 벽시계 시각으로 적으면 파이프라인이 자정 넘김을 자동으로 정규화한다.
- 없는 요일은 빈 배열로 두면 된다(그 요일은 그냥 건너뛴다).

## 신뢰도

이 경로로 들어온 편성은 다른 공식 소스보다 신뢰도를 낮게(`confidence: 0.5`)
매겨서 저장한다 - LLM이 이미지를 읽어 옮긴 값이라는 걸 API 소비자도 구분할 수
있게 하기 위함이다.
