"""지역·독립 방송 mapping의 엄격한 데이터 계약과 채널별 수집 엔진."""

import asyncio
import json
import re
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol, Self
from urllib.parse import unquote

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from radio_epg.adapters import additional
from radio_epg.adapters.html_schedule import ScheduleRow
from radio_epg.catalog import RadioCatalog
from radio_epg.config import SourceConfig
from radio_epg.models import AdapterResult
from radio_epg.validation import SchedulePolicy

_ROOT = Path(__file__).parents[2]
_MAPPING = _ROOT / "data" / "mappings" / "regional.json"
_CATALOG = _ROOT / "data" / "radio_channels.json"
_VISION_DIR = _ROOT / "data" / "vision"

RegionalStatus = Literal["enabled", "unsupported"]


class RegionalMappingError(ValueError):
    """지역 mapping 구조나 catalog 소유권이 잘못됐을 때 발생한다."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RegionalChannelMapping(_StrictModel):
    """하나의 canonical identity에 대한 조사 결과이자 수집 설정 그 자체."""

    channel_id: str = Field(min_length=1)
    family: str = Field(min_length=1)
    status: RegionalStatus
    source_url: str = Field(pattern=r"^https?://")
    parser: str = Field(min_length=1)
    reason: str | None = None
    last_investigated: date

    @model_validator(mode="after")
    def unsupported_requires_a_reason(self) -> Self:
        if self.status == "unsupported" and not self.reason:
            raise ValueError("unsupported regional mapping requires a reason")
        if self.status == "enabled" and self.reason is not None:
            raise ValueError("enabled regional mapping must not include a reason")
        return self


class RegionalMapping(_StrictModel):
    """지역 방송망이 소유하는 모든 identity 목록."""

    schema_version: Literal[1]
    channels: tuple[RegionalChannelMapping, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def channel_ids_must_be_unique(self) -> Self:
        channel_ids = [item.channel_id for item in self.channels]
        if len(channel_ids) != len(set(channel_ids)):
            raise ValueError("regional mapping channel IDs must be unique")
        return self


def load_regional_mapping(path: Path) -> RegionalMapping:
    """지역 mapping을 strict schema로 읽는다."""
    try:
        return RegionalMapping.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise RegionalMappingError("regional mapping schema changed") from error


def validate_regional_catalog(mapping: RegionalMapping, catalog: RadioCatalog) -> None:
    """mapping identity가 실제 catalog에 존재하는지 검증한다."""
    unknown = {item.channel_id for item in mapping.channels} - set(catalog.channels)
    if unknown:
        unknown_ids = sorted(unknown)
        raise RegionalMappingError(f"regional mapping contains unknown channels: {unknown_ids!r}")


def channels_for_family(
    mapping: RegionalMapping, family: str
) -> tuple[RegionalChannelMapping, ...]:
    """mapping 순서를 유지하며 한 방송사(family)를 선택한다."""
    return tuple(item for item in mapping.channels if item.family == family)


class RegionalUnavailableError(ValueError):
    """family에 fixture-verified enabled channel이 없을 때 발생한다."""


class _Client(Protocol):
    async def get(self, url: str) -> httpx.Response: ...


def _format_url(item: RegionalChannelMapping, day: date) -> str:
    """채널마다 필요한 자리표시자가 달라 한 번에 전부 채워 넣는다."""
    return item.source_url.format(
        date=day.isoformat(),
        date_compact=day.strftime("%Y%m%d"),
        weekday=(day.weekday() + 1) % 7,
        year=day.strftime("%Y"),
        month=day.strftime("%m"),
        day=day.strftime("%d"),
    )


async def _mbc_weekly_template(
    client: _Client, day: date, item: RegionalChannelMapping
) -> tuple[ScheduleRow, ...]:
    text = (await client.get(_format_url(item, day))).text
    return additional.mbc_regional_weekly(text, day, item.channel_id)[item.channel_id]


async def _mbc_shared_cms(
    client: _Client, day: date, item: RegionalChannelMapping
) -> tuple[ScheduleRow, ...]:
    text = (await client.get(_format_url(item, day))).text
    return additional.mbc_shared_cms(text, day, item.channel_id)[item.channel_id]


async def _mbc_wonju(
    client: _Client, day: date, item: RegionalChannelMapping
) -> tuple[ScheduleRow, ...]:
    text = (await client.get(item.source_url)).text
    return additional.wonju_mbc(text, day, item.channel_id)[item.channel_id]


async def _mbc_pohang(
    client: _Client, day: date, item: RegionalChannelMapping
) -> tuple[ScheduleRow, ...]:
    url = _format_url(item, day)
    response = await client.get(url)
    response.raise_for_status()
    path = url.rsplit("/", 1)[-1].split("?", 1)[0]
    return additional.phmbc(response.text, day, item.channel_id, path)[item.channel_id]


async def _cbs_appradio(
    client: _Client, day: date, item: RegionalChannelMapping
) -> tuple[ScheduleRow, ...]:
    text = (await client.get(_format_url(item, day))).text
    return additional.cbs_regional(text, day, item.channel_id)[item.channel_id]


async def _cbs_youngdong(
    client: _Client, day: date, item: RegionalChannelMapping
) -> tuple[ScheduleRow, ...]:
    response = await client.get(item.source_url)
    # 강원영동CBS 페이지는 Content-Type에 charset 정보가 없고 실제로는 EUC-KR로
    # 응답한다(자동 감지에 맡기면 깨진다).
    response.encoding = "euc-kr"
    return additional.cbs_youngdong(response.text, day)[item.channel_id]


async def _sbs_tbc(
    client: _Client, day: date, item: RegionalChannelMapping
) -> tuple[ScheduleRow, ...]:
    text = (await client.get(_format_url(item, day))).text
    return additional.sbs_affiliate_tbc(text, day, item.channel_id)[item.channel_id]


async def _sbs_knn(
    client: _Client, day: date, item: RegionalChannelMapping
) -> tuple[ScheduleRow, ...]:
    # KNN(부산)은 channel= 파라미터 값과 무관하게 파워FM/러브FM 응답이 한 번에
    # 함께 온다(어느 탭을 펼쳐 보일지에만 쓰임). 그래서 두 채널이 요청마다 같은
    # 응답을 한 번씩 다시 받는다(중복 호출 1회, 데이터 오류는 아니다).
    text = (await client.get(_format_url(item, day))).text
    return additional.knn_busan(text, day, item.channel_id)[item.channel_id]


async def _sbs_tjb(
    client: _Client, day: date, item: RegionalChannelMapping
) -> tuple[ScheduleRow, ...]:
    text = (await client.get(_format_url(item, day))).text
    return additional.tjb_daejeon(text, day, item.channel_id)[item.channel_id]


async def _sbs_ubc(
    client: _Client, day: date, item: RegionalChannelMapping
) -> tuple[ScheduleRow, ...]:
    text = (await client.get(_format_url(item, day))).text
    return additional.ubc_ulsan(text, day, item.channel_id)[item.channel_id]


async def _sbs_cjb(
    client: _Client, day: date, item: RegionalChannelMapping
) -> tuple[ScheduleRow, ...]:
    text = (await client.get(_format_url(item, day))).text
    return additional.cjb_cheongju(text, day, item.channel_id)[item.channel_id]


async def _sbs_jibs(
    client: _Client, day: date, item: RegionalChannelMapping
) -> tuple[ScheduleRow, ...]:
    text = (await client.get(_format_url(item, day))).text
    return additional.jibs_jeju(text, day, item.channel_id)[item.channel_id]


_BUSAN_MBC_PDF_LINK = re.compile(r'viewer\.asp\?file=([^"\'<>\s]+)')


async def _get_with_retry(client: _Client, url: str, *, attempts: int = 4) -> httpx.Response:
    # busanmbc.co.kr는 GH Actions 환경에서 간헐적으로 RemoteProtocolError로 연결이
    # 끊긴다(로컬 sandbox에서는 재현되지 않음 - befm/ggn과 같은 호스팅 쪽 불안정으로
    # 추정). 짧게 재시도한다.
    for attempt in range(attempts):
        try:
            return await client.get(url)
        except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ConnectTimeout):
            if attempt == attempts - 1:
                raise
            await asyncio.sleep(1.0 * (2**attempt))
    raise AssertionError("unreachable")


async def _mbc_busan_pdf_bytes(client: _Client, item: RegionalChannelMapping) -> bytes:
    # 부산MBC는 요일별 편성표 대신 편성표 페이지(oar05/06.asp) 안의 iframe이
    # 그 주의 PDF를 가리킨다. PDF 파일명이 매주 바뀌므로 페이지를 먼저 읽어
    # 현재 PDF 링크를 알아낸 뒤에 그 PDF를 받는다.
    page_response = await _get_with_retry(client, item.source_url)
    page_response.raise_for_status()
    match = _BUSAN_MBC_PDF_LINK.search(page_response.text)
    if match is None:
        raise ValueError("no rows")
    pdf_response = await _get_with_retry(client, unquote(match.group(1)))
    pdf_response.raise_for_status()
    return pdf_response.content


async def _mbc_busan_sfm(
    client: _Client, day: date, item: RegionalChannelMapping
) -> tuple[ScheduleRow, ...]:
    pdf_bytes = await _mbc_busan_pdf_bytes(client, item)
    return additional.busan_mbc_sfm(pdf_bytes, day, item.channel_id)[item.channel_id]


async def _mbc_busan_fm4u(
    client: _Client, day: date, item: RegionalChannelMapping
) -> tuple[ScheduleRow, ...]:
    pdf_bytes = await _mbc_busan_pdf_bytes(client, item)
    return additional.busan_mbc_fm4u(pdf_bytes, day, item.channel_id)[item.channel_id]


async def _vision_json(
    client: _Client, day: date, item: RegionalChannelMapping
) -> tuple[ScheduleRow, ...]:
    # 편성표가 이미지로만 공개돼 결정적으로 파싱할 수 없는 채널은, Cowork가 주기적으로
    # 이미지를 읽어 정해진 스키마의 JSON을 이 repo(data/vision/<channel_id>.json)에
    # 커밋해 넣는다(스키마는 additional.vision_json 참고). 네트워크 요청 없이 그
    # 커밋된 파일만 읽는다 - 아직 그 주 파일이 없거나 오래됐으면 "no rows"로 넘어간다.
    del client
    path = _VISION_DIR / f"{item.channel_id}.json"
    if not path.exists():
        raise ValueError("no rows")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return additional.vision_json(payload, day, item.channel_id)[item.channel_id]


# RegionalChannelMapping.parser 값이 곧 실제 수집 방식을 고르는 키다 - 새 지역
# 채널을 추가할 때는 이 값이 가리키는 fetch/parse 로직이 여기 있어야 한다.
_PARSERS: dict[
    str, Callable[[_Client, date, RegionalChannelMapping], Awaitable[tuple[ScheduleRow, ...]]]
] = {
    "mbc-weekly-template": _mbc_weekly_template,
    "mbc-shared-cms": _mbc_shared_cms,
    "mbc-wonju": _mbc_wonju,
    "mbc-pohang": _mbc_pohang,
    "cbs-appradio": _cbs_appradio,
    "cbs-youngdong": _cbs_youngdong,
    "sbs-tbc": _sbs_tbc,
    "sbs-knn": _sbs_knn,
    "sbs-tjb": _sbs_tjb,
    "sbs-ubc": _sbs_ubc,
    "sbs-cjb": _sbs_cjb,
    "sbs-jibs": _sbs_jibs,
    "mbc-busan-sfm": _mbc_busan_sfm,
    "mbc-busan-fm4u": _mbc_busan_fm4u,
    "vision-json": _vision_json,
}

# phmbc.co.kr·busanmbc.co.kr가 중간 인증서를 보내지 않아 기본 TLS 체인 검증이
# 실패한다(브라우저는 이미 아는 중간 인증서로 넘어가지만 httpx는 그렇지 않음).
# 이 source_id들만 검증을 끄고 브라우저 User-Agent를 쓴다 - 같은 엔진을 쓰는
# 다른 지역 방송사 소스는 영향받지 않는다.
_INSECURE_SOURCE_IDS = {"mbc-pohang", "mbc-busan"}

# wjmbc.co.kr는 PoliteHttpClient가 보내는 식별용 User-Agent("radio-epg/0.1 ...")를
# 406으로 막는다(브라우저 User-Agent는 통과). TLS는 정상이라 검증까지 끌 필요는
# 없고, 이 source_id만 브라우저 User-Agent를 쓰는 별도 클라이언트로 뺀다.
_BROWSER_UA_SOURCE_IDS = {"mbc-wonju"}


class ConfiguredRegionalAdapter:
    """지역 방송망 채널 목록(regional.json)을 순회하며 채널별 parser로 수집한다."""

    family = ""
    schedule_policy = SchedulePolicy(allow_adjacent=True)

    def __init__(
        self,
        source: SourceConfig,
        *,
        client: _Client | None = None,
        mapping_path: Path = _MAPPING,
        catalog_path: Path = _CATALOG,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.source = source
        self._client = client
        self._mapping = load_regional_mapping(mapping_path)
        self._catalog_path = catalog_path
        self._now = now

    async def collect(self, window: object) -> AdapterResult:
        from radio_epg.adapters.base import CollectionWindow
        from radio_epg.http import PoliteHttpClient

        if not isinstance(window, CollectionWindow):
            raise TypeError("regional adapter requires CollectionWindow")
        if self._client is not None:
            return await self._collect_with(self._client, window)
        if self.source.source_id in _INSECURE_SOURCE_IDS:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=30,
                verify=False,
                headers={"User-Agent": additional.BROWSER_USER_AGENT},
            ) as client:
                return await self._collect_with(client, window)
        if self.source.source_id in _BROWSER_UA_SOURCE_IDS:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=30,
                headers={"User-Agent": additional.BROWSER_USER_AGENT},
            ) as client:
                return await self._collect_with(client, window)
        async with PoliteHttpClient() as client:
            return await self._collect_with(client, window)

    async def _collect_with(self, client: _Client, window: object) -> AdapterResult:
        from radio_epg.adapters.base import CollectionWindow
        from radio_epg.adapters.html_schedule import (
            ChannelMapping,
            ChannelMappingFile,
            normalize_rows,
        )

        if not isinstance(window, CollectionWindow):
            raise TypeError("regional adapter requires CollectionWindow")
        family_channels = channels_for_family(self._mapping, self.family)
        enabled = tuple(item for item in family_channels if item.status == "enabled")
        if not enabled:
            raise RegionalUnavailableError(f"no enabled channels for {self.family}")
        rows: dict[str, list[ScheduleRow]] = defaultdict(list)
        current = window.start
        while current <= window.end:
            for item in enabled:
                parser = _PARSERS[item.parser]
                try:
                    rows[item.channel_id].extend(await parser(client, current, item))
                except ValueError as error:
                    if "no rows" not in str(error):
                        raise
            current += timedelta(days=1)
        normalized_mapping = ChannelMappingFile(
            channels=tuple(
                ChannelMapping(
                    channel_id=item.channel_id,
                    upstream_code=item.channel_id,
                    url=item.source_url,
                    parser=item.parser,
                    evidence_date=item.last_investigated,
                )
                for item in enabled
            )
        )
        return normalize_rows(
            source=self.source,
            mapping=normalized_mapping,
            catalog_path=self._catalog_path,
            rows=rows,
            fetched_at=self._now(),
        )
