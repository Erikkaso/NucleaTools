# ESP32 Núclea TFLite Micro Validation Design

## Goal

Validate that TensorFlow Lite Micro on an ESP32-S3 produces the same INT8
inference result as desktop TensorFlow Lite for known, precomputed MFCC
tensors from one positive and one negative real audio sample.

## Context and fixed model contract

The firmware project will live at `wake-word/esp32_nuclea_test` and target
ESP-IDF 5.5 with `esp32s3`. The existing model is
`wake-word/output_tflite_int8/nuclea_int8.tflite`; its generated C source is
already available at `wake-word/esp32_model/nuclea_model.{h,cc}`.

The model contract is fixed for this stage:

- Model SHA-256: `09f98fa19154dd20d2ce60f8c30ce6cf289c43ae947a964012f8a82f9590bc57`
- Model size: 28,624 bytes
- Input: INT8 `[1, 13, 49, 1]` (637 values), scale `3.1064834594726562`, zero point `76`
- Output: INT8 `[1, 2]`, scale `0.00390625`, zero point `-128`
- Positive-class index: `1`
- Wake threshold: `0.31`; it must not be recalibrated from the selected test files.

## Approaches considered

1. **Precompute and embed quantized MFCCs (selected).** Python owns WAV
   decoding, framing, MFCC extraction, quantization and desktop inference;
   firmware owns only the TFLM model invocation and comparison. This isolates
   the first embedded-runtime risk and gives an exact, reproducible input.
2. **Embed PCM16 and calculate MFCC in firmware now.** This would validate a
   full audio pipeline, but a score mismatch would not identify whether the
   cause is MFCC parity or TFLM. It is deferred until the selected approach
   has passed.
3. **Use a live microphone now.** Hardware timing, capture configuration and
   environmental variation would prevent deterministic regression validation;
   it is out of scope.

## Architecture

`tools/wav_to_test_vector.py` is the authoritative desktop generator. It
loads a WAV as mono 16 kHz audio, pads or center-crops it to 16,000 samples,
extracts MFCC with the exact training parameters, quantizes with metadata read
from the TFLite model, invokes desktop TFLite with those quantized values, and
emits C++ declarations and definitions. The generator must be covered by a
Python unittest that checks vector length, `int8` dtype, integer bounds and
that the reported score equals a direct desktop invocation.

Generated `test_vectors.{h,cc}` exposes an array of `NucleaTestVector` values
containing a descriptive name, the 637-byte input, its PC score, and the PC
threshold decision. At least one real positive and one real negative WAV are
selected from the existing dataset; generation records the selected source
paths in the C++ comments for traceability.

`main.cc` loads `nuclea_model`, rejects a TFLite schema mismatch, constructs a
TFLM interpreter, validates both tensor contracts before copying any data, and
runs every generated vector. It dequantizes output class 1 as
`(raw - zero_point) * scale`, applies `score >= 0.31f`, compares against the
desktop result using a tolerance of one output quantization step plus a small
floating-point epsilon, and prints one PASS/FAIL block per vector.

The initial firmware resolver may use `AllOpsResolver` only for bring-up if
the operator graph cannot be inspected locally. Before the validation is
accepted, it will be replaced with a `MicroMutableOpResolver` containing only
the model's inspected operators. The initial tensor arena is a static 128 KiB
buffer.

## Components and boundaries

- `CMakeLists.txt`, `sdkconfig.defaults`: ESP-IDF project/target defaults.
- `main/CMakeLists.txt`, `main/idf_component.yml`: component source list and
  `espressif/esp-tflite-micro` dependency.
- `main/nuclea_model.{h,cc}`: unchanged model bytes only, copied from the
  existing generated source.
- `tools/wav_to_test_vector.py`: reusable desktop conversion and code
  generation functions plus CLI; no firmware responsibility.
- `tools/test_wav_to_test_vector.py`: generator regression tests.
- `main/test_vectors.{h,cc}`: generated, checked-in immutable test fixtures;
  no transformation logic.
- `main/main.cc`: TFLM lifecycle, contract validation and serial reporting.
- `test-results/esp32-inference.txt`: captured board evidence including
  ESP-IDF version, target, model hash, quantization metadata and positive /
  negative PASS output.

## Data flow and failure handling

`WAV -> Python MFCC -> TFLite input quantization -> desktop TFLite score ->
generated C++ vector -> TFLM Invoke -> ESP32 dequantized score -> comparison`.

The generator fails with a clear exception for missing files, a nonpositive
quantization scale, an unexpected model input/output type or shape, or a MFCC
shape other than `[13,49,1]`. Firmware returns from `app_main` without
inference when schema, allocation, input type/shape/byte count, or output
type/class count differs from the contract. An `Invoke` failure or a score /
classification mismatch prints FAIL and proceeds to the next independent
vector.

## Verification and acceptance gate

1. Unit tests must first fail before generator implementation, then pass using
   `python -m unittest tools/test_wav_to_test_vector.py` from the firmware
   project directory.
2. `idf.py set-target esp32s3` and `idf.py build` must complete successfully.
3. A flashed board must report model schema success and PASS for at least one
   positive and one negative vector.
4. Each ESP32 classification must equal the desktop expected decision and its
   score delta must be no greater than one output quantization step
   (`0.00390625`) plus floating-point epsilon.

Only after all four gates pass may a separate design begin for embedded PCM16
and MFCC generation. Live microphone capture remains a later stage.
