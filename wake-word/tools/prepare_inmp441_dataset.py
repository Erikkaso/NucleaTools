from __future__ import annotations

import argparse
from array import array
import csv
import math
from pathlib import Path
import sys
import wave


SAMPLE_RATE = 16_000
SAMPLE_WIDTH = 2
FRAME_MS = 20
REGION_PADDING_MS = 40
MAX_GAP_MS = 300
MIN_REGION_MS = 120
CLIP_SECONDS = 1.0


def reviewed_candidate_files(review_dir: Path) -> list[Path]:
    return sorted(review_dir.glob("candidate_*.wav"))


def dbfs(samples: list[int]) -> float:
    if not samples:
        return -120.0
    rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples))
    return 20.0 * math.log10(max(rms, 1.0) / 32768.0)


def find_voice_regions(
    samples: list[int],
    sample_rate: int,
    threshold_dbfs: float,
) -> list[tuple[int, int]]:
    frame_samples = sample_rate * FRAME_MS // 1000
    pad_samples = sample_rate * REGION_PADDING_MS // 1000
    max_gap_samples = sample_rate * MAX_GAP_MS // 1000
    min_region_samples = sample_rate * MIN_REGION_MS // 1000
    active_frames: list[tuple[int, int]] = []

    for start in range(0, len(samples), frame_samples):
        end = min(start + frame_samples, len(samples))
        if dbfs(samples[start:end]) >= threshold_dbfs:
            active_frames.append((start, end))

    regions: list[tuple[int, int]] = []
    for start, end in active_frames:
        if regions and start - regions[-1][1] <= max_gap_samples:
            regions[-1] = (regions[-1][0], end)
        else:
            regions.append((start, end))

    return [
        (max(0, start - pad_samples), min(len(samples), end + pad_samples))
        for start, end in regions
        if end - start >= min_region_samples
    ]


def centered_clip(
    samples: list[int],
    region: tuple[int, int],
    target_samples: int,
) -> list[int]:
    center = (region[0] + region[1]) // 2
    start = center - target_samples // 2
    end = start + target_samples
    clip = samples[max(start, 0):min(end, len(samples))]
    left_padding = max(0, -start)
    right_padding = max(0, end - len(samples))
    return [0] * left_padding + clip + [0] * right_padding


def silence_windows(
    samples: list[int],
    voice_regions: list[tuple[int, int]],
    window_samples: int,
) -> list[tuple[int, int]]:
    windows: list[tuple[int, int]] = []
    for start in range(0, len(samples) - window_samples + 1, window_samples):
        end = start + window_samples
        if all(end <= region_start or start >= region_end for region_start, region_end in voice_regions):
            windows.append((start, end))
    return windows


def read_pcm16(path: Path) -> tuple[list[int], int]:
    with wave.open(str(path), "rb") as recording:
        if recording.getnchannels() != 1:
            raise ValueError("o WAV precisa ser mono")
        if recording.getsampwidth() != SAMPLE_WIDTH:
            raise ValueError("o WAV precisa usar PCM 16-bit")
        sample_rate = recording.getframerate()
        if sample_rate != SAMPLE_RATE:
            raise ValueError(f"o WAV precisa usar {SAMPLE_RATE} Hz")
        raw = recording.readframes(recording.getnframes())

    values = array("h")
    values.frombytes(raw)
    if sys.byteorder != "little":
        values.byteswap()
    return list(values), sample_rate


def write_pcm16(path: Path, samples: list[int], sample_rate: int) -> None:
    values = array("h", samples)
    if sys.byteorder != "little":
        values.byteswap()
    with wave.open(str(path), "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(SAMPLE_WIDTH)
        recording.setframerate(sample_rate)
        recording.writeframes(values.tobytes())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Gera candidatos revisaveis para o dataset do INMP441.",
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--threshold-dbfs", type=float, default=-42.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output_dir.exists():
        raise SystemExit(f"Destino ja existe: {args.output_dir}")

    samples, sample_rate = read_pcm16(args.input)
    regions = find_voice_regions(samples, sample_rate, args.threshold_dbfs)
    clip_samples = int(sample_rate * CLIP_SECONDS)
    quiet_windows = silence_windows(samples, regions, clip_samples)

    review_dir = args.output_dir / "review"
    silence_dir = args.output_dir / "negative_silence"
    review_dir.mkdir(parents=True)
    silence_dir.mkdir()
    manifest_path = args.output_dir / "manifest.csv"

    with manifest_path.open("w", newline="", encoding="utf-8") as manifest:
        writer = csv.DictWriter(
            manifest,
            fieldnames=[
                "file",
                "label",
                "kind",
                "source_file",
                "region_start_s",
                "region_end_s",
                "clip_start_s",
                "clip_end_s",
                "rms_dbfs",
            ],
        )
        writer.writeheader()

        for index, region in enumerate(regions, start=1):
            clip = centered_clip(samples, region, clip_samples)
            filename = review_dir / f"candidate_{index:04d}.wav"
            write_pcm16(filename, clip, sample_rate)
            center = (region[0] + region[1]) // 2
            clip_start = center - clip_samples // 2
            writer.writerow({
                "file": filename.relative_to(args.output_dir).as_posix(),
                "label": "review",
                "kind": "speech_candidate",
                "source_file": args.input.name,
                "region_start_s": f"{region[0] / sample_rate:.3f}",
                "region_end_s": f"{region[1] / sample_rate:.3f}",
                "clip_start_s": f"{clip_start / sample_rate:.3f}",
                "clip_end_s": f"{(clip_start + clip_samples) / sample_rate:.3f}",
                "rms_dbfs": f"{dbfs(clip):.2f}",
            })

        for index, (start, end) in enumerate(quiet_windows, start=1):
            clip = samples[start:end]
            filename = silence_dir / f"silence_{index:04d}.wav"
            write_pcm16(filename, clip, sample_rate)
            writer.writerow({
                "file": filename.relative_to(args.output_dir).as_posix(),
                "label": "negative",
                "kind": "silence",
                "source_file": args.input.name,
                "region_start_s": f"{start / sample_rate:.3f}",
                "region_end_s": f"{end / sample_rate:.3f}",
                "clip_start_s": f"{start / sample_rate:.3f}",
                "clip_end_s": f"{end / sample_rate:.3f}",
                "rms_dbfs": f"{dbfs(clip):.2f}",
            })

    print(f"Candidatos para revisao: {len(regions)}")
    print(f"Negativos de silencio: {len(quiet_windows)}")
    print(f"Manifesto: {manifest_path}")


if __name__ == "__main__":
    main()
