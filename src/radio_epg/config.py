"""수집 소스와 환경 기반 배포 설정을 읽는다."""

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class SourceConfig(BaseModel):
    """비밀정보를 포함하지 않는 한 편성 소스의 정적 설정."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    source_kind: str = Field(min_length=1, max_length=100)
    source_url: str = Field(min_length=1, max_length=2048)
    priority: int = Field(ge=0)
    adapter: str = Field(min_length=1, max_length=100)
    enabled: bool = True


_SOURCE_LIST = TypeAdapter(tuple[SourceConfig, ...])


def load_sources(path: Path) -> tuple[SourceConfig, ...]:
    """JSON 파일을 엄격한 source 설정 목록으로 읽는다."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return _SOURCE_LIST.validate_python(raw)


@dataclass(frozen=True, slots=True)
class CollectorSettings:
    """환경 변수에서만 읽는 ingestion 연결 설정."""

    api_base_url: str
    ingest_token: str = field(repr=False)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "CollectorSettings":
        """필수 환경 변수가 없거나 비어 있으면 즉시 실패한다."""
        values = os.environ if environ is None else environ
        api_base_url = values.get("EPG_API_BASE_URL", "").strip()
        ingest_token = values.get("EPG_INGEST_TOKEN", "")
        if not api_base_url:
            raise ValueError("EPG_API_BASE_URL must be set")
        if not ingest_token:
            raise ValueError("EPG_INGEST_TOKEN must be set")
        return cls(api_base_url=api_base_url, ingest_token=ingest_token)
