import unittest

from hard_negative_mining import temporal_ranges, window_starts, select_hard_windows, validate_mined_manifest


class HardNegativeTests(unittest.TestCase):
    def test_ranges_have_guards_and_windows_stay_inside(self):
        ranges = temporal_ranges(16000 * 100)
        self.assertGreaterEqual(ranges['validation'][0] - ranges['train'][1], 32000)
        self.assertGreaterEqual(ranges['test'][0] - ranges['validation'][1], 32000)
        for start, stop in ranges.values():
            starts = window_starts(start, stop, 2560)
            self.assertTrue(all(start <= s and s + 16000 <= stop for s in starts))

    def test_mining_prefers_high_scores_without_dense_duplicates(self):
        starts = [0, 2560, 16000, 32000]
        chosen = select_hard_windows(starts, [.8, .95, .7, .1], threshold=.5, limit=10)
        self.assertEqual(chosen, [1])
        chosen = select_hard_windows(starts, [.8, .95, .7, .6], threshold=.5, limit=2)
        self.assertEqual(chosen, [1, 3])

    def test_short_sources_are_rejected_before_export(self):
        with self.assertRaises(ValueError):
            temporal_ranges(16000 * 3)

    def test_corpus_rejects_training_window_outside_its_block(self):
        source = {'id': 'noise', 'file': 'noise.wav', 'sha256': 'abc', 'samples': 1600000,
                  'ranges': temporal_ranges(1600000)}
        record = {'source': 'noise.wav', 'source_sha256': 'abc', 'split': 'train',
                  'start_sample': 0, 'end_sample': 16000, 'group': 'mined:noise:train', 'kind': 'hard'}
        data = {'sample_rate': 16000, 'sources': [source], 'records': [record]}
        validate_mined_manifest(data)
        record['start_sample'], record['end_sample'] = 960000, 976000
        with self.assertRaises(ValueError):
            validate_mined_manifest(data)


if __name__ == '__main__':
    unittest.main()
