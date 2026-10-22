"""Verify incremental HTTP delivery without GPU weights."""

import socket
import threading

import httpx
import uvicorn

from voice_runtime.app import create_app
from voice_runtime.runtime import VoiceRuntime


def test_http_delivers_first_audio_while_second_phrase_is_still_blocked():
    release = threading.Event()

    class Engine:
        def load(self): pass
        def warmup(self): pass
        def unload(self): pass

        def synthesize_pcm(self, text):
            if text == 'Segunda.':
                assert release.wait(5)
            return b'\x00\x00' * 2400, 24000

    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(VoiceRuntime(Engine())), log_level='error'))
    ready = threading.Event()
    original_startup = server.startup

    async def startup(sockets=None):
        await original_startup(sockets)
        ready.set()

    server.startup = startup
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    thread.start()
    try:
        assert ready.wait(5)
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=5) as client:
            token = client.post('/v1/audio/speech/streams', json={'text': 'Primeira. Segunda.'}).json()['stream_id']
            with client.stream('GET', f'/v1/audio/speech/streams/{token}') as response:
                lines = response.iter_lines()
                assert '"type":"start"' in next(lines)
                assert '"type":"audio"' in next(lines)
                assert not release.is_set()
                release.set()
                remaining = list(lines)
                assert '"type":"end"' in remaining[-1]
    finally:
        release.set()
        server.should_exit = True
        thread.join(5)
        sock.close()
        assert not thread.is_alive()
