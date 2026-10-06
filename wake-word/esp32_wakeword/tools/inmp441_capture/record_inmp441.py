from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import time
import wave


STREAM_MAGIC = b"NCAP"
STREAM_ERROR = b"ERRO"
START_COMMAND = b"S"
SAMPLE_RATE = 16_000
SAMPLE_WIDTH = 2
CHANNELS = 1


class PcmStreamDecoder:
    def __init__(self) -> None:
        self._buffer = bytearray()
        self._synchronized = False

    def feed(self, data: bytes) -> bytes:
        self._buffer.extend(data)

        if not self._synchronized:
            error_marker = self._buffer.find(STREAM_ERROR)
            marker = self._buffer.find(STREAM_MAGIC)
            if error_marker >= 0 and (marker < 0 or error_marker < marker):
                raise RuntimeError("ESP nao conseguiu iniciar o I2S do INMP441")

            if marker < 0:
                keep = max(len(STREAM_MAGIC), len(STREAM_ERROR)) - 1
                if len(self._buffer) > keep:
                    del self._buffer[:-keep]
                return b""

            del self._buffer[:marker + len(STREAM_MAGIC)]
            self._synchronized = True

        complete_size = len(self._buffer) & ~1
        if complete_size == 0:
            return b""

        pcm = bytes(self._buffer[:complete_size])
        del self._buffer[:complete_size]
        return pcm

    @property
    def synchronized(self) -> bool:
        return self._synchronized


def default_output_path() -> Path:
    wakeword_root = Path(__file__).resolve().parents[3]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return wakeword_root / "dataset" / "inmp441_v1" / "continuous" / f"inmp441_{timestamp}.wav"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Grava PCM do INMP441 enviado pelo sketch serial ate Ctrl+C.",
    )
    parser.add_argument("--port", required=True, help="Ex.: COM9")
    parser.add_argument("--output", type=Path, default=default_output_path())
    parser.add_argument("--baud", type=int, default=921600)
    parser.add_argument("--wait-seconds", type=float, default=15.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        import serial
    except ImportError as error:
        raise SystemExit("Instale pyserial: pip install pyserial") from error

    args.output.parent.mkdir(parents=True, exist_ok=True)
    decoder = PcmStreamDecoder()
    captured_bytes = 0
    started_at = time.monotonic()
    last_status_at = started_at
    next_start_at = started_at

    try:
        with serial.Serial(args.port, args.baud, timeout=1) as device:
            device.reset_input_buffer()
            with wave.open(str(args.output), "wb") as output:
                output.setnchannels(CHANNELS)
                output.setsampwidth(SAMPLE_WIDTH)
                output.setframerate(SAMPLE_RATE)
                print(f"Aguardando INMP441 em {args.port}. Ctrl+C para encerrar.")

                while True:
                    now = time.monotonic()
                    if not decoder.synchronized and now >= next_start_at:
                        device.write(START_COMMAND)
                        device.flush()
                        next_start_at = now + 0.25

                    raw = device.read(device.in_waiting or 4096)
                    pcm = decoder.feed(raw)
                    now = time.monotonic()

                    if not decoder.synchronized and now - started_at > args.wait_seconds:
                        raise RuntimeError("Nao recebi a confirmacao NCAP do ESP")

                    if not pcm:
                        continue

                    output.writeframesraw(pcm)
                    captured_bytes += len(pcm)

                    if now - last_status_at >= 5:
                        seconds = captured_bytes / (SAMPLE_RATE * SAMPLE_WIDTH)
                        print(f"Gravando: {seconds:.1f}s -> {args.output}")
                        last_status_at = now
    except KeyboardInterrupt:
        seconds = captured_bytes / (SAMPLE_RATE * SAMPLE_WIDTH)
        print(f"\nGravacao finalizada: {seconds:.1f}s -> {args.output}")
    except Exception as error:
        raise SystemExit(f"Falha na captura: {error}") from error


if __name__ == "__main__":
    main()
