"""Utterance-level Eric splits, with overlapping windows kept together."""
from collections import defaultdict
import hashlib
import math
from pathlib import Path
import random

from multispeaker_data import metadata_by_name


def enrich_capture_times(examples: list[dict]) -> None:
    manifests = {}
    for example in examples:
        if example['speaker'] != 'eric' or not example['label']:
            continue
        row = example['metadata'].copy()
        source = Path(str(row.get('source_file') or '').replace('\\', '/'))
        if 'sessao_' in source.as_posix() and source.suffix.lower() == '.wav':
            manifest_path = source.parent.parent / 'manifest.csv'
            if manifest_path not in manifests:
                manifests[manifest_path] = metadata_by_name(manifest_path)
            capture = manifests[manifest_path].get(source.name, {})
            row['clip_start_s'] = capture.get('clip_start_s', '')
            row['clip_end_s'] = capture.get('clip_end_s', '')
        elif row.get('source_start_s') not in ('', None):
            speed = float(row.get('base_speedup') or 1.)
            start = float(row['source_start_s']) - float(row.get('word_start_ms') or 0.) / 1000 * speed
            row['clip_start_s'], row['clip_end_s'] = start, start + speed
        example['metadata'] = row


def eric_split_plan(examples: list[dict], seed: int) -> dict[str, dict]:
    sources = defaultdict(list)
    for example in examples:
        if example['speaker'] != 'eric' or not example['label']:
            continue
        try:
            start = float(example['metadata']['clip_start_s'])
            stop = float(example['metadata']['clip_end_s'])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f'Missing Eric window provenance: {example["path"]}') from error
        if not math.isfinite(start) or not math.isfinite(stop) or stop <= start:
            raise ValueError('Invalid Eric source interval.')
        sources[example['group']].append((start, stop, str(example['path'])))
    plan = {}
    for source, windows in sorted(sources.items()):
        components = []
        for start, stop, path in sorted(windows):
            if components and start < components[-1]['stop'] - 1e-9:
                components[-1]['paths'].append(path)
                components[-1]['stop'] = max(components[-1]['stop'], stop)
            else:
                components.append({'paths': [path], 'stop': stop})
        if len(components) < 3:
            raise ValueError(f'Need at least 3 non-overlapping Eric groups: {source}')
        for component in components:
            identity = '|'.join(sorted(Path(path).name for path in component['paths']))
            component['group'] = source + ':utterance:' + hashlib.sha256(identity.encode()).hexdigest()[:16]
        components.sort(key=lambda c: c['group'])
        source_seed = int(hashlib.sha256(f'{seed}:{source}'.encode()).hexdigest()[:16], 16)
        random.Random(source_seed).shuffle(components)
        heldout = max(1, len(components) // 10)
        for index, component in enumerate(components):
            split = 'test' if index < heldout else 'validation' if index < 2 * heldout else 'train'
            for path in component['paths']:
                plan[path] = {'split': split, 'group': component['group']}
    return plan
