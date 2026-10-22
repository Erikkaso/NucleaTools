"""Recording-aware splits and conservative waveform checks for v3 training."""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path
import re

import numpy as np


SAMPLE_RATE = 16000
VALIDATION_SPEAKERS = {'lara', 'ryam'}
TEST_SPEAKERS = {'gabriel', 'thayza'}
TEST_ONLY_SPEAKERS = {'thayza'}


def normalize_speaker(name: str) -> str:
    name = name.removeprefix('wakeword_').strip().lower()
    return re.sub(r'\s*\(deprecated\)$', '', name).strip()


def recording_group(speaker: str, row: dict, fallback: str) -> str:
    source = str(row.get('source_file') or '').replace('\\', '/')
    session = re.search(r'(sessao_\d+)', source + '/' + fallback)
    if session:
        source = 'inmp441_' + session.group(1)
    else:
        source = source.rsplit('/', 1)[-1] or fallback
    return speaker + ':' + source


def partition_for(speaker: str, group: str, final_fit: bool = False) -> str:
    speaker = normalize_speaker(speaker)
    if speaker in TEST_ONLY_SPEAKERS:
        return 'test'
    if final_fit:
        return 'train'
    if speaker in VALIDATION_SPEAKERS:
        return 'validation'
    if speaker in TEST_SPEAKERS or group == 'eric:inmp441_sessao_002':
        return 'test'
    return 'train'


def stable_partition(group: str) -> str:
    value = int(hashlib.sha256(group.encode()).hexdigest()[:8], 16) % 10
    return 'validation' if value == 0 else 'test' if value == 1 else 'train'


def positive_quality(audio: np.ndarray) -> tuple[bool, dict]:
    audio = np.asarray(audio, dtype=np.float64)
    ac = audio - np.mean(audio)
    frames = ac[:len(ac) // 320 * 320].reshape(-1, 320)
    frame_rms = np.sqrt(np.mean(frames**2, axis=1))
    rms = float(np.sqrt(np.mean(ac**2)))
    dbfs = float(20 * np.log10(max(rms, 1e-10)))
    active = int(np.sum(frame_rms > 10**(-50 / 20)))
    stats = {'ac_dbfs': round(dbfs, 2), 'active_frames': active,
             'clip_fraction': float(np.mean(np.abs(audio) >= .999))}
    return dbfs >= -60 and active >= 6, stats


def safe_shift(audio: np.ndarray, shift: int) -> np.ndarray:
    audio = np.asarray(audio, dtype=np.float32)
    if not shift:
        return audio.copy()
    amount = min(abs(shift), len(audio))
    lost = audio[-amount:] if shift > 0 else audio[:amount]
    if np.sum(lost.astype(np.float64)**2) > np.sum(audio.astype(np.float64)**2) * .0001:
        return audio.copy()
    result = np.zeros_like(audio)
    if shift > 0:
        result[amount:] = audio[:-amount]
    else:
        result[:-amount] = audio[amount:]
    return result


def quiet_validation_mask(rows: list[dict]) -> np.ndarray:
    return np.array([
        row['speaker'] in ('quiet_synthetic', 'inmp_ambiente', 'mined_quiet')
        for row in rows
    ], dtype=bool)


def select_threshold(positives: np.ndarray, negatives: np.ndarray,
                     quiet_negatives: np.ndarray | None = None, target_fpr: float = .01) -> dict:
    # Speech can contain hard outliers; do not disable the detector to fit one.
    # Quiet/ambient calibration windows retain the stricter zero-error constraint.
    if not len(negatives):
        raise ValueError('Negative validation samples are required for calibration.')
    allowed = int(len(negatives) * target_fpr)
    boundary = float(np.sort(negatives)[::-1][allowed])
    quiet_floor = float(np.max(quiet_negatives)) if quiet_negatives is not None and len(quiet_negatives) else 0.
    threshold = max(.5, boundary + 1 / 256, quiet_floor + 1 / 256)
    tp = int(np.sum(positives >= threshold))
    fp = int(np.sum(negatives >= threshold))
    return {'threshold': threshold, 'tp': tp, 'fn': len(positives) - tp,
            'fp': fp, 'tn': len(negatives) - fp,
            'positive_count': len(positives),
            'recall': tp / len(positives) if len(positives) else None,
            'false_positive_rate': fp / max(1, len(negatives)),
            'target_false_positive_rate': target_fpr,
            'quiet_max_score': quiet_floor,
            'deployable': threshold <= .99}


def metadata_by_name(path: Path, field: str = 'file') -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return {str(row.get(field, '')).replace('\\', '/').rsplit('/', 1)[-1]: row
                for row in csv.DictReader(stream)}


def speaker_examples(directory: Path, include_reviewed_negatives: bool = False,
                     excluded_speakers: tuple[str, ...] | set[str] = (),
                     clean_only: bool = False) -> list[dict]:
    """Discover existing WAVs only; manifests can retain manually deleted clips."""
    speaker = normalize_speaker(directory.name)
    if speaker in {normalize_speaker(name) for name in excluded_speakers}:
        return []
    metadata = metadata_by_name(directory / 'manifest.csv')
    metadata.update(metadata_by_name(directory / 'metadata.csv'))
    positive = directory / 'positive' if (directory / 'positive').is_dir() else directory
    roles = ('clean',) if clean_only else ('original', 'clean', 'augmented')
    locations = [(positive / role, 1, role) for role in roles]
    if include_reviewed_negatives:
        locations += [(directory / 'negative_silence', 0, 'reviewed_negative'),
                      (directory / 'negative', 0, 'reviewed_negative')]
    result = []
    for folder, label, variant in locations:
        for path in sorted(folder.rglob('*.wav')):
            row = metadata.get(path.name, {})
            if clean_only and label and row.get('parent_file'):
                parent = (directory / row['parent_file'].replace('\\', '/')).resolve()
                if not parent.is_relative_to(directory.resolve()):
                    raise ValueError('Positive parent escapes speaker directory.')
                if not parent.is_file():
                    continue
            declared = str(row.get('label') or '').lower()
            if label == 0 and declared and declared not in ('negative', '0', 'negativo'):
                raise ValueError(f'Conflicting negative label in manifest: {path}')
            result.append({'path': path, 'label': label, 'variant': variant,
                           'speaker': speaker, 'metadata': row,
                           'group': recording_group(speaker, row, path.name)})
    return result
