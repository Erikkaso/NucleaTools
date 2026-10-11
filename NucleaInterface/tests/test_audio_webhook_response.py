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


def test_page_reads_assistant_audio_as_a_blob() -> None:
    client = interface_app.app.test_client()

    response = client.get("/")

    assert "await res.blob()" in response.text
    assert "replacePendingWithAudio" in response.text


def test_page_serves_the_local_wakeword_runtime_and_model() -> None:
    client = interface_app.app.test_client()

    page = client.get("/")
    model = client.get("/static/wakeword/nuclea_int8.tflite")
    worklet = client.get("/static/wakeword-worklet.mjs")

    assert "vendor/tfjs-tflite/tf-tflite.min.js" in page.text
    assert "wakeword.mjs" in page.text
    assert model.status_code == 200
    assert model.data[4:8] == b"TFL3"
    assert worklet.status_code == 200
    assert "wakeword-capture" in worklet.text


def test_device_audio_queues_n8n_response_for_browser(monkeypatch) -> None:
    captured = {}

    def fake_post(*args, **kwargs):
        captured.update(kwargs)
        return _audio_response()

    monkeypatch.setattr(interface_app.requests, "post", fake_post)
    interface_app.device_response_mailbox.clear()
    client = interface_app.app.test_client()

    upload = client.post(
        "/api/device-audio",
        data={
            "deviceId": "esp32-laboratorio",
            "audio": (BytesIO(b"RIFFfake-wav"), "command.wav"),
        },
        content_type="multipart/form-data",
    )
    browser_response = client.get("/api/device-response")
    consumed_response = client.get("/api/device-response")

    assert upload.status_code == 200
    assert upload.get_json() == {"status": "ready"}
    assert captured["data"] == {"sessionId": "esp32-laboratorio"}
    assert captured["files"]["audio"][0] == "command.wav"
    assert browser_response.status_code == 200
    assert browser_response.content_type == "audio/mpeg"
    assert browser_response.data == b"ID3fake-mp3"
    assert consumed_response.status_code == 204


def test_device_audio_requires_an_audio_file() -> None:
    interface_app.device_response_mailbox.clear()
    client = interface_app.app.test_client()

    response = client.post(
        "/api/device-audio",
        data={"deviceId": "esp32-laboratorio"},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert client.get("/api/device-response").status_code == 204


def test_page_polls_for_device_audio_response() -> None:
    client = interface_app.app.test_client()

    response = client.get("/")

    assert "pollDeviceResponse" in response.text
    assert "fetch('/api/device-response'" in response.text
