import importlib
import importlib.util
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).parent))


class ReplayWakewordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertIsNotNone(importlib.util.find_spec("replay_wakeword"))
        self.module = importlib.import_module("replay_wakeword")

    def test_windows_use_the_requested_stride_without_gaps(self) -> None:
        starts = self.module.window_starts(
            total_samples=32_000,
            window_samples=16_000,
            stride_samples=2_560,
        )

        self.assertEqual(starts, [0, 2_560, 5_120, 7_680, 10_240, 12_800, 15_360])

    def test_audio_result_key_keeps_same_named_sources_separate(self) -> None:
        first = self.module.audio_result_key(Path("positive/sessao_001.wav"))
        second = self.module.audio_result_key(Path("silencio/sessao_001.wav"))

        self.assertNotEqual(first, second)

    def test_high_confidence_score_bypasses_two_of_three_confirmation(self) -> None:
        events = self.module.detection_events(
            scores=[0.20, 0.97],
            timestamps_ms=[0, 160],
            threshold=0.84,
            high_threshold=0.96,
            cooldown_ms=2_000,
        )

        self.assertEqual(events, [{"time_ms": 160, "score": 0.97, "reason": "high_confidence"}])

    def test_normal_confirmation_still_requires_two_of_three(self) -> None:
        events = self.module.detection_events(
            scores=[0.85, 0.30, 0.86],
            timestamps_ms=[0, 160, 320],
            threshold=0.84,
            high_threshold=0.96,
            cooldown_ms=2_000,
        )

        self.assertEqual(events, [{"time_ms": 320, "score": 0.86, "reason": "two_of_three"}])


if __name__ == "__main__":
    unittest.main()
