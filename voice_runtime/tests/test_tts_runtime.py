import asyncio
import threading

import pytest

from voice_runtime.runtime import VoiceRuntime


class FakeTts:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def load(self) -> None:
        self.calls.append('load:tts')

    def warmup(self) -> None:
        self.calls.append('warmup:tts')

    def unload(self) -> None:
        self.calls.append('unload:tts')

    def synthesize(self, text: str) -> bytes:
        self.calls.append(f'speech:{text}')
        return b'ID3'


def test_startup_loads_and_warms_once_for_multiple_requests() -> None:
    calls = []
    runtime = VoiceRuntime(FakeTts(calls))

    async def run():
        assert not runtime.is_ready
        await runtime.warm_tts()
        await runtime.warm_tts()
        assert runtime.is_ready
        assert await runtime.synthesize('primeira') == b'ID3'
        assert await runtime.synthesize('segunda') == b'ID3'

    asyncio.run(run())
    assert calls == ['load:tts', 'warmup:tts', 'speech:primeira', 'speech:segunda']
    assert not hasattr(runtime, 'transcribe')


def test_concurrent_requests_are_serialized() -> None:
    calls = []
    runtime = VoiceRuntime(FakeTts(calls))

    async def run():
        return await asyncio.gather(runtime.synthesize('a'), runtime.synthesize('b'))

    assert asyncio.run(run()) == [b'ID3', b'ID3']
    assert calls == ['load:tts', 'warmup:tts', 'speech:a', 'speech:b']


def test_shutdown_releases_model_once() -> None:
    calls = []
    runtime = VoiceRuntime(FakeTts(calls))

    async def run():
        await runtime.warm_tts()
        await runtime.close()
        await runtime.close()
        assert not runtime.is_ready

    asyncio.run(run())
    assert calls == ['load:tts', 'warmup:tts', 'unload:tts']


def test_failed_warmup_cleans_up_and_does_not_report_ready() -> None:
    calls = []

    class FailedTts(FakeTts):
        def warmup(self):
            raise RuntimeError('warmup failed')

    runtime = VoiceRuntime(FailedTts(calls))
    with pytest.raises(RuntimeError, match='warmup failed'):
        asyncio.run(runtime.warm_tts())
    assert not runtime.is_ready
    assert calls == ['load:tts', 'unload:tts']


def test_client_cancellation_cannot_overlap_gpu_work() -> None:
    calls = []
    started, release = threading.Event(), threading.Event()

    class SlowTts(FakeTts):
        def synthesize(self, text):
            if text == 'first':
                started.set()
                assert release.wait(2)
            return super().synthesize(text)

    runtime = VoiceRuntime(SlowTts(calls))

    async def run():
        first = asyncio.create_task(runtime.synthesize('first'))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            first.cancel()
            second = asyncio.create_task(runtime.synthesize('second'))
            await asyncio.sleep(.02)
            assert 'speech:second' not in calls
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert await second == b'ID3'

    asyncio.run(run())
    assert calls[-2:] == ['speech:first', 'speech:second']
