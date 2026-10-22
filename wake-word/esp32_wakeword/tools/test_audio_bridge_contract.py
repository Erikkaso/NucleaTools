from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "main"


class AudioBridgeContractTests(unittest.TestCase):
    def test_menuconfig_exposes_device_and_recording_settings(self) -> None:
        config = (MAIN / "Kconfig.projbuild").read_text(encoding="utf-8")

        for symbol in (
            "NUCLEA_DEVICE_ID",
            "NUCLEA_SILENCE_DBFS",
            "NUCLEA_SILENCE_MS",
            "NUCLEA_MIN_RECORDING_MS",
            "NUCLEA_MAX_RECORDING_MS",
        ):
            self.assertIn(f"config {symbol}", config)

    def test_runtime_connects_records_and_uploads_after_detection(self) -> None:
        app = (MAIN / "app_main.cc").read_text(encoding="utf-8")

        self.assertIn("WifiStation", app)
        self.assertIn("AudioRecorder", app)
        self.assertIn("AudioUploadWorker", app)
        self.assertIn("recorder.Start", app)
        self.assertIn("upload_worker.Start", app)
        self.assertIn("uploader.Upload", (MAIN / "audio_upload_worker.cc").read_text())

    def test_recorder_uses_psram_and_bounded_stops(self) -> None:
        recorder = (MAIN / "audio_recorder.cc").read_text(encoding="utf-8")

        self.assertIn("MALLOC_CAP_SPIRAM", recorder)
        self.assertIn("CONFIG_NUCLEA_SILENCE_MS", recorder)
        self.assertIn("CONFIG_NUCLEA_MAX_RECORDING_MS", recorder)

    def test_uploader_streams_multipart_wav(self) -> None:
        uploader = (MAIN / "audio_uploader.cc").read_text(encoding="utf-8")

        self.assertIn("multipart/form-data", uploader)
        self.assertIn(r'name=\"audio\"', uploader)
        self.assertIn(r'name=\"deviceId\"', uploader)
        self.assertIn("esp_http_client_write", uploader)
        self.assertIn("audio/wav", uploader)


if __name__ == "__main__":
    unittest.main()
