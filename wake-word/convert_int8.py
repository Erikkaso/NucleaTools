from __future__ import annotations

from pathlib import Path
import argparse
import csv
import json
import random

import numpy as np


# ============================================================
# MFCC - EXATAMENTE IGUAL AO TREINAMENTO
# ============================================================

SAMPLE_RATE = 16000
NUM_SAMPLES = 16000

N_MFCC = 13
N_FFT = 512
WIN_LENGTH = 400
HOP_LENGTH = 320
N_MELS = 40
FMIN = 20
FMAX = 7600

MAX_FRAMES = 1 + (NUM_SAMPLES - N_FFT) // HOP_LENGTH  # 49

SEED = 42


# ============================================================
# DATASETS PARA CALIBRAÇÃO REPRESENTATIVA
# ============================================================

REAL_DIRS = [
    Path("dataset/real/wakeword_amo"),
    Path("dataset/real/wakeword_biladadeiro"),
    Path("dataset/real/wakeword_derik"),
    Path("dataset/real/wakeword_eric"),
    Path("dataset/real/wakeword_vinicius"),
]

SYNTHETIC_DIRS = [
    Path("dataset/wakeword_synthetic"),
    Path("dataset/wakeword_eleven"),
]

BACKGROUND_DIRS = [
    Path("dataset/background_noise"),
    Path("dataset/background_voice"),
    Path("dataset/background_silence/generated"),
    Path("dataset/background_hard_negative/generated"),
]


# ============================================================
# HELPERS PUROS
# ============================================================

def quantize_array(
    x: np.ndarray,
    scale: float,
    zero_point: int,
) -> np.ndarray:
    if scale <= 0:
        raise ValueError("Quantization scale precisa ser > 0.")

    q = np.rint(
        x / scale + zero_point
    )

    q = np.clip(
        q,
        -128,
        127,
    )

    return q.astype(np.int8)


def dequantize_array(
    q: np.ndarray,
    scale: float,
    zero_point: int,
) -> np.ndarray:
    if scale <= 0:
        raise ValueError("Quantization scale precisa ser > 0.")

    return (
        (q.astype(np.float32) - zero_point)
        * scale
    )


def binary_metrics(
    labels: np.ndarray,
    scores: np.ndarray,
    threshold: float,
) -> dict:
    labels = np.asarray(labels, dtype=np.int32)
    scores = np.asarray(scores, dtype=np.float32)

    pred = scores >= threshold

    tp = int(np.sum((labels == 1) & pred))
    fn = int(np.sum((labels == 1) & (~pred)))
    fp = int(np.sum((labels == 0) & pred))
    tn = int(np.sum((labels == 0) & (~pred)))

    recall = tp / (tp + fn) if tp + fn else 0.0
    precision = tp / (tp + fp) if tp + fp else 0.0
    fpr = fp / (fp + tn) if fp + tn else 0.0
    accuracy = (tp + tn) / len(labels) if len(labels) else 0.0

    return {
        "threshold": float(threshold),
        "tp": tp,
        "fn": fn,
        "fp": fp,
        "tn": tn,
        "recall": float(recall),
        "precision": float(precision),
        "fpr": float(fpr),
        "accuracy": float(accuracy),
    }


# ============================================================
# ARQUIVOS
# ============================================================

def wavs(directory: Path) -> list[Path]:
    if not directory.exists():
        return []

    return sorted(
        directory.rglob("*.wav")
    )


def collect_representative_files(
    positive_limit: int,
    negative_limit: int,
) -> list[Path]:
    positive: list[Path] = []

    for directory in REAL_DIRS + SYNTHETIC_DIRS:
        positive.extend(
            wavs(directory)
        )

    negative: list[Path] = []

    for directory in BACKGROUND_DIRS:
        negative.extend(
            wavs(directory)
        )

    positive = sorted(set(positive))
    negative = sorted(set(negative))

    if not positive:
        raise RuntimeError(
            "Nenhum positivo encontrado para representative dataset."
        )

    if not negative:
        raise RuntimeError(
            "Nenhum negativo encontrado para representative dataset."
        )

    rng = random.Random(SEED)

    rng.shuffle(positive)
    rng.shuffle(negative)

    selected_positive = positive[
        :min(
            positive_limit,
            len(positive),
        )
    ]

    selected_negative = negative[
        :min(
            negative_limit,
            len(negative),
        )
    ]

    combined = (
        selected_positive
        + selected_negative
    )

    rng.shuffle(
        combined
    )

    print(
        f"Representative dataset: "
        f"{len(selected_positive)} positivos + "
        f"{len(selected_negative)} negativos = "
        f"{len(combined)}"
    )

    return combined


# ============================================================
# MFCC
# ============================================================

def extract_mfcc(
    filename: Path,
) -> np.ndarray:
    import librosa

    audio, _ = librosa.load(
        filename,
        sr=SAMPLE_RATE,
        mono=True,
    )

    audio = audio.astype(
        np.float32
    )

    if len(audio) < NUM_SAMPLES:
        audio = np.pad(
            audio,
            (
                0,
                NUM_SAMPLES - len(audio),
            ),
        )

    elif len(audio) > NUM_SAMPLES:
        start = (
            len(audio)
            - NUM_SAMPLES
        ) // 2

        audio = audio[
            start:
            start + NUM_SAMPLES
        ]

    mfcc = librosa.feature.mfcc(
        y=audio,
        sr=SAMPLE_RATE,
        n_mfcc=N_MFCC,
        n_fft=N_FFT,
        win_length=WIN_LENGTH,
        hop_length=HOP_LENGTH,
        n_mels=N_MELS,
        fmin=FMIN,
        fmax=FMAX,
        center=False,
    )

    if mfcc.shape[1] < MAX_FRAMES:
        mfcc = np.pad(
            mfcc,
            (
                (0, 0),
                (
                    0,
                    MAX_FRAMES - mfcc.shape[1],
                ),
            ),
        )

    mfcc = mfcc[
        :,
        :MAX_FRAMES
    ].astype(
        np.float32
    )

    return np.expand_dims(
        mfcc,
        axis=-1,
    )


# ============================================================
# REPRESENTATIVE GENERATOR
# ============================================================

def representative_generator(
    files: list[Path],
):
    for filename in files:
        x = extract_mfcc(
            filename
        )

        x = np.expand_dims(
            x,
            axis=0,
        ).astype(
            np.float32
        )

        yield [x]


# ============================================================
# VALIDAÇÃO
# ============================================================

def resolve_csv_path(
    raw: str,
    csv_path: Path,
) -> Path:
    path = Path(raw)

    if path.exists():
        return path

    candidate = (
        csv_path.parent.parent
        / path
    )

    if candidate.exists():
        return candidate

    return path


def load_validation_csv(
    csv_path: Path,
) -> tuple[list[Path], np.ndarray]:
    files: list[Path] = []
    labels: list[int] = []

    with csv_path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        reader = csv.DictReader(
            f
        )

        for row in reader:
            file_path = resolve_csv_path(
                row["file"],
                csv_path,
            )

            kind = row["type"].strip()

            if kind == "real_positive":
                label = 1
            elif kind == "background":
                label = 0
            else:
                continue

            if not file_path.exists():
                raise FileNotFoundError(
                    f"Arquivo listado na validação não encontrado: "
                    f"{file_path}"
                )

            files.append(
                file_path
            )
            labels.append(
                label
            )

    if not files:
        raise RuntimeError(
            f"Nenhuma amostra encontrada em {csv_path}"
        )

    return (
        files,
        np.asarray(
            labels,
            dtype=np.int32,
        ),
    )


def load_threshold(
    results_json: Path,
) -> float:
    with results_json.open(
        "r",
        encoding="utf-8",
    ) as f:
        data = json.load(
            f
        )

    return float(
        data["threshold"]
    )


# ============================================================
# INFERÊNCIA INT8
# ============================================================

def run_int8(
    interpreter,
    features: np.ndarray,
) -> np.ndarray:
    input_details = interpreter.get_input_details()[0]
    output_details = interpreter.get_output_details()[0]

    in_scale, in_zero = input_details["quantization"]
    out_scale, out_zero = output_details["quantization"]

    if in_scale <= 0:
        raise RuntimeError(
            "Entrada do TFLite não está quantizada."
        )

    if out_scale <= 0:
        raise RuntimeError(
            "Saída do TFLite não está quantizada."
        )

    nuclea_scores = []

    for x in features:
        batch = np.expand_dims(
            x,
            axis=0,
        )

        q_input = quantize_array(
            batch,
            scale=float(in_scale),
            zero_point=int(in_zero),
        )

        interpreter.set_tensor(
            input_details["index"],
            q_input,
        )

        interpreter.invoke()

        q_output = interpreter.get_tensor(
            output_details["index"]
        )

        output = dequantize_array(
            q_output,
            scale=float(out_scale),
            zero_point=int(out_zero),
        )

        nuclea_scores.append(
            float(
                output[0, 1]
            )
        )

    return np.asarray(
        nuclea_scores,
        dtype=np.float32,
    )


# ============================================================
# MAIN
# ============================================================

def main():
    import tensorflow as tf

    parser = argparse.ArgumentParser(
        description=(
            "Converte o modelo Núclea Keras para TFLite FULL INT8 "
            "e compara o INT8 contra o Keras no conjunto de validação."
        )
    )

    parser.add_argument(
        "--model",
        type=Path,
        default=Path(
            "output_final_hardneg/nuclea_final.keras"
        ),
    )

    parser.add_argument(
        "--validation-csv",
        type=Path,
        default=Path(
            "output_final_hardneg/validation_scores.csv"
        ),
    )

    parser.add_argument(
        "--results-json",
        type=Path,
        default=Path(
            "output_final_hardneg/results_final.json"
        ),
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "output_tflite_int8"
        ),
    )

    parser.add_argument(
        "--representative-positive",
        type=int,
        default=250,
    )

    parser.add_argument(
        "--representative-negative",
        type=int,
        default=250,
    )

    args = parser.parse_args()

    for path in (
        args.model,
        args.validation_csv,
        args.results_json,
    ):
        if not path.exists():
            raise FileNotFoundError(
                f"Arquivo não encontrado: {path}"
            )

    args.output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    print(
        "=" * 72
    )
    print(
        "NÚCLEA - CONVERSÃO TFLITE FULL INT8"
    )
    print(
        "=" * 72
    )

    print(
        f"Modelo Keras: "
        f"{args.model}"
    )

    threshold = load_threshold(
        args.results_json
    )

    print(
        f"Threshold congelado: "
        f"{threshold:.4f}"
    )

    model = tf.keras.models.load_model(
        args.model
    )

    representative_files = collect_representative_files(
        positive_limit=args.representative_positive,
        negative_limit=args.representative_negative,
    )

    converter = tf.lite.TFLiteConverter.from_keras_model(
        model
    )

    converter.optimizations = [
        tf.lite.Optimize.DEFAULT
    ]

    converter.representative_dataset = (
        lambda: representative_generator(
            representative_files
        )
    )

    converter.target_spec.supported_ops = [
        tf.lite.OpsSet.TFLITE_BUILTINS_INT8
    ]

    converter.inference_input_type = tf.int8
    converter.inference_output_type = tf.int8

    print()
    print(
        "Convertendo..."
    )

    tflite_model = converter.convert()

    output_model = (
        args.output_dir
        / "nuclea_int8.tflite"
    )

    output_model.write_bytes(
        tflite_model
    )

    interpreter = tf.lite.Interpreter(
        model_path=str(
            output_model
        )
    )

    interpreter.allocate_tensors()

    input_details = interpreter.get_input_details()[0]
    output_details = interpreter.get_output_details()[0]

    print()
    print(
        "Entrada TFLite:"
    )
    print(
        "  shape:",
        input_details["shape"].tolist(),
    )
    print(
        "  dtype:",
        input_details["dtype"],
    )
    print(
        "  quantization:",
        input_details["quantization"],
    )

    print(
        "Saída TFLite:"
    )
    print(
        "  shape:",
        output_details["shape"].tolist(),
    )
    print(
        "  dtype:",
        output_details["dtype"],
    )
    print(
        "  quantization:",
        output_details["quantization"],
    )

    expected_input_shape = [
        1,
        N_MFCC,
        MAX_FRAMES,
        1,
    ]

    if input_details["shape"].tolist() != expected_input_shape:
        raise RuntimeError(
            f"Shape inesperado: "
            f"{input_details['shape'].tolist()} "
            f"!= {expected_input_shape}"
        )

    if input_details["dtype"] != np.int8:
        raise RuntimeError(
            "Entrada TFLite não é int8."
        )

    if output_details["dtype"] != np.int8:
        raise RuntimeError(
            "Saída TFLite não é int8."
        )

    print()
    print(
        "Carregando conjunto de validação..."
    )

    eval_files, labels = load_validation_csv(
        args.validation_csv
    )

    features = np.asarray(
        [
            extract_mfcc(
                filename
            )
            for filename in eval_files
        ],
        dtype=np.float32,
    )

    keras_scores = model.predict(
        features,
        batch_size=128,
        verbose=0,
    )[:, 1].astype(
        np.float32
    )

    int8_scores = run_int8(
        interpreter,
        features,
    )

    keras_metrics = binary_metrics(
        labels,
        keras_scores,
        threshold,
    )

    int8_metrics = binary_metrics(
        labels,
        int8_scores,
        threshold,
    )

    abs_diff = np.abs(
        keras_scores
        - int8_scores
    )

    keras_pred = (
        keras_scores >= threshold
    )

    int8_pred = (
        int8_scores >= threshold
    )

    agreement = float(
        np.mean(
            keras_pred == int8_pred
        )
    )

    report = {
        "keras_model":
            str(args.model),
        "tflite_model":
            str(output_model),
        "threshold":
            threshold,
        "tflite_size_bytes":
            len(tflite_model),

        "input": {
            "shape":
                input_details["shape"].tolist(),
            "dtype":
                str(input_details["dtype"]),
            "scale":
                float(
                    input_details["quantization"][0]
                ),
            "zero_point":
                int(
                    input_details["quantization"][1]
                ),
        },

        "output": {
            "shape":
                output_details["shape"].tolist(),
            "dtype":
                str(output_details["dtype"]),
            "scale":
                float(
                    output_details["quantization"][0]
                ),
            "zero_point":
                int(
                    output_details["quantization"][1]
                ),
        },

        "validation_samples":
            len(labels),
        "keras_metrics":
            keras_metrics,
        "int8_metrics":
            int8_metrics,
        "classification_agreement":
            agreement,

        "score_error": {
            "mean_absolute":
                float(np.mean(abs_diff)),
            "p95_absolute":
                float(
                    np.percentile(
                        abs_diff,
                        95,
                    )
                ),
            "max_absolute":
                float(np.max(abs_diff)),
        },
    }

    report_path = (
        args.output_dir
        / "quantization_report.json"
    )

    with report_path.open(
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            report,
            f,
            ensure_ascii=False,
            indent=2,
        )

    comparison_path = (
        args.output_dir
        / "validation_comparison.csv"
    )

    with comparison_path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as f:
        writer = csv.writer(
            f
        )

        writer.writerow([
            "file",
            "label",
            "keras_score",
            "int8_score",
            "absolute_difference",
            "keras_detected",
            "int8_detected",
        ])

        for (
            filename,
            label,
            keras_score,
            int8_score,
            difference,
        ) in zip(
            eval_files,
            labels,
            keras_scores,
            int8_scores,
            abs_diff,
        ):
            writer.writerow([
                str(filename),
                int(label),
                float(keras_score),
                float(int8_score),
                float(difference),
                int(
                    keras_score >= threshold
                ),
                int(
                    int8_score >= threshold
                ),
            ])

    print()
    print(
        "=" * 72
    )
    print(
        "RESULTADO DA QUANTIZAÇÃO"
    )
    print(
        "=" * 72
    )

    print(
        f"TFLite: "
        f"{output_model}"
    )
    print(
        f"Tamanho: "
        f"{len(tflite_model) / 1024:.2f} KiB"
    )

    print()
    print("KERAS:")
    print(
        f"  Recall:    "
        f"{keras_metrics['recall'] * 100:.2f}%"
    )
    print(
        f"  Precision: "
        f"{keras_metrics['precision'] * 100:.2f}%"
    )
    print(
        f"  FPR:       "
        f"{keras_metrics['fpr'] * 100:.2f}%"
    )
    print(
        f"  TP/FN:     "
        f"{keras_metrics['tp']}/"
        f"{keras_metrics['fn']}"
    )
    print(
        f"  FP/TN:     "
        f"{keras_metrics['fp']}/"
        f"{keras_metrics['tn']}"
    )

    print()
    print("TFLITE INT8:")
    print(
        f"  Recall:    "
        f"{int8_metrics['recall'] * 100:.2f}%"
    )
    print(
        f"  Precision: "
        f"{int8_metrics['precision'] * 100:.2f}%"
    )
    print(
        f"  FPR:       "
        f"{int8_metrics['fpr'] * 100:.2f}%"
    )
    print(
        f"  TP/FN:     "
        f"{int8_metrics['tp']}/"
        f"{int8_metrics['fn']}"
    )
    print(
        f"  FP/TN:     "
        f"{int8_metrics['fp']}/"
        f"{int8_metrics['tn']}"
    )

    print()
    print(
        f"Concordância de classificação: "
        f"{agreement * 100:.2f}%"
    )
    print(
        f"Erro médio de score: "
        f"{np.mean(abs_diff):.6f}"
    )
    print(
        f"Erro P95 de score: "
        f"{np.percentile(abs_diff, 95):.6f}"
    )
    print(
        f"Erro máximo de score: "
        f"{np.max(abs_diff):.6f}"
    )

    print()
    print(
        f"Relatório: "
        f"{report_path}"
    )
    print(
        f"Comparação: "
        f"{comparison_path}"
    )


if __name__ == "__main__":
    main()
