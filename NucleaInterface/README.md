# NucleaInterface

Interface web Flask para conversar com um workflow do n8n por texto ou áudio.
O navegador envia a entrada ao Flask, o Flask encaminha ao webhook e espera que
o n8n devolva um arquivo de áudio. Esse áudio é reproduzido diretamente no
navegador e não é persistido pela interface.

## Executar localmente

```powershell
cd NucleaInterface
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Acesse `http://localhost:5000`.

O servidor iniciado por `app.py` usa o modo de desenvolvimento do Flask. Esta
pasta não possui Dockerfile nem manifesto Kubernetes.

## Configuração

Variáveis lidas por `app.py`:

| Variável | Função | Padrão |
| --- | --- | --- |
| `N8N_WEBHOOK_URL` | Webhook chamado pela interface | URL definida em `app.py` |
| `N8N_TIMEOUT_SECONDS` | Timeout da chamada ao n8n | `60` |
| `SECRET_KEY` | Assinatura da sessão Flask | valor de desenvolvimento |
| `PORT` | Porta HTTP local | `5000` |

Exemplo:

```powershell
$env:N8N_WEBHOOK_URL = "https://seu-n8n/webhook/seu-workflow"
$env:N8N_TIMEOUT_SECONDS = "180"
$env:SECRET_KEY = "substitua-por-um-segredo"
python app.py
```

Para uso contínuo, o workflow do n8n precisa estar ativo e a URL deve utilizar
`/webhook/`. URLs com `/webhook-test/` só funcionam enquanto o n8n aguarda uma
execução de teste.

## Contrato com o n8n

### Entrada de texto

`POST /api/chat` recebe:

```json
{"message":"Onde estão os teclados?"}
```

O Flask envia ao webhook:

```json
{
  "message": "Onde estão os teclados?",
  "sessionId": "uuid-da-sessao"
}
```

### Entrada de áudio

`POST /api/chat-audio` recebe `multipart/form-data` e encaminha:

- arquivo no campo `audio`;
- identificador no campo `sessionId`.

No n8n, o arquivo fica na propriedade binária `audio`. O nó Webhook deve estar
configurado para interpretar multipart, com `Raw Body` desativado.

### Resposta

Nos dois fluxos, o webhook deve responder com bytes de áudio e um
`Content-Type` iniciado por `audio/`, normalmente `audio/mpeg`. Respostas JSON ou
texto são rejeitadas pela interface.

## Fluxo n8n com áudio

Fluxo esperado:

```text
Webhook -> Whisper Runtime -> AI Agent -> Voice Runtime -> Respond to Webhook
```

Para transcrever o áudio recebido:

```text
POST http://whisper-runtime.ollama-system.svc.cluster.local:8080/v1/audio/transcriptions
```

No HTTP Request do n8n:

- `Body Content Type`: `n8n Binary File`;
- `Input Data Field Name`: `audio`;
- resposta esperada: JSON com o campo `text`.

Depois do agente, envie a resposta textual ao TTS:

```text
POST http://voice-runtime.ollama-system.svc.cluster.local:8080/v1/audio/speech
```

Corpo JSON:

```json
{"text":"={{ $json.output }}"}
```

Configure a resposta do HTTP Request como arquivo e armazene o resultado numa
propriedade binária, por exemplo `audio`. No `Respond to Webhook`, responda com
`Binary File` usando essa propriedade.

## Wake word no navegador

A página solicita acesso contínuo ao microfone e carrega localmente:

```text
static/wakeword/nuclea_int8.tflite
static/wakeword.mjs
static/wakeword-worklet.mjs
```

Quando o detector aceita a wake word, a interface inicia uma gravação e a envia
automaticamente após silêncio ou ao atingir o limite máximo. O botão de
microfone também permite iniciar e encerrar a gravação manualmente.

O modelo da interface é independente do modelo embarcado no ESP32. Ao promover
um novo TFLite, também precisam ser atualizados os parâmetros de quantização e
os thresholds definidos em `static/wakeword.mjs`.

## Requisito do navegador

O microfone funciona em `http://localhost` ou numa origem HTTPS. Uma publicação
em HTTP comum não recebe permissão de `getUserMedia` nos navegadores atuais.
