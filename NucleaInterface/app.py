import math
import os
import re
import threading
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request, session
from urllib3.exceptions import ReadTimeoutError

load_dotenv(Path(__file__).with_name(".env"), override=False, encoding="utf-8-sig")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-troque-em-producao")

# URL do webhook do n8n. Pode ser sobrescrita pela variável de ambiente N8N_WEBHOOK_URL.
N8N_WEBHOOK_URL = os.environ.get(
    "N8N_WEBHOOK_URL",
    "https://n8n.200-129-37-25.sslip.io/webhook-test/8cf7d87c-4184-460b-8b0e-95affded7054",
    #"https://n8n.200-129-37-25.sslip.io/webhook-test/8cf7d87c-4184-460b-8b0e-95affded7054",
)
REQUEST_TIMEOUT = int(os.environ.get("N8N_TIMEOUT_SECONDS", "220"))
TTS_BASE_URL = os.environ.get("TTS_BASE_URL", "http://127.0.0.1:8000")
TTS_STREAM_TIMEOUT_SECONDS = int(os.environ.get("TTS_STREAM_TIMEOUT_SECONDS", "90"))


class DeviceResponseMailbox:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._response: tuple[bytes, str] | str | None = None

    def put(self, content: bytes, content_type: str) -> None:
        with self._lock:
            self._response = (content, content_type)

    def put_ticket(self, stream_id: str) -> None:
        with self._lock:
            self._response = stream_id

    def take(self) -> tuple[bytes, str] | str | None:
        with self._lock:
            response = self._response
            self._response = None
            return response

    def clear(self) -> None:
        with self._lock:
            self._response = None


device_response_mailbox = DeviceResponseMailbox()


@app.route("/")
def index():
    try:
        prebuffer_seconds = float(os.environ.get("TTS_PREBUFFER_SECONDS", "3"))
        if not math.isfinite(prebuffer_seconds):
            prebuffer_seconds = 3
    except ValueError:
        prebuffer_seconds = 3
    try:
        progress_seconds = float(os.environ.get("TTS_AUDIO_PROGRESS_TIMEOUT_SECONDS", "60"))
        if not math.isfinite(progress_seconds):
            progress_seconds = 60
    except ValueError:
        progress_seconds = 60
    return render_template(
        "index.html",
        prebuffer_seconds=max(0, min(12, prebuffer_seconds)),
        progress_seconds=max(5, min(300, progress_seconds)),
    )


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()

    if not message:
        return jsonify({"error": "Mensagem vazia."}), 400

    # Mantém um id de sessão por navegador, útil se o workflow do n8n usar
    # memória de conversa (ex.: nó "AI Agent" com Session ID).
    if "session_id" not in session:
        session["session_id"] = str(uuid.uuid4())

    payload = {
        "message": message,
        "sessionId": session["session_id"],
    }

    try:
        n8n_response = requests.post(N8N_WEBHOOK_URL, json=payload, timeout=REQUEST_TIMEOUT)
        n8n_response.raise_for_status()
    except requests.exceptions.Timeout:
        return jsonify({"error": "O n8n demorou demais para responder (timeout)."}), 504
    except requests.exceptions.RequestException as exc:
        return jsonify({"error": "Nao foi possivel falar com o n8n."}), upstream_error_status(exc)

    return proxy_audio_response(n8n_response)


@app.route("/api/chat-audio", methods=["POST"])
def chat_audio():
    audio_file = request.files.get("audio")
    if audio_file is None or audio_file.filename == "":
        return jsonify({"error": "Nenhum áudio recebido."}), 400

    if "session_id" not in session:
        session["session_id"] = str(uuid.uuid4())

    # O nome do campo "audio" vira o nome da propriedade binária no n8n
    # (o node Webhook expõe o arquivo em $binary.audio).
    files = {
        "audio": (
            audio_file.filename or "gravacao.webm",
            audio_file.stream,
            audio_file.mimetype or "application/octet-stream",
        ),
    }
    data = {"sessionId": session["session_id"]}

    try:
        n8n_response = requests.post(
            N8N_WEBHOOK_URL, data=data, files=files, timeout=REQUEST_TIMEOUT
        )
        n8n_response.raise_for_status()
    except requests.exceptions.Timeout:
        return jsonify({"error": "O n8n demorou demais para responder (timeout)."}), 504
    except requests.exceptions.RequestException as exc:
        return jsonify({"error": "Nao foi possivel falar com o n8n."}), upstream_error_status(exc)

    return proxy_audio_response(n8n_response)


@app.route("/api/device-audio", methods=["POST"])
def device_audio():
    audio_file = request.files.get("audio")
    if audio_file is None or audio_file.filename == "":
        return jsonify({"error": "Nenhum áudio recebido."}), 400

    device_id = (request.form.get("deviceId") or "nuclea-esp32").strip()[:128]
    files = {
        "audio": (
            audio_file.filename or "command.wav",
            audio_file.stream,
            audio_file.mimetype or "audio/wav",
        ),
    }

    try:
        n8n_response = requests.post(
            N8N_WEBHOOK_URL,
            data={"sessionId": device_id or "nuclea-esp32"},
            files=files,
            timeout=REQUEST_TIMEOUT,
        )
        n8n_response.raise_for_status()
    except requests.exceptions.Timeout:
        return jsonify({"error": "O n8n demorou demais para responder (timeout)."}), 504
    except requests.exceptions.RequestException as exc:
        return jsonify({"error": "Nao foi possivel falar com o n8n."}), upstream_error_status(exc)

    return queue_device_response(n8n_response)


@app.route("/api/device-response", methods=["GET"])
def device_response():
    queued = device_response_mailbox.take()
    if queued is None:
        return Response(status=204, headers={"Cache-Control": "no-store"})
    if isinstance(queued, str):
        return proxy_tts_stream(queued)
    content, content_type = queued
    response = Response(content, content_type=content_type)
    response.headers["Cache-Control"] = "no-store"
    return response


def response_content_type(response: requests.Response) -> str:
    return response.headers.get("Content-Type", "").split(";", maxsplit=1)[0].strip().lower()


def queue_device_response(response: requests.Response) -> Response | tuple[Response, int]:
    try:
        content_type = response_audio_content_type(response)
        if content_type is not None:
            device_response_mailbox.put(response.content, content_type)
        else:
            stream_id = response_stream_id(response)
            if stream_id is None:
                return jsonify({"error": "Invalid audio response from n8n.", "code": "invalid_stream_ticket"}), 502
            device_response_mailbox.put_ticket(stream_id)
    finally:
        response.close()
    return jsonify({"status": "ready"})


def response_stream_id(response: requests.Response) -> str | None:
    if response_content_type(response) != "application/json":
        return None
    try:
        ticket = response.json()
    except ValueError:
        return None
    stream_id = ticket.get("stream_id") if isinstance(ticket, dict) else None
    if isinstance(stream_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{32,128}", stream_id):
        return stream_id
    return None


def upstream_error_status(exc: requests.exceptions.RequestException) -> int:
    # Requests wraps streamed read timeouts in ConnectionError.
    if isinstance(exc, requests.exceptions.Timeout) or (
        exc.args and isinstance(exc.args[0], ReadTimeoutError)
    ):
        return 504
    return 502


def proxy_tts_stream(stream_id: str) -> Response | tuple[Response, int]:
    upstream = None
    try:
        upstream = requests.get(
            TTS_BASE_URL.rstrip("/") + "/v1/audio/speech/streams/" + stream_id,
            stream=True,
            timeout=(5, TTS_STREAM_TIMEOUT_SECONDS),
            allow_redirects=False,
        )
        if upstream.status_code != 200 or response_content_type(upstream) != "application/x-ndjson":
            upstream.close()
            return jsonify({"error": "Invalid TTS stream response.", "code": "invalid_tts_stream"}), 502
        # Prime one chunk so connection and initial read errors retain an HTTP status.
        chunks = iter(upstream.iter_content(chunk_size=None))
        first = next((chunk for chunk in chunks if chunk), None)
        if first is None:
            upstream.close()
            return jsonify({"error": "Empty TTS stream response.", "code": "invalid_tts_stream"}), 502
    except requests.exceptions.RequestException as exc:
        if upstream is not None:
            upstream.close()
        return jsonify({"error": "TTS stream unavailable.", "code": "tts_stream_unavailable"}), upstream_error_status(exc)

    closed = False

    def close():
        nonlocal closed
        if not closed:
            closed = True
            upstream.close()

    def generate():
        ends_with_newline = first.endswith(b"\n")
        try:
            yield first
            for chunk in chunks:
                if chunk:
                    ends_with_newline = chunk.endswith(b"\n")
                    yield chunk
        except requests.exceptions.RequestException:
            separator = b"" if ends_with_newline else b"\n"
            yield separator + b'{"type":"error","code":"tts_stream_error","message":"TTS stream interrupted."}\n'
        finally:
            close()

    result = Response(generate(), content_type="application/x-ndjson")
    result.headers["Cache-Control"] = "no-store"
    result.headers["X-Accel-Buffering"] = "no"
    result.call_on_close(close)
    return result


def proxy_audio_response(response: requests.Response) -> Response | tuple[Response, int]:
    try:
        content_type = response_audio_content_type(response)
        if content_type is not None:
            return Response(response.content, content_type=content_type)
        stream_id = response_stream_id(response)
    finally:
        response.close()
    if stream_id is None:
        return jsonify({"error": "Invalid audio response from n8n.", "code": "invalid_stream_ticket"}), 502
    return proxy_tts_stream(stream_id)


def response_audio_content_type(response: requests.Response) -> str | None:
    content_type = response_content_type(response)
    return content_type if content_type.startswith("audio/") else None


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
