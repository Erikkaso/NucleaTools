from __future__ import annotations

import math
import random
import unittest

import numpy as np

from noise_augmentation import (
    fit_or_crop_background,
    mix_at_snr,
    should_mix_positive,
)


class NoiseAugmentationTest(unittest.TestCase):
    def test_mix_at_snr_scales_background_to_requested_snr(self):
        clean = np.full(16000, 0.25, dtype=np.float32)
        background = np.full(16000, 0.25, dtype=np.float32)

        mixed = mix_at_snr(clean, background, snr_db=20.0)

        added_noise = mixed - clean
        clean_rms = math.sqrt(float(np.mean(np.square(clean))))
        noise_rms = math.sqrt(float(np.mean(np.square(added_noise))))
        measured_snr = 20.0 * math.log10(clean_rms / noise_rms)

        self.assertAlmostEqual(measured_snr, 20.0, places=4)
        self.assertEqual(mixed.dtype, np.float32)

    def test_mix_at_snr_clips_to_float_audio_range(self):
        clean = np.full(16000, 0.95, dtype=np.float32)
        background = np.full(16000, 0.95, dtype=np.float32)

        mixed = mix_at_snr(clean, background, snr_db=0.0)

        self.assertLessEqual(float(np.max(mixed)), 1.0)
        self.assertGreaterEqual(float(np.min(mixed)), -1.0)

    def test_fit_or_crop_background_repeats_short_background_to_requested_length(self):
        background = np.array([0.1, -0.2, 0.3], dtype=np.float32)

        fitted = fit_or_crop_background(
            background,
            num_samples=8,
            rng=random.Random(123),
        )

        np.testing.assert_allclose(
            fitted,
            np.array([0.1, -0.2, 0.3, 0.1, -0.2, 0.3, 0.1, -0.2], dtype=np.float32),
        )

    def test_fit_or_crop_background_crops_long_background_deterministically(self):
        background = np.arange(10, dtype=np.float32)

        first = fit_or_crop_background(
            background,
            num_samples=4,
            rng=random.Random(42),
        )
        second = fit_or_crop_background(
            background,
            num_samples=4,
            rng=random.Random(42),
        )

        np.testing.assert_array_equal(first, second)
        self.assertEqual(len(first), 4)
        self.assertTrue(any(np.array_equal(first, background[i:i + 4]) for i in range(7)))

    def test_should_mix_positive_respects_probability_boundaries(self):
        rng = random.Random(7)

        self.assertFalse(should_mix_positive(rng, probability=0.0))
        self.assertTrue(should_mix_positive(rng, probability=1.0))

    def test_training_config_excludes_background_test2_and_uses_new_output_dir(self):
        import train_noise_robust_v1 as training

        all_background_dirs = [
            str(path).replace("\\", "/")
            for path in (
                training.BACKGROUND_DIRS
                + training.HARD_NEGATIVE_DIRS
            )
        ]

        self.assertEqual(training.OUTPUT_DIR.as_posix(), "output_noise_robust_v1")
        self.assertEqual(training.NOISY_POSITIVE_PROBABILITY, 0.50)
        self.assertEqual(training.SNR_DB_RANGE, (10.0, 30.0))
        self.assertFalse(
            any("background_test2" in path for path in all_background_dirs),
            all_background_dirs,
        )

    def test_build_positive_training_items_records_train_only_noise_metadata(self):
        import train_noise_robust_v1 as training

        positives = [
            training.AudioExample(path=f"positive_{index}.wav", source="real_train")
            for index in range(6)
        ]
        train_backgrounds = [
            training.AudioExample(path=f"train_bg_{index}.wav", source="background_train")
            for index in range(3)
        ]
        validation_backgrounds = [
            training.AudioExample(path="validation_bg.wav", source="background_validation")
        ]

        items = training.build_positive_training_items(
            positives=positives,
            train_backgrounds=train_backgrounds,
            validation_backgrounds=validation_backgrounds,
            noisy_probability=1.0,
            snr_db_range=(10.0, 30.0),
            rng=random.Random(11),
        )

        self.assertEqual(len(items), len(positives))
        self.assertTrue(all(item.background_path is not None for item in items))
        self.assertTrue(all(item.snr_db is not None for item in items))
        self.assertTrue(
            all(
                item.background_path in {example.path for example in train_backgrounds}
                for item in items
            )
        )
        self.assertFalse(
            any(item.background_path == "validation_bg.wav" for item in items)
        )

    def test_stable_seed_from_text_is_reproducible(self):
        import train_noise_robust_v1 as training

        first = training.stable_seed_from_text("positive.wav|background.wav|20.0")
        second = training.stable_seed_from_text("positive.wav|background.wav|20.0")

        self.assertEqual(first, second)
        self.assertIsInstance(first, int)
        self.assertGreaterEqual(first, 0)
        self.assertLessEqual(first, 0xFFFFFFFF)

    def test_v2_configs_are_isolated_and_do_not_use_external_holdouts(self):
        import train_noise_robust_v2 as training

        for variant in ("v2a", "v2b", "v2c"):
            config = training.get_experiment_config(variant)
            all_dirs = [
                path.as_posix()
                for path in (
                    config.positive_background_dirs
                    + training.BACKGROUND_DIRS
                    + training.HARD_NEGATIVE_DIRS
                )
            ]

            self.assertEqual(
                config.output_dir.as_posix(),
                f"output/output_noise_robust_{variant}",
            )
            self.assertEqual(config.snr_db_range, (20.0, 35.0))
            self.assertFalse(any("background_test2" in path for path in all_dirs))

    def test_v2a_excludes_voice_from_positive_augmentation(self):
        import train_noise_robust_v2 as training

        config = training.get_experiment_config("v2a")

        self.assertEqual(config.noisy_positive_probability, 0.25)
        self.assertFalse(
            any("background_voice" in path.as_posix() for path in config.positive_background_dirs)
        )

    def test_v2b_limits_voice_positive_augmentation_weight(self):
        import train_noise_robust_v2 as training

        config = training.get_experiment_config("v2b")

        self.assertEqual(config.noisy_positive_probability, 0.35)
        self.assertEqual(config.voice_positive_weight, 0.15)

    def test_v2c_reinforces_difficult_negatives_without_changing_positive_rate(self):
        import train_noise_robust_v2 as training

        config = training.get_experiment_config("v2c")

        self.assertEqual(config.noisy_positive_probability, 0.35)
        self.assertGreater(config.voice_negative_oversample, 1)
        self.assertGreater(config.hard_negative_oversample, 1)


if __name__ == "__main__":
    unittest.main()
