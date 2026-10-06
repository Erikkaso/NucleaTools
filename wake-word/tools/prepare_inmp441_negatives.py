from __future__ import annotations

import argparse
import csv
from pathlib import Path

from prepare_inmp441_dataset import (
    CLIP_SECONDS,
    dbfs,
    read_pcm16,
    write_pcm16,
)


NEGATIVE_KINDS = ("ambient", "silence", "dialogue")


def evenly_spaced_starts(
    total_samples: int,
    window_samples: int,
    count: int,
) -> list[int]:
    if window_samples <= 0:
        raise ValueError("window_samples precisa ser positivo")
    if count <= 0 or total_samples < window_samples:
        return []

    available_windows = total_samples // window_samples
    selected = min(count, available_windows)
    last_start = total_samples - window_samples

    if selected == 1:
        return [last_start // 2]

    return [
        round(index * last_start / (selected - 1))
        for index in range(selected)
    ]


def targeted_starts(
    event_samples: list[int],
    total_samples: int,
    window_samples: int,
    hop_samples: int,
    context_samples: int,
) -> list[int]:
    if window_samples <= 0 or hop_samples <= 0 or context_samples < 0:
        raise ValueError("janela, hop e contexto devem ser validos")

    last_start = total_samples - window_samples
    if last_start < 0:
        return []

    starts: set[int] = set()
    for event in event_samples:
        first = max(0, event - context_samples)
        last = min(last_start, event + context_samples)
        starts.update(range(first, last + 1, hop_samples))

    return sorted(starts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extrai negativos espacados de uma gravacao INMP441.",
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-clips", type=int, required=True)
    parser.add_argument("--kind", choices=NEGATIVE_KINDS, required=True)
    parser.add_argument(
        "--event-ms",
        type=int,
        action="append",
        default=[],
        help="Instante de um falso positivo; extrai janelas sobrepostas ao redor dele.",
    )
    parser.add_argument("--context-ms", type=int, default=500)
    parser.add_argument("--hop-ms", type=int, default=250)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output_dir.exists():
        raise SystemExit(f"Destino ja existe: {args.output_dir}")

    samples, sample_rate = read_pcm16(args.input)
    clip_samples = int(sample_rate * CLIP_SECONDS)
    if args.event_ms:
        starts = targeted_starts(
            event_samples=[round(value * sample_rate / 1000) for value in args.event_ms],
            total_samples=len(samples),
            window_samples=clip_samples,
            hop_samples=round(args.hop_ms * sample_rate / 1000),
            context_samples=round(args.context_ms * sample_rate / 1000),
        )
    else:
        starts = evenly_spaced_starts(
            total_samples=len(samples),
            window_samples=clip_samples,
            count=args.max_clips,
        )

    args.output_dir.mkdir(parents=True)
    manifest_path = args.output_dir / "manifest.csv"
    with manifest_path.open("w", newline="", encoding="utf-8") as manifest:
        writer = csv.DictWriter(
            manifest,
            fieldnames=[
                "file",
                "label",
                "kind",
                "source_file",
                "clip_start_s",
                "clip_end_s",
                "rms_dbfs",
            ],
        )
        writer.writeheader()
        for index, start in enumerate(starts, start=1):
            end = start + clip_samples
            clip = samples[start:end]
            filename = args.output_dir / f"{args.kind}_{index:04d}.wav"
            write_pcm16(filename, clip, sample_rate)
            writer.writerow({
                "file": filename.name,
                "label": "negative",
                "kind": args.kind,
                "source_file": args.input.name,
                "clip_start_s": f"{start / sample_rate:.3f}",
                "clip_end_s": f"{end / sample_rate:.3f}",
                "rms_dbfs": f"{dbfs(clip):.2f}",
            })

    print(f"Negativos gerados: {len(starts)}")
    print(f"Manifesto: {manifest_path}")


if __name__ == "__main__":
    main()
