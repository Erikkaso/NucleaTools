import unittest
import csv
from pathlib import Path
import tempfile

import numpy as np

from multispeaker_data import (
    recording_group, positive_quality, safe_shift, partition_for, select_threshold,
    speaker_examples,
    quiet_validation_mask,
)


class TrainingDataTests(unittest.TestCase):
    def test_mined_quiet_is_included_in_every_calibration_path(self):
        mask = quiet_validation_mask([{'speaker': s} for s in
                                      ['speech', 'mined_scene', 'mined_quiet', 'quiet_synthetic', 'inmp_ambiente']])
        self.assertEqual(mask.tolist(), [False, False, True, True, True])

    def test_nested_dataset_and_moved_reviewed_negatives(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'wakeword_raisa'
            names = ['positive/original/a.wav', 'positive/clean/a_clean.wav',
                     'positive/augmented/a_gain.wav', 'negative_silence/silence.wav']
            for name in names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            with (root / 'manifest.csv').open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=['file', 'label', 'source_file', 'source_id', 'original_phrase'])
                writer.writeheader()
                for name in names:
                    writer.writerow({'file': name.replace('negative_silence/', 'negative/silence/'),
                                     'label': 'negative' if 'silence' in name else 'positive',
                                     'source_file': 'raisa.ogg', 'source_id': 'a',
                                     'original_phrase': 'Oi Nuclea' if 'silence' not in name else ''})
                writer.writerow({'file': 'positive/clean/deleted.wav', 'label': 'positive', 'source_file': 'raisa.ogg'})
            rows = speaker_examples(root)
            self.assertEqual(len(rows), 3)
            self.assertTrue(all(r['label'] == 1 for r in rows))
            rows = speaker_examples(root, include_reviewed_negatives=True)
            self.assertEqual(len(rows), 4)
            self.assertEqual(sum(r['label'] == 0 for r in rows), 1)
            self.assertEqual({r['group'] for r in rows}, {'raisa:raisa.ogg'})
            self.assertEqual({r['variant'] for r in rows if r['label']}, {'original', 'clean', 'augmented'})
            self.assertTrue(all(r['metadata']['original_phrase'] == 'Oi Nuclea' for r in rows if r['label']))

    def test_thayza_is_test_only_even_in_final_fit(self):
        self.assertEqual(partition_for('thayza', 'thayza:thayza.wav', final_fit=True), 'test')
        self.assertEqual(partition_for('thayza', 'thayza:thayza.wav'), 'test')
        self.assertEqual(partition_for('raisa', 'raisa:raisa.ogg', final_fit=True), 'train')
        self.assertEqual(partition_for('thayza(deprecated)', 'thayza(deprecated):thayza.wav', final_fit=True), 'test')

    def test_deprecated_folder_keeps_test_only_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'wakeword_thayza(deprecated)'
            (root / 'clean').mkdir(parents=True)
            (root / 'clean/a.wav').touch()
            rows = speaker_examples(root)
            self.assertEqual(rows[0]['speaker'], 'thayza')
            self.assertTrue(rows[0]['group'].startswith('thayza:'))
            self.assertEqual(speaker_examples(root, excluded_speakers={'thayza'}), [])
            self.assertEqual(speaker_examples(root, excluded_speakers={'wakeword_thayza(deprecated)'}), [])

    def test_inmp_candidates_share_recording_not_clip_group(self):
        a = recording_group('eric', {'source_file': 'prepared/sessao_002/review/candidate_0001.wav'}, 'x')
        b = recording_group('eric', {'source_file': 'prepared/sessao_002/review/candidate_0042.wav'}, 'y')
        self.assertEqual(a, b)
        self.assertNotEqual(a, recording_group('eric', {'source_file': 'voz.ogg'}, 'z'))

    def test_silence_and_dc_cannot_be_positive(self):
        self.assertFalse(positive_quality(np.zeros(16000))[0])
        self.assertFalse(positive_quality(np.ones(16000) * 0.1)[0])
        tone = np.sin(np.arange(8000) * 0.1) * 0.1
        self.assertTrue(positive_quality(np.pad(tone, (4000, 4000)))[0])

    def test_shift_never_cuts_word_at_edge(self):
        audio = np.zeros(16000, dtype=np.float32)
        audio[-1200:] = 0.3
        self.assertTrue(np.array_equal(safe_shift(audio, 1600), audio))
        self.assertAlmostEqual(float(np.sum(safe_shift(audio, -1600)**2)), float(np.sum(audio**2)), places=3)

    def test_holdout_speakers_and_microphone_session_are_separate(self):
        self.assertEqual(partition_for('lara', 'lara:lara.ogg'), 'validation')
        self.assertEqual(partition_for('gabriel', 'gabriel:gabriel.ogg'), 'test')
        self.assertEqual(partition_for('eric', 'eric:inmp441_sessao_002'), 'test')
        self.assertEqual(partition_for('eric', 'eric:inmp441_sessao_001'), 'train')

    def test_threshold_is_above_every_silence_score(self):
        result = select_threshold(np.array([.7, .9, .99]), np.array([0., .1, .8]))
        self.assertGreater(result['threshold'], .8)
        self.assertEqual(result['fp'], 0)

    def test_saturated_negative_blocks_calibration(self):
        result = select_threshold(np.array([.99]), np.array([255 / 256]))
        self.assertFalse(result['deployable'])
        self.assertGreater(result['threshold'], .99)

    def test_large_calibration_set_allows_bounded_speech_outliers(self):
        negatives = np.array([.1] * 280 + [.988, .996])
        result = select_threshold(np.array([.95, .99]), negatives)
        self.assertLess(result['threshold'], .99)
        self.assertEqual(result['fp'], 2)
        self.assertLessEqual(result['false_positive_rate'], .01)

    def test_quiet_constraint_is_stricter_than_speech_budget(self):
        negatives = np.array([.1] * 280 + [.8, .95])
        result = select_threshold(np.array([.99]), negatives, np.array([.8]))
        self.assertGreater(result['threshold'], .8)


if __name__ == '__main__':
    unittest.main()
