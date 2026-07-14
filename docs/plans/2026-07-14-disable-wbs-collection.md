# WBS Collection Disablement Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 정기 및 `--all` 수집 실행에서 WBS source를 일시 제외한다.

**Architecture:** Source 등록과 parser는 유지하고 source 설정의 `enabled` 값만 끈다. Registry 테스트가 WBS의 비활성 상태를 고정한다.

**Tech Stack:** JSON, Python, pytest

---

### Task 1: WBS source 비활성화

**Files:**
- Modify: `tests/test_registry.py`
- Modify: `data/sources.json`

**Step 1: Write the failing test**

`tests/test_registry.py`의 비활성 source 집합에 `wbs`를 추가한다.

**Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_registry.py`
Expected: WBS가 아직 활성 상태여서 FAIL.

**Step 3: Write minimal implementation**

`data/sources.json`의 WBS 항목에서 `"enabled": false`로 변경한다.

**Step 4: Run verification**

Run: `uv run pytest -q tests/test_registry.py && uv run pytest -q`
Expected: registry 테스트와 전체 테스트 PASS.

**Step 5: Commit and push**

WBS 설정, 테스트, 구현 계획만 커밋하고 `origin/main`으로 푸시한다.
