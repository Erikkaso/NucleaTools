"""Diagnostic stream replay and held-out noise stress test for a v3 candidate."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '2')
os.environ.setdefault('NUMBA_CACHE_DIR', str(Path(os.environ.get('TEMP', '.')) / 'nuclea-numba'))

import librosa
import numpy as np
import soundfile as sf
import tensorflow as tf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'train_models'))
from train_multispeaker_v3 import feature, predict_int8, load_audio, metrics
from replay_wakeword import detection_events
from multispeaker_data import select_threshold, quiet_validation_mask


def read_chunk(path, start, seconds):
    info = sf.info(path)
    audio, rate = sf.read(path, start=round(start*info.samplerate),
                          frames=round(seconds*info.samplerate), dtype='float32', always_2d=True)
    audio = audio.mean(axis=1)
    if rate != 16000:
        audio = librosa.resample(audio, orig_sr=rate, target_sr=16000)
    return audio


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'output/output_multispeaker_v3')
    parser.add_argument('--seconds-per-source', type=int, default=180)
    parser.add_argument('--baseline', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    report = json.loads((output / 'results.json').read_text(encoding='utf-8'))
    threshold = report['calibration']['threshold']
    high = max(.98, threshold)
    interpreter = tf.lite.Interpreter(model_path=str(output / 'nuclea_int8.tflite'), num_threads=4)
    interpreter.allocate_tensors()
    audit = json.loads((output / 'data_audit.json').read_text(encoding='utf-8'))
    mined = audit.get('mined_negative_corpus')
    mining_sources = {s['file']: s for s in mined['sources']} if mined else {}
    baseline = None
    baseline_threshold = None
    baseline_original_threshold = None
    if args.baseline:
        baseline = tf.lite.Interpreter(model_path=str(args.baseline), num_threads=4)
        baseline.allocate_tensors()
        arrays = np.load(output / 'features.npz')
        manifest_for_calibration = json.loads((output / 'data_manifest.json').read_text(encoding='utf-8'))
        values = predict_int8(baseline, arrays['X_validation'])
        labels = arrays['y_validation']
        quiet = quiet_validation_mask(manifest_for_calibration['validation'])
        calibration = select_threshold(values[labels == 1], values[labels == 0], values[quiet])
        baseline_threshold = calibration['threshold']
        baseline_original_threshold = json.loads((args.baseline.parent / 'results.json').read_text(encoding='utf-8'))['calibration']['threshold']
    sources = sorted((ROOT / 'dataset/background_test2').glob('*'))
    sources += [ROOT / 'dataset/background_test/silencioabsoluto.wav']
    result = {'threshold': threshold, 'high_threshold': high, 'streams': {},
              'limitations': ['Diagnostic recordings may have been inspected in earlier model development.',
                              'Only sampled sections are evaluated, not the entire file.',
                              'No on-device timing, acoustics or final microphone false-wake guarantee.']}
    if baseline is not None:
        result['baseline'] = {'model': str(args.baseline), 'calibration_on_same_validation': calibration,
                              'original_threshold': baseline_original_threshold,
                              'limitation': 'Negative replay comparison only; older baseline trained on Thayza, so do not compare its positive test recall as independent.'}
    for path in sources:
        if path.suffix.lower() not in ('.wav', '.mp3', '.ogg'):
            continue
        info = sf.info(path)
        origin, end = 0., info.duration
        relative = path.relative_to(ROOT).as_posix()
        if relative in mining_sources:
            source = mining_sources[relative]
            if hashlib.sha256(path.read_bytes()).hexdigest() != source['sha256']:
                raise RuntimeError('Evaluation source changed after mining.')
            start_sample, end_sample = source['ranges']['test']
            origin, end = start_sample/16000, end_sample/16000
        section_length = min(args.seconds_per_source / 3, (end-origin) / 3)
        offsets = [origin, origin+(end-origin-section_length)/2, end-section_length]
        chunks = [read_chunk(path, offset, section_length) for offset in offsets]
        by_stride = {}
        for stride_ms in (160, 320):
            step = stride_ms * 16
            total_events, total_seconds, max_score, windows = 0, 0., 0., 0
            baseline_events = 0
            baseline_original_events = 0
            for audio in chunks:
                starts = list(range(0, len(audio)-15999, step))
                if not starts:
                    continue
                x = np.array([feature(audio[i:i+16000]) for i in starts])
                scores = predict_int8(interpreter, x)
                times = [round(i/16) for i in starts]
                events = detection_events(scores.tolist(), times, threshold, high, 2000)
                total_events += len(events)
                if baseline is not None:
                    old_scores = predict_int8(baseline, x)
                    baseline_events += len(detection_events(old_scores.tolist(), times, baseline_threshold,
                                                           max(.98, baseline_threshold), 2000))
                    baseline_original_events += len(detection_events(old_scores.tolist(), times, baseline_original_threshold,
                                                                    max(.98, baseline_original_threshold), 2000))
                total_seconds += len(audio)/16000
                windows += len(scores)
                max_score = max(max_score, float(np.max(scores)))
            by_stride[str(stride_ms)] = {'seconds': total_seconds, 'windows': windows,
                                         'events': total_events, 'max_score': max_score,
                                         'events_per_hour': total_events * 3600/max(1, total_seconds)}
            if baseline is not None:
                by_stride[str(stride_ms)]['baseline_events_same_validation_calibration'] = baseline_events
                by_stride[str(stride_ms)]['baseline_events_original_threshold'] = baseline_original_events
        by_stride['evaluated_source_range_s'] = [origin, end]
        by_stride['evaluated_sections_s'] = [[offset, offset+section_length] for offset in offsets]
        result['streams'][path.relative_to(ROOT).as_posix()] = by_stride
        print(path.name, json.dumps(by_stride), flush=True)

    # Controlled stress, not additional independent recordings: same held-out clips,
    # combined with held-out real ambient audio at reproducible SNRs.
    manifest = json.loads((output / 'data_manifest.json').read_text(encoding='utf-8'))
    positives = [r for r in manifest['test'] if r['label']]
    if not positives:
        positives = [r for r in manifest['train'] if r['label'] and r['variant'] == 'clean'
                     and r['speaker'] != 'synthetic']
        result['noise_stress_limitation'] = 'Final refit: positives are training recordings. Stress is diagnostic, NOT unseen-voice recall.'
    backgrounds = [r for r in manifest['test'] if r['speaker'] == 'inmp_ambiente']
    stress = {}
    for snr in (20., 10.):
        features, speakers = [], []
        for index, row in enumerate(positives):
            audio = load_audio(ROOT / row['file'])
            background = backgrounds[index % len(backgrounds)]['file']
            filename, offset = background.rsplit('@', 1)
            noise = read_chunk(ROOT / filename, float(offset), 1.)
            noise -= noise.mean()
            noise_rms = max(float(np.sqrt(np.mean(noise**2))), 1e-8)
            signal_rms = float(np.sqrt(np.mean(audio**2)))
            mixed = audio + noise * (signal_rms/noise_rms) * 10**(-snr/20)
            mixed *= min(1., .98 / max(float(np.max(np.abs(mixed))), 1e-8))
            features.append(feature(mixed))
            speakers.append(row['speaker'])
        scores = predict_int8(interpreter, np.array(features))
        stress[str(snr)] = {'overall': metrics(scores, np.ones(len(scores)), threshold),
                            'per_speaker': {}}
        for speaker in sorted(set(speakers)):
            mask = np.array([s == speaker for s in speakers])
            stress[str(snr)]['per_speaker'][speaker] = metrics(scores[mask], np.ones(sum(mask)), threshold)
    result['heldout_noise_stress'] = stress
    annotations = [r for r in manifest['train'] if r['label'] and r['variant'] == 'clean'
                   and r.get('original_phrase')]
    if annotations:
        phrase_scores = predict_int8(interpreter, np.array([feature(load_audio(ROOT / r['file'])) for r in annotations]))
        result['annotated_phrase_diagnostic'] = {
            'limitation': 'Known training clips; greetings remain positive; not independent recall or automatic word-boundary verification.',
            'samples': [{'phrase': row['original_phrase'], 'file': row['file'], 'score': float(score),
                         'detected': bool(score >= threshold)} for row, score in zip(annotations, phrase_scores)]}
    # Check the actual temporal confirmation rule, not only one centered score.
    # Artificial silence context and known clips make this diagnostic, not live recall.
    chosen = []
    rng = np.random.default_rng(20261015)
    for speaker in sorted({r['speaker'] for r in positives}):
        buckets = {}
        for row in positives:
            if row['speaker'] == speaker:
                buckets.setdefault(row['group'], []).append(row)
        for bucket in buckets.values():
            rng.shuffle(bucket)
        selected = []
        while len(selected) < 8 and any(buckets.values()):
            for group in sorted(buckets):
                if buckets[group] and len(selected) < 8:
                    selected.append(buckets[group].pop())
        chosen.extend(selected)
    temporal = {}
    for stride_ms in (160, 320):
        step = stride_ms * 16
        speakers = {}
        for row in chosen:
            audio = np.pad(load_audio(ROOT / row['file']), (16000, 16000))
            detected = []
            for phase in (0, step // 2):
                starts = list(range(phase, len(audio)-15999, step))
                x = np.array([feature(audio[i:i+16000]) for i in starts])
                scores = predict_int8(interpreter, x)
                events = detection_events(scores.tolist(), [round(i/16) for i in starts],
                                          threshold, high, 2000)
                detected.append(bool(events))
            counts = speakers.setdefault(row['speaker'], {'trials': 0, 'detected': 0})
            counts['trials'] += len(detected)
            counts['detected'] += sum(detected)
        for counts in speakers.values():
            counts['recall'] = counts['detected'] / counts['trials']
        temporal[str(stride_ms)] = speakers
    result['temporal_positive_diagnostic'] = temporal
    result['temporal_positive_limitation'] = 'At most 8 known clips per speaker balanced across source recordings, padded with silence, two window phases; not independent hardware recall.'
    (output / 'stream_evaluation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    false_events = sum(runs['160']['events'] for runs in result['streams'].values())
    positive_recall = report['test']['int8']['recall']
    positive_screen = positive_recall is not None and positive_recall >= .8
    report['promotion'] = {
        'automatic': False, 'approved': False, 'hardware_validated': False,
        'diagnostic_false_events_160ms': false_events,
        'heldout_positive_recall': positive_recall, 'minimum_positive_recall_screen': .8,
        'offline_checks_passed': bool(false_events == 0 and report['calibration']['deployable']
                                      and report['silence_sanity']['passed'] and positive_screen),
        'reason': ('Rejected: diagnostic false wakes or unusable calibration; keep the active model.'
                   if false_events or not report['calibration']['deployable']
                   else 'Rejected: held-out positive recall is unavailable or below the initial screening floor.' if not positive_screen
                   else 'Offline checks passed, but independent positive sessions and on-device validation are still required.'),
    }
    (output / 'results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(stress, indent=2), flush=True)


if __name__ == '__main__':
    main()
