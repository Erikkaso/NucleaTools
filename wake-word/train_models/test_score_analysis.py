from __future__ import annotations

import unittest

import numpy as np

from score_analysis import summarize_scores, top_score_windows


class ScoreAnalysisTest(unittest.TestCase):
    def test_summarize_scores_reports_distribution_and_threshold_count(self):
        scores = np.array([0.1, 0.2, 0.3, 0.9], dtype=np.float32)

        summary = summarize_scores(scores, threshold=0.25)

        self.assertEqual(summary["windows"], 4)
        self.assertAlmostEqual(summary["mean"], 0.375)
        self.assertAlmostEqual(summary["median"], 0.25)
        self.assertAlmostEqual(summary["max"], 0.9)
        self.assertEqual(summary["above_threshold"], 2)

    def test_top_score_windows_returns_highest_scores_with_timestamps(self):
        scores = np.array([0.1, 0.8, 0.3, 0.9], dtype=np.float32)

        rows = top_score_windows(scores, hop_seconds=0.25, limit=2)

        self.assertEqual(rows[0]["index"], 3)
        self.assertAlmostEqual(rows[0]["time_seconds"], 0.75)
        self.assertAlmostEqual(rows[0]["score"], 0.9)
        self.assertEqual(rows[1]["index"], 1)


if __name__ == "__main__":
    unittest.main()
