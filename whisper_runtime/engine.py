"""Adaptador local para o modelo faster-whisper."""

from __future__ import annotations

from pathlib import Path

from whisper_runtime.config import WhisperSettings


class FasterWhisperEngine:
    def __init__(self, settings: WhisperSettings) -> None:
        self.settings = settings
        self.model = None

    def load(self) -> None:
        if self.model is not None:
            return
        from faster_whisper import WhisperModel

        self.model = WhisperModel(
            self.settings.model,
            device=self.settings.device,
            compute_type=self.settings.compute_type,
        )

    def transcribe(self, path: Path, language: str) -> str:
        if self.model is None:
            raise RuntimeError("Whisper nao foi carregado")
        segments, _ = self.model.transcribe(str(path), language=language, vad_filter=True)
        return " ".join(segment.text.strip() for segment in segments).strip() or "Nenhuma fala foi detectada no audio."
