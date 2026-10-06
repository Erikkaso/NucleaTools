import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class RuntimeModelContractTests(unittest.TestCase):
    def test_mfcc_quantization_comes_from_the_loaded_model(self):
        mfcc_header = (ROOT / "main" / "mfcc.h").read_text(encoding="utf-8")
        detector_header = (ROOT / "main" / "wakeword_detector.h").read_text(
            encoding="utf-8"
        )
        app_source = (ROOT / "main" / "app_main.cc").read_text(encoding="utf-8")

        self.assertIn("float quant_scale", mfcc_header)
        self.assertIn("int quant_zero_point", mfcc_header)
        self.assertIn("InputScale()", detector_header)
        self.assertIn("InputZeroPoint()", detector_header)
        self.assertIn("detector.InputScale()", app_source)
        self.assertIn("detector.InputZeroPoint()", app_source)

    def test_runtime_telemetry_exposes_quantized_input_and_output(self):
        detector_header = (ROOT / "main" / "wakeword_detector.h").read_text(
            encoding="utf-8"
        )
        app_source = (ROOT / "main" / "app_main.cc").read_text(encoding="utf-8")

        self.assertIn("LastInputMin()", detector_header)
        self.assertIn("LastInputMax()", detector_header)
        self.assertIn("LastBackgroundOutput()", detector_header)
        self.assertIn("LastWakewordOutput()", detector_header)
        self.assertIn("q_in=[%d,%d]", app_source)
        self.assertIn("q_out=[%d,%d]", app_source)


if __name__ == "__main__":
    unittest.main()
