import importlib.util
import json
import logging
import threading
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path

import pytest
import requests
from urllib3.exceptions import ReadTimeoutError
from werkzeug.serving import make_server
from flask.testing import FlaskClient


TOKEN = "Ab_9-" + "x" * 38
AUTH_KEY = "test-only-key-" + "a" * 40
START = b'{"type":"start","format":"pcm_s16le","channels":1}\n'
AUDIO = b'{"type":"audio","seq":0,"sample_rate":24000,"data":"AQACAA=="}\n'
END = b'{"type":"end"}\n'


@pytest.fixture
def gateway(monkeypatch):
    monkeypatch.setenv("N8N_WEBHOOK_URL", "http://n8n.test/webhook/inventory")
    monkeypatch.setenv("TTS_BASE_URL", "http://tts.test:8000")
    path = Path(__file__).resolve().parents[1] / "app.py"
    spec = importlib.util.spec_from_file_location("voice_gateway_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.app.config.update(TESTING=True)
    class AuthenticatedClient(FlaskClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.environ_base["HTTP_X_NUCLEA_KEY"] = AUTH_KEY
    module.app.test_client_class = AuthenticatedClient
    return module


def ticket(payload=None, status=200, mime="application/json"):
    result = requests.Response()
    result.status_code = status
    result.headers["Content-Type"] = mime
    result._content = json.dumps(payload if payload is not None else {
        "stream_id": TOKEN, "format": "pcm_s16le", "channels": 1,
    }).encode()
    result._content_consumed = True
    return result


class Stream:
    status_code = 200
    headers = {"Content-Type": "application/x-ndjson; charset=utf-8"}

    def __init__(self, failure=None, empty=False):
        self.closed = False
        self.finished = False
        self.failure = failure
        self.empty = empty

    @property
    def content(self):
        raise AssertionError("Do not buffer the TTS audio")

    def iter_content(self, chunk_size):
        assert chunk_size is None
        if self.empty:
            return
        yield START
        if self.failure:
            raise self.failure
        yield AUDIO
        yield END
        self.finished = True

    def close(self):
        self.closed = True


def setup_dependencies(gateway, monkeypatch, upstream=None, payload=None):
    upstream = upstream or Stream()
    calls = []

    def post(url, **kwargs):
        calls.append(("POST", url, kwargs))
        assert kwargs["files"]["audio"][1].read() == b"RIFFtest"
        return ticket(payload)

    def get(url, **kwargs):
        calls.append(("GET", url, kwargs))
        return upstream

    monkeypatch.setattr(gateway.requests, "post", post)
    monkeypatch.setattr(gateway.requests, "get", get)
    return upstream, calls


def upload(gateway, **fields):
    return gateway.app.test_client().post("/api/device-audio", data={
        "audio": (BytesIO(b"RIFFtest"), "command.wav"), **fields,
    }, buffered=False)


def test_health_is_local_and_no_browser_routes_exist(gateway, monkeypatch):
    monkeypatch.setattr(gateway.requests, "get", lambda *a, **k: pytest.fail("No upstream health probe"))
    client = gateway.app.test_client()
    assert client.get("/health").json == {"status": "ok", "service": "voice_gateway"}
    assert client.get("/").status_code == 404
    assert client.get("/api/device-response").status_code == 404
    assert gateway.app.secret_key is None


@pytest.mark.parametrize("wrapped", [False, True])
def test_same_post_forwards_device_and_streams_without_buffering(gateway, monkeypatch, wrapped):
    payload = {"stream_id": TOKEN, "url": "http://untrusted.test/ignore"}
    upstream, calls = setup_dependencies(gateway, monkeypatch, payload=[payload] if wrapped else payload)
    result = upload(gateway, deviceId="esp-office", responseMode="speaker")
    assert result.status_code == 200
    assert result.mimetype == "application/x-ndjson"
    assert "no-store" in result.headers["Cache-Control"]
    assert "no-transform" in result.headers["Cache-Control"]
    assert result.headers["Content-Encoding"] == "identity"
    assert result.headers["X-Accel-Buffering"] == "no"
    assert result.headers["X-Request-ID"]
    assert calls[0][2]["data"] == {"sessionId": "esp-office"}
    assert calls[0][2]["timeout"] == (5, 220)
    assert calls[0][2]["allow_redirects"] is False
    assert calls[1][1] == "http://tts.test:8000/v1/audio/speech/streams/" + TOKEN
    assert calls[1][2]["stream"] is True
    assert calls[1][2]["allow_redirects"] is False
    assert calls[1][2]["timeout"] == (5, 90)
    assert next(iter(result.response)) == START
    assert not upstream.finished
    result.close()
    assert upstream.closed


def test_default_mode_is_speaker_and_turn_completes(gateway, monkeypatch):
    upstream, calls = setup_dependencies(gateway, monkeypatch)
    result = upload(gateway)
    assert result.data == START + AUDIO + END
    assert calls[0][2]["data"] == {"sessionId": "nuclea-esp32"}
    assert upstream.finished and upstream.closed


def test_close_without_consuming_stream_closes_upstream(gateway, monkeypatch):
    upstream, _ = setup_dependencies(gateway, monkeypatch)
    result = upload(gateway)
    result.close()
    assert upstream.closed


@pytest.mark.parametrize("data,code", [({}, 400), ({"responseMode": "browser"}, 400)])
def test_rejects_missing_file(gateway, monkeypatch, data, code):
    monkeypatch.setattr(gateway.requests, "post", lambda *a, **k: pytest.fail("No upstream POST"))
    assert gateway.app.test_client().post("/api/device-audio", data=data).status_code == code


def test_rejects_browser_mode_before_upstream(gateway, monkeypatch):
    monkeypatch.setattr(gateway.requests, "post", lambda *a, **k: pytest.fail("No upstream POST"))
    assert upload(gateway, responseMode="browser").status_code == 400


def test_rejects_oversized_audio_before_upstream(gateway, monkeypatch):
    monkeypatch.setattr(gateway.requests, "post", lambda *a, **k: pytest.fail("No upstream POST"))
    result = gateway.app.test_client().post("/api/device-audio", data={
        "audio": (BytesIO(b"x" * (2 * 1024 * 1024)), "command.wav"),
    })
    assert result.status_code == 413
    assert result.json["code"] == "audio_too_large"


@pytest.mark.parametrize("payload", [
    {}, [], [None], [{"stream_id": TOKEN}, {"stream_id": TOKEN}],
    {"stream_id": "../" + "x" * 40}, {"stream_id": "x" * 31},
    {"stream_id": "https://untrusted.test/" + "x" * 40},
])
def test_invalid_ticket_never_fetches_arbitrary_url(gateway, monkeypatch, payload):
    setup_dependencies(gateway, monkeypatch, payload=payload)
    monkeypatch.setattr(gateway.requests, "get", lambda *a, **k: pytest.fail("No unsafe GET"))
    result = upload(gateway)
    assert result.status_code == 502
    assert result.json["code"] == "invalid_stream_ticket"


@pytest.mark.parametrize("status,mime,code", [
    (302, "application/json", "n8n_unavailable"),
    (500, "application/json", "n8n_unavailable"),
    (200, "audio/mpeg", "speaker_requires_streaming"),
])
def test_n8n_error_and_legacy_audio_are_not_played(gateway, monkeypatch, status, mime, code):
    monkeypatch.setattr(gateway.requests, "post", lambda *a, **k: ticket(status=status, mime=mime))
    monkeypatch.setattr(gateway.requests, "get", lambda *a, **k: pytest.fail("No TTS GET"))
    result = upload(gateway)
    assert result.status_code == 502
    assert result.json["code"] == code


@pytest.mark.parametrize("status,mime,empty", [
    (404, "application/x-ndjson", False),
    (302, "application/x-ndjson", False),
    (200, "audio/mpeg", False),
    (200, "application/x-ndjson", True),
])
def test_invalid_tts_response_is_closed(gateway, monkeypatch, status, mime, empty):
    upstream = Stream(empty=empty)
    upstream.status_code = status
    upstream.headers = {"Content-Type": mime}
    setup_dependencies(gateway, monkeypatch, upstream)
    result = upload(gateway)
    assert result.status_code == 502
    assert result.json["code"] == "invalid_tts_stream"
    assert upstream.closed


@pytest.mark.parametrize("dependency,error,status", [
    ("post", requests.Timeout(), 504),
    ("post", requests.ConnectionError(), 502),
    ("get", requests.Timeout(), 504),
    ("get", requests.ConnectionError(ReadTimeoutError(None, None, "timeout")), 504),
    ("get", requests.ConnectionError(), 502),
])
def test_dependency_failure_is_controlled(gateway, monkeypatch, dependency, error, status):
    setup_dependencies(gateway, monkeypatch)

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(gateway.requests, dependency, fail)
    result = upload(gateway)
    assert result.status_code == status
    assert result.json["request_id"] == result.headers["X-Request-ID"]


def test_midstream_failure_sends_error_and_closes_without_end(gateway, monkeypatch):
    upstream, _ = setup_dependencies(gateway, monkeypatch, Stream(requests.ConnectionError()))
    result = upload(gateway)
    assert result.status_code == 200
    assert result.data.startswith(START)
    assert b'"type":"error"' in result.data
    assert END not in result.data
    assert upstream.closed


def test_errors_are_logged_without_tickets_or_audio(gateway, monkeypatch, caplog):
    upstream = Stream()
    upstream.status_code = 404
    setup_dependencies(gateway, monkeypatch, upstream)
    with caplog.at_level(logging.INFO):
        result = upload(gateway)
    assert result.status_code == 502
    assert result.json["request_id"] in caplog.text
    assert "invalid_tts_stream" in caplog.text
    assert "404" in caplog.text
    assert TOKEN not in caplog.text


@contextmanager
def serve(application):
    server = make_server("127.0.0.1", 0, application, threaded=True)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_real_http_audio_arrives_before_upstream_finishes(gateway, monkeypatch):
    from flask import Flask, Response, jsonify, request

    dependencies = Flask("fake_dependencies")
    release = threading.Event()
    finished = threading.Event()
    closed = threading.Event()

    @dependencies.post("/webhook/test")
    def webhook():
        assert request.headers.get("X-Nuclea-Key") == AUTH_KEY
        assert request.files["audio"].read() == b"RIFFtest"
        assert request.form["sessionId"] == "test-esp"
        return jsonify(stream_id=TOKEN, format="pcm_s16le", channels=1)

    @dependencies.get("/v1/audio/speech/streams/<token>")
    def tts(token):
        assert token == TOKEN

        def packets():
            try:
                yield START
                yield AUDIO
                assert release.wait(timeout=5), "Gateway buffered the stream instead of forwarding audio"
                yield END
                finished.set()
            finally:
                closed.set()

        return Response(packets(), content_type="application/x-ndjson")

    with serve(dependencies) as backend_url:
        monkeypatch.setattr(gateway, "N8N_WEBHOOK_URL", backend_url + "/webhook/test")
        monkeypatch.setattr(gateway, "TTS_BASE_URL", backend_url)
        with serve(gateway.app) as gateway_url:
            response = None
            try:
                response = requests.post(gateway_url + "/api/device-audio",
                                         headers={"X-Nuclea-Key": AUTH_KEY},
                                         files={"audio": ("command.wav", b"RIFFtest", "audio/wav")},
                                         data={"deviceId": "test-esp"}, stream=True, timeout=(2, 3))
                assert response.status_code == 200
                lines = response.iter_lines(chunk_size=1)
                assert next(lines) == START.rstrip(b"\n")
                assert next(lines) == AUDIO.rstrip(b"\n")
                assert not finished.is_set()
                release.set()
                assert next(lines) == END.rstrip(b"\n")
                assert list(lines) == []
                assert closed.wait(timeout=2)
            finally:
                release.set()
                if response is not None:
                    response.close()
