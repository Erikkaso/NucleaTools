# Wake word Nuclea

Detector local da palavra de ativacao **Nuclea** para ESP32-S3 com microfone
INMP441. O firmware processa audio a 16 kHz, calcula MFCC e executa um modelo
TensorFlow Lite INT8 no proprio microcontrolador.

## Modelo ativo

- Variante: `v2g_replay_hardneg`
- Entrada: `1 x 13 x 49 x 1`, MFCC INT8
- Janela: 1 segundo
- Avanco nominal entre janelas: 160 ms; a cadencia real depende do tempo de inferencia
- Threshold normal: `0.85`
- Threshold de alta confianca: `0.98`
- Confirmacao: 2 positivos nas ultimas 3 inferencias, ou 1 de alta confianca
- Cooldown: 2 segundos

Artefatos atuais:

```text
output/output_noise_robust_v2g_replay_hardneg/
output/output_noise_robust_v2g_replay_hardneg_int8/
esp32_wakeword/main/model/
```

SHA-256 do TFLite ativo:

```text
AF197A126D607AEF903068A665BCF766281A739E514F377A106A44AAC17EEC3E
```

## Estrutura

```text
dataset/             Audios positivos, negativos e hard negatives
train_models/        Treinamento e avaliacao
tools/               Preparacao do dataset e replay continuo
output/              Artefatos do modelo atual
esp32_wakeword/      Firmware ESP-IDF ativo
voz/                 Gravacoes-fonte preservadas
convert_int8.py      Conversao e avaliacao FULL INT8
```

## Ambiente Python

Execute a partir deste diretorio:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Treinar o modelo

```powershell
python train_models\train_noise_robust_v2.py v2g
```

Saida:

```text
output/output_noise_robust_v2g_replay_hardneg/
```

## Converter para INT8

```powershell
python convert_int8.py `
  --model output\output_noise_robust_v2g_replay_hardneg\nuclea_final.keras `
  --validation-csv output\output_noise_robust_v2g_replay_hardneg\validation_scores.csv `
  --results-json output\output_noise_robust_v2g_replay_hardneg\results_final.json `
  --output-dir output\output_noise_robust_v2g_replay_hardneg_int8
```

Antes de promover um novo modelo, confira `quantization_report.json`, os replays
continuos e os falsos positivos em conversas e ruido ambiente.

## Promover para o ESP32

```powershell
Copy-Item `
  output\output_noise_robust_v2g_replay_hardneg_int8\nuclea_int8.tflite `
  esp32_wakeword\main\model\nuclea_int8.tflite -Force

python esp32_wakeword\tools\tflite_to_cc.py `
  esp32_wakeword\main\model\nuclea_int8.tflite `
  --header esp32_wakeword\main\model\nuclea_model.h `
  --source esp32_wakeword\main\model\nuclea_model.cc

python esp32_wakeword\tools\generate_mfcc_reference.py
```

O firmware le `scale` e `zero_point` diretamente do TFLite. Ao trocar o modelo,
atualize tambem `QUANT_SCALE` e `QUANT_ZERO_POINT` em
`esp32_wakeword/tools/generate_mfcc_reference.py` antes de regenerar a paridade.

## Ligacao do INMP441

| INMP441 | ESP32-S3 |
| --- | --- |
| VDD | 3.3 V |
| GND | GND |
| L/R | GND, canal esquerdo |
| SCK/BCLK | GPIO 4 |
| WS | GPIO 5 |
| SD | GPIO 6 |

Esta e a pinagem padrao com o visor habilitado. **Mude fisicamente os tres
fios do microfone antes de gravar:** os antigos GPIOs 11/10/12 agora pertencem
a tela. Os pinos podem ser alterados no menu `Nuclea microphone pins`.
Com o visor desabilitado, um sdkconfig novo usa os antigos 11/10/12;
se reutilizar configuracoes, confira os tres valores no menuconfig.

O LED RGB integrado usa o GPIO 48. No boot ele testa vermelho, verde e azul.
Quando a wake word e aceita, o firmware grava o comando e envia o WAV para a
NucleaInterface. O LED fica azul durante a gravacao, amarelo durante o envio,
verde se o envio terminou com sucesso e vermelho se falhou.

### Testar apenas o microfone, sem tela

Na pasta `esp32_wakeword`, execute `idf.py menuconfig`:

1. Em `Nuclea robot display`, desmarque
   `Enable ST7789 robot animations (rewire microphone first)`
   (`NUCLEA_DISPLAY_ENABLED`).
2. Em `Nuclea microphone pins`, defina explicitamente SCK/BCLK=4, WS=5 e SD=6
   para usar a ligacao da tabela acima. Nao dependa dos defaults ao desativar
   o visor: eles podem ser 11/10/12.
3. Salve e execute:

```powershell
idf.py -p COM9 build flash monitor
```

Com esse firmware, a tela pode ficar totalmente desconectada. O monitor deve
mostrar `INMP441: BCLK=4 WS=5 SD=6` e nao deve mostrar `ROBOT_DISPLAY: Cache wake`.
Fale perto do microfone e confira se `peak` e `audio` variam.

Desligue a placa antes de alterar os fios. Alimente o INMP441 em 3.3 V, nao
5 V, e mantenha L/R ligado ao GND para o canal esquerdo.

## Compilar e gravar

Use um terminal ESP-IDF 5.5.x:

```powershell
cd esp32_wakeword
idf.py set-target esp32s3
idf.py menuconfig
idf.py build
idf.py -p COM9 flash monitor
```

No menu `Nuclea device audio`, ajuste apenas o identificador da sessao e os
limites de gravacao. Wi-Fi e URL sao configurados pelo navegador, nao pelo
`menuconfig`. Use Wi-Fi de 2.4 GHz e permita acesso a porta da interface no
firewall do computador.

### Configurar Wi-Fi pelo navegador

1. Grave o firmware e abra o monitor serial. Sem configuracao salva, o ESP
   cria a rede `Nuclea-Config`, com senha `Nuclea-Dell2026`.
   A senha tambem aparece na linha `Portal:` do monitor serial.
2. Conecte o celular ou computador a essa rede. Ela nao fornece Internet;
   mantenha a conexao mesmo se o sistema avisar sobre isso.
3. Abra **http://192.168.4.1**. A abertura automatica de portal nao esta
   implementada; acesse o IP manualmente.
4. Selecione uma rede ou digite seu nome, informe a senha e a URL base da
   NucleaInterface, por exemplo `http://192.168.1.100:5000`, sem rota.
   Use o IP real do computador na rede local, nao `localhost` nem o IP do ESP.
5. Pressione `Conectar e salvar`. A tentativa dura ate 30 segundos. Somente
   apos obter IP o ESP grava os dados na NVS; isso nao testa o n8n ou o Flask.
   Em caso de falha, a configuracao anterior e preservada.
6. Apos o sucesso, o portal fecha em 10 segundos. Volte a rede normal e
   abra a NucleaInterface no computador.

SSID, senha do Wi-Fi e URL persistem apos reiniciar. A senha do portal e fixa
no firmware; senhas aleatorias salvas por versoes anteriores sao ignoradas.
Um `flash` normal preserva NVS; `erase-flash` apaga esses dados. A senha do Wi-Fi nao e devolvida
pela API nem impressa nos logs. O acesso ao portal usa WPA2 e so e aceito pela
rede do ESP, nao pelo IP dele na rede domestica. NVS nao esta criptografada:
trate o dispositivo e os logs da senha do portal como dados sensiveis.
A senha do portal e compartilhada por todos os dispositivos com este firmware.
Depois de atualizar de uma versao com senha aleatoria, esqueca a rede
`Nuclea-Config` no celular/computador e reconecte com a senha atual.

Se aparecer `403 Forbidden`, use exatamente `http://192.168.4.1`, conectado
a `Nuclea-Config`, sem VPN ou proxy. O servidor aceita o endereco IPv4 do
portal mesmo quando o socket interno e IPv6; acessos pelo IP da rede
domestica continuam bloqueados. O `404` de `favicon.ico` nao impede a conexao.

Se ficar sem conexao por aproximadamente 30 segundos, o ESP reabre o portal
e continua tentando a rede salva. Para trocar a configuracao, desligue
temporariamente a rede anterior ou leve a placa fora de seu alcance; nao ha
botao de reset de configuracao nesta etapa. Os antigos valores de Wi-Fi do
`menuconfig` nao sao importados: configure o portal na primeira instalacao.

A gravacao requer PSRAM habilitada. Para a placa ESP32-S3 com PSRAM de 8 MB
Octal utilizada neste projeto, configure `Component config -> ESP PSRAM` com
PSRAM, modo Octal e 80 MHz. Os defaults incluem essas opcoes; confira o
`menuconfig` se estiver reutilizando um `sdkconfig` antigo.

Em `Partition Table`, use `Custom partition table CSV`, arquivo `partitions.csv`.
O firmware possui 3 MiB para a aplicacao e LittleFS em 0x310000, com tamanho
0xCF0000. A NVS conserva 0x9000/0x6000, como no firmware Wi-Fi anterior.
Com o visor habilitado, `idf.py flash` tambem grava os GIFs atuais no LittleFS: substitui o conteudo
daquela particao, mas nao apaga NVS. Nao execute `erase-flash` para esta mudanca.

Troque `COM9` pela porta da placa. O firmware aguarda a conexao Wi-Fi e entao
inicia o detector. Uma deteccao gera `Wakeword detectada` e inicia a gravacao
PCM16 mono a 16 kHz, com 400 ms de audio anteriores a deteccao. Por padrao, ela
termina apos 2 segundos abaixo de -32 dBFS ou ao atingir o limite de 15 segundos
(incluindo o audio anterior). Esses limites podem ser alterados no menu.

Execute a NucleaInterface no computador e mantenha sua pagina aberta. O n8n
precisa responder com audio. A resposta e recebida pelo Flask, mantida
temporariamente na RAM e entregue ao navegador pelo polling. Se o navegador
bloquear autoplay, pressione o controle de reproducao na mensagem. O ESP32
sinaliza o resultado do envio e volta a escutar; nao reproduz audio nesta etapa.

## Visor ST7789 e estados do robo

| ST7789 | ESP32-S3 |
| --- | --- |
| SCK/SCL | GPIO 10 |
| MOSI/SDA | GPIO 11 |
| CS | GPIO 12 |
| DC | GPIO 9 |
| RST/RES | GPIO 8 |
| VCC / BLK | 3.3 V |
| GND | GND |

O firmware ESP-IDF utiliza os arquivos existentes em
`nuclea_gif_player_fixed/data/`: `sleep.gif`, `wake.gif` e `nuclea-blink.gif`.
Nao e preciso gravar o sketch Arduino nem executar o uploader LittleFS
separadamente. A imagem LittleFS e gerada durante o build e incluida no flash.
Nao altere a pasta dos GIFs sem manter os tres nomes e a resolucao 280x240.

Por padrao, o visor mostra o robo dormindo desde a inicializacao, inclusive
durante a configuracao Wi-Fi. Isso e apenas um estado visual, nao deep sleep.
O detector inicia depois da conexao Wi-Fi, como no fluxo anterior.

Uma wakeword aceita inicia a gravacao e envia o evento de abertura dos olhos.
Os 30 frames de `wake.gif` sao decodificados no boot e guardados completos em
PSRAM (4.032.000 bytes), sem pular frames nem criar um GIF invertido na flash.
Depois, `nuclea-blink.gif` permanece em loop durante a gravacao e o HTTP.
O tempo de inatividade comeca ao concluir ou falhar o envio: por padrao,
30 segundos. A transicao normal fecha os olhos e retorna a `sleep.gif`.
Uma nova deteccao pode interromper o fechamento.

No menu `Nuclea robot display`, ajuste o tempo, clock SPI e offsets do painel,
ou desabilite o visor. O padrao e SPI 40 MHz, orientacao horizontal e offsets
X=20/Y=0. Se a imagem ficar deslocada, ajuste esses offsets conforme a tela;
a orientacao e as cores ainda precisam ser confirmadas no hardware real.

Captura I2S (prioridade 6), inferencia (4), envio HTTP (2) e visor (1) sao
separados. O visor roda no core 1; captura/inferencia/envio usam core 0.
Durante um envio, a captura continua, mas novas deteccoes sao suspensas
ate o HTTP terminar. O buffer da gravacao nao e reutilizado antes disso.
Se a fila de captura atrasar, o firmware registra o descarte e recompoe
a janela; uma gravacao com lacuna e descartada em vez de enviar audio incompleto.
Erros de leitura e overflow DMA/I2S tambem sinalizam lacunas. O historico de
confirmacao da wakeword e limpo entre pedidos e apos lacunas, preservando cooldown.

O cache reverso tem limite de 5 MiB. Se ele nao puder ser criado, o visor
troca diretamente entre as animacoes de repouso/acordado. Falha de montagem
nao formata a flash; falha de inicializacao do visor permite continuar sem ele.
O firmware nao recebe eventos de fim de reproducao do navegador: o temporizador
se baseia no fim do HTTP, nao no fim audivel do TTS.

### Validacao essencial da integracao

```powershell
cd esp32_wakeword
python -m unittest tools.test_visual_contract tools.test_audio_bridge_contract tools.test_wifi_portal_contract
idf.py build
python -m unittest tools.test_capture_stack_budget
idf.py -p COM9 flash monitor
```

O build tambem verifica tres cenarios da maquina de estados por `static_assert`.
O teste de pilha analisa o objeto compilado com `xtensa-esp32s3-elf-objdump`,
disponivel no terminal ESP-IDF. Se nao estiver no PATH, defina `XTENSA_OBJDUMP`
com o caminho do executavel. Sem compilador ou objeto, esse teste e ignorado;
ele mede a reserva local da funcao, nao substitui a medicao de pilha no hardware.
No hardware, confira `Cache wake: 30 frames`, a pinagem `BCLK=4 WS=5 SD=6`,
a abertura ao falar Nuclea, gravacao/envio e retorno ao repouso. Confira que
nao aparecem `Fila de audio atrasada` durante uso normal. Esta integracao
nao foi gravada nem validada fisicamente pelo agente.

## Testes do modelo

```powershell
python -m unittest discover -s train_models -p "test_*.py"
python -m unittest discover -s tools -p "test_*.py"
python -m unittest discover -s esp32_wakeword\tools -p "test_*.py"
```

## Diagnostico

- `audio` e `peak`: nivel recebido pelo INMP441.
- `score`: saida do modelo para wakeword; nao e uma medida de acuracia.
- `max_score`: maior score observado desde o ultimo log de telemetria.
- `q_in`: faixa INT8 dos MFCC enviados ao modelo.
- `q_out`: saidas INT8 para negativo e positivo.
- `positivos`: estado da confirmacao temporal.
- `stack_livre`: menor folga de pilha observada na tarefa principal.
- `captura_stack_livre`: menor folga de pilha observada na captura INMP441,
  em bytes. A captura usa pilha de 6144 bytes e buffers fora da pilha.

`peak=0` constante com `audio=-120.0 dBFS` indica PCM zerado; confira
alimentacao, GND comum, L/R em GND e os GPIOs exibidos na linha `INMP441:`.
Nao altere MFCC ou limiar de deteccao para compensar um microfone sem sinal.
Para testar sem tela, desative `NUCLEA_DISPLAY_ENABLED` em `menuconfig`,
confira os GPIOs do microfone e regrave. A linha `ROBOT_DISPLAY: Cache wake`
significa que o visor ainda esta habilitado no firmware gravado.

Se `audio` variar mas `q_in` ficar constante, revise o DSP. Se `q_in` variar e
`q_out` permanecer saturado, confirme se TFLite, tabelas MFCC e fontes C++ foram
promovidos juntos.

`A stack overflow in task inmp441_capture` e um crash real, nao um erro de
Wi-Fi ou de MFCC. A captura atual usa buffers fora da pilha e registra
`captura_stack_livre`; recompile e regrave para aplicar a correcao. A mensagem
`Fila de audio atrasada` indica descarte de blocos, nao necessariamente crash.
