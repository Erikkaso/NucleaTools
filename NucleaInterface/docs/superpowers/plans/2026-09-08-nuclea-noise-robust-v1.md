# Núclea Noise Robust v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a new wake-word training candidate that improves “Núclea” robustness by adding train-only waveform-domain background mixing for positive samples.

**Architecture:** Keep the current MFCC contract, CNN architecture, validation split, INT8 conversion path, and ESP32 firmware untouched. Add a focused augmentation utility and a new training entrypoint that writes to `wake-word/output_noise_robust_v1/`, then compare it against the current `output_final_hardneg` baseline.

**Tech Stack:** Python, NumPy, librosa, TensorFlow/Keras, unittest, TFLite INT8.

**Spec:** User-approved audit/proposal from 2026-09-08: train-only positive waveform background augmentation, 40–60% clean/noisy mix, SNR 10–30 dB, no `background_test2` for training/threshold, no ESP32/MFCC changes in this stage.

## Global Constraints

- Do not modify ESP32 firmware or frontend MFCC in this stage.
- Do not delete or recreate the dataset.
- Do not use `dataset/background_test2` for training, validation, threshold calibration, or representative quantization data.
- Preserve current model artifacts; write the new candidate under `wake-word/output_noise_robust_v1/`.
- Use TDD: every production behavior below must have a failing test before implementation.

---

### Task 1: Train-only waveform background mixer

**Files:**
- Create: `wake-word/noise_augmentation.py`
- Create: `wake-word/test_noise_augmentation.py`

**Interfaces:**
- Produces: `mix_at_snr(clean: np.ndarray, background: np.ndarray, snr_db: float) -> np.ndarray`
- Produces: `fit_or_crop_background(background: np.ndarray, num_samples: int, rng: random.Random) -> np.ndarray`
- Produces: `should_mix_positive(rng: random.Random, probability: float) -> bool`

- [ ] Write failing tests for SNR scaling, output length, deterministic background cropping, and clean/noisy probability boundaries.
- [ ] Run `python -m unittest wake-word/test_noise_augmentation.py` and verify failure because module/functions do not exist.
- [ ] Implement minimal utility functions in `noise_augmentation.py`.
- [ ] Re-run the unit test and verify pass.

### Task 2: New training pipeline using noise augmentation

**Files:**
- Create: `wake-word/train_noise_robust_v1.py`
- Modify: `wake-word/test_noise_augmentation.py`

**Interfaces:**
- Consumes: `noise_augmentation.mix_at_snr`
- Produces: `OUTPUT_DIR = Path("output_noise_robust_v1")`
- Produces: `NOISY_POSITIVE_PROBABILITY = 0.50`
- Produces: `SNR_DB_RANGE = (10.0, 30.0)`
- Produces: `build_positive_training_items(...)` returning train examples with optional background/SNR metadata.

- [ ] Write failing tests proving the new training config excludes `background_test2`, uses only train backgrounds for positive mixing, and records noisy positive metadata.
- [ ] Run the targeted tests and verify failure for missing training module/API.
- [ ] Implement `train_noise_robust_v1.py` from `train_final_hardneg.py` with waveform-domain positive augmentation before MFCC extraction.
- [ ] Re-run targeted tests and verify pass.

### Task 3: Train, evaluate, quantize, and compare

**Files:**
- Modify: `wake-word/convert_int8.py` only if needed to accept explicit `--model`, `--validation-csv`, `--results-json`, and `--output-dir` for the new artifact.
- Generated: `wake-word/output_noise_robust_v1/*`
- Generated: `wake-word/output_noise_robust_v1_int8/*`

**Interfaces:**
- Consumes: `wake-word/train_noise_robust_v1.py`
- Consumes: `wake-word/convert_int8.py`

- [ ] Run all wake-word unit tests.
- [ ] Train `train_noise_robust_v1.py`.
- [ ] Inspect `results_final.json` for counts, MFCC contract, threshold, recall, precision, FPR, and noisy-positive metadata.
- [ ] Convert the new Keras model to TFLite INT8 into `output_noise_robust_v1_int8/`.
- [ ] Compare baseline `output_final_hardneg` metrics against new Keras/INT8 metrics.
- [ ] Do not update ESP32 model files until explicitly requested after review.
