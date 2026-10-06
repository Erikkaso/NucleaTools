from pathlib import Path
import unittest


class Inmp441SerialCaptureTest(unittest.TestCase):
    def test_uses_the_validated_esp_idf_i2s_configuration(self):
        sketch = (
            Path(__file__).parent
            / "inmp441_serial_capture"
            / "inmp441_serial_capture.ino"
        ).read_text(encoding="utf-8")

        self.assertIn('#include "driver/i2s_std.h"', sketch)
        self.assertIn("I2S_STD_SLOT_LEFT", sketch)
        self.assertIn("raw[index] >> I2S_TO_PCM_SHIFT", sketch)


if __name__ == "__main__":
    unittest.main()
