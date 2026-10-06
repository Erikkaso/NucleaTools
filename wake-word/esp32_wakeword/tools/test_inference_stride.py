from pathlib import Path
import re
import unittest


class InferenceStrideTest(unittest.TestCase):
    def test_uses_160ms_stride_for_two_of_three_confirmation(self):
        source = (
            Path(__file__).resolve().parents[1] / "main" / "app_main.cc"
        ).read_text(encoding="utf-8")

        match = re.search(
            r"kInferenceStrideSamples\s*=\s*(\d+)\s*\*\s*320",
            source,
        )

        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "8")


if __name__ == "__main__":
    unittest.main()
