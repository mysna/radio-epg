"""라디오 채널의 안정적인 식별자와 별칭을 생성한다."""

import re

_ID_SEGMENT = re.compile(r"[a-z0-9][a-z0-9_-]*")


def _normalize_segment(value: str | None) -> str:
    """선택적 식별자 값을 소문자 ASCII 세그먼트로 정규화한다."""
    segment = (value or "main").strip().lower()
    if not segment.isascii() or _ID_SEGMENT.fullmatch(segment) is None:
        raise ValueError(f"ID segments must be lowercase ASCII: {value!r}")
    return segment


def canonical_channel_id(stn: str, ch: str | None, city: str | None) -> str:
    """방송사·채널·도시 튜플에서 안정적인 채널 ID를 생성한다."""
    return ".".join(_normalize_segment(value) for value in (stn, ch, city))


def tuple_alias(stn: str, ch: str | None, city: str | None) -> str:
    """기존 플레이어 조회 튜플과 호환되는 별칭을 생성한다."""
    return "/".join(_normalize_segment(value) for value in (stn, ch, city))
