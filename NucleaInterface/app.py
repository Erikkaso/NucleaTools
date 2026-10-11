import os
import threading
import uuid

import requests
from flask import Flask, Response, jsonify, render_template, request, session

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-troque-em-producao")

# URL do webhook do n8n. Pode ser sobrescrita pela variável de ambiente N8N_WEBHOOK_URL.
N8N_WEBHOOK_URL = os.environ.get(
    "N8N_WEBHOOK_URL",
    #"https://n8n.200-129-37-25.sslip.io/webhook-test/8cf7d87c-4184-460b-8b0e-95affded7054",
    "https://n8n.200-129-37-25.sslip.io/webhook/8cf7d87c-4184-460b-8b0e-95affded7054",
)
REQUEST_TIMEOUT = int(os.environ.get("N8N_TIMEOUT_SECONDS", "60"))


class DeviceResponseMailbox:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._response: tuple[bytes, str] | None = None

    def put(self, content: bytes, content_type: str) -> None:
        with self._lock:
            self._response = (content, content_type)

    def take(self) -> tuple[bytes, str] | None:
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
    return render_template("index.html")


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
        return jsonify({"error": f"Não foi possível falar com o n8n: {exc}"}), 502

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
        return jsonify({"error": f"Não foi possível falar com o n8n: {exc}"}), 502

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
        return jsonify({"error": f"Não foi possível falar com o n8n: {exc}"}), 502

    content_type = response_audio_content_type(n8n_response)
    if content_type is None:
        return jsonify({"error": "O n8n nao retornou um arquivo de audio."}), 502

    device_response_mailbox.put(n8n_response.content, content_type)
    return jsonify({"status": "ready"})


@app.route("/api/device-response", methods=["GET"])
def device_response():
    queued = device_response_mailbox.take()
    if queued is None:
        return Response(status=204)
    content, content_type = queued
    response = Response(content, content_type=content_type)
    response.headers["Cache-Control"] = "no-store"
    return response


def proxy_audio_response(response: requests.Response) -> Response | tuple[Response, int]:
    content_type = response_audio_content_type(response)
    if content_type is None:
        return jsonify({"error": "O n8n nao retornou um arquivo de audio."}), 502
    return Response(response.content, content_type=content_type)


def response_audio_content_type(response: requests.Response) -> str | None:
    content_type = response.headers.get("Content-Type", "").split(";", maxsplit=1)[0].lower()
    return content_type if content_type.startswith("audio/") else None


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
