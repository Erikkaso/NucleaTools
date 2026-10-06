from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from noise_robustness_eval import (
    load_threshold,
    load_validation_files,
    summarize_detection_scores,
)


class NoiseRobustnessEvalTest(unittest.TestCase):
    def test_load_validation_files_keeps_real_positives_and_backgrounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "validation_scores.csv"

            with csv_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "file",
                        "type",
                        "speaker",
                        "score_nuclea",
                        "detected",
                    ],
                )
                writer.writeheader()
                writer.writerow({
                    "file": "dataset/real/wake.wav",
                    "type": "real_positive",
                    "speaker": "eric",
                    "score_nuclea": "0.9",
                    "detected": "1",
                })
                writer.writerow({
                    "file": "dataset/background_noise/noise.wav",
                    "type": "background",
                    "speaker": "",
                    "score_nuclea": "0.1",
                    "detected": "0",
                })
                writer.writerow({
                    "file": "dataset/wakeword_synthetic/synth.wav",
                    "type": "synthetic_positive",
                    "speaker": "tts",
                    "score_nuclea": "0.8",
                    "detected": "1",
                })

            positives, backgrounds = load_validation_files(csv_path)

        self.assertEqual(
            [Path("dataset/real/wake.wav")],
            positives,
        )
        self.assertEqual(
            [Path("dataset/background_noise/noise.wav")],
            backgrounds,
        )

    def test_summarize_detection_scores_reports_recall_and_distribution(self):
        summary = summarize_detection_scores(
            scores=[0.9, 0.7, 0.2, 0.1],
            threshold=0.5,
        )

        self.assertEqual(4, summary["samples"])
        self.assertEqual(2, summary["detected"])
        self.assertAlmostEqual(0.5, summary["recall"])
        self.assertAlmostEqual(0.475, summary["mean_score"])

    def test_load_threshold_reads_final_threshold_from_results_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results_final.json"
            path.write_text(
                '{"threshold": 0.37}',
                encoding="utf-8",
            )

            threshold = load_threshold(path)

        self.assertAlmostEqual(0.37, threshold)


if __name__ == "__main__":
    unittest.main()
