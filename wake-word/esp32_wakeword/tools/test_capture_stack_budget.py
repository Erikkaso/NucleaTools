import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CaptureStackBudgetTests(unittest.TestCase):
    def test_compiled_capture_frame_leaves_room_for_i2s_and_logging(self):
        objdump = os.environ.get("XTENSA_OBJDUMP") or shutil.which(
            "xtensa-esp32s3-elf-objdump"
        )
        object_file = (
            ROOT / "build/esp-idf/main/CMakeFiles/__idf_main.dir/audio_capture.cc.obj"
        )
        if not objdump or not object_file.exists():
            self.skipTest("Build firmware and set XTENSA_OBJDUMP first")
        output = subprocess.check_output(
            [objdump, "-d", "-C", str(object_file)], text=True
        )
        match = re.search(
            r"<AudioCapture::RunCapture\(\)>:\s*\n[^\n]*\bentry\s+a1,\s*(0x[0-9a-f]+|[0-9]+)",
            output,
        )
        self.assertIsNotNone(match, "Capture stack frame not found in object file")
        frame_bytes = int(match.group(1), 0)
        self.assertLessEqual(
            frame_bytes, 512,
            f"RunCapture reserves {frame_bytes} bytes before calling I2S/logging",
        )


if __name__ == "__main__":
    unittest.main()
