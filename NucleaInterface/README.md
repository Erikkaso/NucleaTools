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

## Audio do ESP32

O firmware envia `multipart/form-data` para `POST /api/device-audio` com
`audio` (arquivo WAV) e `deviceId` (identificador da conversa). O Flask usa esse
identificador como `sessionId` no n8n e retorna `{"status":"ready"}` ao ESP32
quando recebe a resposta de audio.

O navegador consulta `GET /api/device-response` uma vez por segundo. A rota
retorna `204` quando nao existe resposta ou o audio mais recente quando existe.
Esse audio fica na RAM e e removido da fila ao ser consultado. Uma nova resposta
substitui a anterior se ainda nao foi consumida. Use um processo Flask e uma aba
para este teste; a primeira aba que consultar a rota recebe o audio.

Mantenha a pagina aberta no computador. Se o navegador bloquear reproducao
automatica, use o controle de reproducao exibido na mensagem.

Configure Wi-Fi e URL pelo portal do ESP32: conecte a rede `Nuclea-Config`
usando a senha `Nuclea-Dell2026` e abra exatamente `http://192.168.4.1`,
sem VPN ou proxy. Se uma senha antiga estiver salva no computador, esqueça
a rede e reconecte. Essa rede não fornece Internet.
Informe a URL base da interface, por exemplo `http://192.168.1.100:5000`,
sem `/api/device-audio`. O ESP32 precisa alcancar esse endereco; `localhost`
no ESP32 nao aponta para o computador. Libere a porta no firewall da rede local.
Depois de salvar, volte a rede normal. O portal fecha e a configuracao fica
salva na flash do ESP32. O detector só inicia após conectar ao Wi-Fi.
Consulte [o guia do firmware](../wake-word/README.md) para pinagem, teste sem
tela, gravação do firmware e diagnóstico do microfone.

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
