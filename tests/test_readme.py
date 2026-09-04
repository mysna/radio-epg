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
        "turso db create",
        "npm run db:migrate",
        "wrangler secret put",
        "TURSO_DATABASE_URL",
        "TURSO_AUTH_TOKEN",
        "wrangler deploy",
        "radio-epg smoke",
        "/v1/admin/retention",
        "workflow_dispatch",
        "17 16 * * *",
        "01:17 KST",
    }
    missing = {token for token in required if token not in readme}
    assert not missing


def test_readme_has_operational_and_extension_sections() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    headings = {
        "## API 예시",
        "## Source adapter 추가",
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
    assert worker.splitlines() == [
        "INGEST_TOKEN=<GENERATE_A_RANDOM_TOKEN>",
        "# 로컬 개발은 `turso dev`로 띄운 서버를 그대로 가리키면 된다 (인증 불필요).",
        "TURSO_DATABASE_URL=http://127.0.0.1:8080",
        "TURSO_AUTH_TOKEN=",
    ]
