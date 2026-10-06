from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import hashlib
import json
import random

import librosa
import numpy as np
import tensorflow as tf
from sklearn.utils.class_weight import compute_class_weight

import train_final_hardneg as baseline
from noise_augmentation import (
    fit_or_crop_background,
    mix_at_snr,
    should_mix_positive,
)


SEED = baseline.SEED

REAL_SPEAKERS = baseline.REAL_SPEAKERS
SYNTHETIC_DIRS = baseline.SYNTHETIC_DIRS
BACKGROUND_DIRS = baseline.BACKGROUND_DIRS
HARD_NEGATIVE_DIRS = baseline.HARD_NEGATIVE_DIRS

OUTPUT_DIR = Path("output_noise_robust_v1")

REAL_VAL_FRACTION = baseline.REAL_VAL_FRACTION
BACKGROUND_VAL_FRACTION = baseline.BACKGROUND_VAL_FRACTION
SYNTHETIC_TO_REAL_RATIO = baseline.SYNTHETIC_TO_REAL_RATIO
TARGET_VALIDATION_FPR = baseline.TARGET_VALIDATION_FPR

MAX_EPOCHS = baseline.MAX_EPOCHS
BATCH_SIZE = baseline.BATCH_SIZE

SAMPLE_RATE = baseline.SAMPLE_RATE
NUM_SAMPLES = baseline.NUM_SAMPLES
N_MFCC = baseline.N_MFCC
N_FFT = baseline.N_FFT
WIN_LENGTH = baseline.WIN_LENGTH
HOP_LENGTH = baseline.HOP_LENGTH
N_MELS = baseline.N_MELS
FMIN = baseline.FMIN
FMAX = baseline.FMAX
MAX_FRAMES = baseline.MAX_FRAMES

NOISY_POSITIVE_PROBABILITY = 0.50
SNR_DB_RANGE = (10.0, 30.0)


@dataclass(frozen=True)
class AudioExample:
    path: Path | str
    source: str


@dataclass(frozen=True)
class PositiveTrainingItem:
    path: Path | str
    source: str
    background_path: Path | str | None = None
    snr_db: float | None = None
    time_shift_samples: int = 0


FEATURE_CACHE: dict[str, np.ndarray] = {}


def stable_seed_from_text(text: str) -> int:
    digest = hashlib.sha256(
        text.encode("utf-8"),
    ).digest()

    return int.from_bytes(
        digest[:4],
        byteorder="big",
        signed=False,
    )


def _cache_key(item: Path | PositiveTrainingItem) -> str:
    if isinstance(item, PositiveTrainingItem):
        return "|".join(
            (
                str(Path(item.path).resolve()),
                str(Path(item.background_path).resolve()) if item.background_path else "",
                f"{item.snr_db:.6f}" if item.snr_db is not None else "",
                str(item.time_shift_samples),
            ),
        )

    return str(Path(item).resolve())


def normalize_audio_window(audio: np.ndarray) -> np.ndarray:
    audio = np.asarray(audio, dtype=np.float32)

    if len(audio) < NUM_SAMPLES:
        return np.pad(
            audio,
            (0, NUM_SAMPLES - len(audio)),
        ).astype(np.float32)

    if len(audio) > NUM_SAMPLES:
        start = (len(audio) - NUM_SAMPLES) // 2

        return audio[start:start + NUM_SAMPLES].astype(np.float32)

    return audio.astype(np.float32)


def load_audio_window(filename: Path | str) -> np.ndarray:
    audio, _ = librosa.load(
        filename,
        sr=SAMPLE_RATE,
        mono=True,
    )

    return normalize_audio_window(audio)


def shift_audio_window(audio: np.ndarray, shift_samples: int) -> np.ndarray:
    """Moves a fixed-size window in time, filling the exposed area with silence."""
    source = normalize_audio_window(audio)
    result = np.zeros_like(source)
    amount = min(abs(shift_samples), len(source))

    if amount == 0:
        return source.copy()
    if shift_samples > 0:
        result[amount:] = source[:-amount]
    else:
        result[:-amount] = source[amount:]

    return result


def mfcc_from_audio(audio: np.ndarray) -> np.ndarray:
    mfcc = librosa.feature.mfcc(
        y=audio.astype(np.float32),
        sr=SAMPLE_RATE,
        n_mfcc=N_MFCC,
        n_fft=N_FFT,
        win_length=WIN_LENGTH,
        hop_length=HOP_LENGTH,
        n_mels=N_MELS,
        fmin=FMIN,
        fmax=FMAX,
        center=False,
    )

    if mfcc.shape[1] < MAX_FRAMES:
        mfcc = np.pad(
            mfcc,
            (
                (0, 0),
                (0, MAX_FRAMES - mfcc.shape[1]),
            ),
        )

    return mfcc[:, :MAX_FRAMES].astype(np.float32)


def extract_mfcc(item: Path | str | PositiveTrainingItem) -> np.ndarray:
    key = _cache_key(item)

    if key in FEATURE_CACHE:
        return FEATURE_CACHE[key]

    if isinstance(item, PositiveTrainingItem):
        audio = load_audio_window(item.path)
        audio = shift_audio_window(audio, item.time_shift_samples)

        if item.background_path is not None:
            background = load_audio_window(item.background_path)
            background = fit_or_crop_background(
                background,
                num_samples=NUM_SAMPLES,
                rng=random.Random(
                    stable_seed_from_text(key),
                ),
            )
            audio = mix_at_snr(
                audio,
                background,
                snr_db=float(item.snr_db),
            )
    else:
        audio = load_audio_window(item)

    mfcc = mfcc_from_audio(audio)
    FEATURE_CACHE[key] = mfcc

    return mfcc


def build_positive_training_items(
    positives: list[AudioExample],
    train_backgrounds: list[AudioExample],
    validation_backgrounds: list[AudioExample],
    noisy_probability: float,
    snr_db_range: tuple[float, float],
    rng: random.Random,
) -> list[PositiveTrainingItem]:
    validation_paths = {
        str(example.path)
        for example in validation_backgrounds
    }

    train_candidates = [
        example
        for example in train_backgrounds
        if str(example.path) not in validation_paths
    ]

    if noisy_probability > 0.0 and not train_candidates:
        raise RuntimeError("Não há backgrounds de treino para misturar positivos.")

    items: list[PositiveTrainingItem] = []

    for positive in positives:
        if should_mix_positive(rng, noisy_probability):
            background = rng.choice(train_candidates)
            snr_db = rng.uniform(*snr_db_range)

            items.append(
                PositiveTrainingItem(
                    path=positive.path,
                    source=positive.source,
                    background_path=background.path,
                    snr_db=float(snr_db),
                ),
            )
        else:
            items.append(
                PositiveTrainingItem(
                    path=positive.path,
                    source=positive.source,
                ),
            )

    return items


def make_xy(
    positives: list[PositiveTrainingItem],
    negatives: list[Path],
    seed: int,
):
    X = [
        extract_mfcc(item)
        for item in positives
    ]

    y = [1] * len(positives)

    X.extend(
        extract_mfcc(path)
        for path in negatives
    )

    y.extend([0] * len(negatives))

    X = np.expand_dims(
        np.asarray(X, dtype=np.float32),
        -1,
    )
    y = np.asarray(y, dtype=np.int32)

    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(y))

    return X[idx], y[idx]


def scores(
    model: tf.keras.Model,
    files: list[Path],
) -> np.ndarray:
    if not files:
        return np.asarray([], dtype=np.float32)

    X = np.asarray(
        [
            extract_mfcc(path)
            for path in files
        ],
        dtype=np.float32,
    )
    X = np.expand_dims(X, -1)

    return model.predict(
        X,
        batch_size=256,
        verbose=0,
    )[:, 1]


def write_positive_training_manifest(
    items: list[PositiveTrainingItem],
    output_path: Path,
) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "file",
                "source",
                "background_file",
                "snr_db",
                "time_shift_samples",
                "is_noisy",
            ],
        )
        writer.writeheader()

        for item in items:
            writer.writerow({
                "file": str(item.path),
                "source": item.source,
                "background_file": str(item.background_path or ""),
                "snr_db": "" if item.snr_db is None else f"{item.snr_db:.6f}",
                "time_shift_samples": item.time_shift_samples,
                "is_noisy": int(item.background_path is not None),
            })


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    random.seed(SEED)
    np.random.seed(SEED)
    tf.random.set_seed(SEED)

    print("=" * 72)
    print("NÚCLEA - NOISE ROBUST V1")
    print("=" * 72)

    real_train: list[Path] = []
    real_val: list[Path] = []
    val_by_speaker: dict[str, list[Path]] = {}
    split_info = {}

    for index, (speaker, directory) in enumerate(REAL_SPEAKERS.items()):
        clean, augmented, clean_groups, aug_groups = baseline.load_real_speaker(directory)
        train_groups, val_groups = baseline.split_groups(
            list(clean_groups),
            REAL_VAL_FRACTION,
            SEED + index,
        )

        train_clean = [
            file
            for gid in train_groups
            for file in clean_groups.get(gid, [])
        ]
        train_augmented = [
            file
            for gid in train_groups
            for file in aug_groups.get(gid, [])
        ]
        val_clean = [
            file
            for gid in val_groups
            for file in clean_groups.get(gid, [])
        ]

        real_train.extend(train_clean + train_augmented)
        real_val.extend(val_clean)
        val_by_speaker[speaker] = val_clean

        split_info[speaker] = {
            "clean_total": len(clean),
            "augmented_total": len(augmented),
            "train_groups": len(train_groups),
            "validation_groups": len(val_groups),
            "train_clean": len(train_clean),
            "train_augmented": len(train_augmented),
            "validation_clean": len(val_clean),
        }

        print(
            f"{speaker}: clean={len(clean)} augmented={len(augmented)} "
            f"train={len(train_clean) + len(train_augmented)} val={len(val_clean)}"
        )

    synthetic_all: list[Path] = []

    for directory in SYNTHETIC_DIRS:
        found = baseline.wavs(directory)
        print(f"{directory}: {len(found)} sintéticos")
        synthetic_all.extend(found)

    synthetic_all = sorted(set(synthetic_all))
    synthetic_limit = min(
        len(synthetic_all),
        round(len(real_train) * SYNTHETIC_TO_REAL_RATIO),
    )

    rng = random.Random(SEED + 1000)
    synthetic_train = (
        rng.sample(synthetic_all, synthetic_limit)
        if synthetic_limit < len(synthetic_all)
        else synthetic_all
    )

    positive_examples = [
        AudioExample(path=path, source="real_train")
        for path in real_train
    ] + [
        AudioExample(path=path, source="synthetic_train")
        for path in synthetic_train
    ]

    background_all: list[Path] = []

    for directory in BACKGROUND_DIRS:
        found = baseline.wavs(directory)
        print(f"{directory}: {len(found)} backgrounds")
        background_all.extend(found)

    background_all = sorted(set(background_all))
    background_train, background_val = baseline.split_files(
        background_all,
        BACKGROUND_VAL_FRACTION,
        SEED + 2000,
    )

    hard_negative_train: list[Path] = []

    for directory in HARD_NEGATIVE_DIRS:
        found = baseline.wavs(directory)
        print(f"{directory}: {len(found)} hard negatives (train-only)")
        hard_negative_train.extend(found)

    hard_negative_train = sorted(set(hard_negative_train))
    negative_train = sorted(set(background_train + hard_negative_train))

    positive_train_items = build_positive_training_items(
        positives=positive_examples,
        train_backgrounds=[
            AudioExample(path=path, source="background_train")
            for path in background_train
        ],
        validation_backgrounds=[
            AudioExample(path=path, source="background_validation")
            for path in background_val
        ],
        noisy_probability=NOISY_POSITIVE_PROBABILITY,
        snr_db_range=SNR_DB_RANGE,
        rng=random.Random(SEED + 4000),
    )

    noisy_positive_count = sum(
        item.background_path is not None
        for item in positive_train_items
    )
    clean_positive_count = len(positive_train_items) - noisy_positive_count

    write_positive_training_manifest(
        positive_train_items,
        OUTPUT_DIR / "positive_training_manifest.csv",
    )

    print()
    print("=" * 72)
    print("DATASET USADO")
    print("=" * 72)
    print(f"Positivos treino:       {len(positive_train_items)}")
    print(f"  limpos:               {clean_positive_count}")
    print(f"  com background:       {noisy_positive_count}")
    print(f"Background treino:      {len(negative_train)}")
    print(f"  hard negatives:       {len(hard_negative_train)}")
    print(f"Reais validação:        {len(real_val)}")
    print(f"Background validação:   {len(background_val)}")

    print()
    print("Extraindo MFCCs...")

    X_train, y_train = make_xy(
        positive_train_items,
        negative_train,
        SEED + 3000,
    )
    X_val, y_val = baseline.make_xy(
        real_val,
        background_val,
        SEED + 3001,
    )

    classes = np.unique(y_train)
    weights = compute_class_weight(
        class_weight="balanced",
        classes=classes,
        y=y_train,
    )
    class_weights = {
        int(cls): float(weight)
        for cls, weight in zip(classes, weights)
    }

    print("Class weights:", class_weights)

    tf.keras.backend.clear_session()
    model = baseline.create_model()

    best_path = OUTPUT_DIR / "best.keras"
    callbacks = [
        tf.keras.callbacks.EarlyStopping(
            monitor="val_loss",
            patience=10,
            restore_best_weights=True,
        ),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss",
            factor=0.5,
            patience=4,
            min_lr=1e-5,
        ),
        tf.keras.callbacks.ModelCheckpoint(
            best_path,
            monitor="val_loss",
            save_best_only=True,
        ),
        tf.keras.callbacks.CSVLogger(OUTPUT_DIR / "history.csv"),
    ]

    print()
    print("Treinando...")

    model.fit(
        X_train,
        y_train,
        validation_data=(X_val, y_val),
        epochs=MAX_EPOCHS,
        batch_size=BATCH_SIZE,
        class_weight=class_weights,
        callbacks=callbacks,
        verbose=1,
    )

    model = tf.keras.models.load_model(best_path)
    final_model = OUTPUT_DIR / "nuclea_final.keras"
    model.save(final_model)

    print()
    print("Calibrando threshold...")

    positive_scores = scores(model, real_val)
    background_scores = scores(model, background_val)
    sweep = baseline.threshold_sweep(positive_scores, background_scores)
    best = baseline.choose_threshold(sweep, TARGET_VALIDATION_FPR)
    threshold = float(best["threshold"])

    per_speaker = {}
    validation_rows = []

    for speaker, files in val_by_speaker.items():
        speaker_scores = scores(model, files)
        detected = int(np.sum(speaker_scores >= threshold))
        total = len(speaker_scores)
        recall = detected / total if total else 0.0
        per_speaker[speaker] = {
            "samples": total,
            "detected": detected,
            "missed": total - detected,
            "recall": recall,
        }

        for file, score in zip(files, speaker_scores):
            validation_rows.append({
                "file": str(file),
                "type": "real_positive",
                "speaker": speaker,
                "score_nuclea": float(score),
                "detected": int(score >= threshold),
            })

    for file, score in zip(background_val, background_scores):
        validation_rows.append({
            "file": str(file),
            "type": "background",
            "speaker": "",
            "score_nuclea": float(score),
            "detected": int(score >= threshold),
        })

    with (OUTPUT_DIR / "threshold_sweep.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["threshold", "recall", "precision", "fpr", "tp", "fn", "fp", "tn"],
        )
        writer.writeheader()
        writer.writerows(sweep)

    with (OUTPUT_DIR / "validation_scores.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["file", "type", "speaker", "score_nuclea", "detected"],
        )
        writer.writeheader()
        writer.writerows(validation_rows)

    results = {
        "model": str(final_model),
        "baseline_model": "output_final_hardneg\\nuclea_final.keras",
        "threshold": threshold,
        "target_validation_fpr": TARGET_VALIDATION_FPR,
        "validation": {
            "real_samples": len(positive_scores),
            "background_samples": len(background_scores),
            "recall": best["recall"],
            "precision": best["precision"],
            "false_positive_rate": best["fpr"],
            "tp": best["tp"],
            "fn": best["fn"],
            "fp": best["fp"],
            "tn": best["tn"],
        },
        "per_speaker_validation": per_speaker,
        "counts": {
            "real_train": len(real_train),
            "synthetic_train": len(synthetic_train),
            "positive_train": len(positive_train_items),
            "clean_positive_train": clean_positive_count,
            "noisy_positive_train": noisy_positive_count,
            "background_train": len(negative_train),
            "hard_negative_train": len(hard_negative_train),
            "real_validation": len(real_val),
            "background_validation": len(background_val),
        },
        "noise_augmentation": {
            "enabled": True,
            "domain": "waveform_before_mfcc",
            "train_only": True,
            "noisy_positive_probability": NOISY_POSITIVE_PROBABILITY,
            "snr_db_range": list(SNR_DB_RANGE),
            "background_dirs": [str(path) for path in BACKGROUND_DIRS],
            "excluded_dirs": ["dataset/background_test2"],
            "manifest": str(OUTPUT_DIR / "positive_training_manifest.csv"),
        },
        "speaker_split": split_info,
        "mfcc": {
            "sample_rate": SAMPLE_RATE,
            "num_samples": NUM_SAMPLES,
            "n_mfcc": N_MFCC,
            "n_fft": N_FFT,
            "win_length": WIN_LENGTH,
            "hop_length": HOP_LENGTH,
            "n_mels": N_MELS,
            "fmin": FMIN,
            "fmax": FMAX,
            "center": False,
            "max_frames": MAX_FRAMES,
        },
    }

    with (OUTPUT_DIR / "results_final.json").open("w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print()
    print("=" * 72)
    print("MODELO NOISE ROBUST V1 GERADO")
    print("=" * 72)
    print(f"Modelo:    {final_model}")
    print(f"Threshold: {threshold:.2f}")
    print(f"Recall validação real: {best['recall'] * 100:.2f}%")
    print(f"Precision:             {best['precision'] * 100:.2f}%")
    print(f"FPR validação:         {best['fpr'] * 100:.2f}%")
    print(f"TP/FN: {best['tp']}/{best['fn']}")
    print(f"FP/TN: {best['fp']}/{best['tn']}")


if __name__ == "__main__":
    main()
