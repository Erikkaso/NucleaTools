from __future__ import annotations

import math
import random

import numpy as np


def rms(audio: np.ndarray) -> float:
    data = np.asarray(audio, dtype=np.float32)

    if data.size == 0:
        return 0.0

    return float(
        np.sqrt(
            np.mean(
                np.square(
                    data.astype(np.float64),
                ),
            ),
        ),
    )


def fit_or_crop_background(
    background: np.ndarray,
    num_samples: int,
    rng: random.Random,
) -> np.ndarray:
    if num_samples <= 0:
        raise ValueError("num_samples precisa ser positivo.")

    data = np.asarray(background, dtype=np.float32)

    if data.size == 0:
        raise ValueError("background não pode estar vazio.")

    if data.size == num_samples:
        return data.copy()

    if data.size < num_samples:
        repeats = math.ceil(num_samples / data.size)

        return np.tile(data, repeats)[:num_samples].astype(np.float32)

    max_start = data.size - num_samples
    start = rng.randint(0, max_start)

    return data[start:start + num_samples].astype(np.float32)


def mix_at_snr(
    clean: np.ndarray,
    background: np.ndarray,
    snr_db: float,
) -> np.ndarray:
    clean_audio = np.asarray(clean, dtype=np.float32)
    background_audio = np.asarray(background, dtype=np.float32)

    if clean_audio.shape != background_audio.shape:
        raise ValueError("clean e background precisam ter o mesmo shape.")

    clean_rms = rms(clean_audio)
    background_rms = rms(background_audio)

    if background_rms <= 0.0:
        return clean_audio.copy()

    target_background_rms = clean_rms / (10.0 ** (float(snr_db) / 20.0))
    scaled_background = background_audio * (target_background_rms / background_rms)

    mixed = clean_audio + scaled_background.astype(np.float32)

    return np.clip(mixed, -1.0, 1.0).astype(np.float32)


def should_mix_positive(
    rng: random.Random,
    probability: float,
) -> bool:
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability precisa estar entre 0.0 e 1.0.")

    return rng.random() < probability
