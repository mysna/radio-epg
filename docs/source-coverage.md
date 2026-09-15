# Radio EPG Source Coverage

- Catalog: 168
- Accounted: 168
- Pending: 0

| Channel | Status | Owner | Reason |
| --- | --- | --- | --- |
| `arirang.main.main` | enabled | independent |  |
| `bbs.main.busan` | unsupported | religious | busanbbs.co.kr 접속 시 dothome.co.kr의 404 안내 페이지로 강제 리다이렉트됨 - 도메인 자체가 더 이상 실제 사이트를 서빙하지 않는 것으로 보임 |
| `bbs.main.daegu` | unsupported | bbs_daegu | 파서는 fixture로 검증됐고 개발 샌드박스에서는 정상 접속되지만, production(GitHub Actions)에서는 도입 직후 3회 연속(재시도 포함 시도 총 10회) 전부 ConnectTimeout으로 실패함(2026-09-15) - wbsi.kr/befm.or.kr과 같은 GH Actions IP 대역 차단으로 추정 |
| `bbs.main.gwangju` | unsupported | religious | kjbbs.co.kr이 User-Agent/헤더와 무관하게 모든 요청에 406 Not Acceptable(nginx)만 돌려줌 - 클라우드 IP 대역 차단으로 추정 |
| `bbs.main.jeju` | unsupported | religious | jejubbs.co.kr 접속 시 dothome.co.kr의 404 안내 페이지로 강제 리다이렉트됨 - 도메인 자체가 더 이상 실제 사이트를 서빙하지 않는 것으로 보임 |
| `bbs.main.main` | enabled | religious |  |
| `befm.main.main` | unsupported | independent | 파서는 fixture로 검증됐으나 개발 샌드박스에서는 정상 접속되는 반면 실제 production(GitHub Actions)에서는 도입 직후부터 연속 8회 모두 ConnectError로 실패(2026-09-12), wbsi.kr과 같은 GH Actions IP 대역 차단으로 추정 |
| `cbs.joy4u.main` | enabled | cbs |  |
| `cbs.mfm.busan` | enabled | cbs_regional |  |
| `cbs.mfm.daegu` | unsupported | cbs_regional | station 0~15 x ch=0/2 전체 조합을 직접 확인함 - ch=0은 station 0~3이 전부 같은 내용(station 파라미터 무시하고 기본값 반환), station 4만 실제로 다른 콘텐츠, station 5 이상은 전부 빈 배열; ch=2는 station 값과 무관하게 항상 응답 station:0의 전국 방송(기독음악)만 돌려줌 - 대구CBS 뮤직FM만의 응답을 주는 station 번호가 이 API에 존재하지 않음. daegu.cbs.co.kr/cbsdaegu.com 등 별도 지역 사이트 추정 URL도 접속 안 됨 |
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
| `mbc.bora.main` | unsupported | mbc | control.imbc.com/Schedule/Radio의 sType 파라미터에 BORA/VISIBLE 등 여러 값을 넣어봐도 전부 sType=ALLTHAT과 동일한 응답(올댓뮤직)만 돌아옴 - 이 API에 보이는 라디오만의 별도 sType이 없고, 기존 오디오 채널(FM4U/표준FM/올댓뮤직) 중 하나를 영상으로 겸용 송출하는 것으로 추정됨(독립 편성 채널 아님) |
| `mbc.chm.main` | enabled | mbc |  |
| `mbc.fm4u.andong` | unsupported | mbc_regional_vision | 편성표가 이미지로만 공개됨 - Cowork 판독 pipeline은 구현됐으나 andongmbc.co.kr이 클라우드 환경에서 503으로 접속 자체가 막혀 있어 첫 데이터를 못 채움(청주MBC로 파일럿 전환) |
| `mbc.fm4u.busan` | unsupported | mbc_busan | 파서는 fixture로 검증됐으나 busanmbc.co.kr이 WAF로 GH Actions 요청을 차단(2026-09-13 18:46 정상, 19:46부터 3회 연속 EmptyScheduleError/WAF 차단 페이지 확인) |
| `mbc.fm4u.changwon` | unsupported | regional_mbc | MBC경남(mbcgn.kr)이 클라우드 환경에서 503으로 접속 자체가 막혀 있음(andongmbc.co.kr과 동일 패턴) |
| `mbc.fm4u.cheongju` | enabled | mbc_regional_vision |  |
| `mbc.fm4u.chuncheon` | enabled | mbc_chuncheon |  |
| `mbc.fm4u.daegu` | enabled | regional_mbc |  |
| `mbc.fm4u.daejeon` | enabled | regional_mbc |  |
| `mbc.fm4u.gangneung` | enabled | regional_mbc |  |
| `mbc.fm4u.gwangju` | enabled | regional_mbc |  |
| `mbc.fm4u.jeju` | enabled | regional_mbc |  |
| `mbc.fm4u.jeonju` | enabled | mbc_regional_vision |  |
| `mbc.fm4u.main` | enabled | mbc |  |
| `mbc.fm4u.mokpo` | enabled | regional_mbc |  |
| `mbc.fm4u.pohang` | enabled | mbc_pohang |  |
| `mbc.fm4u.ulsan` | enabled | mbc_regional_vision |  |
| `mbc.fm4u.wonju` | enabled | mbc_wonju |  |
| `mbc.fm4u.yeosu` | enabled | regional_mbc |  |
| `mbc.sfm.andong` | unsupported | mbc_regional_vision | 편성표가 이미지로만 공개됨 - Cowork 판독 pipeline은 구현됐으나 andongmbc.co.kr이 클라우드 환경에서 503으로 접속 자체가 막혀 있어 첫 데이터를 못 채움(청주MBC로 파일럿 전환) |
| `mbc.sfm.busan` | unsupported | mbc_busan | 파서는 fixture로 검증됐으나 busanmbc.co.kr이 WAF로 GH Actions 요청을 차단(2026-09-13 18:46 정상, 19:46부터 3회 연속 EmptyScheduleError/WAF 차단 페이지 확인) |
| `mbc.sfm.changwon` | unsupported | regional_mbc | MBC경남(mbcgn.kr)이 클라우드 환경에서 503으로 접속 자체가 막혀 있음(andongmbc.co.kr과 동일 패턴) |
| `mbc.sfm.cheongju` | enabled | mbc_regional_vision |  |
| `mbc.sfm.chuncheon` | enabled | mbc_chuncheon |  |
| `mbc.sfm.daegu` | enabled | regional_mbc |  |
| `mbc.sfm.daejeon` | enabled | regional_mbc |  |
| `mbc.sfm.gangneung` | enabled | regional_mbc |  |
| `mbc.sfm.gwangju` | enabled | regional_mbc |  |
| `mbc.sfm.jeju` | enabled | regional_mbc |  |
| `mbc.sfm.jeonju` | enabled | mbc_regional_vision |  |
| `mbc.sfm.main` | enabled | mbc |  |
| `mbc.sfm.mokpo` | enabled | regional_mbc |  |
| `mbc.sfm.pohang` | enabled | mbc_pohang |  |
| `mbc.sfm.ulsan` | enabled | mbc_regional_vision |  |
| `mbc.sfm.wonju` | enabled | mbc_wonju |  |
| `mbc.sfm.yeosu` | enabled | regional_mbc |  |
| `obs.main.main` | enabled | independent |  |
| `sbs.dmb.main` | enabled | sbs |  |
| `sbs.lovefm.busan` | enabled | knn |  |
| `sbs.lovefm.main` | enabled | sbs |  |
| `sbs.powerfm.busan` | enabled | knn |  |
| `sbs.powerfm.cheongju` | enabled | cjb |  |
| `sbs.powerfm.chuncheon` | unsupported | g1 | g1tv.co.kr 자체는 접속되지만 FM 탭(/schedule/?mid=165_168_172)이 송출소 주파수/커버리지 표만 보여줄 뿐, 실제 프로그램 편성표를 아예 게시하지 않음 |
| `sbs.powerfm.daegu` | enabled | tbc |  |
| `sbs.powerfm.daejeon` | enabled | tjb |  |
| `sbs.powerfm.gwangju` | enabled | kbc |  |
| `sbs.powerfm.jeju` | enabled | jibs |  |
| `sbs.powerfm.jeonju` | unsupported | jtv | jtv.co.kr이 클라우드 환경에서 접속 자체가 막혀 있음(직접 접속 3회 모두 ConnectError: Connection reset by peer) |
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
