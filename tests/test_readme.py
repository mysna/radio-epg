"""배포·운영 문서의 필수 계약을 검증한다."""

from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_readme_covers_configuration_and_command_contracts() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    required = {
        "CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_API_TOKEN",
        "EPG_API_BASE_URL",
        "EPG_INGEST_TOKEN",
        "INGEST_TOKEN",
        "CORS_ORIGINS",
        "wrangler d1 create",
        "wrangler r2 bucket create",
        "wrangler d1 migrations apply",
        "wrangler secret put",
        "wrangler deploy",
        "workflow_dispatch",
        "17 19 * * *",
        "04:17 KST",
    }
    missing = {token for token in required if token not in readme}
    assert not missing


def test_readme_has_operational_and_extension_sections() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    headings = {
        "## API 예시",
        "## Source adapter 추가",
        "## 이미지 출처와 삭제 요청",
        "## 무료 사용량 모니터링",
        "## 백업과 복구",
        "## 문제 해결",
    }
    assert headings <= set(readme.splitlines())


def test_example_environment_files_use_visible_placeholders() -> None:
    collector = (ROOT / ".env.example").read_text(encoding="utf-8")
    worker = (ROOT / "worker" / ".dev.vars.example").read_text(encoding="utf-8")
    assert collector.splitlines() == [
        "EPG_API_BASE_URL=https://<WORKER_SUBDOMAIN>.workers.dev",
        "EPG_INGEST_TOKEN=<GENERATE_A_RANDOM_TOKEN>",
    ]
    assert worker.splitlines() == ["INGEST_TOKEN=<GENERATE_A_RANDOM_TOKEN>"]
