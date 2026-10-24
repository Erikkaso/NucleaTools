# NucleaInterface

Interface de conversa por voz: botao para gravar/parar, estado da conversa,
visualizacao de amplitude e reproducao progressiva. Nao ha campo de escrita.
O botao de cancelar interrompe gravacao, requisicao e reproducao. A gravacao
tem limite de 60 segundos. O microfone nao fica ouvindo em segundo plano.

## Fluxo

```text
Navegador ou ESP32 -> NucleaInterface -> n8n: Whisper -> agente -> ticket TTS
NucleaInterface -> voice_runtime: PCM por frases -> navegador com buffer
```

Whisper, agente, ferramentas, memoria e credenciais continuam no n8n. A resposta
textual completa do agente ainda e aguardada. O streaming novo comeca no TTS,
nao nos tokens do agente nem na gravacao de entrada.

O n8n nao transporta os pacotes: seu HTTP Request em modo arquivo aguardaria
o audio inteiro. Ele solicita um identificador e o devolve como JSON. O servidor
Flask abre o stream no TTS e repassa os bytes conforme chegam, sem salvar audio.
O navegador nao precisa conhecer o endereco interno do TTS.

## Preparar o runtime e workflow

1. Publique o `voice_runtime` atualizado (imagem exemplo `nuclic/voice_runtime:2.5`).
   Se ele estiver no pod do Ollama, atualize esse container no manifesto usado
   pelo seu cluster, nao crie outro pod disputando a mesma GPU.
2. Importe [workflows/nuclea-streaming.json](workflows/nuclea-streaming.json) no n8n.
   E uma copia ajustada do workflow fornecido, nao uma alteracao na instancia
   n8n nem no arquivo original de Downloads.
3. Confira a URL do nodo `HTTP Request TTS`: o host original foi preservado,
   alterando apenas a rota para `/v1/audio/speech/streams`. Resposta agora e
   `JSON`, e o `Respond to Webhook` devolve `={{ $json }}` como JSON.
4. A etapa Whisper aceita o campo binario `audio` ou `audio0`. O restante do
   fluxo, inclusive conexoes, foi preservado.
5. Desative o workflow antigo antes de ativar a copia se usarem o mesmo path
   de webhook. Confirme as credenciais ao importar. Use a URL de producao com
   `/webhook/`; `/webhook-test/` exige que o editor esteja escutando.

Nao basta habilitar a opcao de streaming de texto do n8n: o contrato utilizado
por esta interface e o identificador de audio retornado pelo runtime.

## Executar localmente

Dentro de `NucleaInterface`, com um ambiente Python ativo:

```powershell
pip install -r requirements.txt
$env:N8N_WEBHOOK_URL = "https://SEU-N8N/webhook/8cf7d87c-4184-460b-8b0e-95affded7054"
$env:TTS_BASE_URL = "http://127.0.0.1:18080"
$env:SECRET_KEY = "substitua-por-um-segredo-aleatorio"
python app.py
```

Abra `http://localhost:5000`. Clique no microfone para gravar, novamente para
enviar. O navegador precisa de permissao para o microfone e para tocar audio;
o primeiro clique libera a reproducao. Nao ha reproducao automatica antes de
uma interacao do usuario.

O processo Flask precisa alcancar o MESMO runtime que criou o identificador.
Se o TTS estiver no servico do workflow fornecido, abra outro terminal:

```bash
kubectl -n ollama-system port-forward svc/ollama-service 18080:8000
```

Se estiver no Deployment independente de exemplo do runtime, use o Service
correspondente em ambos os lados (n8n e interface):

```bash
kubectl -n ollama-system port-forward svc/voice-runtime 18080:8080
```

Dentro do cluster, `TTS_BASE_URL` pode usar o DNS do Service em vez de port-forward.
`localhost` sempre identifica a maquina/container do processo que faz a chamada.
Em outra maquina, abra a interface por HTTPS; HTTP em IP da rede local nao
habilita o microfone nos navegadores.

## Configuracao

| Variavel | Padrao | Uso |
| --- | --- | --- |
| `N8N_WEBHOOK_URL` | URL existente em `app.py` | Defina explicitamente para seu workflow |
| `N8N_TIMEOUT_SECONDS` | `220` | Espera por transcricao, agente e ticket |
| `TTS_BASE_URL` | `http://127.0.0.1:8080` | Endereco do runtime acessivel pelo Flask |
| `TTS_STREAM_TIMEOUT_SECONDS` | `90` | Timeout de leitura do stream |
| `TTS_PREBUFFER_SECONDS` | `3` | Audio acumulado antes de reproduzir; entre 0 e 12 |
| `TTS_AUDIO_PROGRESS_TIMEOUT_SECONDS` | `60` | Prazo sem novos pacotes de audio no navegador; entre 5 e 300 |
| `PORT` | `5000` | Porta da interface |
| `SECRET_KEY` | Valor de desenvolvimento | Troque antes de publicar |

Um buffer maior reduz a chance de pausas, mas aumenta a espera inicial. O
Chatterbox gera uma frase inteira de cada vez e envia PCM16 mono em pacotes
de ate 100 ms. Enquanto uma frase toca, a proxima pode estar sendo gerada.
Se faltar audio, o player reconstroi o buffer e retoma sem sobrepor pacotes.
Nao e possivel garantir continuidade se a geracao ficar mais lenta que a fala.
Frases geradas separadamente tambem podem ter variacao de entonacao.
O player limita o audio adiantado a aproximadamente 12 segundos e pausa a
leitura quando esse limite e atingido. Pings nao renovam o prazo sem audio:
uma geracao travada produz erro, em vez de manter a tela esperando sem limite.
O runtime tambem possui limite de 90 segundos por espera de frase/fila.

Identificadores sao de uso unico, expiram em 120 segundos e nao sobrevivem a
reinicios do TTS. Um stream interrompido nao e retomado nem repetido
automaticamente, evitando reproduzir a mesma resposta duas vezes.

## Rotas

- `POST /api/chat-audio`: multipart `audio`; encaminha com `sessionId` ao n8n.
- `POST /api/chat`: JSON `message`; API legada, sem campo de texto na tela.
- `POST /api/device-audio`: multipart `audio`, `deviceId` opcional e
  `responseMode` opcional. O padrao `browser` guarda a resposta para o navegador;
  `speaker` devolve o stream diretamente na resposta HTTP para o ESP32.
- `GET /api/device-response`: 204 sem resposta; senao entrega o stream uma vez.

O navegador consulta respostas do ESP32 apos liberar audio por interacao, desde
que nao esteja em outra conversa. A caixa de respostas do dispositivo continua
sendo unica e em memoria: uma resposta nova substitui a anterior. Nao e um
roteador para varios dispositivos/usuarios. O ESP continua enviando gravacao
completa; esta mudanca e na entrega da resposta.

### Resposta no alto-falante do ESP32

O firmware com MAX98357A envia `responseMode=speaker`. Nessa modalidade, a
interface repassa os eventos PCM NDJSON na mesma conexao do upload e nao usa
nem consome a caixa de respostas do navegador. Nao e necessario deixar a pagina
aberta. O workflow n8n e o runtime de streaming existentes sao mantidos.

Reinicie o Flask apos atualizar `app.py`. O workflow precisa devolver o
identificador de streaming; um MP3 legado e recusado com
`speaker_requires_streaming`, porque o firmware nao possui decodificador MP3.
Consulte o README de `wake-word` para pinagem e configuracao do amplificador.

Respostas legadas `audio/*` ainda sao aceitas, mas precisam chegar completas
antes da reproducao. JSON com identificador invalido retorna erro controlado.
URLs recebidas do n8n nao sao seguidas: somente o host configurado e utilizado.

## Proxies e publicacao

Desative buffering e compressao que acumule a resposta nas rotas de streaming.
O Flask envia `X-Accel-Buffering: no` e `Cache-Control: no-store`; verifique se
seu proxy respeita esses cabecalhos. Ajuste tambem timeouts de proxy/ingress.
Um stream ocupa uma conexao/thread no Flask: use servidor WSGI com threads
adequadas em producao, em vez do servidor de desenvolvimento.

Nao publique as APIs sem controle de acesso. A aplicacao continua sendo uma
interface de teste; a sessao de navegador e a mailbox nao substituem autenticacao.

## Validacao

Da raiz do repositorio, com as dependencias Python dos testes instaladas:

```powershell
python -m pytest voice_runtime/tests NucleaInterface/tests -q
node --test NucleaInterface/static/pcm-player.test.mjs NucleaInterface/static/voice-ui.test.mjs
```

O teste opcional de navegador usa Playwright e Chromium instalados, microfone
sintetico e n8n/TTS simulados, sem pesos nem GPU:

```powershell
python -m NucleaInterface.tests.browser_streaming_smoke
```

Ele confirma que a reproducao comeca antes da segunda frase terminar, testa
desktop/celular e salva screenshots em `.pytest_cache/voice-browser`.
Isso nao mede desempenho nem valida as credenciais do n8n real.
