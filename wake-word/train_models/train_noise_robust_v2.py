from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import argparse
import csv
import json
import random

import numpy as np
import tensorflow as tf
from sklearn.utils.class_weight import compute_class_weight

import train_final_hardneg as baseline
import train_noise_robust_v1 as v1
from noise_augmentation import should_mix_positive


SEED = baseline.SEED

REAL_SPEAKERS = baseline.REAL_SPEAKERS
SYNTHETIC_DIRS = baseline.SYNTHETIC_DIRS
BACKGROUND_DIRS = baseline.BACKGROUND_DIRS
HARD_NEGATIVE_DIRS = baseline.HARD_NEGATIVE_DIRS

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

REAL_VAL_FRACTION = baseline.REAL_VAL_FRACTION
BACKGROUND_VAL_FRACTION = baseline.BACKGROUND_VAL_FRACTION
SYNTHETIC_TO_REAL_RATIO = baseline.SYNTHETIC_TO_REAL_RATIO
TARGET_VALIDATION_FPR = baseline.TARGET_VALIDATION_FPR
MAX_EPOCHS = baseline.MAX_EPOCHS
BATCH_SIZE = baseline.BATCH_SIZE


@dataclass(frozen=True)
class ExperimentConfig:
    name: str
    output_dir: Path
    noisy_positive_probability: float
    snr_db_range: tuple[float, float]
    positive_background_dirs: list[Path]
    voice_positive_weight: float = 0.0
    voice_negative_oversample: int = 1
    hard_negative_oversample: int = 1
    temporal_offsets_samples: tuple[int, ...] = (0,)


def get_experiment_config(variant: str) -> ExperimentConfig:
    name = variant.lower()
    non_vocal_backgrounds = [
        Path("dataset/background_noise"),
        Path("dataset/background_silence/generated/room"),
    ]

    if name == "v2a":
        return ExperimentConfig(
            name=name,
            output_dir=Path("output/output_noise_robust_v2a"),
            noisy_positive_probability=0.25,
            snr_db_range=(20.0, 35.0),
            positive_background_dirs=non_vocal_backgrounds,
        )

    if name == "v2b":
        return ExperimentConfig(
            name=name,
            output_dir=Path("output/output_noise_robust_v2b"),
            noisy_positive_probability=0.35,
            snr_db_range=(20.0, 35.0),
            positive_background_dirs=non_vocal_backgrounds + [
                Path("dataset/background_voice"),
            ],
            voice_positive_weight=0.15,
        )

    if name == "v2c":
        return ExperimentConfig(
            name=name,
            output_dir=Path("output/output_noise_robust_v2c"),
            noisy_positive_probability=0.35,
            snr_db_range=(20.0, 35.0),
            positive_background_dirs=non_vocal_backgrounds + [
                Path("dataset/background_voice"),
            ],
            voice_positive_weight=0.15,
            voice_negative_oversample=2,
            hard_negative_oversample=3,
        )

    if name == "v2d":
        return ExperimentConfig(
            name=name,
            output_dir=Path("output/output_noise_robust_v2d_temporal"),
            noisy_positive_probability=0.35,
            snr_db_range=(20.0, 35.0),
            positive_background_dirs=non_vocal_backgrounds + [
                Path("dataset/background_voice"),
            ],
            voice_positive_weight=0.15,
            voice_negative_oversample=2,
            hard_negative_oversample=3,
            temporal_offsets_samples=(-3200, 0, 3200),
        )

    if name == "v2e":
        return ExperimentConfig(
            name=name,
            output_dir=Path("output/output_noise_robust_v2e_inmp441"),
            noisy_positive_probability=0.35,
            snr_db_range=(20.0, 35.0),
            positive_background_dirs=non_vocal_backgrounds + [
                Path("dataset/background_voice"),
            ],
            voice_positive_weight=0.15,
            voice_negative_oversample=2,
            hard_negative_oversample=3,
            temporal_offsets_samples=(-3200, 0, 3200),
        )

    if name == "v2f":
        return ExperimentConfig(
            name=name,
            output_dir=Path("output/output_noise_robust_v2f_dialogue"),
            noisy_positive_probability=0.55,
            snr_db_range=(10.0, 25.0),
            positive_background_dirs=non_vocal_backgrounds + [
                Path("dataset/background_voice"),
            ],
            voice_positive_weight=0.35,
            voice_negative_oversample=3,
            hard_negative_oversample=3,
            temporal_offsets_samples=(-4800, -3200, 0, 3200, 4800),
        )

    if name == "v2g":
        return ExperimentConfig(
            name=name,
            output_dir=Path("output/output_noise_robust_v2g_replay_hardneg"),
            noisy_positive_probability=0.55,
            snr_db_range=(10.0, 25.0),
            positive_background_dirs=non_vocal_backgrounds + [
                Path("dataset/background_voice"),
            ],
            voice_positive_weight=0.35,
            voice_negative_oversample=5,
            hard_negative_oversample=8,
            temporal_offsets_samples=(-4800, -3200, 0, 3200, 4800),
        )

    raise ValueError(f"Variante desconhecida: {variant}")


def path_is_under(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def filter_paths_by_dirs(
    paths: list[Path],
    directories: list[Path],
) -> list[Path]:
    return [
        path
        for path in paths
        if any(path_is_under(path, directory) for directory in directories)
    ]


def choose_positive_background(
    candidates: list[v1.AudioExample],
    voice_positive_weight: float,
    rng: random.Random,
) -> v1.AudioExample:
    voice = [
        example
        for example in candidates
        if "background_voice" in Path(example.path).as_posix()
    ]
    non_voice = [
        example
        for example in candidates
        if "background_voice" not in Path(example.path).as_posix()
    ]

    if voice and non_voice and rng.random() < voice_positive_weight:
        return rng.choice(voice)

    if non_voice:
        return rng.choice(non_voice)

    return rng.choice(candidates)


def build_positive_training_items(
    positives: list[v1.AudioExample],
    train_backgrounds: list[v1.AudioExample],
    validation_backgrounds: list[v1.AudioExample],
    config: ExperimentConfig,
    rng: random.Random,
) -> list[v1.PositiveTrainingItem]:
    validation_paths = {
        str(example.path)
        for example in validation_backgrounds
    }
    candidates = [
        example
        for example in train_backgrounds
        if str(example.path) not in validation_paths
        and any(
            path_is_under(
                Path(example.path),
                directory,
            )
            for directory in config.positive_background_dirs
        )
    ]

    if config.noisy_positive_probability > 0.0 and not candidates:
        raise RuntimeError(
            f"{config.name}: nenhum background permitido para positive augmentation."
        )

    items: list[v1.PositiveTrainingItem] = []

    for positive in positives:
        if should_mix_positive(rng, config.noisy_positive_probability):
            background = choose_positive_background(
                candidates,
                config.voice_positive_weight,
                rng,
            )
            snr_db = rng.uniform(*config.snr_db_range)
            items.append(
                v1.PositiveTrainingItem(
                    path=positive.path,
                    source=positive.source,
                    background_path=background.path,
                    snr_db=float(snr_db),
                ),
            )
        else:
            items.append(
                v1.PositiveTrainingItem(
                    path=positive.path,
                    source=positive.source,
                ),
            )

    return items


def oversample_negatives(
    background_train: list[Path],
    hard_negative_train: list[Path],
    config: ExperimentConfig,
) -> list[Path]:
    voice_backgrounds = [
        path
        for path in background_train
        if "background_voice" in path.as_posix()
    ]
    other_backgrounds = [
        path
        for path in background_train
        if "background_voice" not in path.as_posix()
    ]

    return sorted(other_backgrounds) + (
        sorted(voice_backgrounds) * config.voice_negative_oversample
    ) + (
        sorted(hard_negative_train) * config.hard_negative_oversample
    )


def add_temporal_variants(
    items: list[v1.PositiveTrainingItem],
    offsets_samples: tuple[int, ...],
) -> list[v1.PositiveTrainingItem]:
    return [
        v1.PositiveTrainingItem(
            path=item.path,
            source=item.source,
            background_path=item.background_path,
            snr_db=item.snr_db,
            time_shift_samples=offset,
        )
        for item in items
        for offset in offsets_samples
    ]


def load_training_split():
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

    synthetic_all: list[Path] = []
    for directory in SYNTHETIC_DIRS:
        synthetic_all.extend(baseline.wavs(directory))
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

    background_all: list[Path] = []
    for directory in BACKGROUND_DIRS:
        background_all.extend(baseline.wavs(directory))
    background_all = sorted(set(background_all))
    background_train, background_val = baseline.split_files(
        background_all,
        BACKGROUND_VAL_FRACTION,
        SEED + 2000,
    )

    hard_negative_train: list[Path] = []
    for directory in HARD_NEGATIVE_DIRS:
        hard_negative_train.extend(baseline.wavs(directory))
    hard_negative_train = sorted(set(hard_negative_train))

    return {
        "real_train": real_train,
        "real_val": real_val,
        "synthetic_train": synthetic_train,
        "background_train": background_train,
        "background_val": background_val,
        "hard_negative_train": hard_negative_train,
        "val_by_speaker": val_by_speaker,
        "split_info": split_info,
    }


def write_training_manifest(
    items: list[v1.PositiveTrainingItem],
    negative_train: list[Path],
    output_dir: Path,
) -> dict:
    v1.write_positive_training_manifest(
        items,
        output_dir / "positive_training_manifest.csv",
    )

    with (output_dir / "negative_training_manifest.csv").open(
        "w",
        newline="",
        encoding="utf-8",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["file", "source"],
        )
        writer.writeheader()

        for path in negative_train:
            source = "background_voice" if "background_voice" in path.as_posix() else "background"
            if any(path == hard_path for hard_path in baseline.wavs(Path("dataset/background_hard_negative/generated"))):
                source = "hard_negative"
            writer.writerow({
                "file": str(path),
                "source": source,
            })

    noisy_items = [
        item
        for item in items
        if item.background_path is not None
    ]
    source_counts: dict[str, int] = {}
    snrs = []

    for item in noisy_items:
        background = Path(item.background_path)
        parent = background.parent.as_posix()
        source_counts[parent] = source_counts.get(parent, 0) + 1

        if item.snr_db is not None:
            snrs.append(float(item.snr_db))

    return {
        "clean_positive_train": len(items) - len(noisy_items),
        "noisy_positive_train": len(noisy_items),
        "positive_background_source_counts": source_counts,
        "snr_min": min(snrs) if snrs else None,
        "snr_mean": float(np.mean(snrs)) if snrs else None,
        "snr_max": max(snrs) if snrs else None,
    }


def train_variant(config: ExperimentConfig):
    config.output_dir.mkdir(parents=True, exist_ok=True)
    v1.FEATURE_CACHE.clear()
    baseline.FEATURE_CACHE.clear()

    random.seed(SEED)
    np.random.seed(SEED)
    tf.random.set_seed(SEED)

    split = load_training_split()

    positive_examples = [
        v1.AudioExample(path=path, source="real_train")
        for path in split["real_train"]
    ] + [
        v1.AudioExample(path=path, source="synthetic_train")
        for path in split["synthetic_train"]
    ]

    positive_items = build_positive_training_items(
        positives=positive_examples,
        train_backgrounds=[
            v1.AudioExample(path=path, source="background_train")
            for path in split["background_train"]
        ],
        validation_backgrounds=[
            v1.AudioExample(path=path, source="background_validation")
            for path in split["background_val"]
        ],
        config=config,
        rng=random.Random(SEED + 5000),
    )
    positive_items = add_temporal_variants(
        positive_items,
        config.temporal_offsets_samples,
    )
    validation_positive_items = add_temporal_variants(
        [
            v1.PositiveTrainingItem(path=path, source="real_validation")
            for path in split["real_val"]
        ],
        config.temporal_offsets_samples,
    )
    negative_train = oversample_negatives(
        split["background_train"],
        split["hard_negative_train"],
        config,
    )
    manifest_stats = write_training_manifest(
        positive_items,
        negative_train,
        config.output_dir,
    )

    print("=" * 72)
    print(f"NÚCLEA - {config.name.upper()}")
    print("=" * 72)
    print(f"Output: {config.output_dir}")
    print(f"Positivos: {len(positive_items)}")
    print(f"  limpos: {manifest_stats['clean_positive_train']}")
    print(f"  noisy:  {manifest_stats['noisy_positive_train']}")
    print(f"Negativos treino ponderados: {len(negative_train)}")
    print(f"Val real/background: {len(validation_positive_items)}/{len(split['background_val'])}")

    print("Extraindo MFCCs...")
    X_train, y_train = v1.make_xy(
        positive_items,
        negative_train,
        SEED + 3000,
    )
    X_val, y_val = v1.make_xy(
        validation_positive_items,
        split["background_val"],
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

    tf.keras.backend.clear_session()
    model = baseline.create_model()
    best_path = config.output_dir / "best.keras"
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
        tf.keras.callbacks.CSVLogger(config.output_dir / "history.csv"),
    ]

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
    final_model = config.output_dir / "nuclea_final.keras"
    model.save(final_model)

    positive_scores = v1.scores(model, validation_positive_items)
    background_scores = v1.scores(model, split["background_val"])
    sweep = baseline.threshold_sweep(positive_scores, background_scores)
    best = baseline.choose_threshold(sweep, TARGET_VALIDATION_FPR)
    threshold = float(best["threshold"])

    per_speaker = {}
    validation_rows = []

    for speaker, files in split["val_by_speaker"].items():
        speaker_scores = v1.scores(model, files)
        detected = int(np.sum(speaker_scores >= threshold))
        total = len(speaker_scores)
        per_speaker[speaker] = {
            "samples": total,
            "detected": detected,
            "missed": total - detected,
            "recall": detected / total if total else 0.0,
        }
        for file, score in zip(files, speaker_scores):
            validation_rows.append({
                "file": str(file),
                "type": "real_positive",
                "speaker": speaker,
                "score_nuclea": float(score),
                "detected": int(score >= threshold),
            })

    for file, score in zip(split["background_val"], background_scores):
        validation_rows.append({
            "file": str(file),
            "type": "background",
            "speaker": "",
            "score_nuclea": float(score),
            "detected": int(score >= threshold),
        })

    with (config.output_dir / "threshold_sweep.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["threshold", "recall", "precision", "fpr", "tp", "fn", "fp", "tn"],
        )
        writer.writeheader()
        writer.writerows(sweep)

    with (config.output_dir / "validation_scores.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["file", "type", "speaker", "score_nuclea", "detected"],
        )
        writer.writeheader()
        writer.writerows(validation_rows)

    results = {
        "model": str(final_model),
        "variant": config.name,
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
            "real_train": len(split["real_train"]),
            "synthetic_train": len(split["synthetic_train"]),
            "positive_train": len(positive_items),
            "background_train_weighted": len(negative_train),
            "background_train_unique": len(set(negative_train)),
            "hard_negative_train_unique": len(split["hard_negative_train"]),
            "real_validation": len(split["real_val"]),
            "temporal_validation": len(validation_positive_items),
            "background_validation": len(split["background_val"]),
            **manifest_stats,
        },
        "noise_augmentation": {
            "enabled": True,
            "domain": "waveform_before_mfcc",
            "train_only": True,
            "noisy_positive_probability": config.noisy_positive_probability,
            "snr_db_range": list(config.snr_db_range),
            "positive_background_dirs": [
                str(path)
                for path in config.positive_background_dirs
            ],
            "voice_positive_weight": config.voice_positive_weight,
            "voice_negative_oversample": config.voice_negative_oversample,
            "hard_negative_oversample": config.hard_negative_oversample,
            "temporal_offsets_samples": list(config.temporal_offsets_samples),
            "excluded_dirs": ["dataset/background_test2"],
            "positive_manifest": str(config.output_dir / "positive_training_manifest.csv"),
            "negative_manifest": str(config.output_dir / "negative_training_manifest.csv"),
        },
        "speaker_split": split["split_info"],
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

    with (config.output_dir / "results_final.json").open("w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("=" * 72)
    print(f"{config.name.upper()} GERADO")
    print("=" * 72)
    print(f"Modelo: {final_model}")
    print(f"Threshold: {threshold:.2f}")
    print(f"TP/FN: {best['tp']}/{best['fn']}")
    print(f"FP/TN: {best['fp']}/{best['tn']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "variant",
        choices=["v2a", "v2b", "v2c", "v2d", "v2e", "v2f", "v2g"],
    )
    args = parser.parse_args()

    train_variant(
        get_experiment_config(args.variant),
    )


if __name__ == "__main__":
    main()
