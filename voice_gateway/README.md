# Voice Gateway

Backend independente extraido do fluxo de audio da NucleaInterface. O ESP32
envia o WAV e recebe a resposta progressiva na mesma requisicao HTTP.
Nao possui frontend, cookies, SECRET_KEY, modelos, mailbox ou banco de dados.
Nao altera nem substitui os arquivos da NucleaInterface.

```text
ESP32 -- POST /api/device-audio (WAV) --> Voice Gateway
                                         |
                                         +-- POST webhook n8n
                                         |      Whisper -> IA -> ticket TTS
                                         |
                                         +-- GET stream do TTS
ESP32 <-------- pacotes PCM NDJSON -------+
```

O gateway nao gera voz: repassa os eventos do TTS conforme os recebe. O ESP
continua usando o buffer e o I2S existentes para reproduzir na caixa de som.
O TTS atual gera uma frase por vez; pode haver pausas se gerar mais devagar
que a reproducao. O gateway nao torna essa geracao nativamente continua.

## Contrato

`POST /api/device-audio`, corpo `multipart/form-data`:

Header obrigatorio: `X-Nuclea-Key` com 32 a 128 caracteres ASCII sem espacos.
A chave recebida e repassada somente ao webhook do n8n, nunca ao TTS.
O gateway nao armazena uma chave mestra nem acrescenta credenciais a clientes anonimos.

| Campo | Valor |
| --- | --- |
| `audio` | Arquivo WAV do comando (obrigatorio) |
| `deviceId` | Identificador da conversa; padrao `nuclea-esp32` |
| `responseMode` | `speaker`; tambem e o padrao quando omitido |

O gateway encaminha o arquivo como `audio` e o identificador como `sessionId`
para o n8n, preservando o contrato do workflow de streaming existente.
O workflow deve retornar `{"stream_id":"..."}` ou uma lista com exatamente
um objeto desse tipo. Retorno MP3 ou texto sem ticket falha com HTTP 502.

A resposta valida tem `Content-Type: application/x-ndjson`:

```json
{"type":"start","format":"pcm_s16le","channels":1}
{"type":"audio","seq":0,"sample_rate":24000,"data":"BASE64_PCM16LE"}
{"type":"end"}
```

O exemplo e ilustrativo: `data` transporta bytes reais codificados em base64.
O TTS tambem pode enviar `ping` ou `error`. Os pacotes sao repassados sem
converter para MP3 ou juntar o audio inteiro. O firmware exige PCM16 mono
a 24 kHz, e valida sequencia e eventos de encerramento.

O envio total e limitado a 2 MiB; o WAV de 12 segundos a 16 kHz, mono e 16 bits
ocupa aproximadamente 384 kB. O upload e mantido em memoria. Audio de entrada
e resposta nao sao gravados em disco pelo gateway. Ao desconectar o cliente,
a conexao de streaming com o TTS e fechada; o runtime ainda pode precisar
concluir a geracao GPU em andamento antes de liberar sua fila.

`GET /health` verifica apenas que o gateway esta respondendo; nao testa n8n,
TTS nem GPU. Nao existem as rotas de navegador da NucleaInterface.

## Configuracao

Crie `.env` nesta pasta a partir de `.env.example` e ajuste:

```dotenv
N8N_WEBHOOK_URL=https://SEU_N8N/webhook/ID_DO_WORKFLOW_ATIVO
TTS_BASE_URL=http://ollama-service.ollama-system.svc.cluster.local:8000
N8N_TIMEOUT_SECONDS=220
TTS_STREAM_TIMEOUT_SECONDS=90
PORT=5000
```

`TTS_BASE_URL` precisa apontar para a **mesma instancia** que criou o ticket.
O runtime atual guarda tickets em memoria: mantenha uma replica/processo do
TTS; distribuir POST e GET entre instancias diferentes pode causar 404.
Se voce usa o Service `voice-runtime` do exemplo do runtime, sua porta e
`8080`; ajuste para `http://voice-runtime.ollama-system.svc.cluster.local:8080`.

O DNS `*.svc.cluster.local` funciona dentro do Kubernetes, nao no Windows.
Para rodar localmente, use um endereco do TTS acessivel pelo computador,
por exemplo `http://127.0.0.1:8000` quando ele estiver exposto nessa porta.

Nao e necessario SECRET_KEY: nao existem sessoes de navegador. A configuracao
do ambiente prevalece sobre `.env`. O Docker recebe variaveis de ambiente;
o arquivo `.env` nao entra na imagem. A URL do webhook e obrigatoria para
atender audio; sua ausencia gera HTTP 503 `gateway_not_configured`.

## Executar Localmente

Dentro de `voice_gateway`:

```powershell
python -m pip install -r requirements.txt
python app.py
```

Health: `http://127.0.0.1:5000/health`. Se a NucleaInterface ainda ocupa a
porta 5000, pare-a ou configure outro `PORT`. O servidor de desenvolvimento
serve para teste local, nao para publicacao na Internet.

Teste com um WAV real e `curl.exe` no Windows:

```powershell
curl.exe -N http://127.0.0.1:5000/api/device-audio -H "X-Nuclea-Key: $env:NUCLEA_TEST_KEY" -F "audio=@command.wav;type=audio/wav" -F "deviceId=esp-teste" -F "responseMode=speaker"
```

O curl mostra JSON com audio em base64, nao reproduz o som. Os IDs sao
descartaveis: nao reutilize manualmente o ticket de uma resposta anterior.

## Docker

Dentro de `voice_gateway`:

```powershell
docker build -t nuclic/voice_gateway:1.2 .
docker run --rm --env-file .env -p 5000:5000 nuclic/voice_gateway:1.2
```

No container, `127.0.0.1` e o proprio container. No Docker Desktop, para
acessar um TTS exposto no Windows, use `http://host.docker.internal:8000`.
No Kubernetes, use o DNS interno do Service.

A imagem usa Python slim e Gunicorn com um processo, quatro threads e timeout
de 300 segundos. Nao inclui CUDA, PyTorch, FFmpeg, Whisper nem modelos TTS.
Quatro threads limitam quantas requisicoes simultaneas podem ser atendidas;
a fila da GPU continua sendo administrada pelo TTS, nao pelo gateway.

## Kubernetes Sem Port-Forward

1. Publique a imagem:

```powershell
docker build -t nuclic/voice_gateway:1.2 .
docker push nuclic/voice_gateway:1.2
```

2. Em `k8s/voice-gateway.yaml`, substitua `N8N_WEBHOOK_URL` pela URL de producao
   do workflow ativo. Confira imagem, namespace e o Service/porta do TTS.
3. Aplique o manifesto no cluster que ja possui o namespace `ollama-system`:

```bash
kubectl apply -f k8s/voice-gateway.yaml
kubectl rollout status deployment/voice-gateway -n ollama-system
kubectl logs -n ollama-system deployment/voice-gateway -f
```

O Service de exemplo usa NodePort `30500`. Escolha uma porta livre se ela ja
estiver reservada no cluster. Publique por um Ingress HTTPS com certificado
valido; no portal Wi-Fi do ESP, configure a URL base publica, por exemplo:

```text
https://voice-gateway.200-129-37-25.sslip.io
```

Nao inclua `/api/device-audio` no portal: o firmware atual acrescenta esse
caminho. Nao use `localhost` no ESP. Garanta rota/firewall entre a rede Wi-Fi
e o node. Para autenticacao, atualize o firmware, o gateway e a credencial
do Webhook conforme a secao abaixo. O TTS nao muda. Nada foi aplicado ao cluster automaticamente.

O fluxo passa a funcionar sem computador ligado ou port-forward: o gateway
acessa o TTS pela rede interna do cluster, e o ESP acessa apenas o gateway.
So mover o gateway para Docker no Windows nao elimina essa dependencia;
ele precisa executar numa rede com acesso direto ao TTS.

**Seguranca:** esta versao exige uma chave do cliente e delega sua validacao ao n8n.
Restrinja o NodePort a uma LAN confiavel/firewall; nao exponha a porta
diretamente na Internet. Configure Header Auth no n8n antes de expor o gateway.
Para HTTPS, use um Ingress/reverse proxy com certificado valido;
nao desative validacao TLS no ESP. O proxy deve repassar streaming sem
bufferizar/comprimir o corpo, sem cache e com timeouts adequados ao fluxo.
Nao adicione middleware de buffering do Traefik a essa rota.

A resposta de streaming declara `Content-Encoding: identity` e
`Cache-Control: no-store, no-transform`. O firmware tambem solicita encoding
`identity`: ele nao descomprime gzip ou Brotli. Remova qualquer middleware que
force compressao apesar desses headers. O status HTTP 200 sozinho nao confirma
que chegaram pacotes PCM; confira os eventos e os logs do ESP.

Para atualizar somente a imagem sem sobrescrever a ConfigMap ja configurada:

```bash
kubectl set image deployment/voice-gateway voice-gateway=nuclic/voice_gateway:1.2 -n ollama-system
kubectl rollout status deployment/voice-gateway -n ollama-system
```

## Chave de Acesso no n8n e no ESP

1. Gere uma chave aleatoria localmente, sem publica-la no repositorio:

   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. No node **Webhook** do n8n, selecione **Authentication: Header Auth**.
   Crie uma credencial com **Name: X-Nuclea-Key** e **Value: sua chave**.
   Salve/publique o workflow. Use autenticacao nativa, nao um IF apos o Webhook.
   Referencia: [Webhook credentials](https://docs.n8n.io/integrations/builtin/credentials/webhook/).
3. Publique a nova imagem do gateway e atualize o Deployment. Nenhuma chave
   precisa estar na ConfigMap, no Dockerfile ou no ambiente do gateway.
4. Grave o firmware atualizado. Segure BOOT por 3 segundos, conecte-se a
   `Nuclea-Config` e abra `http://192.168.4.1`. Informe a mesma chave em
   **Chave de acesso do n8n**, confira rede/senha/URL HTTPS e salve.
5. Para trocar a chave, atualize a credencial do n8n, clique em **Editar**
   ao lado da chave no portal e preencha o novo valor. Rota e chave ficam
   bloqueadas por padrao; sem editar, salvar o Wi-Fi preserva os valores existentes.
   O campo fica vazio ao reabrir: vazio preserva a chave existente. O status
   mostra apenas se ha chave salva. A chave nao e devolvida pela API do portal.

Sem chave ou com formato invalido, o gateway retorna 401 antes de interpretar
o upload. Uma chave incorreta e encaminhada ao n8n, que deve responder 401/403;
o gateway preserva esse status e nao acessa o TTS. Se Header Auth estiver
desativado no n8n, esta arquitetura NAO valida o segredo: apenas exigir um
header nao autentica o cliente. Mantenha o webhook protegido.

Use HTTPS no ESP; o firmware bloqueia envio de chave por HTTP. A conexao
gateway/n8n tambem deve usar HTTPS ou uma rede interna confiavel. O portal
HTTP e restrito ao AP protegido por senha, mas nao e TLS. A NVS atual nao
e criptografada: a chave persistida nao resiste a acesso fisico a flash.
Evite compartilhar headers de execucoes do n8n, pois podem conter a chave.
Nunca inclua a chave em URLs, logs, capturas de tela ou exports de credenciais.

## Falhas e Logs

Erros anteriores ao inicio do stream retornam JSON com `code`, `error` e
`request_id`. O mesmo ID vem no header `X-Request-ID` e nos logs:

| Code | Verificacao |
| --- | --- |
| `authentication_required` | Falta X-Nuclea-Key ou formato invalido; HTTP 401 |
| `authentication_failed` | n8n recusou a chave; HTTP 401/403 |
| `n8n_unavailable` | URL ativa de producao, conectividade e status do webhook |
| `invalid_stream_ticket` | n8n retornou objeto/lista unica com `stream_id` valido |
| `speaker_requires_streaming` | Workflow ainda retorna MP3 em vez do ticket |
| `tts_stream_unavailable` | DNS, Service e porta do TTS acessiveis pelo gateway |
| `invalid_tts_stream` | Status e MIME do TTS; ticket expirado/consumido ou instancia errada |

Os logs incluem tempo da chamada ao n8n, primeiro bloco e duracao da conexao
TTS, mas nao incluem voz, texto da conversa, conteudo do ticket ou URL secreta
do webhook. O primeiro bloco pode ser apenas `start`, nao o primeiro som.
Depois de iniciar HTTP 200, uma falha de transporte gera evento `error`,
pois nao e mais possivel trocar o status HTTP. O ESP interrompe a reproducao.

Nao ha retries automaticos: repetir um POST poderia duplicar o processamento
da conversa, e repetir o GET poderia reutilizar um ticket de uso unico.
Timeouts de 220/90 segundos sao de leitura por dependencia, nao uma garantia
de duracao total; o ESP mantem seus limites de requisicao/progresso existentes.

## Verificar

Na raiz do repositorio:

```powershell
python -m pip install -r voice_gateway/requirements-dev.txt
python -m pytest voice_gateway/tests -q
```

Os testes cobrem encaminhamento do WAV/sessao, tickets objeto/lista unica,
erro de dependencia, limites de envio, fechamento ao desconectar e streaming
por HTTP local real que entrega PCM antes do termino do upstream.
Nao validam som fisico, GPU, cluster ou workflow publicado.
