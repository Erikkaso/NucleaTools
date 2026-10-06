# Whisper Runtime

Servico FastAPI independente para transcricao com `faster-whisper`. Esta imagem
nao inclui TTS, Chatterbox nem dependencias CUDA. A configuracao atual usa o
Whisper `small` em CPU com quantizacao `int8`.

## Executar localmente

Na raiz do repositorio:

```powershell
docker compose -f whisper_runtime/docker-compose.yml up --build
```

A API fica em `http://127.0.0.1:8010`.

O primeiro inicio carrega o modelo configurado. O volume `whisper-models`
preserva o cache em `/root/.cache`; sem um cache previamente preenchido, o
container precisa conseguir obter os pesos na primeira inicializacao.

## Configuracao

| Variavel | Padrao |
| --- | --- |
| `WHISPER_MODEL` | `small` |
| `WHISPER_DEVICE` | `cpu` |
| `WHISPER_COMPUTE_TYPE` | `int8` |
| `WHISPER_LANGUAGE` | `pt` |

`GET /health` informa o modelo e o dispositivo configurados.

## API

```text
GET  /health
POST /v1/audio/transcriptions
```

A rota de transcricao aceita `multipart/form-data` com o campo `file` ou audio
binario bruto com um `Content-Type` reconhecido. O parametro opcional
`language` substitui o idioma configurado para aquela requisicao.

Resposta:

```json
{"text":"Bom dia, onde estao os teclados?"}
```

## n8n

Dentro do cluster, use:

```text
POST http://whisper-runtime.ollama-system.svc.cluster.local:8080/v1/audio/transcriptions
```

Para o audio recebido da NucleaInterface, configure o HTTP Request com:

```text
Body Content Type: n8n Binary File
Input Data Field Name: audio
```

O texto transcrito fica no campo `text` da resposta JSON.

## Kubernetes

```bash
cd whisper_runtime
docker build -t nuclic/whisper_runtime:1.0 .
docker push nuclic/whisper_runtime:1.0
kubectl -n ollama-system apply -f k8s/whisper-runtime.yaml
```

O manifesto atual cria o PVC `whisper-model-cache`, o Deployment e o Service
`whisper-runtime`. O Service publica a porta `8080` e encaminha para a porta
`8000` do container.
