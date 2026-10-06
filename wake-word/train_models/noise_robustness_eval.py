from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path
from typing import Iterable

import librosa
import numpy as np
import tensorflow as tf

import train_final_hardneg as baseline
from noise_augmentation import fit_or_crop_background, mix_at_snr


DEFAULT_SNRS = [35, 30, 25, 20, 15, 10]


def load_threshold(results_json: Path) -> float:
    data = json.loads(
        results_json.read_text(encoding="utf-8"),
    )

    return float(data["threshold"])


def load_validation_files(
    validation_csv: Path,
) -> tuple[list[Path], list[Path]]:
    positives: list[Path] = []
    backgrounds: list[Path] = []

    with validation_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            raw_path = Path(str(row["file"]).replace("\\", "/"))
            row_type = row["type"]

            if row_type == "real_positive":
                positives.append(raw_path)
            elif row_type == "background":
                backgrounds.append(raw_path)

    return positives, backgrounds


def summarize_detection_scores(
    scores: Iterable[float],
    threshold: float,
) -> dict[str, float | int]:
    values = np.asarray(
        list(scores),
        dtype=np.float32,
    )

    if values.size == 0:
        return {
            "samples": 0,
            "detected": 0,
            "recall": 0.0,
            "mean_score": 0.0,
            "min_score": 0.0,
            "p10_score": 0.0,
            "max_score": 0.0,
        }

    detected = int(
        np.sum(values >= threshold),
    )

    return {
        "samples": int(values.size),
        "detected": detected,
        "recall": float(detected / values.size),
        "mean_score": float(np.mean(values)),
        "min_score": float(np.min(values)),
        "p10_score": float(np.percentile(values, 10)),
        "max_score": float(np.max(values)),
    }


def load_fixed_audio(path: Path) -> np.ndarray:
    audio, _ = librosa.load(
        path,
        sr=baseline.SAMPLE_RATE,
        mono=True,
    )

    audio = audio.astype(np.float32)

    if len(audio) < baseline.NUM_SAMPLES:
        return np.pad(
            audio,
            (0, baseline.NUM_SAMPLES - len(audio)),
        ).astype(np.float32)

    if len(audio) > baseline.NUM_SAMPLES:
        start = (len(audio) - baseline.NUM_SAMPLES) // 2

        return audio[start:start + baseline.NUM_SAMPLES].astype(np.float32)

    return audio


def mfcc_from_audio(audio: np.ndarray) -> np.ndarray:
    mfcc = librosa.feature.mfcc(
        y=audio.astype(np.float32),
        sr=baseline.SAMPLE_RATE,
        n_mfcc=baseline.N_MFCC,
        n_fft=baseline.N_FFT,
        win_length=baseline.WIN_LENGTH,
        hop_length=baseline.HOP_LENGTH,
        n_mels=baseline.N_MELS,
        fmin=baseline.FMIN,
        fmax=baseline.FMAX,
        center=False,
    )

    if mfcc.shape[1] < baseline.MAX_FRAMES:
        mfcc = np.pad(
            mfcc,
            (
                (0, 0),
                (0, baseline.MAX_FRAMES - mfcc.shape[1]),
            ),
        )

    return mfcc[:, :baseline.MAX_FRAMES].astype(np.float32)


def score_audio_batch(
    model: tf.keras.Model,
    audios: list[np.ndarray],
) -> np.ndarray:
    if not audios:
        return np.asarray([], dtype=np.float32)

    features = np.asarray(
        [
            mfcc_from_audio(audio)
            for audio in audios
        ],
        dtype=np.float32,
    )

    return model.predict(
        np.expand_dims(features, -1),
        batch_size=256,
        verbose=0,
    )[:, 1]


def evaluate_model_robustness(
    model_path: Path,
    threshold: float,
    positive_files: list[Path],
    background_files: list[Path],
    snrs: list[int],
    seed: int = 42,
) -> dict[str, object]:
    model = tf.keras.models.load_model(model_path)
    rng = random.Random(seed)

    clean_audios = [
        load_fixed_audio(path)
        for path in positive_files
    ]
    background_audios = [
        load_fixed_audio(path)
        for path in background_files
    ]

    clean_scores = score_audio_batch(
        model,
        clean_audios,
    )

    levels: dict[str, object] = {
        "clean": summarize_detection_scores(
            clean_scores,
            threshold,
        ),
    }

    shuffled_backgrounds = list(background_audios)
    rng.shuffle(shuffled_backgrounds)

    for snr in snrs:
        mixed: list[np.ndarray] = []

        for index, clean_audio in enumerate(clean_audios):
            background = shuffled_backgrounds[
                index % len(shuffled_backgrounds)
            ]
            cropped = fit_or_crop_background(
                background,
                baseline.NUM_SAMPLES,
                rng,
            )
            mixed.append(
                mix_at_snr(
                    clean_audio,
                    cropped,
                    snr,
                ),
            )

        scores = score_audio_batch(
            model,
            mixed,
        )
        levels[f"{snr}dB"] = summarize_detection_scores(
            scores,
            threshold,
        )

    return {
        "model": str(model_path),
        "threshold": threshold,
        "positive_samples": len(positive_files),
        "background_samples": len(background_files),
        "snrs_db": snrs,
        "levels": levels,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Avalia recall da wake word clean e com ruído em SNRs "
            "controlados usando positivos/backgrounds de validação."
        ),
    )
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--results-json", type=Path)
    parser.add_argument(
        "--validation-csv",
        type=Path,
        default=Path("output_final_hardneg/validation_scores.csv"),
    )
    parser.add_argument(
        "--snrs",
        nargs="*",
        type=int,
        default=DEFAULT_SNRS,
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    if args.threshold is None:
        if args.results_json is None:
            raise SystemExit(
                "Informe --threshold ou --results-json.",
            )

        threshold = load_threshold(args.results_json)
    else:
        threshold = float(args.threshold)

    positives, backgrounds = load_validation_files(
        args.validation_csv,
    )

    if not positives:
        raise SystemExit(
            "Nenhum real_positive encontrado no CSV de validação.",
        )
    if not backgrounds:
        raise SystemExit(
            "Nenhum background encontrado no CSV de validação.",
        )

    result = evaluate_model_robustness(
        model_path=args.model,
        threshold=threshold,
        positive_files=positives,
        background_files=backgrounds,
        snrs=list(args.snrs),
        seed=args.seed,
    )

    args.output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    args.output.write_text(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            result["levels"],
            indent=2,
            ensure_ascii=False,
        ),
    )


if __name__ == "__main__":
    main()
