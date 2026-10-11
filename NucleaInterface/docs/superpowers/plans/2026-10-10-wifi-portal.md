# Wi-Fi Portal Implementation Plan

**Goal:** Configure Wi-Fi and the NucleaInterface URL from a browser, without recompiling.

**Approved design:** Protected Nuclea-Config SoftAP at 192.168.4.1. Browser
selects a 2.4 GHz network and submits credentials plus the interface base URL.
Test the connection before committing one versioned NVS configuration blob.
After 30 seconds disconnected, reopen the portal without deleting saved data.
Keep the AP password in NVS and print it only to the local serial monitor.
No DNS captive redirect or Internet routing is needed for manual IP access.

**Architecture:** wifi_station owns the connection worker, single pending
configuration, NVS state, and HTTP server. wifi_portal.h contains the embedded
page. AudioUploader receives a snapshot of the saved base URL.

**Essential checks only:** two portal integration/source contracts, existing
four audio bridge contracts, and the ESP-IDF firmware build. Hardware checks
remain first provisioning, wrong password, reboot persistence and network loss.

- [x] Add the portal contracts and confirm failure on the old implementation.
- [x] Implement browser portal, bounded connection worker and NVS persistence.
- [x] Wire runtime URL into upload, remove compile-time Wi-Fi credentials.
- [x] Update usage docs; run the focused tests and firmware build.

Verified locally: 6 source/integration contracts passed; embedded JavaScript
passed `node --check`; ESP-IDF 5.5.5 `idf.py build` completed successfully.
The original 1 MiB app partition was too small. Use the standard 1500 KiB
single factory app partition, retaining NVS offsets; final size check reports
13% free. No device flashing or physical Wi-Fi tests were performed.

Do not change DSP, model, microphone settings or existing browser audio flow.
