# ESP32 Audio Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record commands after ESP32 wake-word detection and play the generated response in NucleaInterface.

**Architecture:** The ESP32 records WAV audio in PSRAM and uploads it with a streaming multipart request. Flask forwards it to n8n, stores one response in memory, and exposes a consume-on-read browser endpoint.

**Tech Stack:** ESP-IDF 5.5, C++17, Flask 3, browser Fetch API, pytest/unittest.

**Spec:** `docs/superpowers/specs/2026-10-06-esp32-audio-bridge-design.md`

## Global Constraints

- Keep audio only in memory.
- Preserve existing browser request behavior.
- Configure device networking through `menuconfig`.
- Record PCM16 mono at 16 kHz and upload it as WAV.

---

### Task 1: Device response mailbox

- [ ] Add failing Flask tests for `/api/device-audio` and `/api/device-response`.
- [ ] Verify the tests fail because the routes do not exist.
- [ ] Implement a locked one-item response mailbox and the two routes.
- [ ] Verify all Flask tests pass.

### Task 2: Browser playback

- [ ] Add a failing page-contract test for polling and playback.
- [ ] Add browser polling with no overlapping requests.
- [ ] Verify the page-contract and existing tests pass.

### Task 3: ESP32 recording and upload

- [ ] Add failing source-contract tests for Wi-Fi, PSRAM recording and multipart upload.
- [ ] Implement configurable Wi-Fi with reconnect handling.
- [ ] Implement bounded PSRAM recording with pre-roll, silence and maximum-duration stops.
- [ ] Implement streaming multipart WAV upload.
- [ ] Replace the LED toggle action with record/upload states.
- [ ] Verify Python tests and compile the ESP-IDF project.

### Task 4: Documentation

- [ ] Document the device routes, browser delivery and `menuconfig` setup.
- [ ] Run final test and build verification.
