# Collection Schedule Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move daily EPG collection from 04:17 KST to 01:17 KST and keep the operations guide accurate.

**Architecture:** Change only the GitHub Actions UTC cron and its corresponding README description. Preserve the existing KST collection-date handoff shared by collection and retention.

**Tech Stack:** GitHub Actions YAML, Markdown, Python test suite

---

### Task 1: Change the collection schedule

**Files:**
- Modify: `.github/workflows/collect.yml:5`
- Modify: `README.md:191`
- Modify: `tests/test_workflows.py:68`
- Modify: `tests/test_readme.py:25-26`

**Step 1: Verify the current schedule**

Run: `rg -n '17 19|04:17' .github/workflows/collect.yml README.md`
Expected: both old schedule references are present.

**Step 2: Apply the minimal change**

Replace UTC `17 19 * * *` with `17 16 * * *` and KST `04:17` with `01:17`.

**Step 3: Verify schedule consistency**

Run: `rg -n '17 16|01:17|17 19|04:17' .github/workflows/collect.yml README.md`
Expected: only the new UTC cron and KST time are present.

**Step 4: Run tests**

Run: `uv run pytest -q`
Expected: all tests pass.

**Step 5: Commit and push**

Commit the workflow, documentation, and plan files, then push the current branch to its configured upstream.
