# Radio EPG Source Coverage

- Catalog: 168
- Accounted: 168
- Pending: 0

| Channel | Status | Owner | Reason |
| --- | --- | --- | --- |
| `arirang.main.main` | enabled | independent |  |
| `bbs.main.busan` | unsupported | religious | BBS 지역별 공식 편성 fixture 미검증 |
| `bbs.main.daegu` | unsupported | religious | BBS 지역별 공식 편성 fixture 미검증 |
| `bbs.main.gwangju` | unsupported | religious | BBS 지역별 공식 편성 fixture 미검증 |
| `bbs.main.jeju` | unsupported | religious | BBS 지역별 공식 편성 fixture 미검증 |
| `bbs.main.main` | enabled | religious |  |
| `befm.main.main` | unsupported | independent | 파서는 fixture로 검증됐으나 개발 샌드박스에서는 정상 접속되는 반면 실제 production(GitHub Actions)에서는 도입 직후부터 연속 8회 모두 ConnectError로 실패(2026-09-12), wbsi.kr과 같은 GH Actions IP 대역 차단으로 추정 |
| `cbs.joy4u.main` | enabled | cbs |  |
| `cbs.mfm.busan` | enabled | cbs_regional |  |
| `cbs.mfm.daegu` | unsupported | cbs_regional | 대구CBS 표준FM과 같은 station=6으로 ch=0(음악FM) 요청 시 빈 배열만 반환됨(실존하는 방송이지만 이 API의 어느 station 번호로도 응답을 못 찾음, station 1~4만 콘텐츠 있음) |
| `cbs.mfm.gwangju` | enabled | cbs_regional |  |
| `cbs.mfm.main` | enabled | cbs |  |
| `cbs.sfm.busan` | enabled | cbs_regional |  |
| `cbs.sfm.cheongju` | enabled | cbs_regional |  |
| `cbs.sfm.chuncheon` | enabled | cbs_regional |  |
| `cbs.sfm.daegu` | enabled | cbs_regional |  |
| `cbs.sfm.daejeon` | enabled | cbs_regional |  |
| `cbs.sfm.gwangju` | enabled | cbs_regional |  |
| `cbs.sfm.gyeongnam` | enabled | cbs_regional |  |
| `cbs.sfm.jeju` | enabled | cbs_regional |  |
| `cbs.sfm.jeonbuk` | enabled | cbs_regional |  |
| `cbs.sfm.jeonnam` | enabled | cbs_regional |  |
| `cbs.sfm.main` | enabled | cbs |  |
| `cbs.sfm.pohang` | enabled | cbs_regional |  |
| `cbs.sfm.ulsan` | enabled | cbs_regional |  |
| `cbs.sfm.youngdong` | enabled | cbs_regional |  |
| `cpbc.main.busan` | enabled | religious |  |
| `cpbc.main.daegu` | enabled | religious |  |
| `cpbc.main.gwangju` | enabled | religious |  |
| `cpbc.main.main` | enabled | religious |  |
| `ebs.bandi.main` | enabled | ebs |  |
| `ebs.fm.main` | enabled | ebs |  |
| `febc.main.busan` | enabled | febc |  |
| `febc.main.changwon` | enabled | febc |  |
| `febc.main.daegu` | enabled | febc |  |
| `febc.main.daejeon` | enabled | febc |  |
| `febc.main.gangwon` | enabled | febc |  |
| `febc.main.gwangju` | enabled | febc |  |
| `febc.main.jeju` | enabled | febc |  |
| `febc.main.jeonbuk` | enabled | febc |  |
| `febc.main.jeonnam` | enabled | febc |  |
| `febc.main.main` | enabled | febc |  |
| `febc.main.mokpo` | enabled | febc |  |
| `febc.main.pohang` | enabled | febc |  |
| `febc.main.ulsan` | enabled | febc |  |
| `ggn.main.main` | enabled | independent |  |
| `ifm.main.main` | enabled | independent |  |
| `kbs.1fm.busan` | enabled | kbs |  |
| `kbs.1fm.changwon` | enabled | kbs |  |
| `kbs.1fm.cheongju` | enabled | kbs |  |
| `kbs.1fm.chuncheon` | enabled | kbs |  |
| `kbs.1fm.chungju` | enabled | kbs |  |
| `kbs.1fm.daegu` | enabled | kbs |  |
| `kbs.1fm.daejeon` | enabled | kbs |  |
| `kbs.1fm.gangneung` | enabled | kbs |  |
| `kbs.1fm.gwangju` | enabled | kbs |  |
| `kbs.1fm.jeju` | enabled | kbs |  |
| `kbs.1fm.jeonju` | enabled | kbs |  |
| `kbs.1fm.main` | enabled | kbs |  |
| `kbs.1fm.mokpo` | enabled | kbs |  |
| `kbs.1fm.wonju` | enabled | kbs |  |
| `kbs.1radio.andong` | enabled | kbs |  |
| `kbs.1radio.busan` | enabled | kbs |  |
| `kbs.1radio.changwon` | enabled | kbs |  |
| `kbs.1radio.cheongju` | enabled | kbs |  |
| `kbs.1radio.chuncheon` | enabled | kbs |  |
| `kbs.1radio.chungju` | enabled | kbs |  |
| `kbs.1radio.daegu` | enabled | kbs |  |
| `kbs.1radio.daejeon` | enabled | kbs |  |
| `kbs.1radio.gangneung` | enabled | kbs |  |
| `kbs.1radio.gwangju` | enabled | kbs |  |
| `kbs.1radio.jeju` | enabled | kbs |  |
| `kbs.1radio.jeonju` | enabled | kbs |  |
| `kbs.1radio.jinju` | enabled | kbs |  |
| `kbs.1radio.main` | enabled | kbs |  |
| `kbs.1radio.mokpo` | enabled | kbs |  |
| `kbs.1radio.pohang` | enabled | kbs |  |
| `kbs.1radio.suncheon` | enabled | kbs |  |
| `kbs.1radio.ulsan` | enabled | kbs |  |
| `kbs.1radio.wonju` | enabled | kbs |  |
| `kbs.2fm.main` | enabled | kbs |  |
| `kbs.2radio.busan` | enabled | kbs |  |
| `kbs.2radio.changwon` | enabled | kbs |  |
| `kbs.2radio.cheongju` | enabled | kbs |  |
| `kbs.2radio.chuncheon` | enabled | kbs |  |
| `kbs.2radio.daegu` | enabled | kbs |  |
| `kbs.2radio.daejeon` | enabled | kbs |  |
| `kbs.2radio.gwangju` | enabled | kbs |  |
| `kbs.2radio.jeju` | enabled | kbs |  |
| `kbs.2radio.jeonju` | enabled | kbs |  |
| `kbs.2radio.main` | enabled | kbs |  |
| `kbs.3radio.main` | enabled | kbs |  |
| `kbs.hanminjok.main` | enabled | kbs |  |
| `kookbang.main.main` | enabled | independent |  |
| `kugak.main.daejeon` | enabled | independent |  |
| `kugak.main.gwangju` | enabled | independent |  |
| `kugak.main.main` | enabled | independent |  |
| `mbc.bora.main` | unsupported | mbc | 보이는 라디오는 독립 편성 채널로 확인되지 않음 |
| `mbc.chm.main` | enabled | mbc |  |
| `mbc.fm4u.andong` | unsupported | mbc_regional_vision | 편성표가 이미지로만 공개됨 - Cowork 판독 pipeline은 구현됐으나 andongmbc.co.kr이 클라우드 환경에서 503으로 접속 자체가 막혀 있어 첫 데이터를 못 채움(청주MBC로 파일럿 전환) |
| `mbc.fm4u.busan` | enabled | mbc_busan |  |
| `mbc.fm4u.changwon` | unsupported | regional_mbc | MBC경남(mbcgn.kr)이 클라우드 환경에서 503으로 접속 자체가 막혀 있음(andongmbc.co.kr과 동일 패턴) |
| `mbc.fm4u.cheongju` | unsupported | mbc_regional_vision | 편성표가 게시판 첨부 이미지(JPG)로만 공개됨 - Cowork 판독 pipeline은 구현됐으나 아직 data/vision/에 첫 데이터가 커밋되지 않음 |
| `mbc.fm4u.chuncheon` | unsupported | regional_mbc | chmbc.co.kr이 날짜별 HTML 표(guide2/channel/radio/date/YYYY-MM-DD)를 제공해 결정적으로 파싱 가능함을 확인함 - 전용 parser 미구현, 다음 작업으로 남김 |
| `mbc.fm4u.daegu` | enabled | regional_mbc |  |
| `mbc.fm4u.daejeon` | unsupported | regional_mbc | tjmbc.co.kr이 날짜별 HTML 표(FM4U/FM4U/YYYY-MM-DD)를 제공해 결정적으로 파싱 가능함을 확인함 - 전용 parser 미구현, 다음 작업으로 남김 |
| `mbc.fm4u.gangneung` | enabled | regional_mbc |  |
| `mbc.fm4u.gwangju` | enabled | regional_mbc |  |
| `mbc.fm4u.jeju` | enabled | regional_mbc |  |
| `mbc.fm4u.jeonju` | unsupported | regional_mbc | jmbc.co.kr 편성표 페이지가 "편성표가 존재하지 않습니다"만 표시함 - 사이트 CMS 자체에 데이터가 비어 있는 것으로 보임 |
| `mbc.fm4u.main` | enabled | mbc |  |
| `mbc.fm4u.mokpo` | enabled | regional_mbc |  |
| `mbc.fm4u.pohang` | enabled | mbc_pohang |  |
| `mbc.fm4u.ulsan` | unsupported | mbc_regional_vision | 편성표가 게시판 첨부 이미지(JPG)로만 공개됨 - Cowork 판독 pipeline은 구현됐으나 아직 data/vision/에 첫 데이터가 커밋되지 않음 |
| `mbc.fm4u.wonju` | enabled | mbc_wonju |  |
| `mbc.fm4u.yeosu` | enabled | regional_mbc |  |
| `mbc.sfm.andong` | unsupported | mbc_regional_vision | 편성표가 이미지로만 공개됨 - Cowork 판독 pipeline은 구현됐으나 andongmbc.co.kr이 클라우드 환경에서 503으로 접속 자체가 막혀 있어 첫 데이터를 못 채움(청주MBC로 파일럿 전환) |
| `mbc.sfm.busan` | enabled | mbc_busan |  |
| `mbc.sfm.changwon` | unsupported | regional_mbc | MBC경남(mbcgn.kr)이 클라우드 환경에서 503으로 접속 자체가 막혀 있음(andongmbc.co.kr과 동일 패턴) |
| `mbc.sfm.cheongju` | unsupported | mbc_regional_vision | 편성표가 게시판 첨부 이미지(JPG)로만 공개됨 - Cowork 판독 pipeline은 구현됐으나 아직 data/vision/에 첫 데이터가 커밋되지 않음 |
| `mbc.sfm.chuncheon` | unsupported | regional_mbc | chmbc.co.kr이 날짜별 HTML 표(guide2/channel/radio2/date/YYYY-MM-DD)를 제공해 결정적으로 파싱 가능함을 확인함 - 전용 parser 미구현, 다음 작업으로 남김 |
| `mbc.sfm.daegu` | enabled | regional_mbc |  |
| `mbc.sfm.daejeon` | unsupported | regional_mbc | tjmbc.co.kr이 날짜별 HTML 표(StandardFM/FM/YYYY-MM-DD)를 제공해 결정적으로 파싱 가능함을 확인함 - 전용 parser 미구현, 다음 작업으로 남김 |
| `mbc.sfm.gangneung` | enabled | regional_mbc |  |
| `mbc.sfm.gwangju` | enabled | regional_mbc |  |
| `mbc.sfm.jeju` | enabled | regional_mbc |  |
| `mbc.sfm.jeonju` | unsupported | regional_mbc | jmbc.co.kr 편성표 페이지 경로가 불안정함(404) - 사이트 구조 재확인 필요 |
| `mbc.sfm.main` | enabled | mbc |  |
| `mbc.sfm.mokpo` | enabled | regional_mbc |  |
| `mbc.sfm.pohang` | enabled | mbc_pohang |  |
| `mbc.sfm.ulsan` | unsupported | mbc_regional_vision | 편성표가 게시판 첨부 이미지(JPG)로만 공개됨 - Cowork 판독 pipeline은 구현됐으나 아직 data/vision/에 첫 데이터가 커밋되지 않음 |
| `mbc.sfm.wonju` | enabled | mbc_wonju |  |
| `mbc.sfm.yeosu` | enabled | regional_mbc |  |
| `obs.main.main` | enabled | independent |  |
| `sbs.dmb.main` | enabled | sbs |  |
| `sbs.lovefm.busan` | enabled | knn |  |
| `sbs.lovefm.main` | enabled | sbs |  |
| `sbs.powerfm.busan` | enabled | knn |  |
| `sbs.powerfm.cheongju` | enabled | cjb |  |
| `sbs.powerfm.chuncheon` | unsupported | g1 | 지역 제휴사 공식 편성 endpoint와 fixture 미검증 |
| `sbs.powerfm.daegu` | enabled | tbc |  |
| `sbs.powerfm.daejeon` | enabled | tjb |  |
| `sbs.powerfm.gwangju` | unsupported | kbc | 지역 제휴사 공식 편성 endpoint와 fixture 미검증 |
| `sbs.powerfm.jeju` | enabled | jibs |  |
| `sbs.powerfm.jeonju` | unsupported | jtv | 지역 제휴사 공식 편성 endpoint와 fixture 미검증 |
| `sbs.powerfm.main` | enabled | sbs |  |
| `sbs.powerfm.ulsan` | enabled | ubc |  |
| `tbn.main.busan` | enabled | tbn |  |
| `tbn.main.chungbuk` | enabled | tbn |  |
| `tbn.main.chungnam` | enabled | tbn |  |
| `tbn.main.daegu` | enabled | tbn |  |
| `tbn.main.daejeon` | enabled | tbn |  |
| `tbn.main.gangwon` | enabled | tbn |  |
| `tbn.main.gwangju` | enabled | tbn |  |
| `tbn.main.gyeongbuk` | enabled | tbn |  |
| `tbn.main.gyeongnam` | enabled | tbn |  |
| `tbn.main.jeju` | enabled | tbn |  |
| `tbn.main.jeonbuk` | enabled | tbn |  |
| `tbn.main.main` | enabled | tbn |  |
| `tbn.main.ulsan` | enabled | tbn |  |
| `tbs.efm.main` | enabled | independent |  |
| `tbs.fm.main` | enabled | independent |  |
| `wbs.main.busan` | unsupported | religious | 파서는 fixture로 검증됐으나 wbsi.kr이 GitHub Actions IP 대역을 403으로 차단해 실제 수집 불가(2026-09-12 두 차례 연속 확인) |
| `wbs.main.daegu` | unsupported | religious | 파서는 fixture로 검증됐으나 wbsi.kr이 GitHub Actions IP 대역을 403으로 차단해 실제 수집 불가(2026-09-12 두 차례 연속 확인) |
| `wbs.main.gwangju` | unsupported | religious | 파서는 fixture로 검증됐으나 wbsi.kr이 GitHub Actions IP 대역을 403으로 차단해 실제 수집 불가(2026-09-12 두 차례 연속 확인) |
| `wbs.main.jeonbuk` | unsupported | religious | 파서는 fixture로 검증됐으나 wbsi.kr이 GitHub Actions IP 대역을 403으로 차단해 실제 수집 불가(2026-09-12 두 차례 연속 확인) |
| `wbs.main.main` | unsupported | religious | 파서는 fixture로 검증됐으나 wbsi.kr이 GitHub Actions IP 대역을 403으로 차단해 실제 수집 불가(2026-09-12 두 차례 연속 확인) |
| `ytn.main.main` | enabled | independent |  |
