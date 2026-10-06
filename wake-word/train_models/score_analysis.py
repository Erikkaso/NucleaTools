from __future__ import annotations

from pathlib import Path
import argparse
import csv
import json

import librosa
import numpy as np
import tensorflow as tf

import train_final_hardneg as baseline


SAMPLE_RATE = baseline.SAMPLE_RATE
WINDOW_SAMPLES = baseline.NUM_SAMPLES
HOP_SECONDS = 0.25
HOP_SAMPLES = int(SAMPLE_RATE * HOP_SECONDS)


def summarize_scores(
    scores: np.ndarray,
    threshold: float,
) -> dict:
    values = np.asarray(scores, dtype=np.float32)

    if values.size == 0:
        return {
            "windows": 0,
            "mean": 0.0,
            "median": 0.0,
            "p95": 0.0,
            "p99": 0.0,
            "max": 0.0,
            "above_threshold": 0,
        }

    return {
        "windows": int(values.size),
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "p95": float(np.percentile(values, 95)),
        "p99": float(np.percentile(values, 99)),
        "max": float(np.max(values)),
        "above_threshold": int(np.sum(values >= threshold)),
    }


def top_score_windows(
    scores: np.ndarray,
    hop_seconds: float,
    limit: int,
) -> list[dict]:
    values = np.asarray(scores, dtype=np.float32)
    indexes = np.argsort(values)[::-1][:limit]

    return [
        {
            "index": int(index),
            "time_seconds": float(index * hop_seconds),
            "score": float(values[index]),
        }
        for index in indexes
    ]


def extract_mfcc_from_audio(audio: np.ndarray) -> np.ndarray:
    mfcc = baseline.librosa.feature.mfcc(
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


def score_files(
    model: tf.keras.Model,
    files: list[Path],
) -> np.ndarray:
    if not files:
        return np.asarray([], dtype=np.float32)

    features = [
        baseline.extract_mfcc(path)
        for path in files
    ]
    X = np.expand_dims(
        np.asarray(features, dtype=np.float32),
        -1,
    )

    return model.predict(X, batch_size=256, verbose=0)[:, 1]


def score_long_audio(
    model: tf.keras.Model,
    audio_path: Path,
) -> np.ndarray:
    audio, _ = librosa.load(
        audio_path,
        sr=SAMPLE_RATE,
        mono=True,
    )
    audio = audio.astype(np.float32)

    features = []

    for start in range(0, len(audio) - WINDOW_SAMPLES + 1, HOP_SAMPLES):
        frame = audio[start:start + WINDOW_SAMPLES]
        features.append(extract_mfcc_from_audio(frame))

    if not features:
        return np.asarray([], dtype=np.float32)

    X = np.expand_dims(
        np.asarray(features, dtype=np.float32),
        -1,
    )

    return model.predict(X, batch_size=256, verbose=0)[:, 1]


def load_validation_background_files(validation_csv: Path) -> list[Path]:
    files = []

    with validation_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            if row["type"] != "background":
                continue

            raw = Path(row["file"])
            candidate = validation_csv.parent.parent / raw
            files.append(candidate if candidate.exists() else raw)

    return files


def write_analysis(
    output_path: Path,
    analysis: dict,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def analyze_model(
    model_path: Path,
    threshold: float,
) -> dict:
    model = tf.keras.models.load_model(model_path)
    baseline.FEATURE_CACHE.clear()

    groups = {
        "validation_background": {
            "kind": "files",
            "files": load_validation_background_files(
                Path("output_final_hardneg/validation_scores.csv"),
            ),
        },
        "hard_negatives": {
            "kind": "files",
            "files": baseline.wavs(Path("dataset/background_hard_negative/generated")),
        },
        "external_conversation": {
            "kind": "long_audio",
            "path": Path("dataset/background_test2/conversanew.mp3"),
        },
        "external_music": {
            "kind": "long_audio",
            "path": Path("dataset/background_test2/musicanew.wav"),
        },
        "external_ambient": {
            "kind": "long_audio",
            "path": Path("dataset/background_test2/ambientenew.wav"),
        },
        "external_calm": {
            "kind": "long_audio",
            "path": Path("dataset/background_test2/calmonew.wav"),
        },
    }

    result = {}

    for name, group in groups.items():
        if group["kind"] == "files":
            scores = score_files(model, group["files"])
        else:
            scores = score_long_audio(model, group["path"])

        result[name] = {
            **summarize_scores(scores, threshold),
            "top10": top_score_windows(scores, HOP_SECONDS, 10),
        }

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--threshold", required=True, type=float)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    write_analysis(
        args.output,
        analyze_model(args.model, args.threshold),
    )

    print(f"Análise salva em {args.output}")


if __name__ == "__main__":
    main()
