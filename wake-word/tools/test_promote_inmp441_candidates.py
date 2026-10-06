import csv
import importlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent))


class PromotionTest(unittest.TestCase):
    def test_promotes_candidates_and_registers_one_source_group(self):
        self.assertIsNotNone(
            importlib.util.find_spec("promote_inmp441_candidates"),
        )
        promotion = importlib.import_module("promote_inmp441_candidates")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            review_dir = root / "review"
            review_dir.mkdir()
            (review_dir / "candidate_0001.wav").write_bytes(b"wav")
            (review_dir / "silence_0001.wav").write_bytes(b"wav")

            speaker_dir = root / "wakeword_eric"
            speaker_dir.mkdir()
            metadata = speaker_dir / "metadata.csv"
            metadata.write_text(
                "file,group_id,variant,source_file\n",
                encoding="utf-8",
            )

            promoted = promotion.promote_candidates(
                review_dir,
                speaker_dir,
                "inmp441_sessao_001",
            )

            self.assertEqual(len(promoted), 1)
            self.assertTrue(promoted[0].exists())
            with metadata.open(encoding="utf-8", newline="") as csv_file:
                rows = list(csv.DictReader(csv_file))
            self.assertEqual(rows[0]["group_id"], "inmp441_sessao_001")
            self.assertEqual(rows[0]["variant"], "clean")


if __name__ == "__main__":
    unittest.main()
