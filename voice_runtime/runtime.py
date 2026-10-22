"""Keep one warmed TTS engine resident and serialize GPU work."""

from __future__ import annotations

import asyncio
import logging
from time import perf_counter
from typing import Protocol

from voice_runtime.streaming import split_phrases

logger = logging.getLogger(__name__)


class TtsEngine(Protocol):
    def load(self) -> None: ...
    def warmup(self) -> None: ...
    def unload(self) -> None: ...
    def synthesize(self, text: str) -> bytes: ...
    def synthesize_pcm(self, text: str) -> tuple[bytes, int]: ...


class VoiceRuntime:
    def __init__(self, tts: TtsEngine) -> None:
        self.tts = tts
        self._lock = asyncio.Lock()
        self._ready = False

    @property
    def is_ready(self) -> bool:
        return self._ready

    async def _call(self, function, *args):
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        cancelled = False
        # Cancelling an HTTP request cannot stop a running CUDA worker.
        # Retain the GPU lock until that worker actually finishes.
        while True:
            try:
                result = await asyncio.shield(task)
                break
            except asyncio.CancelledError:
                if task.cancelled():
                    raise
                cancelled = True
            except Exception:
                if cancelled:
                    raise asyncio.CancelledError from None
                raise
        if cancelled:
            raise asyncio.CancelledError
        return result

    async def _ensure_ready(self) -> None:
        if self._ready:
            return
        started = perf_counter()
        try:
            await self._call(self.tts.load)
            await self._call(self.tts.warmup)
        except BaseException:
            await self._call(self.tts.unload)
            raise
        self._ready = True
        logger.info("tts_ready startup_ms=%.1f", (perf_counter() - started) * 1000)

    async def warm_tts(self) -> None:
        async with self._lock:
            await self._ensure_ready()

    async def synthesize(self, text: str) -> bytes:
        queued = perf_counter()
        async with self._lock:
            started = perf_counter()
            await self._ensure_ready()
            try:
                return await self._call(self.tts.synthesize, text)
            finally:
                logger.info(
                    "tts_request queue_ms=%.1f work_ms=%.1f chars=%d",
                    (started - queued) * 1000,
                    (perf_counter() - started) * 1000,
                    len(text),
                )

    async def stream(self, text: str):
        queued = perf_counter()
        async with self._lock:
            logger.info('tts_stream queue_ms=%.1f', (perf_counter() - queued) * 1000)
            await self._ensure_ready()
            for phrase in split_phrases(text):
                yield await self._call(self.tts.synthesize_pcm, phrase)

    async def close(self) -> None:
        async with self._lock:
            if self._ready:
                self._ready = False
                await self._call(self.tts.unload)
