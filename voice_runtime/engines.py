"""Engines locais de Whisper e Chatterbox usados pelo runtime unificado."""

from __future__ import annotations

import gc
import logging
import os
from pathlib import Path

from voice_runtime.config import VoiceSelection, select_voice
from voice_runtime.voice_cache import cache_path_for_voice, load_or_prepare

logger = logging.getLogger(__name__)


class LocalWhisperEngine:
    def __init__(self) -> None:
        self.model = None

    def load(self) -> None:
        if self.model is None:
            from faster_whisper import WhisperModel

            self.model = WhisperModel(
                os.getenv("WHISPER_MODEL", "large-v3-turbo"),
                device=os.getenv("WHISPER_DEVICE", "cuda"),
                compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "int8_float16"),
            )

    def unload(self) -> None:
        self.model = None
        _release_cuda()

    def transcribe(self, path: Path, language: str) -> str:
        if self.model is None:
            raise RuntimeError("Whisper nao foi carregado")
        segments, _ = self.model.transcribe(str(path), language=language, vad_filter=True)
        return " ".join(segment.text.strip() for segment in segments).strip() or "Nenhuma fala foi detectada no audio."


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

    def synthesize(self, text: str) -> bytes:
        if self.model is None:
            raise RuntimeError("Chatterbox nao foi carregado")
        waveform = self.model.generate(
            text,
            language_id=os.getenv("TTS_LANGUAGE_ID", "pt"),
            exaggeration=float(os.getenv("TTS_EXAGGERATION", "0.5")),
            cfg_weight=float(os.getenv("TTS_CFG_WEIGHT", "0.5")),
        )
        return encode_mp3(waveform.squeeze(0).cpu().numpy(), self.model.sr)


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
