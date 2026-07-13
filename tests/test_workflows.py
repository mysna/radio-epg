"""GitHub Actions workflow 계약을 검증한다."""

from pathlib import Path
from typing import Any, cast

import yaml

ROOT = Path(__file__).parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


YamlMap = dict[str, Any]


def _mapping(value: object) -> YamlMap:
    assert isinstance(value, dict)
    return cast(YamlMap, value)


def _load(name: str) -> YamlMap:
    document: object = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    return _mapping(document)


def _job(workflow: YamlMap, name: str) -> YamlMap:
    jobs = _mapping(workflow["jobs"])
    return _mapping(jobs[name])


def _steps(job: YamlMap) -> list[YamlMap]:
    steps = job["steps"]
    assert isinstance(steps, list)
    return [_mapping(step) for step in steps]


def _runs(job: YamlMap) -> list[str]:
    return [str(step["run"]) for step in _steps(job) if "run" in step]


def _assert_read_only(workflow: YamlMap) -> None:
    assert workflow["permissions"] == {"contents": "read"}


def test_ci_runs_locked_quality_and_test_suites() -> None:
    workflow = _load("ci.yml")
    _assert_read_only(workflow)
    triggers = _mapping(workflow["on"])
    assert {"push", "pull_request"} <= triggers.keys()

    python_runs = _runs(_job(workflow, "python"))
    assert "uv sync --locked --dev" in python_runs
    assert "uv run ruff check ." in python_runs
    assert "uv run ruff format --check ." in python_runs
    assert "uvx ty check" in python_runs
    assert "uv run pytest -q" in python_runs

    worker_runs = _runs(_job(workflow, "worker"))
    assert "npm ci --prefix worker" in worker_runs
    assert "npm --prefix worker test -- --run" in worker_runs
    assert "npm --prefix worker run typecheck" in worker_runs


def test_collection_is_single_non_overlapping_daily_import() -> None:
    workflow = _load("collect.yml")
    _assert_read_only(workflow)
    triggers = _mapping(workflow["on"])
    assert "workflow_dispatch" in triggers
    assert triggers["schedule"] == [{"cron": "17 19 * * *"}]
    assert workflow["concurrency"] == {
        "group": "radio-epg-collection",
        "cancel-in-progress": False,
    }

    collect = _job(workflow, "collect")
    runs = _runs(collect)
    joined = "\n".join(runs)
    assert joined.count("uv run radio-epg collect --all") == 1
    assert "tesseract-ocr-kor" in joined
    assert "libcairo2" in joined

    steps = _steps(collect)
    ingestion = next(step for step in steps if step.get("run") == "uv run radio-epg collect --all")
    assert ingestion["env"] == {
        "EPG_API_BASE_URL": "${{ vars.EPG_API_BASE_URL }}",
        "EPG_INGEST_TOKEN": "${{ secrets.EPG_INGEST_TOKEN }}",
    }
    retention = next(step for step in steps if step.get("name") == "Apply schedule retention")
    assert retention["if"] == "always()"
    assert retention["env"] == ingestion["env"]
    assert "/v1/admin/retention" in retention["run"]
    assert steps.index(ingestion) < steps.index(retention)
    diagnostics = next(step for step in steps if step.get("name") == "Upload sanitized diagnostics")
    assert diagnostics["if"] == "failure()"
    assert _mapping(diagnostics["with"])["if-no-files-found"] == "ignore"


def test_deployment_migrates_before_protected_worker_deploy() -> None:
    workflow = _load("deploy-worker.yml")
    _assert_read_only(workflow)
    deploy = _job(workflow, "deploy")
    assert deploy["environment"] == "production"
    assert deploy["env"] == {
        "CLOUDFLARE_API_TOKEN": "${{ secrets.CLOUDFLARE_API_TOKEN }}",
        "CLOUDFLARE_ACCOUNT_ID": "${{ vars.CLOUDFLARE_ACCOUNT_ID }}",
    }
    steps = _steps(deploy)
    migration = next(step for step in steps if step.get("name") == "Apply remote D1 migrations")
    deployment = next(step for step in steps if step.get("name") == "Deploy Worker")
    assert migration["working-directory"] == "worker"
    assert migration["run"] == "npm exec -- wrangler d1 migrations apply DB --remote"
    assert deployment["working-directory"] == "worker"
    assert deployment["run"] == "npm exec -- wrangler deploy"
    assert steps.index(migration) < steps.index(deployment)


def test_live_probe_is_separate_and_non_blocking() -> None:
    workflow = _load("live-probe.yml")
    _assert_read_only(workflow)
    probe = _job(workflow, "probe")
    assert probe["continue-on-error"] is True
    assert "uv run pytest tests/live -q" in _runs(probe)

    ci_text = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    assert "tests/live" not in ci_text
