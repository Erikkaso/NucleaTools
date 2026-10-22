from fastapi.testclient import TestClient

from voice_runtime.app import create_app


class FakeRuntime:
    is_ready = False

    async def warm_tts(self):
        self.is_ready = True

    async def close(self):
        self.is_ready = False

    async def synthesize(self, text):
        assert text == 'Ola'
        return b'fake-mp3'


def test_startup_and_shutdown_manage_tts_readiness():
    runtime = FakeRuntime()
    with TestClient(create_app(runtime)) as client:
        assert runtime.is_ready
        assert client.get('/health').json() == {'status': 'ready', 'service': 'tts'}
    assert not runtime.is_ready


def test_health_is_unavailable_before_startup():
    client = TestClient(create_app(FakeRuntime()))
    assert client.get('/health').status_code == 503


def test_speech_returns_mp3():
    with TestClient(create_app(FakeRuntime())) as client:
        response = client.post('/v1/audio/speech', json={'text': ' Ola '})
    assert response.status_code == 200
    assert response.content == b'fake-mp3'
    assert response.headers['content-type'] == 'audio/mpeg'


def test_blank_speech_is_rejected():
    with TestClient(create_app(FakeRuntime())) as client:
        assert client.post('/v1/audio/speech', json={'text': ' '}).status_code == 422


def test_transcription_route_is_removed():
    with TestClient(create_app(FakeRuntime())) as client:
        assert client.post('/v1/audio/transcriptions', content=b'audio').status_code == 404
        assert '/v1/audio/transcriptions' not in client.get('/openapi.json').json()['paths']


def test_synthesis_failure_is_controlled():
    class FailedRuntime(FakeRuntime):
        async def synthesize(self, text):
            raise RuntimeError('GPU failure')

    with TestClient(create_app(FailedRuntime())) as client:
        response = client.post('/v1/audio/speech', json={'text': 'Ola'})
    assert response.status_code == 503
    assert response.json()['detail'] == 'Servico de sintese indisponivel'
