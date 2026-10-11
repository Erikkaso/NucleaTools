# ESP32 Audio Bridge Design

## Goal

After the ESP32 detects the Nuclea wake word, capture a WAV command, send it to
NucleaInterface, and play the n8n/TTS response in an open browser.

## Data flow

1. ESP32 connects to configured Wi-Fi and keeps wake-word inference active.
2. Detection starts a PCM16 16 kHz mono recording in PSRAM with 400 ms pre-roll.
3. Recording ends after 2 seconds below the configured speech level or after 15 seconds.
4. ESP32 posts a multipart WAV as `audio` plus `deviceId` to `/api/device-audio`.
5. NucleaInterface forwards the request to n8n using `deviceId` as `sessionId`.
6. The returned audio is held only in a one-item in-memory mailbox.
7. The browser polls `/api/device-response`, consumes the audio, and plays it.

## Constraints

- No audio persistence.
- No speaker output on the ESP32.
- Wi-Fi credentials, interface URL, device ID, silence threshold and timings are configurable with `menuconfig`.
- The existing browser text/audio flows remain unchanged.
- A failed or missing response must not replace a queued valid response.

## Verification

- Flask tests cover upload validation, n8n forwarding, mailbox consumption and browser polling.
- ESP32 host-side contract tests cover the recording and upload integration.
- The ESP-IDF project must compile for ESP32-S3.
