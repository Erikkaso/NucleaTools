from io import BytesIO

import requests

from NucleaInterface import app as interface_app


def _audio_response() -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response._content = b"ID3fake-mp3"
    response.headers["Content-Type"] = "audio/mpeg"
    return response


def test_chat_proxies_audio_response_from_n8n(monkeypatch) -> None:
    monkeypatch.setattr(interface_app.requests, "post", lambda *args, **kwargs: _audio_response())
    client = interface_app.app.test_client()

    response = client.post("/api/chat", json={"message": "Ola"})

    assert response.status_code == 200
    assert response.content_type == "audio/mpeg"
    assert response.data == b"ID3fake-mp3"


def test_audio_chat_proxies_audio_response_from_n8n(monkeypatch) -> None:
    monkeypatch.setattr(interface_app.requests, "post", lambda *args, **kwargs: _audio_response())
    client = interface_app.app.test_client()

    response = client.post(
        "/api/chat-audio",
        data={"audio": (BytesIO(b"recording"), "recording.webm")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.content_type == "audio/mpeg"
    assert response.data == b"ID3fake-mp3"


def test_page_renders_voice_controls_without_text_chat() -> None:
    client = interface_app.app.test_client()

    response = client.get("/")

    assert response.status_code == 200
    assert 'id="voiceApp"' in response.text
    assert 'id="speakButton"' in response.text
    assert 'id="cancelButton"' in response.text
    assert 'id="waveform"' in response.text
    assert 'role="status"' in response.text
    assert "<textarea" not in response.text
    assert "<input" not in response.text


def test_page_serves_voice_assets_and_prebuffer_setting() -> None:
    client = interface_app.app.test_client()

    page = client.get("/")
    script = client.get("/static/voice-ui.mjs")
    style = client.get("/static/voice-ui.css")

    assert 'type="module"' in page.text
    assert "/static/voice-ui.mjs" in page.text
    assert "/static/voice-ui.css" in page.text
    assert 'data-tts-prebuffer-seconds="' in page.text
    assert "wakeword" not in page.text.lower()
    assert script.status_code == 200
    assert style.status_code == 200
