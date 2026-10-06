import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from tflite_to_cc import render_model_source


class TfliteToCppTests(unittest.TestCase):
    def test_renders_aligned_model_data_and_size_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "model.tflite"
            model_path.write_bytes(bytes([0x01, 0xAB, 0x00]))

            header, source = render_model_source(model_path, "kNucleaModelData")

        self.assertIn("extern const unsigned char kNucleaModelData[];", header)
        self.assertIn("extern const size_t kNucleaModelDataSize;", header)
        self.assertIn("alignas(16) const unsigned char kNucleaModelData[]", source)
        self.assertIn("0x01, 0xab, 0x00", source)
        self.assertIn("kNucleaModelDataSize = sizeof(kNucleaModelData);", source)

    def test_rejects_empty_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "empty.tflite"
            model_path.write_bytes(b"")

            with self.assertRaisesRegex(ValueError, "vazio"):
                render_model_source(model_path, "kNucleaModelData")


if __name__ == "__main__":
    unittest.main()
