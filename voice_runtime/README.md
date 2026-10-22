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
POST /v1/audio/speech/streams
GET  /v1/audio/speech/streams/{stream_id}
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

### Resposta progressiva

Para a interface de voz nova, importe
`NucleaInterface/workflows/nuclea-streaming.json` no n8n. O nodo TTS usa
`POST /v1/audio/speech/streams` com o mesmo JSON `text`, mas recebe um
identificador em JSON imediatamente (202), nao um arquivo. O webhook devolve
esse JSON. A interface abre o GET correspondente diretamente por seu backend,
evitando o buffering do nodo HTTP Request configurado como arquivo.

Cada identificador e aleatorio, de uso unico, expira em 120 segundos e guarda
somente texto em memoria. O limite e 32 identificadores pendentes e 6000
caracteres por texto. O servico deve continuar com um worker e uma replica;
reiniciar o pod invalida identificadores e interrompe streams em andamento.

O GET devolve `application/x-ndjson`. A geracao so comeca quando o GET e
consumido. Os eventos sao `start`, `audio`, `ping`, `end` ou `error`. Cada
`audio` contem `seq`, `sample_rate` e `data` (PCM16 little-endian mono em
base64), em pacotes de ate 100 ms. `ping` mantem a conexao durante a espera.
Uma espera de frase ou fila maior que 90 segundos gera evento de erro;
pings nao renovam esse prazo. Trabalho CUDA em andamento termina antes de
liberar a GPU, mesmo apos erro ou cancelamento do cliente.
Nenhum arquivo e persistido. Nao registre o identificador de acesso em logs
publicos nem publique este servico sem protecao de acesso.

O Chatterbox ainda gera uma frase inteira antes de disponibilizar seus pacotes.
A frase seguinte e gerada enquanto o navegador reproduz o buffer anterior.
Isso nao e streaming nativo dentro de uma frase. A divisao preserva palavras
e limita normalmente cada frase a 160 caracteres; palavras individuais maiores
nao sao cortadas. Entonacao entre frases pode variar.

O navegador acumula audio antes de tocar. Continuidade depende de a GPU produzir
audio suficientemente rapido: se faltar audio, a interface volta a acumular
buffer. Nao ha garantia de ausencia de pausas com geracao mais lenta que tempo
real. Ajuste `TTS_PREBUFFER_SECONDS` na NucleaInterface para equilibrar espera
inicial e estabilidade.

Cancelamento interrompe as proximas frases e fecha a conexao. A geracao CUDA
ja iniciada termina antes de liberar a GPU. Os logs `tts_pcm` mostram tempo de
geracao por frase; `tts_stream` mostra fila, primeiro audio e total do stream.

Desative buffering/compressao intermediaria no proxy reverso para essa rota.
O backend envia `X-Accel-Buffering: no` e `Cache-Control: no-store`, mas cada
proxy deve respeitar ou ter configuracao equivalente. O navegador nao precisa
acessar diretamente a rede interna do cluster; o servidor da interface precisa.

**Migracao:** `/v1/audio/transcriptions` nao existe mais neste servico (404).
Aponte a etapa Whisper para o servico separado, quando implantado:

```text
POST http://whisper-runtime.ollama-system.svc.cluster.local:8080/v1/audio/transcriptions
```

## Kubernetes

Da raiz do repositorio:

```bash
docker build -t nuclic/voice_runtime:2.5 voice_runtime
docker push nuclic/voice_runtime:2.5
kubectl -n ollama-system apply -f voice_runtime/k8s/voice-runtime.yaml
kubectl -n ollama-system rollout status deployment/voice-runtime
kubectl -n ollama-system logs deployment/voice-runtime -f
```

Ou, dentro de `voice_runtime`, use `docker build -t nuclic/voice_runtime:2.5 .`.
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
