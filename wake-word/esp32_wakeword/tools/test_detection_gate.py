import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from detection_gate_reference import DetectionGate


class DetectionGateTests(unittest.TestCase):
    def test_reset_confirmation_drops_old_scores_but_preserves_cooldown(self) -> None:
        gate = DetectionGate()
        self.assertTrue(hasattr(gate, "reset_confirmation"))
        self.assertFalse(gate.accept(0.95, 0))
        self.assertTrue(gate.accept(0.95, 240))
        gate.reset_confirmation()
        self.assertFalse(gate.accept(0.98, 500))
        gate.reset_confirmation()
        self.assertFalse(gate.accept(0.10, 3000))
        self.assertFalse(gate.accept(0.95, 3240))
        self.assertTrue(gate.accept(0.95, 3480))

    def test_matches_the_firmware_threshold_and_policy(self) -> None:
        self.assertEqual(DetectionGate.threshold, 0.93359375)
        self.assertEqual(DetectionGate.support_threshold, 0.5)
        source = (Path(__file__).parents[1] / "main/detection_gate.cc").read_text()
        self.assertIn("normal_confirmation", source)
        self.assertIn("support >= 2", source)

    def test_requires_two_scores_in_last_three(self) -> None:
        gate = DetectionGate()
        self.assertFalse(gate.accept(0.95, 0))
        self.assertFalse(gate.accept(0.20, 240))
        self.assertTrue(gate.accept(0.95, 480))

    def test_rejects_isolated_high_score_and_accepts_confirmed_high_scores(self) -> None:
        gate = DetectionGate()
        self.assertFalse(gate.accept(0.996, 0))
        self.assertFalse(gate.accept(0.10, 240))
        self.assertFalse(gate.accept(0.10, 480))
        self.assertFalse(gate.accept(0.996, 720))
        self.assertTrue(gate.accept(0.996, 960))

    def test_current_window_must_be_positive_after_cooldown(self) -> None:
        gate = DetectionGate()
        self.assertFalse(gate.accept(0.95, 0))
        self.assertTrue(gate.accept(0.95, 240))
        self.assertFalse(gate.accept(0.95, 480))
        self.assertFalse(gate.accept(0.10, 2240))

    def test_high_peak_needs_a_second_supporting_window(self) -> None:
        gate = DetectionGate()
        self.assertFalse(gate.accept(0.996, 0))
        self.assertTrue(gate.accept(0.60, 240))
        gate = DetectionGate()
        self.assertFalse(gate.accept(0.60, 0))
        self.assertTrue(gate.accept(0.996, 240))

    def test_support_without_a_high_peak_cannot_activate(self) -> None:
        gate = DetectionGate()
        self.assertFalse(gate.accept(0.60, 0))
        self.assertFalse(gate.accept(0.60, 240))
        self.assertFalse(gate.accept(0.95, 480))

    def test_suppresses_events_during_cooldown(self) -> None:
        gate = DetectionGate()
        gate.accept(0.95, 0)
        self.assertTrue(gate.accept(0.95, 240))
        self.assertFalse(gate.accept(0.95, 480))
        self.assertTrue(gate.accept(0.95, 2_500))


if __name__ == "__main__":
    unittest.main()
