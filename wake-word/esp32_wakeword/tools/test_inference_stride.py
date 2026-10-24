from pathlib import Path
import re
import unittest


class InferenceStrideTest(unittest.TestCase):
    def test_stride_has_room_for_measured_220ms_inference(self):
        source = (
            Path(__file__).resolve().parents[1] / "main" / "app_main.cc"
        ).read_text(encoding="utf-8")

        match = re.search(
            r"kInferenceStrideSamples\s*=\s*(\d+)\s*\*\s*320",
            source,
        )

        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "12")
        stride_ms = int(match.group(1)) * 320 / 16000 * 1000
        self.assertGreaterEqual(stride_ms, 220)
        self.assertLessEqual(stride_ms, 320)


if __name__ == "__main__":
    unittest.main()
