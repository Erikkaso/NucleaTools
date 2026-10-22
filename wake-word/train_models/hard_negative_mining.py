"""Time-separated negative mining; no TensorFlow dependency for split tests."""
from __future__ import annotations

import numpy as np


def temporal_ranges(samples: int, guard: int = 32000) -> dict[str, tuple[int, int]]:
    first, second = int(samples * .6), int(samples * .8)
    ranges = {'train': (0, first), 'validation': (first + guard, second),
              'test': (second + guard, samples)}
    if any(stop - start < 16000 for start, stop in ranges.values()):
        raise ValueError('Source too short for guarded train/validation/test blocks.')
    return ranges


def window_starts(start: int, stop: int, stride: int, window: int = 16000) -> list[int]:
    if start < 0 or stop < start or stride <= 0 or window <= 0:
        raise ValueError('Invalid window boundaries or stride.')
    return list(range(start, stop - window + 1, stride))


def select_hard_windows(starts: list[int], scores, threshold: float = .5,
                        limit: int = 240, minimum_gap: int = 16000) -> list[int]:
    if len(starts) != len(scores) or minimum_gap < 16000 or limit < 0:
        raise ValueError('Invalid mining selection arguments.')
    chosen = []
    for i in np.argsort(-np.asarray(scores, dtype=np.float64), kind='stable'):
        if not np.isfinite(scores[i]) or scores[i] < threshold or len(chosen) >= limit:
            continue
        if all(abs(starts[i] - starts[j]) >= minimum_gap for j in chosen):
            chosen.append(int(i))
    return chosen


def validate_mined_manifest(data: dict) -> None:
    if data.get('sample_rate') != 16000 or not data.get('sources'):
        raise ValueError('Invalid mined corpus format.')
    sources = {s['file']: s for s in data['sources']}
    if len(sources) != len(data['sources']):
        raise ValueError('Duplicate mining source.')
    for source in sources.values():
        expected = temporal_ranges(source['samples'])
        if {k: tuple(v) for k, v in source['ranges'].items()} != expected:
            raise ValueError('Mining source ranges do not match the guarded split.')
    for record in data['records']:
        source = sources[record['source']]
        split = record['split']
        if split not in ('train', 'validation', 'test'):
            raise ValueError('Invalid mined split.')
        start, stop = source['ranges'][split]
        if not (start <= record['start_sample'] and record['end_sample'] <= stop
                and record['end_sample'] - record['start_sample'] == 16000):
            raise ValueError('Mining window crosses its assigned source range.')
        if record['source_sha256'] != source['sha256'] or record['group'] != f'mined:{source["id"]}:{split}':
            raise ValueError('Mined source provenance mismatch.')
        if split != 'train' and (record['kind'] == 'hard' or record.get('teacher_score') is not None):
            raise ValueError('Held-out examples cannot be selected by teacher scores.')
