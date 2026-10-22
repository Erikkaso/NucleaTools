# Voice Runtime TTS

Servico FastAPI exclusivo para sintese com Chatterbox Multilingual em CUDA.
Whisper foi removido deste container; a transcricao permanece na aplicacao
separada `whisper_runtime`.

## Inicializacao e desempenho

Antes de aceitar requisicoes, o processo carrega os pesos, prepara ou recupera
o condicionamento da voz e gera uma frase curta de aquecimento, descartada.
O modelo e a voz permanecem em memoria entre requisicoes e sao liberados no
encerramento. Nao ha alternancia de modelos nem recarga por chamada.

A fila interna permite uma sintese por vez. Mesmo se uma requisicao for
cancelada, outra nao comeca enquanto o trabalho anterior na GPU nao terminar.
Use apenas um worker por GPU, como configurado no Dockerfile, para nao duplicar
os pesos em VRAM.

O aquecimento evita parte dos custos da primeira chamada, mas nao elimina o
custo de gerar audio. Nao ha garantia de ganho percentual sem medir na GPU.
Os parametros de geracao e a qualidade MP3 foram preservados. Os logs mostram:

- `tts_ready startup_ms`: carregamento e aquecimento.
- `tts_request queue_ms work_ms`: espera na fila e trabalho da requisicao.
- `tts_synthesis generation_ms encoding_ms audio_seconds chars`: geracao,
  transferencia para CPU e codificacao, sem registrar o texto enviado.

## Executar

Na raiz do repositorio:

```powershell
docker compose -f voice_runtime/docker-compose.yml up -d --build
```

API: `http://127.0.0.1:8080`. O primeiro inicio pode baixar pesos. O volume
`voice-models` preserva `/root/.cache`, e `voice-cache` preserva o condicionamento
da voz. Cache em disco nao substitui o carregamento em VRAM a cada reinicio.

## Voz e configuracao

Coloque uma referencia WAV em `voice_runtime/voices/<nome>.wav` e selecione o
nome sem extensao. A pasta e montada em `/voices` como somente leitura:

```powershell
$env:TTS_VOICE = "eric"
docker compose -f voice_runtime/docker-compose.yml up -d --build
```

`default` usa a voz embutida. Se o arquivo selecionado nao existir, o servico
registra o fallback e usa `default`. Reinicie ou recrie o processo para trocar
a voz. No Kubernetes, as referencias precisam estar no PVC `voice-assets`;
o volume montado em `/voices` substitui qualquer pasta da imagem nesse caminho.

| Variavel | Padrao |
| --- | --- |
| `TTS_VOICE` | `default` |
| `TTS_VOICES_DIR` | `/voices` |
| `TTS_VOICE_CACHE_DIR` | `/voice-cache` |
| `TTS_MODEL_REVISION` | `v3` (identificador do cache, nao seletor de checkpoint) |
| `TTS_LANGUAGE_ID` | `pt` |
| `TTS_EXAGGERATION` | `0.5` |
| `TTS_CFG_WEIGHT` | `0.5` |
| `TTS_MP3_BITRATE` | `128` kbps |
| `TTS_WARMUP_TEXT` | `Ola.` |

Definir `TTS_WARMUP_TEXT` como string vazia pula apenas a geracao de aquecimento;
os pesos e o condicionamento continuam sendo carregados no startup. Para mudar
variaveis nao expostas no Compose, adicione-as ao bloco `environment` do servico.

## API e n8n

```text
GET  /health
POST /v1/audio/speech
```

`/health` retorna `{"status":"ready","service":"tts"}` depois do aquecimento.
O servidor so comeca a atender apos o startup terminar; uma falha nessa etapa
impede o processo de ficar pronto.

Sintese recebe JSON:

```json
{"text":"Os teclados estao no armario principal."}
```

A resposta e MP3 binario em memoria com `Content-Type: audio/mpeg`, sem arquivo
persistido. Texto vazio retorna 422; falha de sintese `RuntimeError` retorna 503.

No HTTP Request do n8n dentro do cluster:

```text
POST http://voice-runtime.ollama-system.svc.cluster.local:8080/v1/audio/speech
```

Envie o texto do agente no campo `text`, em modo Expression, com
`{{ $json.output }}`. Configure a resposta como arquivo e passe o campo binario
para o `Respond to Webhook`.

**Migracao:** `/v1/audio/transcriptions` nao existe mais neste servico (404).
Aponte a etapa Whisper para o servico separado, quando implantado:

```text
POST http://whisper-runtime.ollama-system.svc.cluster.local:8080/v1/audio/transcriptions
```

## Kubernetes

Da raiz do repositorio:

```bash
docker build -t nuclic/voice_runtime:2.4 voice_runtime
docker push nuclic/voice_runtime:2.4
kubectl -n ollama-system apply -f voice_runtime/k8s/voice-runtime.yaml
kubectl -n ollama-system rollout status deployment/voice-runtime
kubectl -n ollama-system logs deployment/voice-runtime -f
```

Ou, dentro de `voice_runtime`, use `docker build -t nuclic/voice_runtime:2.4 .`.
O manifesto solicita uma GPU e cria os PVCs de pesos, condicionamentos e vozes.
O rollout usa `Recreate`: encerra o pod antigo antes de reservar a unica GPU
para o novo. Ha indisponibilidade durante o carregamento do substituto.
Se outro manifesto gerencia o container no seu cluster, atualize a imagem nele;
alterar o codigo local nao atualiza o pod automaticamente.

Para enviar uma voz ao PVC, execute da raiz e ajuste o caminho do WAV:

```bash
kubectl -n ollama-system apply -f voice_runtime/k8s/voice-assets-loader.yaml
kubectl -n ollama-system cp ./eric.wav voice-assets-loader:/voices/eric.wav
kubectl -n ollama-system delete pod voice-assets-loader
kubectl -n ollama-system set env deployment/voice-runtime TTS_VOICE=eric
```

O `set env` altera o template e inicia um novo rollout. Preserve o mesmo nome
de voz no manifesto para que uma aplicacao futura nao volte para `default`.
