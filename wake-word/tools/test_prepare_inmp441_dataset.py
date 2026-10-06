import importlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent))

class VoiceRegionTest(unittest.TestCase):
    def test_detects_a_voice_region_between_silent_samples(self):
        self.assertIsNotNone(
            importlib.util.find_spec("prepare_inmp441_dataset"),
        )
        preparation = importlib.import_module("prepare_inmp441_dataset")

        sample_rate = 16_000
        samples = [0] * (sample_rate // 2)
        samples.extend([2_000] * (sample_rate // 2))
        samples.extend([0] * (sample_rate // 2))

        self.assertTrue(hasattr(preparation, "find_voice_regions"))
        regions = preparation.find_voice_regions(samples, sample_rate, -35.0)

        self.assertEqual(len(regions), 1)
        self.assertLess(regions[0][0], sample_rate // 2)
        self.assertGreater(regions[0][1], sample_rate)

    def test_selects_only_reviewed_candidate_wavs_for_promotion(self):
        preparation = importlib.import_module("prepare_inmp441_dataset")

        with tempfile.TemporaryDirectory() as temporary:
            review_dir = Path(temporary)
            candidate = review_dir / "candidate_0001.wav"
            candidate.touch()
            (review_dir / "silence_0002.wav").touch()
            (review_dir / "notes.txt").touch()

            self.assertTrue(hasattr(preparation, "reviewed_candidate_files"))
            self.assertEqual(
                preparation.reviewed_candidate_files(review_dir),
                [candidate],
            )


if __name__ == "__main__":
    unittest.main()
