from pathlib import Path

from fastapi.testclient import TestClient

from whisper_runtime.app import create_app
from whisper_runtime.config import WhisperSettings


class FakeWhisperEngine:
    def __init__(self) -> None:
        self.loaded = False

    def load(self) -> None:
        self.loaded = True

    def transcribe(self, path: Path, language: str) -> str:
        assert path.exists()
        assert language == "pt"
        return "onde estao os teclados"


def test_transcription_service_reports_cpu_configuration_and_accepts_n8n_audio() -> None:
    engine = FakeWhisperEngine()
    settings = WhisperSettings(model="small", device="cpu", compute_type="int8", language="pt")

    with TestClient(create_app(engine, settings)) as client:
        health = client.get("/health")
        response = client.post(
            "/v1/audio/transcriptions",
            content=b"audio",
            headers={"content-type": "audio/webm"},
        )

    assert engine.loaded is True
    assert health.json() == {"status": "ready", "model": "small", "device": "cpu"}
    assert response.status_code == 200
    assert response.json() == {"text": "onde estao os teclados"}
