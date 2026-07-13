"""라디오 EPG 명령행 인터페이스의 진입점."""

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from radio_epg.collector import Collector
from radio_epg.config import CollectorSettings, load_sources
from radio_epg.fixture_validation import validate_fixtures
from radio_epg.models import ImportBatch
from radio_epg.publisher import publish_batch
from radio_epg.registry import default_registry

_SOURCES_PATH = Path(__file__).parents[2] / "data" / "sources.json"


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

    commands.add_parser("validate-fixtures", help="등록된 fixture 계약을 검증한다")
    commands.add_parser("coverage", help="설정된 source 커버리지를 출력한다")
    return parser


async def _run_collection(source_id: str | None) -> int:
    settings = CollectorSettings.from_env()
    sources = load_sources(_SOURCES_PATH)
    selected = None if source_id is None else {source_id}
    adapters = default_registry().build(sources, source_ids=selected)

    async def publisher(batch: ImportBatch) -> dict[str, object]:
        return await publish_batch(
            batch,
            base_url=settings.api_base_url,
            token=settings.ingest_token,
        )

    report = await Collector(adapters, publisher=publisher).collect()
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


def main(argv: list[str] | None = None) -> int:
    """선택한 CLI 명령을 실행하고 process status를 반환한다."""
    arguments = build_parser().parse_args(argv)
    if arguments.command == "collect":
        return asyncio.run(_run_collection(arguments.source))
    if arguments.command == "validate-fixtures":
        return _validate_fixtures()
    return _configured_sources()
