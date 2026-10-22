import importlib.util
import json
from io import BytesIO
from pathlib import Path

import pytest
import requests
from urllib3.exceptions import ReadTimeoutError


TOKEN = "Ab_9-" + "x" * 38
START = b'{"type":"start","sample_rate":24000}\n'
END = b'{"type":"end"}\n'


@pytest.fixture
def backend(monkeypatch):
    monkeypatch.delenv("TTS_STREAM_TIMEOUT_SECONDS", raising=False)
    root = Path(__file__).resolve().parents[1]
    path = root / "app.py"
    spec = importlib.util.spec_from_file_location("streaming_backend", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.app.config["TESTING"] = True
    return module


class Stream:
    status_code = 200
    headers = {"Content-Type": "application/x-ndjson; charset=utf-8"}

    def __init__(self, failure=None):
        self.closed = False
        self.finished = False
        self.failure = failure

    @property
    def content(self):
        raise AssertionError("stream must never be materialized")

    def iter_content(self, chunk_size):
        yield START
        if self.failure:
            raise self.failure
        yield b'{"type":"audio","audio":"AA=="}\n'
        yield END
        self.finished = True

    def close(self):
        self.closed = True


def ticket_response(payload=None):
    response = requests.Response()
    response.status_code = 200
    response.headers["Content-Type"] = "application/json"
    response._content = json.dumps(payload if payload is not None else {
        "stream_id": TOKEN, "format": "pcm_s16le", "channels": 1,
        "url": "http://attacker.invalid/ignore-me",
    }).encode()
    return response


def upload(backend, route="/api/chat-audio", **kwargs):
    return backend.app.test_client().post(
        route, data={"audio": (BytesIO(b"RIFFtest"), "command.wav")}, **kwargs
    )


def setup_ticket(backend, monkeypatch, upstream):
    monkeypatch.setattr(backend.requests, "post", lambda *a, **k: ticket_response())
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return upstream

    monkeypatch.setattr(backend.requests, "get", get)
    return calls


def test_stream_is_incremental_and_closes_on_disconnect(backend, monkeypatch):
    upstream = Stream()
    calls = setup_ticket(backend, monkeypatch, upstream)
    monkeypatch.setattr(backend, "TTS_BASE_URL", "http://trusted.test:8080/")
    response = upload(backend, buffered=False)
    assert response.status_code == 200
    assert response.mimetype == "application/x-ndjson"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Accel-Buffering"] == "no"
    assert next(iter(response.response)) == START
    assert not upstream.finished
    assert calls == [("http://trusted.test:8080/v1/audio/speech/streams/" + TOKEN, {
        "stream": True, "timeout": (5, 90), "allow_redirects": False,
    })]
    response.close()
    assert upstream.closed


@pytest.mark.parametrize("payload", [
    {}, [], None, {"url": "http://127.0.0.1/private"},
    {"stream_id": "http://evil.test/" + "x" * 40},
    {"stream_id": "../" + "x" * 40}, {"stream_id": "x" * 31},
    {"stream_id": "x" * 129}, {"stream_id": 123},
    {"stream_id": "x" * 32 + "\n"},
])
def test_rejects_invalid_tickets_without_network_fetch(backend, monkeypatch, payload):
    response = ticket_response()
    response._content = json.dumps(payload).encode()
    monkeypatch.setattr(backend.requests, "post", lambda *a, **k: response)
    monkeypatch.setattr(backend.requests, "get", lambda *a, **k: pytest.fail("unsafe GET"))
    result = upload(backend)
    assert result.status_code == 502
    assert result.json["code"] == "invalid_stream_ticket"


@pytest.mark.parametrize("status,mime", [(302, "application/x-ndjson"),
    (404, "application/x-ndjson"), (200, "text/html"), (200, "audio/mpeg")])
def test_rejects_upstream_status_or_mime_and_closes(backend, monkeypatch, status, mime):
    upstream = Stream()
    upstream.status_code = status
    upstream.headers = {"Content-Type": mime}
    setup_ticket(backend, monkeypatch, upstream)
    response = upload(backend)
    assert response.status_code == 502
    assert upstream.closed


@pytest.mark.parametrize("failure,status", [
    (requests.Timeout("secret host"), 504),
    (requests.ConnectionError("secret host"), 502),
    (requests.ConnectionError(ReadTimeoutError(None, "secret host", "read timed out")), 504),
])
@pytest.mark.parametrize("phase", ["n8n", "connect", "first_read"])
def test_errors_before_headers_are_controlled(backend, monkeypatch, failure, status, phase):
    upstream = Stream()
    setup_ticket(backend, monkeypatch, upstream)

    def fail(*args, **kwargs):
        raise failure

    if phase == "n8n":
        monkeypatch.setattr(backend.requests, "post", fail)
    elif phase == "connect":
        monkeypatch.setattr(backend.requests, "get", fail)
    else:
        monkeypatch.setattr(upstream, "iter_content", fail)
    response = upload(backend)
    assert response.status_code == status
    assert "secret host" not in response.text
    if phase == "first_read":
        assert upstream.closed


def test_failure_after_headers_emits_error_event_and_closes(backend, monkeypatch):
    upstream = Stream(requests.ConnectionError("secret host"))
    setup_ticket(backend, monkeypatch, upstream)
    response = upload(backend, buffered=False)
    events = [json.loads(line) for line in response.data.splitlines()]
    assert response.status_code == 200
    assert events[0]["type"] == "start"
    assert events[-1]["type"] == "error"
    assert events[-1]["code"] == "tts_stream_error"
    assert events[-1]["message"]
    assert "secret host" not in response.text
    assert upstream.closed


def test_successful_stream_is_forwarded_verbatim(backend, monkeypatch):
    upstream = Stream()
    setup_ticket(backend, monkeypatch, upstream)
    response = upload(backend)
    assert response.data == START + b'{"type":"audio","audio":"AA=="}\n' + END
    assert upstream.finished and upstream.closed


def test_device_ticket_is_deferred_and_consumed_once(backend, monkeypatch):
    upstream = Stream()
    calls = setup_ticket(backend, monkeypatch, upstream)
    response = upload(backend, "/api/device-audio")
    assert response.status_code == 200
    assert response.json == {"status": "ready"}
    assert calls == []
    client = backend.app.test_client()
    stream = client.get("/api/device-response", buffered=False)
    assert stream.mimetype == "application/x-ndjson"
    assert next(iter(stream.response)) == START
    assert not upstream.finished
    assert client.get("/api/device-response").status_code == 204
    stream.close()
    assert upstream.closed


def test_invalid_device_ticket_preserves_previous_legacy_mailbox(backend, monkeypatch):
    backend.device_response_mailbox.put(b"previous", "audio/mpeg")
    monkeypatch.setattr(backend.requests, "post", lambda *a, **k: ticket_response({"stream_id": "bad"}))
    assert upload(backend, "/api/device-audio").status_code == 502
    client = backend.app.test_client()
    response = client.get("/api/device-response")
    assert response.data == b"previous"
    assert response.headers["Cache-Control"] == "no-store"
    assert client.get("/api/device-response").status_code == 204


def test_mailbox_legacy_api_and_clear(backend):
    mailbox = backend.DeviceResponseMailbox()
    mailbox.put(b"old", "audio/mpeg")
    mailbox.put(b"new", "audio/wav")
    assert mailbox.take() == (b"new", "audio/wav")
    assert mailbox.take() is None
    mailbox.put(b"old", "audio/mpeg")
    mailbox.clear()
    assert mailbox.take() is None


@pytest.mark.parametrize("route", ["/api/chat", "/api/chat-audio", "/api/device-audio"])
def test_legacy_binary_passthrough_and_upload_contract(backend, monkeypatch, route):
    captured = {}

    def post(url, **kwargs):
        captured.update(kwargs)
        response = requests.Response()
        response.status_code = 200
        response._content = b"ID3legacy"
        response.headers["Content-Type"] = "audio/mpeg"
        return response

    monkeypatch.setattr(backend.requests, "post", post)
    client = backend.app.test_client()
    if route == "/api/chat":
        response = client.post(route, json={"message": "Ola"})
        assert captured["json"]["message"] == "Ola"
        assert captured["json"]["sessionId"]
    else:
        response = client.post(route, data={
            "audio": (BytesIO(b"RIFFtest"), "command.wav"), "deviceId": "esp-test",
        })
        assert captured["files"]["audio"][0] == "command.wav"
        assert captured["data"]["sessionId"]
        if route == "/api/device-audio":
            assert captured["data"]["sessionId"] == "esp-test"
            assert response.json == {"status": "ready"}
            response = client.get("/api/device-response")
    assert response.status_code == 200
    assert response.mimetype == "audio/mpeg"
    assert response.data == b"ID3legacy"


def test_empty_stream_is_controlled_and_closed(backend, monkeypatch):
    upstream = Stream()
    monkeypatch.setattr(upstream, "iter_content", lambda **kwargs: iter([b""]))
    setup_ticket(backend, monkeypatch, upstream)
    assert upload(backend).status_code == 502
    assert upstream.closed


def test_malformed_ticket_json_is_rejected(backend, monkeypatch):
    response = ticket_response()
    response._content = b"{broken"
    monkeypatch.setattr(backend.requests, "post", lambda *a, **k: response)
    result = upload(backend)
    assert result.status_code == 502
    assert result.json["code"] == "invalid_stream_ticket"


@pytest.mark.parametrize("value,expected", [(None, 3), ("garbage", 3), ("nan", 3),
    ("inf", 3), ("-1", 0), ("99", 12), ("2.5", 2.5)])
def test_index_passes_safe_prebuffer_setting(backend, monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("TTS_PREBUFFER_SECONDS", raising=False)
    else:
        monkeypatch.setenv("TTS_PREBUFFER_SECONDS", value)
    captured = {}

    def render(template, **kwargs):
        captured.update(kwargs)
        return "page"

    monkeypatch.setattr(backend, "render_template", render)
    assert backend.app.test_client().get("/").status_code == 200
    assert captured["prebuffer_seconds"] == expected


@pytest.mark.parametrize('value,expected', [(None, 60), ('bad', 60), ('nan', 60),
    ('inf', 60), ('-2', 5), ('9999', 300), ('45', 45)])
def test_index_passes_safe_audio_progress_timeout(backend, monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv('TTS_AUDIO_PROGRESS_TIMEOUT_SECONDS', raising=False)
    else:
        monkeypatch.setenv('TTS_AUDIO_PROGRESS_TIMEOUT_SECONDS', value)
    captured = {}

    def render(template, **kwargs):
        captured.update(kwargs)
        return 'page'

    monkeypatch.setattr(backend, 'render_template', render)
    assert backend.app.test_client().get('/').status_code == 200
    assert captured['progress_seconds'] == expected
