"""라디오 EPG 명령행 인터페이스의 진입점."""

import argparse
import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

import httpx

from radio_epg.collector import Collector
from radio_epg.config import CollectorSettings, load_sources
from radio_epg.coverage import build_coverage, render_coverage_markdown
from radio_epg.fixture_validation import validate_fixtures
from radio_epg.image_publisher import ImagePublishSummary, publish_images
from radio_epg.models import ImportBatch
from radio_epg.publisher import publish_batch
from radio_epg.registry import default_registry

_SOURCES_PATH = Path(__file__).parents[2] / "data" / "sources.json"
_DEFAULT_SMOKE_RADIO_ID = "busan-039-kbs-1radio-busan"
_SMOKE_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)

SchedulePublisher = Callable[..., Awaitable[dict[str, Any]]]
ImagePublisher = Callable[..., Awaitable[ImagePublishSummary]]


class SmokeCheckError(RuntimeError):
    """배포 API가 smoke 계약을 충족하지 않을 때 발생한다."""


def app_name() -> str:
    """서비스의 안정적인 애플리케이션 이름을 반환한다."""
    return "radio-epg"


def build_parser() -> argparse.ArgumentParser:
    """지원하는 수집·검증·커버리지 명령을 정의한다."""
    parser = argparse.ArgumentParser(prog=app_name())
    commands = parser.add_subparsers(dest="command", required=True)

    collect = commands.add_parser("collect", help="활성 편성 source를 수집한다")
    selection = collect.add_mutually_exclusive_group(required=True)
    selection.add_argument("--all", action="store_true", help="모든 활성 source")
    selection.add_argument("--source", help="하나의 source ID")
    collect.add_argument(
        "--start-date",
        type=date.fromisoformat,
        help="수집 실행 전체가 공유할 KST 기준일 (YYYY-MM-DD)",
    )

    commands.add_parser("validate-fixtures", help="등록된 fixture 계약을 검증한다")
    coverage = commands.add_parser("coverage", help="설정된 source 커버리지를 출력한다")
    coverage.add_argument("--write", type=Path, help="Markdown 보고서를 저장할 경로")
    coverage.add_argument(
        "--require-accounted",
        action="store_true",
        help="현재 단계가 소유한 catalog identity 누락을 실패 처리한다",
    )
    smoke = commands.add_parser("smoke", help="배포된 공개 API의 핵심 경로를 확인한다")
    smoke.add_argument("--base-url", required=True, help="배포된 Worker base URL")
    smoke.add_argument(
        "--radio-id",
        default=_DEFAULT_SMOKE_RADIO_ID,
        help="별칭 호환성을 확인할 현재 라디오 플레이어 ID",
    )
    return parser


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SmokeCheckError(f"{label} response must be a JSON object")
    return cast(dict[str, Any], value)


def _list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise SmokeCheckError(f"{label} response must contain a list")
    return cast(list[Any], value)


async def _smoke_get(client: httpx.AsyncClient, path: str) -> dict[str, Any]:
    try:
        response = await client.get(path)
        response.raise_for_status()
    except (httpx.HTTPStatusError, httpx.NetworkError, httpx.TimeoutException) as error:
        raise SmokeCheckError(f"{path} smoke request failed") from error
    try:
        payload: object = response.json()
    except ValueError as error:
        raise SmokeCheckError(f"{path} response must be JSON") from error
    return _mapping(payload, path)


async def smoke_api(
    base_url: str,
    radio_id: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, object]:
    """health, 채널 목록·별칭, coverage 응답의 최소 배포 계약을 검사한다."""
    if not base_url.strip() or not radio_id.strip():
        raise ValueError("base_url and radio_id must not be empty")

    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        timeout=_SMOKE_TIMEOUT,
        transport=transport,
    ) as client:
        health = await _smoke_get(client, "/health")
        channels = _list((await _smoke_get(client, "/v1/channels")).get("channels"), "channels")
        channel = await _smoke_get(client, f"/v1/channels/{quote(radio_id, safe='')}")
        aliases = _list(channel.get("aliases"), "channel aliases")
        coverage = _list((await _smoke_get(client, "/v1/coverage")).get("sources"), "coverage")

    if health.get("service") != app_name():
        raise SmokeCheckError("health response identifies an unexpected service")
    if not channels:
        raise SmokeCheckError("channels response must contain at least one channel")
    if not coverage:
        raise SmokeCheckError("coverage response must contain at least one source")
    channel_id = channel.get("channel_id")
    if not isinstance(channel_id, str) or not channel_id:
        raise SmokeCheckError("radio ID did not resolve to a channel")
    if not any(isinstance(alias, dict) and alias.get("value") == radio_id for alias in aliases):
        raise SmokeCheckError("resolved channel does not preserve the requested radio ID")

    return {
        "service": app_name(),
        "channel_count": len(channels),
        "radio_id": radio_id,
        "channel_id": channel_id,
        "coverage_source_count": len(coverage),
    }


async def publish_collection_batch(
    batch: ImportBatch,
    *,
    base_url: str,
    token: str,
    schedule_publisher: SchedulePublisher = publish_batch,
    image_publisher: ImagePublisher = publish_images,
) -> dict[str, Any]:
    """편성을 먼저 저장한 뒤 이미지 후보를 best-effort로 게시한다."""
    result = await schedule_publisher(batch, base_url=base_url, token=token)
    image_summary = await image_publisher(
        batch.images,
        source_id=batch.source.source_id,
        base_url=base_url,
        token=token,
    )
    return {
        **result,
        "image_variant_count": image_summary.uploaded_variant_count,
        "image_error_count": image_summary.failed_candidate_count,
    }


async def _run_collection(source_id: str | None, start_date: date | None = None) -> int:
    settings = CollectorSettings.from_env()
    sources = load_sources(_SOURCES_PATH)
    selected = None if source_id is None else {source_id}
    adapters = default_registry().build(sources, source_ids=selected)

    async def publisher(batch: ImportBatch) -> dict[str, object]:
        return await publish_collection_batch(
            batch,
            base_url=settings.api_base_url,
            token=settings.ingest_token,
        )

    report = await Collector(adapters, publisher=publisher, start_date=start_date).collect()
    print(report.model_dump_json(indent=2))
    return 1 if any(run.status == "failed" for run in report.runs) else 0


def _configured_sources() -> int:
    sources = load_sources(_SOURCES_PATH)
    print(json.dumps([source.model_dump() for source in sources], ensure_ascii=False, indent=2))
    return 0


def _validate_fixtures() -> int:
    result = validate_fixtures()
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0


def _coverage(write_path: Path | None, *, require_accounted: bool) -> int:
    report = build_coverage(_SOURCES_PATH.parents[1], require_accounted=require_accounted)
    markdown = render_coverage_markdown(report)
    if write_path is not None:
        write_path.write_text(markdown, encoding="utf-8")
    else:
        print(markdown, end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    """선택한 CLI 명령을 실행하고 process status를 반환한다."""
    arguments = build_parser().parse_args(argv)
    if arguments.command == "collect":
        return asyncio.run(_run_collection(arguments.source, arguments.start_date))
    if arguments.command == "validate-fixtures":
        return _validate_fixtures()
    if arguments.command == "coverage":
        return _coverage(arguments.write, require_accounted=arguments.require_accounted)
    if arguments.command == "smoke":
        result = asyncio.run(smoke_api(arguments.base_url, arguments.radio_id))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    return _configured_sources()
