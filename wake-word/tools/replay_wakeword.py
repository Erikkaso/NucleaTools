from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import librosa
import numpy as np
import tensorflow as tf


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "train_models"))
from score_analysis import extract_mfcc_from_audio


SAMPLE_RATE = 16_000
WINDOW_SAMPLES = 16_000


def audio_result_key(audio_path: Path) -> str:
    return audio_path.as_posix()


def window_starts(
    total_samples: int,
    window_samples: int,
    stride_samples: int,
) -> list[int]:
    if window_samples <= 0 or stride_samples <= 0:
        raise ValueError("window_samples e stride_samples precisam ser positivos")
    return list(range(0, total_samples - window_samples + 1, stride_samples))


def detection_events(
    scores: list[float],
    timestamps_ms: list[int],
    threshold: float,
    high_threshold: float,
    cooldown_ms: int,
) -> list[dict]:
    history: list[bool] = []
    last_detection_ms = -cooldown_ms
    events: list[dict] = []

    for score, now_ms in zip(scores, timestamps_ms):
        history.append(score >= threshold)
        history = history[-3:]
        if now_ms - last_detection_ms < cooldown_ms:
            continue

        reason = ""
        if score >= high_threshold:
            reason = "high_confidence"
        elif sum(history) >= 2:
            reason = "two_of_three"

        if reason:
            events.append({
                "time_ms": now_ms,
                "score": round(float(score), 6),
                "reason": reason,
            })
            last_detection_ms = now_ms

    return events


def score_audio(
    model: tf.keras.Model,
    audio_path: Path,
    stride_samples: int,
) -> tuple[list[float], list[int]]:
    audio, _ = librosa.load(audio_path, sr=SAMPLE_RATE, mono=True)
    starts = window_starts(len(audio), WINDOW_SAMPLES, stride_samples)
    if not starts:
        return [], []

    features = np.asarray(
        [
            extract_mfcc_from_audio(audio[start:start + WINDOW_SAMPLES])
            for start in starts
        ],
        dtype=np.float32,
    )
    scores = model.predict(
        np.expand_dims(features, axis=-1),
        batch_size=256,
        verbose=0,
    )[:, 1]
    timestamps_ms = [round(start * 1000 / SAMPLE_RATE) for start in starts]
    return scores.astype(np.float32).tolist(), timestamps_ms


def summarize(scores: list[float], events: list[dict]) -> dict:
    values = np.asarray(scores, dtype=np.float32)
    if not len(values):
        return {"windows": 0, "events": 0}
    return {
        "windows": int(len(values)),
        "events": len(events),
        "mean_score": float(np.mean(values)),
        "p99_score": float(np.percentile(values, 99)),
        "max_score": float(np.max(values)),
        "event_samples": events[:20],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduz streams de audio com a mesma janela de 1 s do wakeword.",
    )
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--audio", required=True, type=Path, action="append")
    parser.add_argument("--threshold", required=True, type=float)
    parser.add_argument("--high-threshold", required=True, type=float)
    parser.add_argument("--stride-ms", required=True, type=int, action="append")
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model = tf.keras.models.load_model(args.model)
    result = {
        "model": str(args.model),
        "threshold": args.threshold,
        "high_threshold": args.high_threshold,
        "window_ms": 1000,
        "strides": {},
    }

    for stride_ms in args.stride_ms:
        if stride_ms <= 0:
            raise ValueError("stride-ms precisa ser positivo")
        stride_samples = SAMPLE_RATE * stride_ms // 1000
        runs = {}
        for audio_path in args.audio:
            scores, timestamps_ms = score_audio(model, audio_path, stride_samples)
            events = detection_events(
                scores=scores,
                timestamps_ms=timestamps_ms,
                threshold=args.threshold,
                high_threshold=args.high_threshold,
                cooldown_ms=2_000,
            )
            runs[audio_result_key(audio_path)] = summarize(scores, events)
        result["strides"][str(stride_ms)] = runs

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
