import csv
from pathlib import Path
import tempfile
import unittest

from multispeaker_data import speaker_examples
from reviewed_split import enrich_capture_times, eric_split_plan


class ReviewedSplitTests(unittest.TestCase):
    def test_clean_only_does_not_restore_removed_parents_or_old_augmentations(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'wakeword_raisa'
            names = ['positive/original/good.wav', 'positive/clean/good_clean.wav',
                     'positive/clean/bad_clean.wav', 'positive/augmented/bad_aug.wav',
                     'negative_silence/quiet.wav']
            for name in names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            with (root / 'manifest.csv').open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=['file', 'parent_file', 'source_file'])
                writer.writeheader()
                for name in names:
                    writer.writerow({'file': name, 'parent_file': 'positive/original/' +
                                     ('bad.wav' if 'bad' in name else 'good.wav') if '/clean/' in name else '',
                                     'source_file': 'raisa.ogg'})
            examples = speaker_examples(root, include_reviewed_negatives=True, clean_only=True)
            self.assertEqual({r['path'].name for r in examples}, {'good_clean.wav', 'quiet.wav'})

    def make_examples(self):
        return [{'path': Path(f'{session}_{i}.wav'), 'speaker': 'eric', 'label': 1,
                 'group': f'eric:{session}', 'metadata': {'clip_start_s': i * 2,
                                                        'clip_end_s': i * 2 + 1}}
                for session in ('session1', 'session2', 'phone') for i in range(20)]

    def test_random_split_is_reproducible_stratified_and_not_order_dependent(self):
        examples = self.make_examples()
        plan = eric_split_plan(examples, 42)
        self.assertEqual(plan, eric_split_plan(list(reversed(examples)), 42))
        self.assertNotEqual(plan, eric_split_plan(examples, 43))
        for source in ('session1', 'session2', 'phone'):
            values = [plan[str(e['path'])]['split'] for e in examples if e['group'] == f'eric:{source}']
            self.assertEqual([values.count(s) for s in ('train', 'validation', 'test')], [16, 2, 2])

    def test_overlapping_windows_share_group_and_split(self):
        examples = self.make_examples()
        duplicate = {**examples[0], 'path': Path('overlapping.wav'),
                     'metadata': {'clip_start_s': .5, 'clip_end_s': 1.5}}
        plan = eric_split_plan(examples + [duplicate], 42)
        self.assertEqual(plan['session1_0.wav'], plan['overlapping.wav'])

    def test_eric_without_time_provenance_is_rejected(self):
        example = self.make_examples()[0]
        example['metadata'] = {}
        with self.assertRaises(ValueError):
            eric_split_plan([example], 42)

    def test_capture_intervals_come_from_the_session_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            session = Path(temp) / 'sessao_002'
            session.mkdir()
            with (session / 'manifest.csv').open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=['file', 'clip_start_s', 'clip_end_s'])
                writer.writeheader()
                writer.writerow({'file': 'review/candidate_0001.wav', 'clip_start_s': 2.5, 'clip_end_s': 3.5})
            example = {**self.make_examples()[0], 'metadata': {
                'source_file': str(session / 'review/candidate_0001.wav')}}
            enrich_capture_times([example])
            self.assertEqual(float(example['metadata']['clip_start_s']), 2.5)
            self.assertEqual(float(example['metadata']['clip_end_s']), 3.5)

    def test_legacy_window_accounts_for_padding_and_original_speed(self):
        example = {**self.make_examples()[0], 'metadata': {
            'source_file': 'voz.ogg', 'source_start_s': '2',
            'word_start_ms': '200', 'base_speedup': '1.5'}}
        enrich_capture_times([example])
        self.assertAlmostEqual(example['metadata']['clip_start_s'], 1.7)
        self.assertAlmostEqual(example['metadata']['clip_end_s'], 3.2)


if __name__ == '__main__':
    unittest.main()
