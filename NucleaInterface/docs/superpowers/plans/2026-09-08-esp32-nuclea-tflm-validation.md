# ESP32 Nuclea TFLM Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `wake-word/esp32_nuclea_test`, an ESP-IDF project that validates ESP32-S3 TensorFlow Lite Micro INT8 inference against desktop TensorFlow Lite for fixed MFCC vectors.

**Architecture:** Python generates quantized MFCC test vectors and desktop scores from real WAV files. Firmware embeds the existing model and generated vectors, checks the tensor contract, invokes TFLM, dequantizes class 1, and reports PASS/FAIL per vector.

**Tech Stack:** ESP-IDF 5.5, ESP32-S3, C++17, espressif/esp-tflite-micro, Python 3, unittest, numpy, librosa, TensorFlow Lite interpreter.

**Spec:** `docs/superpowers/specs/2026-09-08-esp32-nuclea-tflm-validation-design.md`

## Global Constraints

- Project path: `wake-word/esp32_nuclea_test`.
- Target: `esp32s3`.
- Model source: `wake-word/output_tflite_int8/nuclea_int8.tflite`.
- Existing generated model source: `wake-word/esp32_model/nuclea_model.{h,cc}`.
- Model SHA-256: `09f98fa19154dd20d2ce60f8c30ce6cf289c43ae947a964012f8a82f9590bc57`.
- Model size: `28624` bytes.
- Input: INT8 `[1, 13, 49, 1]`, 637 values, scale `3.1064834594726562`, zero point `76`.
- Output: INT8 `[1, 2]`, scale `0.00390625`, zero point `-128`.
- Positive-class index: `1`.
- Wake threshold: `0.31`.
- Tolerance: `0.00390625 + 0.000001`.
- MFCC training parameters: sample rate `16000`, samples `16000`, MFCC `13`, FFT `512`, window `400`, hop `320`, mels `40`, fmin `20`, fmax `7600`, center `False`, frames `49`.
- Selected positive WAV: `wake-word/dataset/real/wakeword_amo/detected_raw/raw_0000.wav`.
- Selected negative WAV: `wake-word/dataset/background_test/negative.wav`.
- Do not implement embedded PCM MFCC or live microphone capture in this stage.

---

## File Structure

- Create `wake-word/esp32_nuclea_test/CMakeLists.txt`: root ESP-IDF project declaration.
- Create `wake-word/esp32_nuclea_test/sdkconfig.defaults`: target and C++ defaults.
- Create `wake-word/esp32_nuclea_test/main/CMakeLists.txt`: firmware component source registration.
- Create `wake-word/esp32_nuclea_test/main/idf_component.yml`: `esp-tflite-micro` dependency.
- Copy into `wake-word/esp32_nuclea_test/main/nuclea_model.h`: model declaration from existing source.
- Copy into `wake-word/esp32_nuclea_test/main/nuclea_model.cc`: model bytes from existing source, unchanged.
- Create `wake-word/esp32_nuclea_test/tools/wav_to_test_vector.py`: desktop feature extraction, quantization, inference, and C++ fixture generation.
- Create `wake-word/esp32_nuclea_test/tools/test_wav_to_test_vector.py`: unittest coverage for generator behavior.
- Generate `wake-word/esp32_nuclea_test/main/test_vectors.h`: immutable vector interface.
- Generate `wake-word/esp32_nuclea_test/main/test_vectors.cc`: immutable generated vector data.
- Create `wake-word/esp32_nuclea_test/main/main.cc`: TFLM setup, contract checks, invocation, comparison, serial output.
- Create `wake-word/esp32_nuclea_test/test-results/`: board evidence directory.

## Task 1: Project Skeleton And Model Copy

**Files:**
- Create: `wake-word/esp32_nuclea_test/CMakeLists.txt`
- Create: `wake-word/esp32_nuclea_test/sdkconfig.defaults`
- Create: `wake-word/esp32_nuclea_test/main/CMakeLists.txt`
- Create: `wake-word/esp32_nuclea_test/main/idf_component.yml`
- Create: `wake-word/esp32_nuclea_test/main/nuclea_model.h`
- Create: `wake-word/esp32_nuclea_test/main/nuclea_model.cc`
- Create: `wake-word/esp32_nuclea_test/test-results/.gitkeep`

**Interfaces:**
- Consumes: `wake-word/esp32_model/nuclea_model.{h,cc}`.
- Produces: ESP-IDF project scaffold and `extern const unsigned char nuclea_model[]; extern const unsigned int nuclea_model_len;`.

- [x] **Step 1: Create ESP-IDF files**

```cmake
cmake_minimum_required(VERSION 3.16)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(esp32_nuclea_test)
```

```ini
CONFIG_IDF_TARGET="esp32s3"
CONFIG_COMPILER_CXX_EXCEPTIONS=n
CONFIG_COMPILER_CXX_RTTI=n
CONFIG_ESP_MAIN_TASK_STACK_SIZE=8192
```

- [x] **Step 2: Register firmware component**

```cmake
idf_component_register(
    SRCS
        "main.cc"
        "nuclea_model.cc"
        "test_vectors.cc"
    INCLUDE_DIRS "."
)
target_compile_features(${COMPONENT_LIB} PRIVATE cxx_std_17)
```

```yaml
dependencies:
  espressif/esp-tflite-micro: "*"
```

- [x] **Step 3: Copy model source unchanged**

Copy `wake-word/esp32_model/nuclea_model.h` and `wake-word/esp32_model/nuclea_model.cc` into `wake-word/esp32_nuclea_test/main/`.

- [x] **Step 4: Verify scaffold files exist**

Run: `Get-ChildItem wake-word\esp32_nuclea_test -Recurse -File`
Expected: all seven files above are present.

## Task 2: Generator Tests RED

**Files:**
- Create: `wake-word/esp32_nuclea_test/tools/test_wav_to_test_vector.py`

**Interfaces:**
- Consumes: wished-for module `wav_to_test_vector`.
- Produces: tests for `load_model_metadata(model_path)`, `build_test_case(name, wav_path, model_path)`, and `render_cpp(test_cases, metadata)`.

- [x] **Step 1: Write failing unittest**

```python
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOLS = pathlib.Path(__file__).resolve().parent

spec = importlib.util.spec_from_file_location("wav_to_test_vector", TOOLS / "wav_to_test_vector.py")
wav_to_test_vector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wav_to_test_vector)


class WavToTestVectorTests(unittest.TestCase):
    def setUp(self):
        self.model_path = ROOT / "output_tflite_int8" / "nuclea_int8.tflite"
        self.positive_wav = ROOT / "dataset" / "real" / "wakeword_amo" / "detected_raw" / "raw_0000.wav"
        self.negative_wav = ROOT / "dataset" / "background_test" / "negative.wav"

    def test_metadata_matches_fixed_int8_contract(self):
        metadata = wav_to_test_vector.load_model_metadata(self.model_path)
        self.assertEqual(metadata.input_shape, (1, 13, 49, 1))
        self.assertEqual(metadata.output_shape, (1, 2))
        self.assertEqual(metadata.input_dtype, "int8")
        self.assertEqual(metadata.output_dtype, "int8")
        self.assertAlmostEqual(metadata.input_scale, 3.1064834594726562)
        self.assertEqual(metadata.input_zero_point, 76)
        self.assertAlmostEqual(metadata.output_scale, 0.00390625)
        self.assertEqual(metadata.output_zero_point, -128)

    def test_build_test_case_quantizes_real_positive_wav(self):
        case = wav_to_test_vector.build_test_case("positive_amo_raw_0000", self.positive_wav, self.model_path)
        self.assertEqual(case.name, "positive_amo_raw_0000")
        self.assertEqual(len(case.quantized_input), 637)
        self.assertTrue(all(isinstance(value, int) for value in case.quantized_input))
        self.assertTrue(all(-128 <= value <= 127 for value in case.quantized_input))
        self.assertEqual(case.expected_detected, case.desktop_score >= 0.31)

    def test_generated_cpp_contains_two_vectors_and_traceability(self):
        metadata = wav_to_test_vector.load_model_metadata(self.model_path)
        cases = [
            wav_to_test_vector.build_test_case("positive_amo_raw_0000", self.positive_wav, self.model_path),
            wav_to_test_vector.build_test_case("negative_background", self.negative_wav, self.model_path),
        ]
        header, source = wav_to_test_vector.render_cpp(cases, metadata)
        self.assertIn("struct NucleaTestVector", header)
        self.assertIn("extern const NucleaTestVector kNucleaTestVectors[];", header)
        self.assertIn("positive_amo_raw_0000", source)
        self.assertIn("negative_background", source)
        self.assertIn("wake-word/dataset/real/wakeword_amo/detected_raw/raw_0000.wav", source)
        self.assertIn("wake-word/dataset/background_test/negative.wav", source)
        self.assertIn("kNucleaTestVectorCount = 2", source)


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run test to verify RED**

Run from `wake-word/esp32_nuclea_test`: `python -m unittest tools/test_wav_to_test_vector.py -v`
Expected: fail because `tools/wav_to_test_vector.py` does not exist.

## Task 3: Generator Implementation GREEN

**Files:**
- Create: `wake-word/esp32_nuclea_test/tools/wav_to_test_vector.py`
- Modify: `wake-word/esp32_nuclea_test/tools/test_wav_to_test_vector.py`

**Interfaces:**
- Consumes: model path and WAV paths.
- Produces: `ModelMetadata`, `TestCase`, `load_model_metadata`, `extract_mfcc`, `quantize_mfcc`, `run_desktop_inference`, `build_test_case`, `render_cpp`, `write_cpp_files`, and CLI `main`.

- [x] **Step 1: Implement generator**

Implement dataclasses with exact fields:

```python
@dataclasses.dataclass(frozen=True)
class ModelMetadata:
    input_shape: tuple[int, ...]
    output_shape: tuple[int, ...]
    input_dtype: str
    output_dtype: str
    input_scale: float
    input_zero_point: int
    output_scale: float
    output_zero_point: int
    sha256: str
    size_bytes: int


@dataclasses.dataclass(frozen=True)
class TestCase:
    name: str
    source_path: pathlib.Path
    quantized_input: tuple[int, ...]
    desktop_raw_output: tuple[int, int]
    desktop_score: float
    expected_detected: bool
```

Use `tf.lite.Interpreter`, `librosa.load(..., sr=16000, mono=True)`, right-pad or center-crop to 16000 samples, and `librosa.feature.mfcc(..., n_mfcc=13, n_fft=512, win_length=400, hop_length=320, n_mels=40, fmin=20, fmax=7600, center=False)`.

- [x] **Step 2: Make CLI write generated files**

The CLI accepts `--model`, `--positive`, `--negative`, `--out-dir`, defaults to the project-relative paths in Global Constraints, and writes `test_vectors.h` plus `test_vectors.cc`.

- [x] **Step 3: Run generator tests to verify GREEN**

Run from `wake-word/esp32_nuclea_test`: `python -m unittest tools/test_wav_to_test_vector.py -v`
Expected: PASS.

## Task 4: Generate Checked-In Vectors

**Files:**
- Create: `wake-word/esp32_nuclea_test/main/test_vectors.h`
- Create: `wake-word/esp32_nuclea_test/main/test_vectors.cc`

**Interfaces:**
- Consumes: `tools/wav_to_test_vector.py`.
- Produces: `struct NucleaTestVector`, `kNucleaTestVectors`, `kNucleaTestVectorCount`, `kNucleaInputElementCount`, `kNucleaWakeThreshold`.

- [x] **Step 1: Run generator**

Run from `wake-word/esp32_nuclea_test`: `python tools/wav_to_test_vector.py`
Expected: writes `main/test_vectors.h` and `main/test_vectors.cc`.

- [x] **Step 2: Inspect generated traceability**

Run: `Select-String -Path main\test_vectors.cc -Pattern 'positive_amo_raw_0000|negative_background|wake-word/dataset/real/wakeword_amo/detected_raw/raw_0000.wav|wake-word/dataset/background_test/negative.wav|kNucleaTestVectorCount = 2'`
Expected: all patterns appear.

## Task 5: Firmware Main RED/GREEN By Build

**Files:**
- Create: `wake-word/esp32_nuclea_test/main/main.cc`

**Interfaces:**
- Consumes: `nuclea_model`, `nuclea_model_len`, and `test_vectors.h`.
- Produces: `app_main()` that prints model metadata, runs each vector, and reports PASS/FAIL.

- [x] **Step 1: Write minimal firmware using wished-for vector interface**

Include TensorFlow Lite Micro headers, create static `uint8_t tensor_arena[128 * 1024]`, check model schema, register required ops, allocate tensors, validate input and output contracts, copy each `int8_t input[637]`, invoke, and compare dequantized class 1 score.

- [x] **Step 2: Run ESP-IDF target and build**

Run from `wake-word/esp32_nuclea_test`: `idf.py set-target esp32s3`
Run from `wake-word/esp32_nuclea_test`: `idf.py build`
Expected: build succeeds, or stops on a concrete missing local ESP-IDF/dependency/toolchain issue.

- [x] **Step 3: Tighten op resolver when graph inspection is available**

If Python can inspect model op names, replace `AllOpsResolver` with `MicroMutableOpResolver<N>` and explicit registrations. If local inspection is blocked, keep `AllOpsResolver` for the first compile attempt and document the blocker in final status.

## Task 6: Board Evidence

**Files:**
- Create or Modify: `wake-word/esp32_nuclea_test/test-results/esp32-inference.txt`

**Interfaces:**
- Consumes: built firmware and connected ESP32-S3.
- Produces: captured serial evidence containing ESP-IDF version, target, model hash, tensor metadata, and PASS for both vectors.

- [x] **Step 1: Flash and monitor when a board is available**

Completed on 2026-09-08 via `COM7` (`USB-SERIAL CH340`). Serial output reported `PASS positive_amo_raw_0000` and `PASS negative_background`.

Run from `wake-word/esp32_nuclea_test`: `idf.py -p COMx flash monitor`
Expected serial output includes `PASS positive_amo_raw_0000` and `PASS negative_background`.

- [x] **Step 2: Save board log**

Save the monitor output to `test-results/esp32-inference.txt` with the actual port and timestamp.

## Self-Review

- Spec coverage: Tasks cover scaffold, model copy, generator tests, generator implementation, generated vectors, firmware TFLM invocation, build, and board evidence.
- Placeholder scan: passed for forbidden planning markers.
- Type consistency: generator and firmware interfaces define the same vector count, input length, threshold, and expected decision fields.
