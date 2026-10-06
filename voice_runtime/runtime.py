"""Orquestracao serial de Whisper e Chatterbox sobre uma unica GPU."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol


class WhisperEngine(Protocol):
    def load(self) -> None: ...

    def unload(self) -> None: ...

    def transcribe(self, path: Path, language: str) -> str: ...


class TtsEngine(Protocol):
    def load(self) -> None: ...

    def unload(self) -> None: ...

    def synthesize(self, text: str) -> bytes: ...


class VoiceRuntime:
    """Garante que apenas um dos modelos permaneça residente na GPU."""

    def __init__(self, whisper: WhisperEngine, tts: TtsEngine) -> None:
        self.whisper = whisper
        self.tts = tts
        self._lease = asyncio.Lock()
        self._active: str | None = None
        self._warm_task: asyncio.Task[None] | None = None

    async def transcribe(self, path: Path, language: str) -> str:
        async with self._lease:
            await self._activate_whisper()
            text = await asyncio.to_thread(self.whisper.transcribe, path, language)
        self._warm_task = asyncio.create_task(self.warm_tts())
        return text

    async def warm_tts(self) -> None:
        async with self._lease:
            await self._activate_tts()

    async def synthesize(self, text: str) -> bytes:
        async with self._lease:
            await self._activate_tts()
            return await asyncio.to_thread(self.tts.synthesize, text)

    async def join(self) -> None:
        if self._warm_task is not None:
            await self._warm_task

    async def _activate_whisper(self) -> None:
        if self._active == "whisper":
            return
        if self._active == "tts":
            await asyncio.to_thread(self.tts.unload)
        await asyncio.to_thread(self.whisper.load)
        self._active = "whisper"

    async def _activate_tts(self) -> None:
        if self._active == "tts":
            return
        if self._active == "whisper":
            await asyncio.to_thread(self.whisper.unload)
        await asyncio.to_thread(self.tts.load)
        self._active = "tts"
