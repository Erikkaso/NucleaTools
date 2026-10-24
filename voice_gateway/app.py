"""ESP audio gateway extracted from NucleaInterface's streaming backend."""

import logging
import os
import re
import uuid
from io import BytesIO
from pathlib import Path
from time import perf_counter

import requests
from dotenv import load_dotenv
from flask import Flask, Request, Response, g, jsonify, request
from urllib3.exceptions import ReadTimeoutError


load_dotenv(Path(__file__).with_name(".env"), override=False, encoding="utf-8-sig")


class MemoryUploadRequest(Request):
    def _get_file_stream(self, total_content_length, content_type, filename=None, content_length=None):
        return BytesIO()


app = Flask(__name__, static_folder=None)
app.request_class = MemoryUploadRequest
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
app.logger.setLevel(logging.INFO)

N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "").strip()
TTS_BASE_URL = os.environ.get("TTS_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
N8N_TIMEOUT_SECONDS = int(os.environ.get("N8N_TIMEOUT_SECONDS", "220"))
TTS_STREAM_TIMEOUT_SECONDS = int(os.environ.get("TTS_STREAM_TIMEOUT_SECONDS", "90"))


@app.before_request
def identify_request():
    provided = request.headers.get("X-Request-ID", "")
    g.request_id = provided if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", provided) else uuid.uuid4().hex


@app.after_request
def identify_response(response):
    response.headers["X-Request-ID"] = g.request_id
    response.headers.setdefault("Cache-Control", "no-store")
    return response


def error_response(code, message, status, upstream_status=None):
    app.logger.warning("request_id=%s code=%s status=%s upstream_status=%s",
                       g.request_id, code, status, upstream_status)
    return jsonify(error=message, code=code, request_id=g.request_id), status


@app.errorhandler(413)
def audio_too_large(error):
    return error_response("audio_too_large", "O envio excedeu o limite de 2 MiB.", 413)


@app.get("/health")
def health():
    return jsonify(status="ok", service="voice_gateway")


def content_type(response):
    return response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()


def stream_ticket(response):
    if content_type(response) != "application/json":
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    if isinstance(payload, list) and len(payload) == 1:
        payload = payload[0]
    token = payload.get("stream_id") if isinstance(payload, dict) else None
    return token if isinstance(token, str) and re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token) else None


def dependency_error_status(error):
    if isinstance(error, requests.Timeout) or (error.args and isinstance(error.args[0], ReadTimeoutError)):
        return 504
    return 502


@app.post("/api/device-audio")
def device_audio():
    auth_key = request.headers.get("X-Nuclea-Key", "")
    if not re.fullmatch(r"[!-~]{32,128}", auth_key):
        return error_response("authentication_required", "Informe a chave X-Nuclea-Key.", 401)
    audio = request.files.get("audio")
    if audio is None or not audio.filename or not audio.stream.read(1):
        return error_response("missing_audio", "Envie o arquivo no campo audio.", 400)
    audio.stream.seek(0)
    if request.form.get("responseMode", "speaker") != "speaker":
        return error_response("invalid_response_mode", "Este gateway atende apenas responseMode=speaker.", 400)
    if not N8N_WEBHOOK_URL:
        return error_response("gateway_not_configured", "Configure N8N_WEBHOOK_URL no gateway.", 503)
    device_id = (request.form.get("deviceId") or "nuclea-esp32").strip()[:128] or "nuclea-esp32"
    started = perf_counter()
    n8n_response = None
    try:
        n8n_response = requests.post(
            N8N_WEBHOOK_URL,
            files={"audio": (audio.filename, audio.stream, audio.mimetype or "audio/wav")},
            data={"sessionId": device_id},
            headers={"X-Request-ID": g.request_id, "X-Nuclea-Key": auth_key},
            timeout=(5, N8N_TIMEOUT_SECONDS),
            allow_redirects=False,
        )
        if n8n_response.status_code in (401, 403):
            return error_response("authentication_failed", "O n8n recusou a chave de acesso.",
                                  n8n_response.status_code)
        if not 200 <= n8n_response.status_code < 300:
            return error_response("n8n_unavailable", "O webhook do n8n recusou a requisicao.",
                                  502, n8n_response.status_code)
        if content_type(n8n_response).startswith("audio/"):
            return error_response("speaker_requires_streaming", "Use o workflow que retorna o stream_id, nao MP3.", 502)
        token = stream_ticket(n8n_response)
        if token is None:
            return error_response("invalid_stream_ticket", "O n8n nao retornou um ticket de audio valido.", 502)
    except requests.RequestException as error:
        return error_response("n8n_unavailable", "Nao foi possivel receber a resposta do n8n.",
                              dependency_error_status(error))
    finally:
        if n8n_response is not None:
            n8n_response.close()
        app.logger.info("request_id=%s dependency=n8n duration_ms=%.1f", g.request_id,
                        (perf_counter() - started) * 1000)
    return proxy_tts_stream(token)


def proxy_tts_stream(token):
    upstream = None
    started = perf_counter()
    request_id = g.request_id
    try:
        # Only the configured origin is trusted; URLs returned by n8n are ignored.
        upstream = requests.get(
            TTS_BASE_URL + "/v1/audio/speech/streams/" + token,
            stream=True,
            headers={"Accept": "application/x-ndjson", "Accept-Encoding": "identity", "X-Request-ID": request_id},
            timeout=(5, TTS_STREAM_TIMEOUT_SECONDS),
            allow_redirects=False,
        )
        if upstream.status_code != 200 or content_type(upstream) != "application/x-ndjson":
            upstream.close()
            return error_response("invalid_tts_stream", "O TTS nao retornou um stream PCM valido.",
                                  502, upstream.status_code)
        chunks = iter(upstream.iter_content(chunk_size=None))
        first = next((chunk for chunk in chunks if chunk), None)
        if first is None:
            upstream.close()
            return error_response("invalid_tts_stream", "O TTS retornou um stream vazio.", 502)
    except requests.RequestException as error:
        if upstream is not None:
            upstream.close()
        return error_response("tts_stream_unavailable", "Nao foi possivel acessar o stream do TTS.",
                              dependency_error_status(error))

    closed = False
    app.logger.info("request_id=%s dependency=tts headers_and_first_chunk_ms=%.1f",
                    request_id, (perf_counter() - started) * 1000)

    def close():
        nonlocal closed
        if not closed:
            closed = True
            upstream.close()
            app.logger.info("request_id=%s dependency=tts stream_closed_ms=%.1f", request_id,
                            (perf_counter() - started) * 1000)

    def generate():
        ends_with_newline = first.endswith(b"\n")
        try:
            yield first
            for chunk in chunks:
                if chunk:
                    ends_with_newline = chunk.endswith(b"\n")
                    yield chunk
        except requests.RequestException:
            app.logger.warning("request_id=%s code=tts_stream_interrupted", request_id)
            separator = b"" if ends_with_newline else b"\n"
            yield separator + b'{"type":"error","code":"tts_stream_interrupted","message":"TTS stream interrupted."}\n'
        finally:
            close()

    result = Response(generate(), content_type="application/x-ndjson")
    result.headers["X-Accel-Buffering"] = "no"
    result.headers["Cache-Control"] = "no-store, no-transform"
    result.headers["Content-Encoding"] = "identity"
    result.call_on_close(close)
    return result


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
