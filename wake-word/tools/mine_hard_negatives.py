"""Mine train-only background false wakes, exporting guarded temporal holdouts."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'train_models'))
from train_multispeaker_v3 import feature, load_audio, predict_int8, np, sf, tf
from hard_negative_mining import temporal_ranges, window_starts, select_hard_windows, validate_mined_manifest
from multispeaker_data import normalize_speaker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--teacher', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--confirmed-negative-sources', action='store_true')
    parser.add_argument('--max-hard-per-source', type=int, default=240)
    args = parser.parse_args()
    if not args.confirmed_negative_sources:
        parser.error('Use only a corpus already labeled as not containing the wakeword.')
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise RuntimeError('Refusing to overwrite an existing mining corpus.')
    output.mkdir(parents=True, exist_ok=True)
    interpreter = tf.lite.Interpreter(model_path=str(args.teacher), num_threads=4)
    interpreter.allocate_tensors()
    report_path = args.teacher.parent / 'results.json'
    teacher_report = json.loads(report_path.read_text(encoding='utf-8'))
    if 'thayza' not in teacher_report.get('test_only_speakers', []):
        raise RuntimeError('Mining teacher must honor Thayza as test-only.')
    teacher_manifest = json.loads((args.teacher.parent / 'data_manifest.json').read_text(encoding='utf-8'))
    if any(normalize_speaker(r['speaker']) == 'thayza' or normalize_speaker(r['group'].split(':', 1)[0]) == 'thayza'
           for split in ('train', 'validation') for r in teacher_manifest[split]):
        raise RuntimeError('Teacher data violates test-only speaker policy.')
    sources, records = [], []

    def export(audio, start, source, split, kind, number, score=None):
        relative = Path(split) / f'{source["id"]}_{number:05d}.wav'
        destination = output / relative
        destination.parent.mkdir(exist_ok=True)
        sf.write(destination, audio[start:start+16000], 16000, subtype='PCM_16')
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        records.append({'file': relative.as_posix(), 'split': split, 'kind': kind,
                        'source': source['file'], 'source_sha256': source['sha256'],
                        'start_sample': start, 'end_sample': start + 16000,
                        'group': f'mined:{source["id"]}:{split}',
                        'teacher_score': score, 'wav_sha256': digest})

    for source_path in sorted((ROOT / 'dataset/background_test2').iterdir()):
        if source_path.suffix.lower() not in ('.wav', '.mp3', '.ogg'):
            continue
        audio = load_audio(source_path)
        ranges = temporal_ranges(len(audio))
        source = {'id': source_path.stem, 'file': source_path.relative_to(ROOT).as_posix(),
                  'sha256': hashlib.sha256(source_path.read_bytes()).hexdigest(),
                  'samples': len(audio), 'sample_rate': 16000, 'ranges': ranges}
        sources.append(source)
        start, stop = ranges['train']
        starts = window_starts(start, stop, 2560)
        all_scores = []
        for index in range(0, len(starts), 128):
            batch = starts[index:index+128]
            x = np.array([feature(audio[i:i+16000]) for i in batch])
            all_scores.extend(predict_int8(interpreter, x).tolist())
        selected = select_hard_windows(starts, all_scores, limit=args.max_hard_per_source)
        hard_starts = {starts[i] for i in selected}
        number = 0
        for index in selected:
            export(audio, starts[index], source, 'train', 'hard', number, float(all_scores[index]))
            number += 1
        # Unconditional coverage supplements the mined, teacher-biased negatives.
        for position in np.linspace(start, stop-16000, 32, dtype=int):
            position = int(position)
            if position in hard_starts:
                continue
            export(audio, position, source, 'train', 'coverage', number)
            number += 1
        for split in ('validation', 'test'):
            start, stop = ranges[split]
            for number, position in enumerate(np.unique(np.linspace(start, stop-16000, 64, dtype=int))):
                export(audio, int(position), source, split, 'quiet' if 'calmo' in source_path.stem else 'scene', number)
        print(f'{source_path.name}: {len(starts)} train windows, {len(selected)} hard, '
              f'{number+1} test coverage; heldouts never scored by teacher.', flush=True)
    result = {'teacher': str(args.teacher), 'teacher_sha256': hashlib.sha256(args.teacher.read_bytes()).hexdigest(),
              'label_basis': 'Existing background corpus labeled negative; no per-clip transcription or new manual review.',
              'policy': '60/20/20 chronological blocks, 2s guards; mining scores train only; heldouts uniform.',
              'limitations': 'Recordings were inspected in earlier diagnostics; time blocks are not independent sessions.',
              'sample_rate': 16000, 'sources': sources, 'records': records}
    validate_mined_manifest(result)
    (output / 'manifest.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(f'Exported {len(records)} negatives into {output}', flush=True)


if __name__ == '__main__':
    main()
