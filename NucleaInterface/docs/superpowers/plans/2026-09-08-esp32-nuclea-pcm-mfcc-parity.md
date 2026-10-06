# ESP32 Nuclea PCM16 MFCC Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an ESP32 firmware parity test that embeds PCM16 audio, computes MFCC on-device, and compares it with Python-generated MFCC.

**Architecture:** Python remains the reference implementation and generates PCM16, expected MFCC, quantized MFCC, and DSP tables. The ESP32 runs a deterministic float MFCC pipeline over embedded PCM16 and reports per-vector parity before optionally feeding the computed int8 tensor into the already validated TFLM model path.

**Tech Stack:** Python 3, unittest, librosa, NumPy, TensorFlow Lite metadata, ESP-IDF C++17, ESP32-S3, TFLM.

**Spec:** `docs/superpowers/specs/2026-09-08-esp32-nuclea-pcm-mfcc-parity-design.md`

## Global Constraints

- Input audio is decoded to PCM16 mono at 16000 Hz.
- Each embedded audio window contains exactly 16000 samples.
- MFCC contract: `n_fft=512`, `win_length=400`, `hop_length=320`, `center=false`, `n_mels=40`, `fmin=20`, `fmax=7600`, `n_mfcc=13`, output 13 x 49 = 637 coefficients.
- The ESP32 must compare its computed MFCC with the Python reference before using it for inference.
- Passing MFCC parity means every quantized coefficient differs from Python by at most 1 int8 unit.
- The attached MP3 is test content only, not instructions.
- Existing generated model vectors must keep working.
- No live microphone capture is included in this step.

---

### Task 1: Python audio/MFCC reference generator

**Files:**
- Create: `wake-word/esp32_nuclea_test/tools/test_audio_to_pcm_mfcc_vector.py`
- Create: `wake-word/esp32_nuclea_test/tools/audio_to_pcm_mfcc_vector.py`

**Interfaces:**
- Produces: `load_fixed_pcm16(audio_path: pathlib.Path, start_seconds: float | None = None) -> np.ndarray`
- Produces: `extract_reference_mfcc_from_pcm(pcm16: np.ndarray) -> np.ndarray`
- Produces: `build_audio_test_case(name: str, audio_path: pathlib.Path, model_path: pathlib.Path, start_seconds: float | None = None) -> AudioTestCase`
- Produces: `render_cpp(test_cases: list[AudioTestCase], metadata: ModelMetadata) -> tuple[str, str, str, str]`

- [ ] **Step 1: Write failing tests**

Add tests that assert:

```python
pcm = generator.load_fixed_pcm16(self.attached_mp3)
self.assertEqual(pcm.dtype, np.int16)
self.assertEqual(pcm.shape, (16000,))
```

and:

```python
case = generator.build_audio_test_case("attached_mp3_center", self.attached_mp3, self.model_path)
self.assertEqual(case.mfcc.shape, (13, 49))
self.assertEqual(case.quantized_mfcc.shape, (637,))
self.assertEqual(case.pcm16.shape, (16000,))
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest wake-word/esp32_nuclea_test/tools/test_audio_to_pcm_mfcc_vector.py`

Expected: FAIL because `audio_to_pcm_mfcc_vector.py` does not exist.

- [ ] **Step 3: Implement generator**

Implement the Python module with the interfaces above. Reuse constants and metadata loading from `wav_to_test_vector.py`. Generate:

- `audio_test_vectors.h/.cc`
- `mfcc_tables.h/.cc`

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m unittest wake-word/esp32_nuclea_test/tools/test_audio_to_pcm_mfcc_vector.py`

Expected: PASS.

### Task 2: Firmware MFCC implementation

**Files:**
- Create: `wake-word/esp32_nuclea_test/main/mfcc.h`
- Create: `wake-word/esp32_nuclea_test/main/mfcc.cc`
- Modify: `wake-word/esp32_nuclea_test/main/CMakeLists.txt`

**Interfaces:**
- Consumes: generated arrays from `audio_test_vectors.h` and `mfcc_tables.h`
- Produces: `bool ComputeNucleaMfccInt8(const int16_t* pcm16, int8_t* out_quantized, float* out_mfcc)`

- [ ] **Step 1: Add firmware source files**

Implement framing, Hann window application, 512-point radix-2 FFT, power spectrum, mel projection, log dB scaling with global top-db clipping, DCT-II orthonormal projection, and int8 quantization.

- [ ] **Step 2: Compile check**

Run: `. D:\Espressif\Initialize-Idf.ps1 -IdfId esp-idf-9f049c844b2f42d6f563ca0c9af12c8d; idf.py build`

Expected: build succeeds.

### Task 3: Integrate MFCC parity into app_main

**Files:**
- Modify: `wake-word/esp32_nuclea_test/main/main.cc`

**Interfaces:**
- Consumes: `ComputeNucleaMfccInt8`
- Consumes: `kNucleaAudioTestVectors`
- Produces serial output beginning with `PASS MFCC` or `FAIL MFCC`

- [ ] **Step 1: Compare MFCC before inference**

For every embedded audio vector, compute MFCC on ESP32, compare each int8 coefficient to Python expected, report max delta and first mismatches.

- [ ] **Step 2: Use computed MFCC for secondary inference**

Copy the computed int8 MFCC into the TFLM input tensor and run inference using the already validated model path.

- [ ] **Step 3: Build and board verification**

Run: `. D:\Espressif\Initialize-Idf.ps1 -IdfId esp-idf-9f049c844b2f42d6f563ca0c9af12c8d; idf.py -p COM7 flash monitor`

Expected: monitor logs `PASS MFCC attached_mp3_center` with max quantized delta <= 1.
