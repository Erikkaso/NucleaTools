"""Compare old and confirmed-only firmware gates using the actual INT8 model."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "esp32_wakeword/tools"))
from detection_gate_reference import DetectionGate


def events(scores, strict=True):
    gate = DetectionGate()
    history = []
    last = -2000
    count = 0
    for index, score in enumerate(scores):
        now = 1000 + index * 240
        if strict:
            count += int(gate.accept(score, now))
        else:
            history.append(score >= gate.threshold)
            history = history[-3:]
            if now - last >= 2000 and (score >= .98 or sum(history) >= 2):
                count += 1
                last = now
    return count


def supported_events(scores, support_threshold):
    history = []
    last = -2000
    count = 0
    for index, score in enumerate(scores):
        now = 1000 + index * 240
        history.append(score)
        history = history[-3:]
        normal = score >= DetectionGate.threshold and sum(s >= DetectionGate.threshold for s in history) >= 2
        supported = (score >= support_threshold and max(history) >= .98
                     and sum(s >= support_threshold for s in history) >= 2)
        if now - last >= 2000 and (normal or supported):
            count += 1
            last = now
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=ROOT / "dataset/synthetic_negatives_v1/sources")
    parser.add_argument("--output", type=Path, default=ROOT / "output/synthetic_negatives_v1/gate_diagnostic.json")
    args = parser.parse_args()
    negatives = sorted(args.corpus.rglob("*.wav"))
    if not negatives:
        parser.error("No generated negative source WAVs found.")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    os.environ.setdefault("NUMBA_CACHE_DIR", str(Path(os.environ.get("TEMP", ".")) / "nuclea-numba"))
    import numpy as np
    import soundfile as sf
    import tensorflow as tf
    sys.path.insert(0, str(ROOT / "train_models"))
    from train_noise_robust_v1 import mfcc_from_audio

    embedded_source = (ROOT / "esp32_wakeword/main/model/nuclea_model.cc").read_text()
    model = bytes(int(value, 16) for value in re.findall(r"0x([0-9a-fA-F]{2})\b", embedded_source))
    if model[4:8] != b"TFL3":
        raise RuntimeError("Embedded firmware data is not a valid TFLite model.")
    matching_artifacts = [path.relative_to(ROOT).as_posix() for path in (ROOT / "output").rglob("*.tflite")
                          if path.read_bytes() == model]
    interpreter = tf.lite.Interpreter(model_content=model, num_threads=2)
    interpreter.allocate_tensors()
    inp = interpreter.get_input_details()[0]
    out = interpreter.get_output_details()[0]
    in_scale, in_zero = inp["quantization"]
    out_scale, out_zero = out["quantization"]

    def score_file(path):
        audio, rate = sf.read(path, dtype="float32", always_2d=True)
        if rate != 16000:
            raise ValueError(f"Expected 16 kHz PCM: {path}")
        audio = audio.mean(axis=1)
        # Context lets a 1-second positive move through the overlapping runtime windows.
        audio = np.pad(audio, (16000, 16000))
        audio = np.clip(np.rint(audio * 32768), -32768, 32767).astype("<i2").astype(np.float32) / 32768
        scores = []
        for start in range(0, len(audio) - 15999, 3840):
            feature = mfcc_from_audio(audio[start:start + 16000])
            quantized = np.clip(np.rint(feature / in_scale + in_zero), -128, 127).astype(np.int8)
            interpreter.set_tensor(inp["index"], quantized.reshape(inp["shape"]))
            interpreter.invoke()
            scores.append(float((int(interpreter.get_tensor(out["index"])[0, 1]) - out_zero) * out_scale))
        return {"file": path.relative_to(ROOT).as_posix(), "windows": len(scores),
                "max_score": max(scores), "scores": scores, "previous_events": events(scores, False),
                "confirmed_events": events(scores, True)}

    positive_paths = []
    for speaker in sorted((ROOT / "dataset/real").glob("wakeword_*")):
        if "thayza" in speaker.name.lower():
            continue
        for folder in (speaker / "review", speaker / "positive/original", speaker / "clean"):
            paths = sorted(folder.glob("*.wav"))
            if paths:
                positive_paths.extend(paths[:3])
                break
    results = {"negatives": [], "positive_diagnostic": []}
    for kind, paths in (("negatives", negatives), ("positive_diagnostic", positive_paths)):
        for index, path in enumerate(paths):
            results[kind].append(score_file(path))
            if (index + 1) % 20 == 0:
                print(f"{kind}: {index + 1}/{len(paths)}", flush=True)
    summary = {}
    for kind, rows in results.items():
        summary[kind] = {"files": len(rows),
            "previous_triggered_files": sum(row["previous_events"] > 0 for row in rows),
            "confirmed_triggered_files": sum(row["confirmed_events"] > 0 for row in rows),
            "previous_events": sum(row["previous_events"] for row in rows),
            "confirmed_events": sum(row["confirmed_events"] for row in rows)}
    support_sweep = {str(threshold): {kind: sum(supported_events(row["scores"], threshold) > 0 for row in rows)
                    for kind, rows in results.items()} for threshold in (.25, .5, .6, .7, .75, .8, .85, .9)}
    report = {"model_sha256": hashlib.sha256(model).hexdigest(), "model_unchanged": True,
              "model_source": "esp32_wakeword/main/model/nuclea_model.cc",
              "matching_artifacts": matching_artifacts,
              "threshold": DetectionGate.threshold, "stride_ms": 240, "summary": summary,
              "high_threshold": DetectionGate.high_threshold,
              "support_threshold": DetectionGate.support_threshold,
              "support_sweep_development_only": support_sweep,
              "limitations": ["Diagnostic data, not an independent test set or new training.",
                              "Positive samples may have been used during model development.",
                              "No room playback, microphone acoustics or echo cancellation simulated.",
                              "Synthetic negatives can enter future training only, not validation/test."],
              **results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    print(json.dumps(support_sweep, indent=2), flush=True)


if __name__ == "__main__":
    main()
