"""Convert the local test song to flash-streamable PCM without changing its source."""
import argparse
import csv
import json
from pathlib import Path
import shutil
import subprocess

PROJECT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    args = parser.parse_args()
    source = args.input
    if source is None:
        songs = list(PROJECT.parent.parent.glob("*.mp3"))
        if len(songs) != 1:
            parser.error("Use --input para selecionar uma unica musica MP3.")
        source = songs[0]
    if not source.is_file():
        parser.error("Arquivo de entrada nao encontrado.")
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            parser.error(f"{tool} nao encontrado no PATH.")
    with (PROJECT / "partitions.csv").open(newline="") as stream:
        partition = next(row for row in csv.reader(stream)
                         if row and row[0].strip() == "spiffs")
    limit = int(partition[4].strip(), 0) - 256 * 1024
    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "json", str(source),
    ], check=True, capture_output=True, text=True)
    duration = float(json.loads(probe.stdout)["format"]["duration"])
    if duration <= 0 or duration * 48000 > limit:
        parser.error("A musica inteira nao cabe na particao de teste.")
    output = PROJECT / "main" / "speaker_test_data" / "music.pcm"
    output.parent.mkdir(parents=True, exist_ok=True)
    # Keep the left channel: averaging headphone stereo can cancel opposite phases.
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
        "-map", "0:a:0", "-af", "pan=mono|c0=c0", "-ar", "24000",
        "-c:a", "pcm_s16le", "-f", "s16le", str(output),
    ], check=True)
    size = output.stat().st_size
    if not size or size % 2 or size > limit:
        raise ValueError("PCM gerado invalido ou maior que a particao.")
    print(f"Musica completa: {size / 48000:.2f}s, {size} bytes, PCM16 mono 24000 Hz")
    print(output)


if __name__ == "__main__":
    main()
