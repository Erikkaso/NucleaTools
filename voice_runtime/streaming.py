"""Short-lived text tickets and progressive PCM framing."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import secrets
from contextlib import suppress
from time import monotonic, perf_counter

logger = logging.getLogger(__name__)


class StreamTickets:
    def __init__(self, capacity=32, ttl=120, clock=monotonic):
        self.capacity, self.ttl, self.clock = capacity, ttl, clock
        self._tickets: dict[str, tuple[float, str]] = {}

    def _prune(self):
        now = self.clock()
        self._tickets = {key: item for key, item in self._tickets.items() if item[0] > now}

    def create(self, text: str) -> str:
        self._prune()
        if len(self._tickets) >= self.capacity:
            raise OverflowError('Stream ticket capacity reached')
        token = secrets.token_urlsafe(32)
        self._tickets[token] = (self.clock() + self.ttl, text)
        return token

    def take(self, token: str) -> str:
        self._prune()
        return self._tickets.pop(token)[1]


def split_phrases(text: str, max_chars: int = 160) -> list[str]:
    phrases = []
    for sentence in re.split(r'(?<=[.!?;:])\s+', ' '.join(text.split())):
        words = sentence.split()
        current = ''
        for word in words:
            if current and len(current) + len(word) + 1 > max_chars:
                phrases.append(current)
                current = ''
            current = f'{current} {word}'.strip()
        if current:
            phrases.append(current)
    return phrases


def event_line(event: dict) -> bytes:
    return (json.dumps(event, separators=(',', ':')) + '\n').encode()


async def pcm_events(runtime, text: str, stream_id: str, progress_timeout: float = 90):
    source = runtime.stream(text)
    pending = None
    started = perf_counter()
    seq = 0
    try:
        yield event_line({'type': 'start', 'format': 'pcm_s16le', 'channels': 1})
        while True:
            pending = asyncio.create_task(anext(source))
            deadline = perf_counter() + progress_timeout
            while True:
                remaining = deadline - perf_counter()
                if remaining <= 0:
                    logger.error('tts_stream_progress_timeout stream_id=%s', stream_id)
                    yield event_line({'type': 'error', 'code': 'audio_progress_timeout',
                                      'message': 'A geracao de voz demorou demais. Tente novamente.'})
                    return
                if (await asyncio.wait({pending}, timeout=min(10, remaining)))[0]:
                    break
                yield event_line({'type': 'ping'})
            try:
                pcm, sample_rate = pending.result()
            except StopAsyncIteration:
                break
            pending = None
            if seq == 0:
                logger.info('tts_stream first_audio_ms=%.1f stream_id=%s',
                            (perf_counter() - started) * 1000, stream_id)
            # 100 ms packets; no independent MP3 headers or decoder resets.
            packet_bytes = max(2, sample_rate // 10 * 2)
            for offset in range(0, len(pcm), packet_bytes):
                yield event_line({'type': 'audio', 'seq': seq, 'sample_rate': sample_rate,
                                  'data': base64.b64encode(pcm[offset:offset + packet_bytes]).decode('ascii')})
                seq += 1
        yield event_line({'type': 'end'})
    except Exception:
        logger.exception('tts_stream_failed stream_id=%s', stream_id)
        yield event_line({'type': 'error', 'message': 'Falha ao gerar a resposta de voz.'})
    finally:
        if pending is not None:
            pending.cancel()
            with suppress(asyncio.CancelledError, StopAsyncIteration, Exception):
                await pending
        await source.aclose()
        logger.info('tts_stream total_ms=%.1f packets=%d stream_id=%s',
                    (perf_counter() - started) * 1000, seq, stream_id)
