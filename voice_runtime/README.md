# Voice Runtime

Servico FastAPI que reune transcricao com `faster-whisper` e sintese de voz com
Chatterbox. O runtime carrega o TTS durante a inicializacao e serializa o uso dos
modelos para evitar execucoes simultaneas.

Na configuracao atual do Docker Compose, o Whisper `small` usa CPU com
quantizacao `int8`, enquanto o Chatterbox usa CUDA.

## Executar localmente

Na raiz do repositorio:

```powershell
docker compose -f voice_runtime/docker-compose.yml up --build
```

A API fica em `http://127.0.0.1:8080`.

O primeiro inicio carrega os pesos usados pelas bibliotecas. O volume
`voice-models` preserva o cache em `/root/.cache`, e `voice-cache` preserva o
condicionamento preparado da voz. Sem um cache previamente preenchido, o
container precisa conseguir obter os pesos na primeira inicializacao.

## Vozes

As referencias locais ficam em `voice_runtime/voices` e sao montadas como
somente leitura em `/voices`. Os arquivos presentes sao:

```text
anderson.wav
eric.wav
julio.wav
pamela.wav
sara.wav
```

Selecione a voz pelo nome do arquivo, sem `.wav`:

```powershell
$env:TTS_VOICE = "eric"
docker compose -f voice_runtime/docker-compose.yml up --build
```

O valor `default` usa a voz padrao do Chatterbox. Um nome invalido ou um arquivo
ausente tambem faz o runtime usar `default`.

## API

```text
GET  /health
POST /v1/audio/transcriptions
POST /v1/audio/speech
```

### Transcricao

`POST /v1/audio/transcriptions` aceita `multipart/form-data` com o campo `file`
ou audio binario bruto com um `Content-Type` reconhecido. O parametro opcional
`language` usa `pt` quando nao informado.

Resposta:

```json
{"text":"Bom dia, onde estao os teclados?"}
```

### Sintese

`POST /v1/audio/speech` recebe:

```json
{"text":"Os teclados estao no armario principal."}
```

A resposta e binaria com `Content-Type: audio/mpeg`.

## Configuracao

Variaveis usadas pelo runtime:

| Variavel | Padrao no Docker Compose |
| --- | --- |
| `WHISPER_MODEL` | `small` |
| `WHISPER_DEVICE` | `cpu` |
| `WHISPER_COMPUTE_TYPE` | `int8` |
| `TTS_VOICE` | `default` |
| `TTS_VOICES_DIR` | `/voices` |
| `TTS_VOICE_CACHE_DIR` | `/voice-cache` |
| `TTS_MODEL_REVISION` | `v3` |
| `TTS_LANGUAGE_ID` | `pt` |
| `TTS_EXAGGERATION` | `0.5` |
| `TTS_CFG_WEIGHT` | `0.5` |

## n8n

Para gerar audio dentro do cluster:

```text
POST http://voice-runtime.ollama-system.svc.cluster.local:8080/v1/audio/speech
```

Envie JSON com o texto do agente:

```json
{"text":"={{ $json.output }}"}
```

Configure o HTTP Request para receber um arquivo. O `Respond to Webhook` deve
responder com esse arquivo binario.

Se este runtime for usado para transcricao do audio enviado pela
NucleaInterface, a propriedade binaria de entrada no n8n e `audio`.

## Kubernetes

Execute a partir da raiz do repositorio:

```bash
docker build -t nuclic/voice_runtime:2.3 voice_runtime
docker push nuclic/voice_runtime:2.3
kubectl -n ollama-system apply -f voice_runtime/k8s/voice-runtime.yaml
```

O manifesto atual cria os PVCs de modelos, condicionamentos e referencias de
voz, alem do Deployment e do Service `voice-runtime` na porta `8080`.

Ainda na raiz, para adicionar uma referencia ao PVC e seleciona-la, use os
comandos abaixo. O arquivo `./eric.wav` deve existir nesse diretorio;
ajuste o caminho se estiver em outro local.

```bash
kubectl -n ollama-system apply -f voice_runtime/k8s/voice-assets-loader.yaml
kubectl -n ollama-system cp ./eric.wav voice-assets-loader:/voices/eric.wav
kubectl -n ollama-system delete pod voice-assets-loader
kubectl -n ollama-system set env deployment/voice-runtime TTS_VOICE=eric
kubectl -n ollama-system rollout restart deployment/voice-runtime
```
