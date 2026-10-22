"""Resident Chatterbox engine and in-memory MP3 encoding."""

from __future__ import annotations

import gc
import logging
import os
from pathlib import Path
from time import perf_counter

from voice_runtime.config import VoiceSelection, select_voice
from voice_runtime.voice_cache import cache_path_for_voice, load_or_prepare

logger = logging.getLogger(__name__)


class LocalChatterboxEngine:
    def __init__(self) -> None:
        self.model = None
        self.voice: VoiceSelection | None = None

    def load(self) -> None:
        if self.model is not None:
            return
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        self.model = ChatterboxMultilingualTTS.from_pretrained(device="cuda")
        self.voice = select_voice(os.getenv("TTS_VOICE", "default"), Path(os.getenv("TTS_VOICES_DIR", "/voices")))
        if self.voice.used_fallback:
            logger.warning("Voz TTS configurada nao encontrada; usando a voz default")
        if self.voice.reference is not None:
            exaggeration = float(os.getenv("TTS_EXAGGERATION", "0.5"))
            cache_path = cache_path_for_voice(
                self.voice.name,
                self.voice.reference,
                Path(os.getenv("TTS_VOICE_CACHE_DIR", "/voice-cache")),
                os.getenv("TTS_MODEL_REVISION", "v3"),
                exaggeration,
            )
            load_or_prepare(self.model, self.voice.reference, cache_path, exaggeration)

    def unload(self) -> None:
        self.model = None
        self.voice = None
        _release_cuda()

    def warmup(self) -> None:
        text = os.getenv("TTS_WARMUP_TEXT", "Ola.").strip()
        if text:
            self.synthesize(text)

    def synthesize(self, text: str) -> bytes:
        if self.model is None:
            raise RuntimeError("Chatterbox nao foi carregado")
        started = perf_counter()
        waveform = self.model.generate(
            text,
            language_id=os.getenv("TTS_LANGUAGE_ID", "pt"),
            exaggeration=float(os.getenv("TTS_EXAGGERATION", "0.5")),
            cfg_weight=float(os.getenv("TTS_CFG_WEIGHT", "0.5")),
        )
        samples = waveform.squeeze(0).cpu().numpy()
        generated = perf_counter()
        audio = encode_mp3(samples, self.model.sr)
        encoded = perf_counter()
        logger.info(
            "tts_synthesis generation_ms=%.1f encoding_ms=%.1f audio_seconds=%.2f chars=%d",
            (generated - started) * 1000,
            (encoded - generated) * 1000,
            len(samples) / self.model.sr,
            len(text),
        )
        return audio


def encode_mp3(waveform, sample_rate: int) -> bytes:
    import lameenc
    import numpy as np

    encoder = lameenc.Encoder()
    encoder.set_bit_rate(int(os.getenv("TTS_MP3_BITRATE", "128")))
    encoder.set_in_sample_rate(sample_rate)
    encoder.set_channels(1)
    encoder.set_quality(2)
    pcm = (np.clip(waveform, -1.0, 1.0) * 32767.0).astype("<i2")
    return bytes(encoder.encode(pcm.tobytes()) + encoder.flush())


def _release_cuda() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass
