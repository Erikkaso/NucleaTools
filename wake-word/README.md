# Wake word Nuclea

Detector local da palavra de ativacao **Nuclea** para ESP32-S3 com microfone
INMP441. O firmware processa audio a 16 kHz, calcula MFCC e executa um modelo
TensorFlow Lite INT8 no proprio microcontrolador.

## Modelo ativo

- Variante: `v2g_replay_hardneg`
- Entrada: `1 x 13 x 49 x 1`, MFCC INT8
- Janela: 1 segundo
- Avanco nominal entre janelas: 240 ms; a cadencia real depende do tempo de inferencia
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

## Preparar candidatos revisados e gerar augmentation

Depois de ouvir os candidatos e remover os invalidos de `review/`, execute
na pasta `wake-word`, com FFmpeg no PATH e as dependencias Python instaladas:

```powershell
python tools/augment_reviewed_candidates.py --confirmed-reviewed `
  --speaker-dir dataset/real/wakeword_gabriel dataset/real/wakeword_ryam
```

Use as pastas que ainda nao possuem `clean/`, `augmented/` ou `metadata.csv`.
O comando recusa sobrescrever saidas existentes. Ele preserva `review/`,
`manifest.csv`, negativos e gravacoes-fonte. Apenas os `candidate_*.wav`
restantes sao considerados positivos, mediante confirmacao de revisao.

Cada candidato gera uma copia original em `clean/` e quatro versoes em
`augmented/`: ganho/deslocamento seguro, velocidade de 1.04 a 1.06,
pitch de +/-0.5 semitom e ruido sintetico leve a 22-28 dB de SNR.
As saidas continuam PCM16 mono, 16 kHz e 1 segundo. As variacoes usam seed
fixa e margem de pico para evitar saturacao adicional.

Quando o percentil 10 dos niveis de frames de 20 ms supera -45 dBFS,
tambem e criada uma
versao `denoised`. Essa triagem e um indicador aproximado, nao uma medida
real de SNR. O filtro usa passa-altas de 70 Hz e FFmpeg `afftdn` com reducao
de 6 dB; sua latencia e compensada para preservar o final da palavra.
O original ruidoso tambem e mantido, sem filtragem destrutiva. O filtro nao
separa outras vozes nem recupera audio ja saturado.

`metadata.csv` registra os parametros, hash do candidato e grupo da gravacao
de origem. `augmentation_report.json` lista a triagem e as quantidades.
Todas as versoes da mesma gravacao compartilham `group_id`: nao as divida
entre treino e validacao. No treinador anterior v2, os novos locutores nao sao adicionados
automaticamente a `REAL_SPEAKERS`. Esse split exige pelo menos duas
gravacoes/grupos por locutor; nao divida artificialmente uma unica sessao
para contornar essa restricao. O pipeline v3 descrito abaixo descobre as
pastas automaticamente e usa outro protocolo de separacao por origem.
Este comando nao treina nem troca o TFLite.

Teste essencial desta etapa:

```powershell
python -m unittest discover -s tools -p test_augment_reviewed_candidates.py
```

## Treinar o modelo

### Treinamento multispeaker v3

**Experimental, nao promovido ao firmware.** Os candidatos treinados ainda
apresentam falsos acionamentos em ruido/conversas. Veja o
[resultado v7 com recortes revisados](output/RESULTADO_TREINO_V7.md), o
[resultado v6 com parametros sorteados](output/RESULTADO_TREINO_V6.md), o
[resultado v5 com mineracao de negativos](output/RESULTADO_TREINO_V5.md),
o [resultado v4 com negativos revisados](output/RESULTADO_TREINO_V4.md)
ou o [historico v3](output/RESULTADO_TREINO_V3.md) antes de substituir o modelo.

O pipeline novo descobre automaticamente os locutores em `dataset/real/`,
usando `clean/`, `augmented/` e `metadata.csv`. O peso dos positivos e
equilibrado por locutor; sinteticos nao dominam o treino. Positivos com
AC RMS abaixo de -60 dBFS ou menos de 120 ms acima de -50 dBFS sao excluidos
sem alterar os WAVs originais. Esse criterio nao substitui a escuta humana.

Ha duas etapas distintas:

1. Desenvolvimento com vozes e sessoes reservadas: Lara/Ryam na validacao,
   Gabriel/Thayza e INMP441 sessao 002 no teste. Isso mede transferencia
   entre vozes e grava sinais de sobreajuste.
2. Ajuste final com todas as vozes **exceto Thayza** ate convergencia da perda de treino,
   com early stopping e limite de 65 epocas, sem escolher pesos pelo teste.
   O recall sobre esses positivos passa a ser uma
   medida de treino, **nao** uma estimativa independente de generalizacao.

A politica atual reserva Thayza exclusivamente para teste, inclusive quando
a pasta se chama `wakeword_thayza(deprecated)`. Suas augmentations nao entram
no ajuste, nas misturas de ruido nem na calibracao representativa INT8.
Frases positivas como `Oi Nuclea`, `Bom dia Nuclea` e `Boa tarde Nuclea`
continuam positivas; nao sao convertidas em negativos por conter outras palavras.

```powershell
python train_models/train_multispeaker_v3.py `
  --include-reviewed-negatives `
  --output output/output_multispeaker_v3_temporal_dev

python train_models/train_multispeaker_v3.py --final-fit `
  --include-reviewed-negatives `
  --development-report output/output_multispeaker_v3_temporal_dev/results.json `
  --output output/output_multispeaker_v4_reviewed

python tools/evaluate_multispeaker_v3.py `
  --output output/output_multispeaker_v4_reviewed
```

A rede temporal preserva o contrato MFCC `1 x 13 x 49 x 1` e saida
`[negativo, Nuclea]`. Usa convolucoes separaveis com contexto temporal maior.
As augmentations adicionais preservam a palavra inteira, variam ganho e
misturam ruido entre 8 e 25 dB de SNR, somente no treino. Um quarto das
misturas usa trechos da conversa legada `background_test/conversa.mp3`,
que tambem fornece negativos de dialogo. Sem `--mined-negative-dir`,
`background_test2` nao entra no treinamento. Na rodada v5 descrita abaixo,
somente o bloco de treino desse corpus fornece negativos e misturas.
As gravacoes legadas `background_test/ambiente.wav`,
`musica.wav` e `negative.wav` tambem entram como negativos, em janelas
de um segundo a cada dois segundos; ambiente/musica podem compor as
misturas positivas. O peso dos positivos e equilibrado por voz e gravacao.
Use `--include-reviewed-negatives` somente apos ouvir e aprovar os negativos.
O usuario confirmou essa revisao em 2026-10-15; a rodada
`output_multispeaker_v4_reviewed` inclui os 68 WAVs negativos presentes nas
pastas aprovadas. Tambem suporta `positive/original`, `positive/clean` e
`positive/augmented` com `manifest.csv`, como no dataset da Raisa.
Arquivos removidos durante revisao nao sao recriados a partir do manifesto.
Negativos de mesma origem ficam no mesmo split que os positivos, entram
como contraprovas e recebem variacoes de ganho somente no treino.

Silencio digital, DC, ruido baixo e hum entram como negativos explicitos.
Common Voice e separado por locutor de origem; copias legadas de INMP441
nao entram junto dos trechos reservados da mesma sessao. Os negativos
longos INMP441 usam blocos cronologicos com margem de dois segundos:
esses blocos continuam sendo da **mesma gravacao**, nao sessoes independentes.
Os WAVs identicos sao deduplicados antes da augmentation adicional.

Consulte `data_audit.json`, `data_manifest.json`, `results.json` e
`stream_evaluation.json`. Este ultimo usa trechos do inicio, meio e fim
dos arquivos de diagnostico, nas cadencias de 160 e 320 ms. Nao e teste
da duracao completa nem garantia de falsos positivos por hora no hardware.

O limiar e calibrado no INT8 usando apenas os negativos da validacao,
com meta empirica de ate 1% de falsos positivos por janela e nenhum nos
trechos de silencio sintetico/ambiente da calibracao. Isso nao garante
essas taxas em gravacoes novas; os eventos do replay sao medidos a parte.
O modelo anterior e preservado; **treinar nao troca o firmware**. Antes
de promover, atualize modelo, arrays C++, escala/zero point da referencia
MFCC e limiares juntos. Ainda e necessario verificar a arena TFLM, a
latencia e a deteccao com o INMP441 no ESP32 real.

Para retomar depois da preparacao, use `--reuse-features` no mesmo output.
Se adicionar ou revisar audios, use um novo output sem `--reuse-features`:
o cache antigo nao incorpora arquivos novos.
O script recusa sobrescrever um modelo treinado. Teste essencial do split,
silencio, deslocamento e limiar:

```powershell
python -m unittest discover -s train_models -p test_multispeaker_data.py
```

### Mineracao de negativos v5

**Candidato nao aprovado para substituir o modelo ativo.** Veja as metricas e
limitacoes no [relatorio v5](output/RESULTADO_TREINO_V5.md).

O minerador separa cada gravacao de `background_test2` em blocos cronologicos
60/20/20, com margem de dois segundos no inicio dos blocos de validacao e teste.
Somente o primeiro bloco e pontuado pelo modelo-base para selecionar janelas
dificeis. Validacao e teste usam cobertura uniforme, sem selecao por score.
Os blocos pertencem as mesmas gravacoes, nao sao novas sessoes independentes.

Sequencia usada, executada em `wake-word` (use novas pastas para outra rodada):

```powershell
python train_models/train_multispeaker_v3.py --final-fit `
  --include-reviewed-negatives `
  --development-report output/output_multispeaker_v3_temporal_dev/results.json `
  --output output/output_multispeaker_v5_seed_holdout

python tools/mine_hard_negatives.py `
  --teacher output/output_multispeaker_v5_seed_holdout/nuclea_int8.tflite `
  --output dataset/mined_hard_negative_v5 --confirmed-negative-sources

python train_models/train_multispeaker_v3.py --final-fit `
  --include-reviewed-negatives --mined-negative-dir dataset/mined_hard_negative_v5 `
  --development-report output/output_multispeaker_v5_seed_holdout/results.json `
  --output output/output_multispeaker_v5_hardneg

python tools/evaluate_multispeaker_v3.py `
  --output output/output_multispeaker_v5_hardneg `
  --baseline output/output_multispeaker_v4_reviewed/nuclea_int8.tflite

python -m unittest discover -s train_models -p test_hard_negative_mining.py
```

`--confirmed-negative-sources` exige que as fontes ja estejam rotuladas como
sem wakeword. Nao executa transcricao nem nova revisao humana dos recortes.
O `manifest.json` registra hashes, intervalos, splits e modelo-base da mineracao.
O treinador verifica esses dados e rejeita caches com politica/corpus divergentes.
O modelo intermediario `output_multispeaker_v5_seed` foi invalidado por uma
falha anterior na identificacao da pasta renomeada da Thayza; nao deve ser usado.
A rodada valida parte de `output_multispeaker_v5_seed_holdout`.

### Rodada v6: parametros sorteados, sem Thayza

`--randomize` sorteia learning rate entre 0.0003 e 0.001 (escala logaritmica),
dropout entre 0.2/0.3/0.4 e batch entre 32/64. Sem `--seed`, uma seed e gerada
e registrada em `training_config.json`, `data_audit.json` e `results.json`.
O sorteio nao muda MFCC, pinagem, firmware ou splits por gravacao.

Esta rodada nao usa `--final-fit`: Lara/Ryam ficam na validacao, Gabriel e
Eric sessao 002 no teste. `--exclude-speaker thayza` retira Thayza de todos
os splits, incluindo negativos e augmentations. A pasta original e preservada.
Saudacoes com Nuclea continuam positivas. Para reproduzir os valores usados:

```powershell
python train_models/train_multispeaker_v3.py `
  --randomize --seed 1204528219 --exclude-speaker thayza `
  --include-reviewed-negatives --mined-negative-dir dataset/mined_hard_negative_v5 `
  --epochs 65 --output output/output_multispeaker_v6_reproduction

python tools/evaluate_multispeaker_v3.py `
  --output output/output_multispeaker_v6_random

python -m unittest discover -s train_models -p test_training_config.py
```

Seed fixa reproduz o sorteio; identicidade bit a bit do treinamento nao e
garantida entre versoes/plataformas e kernels TensorFlow. O cache de features
valida a seed e os locutores excluidos antes de permitir reutilizacao.

Na limpeza de 2026-10-19 foram removidos experimentos v3 descartados, a rodada
v5 invalidada e caches `features.npz` antigos. `output/cleanup_v6.json` registra
os caminhos e tamanhos. Relatorios historicos e modelos de comparacao foram
mantidos. Recalibrar ou retreinar uma rodada cujo cache foi apagado exige
preparar os dados novamente em uma nova pasta; nao use `--reuse-features` nela.

### Rodada v7: recortes revisados e Eric aleatorio

**Depois da revisao manual, use esta receita.** As receitas antigas acima sao
historicas e podem ler augmentations obsoletas que nao refletem arquivos apagados.

`--reviewed-clean-only` usa os WAVs que restaram em `clean/` (ou `positive/clean/`),
ignora `original/` e todas as pastas `augmented/` antigas. Se o manifesto declara
um `parent_file` que foi apagado, a copia clean tambem e excluida. Nada e
restaurado dos candidatos `review/` ou de manifestos antigos.

Tres variantes novas por positivo clean de treino sao geradas em
`output/<rodada>/augmented/`, com ganho, deslocamento seguro e mistura de ruido.
Nao ha recorte adicional, pitch ou time stretch nesta etapa. O deslocamento
e recusado se descartaria energia significativa; os originais nao sao alterados.
Arquivos que nao tenham um segundo sao rejeitados, nao truncados. As pastas
antigas de augmentation permanecem no dataset, mas nao sao usadas nesta receita.

`--eric-random-split` randomiza componentes de janelas sobrepostas do Eric,
estratificados por gravacao de origem, em aproximadamente 80/10/10 por grupo.
Sobreposicoes ficam juntas antes de gerar variantes. Os percentuais de WAVs
podem variar porque um grupo pode conter varios recortes. O split usa tempos
dos manifestos INMP441 e metadados de padding/velocidade dos recortes legados.
Lara/Ryam continuam na validacao, Gabriel no teste, Thayza fora de todos.
Eric compartilha voz e sessoes entre splits: **nao e teste de sessao desconhecida**.

```powershell
python train_models/train_multispeaker_v3.py `
  --randomize --seed 1204528219 --exclude-speaker thayza `
  --reviewed-clean-only --eric-random-split --include-reviewed-negatives `
  --mined-negative-dir dataset/mined_hard_negative_v5 --epochs 65 `
  --output output/output_multispeaker_v7_reproduction

python tools/evaluate_multispeaker_v3.py `
  --output output/output_multispeaker_v7_reviewed

python -m unittest discover -s train_models -p test_reviewed_split.py
```

Os hiperparametros sao os mesmos da v6, sem novo sorteio. Se revisar ou apagar
mais audios, use uma pasta nova: nao reutilize features preparadas antes da revisao.
Esta rodada nao substitui o modelo do ESP32 automaticamente.

### Treinamento anterior v2g

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

### Teste isolado da tela (pinagem padrao)

Com `CONFIG_NUCLEA_DISPLAY_ONLY_TEST=y`, conecte somente o visor:

| Tela (ordem dos terminais) | ESP32-S3 |
|---|---|
| GND | GND |
| VCC | 3V3 |
| SCL | GPIO 4 |
| SDA | GPIO 5 |
| RES | GPIO 6 |
| DC | GPIO 7 |
| CS | GPIO 15 |
| BLK | 3V3 |

Desconecte microfone e amplificador desses GPIOs antes de alimentar.
Neste modo, nao iniciam Wi-Fi, microfone, amplificador ou wakeword.
A tela alterna automaticamente entre dormir, acordar e olhos abertos;
o retorno ao repouso usa `NUCLEA_DISPLAY_IDLE_MS` (30 segundos por padrao).
Esta pinagem tambem e usada no modo normal, validada no teste do visor.
Para voltar ao assistente, desmarque `Test display only on GPIOs 4/5/6/7/15`
em `idf.py menuconfig` > `Nuclea robot display`. O teste esta desabilitado no sdkconfig atual.

Compile e grave a partir de `wake-word/esp32_wakeword`, no terminal ESP-IDF:

```powershell
idf.py -B build-speaker -p COM9 reconfigure build flash monitor
```

### Esquema rapido: ESP32-S3, microfone e LED

O esquema abaixo corresponde ao `sdkconfig` atual: microfone nos GPIOs
**41/42/40** (BCLK/WS/SD), visor habilitado e LED RGB integrado no **GPIO 48**.
Os numeros sao os GPIOs impressos na placa, nao a posicao fisica dos pinos.
Desligue o USB e qualquer outra alimentacao antes de montar ou alterar fios.

```text
ESP32-S3                         INMP441
========                         =======
3V3 ---------------------------- VDD
GND ---------+------------------ GND
             +------------------ L/R  (canal esquerdo)
GPIO 41 ------------------------ SCK / BCLK
GPIO 42 ------------------------ WS
GPIO 40 <----------------------- SD   (audio do microfone)

GPIO 48 ---- LED RGB integrado na propria placa
             Nao precisa de fio, resistor ou alimentacao externa.
```

**LED integrado nao e o visor.** O firmware controla o LED RGB enderecavel
WS2812 da placa pelo GPIO 48; nao se trata de um LED comum externo de dois
terminais. O LED de alimentacao da placa tambem nao e esse indicador RGB.

Se faltar um pino GND livre, use uma protoboard ou um distribuidor para criar
um GND comum. Ligue um GND do ESP ao barramento e nele conecte GND e L/R do
microfone e GND do visor. Nao use um GPIO como substituto de GND. O mesmo
principio permite distribuir o 3V3 para os modulos, respeitando a capacidade
de alimentacao da placa.

### Esquema opcional do visor ST7789

Para usar a tela do robo junto com o microfone acima:

```text
ESP32-S3                         ST7789
========                         ======
3V3 ---------+------------------ VCC
             +------------------ BLK / BL (luz de fundo)
GND ---------------------------- GND
GPIO 4 ------------------------- SCK / SCL
GPIO 5 ------------------------- MOSI / SDA
GPIO 15 ------------------------ CS
GPIO 7 ------------------------- DC
GPIO 6 ------------------------- RST / RES
```

SCL/SDA neste visor sao sinais **SPI**, nao I2C. A ligacao acima nao usa MISO.
VCC e BLK compartilham o 3V3, mas ambos os terminais precisam da conexao
indicada. Nao remova tres sinais do visor para compensar a falta de jumpers.
Para testar apenas o microfone, deixe a tela desconectada e siga a secao
[Testar apenas o microfone, sem tela](#testar-apenas-o-microfone-sem-tela).

### Pinagem do microfone

| INMP441 | ESP32-S3 |
| --- | --- |
| VDD | 3.3 V |
| GND | GND |
| L/R | GND, canal esquerdo |
| SCK/BCLK | GPIO 41 |
| WS | GPIO 42 |
| SD | GPIO 40 |

Esta e a pinagem padrao com ou sem visor. Os GPIOs 4/5/6 agora sao do visor.
Os pinos podem ser alterados no menu `Nuclea microphone pins`;
se reutilizar configuracoes antigas, confira os tres valores no menuconfig.

O LED RGB integrado usa o GPIO 48. No boot ele testa vermelho, verde e azul.
Quando a wake word e aceita, o firmware grava o comando e envia o WAV para a
NucleaInterface. O LED fica azul durante a gravacao, amarelo durante o envio
ou espera, verde durante a reproducao no alto-falante e ao concluir com sucesso,
e vermelho se falhou.

### Testar apenas o microfone, sem tela

Na pasta `esp32_wakeword`, execute `idf.py menuconfig`:

1. Em `Nuclea robot display`, desmarque
   `Enable ST7789 robot animations (rewire microphone first)`
   (`NUCLEA_DISPLAY_ENABLED`).
2. Em `Nuclea microphone pins`, confira SCK/BCLK=41, WS=42 e SD=40
   para usar a ligacao da tabela acima.
3. Salve e execute:

```powershell
idf.py -p COM9 build flash monitor
```

Com esse firmware, a tela pode ficar totalmente desconectada. O monitor deve
mostrar `INMP441: BCLK=41 WS=42 SD=40` e nao deve mostrar `ROBOT_DISPLAY: Cache wake`.
Fale perto do microfone e confira se `peak` e `audio` variam.

Desligue a placa antes de alterar os fios. Alimente o INMP441 em 3.3 V, nao
5 V, e mantenha L/R ligado ao GND para o canal esquerdo.

## Alto-falante com MAX98357A

O firmware pode receber a resposta diretamente no ESP32 e reproduzir no
MAX98357A. O microfone continua no I2S0; a saida usa o I2S1, sem compartilhar
os clocks ou alterar os GPIOs do microfone e do visor.

| MAX98357A | Conexao |
| --- | --- |
| LRC / WS | GPIO 21 |
| BCLK | GPIO 14 |
| DIN | GPIO 13 |
| GAIN | GND para 12 dB; aberto para o padrao de 9 dB |
| SD | 3V3, habilitado e canal esquerdo |
| GND | GND comum ao ESP32 e a fonte |
| VIN | Fonte de 5 V adequada ao consumo do conjunto |
| Saida + / - | Somente os dois terminais do alto-falante |

Nao ligue nenhum terminal de saida do amplificador ao GND. O INMP441 continua
em 3.3 V. Monte com a alimentacao desligada. O volume digital padrao atual e
**100%**. O alto-falante usado e de 4 ohms e 3 W; se houver distorcao, reduza
o volume. O teste musical confirmou brownout com a alimentacao anterior do PC;
use uma alimentacao 5 V adequada ao conjunto.

GAIN conectado diretamente ao GND aumenta o ganho de 9 para 12 dB sem mudar
o firmware. Para 15 dB, use resistor de 100 kohms entre GAIN e GND. Conectar
GAIN ao VIN reduz o ganho, nao aumenta. Mais ganho nao aumenta a potencia
maxima do amplificador e pode causar distorcao. Referencia:
[MAX98357A: controle de ganho](https://learn.adafruit.com/adafruit-max98357-i2s-class-d-mono-amp/pinouts).

No menu `Nuclea device audio`, `NUCLEA_SPEAKER_ENABLED` vem habilitado.
Os pinos sao configuraveis em `NUCLEA_SPEAKER_BCLK_GPIO`,
`NUCLEA_SPEAKER_WS_GPIO` e `NUCLEA_SPEAKER_DIN_GPIO`; o volume em
`NUCLEA_SPEAKER_VOLUME_PERCENT`.

Com o alto-falante habilitado, o ESP envia `responseMode=speaker` junto ao WAV
para `/api/device-audio`. A NucleaInterface atualizada devolve PCM16 mono a
24 kHz em NDJSON na mesma conexao. O firmware valida os pacotes, acumula um
buffer limitado em PSRAM e reproduz sem esperar o audio completo. Nao ha
decodificador MP3: mantenha o workflow `nuclea-streaming.json` e o runtime de
streaming. Nao e necessario deixar o navegador aberto.

Durante envio, espera e reproducao TTS, novas deteccoes continuam ativas.
Uma nova wakeword interrompe o audio, sinaliza cancelamento HTTP e descarta
o retorno anterior. O worker encerra a conexao e libera o buffer antes de
abrir um novo comando com `onsfx`; nao e preciso esperar o n8n responder.
Os efeitos locais curtos de inicio/fim continuam bloqueando novas deteccoes.
Ao terminar naturalmente ou falhar sem interrupcao, permanece a margem de
dois segundos para drenar captura e eco. Audio invalido nao e repetido automaticamente.

O cancelamento e local: n8n/GPU podem concluir uma execucao ja iniciada.
Ele nao desfaz consultas, alteracoes de dados ou memoria que o workflow ja
tenha produzido. Nao foi adicionada uma API para interromper execucoes no n8n.
Durante DNS/conexao TLS ainda nao existe socket conectado para interromper;
o timeout de transporte dessa fase e 5 s (a resolucao DNS depende da pilha).
Nao ha cancelamento acustico de eco: se o proprio TTS disser a wakeword, ele
pode acionar a interrupcao; distancia entre caixa e microfone e volume afetam isso.

Para manter a resposta no navegador, desabilite `NUCLEA_SPEAKER_ENABLED` em
`menuconfig` e regrave a placa; o modo antigo permanece disponivel.

Reinicie tambem a NucleaInterface apos atualizar seu `app.py`. Nao e preciso
alterar o n8n ou o TTS se o fluxo de streaming ja estava funcionando.

Para esta atualizacao, use uma pasta de compilacao nova, evitando o cache
antigo com caminhos anteriores a mudanca de repositorio:

```powershell
cd wake-word/esp32_wakeword
idf.py -B build-speaker menuconfig
idf.py -B build-speaker -p COM9 reconfigure build flash monitor
```

Execute em um terminal ESP-IDF 5.5.x. Substitua `COM9` pela porta da placa.
O `reconfigure` atualiza tambem o caminho do Python caso seu terminal ESP-IDF
use outro ambiente virtual que o utilizado na compilacao anterior.
A pinagem do microfone deve aparecer no log como `BCLK=41 WS=42 SD=40`;
o amplificador deve indicar `I2S1 TX BCLK=14 WS=21 DIN=13`, seguido do volume configurado.
Os testes de software e a compilacao nao substituem a validacao do som na placa.

## Teste isolado da caixa de som: musica em loop

O teste fica desabilitado no `sdkconfig` atual. Para usa-lo, habilite
`NUCLEA_SPEAKER_ONLY_TEST` em `menuconfig`; o volume de teste padrao e **100%**.
Com o teste habilitado, ao ligar, o ESP toca a musica inteira em loop,
sem iniciar Wi-Fi, visor, microfone ou wakeword. O volume do modo normal
continua independente (`NUCLEA_SPEAKER_VOLUME_PERCENT`).

Conecte apenas o MAX98357A: LRC em GPIO21, BCLK em GPIO14, DIN em GPIO13,
SD em 3V3, GND em GND e VIN em 5V; GAIN pode ficar aberto. Ligue o alto-falante
somente entre SPK+ e SPK-, nunca entre uma saida e GND. Desligue a alimentacao
antes de alterar fios. O USB do ESP pode limitar a potencia e causar distorcao
ou reinicializacao no volume maximo. Uma fonte regulada de 5V adequada pode
alimentar apenas o VIN do MAX, mantendo GND comum e sem unir dois positivos de 5V.

Para preparar e gravar, em `wake-word/esp32_wakeword`, com FFmpeg no PATH
e terminal ESP-IDF habilitado:

```powershell
python tools/prepare_speaker_music.py
idf.py -B build-speaker -p COM9 build flash monitor
```

O conversor usa o unico MP3 na raiz de NucleaTools; para outro caminho,
use `--input "caminho/musica.mp3"`. Preserva o original e converte o canal
esquerdo completo em PCM16 mono 24 kHz. O PCM gerado e ignorado pelo Git.
O ESP le pequenos blocos da flash, sem carregar a musica inteira na RAM.

Este teste substitui os GIFs na particao de arquivos pela musica, sem apagar
as credenciais Wi-Fi na NVS. Para voltar ao assistente, desmarque
`Test speaker only` em `idf.py -B build-speaker menuconfig` e execute novamente
o comando completo `build flash monitor`: isso tambem restaura os GIFs.
Nao use `erase-flash`. Para reduzir o volume do teste, altere
`Speaker music test volume (percent)` no mesmo menu.

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
e continua tentando a rede salva. Tambem e possivel reabrir o portal pelo
botao BOOT, sem desligar o roteador nem apagar a configuracao.
Os antigos valores de Wi-Fi do
`menuconfig` nao sao importados: configure o portal na primeira instalacao.

### Reabrir o portal pelo botao BOOT

1. Com o firmware funcionando, segure **BOOT (GPIO 0)** por pelo menos
   **3 segundos** e solte. O monitor registra
   `Portal reaberto por BOOT; configuracao salva preservada.`
2. Conecte a `Nuclea-Config` com senha `Nuclea-Dell2026` e abra
   `http://192.168.4.1`, mesmo que o ESP ja esteja conectado ao Wi-Fi.
3. Confira a rede e a URL. Digite novamente a senha do Wi-Fi: ela nao e
   preenchida pelo portal nem devolvida pela API.
4. Use `Conectar e salvar`. Apos conectar e salvar com sucesso, o portal
   fecha em 10 segundos. Se falhar, os dados anteriores sao preservados.

O portal aberto pelo BOOT permanece disponivel ate salvar com sucesso ou
reiniciar a placa, mesmo se reconectar automaticamente a rede antiga.
Uma pressao longa gera apenas um acionamento; solte antes de acionar novamente.
O botao tambem e consultado durante as tentativas de conexao Wi-Fi. Nao apaga
NVS, GIFs ou modelo. **RST continua apenas reiniciando o ESP. Nao segure BOOT
ao apertar RST ou ligar a placa**, pois isso pode entrar no modo de gravacao.

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
inicia o detector. Uma deteccao gera `Wakeword detectada`, toca o `onsfx` local
e abre a gravacao PCM16 mono a 16 kHz depois do efeito e de uma margem de 150 ms.
Aguarde o som inicial acabar antes de falar o comando. Por padrao, ela
grava no minimo 5 segundos. Audio com RMS >= -32 dBFS renova uma margem de
1,5 segundo apos a ultima atividade, sem ultrapassar 12 segundos. Por exemplo,
atividade ate 4,5 s leva o termino para 6 s; sem atividade perto do fim, o WAV
termina em 5 s. Ruido alto tambem pode prorrogar: e deteccao de volume, nao VAD.
Com os efeitos habilitados, os tempos comecam depois do som inicial; sem efeitos,
o firmware preserva os 400 ms de pre-roll anteriores a deteccao. Sao contados pelas amostras,
nao pelo atraso de processamento. O ultimo bloco e limitado para nao ultrapassar
a duracao calculada. Em `Nuclea device audio`, os parametros sao
`NUCLEA_MIN_RECORDING_MS=5000`, `NUCLEA_SILENCE_MS=1500` e
`NUCLEA_MAX_RECORDING_MS=12000`; o maximo permitido e 12 segundos.

Configure no portal a URL base do Voice Gateway ou execute a NucleaInterface
no computador para manter o fluxo anterior. Com `NUCLEA_SPEAKER_ENABLED`, a resposta
e reproduzida no MAX98357A conectado ao ESP32, sem pagina aberta. Sem essa opcao,
a resposta segue para a caixa de audio do navegador por polling; libere audio
com uma interacao na pagina. O workflow n8n deve ser o de streaming para usar
o alto-falante. Consulte a secao `Alto-falante com MAX98357A` para configuracao.

### Chave de acesso do n8n

O portal Wi-Fi possui o campo mascarado **Chave de acesso do n8n**. Use a
mesma chave da credencial Header Auth do Webhook, com nome `X-Nuclea-Key`.
A chave deve ter entre 32 e 128 caracteres ASCII sem espacos; prefira uma
chave aleatoria gerada com `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

Segure BOOT por 3 segundos, conecte-se a `Nuclea-Config`, abra
`http://192.168.4.1` e confira rede, senha e URL HTTPS antes de salvar.
Rota e chave ficam bloqueadas por padrao, cada uma com seu botao **Editar**.
Sem escolher editar, salvar o Wi-Fi preserva ambas na NVS; elas nao sao
reenviadas pelo formulario. Para trocar a chave, clique em **Editar** e
preencha uma nova. Vazio preserva a salva; o portal
mostra apenas se existe chave configurada, sem ler o segredo de volta.
Ela fica em uma entrada separada na NVS, sem mudar o blob legado de Wi-Fi.
Nao e necessario `erase-flash`. A NVS atual nao e criptografada.

O ESP envia `X-Nuclea-Key` ao gateway, que o repassa somente ao n8n.
Com chave configurada, o ESP exige HTTPS e nao segue redirecionamentos.
Atualize tambem o Voice Gateway e habilite Header Auth no Webhook do n8n;
o gateway nao valida o valor sozinho e nao guarda uma chave mestra.
Nenhuma mudanca no TTS e necessaria. Veja o guia completo em
[Voice Gateway](../voice_gateway/README.md#chave-de-acesso-no-n8n-e-no-esp).

### Sons de inicio e fim da gravacao

`NUCLEA_RECORDING_SFX_ENABLED` vem habilitado quando o alto-falante esta ativo.
Em `Nuclea device audio`, desmarque `Play local recording start/stop sound effects`
para voltar ao comportamento anterior sem sons.

- `onsfx`: toca uma vez quando a wakeword e aceita, antes de abrir o comando.
- `offsfx`: toca depois de fechar a gravacao, antes do envio HTTP. Tambem toca
  ao descartar uma gravacao por lacuna de captura; sem Wi-Fi, o som continua local.
- Durante efeitos, o loop continua drenando o INMP441, sem gravar o proprio
  som no WAV e sem executar novas inferencias. Efeitos e resposta TTS usam o
  mesmo worker e a mesma saida I2S, sem reproducao simultanea.
- A duracao minima de 5 s e a maxima de 12 s continuam valendo para o comando,
  sem contar os sons. Os efeitos acrescentam seu tempo ao ciclo: aproximadamente
  0,85 s no inicio, uma margem de 150 ms e 0,63 s no fim, mais o esvaziamento I2S.
- O volume segue `NUCLEA_SPEAKER_VOLUME_PERCENT`, sem alterar o valor configurado.
  O padrao atual e 100%, o maximo digital sem amplificacao adicional.

Os arquivos `main/assets/onsfx.pcm` e `offsfx.pcm` sao embutidos no firmware
como PCM16 little-endian, mono, 24 kHz, sem cabecalho WAV. Nao precisam do
gateway, TTS, rede, MP3 decoder ou FFmpeg no ESP. Os originais `onsfx.mp4` e
`offsfx.mp4` da raiz foram preservados; sao fontes de audio reconhecidas pelo FFmpeg.
Somente o silencio inicial/final do `onsfx` foi removido.
O `offsfx` recebeu +6,63 dB para aproximar seu nivel RMS do `onsfx`, sem
recortar sua duracao nem saturar as amostras PCM. Isso nao garante o mesmo
volume percebido, pois os efeitos possuem timbres diferentes.

Para regenerar a partir da raiz de `NucleaTools` (FFmpeg instalado):

```powershell
ffmpeg -y -i onsfx.mp4 -map 0:a:0 -af "atrim=start=0.53:end=1.38,asetpts=PTS-STARTPTS" -ac 1 -ar 24000 -c:a pcm_s16le -f s16le wake-word/esp32_wakeword/main/assets/onsfx.pcm
ffmpeg -y -i offsfx.mp4 -map 0:a:0 -af "volume=6.63dB" -ac 1 -ar 24000 -c:a pcm_s16le -f s16le wake-word/esp32_wakeword/main/assets/offsfx.pcm
```

O recorte acima corresponde ao `onsfx` fornecido; ajuste se trocar o arquivo.
Inclua os dois `.pcm` no repositorio. O build normal nao depende de FFmpeg nem
dos originais. Para gravar os efeitos, basta recompilar e fazer flash normalmente.

## Visor ST7789 e estados do robo

| ST7789 | ESP32-S3 |
| --- | --- |
| SCK/SCL | GPIO 4 |
| MOSI/SDA | GPIO 5 |
| CS | GPIO 15 |
| DC | GPIO 7 |
| RST/RES | GPIO 6 |
| VCC / BLK | 3.3 V |
| GND | GND |

O firmware ESP-IDF utiliza os arquivos existentes em
`nuclea_gif_player_fixed/data/`: `sleep.gif`, `wake.gif` e `nuclea-blink.gif`.
Nao e preciso gravar o sketch Arduino nem executar o uploader LittleFS
separadamente. A imagem LittleFS e gerada durante o build e incluida no flash.
Nao altere a pasta dos GIFs sem manter os tres nomes e a resolucao 280x240.

Por padrao, o visor mostra o robo dormindo desde a inicializacao, inclusive
durante a configuracao Wi-Fi. Isso e apenas um estado visual, nao deep sleep.
Somente `sleep.gif` tem inversao horizontal por software no envio ao visor; as animacoes de acordar e olhos abertos mantem a orientacao original.
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
separados. Inferencia e visor rodam no core 1; captura, alto-falante (3) e
envio usam core 0. Assim, inferencias longas nao bloqueiam o abastecimento I2S.
Durante um envio, captura e deteccao continuam. A nova wakeword cancela o
pedido anterior; o buffer da gravacao so e reutilizado apos o worker confirmar
o encerramento. Apenas o worker HTTP fecha/libera seu cliente e consome a
confirmacao de parada do alto-falante; a outra tarefa somente sinaliza e
interrompe o socket com `shutdown`, sem liberar objetos em uso.
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
O controle de gravacao verifica cinco cenarios adicionais por `static_assert`:
silencio com WAV de 5 s, renovacao da margem de 1,5 s, volume continuo limitado
a 12 s, silencio inicial sem encerramento antecipado e buffer cheio sem escrita.
Tambem verifica o BOOT: acionamento apos 3 segundos, acionamento unico por
pressao e reinicio da contagem apos soltar o botao.
O teste de pilha analisa o objeto compilado com `xtensa-esp32s3-elf-objdump`,
disponivel no terminal ESP-IDF. Se nao estiver no PATH, defina `XTENSA_OBJDUMP`
com o caminho do executavel. Sem compilador ou objeto, esse teste e ignorado;
ele mede a reserva local da funcao, nao substitui a medicao de pilha no hardware.
No hardware, confira `Cache wake: 30 frames`, a pinagem `BCLK=41 WS=42 SD=40`,
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
