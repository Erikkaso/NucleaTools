"""Persistencia dos condicionamentos preparados de uma voz Chatterbox."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def cache_path_for_voice(voice: str, reference: Path, cache_dir: Path, revision: str, exaggeration: float) -> Path:
    digest = hashlib.sha256(reference.read_bytes()).hexdigest()
    identity = f"{voice}|{digest}|{revision}|{exaggeration:.6f}".encode()
    return cache_dir / f"{hashlib.sha256(identity).hexdigest()}.pt"


def load_or_prepare(model: Any, reference: Path, cache_path: Path, exaggeration: float) -> bool:
    """Retorna ``True`` quando restaurou o cache existente."""

    if cache_path.is_file():
        model.conds = _load_conditionals().load(cache_path, map_location="cpu").to(model.device)
        return True
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    model.prepare_conditionals(str(reference), exaggeration=exaggeration)
    temporary = cache_path.with_suffix(".tmp")
    model.conds.save(temporary)
    temporary.replace(cache_path)
    return False


def _load_conditionals() -> Any:
    from chatterbox.mtl_tts import Conditionals

    return Conditionals
