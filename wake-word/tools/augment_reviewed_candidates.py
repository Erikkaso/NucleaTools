from __future__ import annotations

import argparse
import csv
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import wave

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "train_models"))
from noise_augmentation import mix_at_snr


SAMPLE_RATE = 16000
SAMPLES = 16000
OUTPUT_NAMES = ("clean", "augmented", "metadata.csv", "augmentation_report.json")
FIELDS = (
    "file", "group_id", "variant", "source_file", "source_clip", "source_sha256",
    "source_start_s", "source_end_s", "gain_db", "stretch_rate",
    "pitch_semitones", "shift_samples", "snr_db", "denoise_filter",
)


def read_audio(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as stream:
        shape = (stream.getnchannels(), stream.getsampwidth(), stream.getframerate(), stream.getnframes())
        if shape != (1, 2, SAMPLE_RATE, SAMPLES):
            raise ValueError(f"WAV deve ser mono PCM16, 16 kHz e 1 segundo: {path}: {shape}")
        return np.frombuffer(stream.readframes(SAMPLES), dtype="<i2").astype(np.float32) / 32768.0


def write_audio(path: Path, audio: np.ndarray) -> None:
    audio = np.asarray(audio)
    if audio.shape != (SAMPLES,) or not np.isfinite(audio).all():
        raise ValueError("Audio invalido: esperado 1 segundo de amostras finitas")
    pcm = np.rint(np.clip(audio, -1.0, 32767 / 32768) * 32768).astype("<i2")
    with path.open("xb") as output:
        with wave.open(output, "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(SAMPLE_RATE)
            stream.writeframes(pcm.tobytes())


def assess_noise(audio: np.ndarray) -> dict:
    frames = np.asarray(audio, dtype=np.float64).reshape(-1, 320)
    levels = 20 * np.log10(np.maximum(np.sqrt(np.mean(frames ** 2, axis=1)), 1e-7))
    floor, active = np.percentile(levels, [10, 80])
    return {
        "low_energy_proxy_dbfs": float(floor),
        "energy_range_db": float(active - floor),
        "near_clip_fraction": float(np.mean(np.abs(audio) >= 0.999)),
        # A low-energy percentile is a screening proxy, not a measured SNR.
        "filter_recommended": bool(floor > -45),
    }


def cap_peak(audio: np.ndarray, ceiling: float = 0.98) -> np.ndarray:
    peak = float(np.max(np.abs(audio)))
    return (audio * min(1.0, ceiling / max(peak, 1e-12))).astype(np.float32)


def safe_shift(audio: np.ndarray, requested: int) -> tuple[np.ndarray, int]:
    total_energy = float(np.sum(np.square(audio.astype(np.float64))))
    direction = 1 if requested >= 0 else -1
    for size in range(min(abs(requested), SAMPLES - 1), 0, -160):
        discarded = audio[-size:] if direction > 0 else audio[:size]
        if float(np.sum(discarded.astype(np.float64) ** 2)) > total_energy * 0.0001:
            continue
        shifted = np.zeros_like(audio)
        if direction > 0:
            shifted[size:] = audio[:-size]
        else:
            shifted[:-size] = audio[size:]
        return shifted, direction * size
    return audio.copy(), 0


def make_variants(audio: np.ndarray, seed: int) -> list[tuple[str, np.ndarray, dict]]:
    import librosa

    rng = np.random.default_rng(seed)
    shifted, offset = safe_shift(audio, 960 if rng.random() < 0.5 else -960)
    speed = 1.04 + float(rng.uniform(0, 0.02))
    faster = librosa.effects.time_stretch(audio, rate=speed)
    if len(faster) > SAMPLES:
        raise ValueError("Augmentation nao pode cortar a palavra")
    padding = SAMPLES - len(faster)
    faster = np.pad(faster, (padding // 2, padding - padding // 2))
    semitones = 0.5 if rng.random() < 0.5 else -0.5
    pitched = librosa.effects.pitch_shift(audio, sr=SAMPLE_RATE, n_steps=semitones)
    snr = float(rng.uniform(22, 28))
    noise = rng.normal(size=SAMPLES).astype(np.float32)
    noisy = mix_at_snr(cap_peak(audio, 0.7), noise, snr)
    variants = [
        ("gain_shift", shifted * 10 ** (-3 / 20), {"gain_db": -3, "shift_samples": offset}),
        ("tempo", faster * 0.9, {"stretch_rate": speed}),
        ("pitch", pitched * 0.9, {"pitch_semitones": semitones}),
        ("noise", noisy, {"snr_db": snr}),
    ]
    return [(name, cap_peak(data), settings) for name, data, settings in variants]


def filter_audio(audio: np.ndarray, ffmpeg: str, filters: str) -> np.ndarray:
    result = subprocess.run(
        [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
         "-f", "f32le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", "pipe:0",
         "-af", filters, "-f", "f32le", "pipe:1"],
        input=np.asarray(audio, dtype="<f4").tobytes(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=30,
    )
    return np.frombuffer(result.stdout, dtype="<f4").copy()


@lru_cache(maxsize=1)
def filter_latency(ffmpeg: str) -> int:
    probe = np.zeros(SAMPLES, dtype=np.float32)
    probe[SAMPLES // 2] = 0.7
    filtered = filter_audio(probe, ffmpeg, "highpass=f=70,afftdn=nr=6:nf=-50:gs=5")
    delay = int(np.argmax(np.abs(filtered))) - SAMPLES // 2
    if not 0 <= delay <= 1600:
        raise ValueError(f"Latencia inesperada do filtro: {delay} amostras")
    return delay


def denoise_audio(audio: np.ndarray, ffmpeg: str, floor_dbfs: float) -> np.ndarray:
    floor = min(-35.0, max(-60.0, floor_dbfs - 6))
    filters = f"highpass=f=70,afftdn=nr=6:nf={floor:.2f}:gs=5"
    delay = filter_latency(ffmpeg)
    # Flush delayed samples before trimming, so the word's ending is preserved.
    filtered = filter_audio(np.pad(audio, (0, delay)), ffmpeg, filters)
    aligned = filtered[delay:delay + SAMPLES]
    if aligned.shape != (SAMPLES,) or not np.isfinite(aligned).all():
        raise ValueError("Filtro retornou audio truncado ou invalido")
    return cap_peak(aligned)


def reviewed_inputs(speaker: Path) -> list[Path]:
    if any((speaker / name).exists() for name in OUTPUT_NAMES):
        raise FileExistsError(f"Saida ja existe, nada sera sobrescrito: {speaker}")
    files = sorted((speaker / "review").glob("candidate_*.wav"))
    if not files:
        raise ValueError(f"Nenhum candidato validado encontrado: {speaker}")
    return files


def process_speaker(speaker: Path, ffmpeg: str, seed: int = 42) -> dict:
    files = reviewed_inputs(speaker)
    with (speaker / "manifest.csv").open(encoding="utf-8-sig", newline="") as stream:
        manifest = {row["file"].replace("\\", "/"): row for row in csv.DictReader(stream)}
    for source in files:
        read_audio(source)
        if source.relative_to(speaker).as_posix() not in manifest:
            raise ValueError(f"Candidato sem procedencia no manifest.csv: {source}")
    (speaker / "clean").mkdir()
    (speaker / "augmented").mkdir()
    rows = []
    quality = []
    for source in files:
        audio = read_audio(source)
        relative = source.relative_to(speaker).as_posix()
        original = manifest[relative]
        recording = original.get("source_file") or "unknown_recording"
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        group_key = f"{speaker.name}/{recording}"
        group_id = speaker.name + "_" + hashlib.sha256(group_key.encode()).hexdigest()[:12]
        stem = f"nuclea_{speaker.name.removeprefix('wakeword_')}_{source.stem}"
        clean = speaker / "clean" / f"{stem}.wav"
        shutil.copy2(source, clean)
        base = {
            "group_id": group_id, "source_file": recording,
            "source_clip": relative, "source_sha256": digest,
            "source_start_s": original.get("clip_start_s", ""),
            "source_end_s": original.get("clip_end_s", ""),
        }
        rows.append({**base, "file": clean.relative_to(speaker).as_posix(), "variant": "clean"})
        file_seed = seed + int(hashlib.sha256((speaker.name + relative + digest).encode()).hexdigest()[:8], 16)
        variants = make_variants(audio, file_seed)
        assessment = assess_noise(audio)
        if assessment["filter_recommended"]:
            denoised = denoise_audio(audio, ffmpeg, assessment["low_energy_proxy_dbfs"])
            variants.append(("denoised", denoised, {"denoise_filter": "highpass_70Hz_afftdn_6dB_latency_compensated"}))
        quality.append({"source_clip": relative, **assessment})
        for name, augmented, settings in variants:
            destination = speaker / "augmented" / f"{stem}_aug_{name}.wav"
            write_audio(destination, augmented)
            rows.append({**base, **settings, "file": destination.relative_to(speaker).as_posix(), "variant": name})
    with (speaker / "metadata.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    report = {
        "review_confirmation": "User validated the remaining files in review/",
        "seed": seed, "clean_count": len(files),
        "augmented_count": len(rows) - len(files),
        "denoised_count": sum(item["filter_recommended"] for item in quality),
        "recording_groups": len({row["group_id"] for row in rows}),
        "grouping": "Original recording; never split its variants between train and validation",
        "noise_assessment": "Low-energy proxy, not measured SNR; filtering cannot remove other speakers or repair clipping",
        "training": "No training run; new speakers are not automatically registered in REAL_SPEAKERS",
        "clips": quality,
    }
    with (speaker / "augmentation_report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Promove candidatos revisados e cria augmentations sem alterar originais")
    parser.add_argument("--speaker-dir", type=Path, nargs="+", required=True)
    parser.add_argument("--confirmed-reviewed", action="store_true", required=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    speakers = [path.resolve() for path in args.speaker_dir]
    if len(set(speakers)) != len(speakers):
        parser.error("Uma pasta de locutor foi repetida")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        parser.error("FFmpeg precisa estar no PATH")
    for speaker in speakers:
        reviewed_inputs(speaker)
    for speaker in speakers:
        report = process_speaker(speaker, ffmpeg, args.seed)
        print(f"{speaker.name}: clean={report['clean_count']} augmented={report['augmented_count']} denoised={report['denoised_count']}", flush=True)


if __name__ == "__main__":
    main()
