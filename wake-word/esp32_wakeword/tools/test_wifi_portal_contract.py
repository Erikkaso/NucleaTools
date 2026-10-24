from pathlib import Path
import unittest


MAIN = Path(__file__).resolve().parents[1] / "main"


class WifiPortalContractTests(unittest.TestCase):
    def test_omitted_gateway_and_key_preserve_saved_values(self):
        wifi = (MAIN / "wifi_station.cc").read_text(encoding="utf-8")
        handler = wifi.split("esp_err_t WifiStation::HandleConfigure", 1)[1]
        self.assertIn("std::memcpy(candidate.base_url, wifi->settings_.base_url", handler)
        self.assertIn("std::memcpy(pending.auth_key, wifi->auth_key_", handler)
        self.assertIn("bool valid_url = !url ||", handler)
        self.assertIn("bool valid_key = !key ||", handler)
        self.assertIn("url->valuestring[0]", handler)
        self.assertIn("key->valuestring[0]", handler)

    def test_auth_key_is_separate_from_legacy_settings_and_never_read_back(self):
        wifi = (MAIN / "wifi_station.cc").read_text(encoding="utf-8")
        header = (MAIN / "wifi_station.h").read_text(encoding="utf-8")
        legacy = header.split("struct WifiSettings {", 1)[1].split("};", 1)[0]
        self.assertNotIn("auth_key", legacy)
        self.assertIn('nvs_get_str(nvs, "auth_key"', wifi)
        self.assertIn('nvs_set_str(nvs, "auth_key"', wifi)
        status = wifi.split("esp_err_t WifiStation::HandleStatus", 1)[1].split("esp_err_t WifiStation::HandleScan", 1)[0]
        self.assertIn('"auth_configured"', status)
        self.assertNotIn('cJSON_AddStringToObject(root, "auth_key"', status)
        uploader = (MAIN / "audio_uploader.cc").read_text(encoding="utf-8")
        self.assertIn('"X-Nuclea-Key", auth_key.c_str()', uploader)
        self.assertIn('base_url.compare(0, 8, "https://")', uploader)
        self.assertIn("config.disable_auto_redirect = true", uploader)

    def test_blank_saved_url_gets_default_before_validation_without_nvs_write(self):
        wifi = (MAIN / "wifi_station.cc").read_text(encoding="utf-8")
        load = wifi.split('size_t size = sizeof(settings_);', 1)[1]
        load = load.split('nvs_close(nvs);', 1)[0]
        self.assertIn("settings_.base_url[0] == '\\0'", load)
        self.assertLess(load.index("std::memcpy(settings_.base_url"),
                        load.index("!ValidSettings(settings_)"))
        self.assertIn('https://voice-gateway.200-129-37-25.sslip.io', wifi)
        self.assertNotIn("nvs_set", load)
        self.assertNotIn("SaveSettings", load)

    def test_boot_button_reopens_portal_without_erasing_saved_settings(self):
        wifi = (MAIN / "wifi_station.cc").read_text(encoding="utf-8")
        self.assertIn("gpio_get_level(GPIO_NUM_0)", wifi)
        self.assertGreaterEqual(wifi.count("PollPortalButton();"), 2)
        self.assertIn("manual_portal_ = true", wifi)
        self.assertIn("manual_portal_ = false", wifi)
        self.assertIn("!manual_portal_", wifi)
        self.assertNotIn("nvs_erase", wifi)
        cmake = (MAIN / "CMakeLists.txt").read_text(encoding="utf-8")
        self.assertIn("portal_button_tests.cc", cmake)

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
