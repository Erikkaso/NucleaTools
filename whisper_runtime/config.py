"""Configuracao do runtime Whisper."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class WhisperSettings:
    model: str
    device: str
    compute_type: str
    language: str

    @classmethod
    def from_environment(cls) -> WhisperSettings:
        return cls(
            model=os.getenv("WHISPER_MODEL", "small"),
            device=os.getenv("WHISPER_DEVICE", "cpu"),
            compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "int8"),
            language=os.getenv("WHISPER_LANGUAGE", "pt"),
        )
