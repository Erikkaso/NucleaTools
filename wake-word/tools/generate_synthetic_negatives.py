"""Generate train-only Portuguese confusers, retaining full spoken sources."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unicodedata
import wave

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
VOICES = ("pt-BR-AntonioNeural", "pt-BR-FranciscaNeural", "pt-BR-ThalitaMultilingualNeural",
          "pt-PT-DuarteNeural", "pt-PT-RaquelNeural")
RATES = ("-15%", "+0%", "+15%")
PHRASES = (
    ("corno_1", "Corno."), ("corno_2", "Ele falou corno."), ("corno_3", "A palavra era corno."),
    ("problema_1", "Problema."), ("problema_2", "Qual \u00e9 o problema?"),
    ("problema_3", "O problema foi resolvido."),
    ("singapura_1", "Singapura."), ("singapura_2", "Uma viagem para Singapura."),
    ("singapura_3", "Ela mora em Singapura."),
    ("irma_1", "Irm\u00e3."), ("irma_2", "Minha irm\u00e3 chegou."),
    ("irma_3", "Fale com a minha irm\u00e3."),
    ("nunca", "Nunca."), ("nenhuma", "Nenhuma dessas op\u00e7\u00f5es."),
    ("nucleo", "O n\u00facleo do projeto."), ("nuclear", "Uma usina nuclear."),
)


def validate_negative(text):
    plain = "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))
    if re.search(r"\bnuclea\b", plain):
        raise ValueError("Negative text cannot contain the wakeword.")


def group_id(voice, phrase):
    return f"synthetic:{voice}:{phrase}"


def read_wav(path):
    with wave.open(str(path), "rb") as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (1, 2, 16000):
            raise ValueError(f"Expected mono PCM16 16 kHz: {path}")
        return np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2").astype(np.float32) / 32768


def cap_peak(audio):
    peak = float(np.max(np.abs(audio))) if len(audio) else 0
    return np.asarray(audio * min(1., .98 / max(peak, 1e-12)), dtype=np.float32)


def write_wav(path, audio):
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.rint(cap_peak(audio) * 32768).astype("<i2")
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(pcm.tobytes())


def choose_windows(audio):
    if len(audio) < 16000:
        return []
    candidates = sorted(set(range(0, len(audio) - 15999, 3840)) | {len(audio) - 16000})
    candidates = [start for start in candidates
                  if np.sqrt(np.mean(audio[start:start + 16000] ** 2)) > 10 ** (-45 / 20)]
    if not candidates:
        return []
    return sorted({candidates[int(i)] for i in np.linspace(0, len(candidates) - 1, min(3, len(candidates)))})


def variants(audio, noise, rng):
    start = int(rng.integers(0, len(noise) - 16000 + 1))
    ambient = noise[start:start + 16000]
    noise_rms = float(np.sqrt(np.mean(ambient ** 2)))
    if noise_rms < 1e-8:
        raise ValueError("Ambient reference is silent.")
    rms = float(np.sqrt(np.mean(audio ** 2)))
    mixed = audio + ambient * (rms / (10 ** (18 / 20)) / noise_rms)
    return {"clean": cap_peak(audio), "quiet": cap_peak(audio * 10 ** (-9 / 20)),
            "ambient": cap_peak(mixed)}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_manifest(path, manifest):
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


async def generate(args):
    import edge_tts
    import importlib.metadata
    output = args.output.resolve()
    training = ROOT / "dataset/background_hard_negative/generated/synthetic_confusers_v1"
    manifest_path = output / "manifest.json"
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("Install FFmpeg and add it to PATH.")
    for _, text in PHRASES:
        validate_negative(text)
    policy = {"version": 1, "seed": 20261025, "voices": list(VOICES), "rates": list(RATES),
              "phrases": [list(p) for p in PHRASES], "label": 0, "split": "train",
              "noise": str(args.noise.resolve()), "noise_sha256": digest(args.noise),
              "sample_rate": 16000, "ambient_snr_db": 18, "quiet_gain_db": -9,
              "source_padding_seconds": [.2, .35], "max_windows_per_source": 3,
              "tts": "edge-tts", "tts_version": importlib.metadata.version("edge-tts")}
    if manifest_path.exists():
        if not args.resume:
            raise RuntimeError("Corpus already exists; use --resume to verify and complete it.")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["policy"] != policy:
            raise RuntimeError("Existing corpus generation settings differ.")
    else:
        if (output.exists() and any(output.iterdir())) or (training.exists() and any(training.iterdir())):
            raise RuntimeError("Refusing to overwrite an untracked existing corpus.")
        manifest = {"policy": policy, "sources": [], "failures": [],
                    "limitations": "TTS-generated labels, not human transcription; training only. No model retraining."}
    output.mkdir(parents=True, exist_ok=True)
    save_manifest(manifest_path, manifest)
    completed = {record["id"] for record in manifest["sources"]}
    for record in manifest["sources"]:
        for file in [record["source"], *record["windows"]]:
            path = (ROOT / file["file"]).resolve()
            if not path.is_relative_to(ROOT / "dataset") or digest(path) != file["sha256"]:
                raise RuntimeError(f"Existing audio is missing or changed: {path}")
    noise = read_wav(args.noise)
    semaphore = asyncio.Semaphore(2)

    def record_file(path):
        return {"file": path.relative_to(ROOT).as_posix(), "sha256": digest(path)}

    async def run_job(voice, phrase, text, rate):
        identity = f"{voice}_{phrase}_{rate.replace('+', 'plus').replace('-', 'minus').replace('%', '')}"
        if identity in completed:
            return
        async with semaphore:
            try:
                with tempfile.TemporaryDirectory(prefix="nuclea-negative-") as temporary:
                    mp3 = Path(temporary) / "source.mp3"
                    wav = Path(temporary) / "source.wav"
                    for attempt in range(3):
                        try:
                            await asyncio.wait_for(edge_tts.Communicate(text, voice, rate=rate).save(str(mp3)), 30)
                            break
                        except Exception as error:
                            if attempt == 2 or getattr(error, "status", None) in (401, 403):
                                raise
                            await asyncio.sleep(2 ** attempt)
                    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(mp3),
                                    "-af", "adelay=200,apad=pad_dur=0.35", "-ac", "1", "-ar", "16000",
                                    "-c:a", "pcm_s16le", str(wav)], check=True)
                    audio = read_wav(wav)
                    if len(audio) < 16000:
                        audio = np.pad(audio, (0, 16000 - len(audio)))
                    starts = choose_windows(audio)
                    if not starts:
                        raise ValueError("TTS did not produce enough speech energy.")
                    source = output / "sources" / f"{identity}.wav"
                    write_wav(source, audio)
                    seed = int(hashlib.sha256(identity.encode()).hexdigest()[:8], 16) ^ policy["seed"]
                    rng = np.random.default_rng(seed)
                    windows = []
                    for number, start in enumerate(starts):
                        for name, data in variants(audio[start:start + 16000], noise, rng).items():
                            path = training / f"{identity}_w{number}_{name}.wav"
                            write_wav(path, data)
                            windows.append({**record_file(path), "variant": name, "start_sample": start})
                    manifest["sources"].append({"id": identity, "voice": voice, "text": text, "rate": rate,
                        "group_id": group_id(voice, phrase), "label": 0, "split": "train",
                        "duration_seconds": len(audio) / 16000, "source": record_file(source), "windows": windows})
                    print(f"Generated {len(manifest['sources'])}/240: {identity}", flush=True)
            except Exception as error:
                # Do not log service exception URLs or provider handshake tokens.
                manifest["failures"].append({"id": identity, "error": type(error).__name__})
                print(f"Failed: {identity}: {type(error).__name__}", flush=True)
            save_manifest(manifest_path, manifest)

    manifest["failures"] = []
    await asyncio.gather(*(run_job(voice, phrase, text, rate)
        for voice in VOICES for phrase, text in PHRASES for rate in RATES))
    manifest["summary"] = {"sources": len(manifest["sources"]),
                           "training_windows": sum(len(r["windows"]) for r in manifest["sources"]),
                           "failures": len(manifest["failures"])}
    save_manifest(manifest_path, manifest)
    print(json.dumps(manifest["summary"]), flush=True)
    if manifest["failures"]:
        raise RuntimeError("Some sources failed. Use --resume to retry only missing jobs.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dataset/synthetic_negatives_v1")
    parser.add_argument("--noise", type=Path, default=ROOT / "dataset/inmp441_v1/ambiente/sessao_001.wav")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to(ROOT / "dataset"):
        parser.error("Output must stay inside this project's dataset directory.")
    asyncio.run(generate(args))


if __name__ == "__main__":
    main()
