from __future__ import annotations

from pathlib import Path
import csv
import json
import random
import re

import librosa
import numpy as np
import tensorflow as tf
from sklearn.utils.class_weight import compute_class_weight


# ============================================================
# CONFIGURAÇÃO
# ============================================================

SEED = 42

# 5 locutores reais confiáveis.
# Thayza fica propositalmente fora deste modelo candidato.
REAL_SPEAKERS = {
    "amo": Path("dataset/real/wakeword_amo"),
    "biladadeiro": Path("dataset/real/wakeword_biladadeiro"),
    "derik": Path("dataset/real/wakeword_derik"),
    "eric": Path("dataset/real/wakeword_eric"),
    "vinicius": Path("dataset/real/wakeword_vinicius"),
}

# Sintéticos entram SOMENTE no treino.
SYNTHETIC_DIRS = [
    Path("dataset/wakeword_synthetic"),
    Path("dataset/wakeword_eleven"),
]

# Background usado para treino/validação, agora incluindo negativos de silêncio.
# IMPORTANTE: os arquivos-fonte e os áudios externos de teste contínuo NÃO entram aqui;
# somente os WAVs de dataset/background_silence/generated são usados no treino.
BACKGROUND_DIRS = [
    Path("dataset/background_noise"),
    Path("dataset/background_voice"),
    Path("dataset/background_silence/generated"),
]

# Hard negatives extraídos dos false wakes entram SOMENTE no treino.
# Eles NÃO participam da validação nem da calibração do threshold,
# porque vieram diretamente dos áudios usados para diagnosticar o modelo.
HARD_NEGATIVE_DIRS = [
    Path("dataset/background_hard_negative/generated"),
]

OUTPUT_DIR = Path("output_final_hardneg")

# 20% dos grupos clean de cada locutor ficam reservados para validação.
REAL_VAL_FRACTION = 0.20

# 20% do background fica reservado para calibração do threshold.
BACKGROUND_VAL_FRACTION = 0.20

# Evita que TTS domine os positivos.
# 1.0 = no máximo 1 sintético para cada exemplo real de treino
# (reais incluem clean + augmented).
SYNTHETIC_TO_REAL_RATIO = 1.0

# Meta para calibração.
TARGET_VALIDATION_FPR = 0.01

MAX_EPOCHS = 80
BATCH_SIZE = 32


# ============================================================
# MFCC - IGUAL AOS TREINOS ANTERIORES
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


random.seed(SEED)
np.random.seed(SEED)
tf.random.set_seed(SEED)

FEATURE_CACHE: dict[str, np.ndarray] = {}


# ============================================================
# UTILITÁRIOS
# ============================================================

def wavs(directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.wav")) if directory.exists() else []


def infer_group_id(path: Path) -> str:
    """
    Fallback caso metadata.csv não forneça group_id.

    Ex.:
        nuclea_001.wav
        nuclea_001_aug_00.wav
        nuclea_001_aug_01.wav

    Todos viram o grupo "nuclea_001".
    """
    stem = path.stem

    for pattern in (
        r"(?i)[_-]aug(?:mented)?[_-]?\d+$",
        r"(?i)[_-]augmentation[_-]?\d+$",
    ):
        new = re.sub(pattern, "", stem)

        if new != stem:
            return new

    return stem


def read_metadata_groups(speaker_dir: Path) -> dict[str, str]:
    """
    Procura group_id/group/source_id em metadata.csv.

    Associa qualquer coluna da linha que contenha um caminho .wav
    ao respectivo grupo. Se não houver metadata utilizável,
    o script usa infer_group_id().
    """
    metadata = speaker_dir / "metadata.csv"

    if not metadata.exists():
        return {}

    mapping: dict[str, str] = {}

    with metadata.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        reader = csv.DictReader(f)

        fields = reader.fieldnames or []

        group_col = next(
            (
                name
                for name in ("group_id", "group", "source_id")
                if name in fields
            ),
            None,
        )

        if group_col is None:
            return {}

        for row in reader:
            gid = str(
                row.get(group_col, "")
            ).strip()

            if not gid:
                continue

            for value in row.values():
                value = str(
                    value or ""
                ).strip().replace("\\", "/")

                if value.lower().endswith(".wav"):
                    mapping[value] = gid
                    mapping[Path(value).name] = gid

    return mapping


def file_group(
    path: Path,
    mapping: dict[str, str],
) -> str:
    normalized = str(path).replace("\\", "/")

    return mapping.get(
        normalized,
        mapping.get(
            path.name,
            infer_group_id(path),
        ),
    )


def load_real_speaker(speaker_dir: Path):
    if not speaker_dir.exists():
        raise FileNotFoundError(
            f"Pasta não encontrada: {speaker_dir}"
        )

    clean_dir = speaker_dir / "clean"
    aug_dir = speaker_dir / "augmented"

    if clean_dir.exists():
        clean = wavs(clean_dir)
    else:
        # Fallback para dataset plano.
        clean = sorted(
            speaker_dir.glob("*.wav")
        )

    augmented = wavs(aug_dir)

    if not clean:
        raise RuntimeError(
            f"Nenhum WAV clean encontrado em {speaker_dir}"
        )

    mapping = read_metadata_groups(
        speaker_dir
    )

    clean_by_group: dict[str, list[Path]] = {}
    aug_by_group: dict[str, list[Path]] = {}

    for path in clean:
        gid = file_group(
            path,
            mapping,
        )

        clean_by_group.setdefault(
            gid,
            [],
        ).append(path)

    for path in augmented:
        gid = file_group(
            path,
            mapping,
        )

        aug_by_group.setdefault(
            gid,
            [],
        ).append(path)

    return (
        clean,
        augmented,
        clean_by_group,
        aug_by_group,
    )


def split_groups(
    group_ids: list[str],
    val_fraction: float,
    seed: int,
):
    groups = sorted(
        set(group_ids)
    )

    if len(groups) < 2:
        raise RuntimeError(
            "Preciso de pelo menos 2 grupos clean por locutor."
        )

    rng = random.Random(seed)
    rng.shuffle(groups)

    n_val = max(
        1,
        round(
            len(groups)
            * val_fraction
        ),
    )

    n_val = min(
        n_val,
        len(groups) - 1,
    )

    val = set(
        groups[:n_val]
    )

    train = set(
        groups[n_val:]
    )

    if train & val:
        raise RuntimeError(
            "Vazamento entre grupos de treino e validação."
        )

    return train, val


def split_files(
    files: list[Path],
    val_fraction: float,
    seed: int,
):
    files = list(files)

    if len(files) < 2:
        raise RuntimeError(
            "Poucos arquivos para separar treino/validação."
        )

    rng = random.Random(seed)
    rng.shuffle(files)

    n_val = max(
        1,
        round(
            len(files)
            * val_fraction
        ),
    )

    n_val = min(
        n_val,
        len(files) - 1,
    )

    return (
        files[n_val:],
        files[:n_val],
    )


# ============================================================
# MFCC
# ============================================================

def extract_mfcc(
    filename: Path,
) -> np.ndarray:
    key = str(
        filename.resolve()
    )

    if key in FEATURE_CACHE:
        return FEATURE_CACHE[key]

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
                    MAX_FRAMES
                    - mfcc.shape[1],
                ),
            ),
        )

    mfcc = mfcc[
        :,
        :MAX_FRAMES,
    ].astype(
        np.float32
    )

    FEATURE_CACHE[key] = mfcc

    return mfcc


def make_xy(
    positives: list[Path],
    negatives: list[Path],
    seed: int,
):
    X = [
        extract_mfcc(x)
        for x in positives
    ]

    y = [
        1
    ] * len(positives)

    X.extend(
        extract_mfcc(x)
        for x in negatives
    )

    y.extend(
        [0]
        * len(negatives)
    )

    X = np.expand_dims(
        np.asarray(
            X,
            dtype=np.float32,
        ),
        -1,
    )

    y = np.asarray(
        y,
        dtype=np.int32,
    )

    rng = np.random.default_rng(
        seed
    )

    idx = rng.permutation(
        len(y)
    )

    return (
        X[idx],
        y[idx],
    )


def scores(
    model: tf.keras.Model,
    files: list[Path],
) -> np.ndarray:
    if not files:
        return np.asarray(
            [],
            dtype=np.float32,
        )

    X = np.asarray(
        [
            extract_mfcc(x)
            for x in files
        ],
        dtype=np.float32,
    )

    X = np.expand_dims(
        X,
        -1,
    )

    return model.predict(
        X,
        batch_size=256,
        verbose=0,
    )[:, 1]


# ============================================================
# CNN - MESMA ARQUITETURA DOS MODELOS ANTERIORES
# ============================================================

def create_model() -> tf.keras.Model:
    model = tf.keras.Sequential([
        tf.keras.layers.Input(
            shape=(
                N_MFCC,
                MAX_FRAMES,
                1,
            )
        ),

        tf.keras.layers.Conv2D(
            32,
            (3, 3),
            padding="same",
            use_bias=False,
        ),

        tf.keras.layers.BatchNormalization(),

        tf.keras.layers.ReLU(),

        tf.keras.layers.MaxPooling2D(
            (2, 2)
        ),

        tf.keras.layers.Conv2D(
            64,
            (3, 3),
            padding="same",
            use_bias=False,
        ),

        tf.keras.layers.BatchNormalization(),

        tf.keras.layers.ReLU(),

        tf.keras.layers.GlobalAveragePooling2D(),

        tf.keras.layers.Dense(
            32,
            activation="relu",
        ),

        tf.keras.layers.Dropout(
            0.25
        ),

        tf.keras.layers.Dense(
            2,
            activation="softmax",
        ),
    ])

    model.compile(
        optimizer=tf.keras.optimizers.Adam(
            learning_rate=0.001
        ),

        loss=(
            tf.keras.losses
            .SparseCategoricalCrossentropy()
        ),

        metrics=[
            "accuracy"
        ],
    )

    return model


# ============================================================
# CALIBRAÇÃO DO THRESHOLD
# ============================================================

def threshold_sweep(
    positive_scores: np.ndarray,
    negative_scores: np.ndarray,
):
    result = []

    for threshold in np.arange(
        0.30,
        0.991,
        0.01,
    ):
        threshold = round(
            float(threshold),
            2,
        )

        tp = int(
            np.sum(
                positive_scores
                >= threshold
            )
        )

        fn = int(
            np.sum(
                positive_scores
                < threshold
            )
        )

        fp = int(
            np.sum(
                negative_scores
                >= threshold
            )
        )

        tn = int(
            np.sum(
                negative_scores
                < threshold
            )
        )

        recall = (
            tp / (tp + fn)
            if tp + fn
            else 0.0
        )

        precision = (
            tp / (tp + fp)
            if tp + fp
            else 0.0
        )

        fpr = (
            fp / (fp + tn)
            if fp + tn
            else 0.0
        )

        result.append({
            "threshold": threshold,
            "recall": recall,
            "precision": precision,
            "fpr": fpr,
            "tp": tp,
            "fn": fn,
            "fp": fp,
            "tn": tn,
        })

    return result


def choose_threshold(
    sweep,
    target_fpr: float,
):
    """
    Critério:
      1. FPR <= target;
      2. maior recall;
      3. menor FPR;
      4. em empate, MENOR threshold.

    O item 4 evita escolher 0.95 arbitrariamente
    quando thresholds menores dão exatamente
    as mesmas métricas de validação.
    """
    candidates = [
        row
        for row in sweep
        if row["fpr"] <= target_fpr
    ]

    if candidates:
        return sorted(
            candidates,
            key=lambda row: (
                -row["recall"],
                row["fpr"],
                row["threshold"],
            ),
        )[0]

    # Caso nenhum threshold alcance a meta:
    return sorted(
        sweep,
        key=lambda row: (
            row["fpr"],
            -row["recall"],
            row["threshold"],
        ),
    )[0]


# ============================================================
# MAIN
# ============================================================

def main():
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    print(
        "=" * 72
    )

    print(
        "NÚCLEA - CANDIDATO COM HARD-NEGATIVE MINING"
    )

    print(
        "=" * 72
    )

    real_train: list[Path] = []
    real_val: list[Path] = []

    val_by_speaker: dict[
        str,
        list[Path],
    ] = {}

    split_info = {}

    # ========================================================
    # 1. REAIS
    #
    # 80% grupos -> treino
    # 20% grupos -> validação
    #
    # treino:
    #   clean + augmented
    #
    # validação:
    #   SOMENTE clean
    # ========================================================

    for index, (
        speaker,
        directory,
    ) in enumerate(
        REAL_SPEAKERS.items()
    ):
        (
            clean,
            augmented,
            clean_groups,
            aug_groups,
        ) = load_real_speaker(
            directory
        )

        (
            train_groups,
            val_groups,
        ) = split_groups(
            list(
                clean_groups
            ),
            REAL_VAL_FRACTION,
            SEED + index,
        )

        train_clean = [
            file
            for gid in train_groups
            for file in clean_groups.get(
                gid,
                [],
            )
        ]

        # Só augmentations dos grupos que ficaram no treino.
        train_augmented = [
            file
            for gid in train_groups
            for file in aug_groups.get(
                gid,
                [],
            )
        ]

        # Validação usa somente clean.
        val_clean = [
            file
            for gid in val_groups
            for file in clean_groups.get(
                gid,
                [],
            )
        ]

        real_train.extend(
            train_clean
            + train_augmented
        )

        real_val.extend(
            val_clean
        )

        val_by_speaker[
            speaker
        ] = val_clean

        split_info[
            speaker
        ] = {
            "clean_total":
                len(clean),

            "augmented_total":
                len(augmented),

            "train_groups":
                len(train_groups),

            "validation_groups":
                len(val_groups),

            "train_clean":
                len(train_clean),

            "train_augmented":
                len(train_augmented),

            "validation_clean":
                len(val_clean),
        }

        print()

        print(
            f"{speaker}:"
        )

        print(
            f"  clean total:       "
            f"{len(clean)}"
        )

        print(
            f"  augmented total:   "
            f"{len(augmented)}"
        )

        print(
            f"  treino clean:      "
            f"{len(train_clean)}"
        )

        print(
            f"  treino augmented:  "
            f"{len(train_augmented)}"
        )

        print(
            f"  validação clean:   "
            f"{len(val_clean)}"
        )

    # ========================================================
    # 2. SINTÉTICOS
    # ========================================================

    synthetic_all: list[Path] = []

    for directory in SYNTHETIC_DIRS:
        found = wavs(
            directory
        )

        print()

        print(
            f"{directory}: "
            f"{len(found)} sintéticos"
        )

        synthetic_all.extend(
            found
        )

    synthetic_all = sorted(
        set(
            synthetic_all
        )
    )

    synthetic_limit = min(
        len(synthetic_all),

        round(
            len(real_train)
            * SYNTHETIC_TO_REAL_RATIO
        ),
    )

    rng = random.Random(
        SEED + 1000
    )

    if synthetic_limit < len(
        synthetic_all
    ):
        synthetic_train = rng.sample(
            synthetic_all,
            synthetic_limit,
        )

    else:
        synthetic_train = (
            synthetic_all
        )

    positive_train = (
        real_train
        + synthetic_train
    )

    # ========================================================
    # 3. BACKGROUND
    # ========================================================

    background_all: list[Path] = []

    for directory in BACKGROUND_DIRS:
        found = wavs(
            directory
        )

        print(
            f"{directory}: "
            f"{len(found)} backgrounds"
        )

        background_all.extend(
            found
        )

    background_all = sorted(
        set(
            background_all
        )
    )

    (
        background_train,
        background_val,
    ) = split_files(
        background_all,
        BACKGROUND_VAL_FRACTION,
        SEED + 2000,
    )

    # ========================================================
    # 3B. HARD NEGATIVES - SOMENTE TREINO
    #
    # Não misturamos estes arquivos na validação porque eles
    # foram minerados dos próprios testes contínuos anteriores.
    # Colocá-los em validação criaria vazamento e deixaria a
    # calibração do threshold artificialmente otimista.
    # ========================================================

    hard_negative_train: list[Path] = []

    for directory in HARD_NEGATIVE_DIRS:
        found = wavs(
            directory
        )

        print(
            f"{directory}: "
            f"{len(found)} hard negatives (train-only)"
        )

        hard_negative_train.extend(
            found
        )

    hard_negative_train = sorted(
        set(
            hard_negative_train
        )
    )

    background_train.extend(
        hard_negative_train
    )

    background_train = sorted(
        set(
            background_train
        )
    )

    print()

    print(
        "=" * 72
    )

    print(
        "DATASET USADO"
    )

    print(
        "=" * 72
    )

    print(
        f"Reais treino "
        f"(clean+aug): "
        f"{len(real_train)}"
    )

    print(
        f"Sintéticos treino:    "
        f"{len(synthetic_train)}"
    )

    print(
        f"Positivos treino:     "
        f"{len(positive_train)}"
    )

    print(
        f"Background treino:    "
        f"{len(background_train)}"
    )

    print(
        f"  hard negatives:     "
        f"{len(hard_negative_train)}"
    )

    print(
        f"Reais validação:      "
        f"{len(real_val)}"
    )

    print(
        f"Background validação: "
        f"{len(background_val)}"
    )

    # ========================================================
    # 4. FEATURES
    # ========================================================

    print()

    print(
        "Extraindo MFCCs..."
    )

    X_train, y_train = make_xy(
        positive_train,
        background_train,
        SEED + 3000,
    )

    X_val, y_val = make_xy(
        real_val,
        background_val,
        SEED + 3001,
    )

    classes = np.unique(
        y_train
    )

    weights = compute_class_weight(
        class_weight="balanced",
        classes=classes,
        y=y_train,
    )

    class_weights = {
        int(cls):
            float(weight)

        for cls, weight in zip(
            classes,
            weights,
        )
    }

    print(
        "Class weights:",
        class_weights,
    )

    # ========================================================
    # 5. TREINAMENTO
    # ========================================================

    tf.keras.backend.clear_session()

    model = create_model()

    best_path = (
        OUTPUT_DIR
        / "best.keras"
    )

    callbacks = [
        tf.keras.callbacks.EarlyStopping(
            monitor="val_loss",
            patience=10,
            restore_best_weights=True,
        ),

        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss",
            factor=0.5,
            patience=4,
            min_lr=1e-5,
        ),

        tf.keras.callbacks.ModelCheckpoint(
            best_path,
            monitor="val_loss",
            save_best_only=True,
        ),

        tf.keras.callbacks.CSVLogger(
            OUTPUT_DIR
            / "history.csv"
        ),
    ]

    print()

    print(
        "Treinando..."
    )

    model.fit(
        X_train,
        y_train,

        validation_data=(
            X_val,
            y_val,
        ),

        epochs=MAX_EPOCHS,
        batch_size=BATCH_SIZE,

        class_weight=class_weights,

        callbacks=callbacks,

        verbose=1,
    )

    # Carrega explicitamente o melhor checkpoint.
    model = (
        tf.keras.models
        .load_model(
            best_path
        )
    )

    final_model = (
        OUTPUT_DIR
        / "nuclea_final.keras"
    )

    model.save(
        final_model
    )

    # ========================================================
    # 6. CALIBRAÇÃO DO THRESHOLD
    # ========================================================

    print()

    print(
        "Calibrando threshold..."
    )

    positive_scores = scores(
        model,
        real_val,
    )

    background_scores = scores(
        model,
        background_val,
    )

    sweep = threshold_sweep(
        positive_scores,
        background_scores,
    )

    best = choose_threshold(
        sweep,
        TARGET_VALIDATION_FPR,
    )

    threshold = float(
        best["threshold"]
    )

    # ========================================================
    # 7. RESULTADO POR LOCUTOR
    # ========================================================

    per_speaker = {}

    validation_rows = []

    for (
        speaker,
        files,
    ) in val_by_speaker.items():
        speaker_scores = scores(
            model,
            files,
        )

        detected = int(
            np.sum(
                speaker_scores
                >= threshold
            )
        )

        total = len(
            speaker_scores
        )

        recall = (
            detected / total
            if total
            else 0.0
        )

        per_speaker[
            speaker
        ] = {
            "samples":
                total,

            "detected":
                detected,

            "missed":
                total
                - detected,

            "recall":
                recall,
        }

        for (
            file,
            score,
        ) in zip(
            files,
            speaker_scores,
        ):
            validation_rows.append({
                "file":
                    str(file),

                "type":
                    "real_positive",

                "speaker":
                    speaker,

                "score_nuclea":
                    float(score),

                "detected":
                    int(
                        score
                        >= threshold
                    ),
            })

    for (
        file,
        score,
    ) in zip(
        background_val,
        background_scores,
    ):
        validation_rows.append({
            "file":
                str(file),

            "type":
                "background",

            "speaker":
                "",

            "score_nuclea":
                float(score),

            "detected":
                int(
                    score
                    >= threshold
                ),
        })

    # ========================================================
    # 8. SALVAR AUDITORIA
    # ========================================================

    with (
        OUTPUT_DIR
        / "threshold_sweep.csv"
    ).open(
        "w",
        newline="",
        encoding="utf-8",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "threshold",
                "recall",
                "precision",
                "fpr",
                "tp",
                "fn",
                "fp",
                "tn",
            ],
        )

        writer.writeheader()

        writer.writerows(
            sweep
        )

    with (
        OUTPUT_DIR
        / "validation_scores.csv"
    ).open(
        "w",
        newline="",
        encoding="utf-8",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "file",
                "type",
                "speaker",
                "score_nuclea",
                "detected",
            ],
        )

        writer.writeheader()

        writer.writerows(
            validation_rows
        )

    results = {
        "model":
            str(
                final_model
            ),

        "threshold":
            threshold,

        "target_validation_fpr":
            TARGET_VALIDATION_FPR,

        "validation": {
            "real_samples":
                len(
                    positive_scores
                ),

            "background_samples":
                len(
                    background_scores
                ),

            "recall":
                best["recall"],

            "precision":
                best["precision"],

            "false_positive_rate":
                best["fpr"],

            "tp":
                best["tp"],

            "fn":
                best["fn"],

            "fp":
                best["fp"],

            "tn":
                best["tn"],
        },

        "per_speaker_validation":
            per_speaker,

        "counts": {
            "real_train":
                len(
                    real_train
                ),

            "synthetic_train":
                len(
                    synthetic_train
                ),

            "positive_train":
                len(
                    positive_train
                ),

            "background_train":
                len(
                    background_train
                ),

            "hard_negative_train":
                len(
                    hard_negative_train
                ),

            "real_validation":
                len(
                    real_val
                ),

            "background_validation":
                len(
                    background_val
                ),
        },

        "speaker_split":
            split_info,

        "mfcc": {
            "sample_rate":
                SAMPLE_RATE,

            "num_samples":
                NUM_SAMPLES,

            "n_mfcc":
                N_MFCC,

            "n_fft":
                N_FFT,

            "win_length":
                WIN_LENGTH,

            "hop_length":
                HOP_LENGTH,

            "n_mels":
                N_MELS,

            "fmin":
                FMIN,

            "fmax":
                FMAX,

            "center":
                False,

            "max_frames":
                MAX_FRAMES,
        },
    }

    with (
        OUTPUT_DIR
        / "results_final.json"
    ).open(
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            results,
            f,
            ensure_ascii=False,
            indent=2,
        )

    # ========================================================
    # 9. RESUMO
    # ========================================================

    print()

    print(
        "=" * 72
    )

    print(
        "MODELO CANDIDATO GERADO"
    )

    print(
        "=" * 72
    )

    print(
        f"Modelo:    "
        f"{final_model}"
    )

    print(
        f"Threshold: "
        f"{threshold:.2f}"
    )

    print()

    print(
        f"Recall validação real: "
        f"{best['recall'] * 100:.2f}%"
    )

    print(
        f"Precision:             "
        f"{best['precision'] * 100:.2f}%"
    )

    print(
        f"FPR validação:         "
        f"{best['fpr'] * 100:.2f}%"
    )

    print(
        f"TP/FN: "
        f"{best['tp']}/"
        f"{best['fn']}"
    )

    print(
        f"FP/TN: "
        f"{best['fp']}/"
        f"{best['tn']}"
    )

    print()

    print(
        "Recall de validação por locutor:"
    )

    for (
        speaker,
        metrics,
    ) in per_speaker.items():
        print(
            f"  {speaker:12} "
            f"{metrics['detected']}/"
            f"{metrics['samples']} "
            f"("
            f"{metrics['recall'] * 100:.2f}%"
            f")"
        )

    print()

    print(
        "Arquivos gerados:"
    )

    print(
        f"  {final_model}"
    )

    print(
        f"  "
        f"{OUTPUT_DIR / 'results_final.json'}"
    )

    print(
        f"  "
        f"{OUTPUT_DIR / 'validation_scores.csv'}"
    )

    print(
        f"  "
        f"{OUTPUT_DIR / 'threshold_sweep.csv'}"
    )

    print(
        f"  "
        f"{OUTPUT_DIR / 'history.csv'}"
    )


if __name__ == "__main__":
    main()
