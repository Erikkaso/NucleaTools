import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from detection_gate_reference import DetectionGate


class DetectionGateTests(unittest.TestCase):
    def test_uses_the_calibrated_thresholds(self) -> None:
        self.assertEqual(DetectionGate.threshold, 0.85)
        self.assertEqual(DetectionGate.high_threshold, 0.98)

    def test_requires_two_scores_in_last_three(self) -> None:
        gate = DetectionGate()
        self.assertFalse(gate.accept(0.86, 0))
        self.assertFalse(gate.accept(0.20, 320))
        self.assertTrue(gate.accept(0.86, 640))

    def test_accepts_one_high_confidence_score(self) -> None:
        gate = DetectionGate()
        self.assertTrue(gate.accept(0.98, 0))

    def test_suppresses_events_during_cooldown(self) -> None:
        gate = DetectionGate()
        gate.accept(0.86, 0)
        self.assertTrue(gate.accept(0.86, 320))
        self.assertFalse(gate.accept(0.86, 640))
        self.assertTrue(gate.accept(0.86, 2_500))


if __name__ == "__main__":
    unittest.main()
