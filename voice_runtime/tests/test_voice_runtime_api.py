from pathlib import Path

from fastapi.testclient import TestClient

from voice_runtime.app import create_app


class FakeRuntime:
    def __init__(self) -> None:
        self.warmed = False

    async def warm_tts(self) -> None:
        self.warmed = True

    async def transcribe(self, path: Path, language: str) -> str:
        assert path.exists()
        assert language == "pt"
        return "texto transcrito"

    async def synthesize(self, text: str) -> bytes:
        assert text == "Ola"
        return b"fake-mp3"


def test_transcription_accepts_audio_upload() -> None:
    client = TestClient(create_app(FakeRuntime()))

    response = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("audio.webm", b"audio", "audio/webm")},
        data={"language": "pt"},
    )

    assert response.status_code == 200
    assert response.json() == {"text": "texto transcrito"}


def test_transcription_accepts_raw_binary_audio_from_n8n() -> None:
    client = TestClient(create_app(FakeRuntime()))

    response = client.post(
        "/v1/audio/transcriptions",
        content=b"audio",
        headers={"content-type": "audio/webm"},
    )

    assert response.status_code == 200
    assert response.json() == {"text": "texto transcrito"}


def test_speech_returns_mp3() -> None:
    client = TestClient(create_app(FakeRuntime()))

    response = client.post("/v1/audio/speech", json={"text": "Ola"})

    assert response.status_code == 200
    assert response.content == b"fake-mp3"
    assert response.headers["content-type"] == "audio/mpeg"


def test_transcription_rejects_missing_upload() -> None:
    client = TestClient(create_app(FakeRuntime()))

    response = client.post("/v1/audio/transcriptions")

    assert response.status_code == 400
    assert response.json()["detail"] == "O campo file e obrigatorio"


def test_tts_is_warmed_when_application_starts() -> None:
    runtime = FakeRuntime()

    with TestClient(create_app(runtime)):
        assert runtime.warmed is True
