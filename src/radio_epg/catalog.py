"""라디오 플레이어 채널 스냅샷을 정규화된 카탈로그로 읽는다."""

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from radio_epg.ids import canonical_channel_id, tuple_alias


@dataclass(frozen=True, slots=True)
class CatalogChannel:
    """하나 이상의 플레이어 행을 접은 안정적인 채널 레코드."""

    channel_id: str
    name: str
    stn: str
    ch: str | None
    city: str | None
    region_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RadioCatalog:
    """정규 채널과 현재 플레이어 별칭을 함께 보관한다."""

    channels: dict[str, CatalogChannel]
    radio_aliases: dict[str, str]
    tuple_aliases: dict[str, str]


def _required_text(row: dict[str, Any], key: str) -> str:
    """카탈로그 행의 필수 문자열 필드를 검증한다."""
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Catalog field {key!r} must be a non-empty string")
    return value


def _optional_text(row: dict[str, Any], key: str) -> str | None:
    """카탈로그 행의 선택 문자열 필드를 검증한다."""
    value = row.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"Catalog field {key!r} must be a non-empty string or null")
    return value


def _add_region(channel: CatalogChannel, region_id: str) -> CatalogChannel:
    """중복 채널에 아직 없는 플레이어 지역을 추가한다."""
    if region_id in channel.region_ids:
        return channel
    return replace(channel, region_ids=(*channel.region_ids, region_id))


def _load_rows(path: Path) -> list[dict[str, Any]]:
    """JSON 스냅샷을 객체 행 목록으로 읽고 구조를 검증한다."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not all(isinstance(row, dict) for row in raw):
        raise ValueError("Radio catalog must be a JSON array of objects")
    return raw


def load_catalog(path: Path) -> RadioCatalog:
    """플레이어 스냅샷을 중복이 제거된 채널과 별칭으로 변환한다."""
    channels: dict[str, CatalogChannel] = {}
    radio_aliases: dict[str, str] = {}
    tuple_aliases: dict[str, str] = {}

    for row in _load_rows(path):
        radio_id = _required_text(row, "id")
        region_id = _required_text(row, "regionId")
        name = _required_text(row, "name")
        stn = _required_text(row, "stn")
        ch = _optional_text(row, "ch")
        city = _optional_text(row, "city")
        channel_id = canonical_channel_id(stn, ch, city)

        if channel_id in channels:
            channels[channel_id] = _add_region(channels[channel_id], region_id)
        else:
            channels[channel_id] = CatalogChannel(
                channel_id=channel_id,
                name=name,
                stn=stn,
                ch=ch,
                city=city,
                region_ids=(region_id,),
            )

        radio_aliases[radio_id] = channel_id
        tuple_aliases[tuple_alias(stn, ch, city)] = channel_id

    return RadioCatalog(
        channels=channels,
        radio_aliases=radio_aliases,
        tuple_aliases=tuple_aliases,
    )
