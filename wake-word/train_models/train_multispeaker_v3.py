"""Train a speaker-balanced ESP32 candidate with explicit holdout policies."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import random
import secrets
import sys

os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '2')
os.environ.setdefault('NUMBA_CACHE_DIR', str(Path(os.environ.get('TEMP', '.')) / 'nuclea-numba'))

import librosa
import numpy as np
import soundfile as sf
import tensorflow as tf

import train_final_hardneg as baseline
from hard_negative_mining import validate_mined_manifest
from training_config import training_config
from reviewed_split import enrich_capture_times, eric_split_plan
from train_noise_robust_v1 import mfcc_from_audio
from multispeaker_data import (
    metadata_by_name, partition_for, positive_quality, recording_group,
    safe_shift, select_threshold, stable_partition, quiet_validation_mask,
    speaker_examples, normalize_speaker,
    TEST_ONLY_SPEAKERS,
)


ROOT = Path(__file__).resolve().parents[1]
SPLITS = ('train', 'validation', 'test')
SEED = 20261015


def load_audio(path: Path) -> np.ndarray:
    if path.stat().st_size < 200:
        raise RuntimeError(f'Audio ausente/Git LFS nao materializado: {path}')
    audio, rate = sf.read(path, dtype='float32', always_2d=True)
    audio = audio.mean(axis=1)
    if rate != 16000:
        audio = librosa.resample(audio, orig_sr=rate, target_sr=16000)
    return audio.astype(np.float32)


def feature(audio: np.ndarray) -> np.ndarray:
    return mfcc_from_audio(audio)[..., None]


def prepare(output: Path, final_fit: bool = False, include_reviewed_negatives: bool = False,
            mined_negative_dir: Path | None = None, seed: int = SEED,
            excluded_speakers: tuple[str, ...] = (), reviewed_clean_only: bool = False,
            eric_random_split: bool = False) -> tuple[dict, dict]:
    rng = np.random.default_rng(seed)
    rows = []
    rejected = []
    waves = {}
    noise_pool = []
    dialogue_pool = []

    def add(audio, label, speaker, group, split, source, variant='clean', weight=1., phrase='', provenance=None):
        audio = np.asarray(audio, dtype=np.float32)
        if len(audio) != 16000:
            rejected.append({'file': source, 'reason': 'not_one_second', 'samples': len(audio)})
            return
        if label:
            valid, stats = positive_quality(audio)
            if not valid:
                rejected.append({'file': source, 'reason': 'silent_or_insufficient_activity', **stats})
                return
        pcm = np.clip(np.rint(audio * 32768), -32768, 32767).astype('<i2')
        digest = hashlib.sha256(pcm.tobytes()).hexdigest()
        rows.append({'file': source, 'label': label, 'speaker': speaker,
                     'group': group, 'split': split, 'variant': variant,
                     'weight': weight, 'sha256': digest, 'original_phrase': phrase,
                     **(provenance or {})})
        waves[len(rows) - 1] = audio

    # Recording holdouts are the default; Eric can opt into overlap-safe clip splits.
    for directory in sorted((ROOT / 'dataset/real').glob('wakeword_*')):
        if not directory.is_dir():
            continue
        examples = speaker_examples(directory, include_reviewed_negatives, excluded_speakers,
                                    clean_only=reviewed_clean_only)
        plan = {}
        if eric_random_split and normalize_speaker(directory.name) == 'eric':
            enrich_capture_times(examples)
            plan = eric_split_plan(examples, seed)
            if not plan:
                raise ValueError('No reviewed Eric positives available for random split.')
        for example in examples:
            path, label, variant = example['path'], example['label'], example['variant']
            speaker, group = example['speaker'], example['group']
            if not example['metadata']:
                rejected.append({'file': str(path.relative_to(ROOT)), 'reason': 'missing_provenance'})
                continue
            split = partition_for(speaker, group, final_fit)
            provenance = None
            if str(path) in plan:
                provenance = {'source_group': group,
                              'clip_start_s': float(example['metadata']['clip_start_s']),
                              'clip_end_s': float(example['metadata']['clip_end_s'])}
                split, group = plan[str(path)]['split'], plan[str(path)]['group']
            if variant == 'augmented' and split != 'train':
                continue
            # Raw and denoised versions of the same utterance stay in one group.
            weight = .25 if variant == 'augmented' else .5 if variant == 'original' else 1.
            kind = speaker if label else 'matched_silence'
            audio = load_audio(path)
            add(audio, label, kind, group, split, str(path.relative_to(ROOT)), variant, weight,
                str(example['metadata'].get('original_phrase') or ''), provenance)
            if not label and split == 'train' and len(audio) == 16000:
                noise_pool.append(audio.copy())

    # Annotated Common Voice sources are grouped by client, never random WAV split.
    voice_dir = ROOT / 'dataset/background_voice'
    voice_meta = metadata_by_name(voice_dir / 'metadata.csv', 'output')
    for path in sorted(voice_dir.glob('*.wav')):
        row = voice_meta.get(path.name, {})
        if 'nuclea' in str(row.get('sentence', '')).lower():
            rejected.append({'file': str(path.relative_to(ROOT)), 'reason': 'target_word_in_negative_transcript'})
            continue
        group = 'voice:' + (row.get('client_id') or row.get('source') or 'unknown')
        split = stable_partition(group) if row else 'train'
        add(load_audio(path), 0, 'speech', group, split, str(path.relative_to(ROOT)))

    # This legacy conversation was already used for mined training negatives.
    # The separate background_test2 conversation remains diagnostic-only.
    dialogue_path = ROOT / 'dataset/background_test/conversa.mp3'
    if dialogue_path.exists():
        dialogue = load_audio(dialogue_path)
        for offset in range(0, len(dialogue)-15999, 32000):
            window = dialogue[offset:offset+16000]
            add(window, 0, 'dialogue', 'dialogue:conversa.mp3', 'train',
                f'{dialogue_path.relative_to(ROOT).as_posix()}@{offset / 16000:.3f}')
            if np.sqrt(np.mean(window**2)) > .0001:
                dialogue_pool.append(window.copy())

    # Counterexamples from full legacy negative scenes, not only mined snippets.
    # Differently named "*new*" sources remain excluded because they may be
    # alternate encodings of background_test2 evaluation recordings.
    for filename, kind in [('ambiente.wav', 'scene'), ('musica.wav', 'scene'),
                           ('negative.wav', 'dialogue')]:
        path = ROOT / 'dataset/background_test' / filename
        if not path.exists():
            continue
        audio = load_audio(path)
        for offset in range(0, len(audio)-15999, 32000):
            window = audio[offset:offset+16000]
            add(window, 0, kind, 'legacy_scene:' + filename, 'train',
                f'{path.relative_to(ROOT).as_posix()}@{offset / 16000:.3f}')
            if np.sqrt(np.mean(window**2)) > .0001:
                (dialogue_pool if kind == 'dialogue' else noise_pool).append(window.copy())

    # Unknown-origin noise, old silence and mined false wakes are TRAIN ONLY.
    # They cannot support claims of independent false-positive performance.
    for folder, kind in [('background_noise', 'noise'),
                         ('background_silence/generated', 'silence'),
                         ('background_hard_negative/generated', 'hard_negative')]:
        for path in sorted((ROOT / 'dataset' / folder).rglob('*.wav')):
            # These excerpts come from the long INMP441 ambient session below.
            # Use only the explicit chronological split, never legacy copies.
            if 'inmp441' in path.as_posix().lower():
                continue
            audio = load_audio(path)
            if len(audio) != 16000:
                continue
            add(audio, 0, kind, kind + ':legacy', 'train', str(path.relative_to(ROOT)))
            if kind == 'noise' and np.sqrt(np.mean(audio**2)) > .0001:
                noise_pool.append(audio)

    # Real room/speech sessions: chronological blocks, 2-second guards, no overlap.
    # These are held-out time spans, NOT independent recording sessions.
    for folder in ('ambiente', 'negative'):
        for path in sorted((ROOT / 'dataset/inmp441_v1' / folder).glob('*.wav')):
            audio = load_audio(path)
            n = len(audio)
            limits = [(0, int(.70*n), 'train'), (int(.70*n)+32000, int(.85*n), 'validation'),
                      (int(.85*n)+32000, n, 'test')]
            for start, stop, split in limits:
                for offset in range(start, stop-15999, 16000):
                    add(audio[offset:offset+16000], 0, 'inmp_' + folder,
                        f'{folder}:{path.name}:{split}', split,
                        f'{path.relative_to(ROOT).as_posix()}@{offset / 16000:.3f}')
                    if split == 'train' and folder == 'ambiente':
                        noise_pool.append(audio[offset:offset+16000].copy())

    # Complete quiet recordings from other microphones add realistic room tone.
    quiet = ROOT / 'dataset/background_silence/silencio.wav'
    if quiet.exists():
        audio = load_audio(quiet)
        for offset in range(0, len(audio)-15999, 16000*5):
            add(audio[offset:offset+16000], 0, 'room_tone', 'silencio.wav', 'train',
                f'{quiet.relative_to(ROOT).as_posix()}@{offset / 16000:.3f}')

    # Synthetic speech is capped and used only in training, never as real recall.
    synthetic = sorted((ROOT / 'dataset/wakeword_synthetic').rglob('*.wav'))
    synthetic += sorted((ROOT / 'dataset/wakeword_eleven/clean').rglob('*.wav'))
    random.Random(seed).shuffle(synthetic)
    for path in synthetic[:160]:
        add(load_audio(path), 1, 'synthetic', 'synthetic:train', 'train', str(path.relative_to(ROOT)), weight=.4)

    mining_info = None
    if mined_negative_dir is not None:
        mined_negative_dir = mined_negative_dir.resolve()
        manifest_path = mined_negative_dir / 'manifest.json'
        mining = json.loads(manifest_path.read_text(encoding='utf-8'))
        validate_mined_manifest(mining)
        mining_info = {'directory': str(mined_negative_dir),
                       'manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                       'teacher_sha256': mining['teacher_sha256'], 'sources': mining['sources'],
                       'label_basis': mining['label_basis'], 'policy': mining['policy']}
        for record in mining['records']:
            path = (mined_negative_dir / record['file']).resolve()
            if not path.is_relative_to(mined_negative_dir):
                raise ValueError('Mined path escapes corpus directory.')
            if hashlib.sha256(path.read_bytes()).hexdigest() != record['wav_sha256']:
                raise ValueError(f'Mined audio hash mismatch: {path}')
            split = record['split']
            kind = 'mined_hard_negative' if split == 'train' else 'mined_quiet' if record['kind'] == 'quiet' else 'mined_scene'
            audio = load_audio(path)
            add(audio, 0, kind, record['group'], split,
                str(path.relative_to(ROOT)), 'mined_' + record['kind'], 2. if record['kind'] == 'hard' else 1.)
            if split == 'train':
                (dialogue_pool if 'conversa' in Path(record['source']).stem else noise_pool).append(audio.copy())
    for row in rows:
        if normalize_speaker(row['group'].split(':', 1)[0]) in excluded_speakers:
            raise RuntimeError('Excluded speaker entered the dataset.')
        if row['split'] != 'test' and row['group'].split(':', 1)[0] in TEST_ONLY_SPEAKERS:
            raise RuntimeError('Test-only speaker leaked into fitting or calibration.')

    # Exact PCM duplicates stay in the most conservative partition only.
    priority = {'test': 0, 'validation': 1, 'train': 2}
    seen = {}
    keep = []
    for index in sorted(range(len(rows)), key=lambda i: priority[rows[i]['split']]):
        row = rows[index]
        previous = seen.get(row['sha256'])
        if previous is not None:
            if previous['label'] != row['label']:
                raise RuntimeError(f'Contradictory labels: {previous["file"]} / {row["file"]}')
            rejected.append({'file': row['file'], 'reason': 'duplicate_pcm', 'kept': previous['file']})
            continue
        seen[row['sha256']] = row
        keep.append(index)

    originals = [(rows[i], waves[i]) for i in keep]
    data = {split: [] for split in SPLITS}
    all_rows = []
    for row, audio in originals:
        data[row['split']].append((feature(audio), row.copy()))
        all_rows.append(row.copy())
    del waves
    print(f'Base features: {len(all_rows)}; rejected: {len(rejected)}', flush=True)

    # Additional train-only variants preserve the whole word: no +/-300 ms cuts.
    clean_train = [(row, audio) for row, audio in originals
                   if row['split'] == 'train' and row['label'] and row['variant'] == 'clean'
                   and row['speaker'] != 'synthetic']
    for row, audio in clean_train:
        for version in range(3):
            mixed = safe_shift(audio, int(rng.integers(-1280, 1281)))
            mixed = mixed * 10**(rng.uniform(-12, 3) / 20)
            if noise_pool and version:
                pool = dialogue_pool if dialogue_pool and rng.random() < .25 else noise_pool
                noise = pool[int(rng.integers(len(pool)))].copy()
                noise -= noise.mean()
                signal_rms = float(np.sqrt(np.mean(mixed**2)))
                noise_rms = float(np.sqrt(np.mean(noise**2)))
                snr = float(rng.uniform(8, 25))
                mixed = mixed + noise * (signal_rms / max(noise_rms, 1e-8)) * 10**(-snr / 20)
            peak = float(np.max(np.abs(mixed)))
            mixed = mixed * min(1., .98 / max(peak, 1e-8))
            record = {**row, 'variant': f'v3_safe_noise_{version}', 'weight': .5}
            if reviewed_clean_only:
                # Quantize once, then use exactly the saved PCM for MFCC and audit.
                pcm = np.clip(np.rint(mixed * 32768), -32768, 32767).astype('<i2')
                mixed = pcm.astype(np.float32) / 32768
                identity = hashlib.sha256(row['file'].encode()).hexdigest()[:16]
                destination = output / 'augmented' / f'{row["speaker"]}_{identity}_{version}.wav'
                destination.parent.mkdir(exist_ok=True)
                if destination.exists():
                    raise RuntimeError('Refusing to overwrite a fresh augmentation.')
                sf.write(destination, mixed, 16000, subtype='PCM_16')
                record.update(file=str(destination.relative_to(ROOT)), parent_file=row['file'],
                              parent_sha256=row['sha256'], sha256=hashlib.sha256(pcm.tobytes()).hexdigest())
            data['train'].append((feature(mixed), record))
            all_rows.append(record)

    # Reviewed same-room negatives counter background cues correlated with positives.
    for row, audio in originals:
        if row['split'] != 'train' or row['variant'] != 'reviewed_negative':
            continue
        for gain_db in (-6, 6, 12):
            changed = audio * 10**(gain_db / 20)
            changed *= min(1., .98 / max(float(np.max(np.abs(changed))), 1e-8))
            record = {**row, 'variant': f'reviewed_negative_gain_{gain_db}', 'weight': .5}
            data['train'].append((feature(changed), record))
            all_rows.append(record)

    # Explicit quiet negatives cover digital zero, DC, low noise and mains hum.
    for split_index, split in enumerate(SPLITS):
        quiet_rng = np.random.default_rng(seed + 100 + split_index)
        for i in range(180 if split == 'train' else 60):
            level = quiet_rng.uniform(-95, -35)
            audio = quiet_rng.normal(size=16000).astype(np.float32) * 10**(level / 20)
            if i % 3 == 0:
                frequency = quiet_rng.uniform(49, 61)
                audio += np.sin(np.arange(16000) * 2*np.pi*frequency/16000).astype(np.float32) * 10**(level/20)
            if i % 5 == 0:
                audio += quiet_rng.uniform(-.003, .003)
            row = {'file': f'generated:{split}:{i}', 'label': 0, 'speaker': 'quiet_synthetic',
                   'group': f'quiet:{split}', 'split': split, 'variant': 'quiet', 'weight': 1., 'sha256': ''}
            data[split].append((feature(audio), row))
            all_rows.append(row)

    arrays = {}
    manifest = {}
    for split in SPLITS:
        arrays['X_' + split] = np.array([x for x, _ in data[split]], dtype=np.float32)
        arrays['y_' + split] = np.array([r['label'] for _, r in data[split]], dtype=np.int32)
        manifest[split] = [r for _, r in data[split]]
        print(split, arrays['X_' + split].shape, Counter(r['speaker'] for r in manifest[split]), flush=True)
    np.savez_compressed(output / 'features.npz', **arrays)
    (output / 'data_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    audit = {'final_fit': final_fit, 'include_reviewed_negatives': include_reviewed_negatives,
             'seed': seed, 'excluded_speakers': sorted(excluded_speakers),
             'reviewed_clean_only': reviewed_clean_only, 'eric_random_split': eric_random_split,
             'positive_input_policy': ('Existing clean WAVs with surviving declared parents only; old augmented and original aliases ignored; fresh train-only WAV variants in output/augmented.'
                                       if reviewed_clean_only else 'Existing original, clean and stored train augmentations.'),
             'eric_split_limitation': ('Random overlapping-window components, stratified by source, approximately 80/10/10; same voice and sessions in all splits, NOT unseen-session recall.'
                                       if eric_random_split else None),
             'mined_negative_corpus': mining_info,
             'positive_phrase_policy': 'Greetings such as oi Nuclea remain positive; no phrase-text exclusion or conversion to negative.',
             'negative_review_confirmation': 'User explicitly approved negative_silence on 2026-10-15' if include_reviewed_negatives else None,
             'rejected': rejected, 'counts': {s: dict(Counter(r['speaker'] for r in manifest[s])) for s in SPLITS},
             'test_only_speakers': sorted(TEST_ONLY_SPEAKERS - set(excluded_speakers)),
             'split_policy': ('Excluded speakers absent; non-test-only real speakers fit. Training-positive recall is not generalization.'
                              if final_fit else 'Eric overlap components randomized within source; other voices use recording/speaker holdouts; excluded speakers absent.'
                              if eric_random_split else 'Subject to excluded_speakers: lara/ryam validation; gabriel and test-only speakers test; eric session 002 test.'),
             'negative_limitations': 'INMP441 temporal holdout is the same recording; legacy noise, silence and mined false wakes train-only.',
             'positive_quality': 'Reject AC RMS < -60 dBFS or fewer than 6 x 20 ms frames above -50 dBFS; no relabeling.',
             'augmentation': 'Stored train-only variants plus 3 safe shifts/gain/noise per clean train clip, SNR 8-25 dB; 25% of mixed variants use training dialogue.'}
    (output / 'data_audit.json').write_text(json.dumps(audit, indent=2), encoding='utf-8')
    return arrays, manifest


def create_temporal_model(dropout: float = .3):
    # Temporal receptive field reaches ~780 ms rather than local 160 ms cues.
    layers = tf.keras.layers
    inputs = layers.Input((13, 49, 1))
    x = layers.Conv2D(16, (3, 5), strides=(1, 2), padding='same', use_bias=False)(inputs)
    x = layers.ReLU()(layers.BatchNormalization()(x))
    x = layers.MaxPooling2D((2, 2))(x)
    for stride in (1, 2):
        x = layers.DepthwiseConv2D((3, 5), strides=(1, stride), padding='same', use_bias=False)(x)
        x = layers.ReLU()(layers.BatchNormalization()(x))
        x = layers.Conv2D(32, (1, 1), use_bias=False)(x)
        x = layers.ReLU()(layers.BatchNormalization()(x))
    x = layers.GlobalAveragePooling2D()(x)
    x = layers.Dropout(dropout)(x)
    outputs = layers.Dense(2, activation='softmax')(x)
    model = tf.keras.Model(inputs, outputs)
    model.compile(optimizer=tf.keras.optimizers.Adam(.0007),
                  loss='sparse_categorical_crossentropy', metrics=['accuracy'])
    return model


def weights_for(rows: list[dict]) -> np.ndarray:
    # Each real speaker contributes equally, regardless of clip/augmentation count.
    totals = defaultdict(float)
    group_totals = defaultdict(float)
    speaker_groups = defaultdict(set)
    for row in rows:
        totals[(row['label'], row['speaker'])] += row['weight']
        if row['label']:
            key = (row['speaker'], row['group'])
            group_totals[key] += row['weight']
            speaker_groups[row['speaker']].add(row['group'])
    positive_speakers = {s for label, s in totals if label and s != 'synthetic'}
    negative_kinds = {s for label, s in totals if not label}
    weights = []
    for row in rows:
        if row['label']:
            real_share = .95 if (1, 'synthetic') in totals else 1.
            target = .05 if row['speaker'] == 'synthetic' else real_share / len(positive_speakers)
            weights.append(row['weight'] * target / len(speaker_groups[row['speaker']]) /
                           group_totals[(row['speaker'], row['group'])])
        else:
            # Speech is more confusable than many near-identical quiet variants.
            speech_kinds = negative_kinds & {'speech', 'dialogue'}
            has_mined = 'mined_hard_negative' in negative_kinds
            if row['speaker'] == 'mined_hard_negative':
                target = .3
            elif row['speaker'] in speech_kinds:
                target = (.4 if has_mined else .6) / max(1, len(speech_kinds))
            else:
                target = (.3 if has_mined else .4) / max(1, len(negative_kinds) - len(speech_kinds) - int(has_mined))
            weights.append(row['weight'] * target / totals[(row['label'], row['speaker'])])
    values = np.array(weights, dtype=np.float32)
    return values / values.mean()


def metrics(scores, labels, threshold):
    p = scores[labels == 1]
    n = scores[labels == 0]
    return {'tp': int(np.sum(p >= threshold)), 'positive_count': len(p),
            'recall': float(np.mean(p >= threshold)) if len(p) else None,
            'fp': int(np.sum(n >= threshold)), 'negative_count': len(n),
            'fpr': float(np.mean(n >= threshold)) if len(n) else None,
            'max_negative': float(np.max(n)) if len(n) else None}


def predict(model, x):
    # Direct calls avoid creating tf.data thread pools repeatedly on Windows.
    return np.concatenate([model(x[i:i+128], training=False).numpy()[:, 1]
                           for i in range(0, len(x), 128)])


def quantize(model, x, output, seed: int = SEED):
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    indices = np.random.default_rng(seed).choice(len(x), min(500, len(x)), replace=False)
    converter.representative_dataset = lambda: ([x[i:i+1]] for i in indices)
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.int8
    converter.inference_output_type = tf.int8
    binary = converter.convert()
    (output / 'nuclea_int8.tflite').write_bytes(binary)
    interpreter = tf.lite.Interpreter(model_content=binary, num_threads=4)
    interpreter.allocate_tensors()
    inp = interpreter.get_input_details()[0]
    out = interpreter.get_output_details()[0]
    ops = sorted({op['op_name'] for op in interpreter._get_ops_details()} - {'DELEGATE'})
    allowed = {'CONV_2D', 'DEPTHWISE_CONV_2D', 'MAX_POOL_2D', 'FULLY_CONNECTED',
               'RESHAPE', 'ADD', 'MUL', 'MEAN', 'RELU', 'SOFTMAX'}
    if set(ops) - allowed or inp['dtype'] != np.int8 or out['dtype'] != np.int8:
        raise RuntimeError(f'Unsupported ESP32 contract: {ops}')
    return interpreter, {'bytes': len(binary), 'sha256': hashlib.sha256(binary).hexdigest(),
                         'ops': ops, 'input_scale': inp['quantization'][0],
                         'input_zero_point': inp['quantization'][1],
                         'input_shape': inp['shape'].tolist(), 'output_shape': out['shape'].tolist()}


def predict_int8(interpreter, x):
    inp, out = interpreter.get_input_details()[0], interpreter.get_output_details()[0]
    scale, zero = inp['quantization']
    out_scale, out_zero = out['quantization']
    scores = []
    for sample in x:
        value = np.clip(np.rint(sample / scale + zero), -128, 127).astype(np.int8)
        interpreter.set_tensor(inp['index'], value[None])
        interpreter.invoke()
        scores.append((int(interpreter.get_tensor(out['index'])[0, 1]) - out_zero) * out_scale)
    return np.array(scores)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'output/output_multispeaker_v3')
    parser.add_argument('--epochs', type=int, default=65)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--reuse-features', action='store_true')
    parser.add_argument('--architecture', choices=('baseline', 'temporal'), default='temporal')
    parser.add_argument('--final-fit', action='store_true', help='Fit all speakers to training-loss convergence; no claim of held-out positive recall.')
    parser.add_argument('--development-report', type=Path)
    parser.add_argument('--include-reviewed-negatives', action='store_true',
                        help='Include manually approved negative_silence and negative folders.')
    parser.add_argument('--mined-negative-dir', type=Path)
    parser.add_argument('--seed', type=int)
    parser.add_argument('--randomize', action='store_true',
                        help='Sample learning rate, dropout and batch size; record the seed and values.')
    parser.add_argument('--exclude-speaker', action='append', default=[],
                        help='Exclude a real speaker from every split, including stored augmentations.')
    parser.add_argument('--reviewed-clean-only', action='store_true',
                        help='Ignore stored originals/augmentations; regenerate train-only variants from surviving clean WAVs.')
    parser.add_argument('--eric-random-split', action='store_true',
                        help='Stratify Eric utterance groups randomly across train/validation/test, keeping overlaps together.')
    args = parser.parse_args()
    os.chdir(ROOT)
    output = args.output.resolve()
    excluded_speakers = tuple(sorted({normalize_speaker(name) for name in args.exclude_speaker}))
    if args.eric_random_split and (not args.reviewed_clean_only or args.final_fit or 'eric' in excluded_speakers):
        parser.error('--eric-random-split requires --reviewed-clean-only, Eric included, and development mode.')
    seed = args.seed
    if seed is None and args.reuse_features:
        cached = json.loads((output / 'data_audit.json').read_text(encoding='utf-8'))
        seed = cached.get('seed', SEED)
    if seed is None:
        seed = secrets.randbits(31) if args.randomize else SEED
    config = training_config(seed, args.randomize)
    if args.randomize and args.architecture != 'temporal':
        parser.error('--randomize requires the temporal architecture.')
    print('Training configuration: ' + json.dumps(config), flush=True)
    output.mkdir(parents=True, exist_ok=True)
    tf.config.threading.set_intra_op_parallelism_threads(4)
    tf.config.threading.set_inter_op_parallelism_threads(2)
    tf.keras.utils.set_random_seed(seed)
    if args.reuse_features:
        arrays = dict(np.load(output / 'features.npz'))
        manifest = json.loads((output / 'data_manifest.json').read_text(encoding='utf-8'))
        audit = json.loads((output / 'data_audit.json').read_text(encoding='utf-8'))
        if (bool(audit.get('reviewed_clean_only')) != args.reviewed_clean_only or
                bool(audit.get('eric_random_split')) != args.eric_random_split):
            raise RuntimeError('Cached review or Eric split policy differs; prepare a new output.')
        if audit.get('seed', SEED) != seed or set(audit.get('excluded_speakers', [])) != set(excluded_speakers):
            raise RuntimeError('Cached seed or excluded speakers differ; prepare a new output.')
        if bool(audit.get('final_fit')) != args.final_fit:
            raise RuntimeError('Feature split does not match --final-fit.')
        if bool(audit.get('include_reviewed_negatives')) != args.include_reviewed_negatives:
            raise RuntimeError('Cached features do not match --include-reviewed-negatives.')
        if set(audit.get('test_only_speakers', [])) != TEST_ONLY_SPEAKERS - set(excluded_speakers):
            raise RuntimeError('Cached features do not honor the test-only speaker policy; prepare a new output.')
        mined = audit.get('mined_negative_corpus')
        if bool(mined) != bool(args.mined_negative_dir):
            raise RuntimeError('Cached features do not match the mined negative corpus.')
        if mined and (str(args.mined_negative_dir.resolve()) != mined['directory'] or
                      hashlib.sha256((args.mined_negative_dir / 'manifest.json').read_bytes()).hexdigest() != mined['manifest_sha256']):
            raise RuntimeError('Cached mined corpus path or content has changed.')
    else:
        if (output / 'features.npz').exists():
            raise RuntimeError('Output already prepared; use --reuse-features or a new --output.')
        arrays, manifest = prepare(output, args.final_fit, args.include_reviewed_negatives,
                                   args.mined_negative_dir, seed, excluded_speakers,
                                   args.reviewed_clean_only, args.eric_random_split)
    if not args.final_fit and (not np.any(arrays['y_validation'] == 1) or not np.any(arrays['y_validation'] == 0)):
        raise RuntimeError('Development validation requires both positive and negative samples.')
    if args.prepare_only:
        return
    if (output / 'nuclea_final.keras').exists():
        raise RuntimeError('Refusing to overwrite a trained model; use a new output directory.')
    (output / 'training_config.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
    model = baseline.create_model() if args.architecture == 'baseline' else create_temporal_model(config['dropout'])
    model.optimizer.learning_rate.assign(config['learning_rate'])
    weights = weights_for(manifest['train'])
    train = tf.data.Dataset.from_tensor_slices((arrays['X_train'], arrays['y_train'], weights))
    train = train.shuffle(len(weights), seed=seed, reshuffle_each_iteration=True).batch(config['batch_size'])
    validation = tf.data.Dataset.from_tensor_slices((arrays['X_validation'], arrays['y_validation'],
                                                    weights_for(manifest['validation']))).batch(128)
    options = tf.data.Options()
    options.threading.private_threadpool_size = 2
    train, validation = train.with_options(options), validation.with_options(options)
    callbacks = [tf.keras.callbacks.CSVLogger(output / 'history.csv')]
    if not args.final_fit:
        callbacks += [tf.keras.callbacks.EarlyStopping(monitor='val_loss', patience=12, restore_best_weights=True),
                      tf.keras.callbacks.ReduceLROnPlateau(monitor='val_loss', patience=5, factor=.5, min_lr=.00002)]
    else:
        if not args.development_report:
            raise RuntimeError('--final-fit requires a development report documenting the earlier holdout evaluation.')
        development = json.loads(args.development_report.read_text(encoding='utf-8'))
        # The final corpus is larger than the development fold. Stop on training
        # convergence, not on final test scores or the unseen-speaker fold epoch.
        callbacks += [tf.keras.callbacks.EarlyStopping(monitor='loss', patience=8,
                                                       min_delta=.001, restore_best_weights=True),
                      tf.keras.callbacks.ReduceLROnPlateau(monitor='loss', patience=4,
                                                          factor=.5, min_lr=.00002)]
    history = model.fit(train, validation_data=validation if not args.final_fit else None,
                        epochs=args.epochs, verbose=2, callbacks=callbacks)
    model.save(output / 'nuclea_final.keras')
    interpreter, quant = quantize(model, arrays['X_train'], output, seed)
    selector = next(cb for cb in callbacks if isinstance(cb, tf.keras.callbacks.EarlyStopping))
    results = {'seed': seed, 'training_config': config, 'excluded_speakers': list(excluded_speakers),
               'reviewed_clean_only': args.reviewed_clean_only, 'eric_random_split': args.eric_random_split,
               'epochs_run': len(history.history['loss']),
               'architecture': args.architecture, 'final_fit': args.final_fit,
               'best_epoch': int(selector.best_epoch) + 1,
               'quantization': quant}
    if args.final_fit:
        results['development_report'] = str(args.development_report)
        results['final_stopping_rule'] = 'Training loss convergence, patience 8, min_delta .001, at most requested epochs; test scores never select weights.'
        results['positive_recall_limitation'] = 'Non-excluded, non-test-only voices were refit. Test-only voices, if any, stay held out; datasets were inspected in earlier rounds.'
    results['test_only_speakers'] = sorted(TEST_ONLY_SPEAKERS - set(excluded_speakers))
    if args.eric_random_split:
        results['positive_recall_limitation'] = 'Eric train/validation/test share voice and recording sessions; only utterance/overlap groups are held out. Other voices keep speaker holdouts. Not independent-session generalization.'
    validation_scores = predict_int8(interpreter, arrays['X_validation'])
    labels = arrays['y_validation']
    quiet_mask = quiet_validation_mask(manifest['validation'])
    calibration = select_threshold(validation_scores[labels == 1], validation_scores[labels == 0],
                                   validation_scores[quiet_mask])
    threshold = calibration['threshold']
    results['calibration'] = calibration
    # Test is read only after model fitting and threshold selection.
    for split in ('validation', 'test'):
        x, y = arrays['X_' + split], arrays['y_' + split]
        float_scores = predict(model, x)
        scores = predict_int8(interpreter, x)
        result = {'float': metrics(float_scores, y, threshold), 'int8': metrics(scores, y, threshold),
                  'quantization_mean_delta': float(np.mean(np.abs(scores - float_scores))), 'per_source': {}}
        for speaker in sorted({r['speaker'] for r in manifest[split]}):
            mask = np.array([r['speaker'] == speaker for r in manifest[split]])
            result['per_source'][speaker] = metrics(scores[mask], y[mask], threshold)
        np.savez_compressed(output / (split + '_scores.npz'), scores=scores, labels=y)
        results[split] = result
    sanity_audio = [np.zeros(16000, dtype=np.float32), np.ones(16000, dtype=np.float32) * .001,
                    np.ones(16000, dtype=np.float32) * -.001]
    sanity_scores = predict_int8(interpreter, np.array([feature(a) for a in sanity_audio]))
    results['silence_sanity'] = {'zero_dc_scores': sanity_scores.tolist(),
                                 'passed': bool(np.all(sanity_scores < threshold))}
    if args.final_fit:
        rows = manifest['train']
        clean_mask = np.array([r['label'] == 1 and r['variant'] == 'clean' and r['speaker'] != 'synthetic'
                               for r in rows])
        clean_scores = predict_int8(interpreter, arrays['X_train'][clean_mask])
        clean_rows = [r for r, keep in zip(rows, clean_mask) if keep]
        results['training_positive_diagnostic_NOT_generalization'] = {}
        for speaker in sorted({r['speaker'] for r in clean_rows}):
            mask = np.array([r['speaker'] == speaker for r in clean_rows])
            results['training_positive_diagnostic_NOT_generalization'][speaker] = metrics(
                clean_scores[mask], np.ones(sum(mask)), threshold)
    old = ROOT / 'output/output_noise_robust_v2g_replay_hardneg_int8/nuclea_int8.tflite'
    if old.exists() and not args.final_fit:
        previous = tf.lite.Interpreter(model_path=str(old), num_threads=4)
        previous.allocate_tensors()
        scores = predict_int8(previous, arrays['X_test'])
        results['previous_model_same_test'] = metrics(scores, arrays['y_test'], .85)
        results['previous_model_silence'] = predict_int8(previous, np.array([feature(a) for a in sanity_audio])).tolist()
        results['previous_model_comparison_limitation'] = 'Diagnostic only: the previous model trained on some of these positives/negatives.'
    results['promotion'] = {'automatic': False,
                            'reason': 'ESP32 latency, tensor arena, live recall and false wakes require hardware validation.'}
    (output / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps(results, indent=2), flush=True)


if __name__ == '__main__':
    main()
