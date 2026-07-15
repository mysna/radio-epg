# Disable Image Publication Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Stop scheduled collection from downloading and publishing images while retaining the dormant image pipeline.

**Architecture:** Keep adapter image candidates and image modules unchanged. Make the collection publication boundary return after schedule import without invoking the image publisher.

**Tech Stack:** Python 3.13, pytest, httpx

---

### Task 1: Define the disabled behavior

1. Update the CLI test to expect only schedule publication.
2. Run it and confirm it fails because the image publisher is still called.

### Task 2: Disconnect image publication

1. Change `publish_collection_batch()` to return the schedule publisher result directly.
2. Update the integration test to expect `/v1/admin/import` and no `/v1/admin/images` calls.
3. Run the focused tests, then the full Python and Worker suites.
