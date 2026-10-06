from __future__ import annotations

from pathlib import Path
import argparse
import csv
import math
import shutil


SAMPLE_RATE = 16000
WINDOW_SECONDS = 1.0
HOP_SECONDS = 0.25

# Intervalos identificados nos testes contínuos.
# Eles são deliberadamente um pouco maiores que o instante exato do wake.
SEGMENTS = {
    "ambiente": [
        ("14:03.5", "14:06.5"),
    ],
    "conversa": [
        ("10:21", "10:24"),
    ],
    "musica": [
        ("02:18", "02:21"),
        ("05:59", "06:02"),
    ],
    "silencio": [
        ("18:45.5", "18:49"),
    ],
}


def parse_timecode(value: str) -> float:
    """
    Aceita:
      SS
      MM:SS
      HH:MM:SS
    com casas decimais no último campo.
    """
    parts = value.strip().split(":")

    if not 1 <= len(parts) <= 3:
        raise ValueError(f"Timecode inválido: {value}")

    numbers = [float(x) for x in parts]

    if len(numbers) == 1:
        return numbers[0]

    if len(numbers) == 2:
        minutes, seconds = numbers
        return minutes * 60.0 + seconds

    hours, minutes, seconds = numbers
    return hours * 3600.0 + minutes * 60.0 + seconds


def window_starts(
    start_seconds: float,
    end_seconds: float,
    window_seconds: float = WINDOW_SECONDS,
    hop_seconds: float = HOP_SECONDS,
) -> list[float]:
    """
    Retorna apenas janelas completamente contidas no intervalo.
    Ex.: 10–13 s, janela 1 s, hop 250 ms => 9 janelas.
    """
    if end_seconds <= start_seconds:
        raise ValueError("end_seconds precisa ser maior que start_seconds.")

    if window_seconds <= 0 or hop_seconds <= 0:
        raise ValueError("window_seconds e hop_seconds precisam ser positivos.")

    last_start = end_seconds - window_seconds

    if last_start < start_seconds:
        return []

    count = int(
        math.floor(
            (last_start - start_seconds) / hop_seconds + 1e-9
        )
    ) + 1

    return [
        round(start_seconds + i * hop_seconds, 6)
        for i in range(count)
    ]


def rms_dbfs(audio) -> float:
    import numpy as np

    if len(audio) == 0:
        return -240.0

    rms = float(
        np.sqrt(
            np.mean(
                np.square(audio.astype(np.float64))
            )
        )
    )

    return 20.0 * math.log10(rms + 1e-12)


def extract_source(
    source_name: str,
    source_path: Path,
    ranges: list[tuple[str, str]],
    output_root: Path,
    writer,
) -> int:
    import librosa
    import numpy as np
    import soundfile as sf

    print()
    print(f"Carregando {source_name}: {source_path}")

    audio, _ = librosa.load(
        source_path,
        sr=SAMPLE_RATE,
        mono=True,
    )

    audio = audio.astype(np.float32)
    duration = len(audio) / SAMPLE_RATE

    print(f"  duração: {duration:.2f}s ({duration / 60:.2f} min)")

    output_dir = output_root / source_name
    output_dir.mkdir(parents=True, exist_ok=True)

    generated = 0

    for range_index, (start_text, end_text) in enumerate(ranges):
        start = parse_timecode(start_text)
        end = parse_timecode(end_text)

        if end > duration + 1e-6:
            raise RuntimeError(
                f"Intervalo {start_text}–{end_text} excede a duração "
                f"de {source_path} ({duration:.2f}s)."
            )

        starts = window_starts(
            start_seconds=start,
            end_seconds=end,
        )

        print(
            f"  trecho {start_text}–{end_text}: "
            f"{len(starts)} janelas"
        )

        for local_index, window_start in enumerate(starts):
            i0 = round(window_start * SAMPLE_RATE)
            i1 = i0 + SAMPLE_RATE

            frame = audio[i0:i1]

            if len(frame) != SAMPLE_RATE:
                raise RuntimeError(
                    f"Janela incompleta em {source_path}: {window_start:.3f}s"
                )

            filename = (
                f"{source_name}_"
                f"seg{range_index:02d}_"
                f"{local_index:03d}_"
                f"{window_start:.3f}s.wav"
            )

            destination = output_dir / filename

            # IMPORTANTE:
            # não normalizamos amplitude. O hard negative precisa preservar
            # exatamente o nível acústico que enganou o modelo.
            sf.write(
                destination,
                frame,
                SAMPLE_RATE,
                subtype="PCM_16",
            )

            peak = float(
                np.max(
                    np.abs(frame)
                )
            )

            zeros = float(
                np.mean(
                    frame == 0
                )
            )

            writer.writerow({
                "file": str(destination),
                "source_type": source_name,
                "source_file": str(source_path),
                "source_segment_start": start_text,
                "source_segment_end": end_text,
                "window_start_seconds": f"{window_start:.6f}",
                "window_end_seconds": f"{window_start + WINDOW_SECONDS:.6f}",
                "rms_dbfs": f"{rms_dbfs(frame):.6f}",
                "peak": f"{peak:.9f}",
                "zero_fraction": f"{zeros:.9f}",
            })

            generated += 1

    return generated


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Extrai janelas de 1s/250ms hop dos trechos que geraram "
            "false wakes e cria hard negatives para o próximo treino."
        )
    )

    parser.add_argument(
        "--ambiente",
        required=True,
        type=Path,
        help="Áudio-fonte do teste ambiente que gerou o falso wake.",
    )

    parser.add_argument(
        "--conversa",
        required=True,
        type=Path,
        help="Áudio-fonte do teste de conversa.",
    )

    parser.add_argument(
        "--musica",
        required=True,
        type=Path,
        help="Áudio-fonte do teste de música.",
    )

    parser.add_argument(
        "--silencio",
        required=True,
        type=Path,
        help="Áudio-fonte do teste de silêncio.",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("dataset/background_hard_negative/generated"),
    )

    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="Não apaga a pasta generated antes de gerar os novos arquivos.",
    )

    args = parser.parse_args()

    sources = {
        "ambiente": args.ambiente,
        "conversa": args.conversa,
        "musica": args.musica,
        "silencio": args.silencio,
    }

    for name, path in sources.items():
        if not path.exists():
            raise FileNotFoundError(
                f"Arquivo de {name} não encontrado: {path}"
            )

    if args.output_dir.exists() and not args.keep_existing:
        print(f"Removendo saída anterior: {args.output_dir}")
        shutil.rmtree(args.output_dir)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    metadata_path = args.output_dir / "metadata.csv"

    with metadata_path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as f:
        fields = [
            "file",
            "source_type",
            "source_file",
            "source_segment_start",
            "source_segment_end",
            "window_start_seconds",
            "window_end_seconds",
            "rms_dbfs",
            "peak",
            "zero_fraction",
        ]

        writer = csv.DictWriter(
            f,
            fieldnames=fields,
        )

        writer.writeheader()

        counts = {}

        for source_name in (
            "ambiente",
            "conversa",
            "musica",
            "silencio",
        ):
            counts[source_name] = extract_source(
                source_name=source_name,
                source_path=sources[source_name],
                ranges=SEGMENTS[source_name],
                output_root=args.output_dir,
                writer=writer,
            )

    total = sum(counts.values())

    print()
    print("=" * 72)
    print("HARD NEGATIVES GERADOS")
    print("=" * 72)

    for name, count in counts.items():
        print(f"{name:12} {count:4d}")

    print("-" * 72)
    print(f"Total:        {total:4d}")
    print(f"Metadata:     {metadata_path}")

    # Com os intervalos atuais, o total esperado é 47.
    expected = 47

    if total != expected:
        print(
            f"ATENÇÃO: esperávamos {expected} janelas com a configuração "
            f"atual, mas foram geradas {total}."
        )
    else:
        print("Quantidade esperada confirmada: 47 janelas.")


if __name__ == "__main__":
    main()
