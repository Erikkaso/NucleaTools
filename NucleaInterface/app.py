import os
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


def proxy_audio_response(response: requests.Response) -> Response | tuple[Response, int]:
    content_type = response.headers.get("Content-Type", "").split(";", maxsplit=1)[0].lower()
    if not content_type.startswith("audio/"):
        return jsonify({"error": "O n8n nao retornou um arquivo de audio."}), 502
    return Response(response.content, content_type=content_type)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
