from pathlib import Path
import argparse
import csv

import librosa
import numpy as np
import tensorflow as tf


# ============================================================
# CONFIGURAÇÃO DO MODELO
# ============================================================

SAMPLE_RATE = 16000

WINDOW_SECONDS = 1.0
WINDOW_SAMPLES = int(
    SAMPLE_RATE * WINDOW_SECONDS
)

HOP_SECONDS = 0.25
HOP_SAMPLES = int(
    SAMPLE_RATE * HOP_SECONDS
)


# ============================================================
# MFCC
#
# EXATAMENTE IGUAL AO TREINAMENTO
# ============================================================

N_MFCC = 13

N_FFT = 512
WIN_LENGTH = 400
HOP_LENGTH = 320

N_MELS = 40

FMIN = 20
FMAX = 7600

MAX_FRAMES = (
    1
    + (
        WINDOW_SAMPLES - N_FFT
    )
    // HOP_LENGTH
)


# ============================================================
# LÓGICA TEMPORAL
#
# Para acordar:
# pelo menos 2 das últimas 3 janelas
# devem superar o threshold.
#
# Isso depois pode ser usado também no ESP32.
# ============================================================

CONFIRM_REQUIRED = 2
CONFIRM_WINDOW = 3

# Depois de detectar uma wake,
# espera 2 segundos para não contar
# o mesmo evento várias vezes.
COOLDOWN_SECONDS = 2.0


# ============================================================
# MFCC DE UMA JANELA
# ============================================================

def extract_mfcc(audio):

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
                    MAX_FRAMES
                    - mfcc.shape[1]
                )
            )
        )


    mfcc = mfcc[
        :,
        :MAX_FRAMES
    ]


    return mfcc.astype(
        np.float32
    )


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser()


    parser.add_argument(
        "--model",
        required=True,
        type=Path
    )


    parser.add_argument(
        "--audio",
        required=True,
        type=Path
    )


    parser.add_argument(
        "--threshold",
        required=True,
        type=float
    )


    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "continuous_results.csv"
        )
    )


    args = parser.parse_args()


    # ========================================================
    # CARREGAR MODELO
    # ========================================================

    print("Carregando modelo...")

    model = tf.keras.models.load_model(
        args.model
    )


    # ========================================================
    # CARREGAR ÁUDIO LONGO
    # ========================================================

    print("Carregando áudio...")

    audio, _ = librosa.load(
        args.audio,
        sr=SAMPLE_RATE,
        mono=True
    )


    audio = audio.astype(
        np.float32
    )


    duration_seconds = (
        len(audio)
        / SAMPLE_RATE
    )


    duration_hours = (
        duration_seconds
        / 3600.0
    )


    print()
    print(
        f"Duração: "
        f"{duration_seconds / 60:.2f} minutos"
    )

    print(
        f"Threshold: "
        f"{args.threshold:.3f}"
    )

    print(
        f"Janela: "
        f"{WINDOW_SECONDS:.2f}s"
    )

    print(
        f"Hop: "
        f"{HOP_SECONDS:.2f}s"
    )


    # ========================================================
    # GERAR JANELAS
    # ========================================================

    features = []
    timestamps = []


    for start in range(
        0,
        len(audio) - WINDOW_SAMPLES + 1,
        HOP_SAMPLES
    ):

        frame = audio[
            start:
            start + WINDOW_SAMPLES
        ]


        mfcc = extract_mfcc(
            frame
        )


        features.append(
            mfcc
        )


        timestamps.append(
            start
            / SAMPLE_RATE
        )


    X = np.array(
        features,
        dtype=np.float32
    )


    X = np.expand_dims(
        X,
        axis=-1
    )


    print()
    print(
        f"Janelas: {len(X)}"
    )


    # ========================================================
    # INFERÊNCIA EM BATCH
    # ========================================================

    predictions = model.predict(
        X,
        batch_size=256,
        verbose=1
    )


    probabilities = (
        predictions[:, 1]
    )


    raw_positive = (
        probabilities
        >= args.threshold
    )


    # ========================================================
    # CONTAR EVENTOS REAIS
    #
    # Não contamos simplesmente cada janela positiva.
    #
    # Exemplo:
    #
    # 0.25 = 0.91
    # 0.50 = 0.96
    # 0.75 = 0.94
    #
    # Isso deve contar como UMA falsa wake,
    # não três.
    # ========================================================

    wake_events = []

    cooldown_windows = int(
        COOLDOWN_SECONDS
        / HOP_SECONDS
    )


    cooldown = 0

    history = []


    for i, is_positive in enumerate(
        raw_positive
    ):

        history.append(
            bool(is_positive)
        )


        if len(history) > CONFIRM_WINDOW:

            history.pop(0)


        if cooldown > 0:

            cooldown -= 1

            continue


        if len(history) < CONFIRM_WINDOW:

            continue


        positives = sum(
            history
        )


        if positives >= CONFIRM_REQUIRED:

            event_time = (
                timestamps[i]
            )


            wake_events.append({

                "time_seconds":
                    event_time,

                "time":
                    (
                        f"{int(event_time // 60):02d}:"
                        f"{event_time % 60:06.3f}"
                    ),

                "probability":
                    float(
                        probabilities[i]
                    ),
            })


            cooldown = (
                cooldown_windows
            )

            history = []


    # ========================================================
    # MÉTRICAS
    # ========================================================

    num_events = len(
        wake_events
    )


    false_wakes_per_hour = (

        num_events
        / duration_hours

        if duration_hours > 0

        else 0
    )


    raw_count = int(
        np.sum(
            raw_positive
        )
    )


    max_probability = float(
        np.max(
            probabilities
        )
    )


    mean_probability = float(
        np.mean(
            probabilities
        )
    )


    p99 = float(
        np.percentile(
            probabilities,
            99
        )
    )


    p999 = float(
        np.percentile(
            probabilities,
            99.9
        )
    )


    # ========================================================
    # RESULTADO
    # ========================================================

    print()
    print("=" * 60)
    print("TESTE CONTÍNUO")
    print("=" * 60)


    print(
        f"Duração: "
        f"{duration_seconds / 60:.2f} min"
    )


    print(
        f"Janelas analisadas: "
        f"{len(probabilities)}"
    )


    print(
        f"Janelas acima do threshold: "
        f"{raw_count}"
    )


    print()
    print(
        f"False wake EVENTS: "
        f"{num_events}"
    )


    print(
        f"False wakes / hora: "
        f"{false_wakes_per_hour:.3f}"
    )


    print()
    print(
        f"Probabilidade média: "
        f"{mean_probability:.5f}"
    )


    print(
        f"P99: "
        f"{p99:.5f}"
    )


    print(
        f"P99.9: "
        f"{p999:.5f}"
    )


    print(
        f"Maior probabilidade: "
        f"{max_probability:.5f}"
    )


    # ========================================================
    # MOSTRAR EVENTOS
    # ========================================================

    if wake_events:

        print()
        print(
            "FALSE WAKES:"
        )

        for event in wake_events:

            print(
                f"  {event['time']}  "
                f"score="
                f"{event['probability']:.4f}"
            )


    # ========================================================
    # CSV DE TODAS AS JANELAS
    # ========================================================

    with open(
        args.output,
        "w",
        newline="",
        encoding="utf-8"
    ) as f:

        writer = csv.writer(
            f
        )


        writer.writerow([
            "time_seconds",
            "probability",
            "above_threshold",
        ])


        for (
            timestamp,
            probability,
            positive
        ) in zip(
            timestamps,
            probabilities,
            raw_positive
        ):

            writer.writerow([
                timestamp,
                float(probability),
                bool(positive),
            ])


    print()
    print(
        f"Resultados completos: "
        f"{args.output}"
    )


if __name__ == "__main__":
    main()