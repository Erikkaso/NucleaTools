from pathlib import Path
import unittest


MAIN = Path(__file__).resolve().parents[1] / "main"


class WifiPortalContractTests(unittest.TestCase):
    def test_configuration_is_runtime_persisted_and_portal_is_protected(self):
        wifi = (MAIN / "wifi_station.cc").read_text(encoding="utf-8")
        for contract in (
            '"Nuclea-Config"', "WIFI_MODE_APSTA", "WIFI_STORAGE_RAM",
            "nvs_set_blob", "nvs_commit",
            "httpd_start", "kConnectionTimeoutMs", "httpd_resp_set_status",
        ):
            self.assertIn(contract, wifi)
        self.assertNotIn("portMAX_DELAY);\n    ESP_LOGI", wifi)

    def test_requested_ap_password_overrides_legacy_random_password(self):
        wifi = (MAIN / "wifi_station.cc").read_text(encoding="utf-8")
        self.assertIn('kApPassword = "Nuclea-Dell2026"', wifi)
        self.assertIn("std::memcpy(ap.ap.password, kApPassword", wifi)
        self.assertNotIn('nvs_get_str(nvs, "ap_password"', wifi)
        self.assertNotIn("esp_fill_random", wifi)

    def test_softap_guard_handles_dual_stack_without_relaxing_header_checks(self):
        wifi = (MAIN / "wifi_station.cc").read_text(encoding="utf-8")
        guard = wifi.split("bool WifiStation::AllowRequest", 1)[-1]
        guard = guard.split("esp_err_t WifiStation::HandlePage", 1)[0]
        for contract in (
            "sockaddr_storage local", "getsockname", "AF_INET", "AF_INET6",
            "sizeof(sockaddr_in)", "sizeof(sockaddr_in6)",
            '"::ffff:192.168.4.1"', "std::memcmp", "sin6_addr",
            "!origin_ok || !host_ok || !local_ok", "HTTPD_403_FORBIDDEN",
        ):
            self.assertIn(contract, guard)

    def test_uploader_uses_saved_url_and_portal_has_no_password_readback(self):
        uploader = (MAIN / "audio_uploader.cc").read_text(encoding="utf-8")
        header = (MAIN / "audio_uploader.h").read_text(encoding="utf-8")
        self.assertNotIn("CONFIG_NUCLEA_INTERFACE_URL", uploader)
        self.assertIn("base_url", header)
        wifi = (MAIN / "wifi_station.cc").read_text(encoding="utf-8")
        status = wifi.split("esp_err_t WifiStation::HandleStatus", 1)[-1]
        status = status.split("esp_err_t WifiStation::Handle", 1)[0]
        self.assertNotIn('cJSON_AddStringToObject(root, "password"', status)


if __name__ == "__main__":
    unittest.main()
