from pathlib import Path
import csv
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "main"


def read(path):
    return path.read_text(encoding="utf-8") if path.exists() else ""


class VisualContractTests(unittest.TestCase):
    def test_capture_marks_driver_losses_and_runtime_resets_confirmation(self):
        capture = read(MAIN / "audio_capture.cc")
        app = read(MAIN / "app_main.cc")
        gate = read(MAIN / "detection_gate.cc")
        self.assertIn("on_recv_q_ovf", capture)
        self.assertIn("loss_epoch_", capture)
        self.assertIn("LastLossEpoch()", app)
        self.assertGreaterEqual(app.count("gate.ResetConfirmation()"), 3)
        self.assertIn("void DetectionGate::ResetConfirmation()", gate)

    def test_display_and_audio_have_dedicated_tasks(self):
        display = read(MAIN / "robot_display.cc")
        capture = read(MAIN / "audio_capture.cc")
        app = read(MAIN / "app_main.cc")
        self.assertIn("xTaskCreatePinnedToCore", display)
        self.assertIn("xTaskCreatePinnedToCore", capture)
        self.assertIn("display.Wake()", app)
        self.assertIn("display.Ready()", app)
        self.assertIn("upload_worker.Start", app)
        self.assertNotIn("uploader.Upload", app)

    def test_display_partition_preserves_nvs_and_original_gif_offset(self):
        rows = {r[0].strip(): [v.strip() for v in r]
                for r in csv.reader(read(ROOT / "partitions.csv").splitlines())
                if r and not r[0].startswith("#")}
        self.assertIn("nvs", rows)
        self.assertIn("spiffs", rows)
        self.assertEqual(rows["nvs"][3:5], ["0x9000", "0x6000"])
        self.assertEqual(rows["spiffs"][3:5], ["0x310000", "0xCF0000"])

    def test_visual_asset_mount_never_formats_and_build_includes_assets(self):
        display = read(MAIN / "robot_display.cc")
        cmake = read(MAIN / "CMakeLists.txt")
        self.assertIn("format_if_mount_failed = false", display)
        self.assertIn("littlefs_create_partition_image", cmake)
        self.assertIn("FLASH_IN_PROJECT", cmake)
        for name in ("sleep2.gif", "wake-open2.gif", "wake-open2-reverse.gif", "idle.gif"):
            self.assertIn(name, display)

    def test_microphone_gpio_is_configurable_and_display_is_optional(self):
        config = (MAIN / "Kconfig.projbuild").read_text()
        for symbol in ("NUCLEA_DISPLAY_ENABLED", "NUCLEA_DISPLAY_IDLE_MS",
                       "NUCLEA_MIC_BCLK_GPIO", "NUCLEA_MIC_WS_GPIO", "NUCLEA_MIC_SD_GPIO"):
            self.assertIn("config " + symbol, config)


if __name__ == "__main__":
    unittest.main()
