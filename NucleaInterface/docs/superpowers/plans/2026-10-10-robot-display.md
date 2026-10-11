# Robot Display Implementation Plan

**Goal:** Integrate the existing ST7789 GIFs with the accepted wakeword event.
**Architecture:** Native ESP-IDF esp_lcd + portable AnimatedGIF, independent visual
task, bounded raw RGB565 transition cache in PSRAM. Dedicated I2S capture task
and single-flight HTTP worker keep network/display work outside audio reads.
**Approved design:** Previous feasibility analysis, accepted by the user.

- [x] Add failing integration contract tests for tasks, events, assets and pins.
- [x] Vendor the Apache-2.0 decoder at a fixed upstream commit; add LittleFS.
- [x] Preserve NVS at 0x9000/0x6000 and GIF region at 0x310000/0xCF0000.
- [x] Implement compositing (transparency/disposal), reverse transition and
      sleeping/waking/awake/closing states; 30 s idle timer pauses during a request.
- [x] Make mic pins configurable (BCLK=4, WS=5, SD=6 with screen enabled);
      retain 11/10/12 defaults when the display is disabled; reject conflicts.
- [x] Separate continuous I2S capture from inference and asynchronous upload;
      keep the recording buffer owned until the HTTP worker finishes.
- [x] Build the assets with the firmware and document rewiring/menuconfig/flash.
- [x] Run focused contracts and full ESP-IDF build. Hardware verification remains
      manual: orientation/colors, transitions, audio continuity, network response.

## Verification

- 16 focused Python contract/reference tests passed; three compile-time C++
  state scenarios passed in the ESP-IDF build.
- Final ESP-IDF 5.5.5 build passed: application 0x15b7c0 bytes, 55% free in
  the 3 MiB factory partition. LittleFS image generated and all three files
  verified byte-identical to the original GIFs by SHA-256.
- Review fixes: reset wake confirmation after detection/request/gap while
  preserving cooldown; report read failures and DMA overflow as audio gaps.
- No physical flash or hardware testing performed. No commit created.
