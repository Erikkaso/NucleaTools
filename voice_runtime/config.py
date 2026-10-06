"""Configuracao de voz do runtime unificado."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

VOICE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


@dataclass(frozen=True)
class VoiceSelection:
    name: str
    reference: Path | None
    used_fallback: bool


def select_voice(configured_voice: str, voices_dir: Path) -> VoiceSelection:
    """Seleciona uma referencia existente ou retorna a voz embutida padrao."""

    if configured_voice == "default":
        return VoiceSelection("default", None, False)
    if not VOICE_NAME.fullmatch(configured_voice):
        return VoiceSelection("default", None, True)
    reference = voices_dir / f"{configured_voice}.wav"
    if not reference.is_file():
        return VoiceSelection("default", None, True)
    return VoiceSelection(configured_voice, reference, False)
