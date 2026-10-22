import asyncio
import base64
import json
import threading

import pytest
from fastapi.testclient import TestClient

from voice_runtime.app import create_app
from voice_runtime.runtime import VoiceRuntime
from voice_runtime.streaming import StreamTickets, pcm_events, split_phrases


def test_tickets_are_bounded_single_use_and_expire():
    now = [0.0]
    tickets = StreamTickets(capacity=1, ttl=10, clock=lambda: now[0])
    token = tickets.create('Ola')
    with pytest.raises(OverflowError):
        tickets.create('Outro')
    assert tickets.take(token) == 'Ola'
    with pytest.raises(KeyError):
        tickets.take(token)
    token = tickets.create('Expirado')
    now[0] = 11
    with pytest.raises(KeyError):
        tickets.take(token)
    assert tickets.create('Novo')


def test_split_keeps_all_words_and_limits_long_phrases():
    text = 'Bom dia. ' + 'Os teclados estao no armario vermelho. ' * 20
    phrases = split_phrases(text, max_chars=100)
    assert len(phrases) > 2
    assert ' '.join(phrases) == text.strip()
    assert all(len(phrase) <= 100 for phrase in phrases)


class FakeTts:
    def __init__(self):
        self.calls = []

    def load(self): pass
    def warmup(self): pass
    def unload(self): pass

    def synthesize_pcm(self, text):
        self.calls.append(text)
        return b'\x01\x00' * 2400, 24000


def test_first_phrase_is_available_before_next_phrase_is_generated():
    engine = FakeTts()
    runtime = VoiceRuntime(engine)

    async def run():
        stream = runtime.stream('Primeira frase. Segunda frase.')
        assert await anext(stream) == (b'\x01\x00' * 2400, 24000)
        assert engine.calls == ['Primeira frase.']
        await stream.aclose()

    asyncio.run(run())


def test_stream_ticket_route_frames_pcm_and_cannot_be_replayed():
    with TestClient(create_app(VoiceRuntime(FakeTts()))) as client:
        ticket = client.post('/v1/audio/speech/streams', json={'text': 'Ola.'})
        assert ticket.status_code == 202
        token = ticket.json()['stream_id']
        assert len(token) >= 32
        path = f'/v1/audio/speech/streams/{token}'
        response = client.get(path)
        assert response.headers['content-type'].startswith('application/x-ndjson')
        assert response.headers['x-accel-buffering'] == 'no'
        events = [json.loads(line) for line in response.text.splitlines()]
        assert events[0]['type'] == 'start'
        assert events[1]['type'] == 'audio'
        assert events[1]['seq'] == 0
        assert events[1]['sample_rate'] == 24000
        assert base64.b64decode(events[1]['data']) == b'\x01\x00' * 2400
        assert events[-1]['type'] == 'end'
        assert client.get(path).status_code == 404


def test_blank_and_oversized_ticket_text_is_rejected():
    with TestClient(create_app(VoiceRuntime(FakeTts()))) as client:
        for text in (' ', 'a' * 6001):
            assert client.post('/v1/audio/speech/streams', json={'text': text}).status_code == 422


def test_stream_failure_is_a_terminal_error_not_a_success():
    class BrokenTts(FakeTts):
        def synthesize_pcm(self, text):
            raise RuntimeError('private CUDA exception')

    with TestClient(create_app(VoiceRuntime(BrokenTts()))) as client:
        token = client.post('/v1/audio/speech/streams', json={'text': 'Ola.'}).json()['stream_id']
        events = [json.loads(line) for line in client.get(f'/v1/audio/speech/streams/{token}').text.splitlines()]
        assert events[-1]['type'] == 'error'
        assert 'private' not in str(events)
        assert not any(event['type'] == 'end' for event in events)


def test_other_requests_cannot_interleave_phrases_of_one_stream():
    engine = FakeTts()
    runtime = VoiceRuntime(engine)

    async def run():
        stream = runtime.stream('Primeira. Segunda.')
        await anext(stream)
        other = asyncio.create_task(anext(runtime.stream('Outra.')))
        await asyncio.sleep(.01)
        assert engine.calls == ['Primeira.']
        await anext(stream)
        assert engine.calls == ['Primeira.', 'Segunda.']
        await stream.aclose()
        await other

    asyncio.run(run())


def test_cancelled_stream_finishes_current_cuda_work_and_stops_next_phrase():
    entered, release = threading.Event(), threading.Event()

    class SlowTts(FakeTts):
        def synthesize_pcm(self, text):
            entered.set()
            assert release.wait(2)
            return super().synthesize_pcm(text)

    engine = SlowTts()
    runtime = VoiceRuntime(engine)

    async def run():
        stream = runtime.stream('Primeira. Segunda.')
        pending = asyncio.create_task(anext(stream))
        assert await asyncio.to_thread(entered.wait, 2)
        pending.cancel()
        await asyncio.sleep(.01)
        assert not pending.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        await stream.aclose()
        assert not runtime._lock.locked()

    asyncio.run(run())
    assert engine.calls == ['Primeira.']


def test_server_progress_timeout_is_not_extended_by_heartbeats():
    release = threading.Event()

    class SlowTts(FakeTts):
        def synthesize_pcm(self, text):
            assert release.wait(2)
            return super().synthesize_pcm(text)

    engine = SlowTts()
    runtime = VoiceRuntime(engine)

    async def run():
        events = pcm_events(runtime, 'Primeira. Segunda.', 'test', progress_timeout=.02)
        try:
            assert json.loads(await anext(events))['type'] == 'start'
            event = json.loads(await anext(events))
            while event['type'] == 'ping':
                event = json.loads(await anext(events))
            assert event['type'] == 'error'
            assert event['code'] == 'audio_progress_timeout'
            assert runtime._lock.locked()
        finally:
            release.set()
            await events.aclose()
        assert not runtime._lock.locked()

    asyncio.run(run())
    assert engine.calls == ['Primeira.']
