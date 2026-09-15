# Cowork 판독 Routine 프롬프트

`data/vision/*.json`을 채우는 주간 Cowork Routine(매주 일요일, 청주·울산·전주
MBC 대상)에 실제로 설정된 프롬프트 원문이다. Routine 설정 자체는 이 저장소
밖(Claude Code Remote의 트리거)에 있어서 버전 관리가 안 되므로, 나중에
프롬프트를 고치거나 다른 vision-assisted 채널로 넓힐 때 참고할 수 있도록 여기
그대로 옮겨 둔다.

## 실행 주기

매주 일요일 09:02 UTC(한국시간 월요일 18:02) 1회, 세션을 새로 만들어 실행한다.

## 프롬프트 원문

```
너는 `mysna/radio-epg`(라디오 EPG 수집기) 저장소에서 매주 한 번 실행되는 vision-assisted 편성표 판독 작업을 맡았다. 이 저장소는 라디오 방송사들의 편성표를 수집해 API로 제공하는 프로젝트로, 대부분 소스는 결정적 파서로 자동 수집하지만 청주MBC(MBC충북)·울산MBC·전주MBC는 편성표를 이미지로만 공개해서 자동 파싱이 불가능하다. 그래서 매주 네가 직접 이미지를 읽어 정해진 스키마의 JSON을 커밋하는 방식으로 데이터를 채운다.

이번 실행에서는 **청주MBC, 울산MBC, 전주MBC 셋 다** 처리해라. 하나가 실패해도 다른 둘은 계속 시도해라(서로 독립적인 작업이다).

## 준비
1. `/home/user/radio-epg`에 이 저장소가 이미 있는지 확인해라. 없으면 `git clone https://github.com/mysna/radio-epg /home/user/radio-epg`로 클론하고 `cd /home/user/radio-epg`로 이동해라. `git pull origin main`으로 최신 상태로 맞춰라.
2. `data/vision/README.md`를 읽어 JSON 스키마를 정확히 파악해라. 이게 이번 작업의 출력 계약이다.

## 청주MBC
3. 표준FM(제1FM) 게시판: `https://www.mbccb.co.kr/rb/?r=home&c=78/109/668/798`, 파워FM(제2FM/FM4U) 게시판: `https://www.mbccb.co.kr/rb/?r=home&c=78/109/668/797` 을 각각 방문해라. 그누보드 기반 게시판이고 "YYYY년 M월N주차 (M/D-M/D) 주간편성표" 형식의 제목으로 매주 새 글이 올라온다. 오늘 날짜 기준으로 **이번 주(월요일 시작)**에 해당하는 가장 최신 게시글을 찾아 들어가서, 본문에 삽입된 편성표 이미지(JPG)를 읽어라.
4. 표준FM은 channel_id `mbc.sfm.cheongju`, 파워FM은 `mbc.fm4u.cheongju`다. 각각 `data/vision/mbc.sfm.cheongju.json`, `data/vision/mbc.fm4u.cheongju.json`에 스키마대로 써라.

## 울산MBC
5. 표준FM 게시판: `https://www.usmbc.co.kr/StandardFMProgramming`, FM4U 게시판: `https://www.usmbc.co.kr/FM4UProgramming` 을 각각 방문해라. "YYYY년 M월N주차 주간 편성표(표준FM/FM4U)" 형식의 제목으로 매주 새 글이 올라오고, 게시글 안에 편성표 이미지(JPG)가 첨부돼 있다. 오늘 날짜 기준 이번 주 게시글을 찾아 이미지를 읽어라.
6. 표준FM은 channel_id `mbc.sfm.ulsan`, FM4U는 `mbc.fm4u.ulsan`이다. 각각 `data/vision/mbc.sfm.ulsan.json`, `data/vision/mbc.fm4u.ulsan.json`에 스키마대로 써라.

## 전주MBC
7. 청주·울산과 달리 게시판이 아니라, 표준FM 편성표 페이지 `https://www.jmbc.co.kr/schedule/sfm`와 FM4U 편성표 페이지 `https://www.jmbc.co.kr/schedule/fm4u`를 그냥 방문하면 페이지 안에 이번 주 편성표 이미지가 바로 박혀 있다(`<img src="/uploads/schedule/{fm4u|sfm}_YYMMDD.jpg">` 형태, YYMMDD는 이번 주 월요일 날짜 - 게시글을 따로 찾을 필요 없이 그 페이지에 보이는 이미지를 그대로 읽으면 된다). 표는 "프로그램명" 기본 칸 하나와 월~일 요일별 칸으로 돼 있는데, 날짜 칸이 비어 있으면 그 날은 기본값과 같다는 뜻이고 채워져 있으면 그 날짜만 다른 프로그램이 편성됐다는 뜻이다 - 평일(월~금)은 보통 기본값과 같고 토·일요일에 재방송이나 특집으로 바뀌는 경우가 많으니 요일별로 잘 구분해서 읽어라.
8. 표준FM은 channel_id `mbc.sfm.jeonju`, FM4U는 `mbc.fm4u.jeonju`다. 각각 `data/vision/mbc.sfm.jeonju.json`, `data/vision/mbc.fm4u.jeonju.json`에 스키마대로 써라.

## 공통 유의사항
9. 이미지가 흐리거나 일부만 읽혀서 확신이 안 서는 항목은 무리해서 지어내지 말고, 읽을 수 있는 만큼만 채워라 (그 요일/시간대는 그냥 비워두는 게 틀린 데이터를 넣는 것보다 낫다). `week_of`는 이번 주 월요일 날짜(YYYY-MM-DD), `source_note`에는 실제로 읽은 게시글/페이지 URL을 남겨라.
10. 이번 실행에서 실제로 쓴(성공한) 파일들만 한 번에 커밋해라. 커밋 메시지에 "지역 MBC 편성표 이미지 판독 (주간, YYYY-MM-DD 주) - 청주/울산/전주" 처럼 어느 방송사·어느 주 것인지 명시하고, vision-assisted임을 밝혀라. `git push origin main`으로 바로 푸시해라(이 저장소는 PR 없이 main에 직접 push하는 관례다).
11. **절대 하지 말아야 할 것**: `data/sources.json`의 `mbc-regional-vision` 항목의 `enabled` 값을 건드리지 마라(사람이 몇 주 검증 후 직접 켠다). `data/mappings/regional.json`의 행들도 건드리지 마라. 오직 `data/vision/` 아래 JSON 파일만 쓰고 커밋해라.

## 실패 시
12. 한 방송사에서 이번 주 게시글/이미지를 못 찾았거나, 사이트 접속이 안 되거나(503 등), 이미지를 전혀 읽을 수 없으면 그 방송사의 파일만 건너뛰어라(기존 파일이 있다면 건드리지 마라) - 다른 방송사는 계속 시도해라. 어느 방송사가 왜 실패했는지만 마지막에 짧게 요약해라.

각 실행은 독립적이다 - 이전 실행에 대한 기억은 없다고 가정하고 매번 이 지시를 처음부터 그대로 따라라.
```

## 변경 이력

- 2026-09-15: 전주MBC(`mbc.fm4u.jeonju`/`mbc.sfm.jeonju`) 섹션 추가. 청주·울산과
  달리 게시판 첨부가 아니라 `/schedule/fm4u`, `/schedule/sfm` 페이지에 이미지가
  직접 박혀 있는 구조라 탐색 방식이 다름을 별도 절로 설명해뒀다.
