import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).parent))
import train_noise_robust_v2 as training


class ExperimentConfigTests(unittest.TestCase):
    def test_v2e_preserves_temporal_augmentation_in_a_new_output_directory(self) -> None:
        config = training.get_experiment_config("v2e")

        self.assertEqual(config.output_dir, Path("output/output_noise_robust_v2e_inmp441"))
        self.assertEqual(config.temporal_offsets_samples, (-3200, 0, 3200))
        self.assertIn(Path("dataset/background_noise"), config.positive_background_dirs)

    def test_v2f_emphasizes_dialogue_noise_and_temporal_offsets(self) -> None:
        config = training.get_experiment_config("v2f")

        self.assertEqual(config.output_dir, Path("output/output_noise_robust_v2f_dialogue"))
        self.assertEqual(config.noisy_positive_probability, 0.55)
        self.assertEqual(config.snr_db_range, (10.0, 25.0))
        self.assertEqual(config.voice_positive_weight, 0.35)
        self.assertEqual(config.voice_negative_oversample, 3)
        self.assertEqual(config.temporal_offsets_samples, (-4800, -3200, 0, 3200, 4800))

    def test_v2g_gives_replayed_hard_negatives_extra_weight(self) -> None:
        config = training.get_experiment_config("v2g")

        self.assertEqual(config.output_dir, Path("output/output_noise_robust_v2g_replay_hardneg"))
        self.assertEqual(config.hard_negative_oversample, 8)
        self.assertEqual(config.voice_negative_oversample, 5)
        self.assertEqual(config.temporal_offsets_samples, (-4800, -3200, 0, 3200, 4800))


if __name__ == "__main__":
    unittest.main()
