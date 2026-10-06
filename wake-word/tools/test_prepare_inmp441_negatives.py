import importlib
import importlib.util
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).parent))


class PrepareInmp441NegativesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertIsNotNone(importlib.util.find_spec("prepare_inmp441_negatives"))
        self.module = importlib.import_module("prepare_inmp441_negatives")

    def test_evenly_spaced_windows_cover_the_whole_recording(self) -> None:
        starts = self.module.evenly_spaced_starts(
            total_samples=160_000,
            window_samples=16_000,
            count=4,
        )

        self.assertEqual(starts, [0, 48_000, 96_000, 144_000])

    def test_returns_all_possible_windows_when_limit_is_larger(self) -> None:
        starts = self.module.evenly_spaced_starts(
            total_samples=40_000,
            window_samples=16_000,
            count=10,
        )

        self.assertEqual(starts, [0, 24_000])

    def test_accepts_dialogue_as_a_negative_kind(self) -> None:
        self.assertIn("dialogue", self.module.NEGATIVE_KINDS)

    def test_targeted_starts_cover_an_event_with_overlapping_windows(self) -> None:
        starts = self.module.targeted_starts(
            event_samples=[28_160],
            total_samples=80_000,
            window_samples=16_000,
            hop_samples=4_000,
            context_samples=8_000,
        )

        self.assertEqual(starts, [20_160, 24_160, 28_160, 32_160, 36_160])


if __name__ == "__main__":
    unittest.main()
