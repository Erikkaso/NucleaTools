# Wake word Nuclea

Detector local da palavra de ativacao **Nuclea** para ESP32-S3 com microfone
INMP441. O firmware processa audio a 16 kHz, calcula MFCC e executa um modelo
TensorFlow Lite INT8 no proprio microcontrolador.

## Modelo ativo

- Variante: `multispeaker_v7_reviewed` (confirmada pelos bytes embutidos no firmware)
- Entrada: `1 x 13 x 49 x 1`, MFCC INT8
- Janela: 1 segundo
- Avanco nominal entre janelas: 240 ms; a cadencia real depende do tempo de inferencia
- Threshold no firmware: `0.93359375` (mantido no ajuste de 2026-10-25)
- Confirmacao normal: 2 scores >=0.93359375 nas ultimas 3 inferencias, incluindo a atual
- Alternativa para fala curta: pico >=0.98 mais outra janela >=0.5, com a atual >=0.5
- Um score alto isolado, mesmo `0.996`, nao ativa sozinho
- Cooldown: 2 segundos

Artefatos atuais:

```text
output/output_multispeaker_v7_reviewed/
esp32_wakeword/main/model/
```

SHA-256 do TFLite ativo:

```text
6B4321B5B38A4FD793080B0A3889A0AEFF7BDA30DBA1ACD31063689266728AAF
```

## Estrutura

```text
dataset/             Audios positivos, negativos e hard negatives
train_models/        Treinamento e avaliacao
tools/               Preparacao do dataset e replay continuo
output/              Artefatos do modelo atual
esp32_wakeword/      Firmware ESP-IDF ativo
dataset/voz/         Gravacoes-fonte preservadas
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

## Gerar negativos sinteticos de fala

O gerador `tools/generate_synthetic_negatives.py` usa cinco vozes publicas
do Edge TTS: Antonio, Francisca e Thalita (pt-BR), Duarte e Raquel (pt-PT).
Sao 16 textos em tres velocidades (-15%, normal, +15%): palavras isoladas,
frases com `corno`, `problema`, `Singapura`, `irma` e confusores proximos.
Nenhum texto negativo pode conter a palavra completa `Nuclea`, inclusive
com acento. Apenas esses textos publicos sao enviados ao servico TTS.

Na pasta `wake-word`, com FFmpeg no PATH:

```powershell
python -m pip install -r requirements-tts.txt
python tools/generate_synthetic_negatives.py
```

Para concluir uma geracao interrompida, use `--resume`. O comando confere
os hashes e nao substitui fontes concluidas ou um corpus existente diferente.
O Edge TTS precisa de Internet; sua disponibilidade nao e garantida.

- `dataset/synthetic_negatives_v1/sources/`: falas completas em WAV mono
  PCM16, 16 kHz, sem cortar palavras, com contexto silencioso curto.
- `dataset/synthetic_negatives_v1/manifest.json`: texto, voz, velocidade,
  origem, hashes, grupo e parametros. Label 0, somente treino.
- `dataset/background_hard_negative/generated/synthetic_confusers_v1/`:
  ate tres janelas energeticas de 1 s por fonte, com versoes limpa,
  -9 dB e mistura de ambiente INMP441 a 18 dB de SNR, sem clipping digital.
  O silencio nao vira exemplo principal; falas completas sao preservadas.

Os treinadores existentes leem as janelas pela pasta de hard negatives.
Variacoes da mesma voz/texto pertencem ao mesmo grupo e nunca devem ser
distribuidas entre treino, validacao e teste. Os sinteticos nao substituem
negativos reais captados no INMP441; a pronuncia deve ser ouvida antes de um
novo treinamento. Gerar audios nao retreina nem altera os pesos do TFLite.

O ajuste de sensibilidade atual mantem o threshold normal 0.93359375 e exige
evidencia temporal nas ultimas tres janelas, incluindo a atual. Duas janelas
acima desse limiar confirmam normalmente. Para preservar palavras curtas,
um pico >=0.98 tambem pode ser confirmado por outra janela >=0.5, desde que
a atual seja >=0.5. Um pico isolado nao ativa sozinho. Os limiares sao iguais
durante espera, envio e reproducao. A referencia Python le os limiares do
header C++, evitando divergencia entre os testes e o firmware.

Para comparar as duas regras com o INT8 realmente embutido no firmware:

```powershell
python tools/evaluate_synthetic_negatives.py
```

O relatorio fica em `output/synthetic_negatives_v1/gate_diagnostic.json`.
Inclui as fontes sinteticas e uma amostra pequena de positivos reais, sem
Thayza. E um diagnostico de regressao, nao um teste independente de acuracia;
nao simula a caixa de som, o ambiente ou o cancelamento acustico de eco.

Diagnostico de 2026-10-25, sem retreinar os pesos:

| Fontes com acionamento | Regra anterior | Regra atual |
| --- | --- | --- |
| Negativos sinteticos (240 fontes) | 51 | 45 |
| Positivos amostrados (42 fontes) | 34 | 33 |

Exigir duas janelas >=0.93359375 sem a alternativa de apoio reduzia os
negativos para 30, mas reconhecia apenas 22 positivos; essa regra mais
agressiva foi descartada. O ajuste atual e moderado e nao elimina as
confusoes: `corno` e `irma` ainda acionaram em 4 de 45 fontes cada. Os novos
negativos estao preparados para um proximo treinamento, nao incorporados
aos pesos atuais. Nao use esses numeros como acuracia de producao.

### Confusores foneticos (corpus v2)

`python tools/generate_synthetic_negatives.py --corpus v2` gera, com as mesmas
cinco vozes e tres velocidades, palavras e nomes proximos de "Nuclea":
`nuclear`, `nucleo`, `nuclideo`, `nucleolo`, `nuca`, `Clea/Clea`, `Nubia`,
`luz clara`, `nunca mais`, `Cleo`, `Claudia`, `Nicole` e `Nadia`, tambem em
saudacoes ("Oi, nuclear", "Boa tarde, nucleo"). Fontes em
`dataset/synthetic_negatives_v2/` e janelas em
`dataset/background_hard_negative/generated/synthetic_confusers_v2/`. O v1
permanece intacto. Ouca algumas fontes antes de treinar: o TTS pode ler
`Clea` de forma diferente da pronuncia real.

O treinador agrupa qualquer pasta `synthetic_confusers*` no tipo
`synthetic_confuser`, com peso proprio (`CONFUSER_SHARE`, 12% da massa dos
positivos), em vez de misturar com ambiente/conversa legados. Os pesos de fala
e ruido nao mudam.

### Cortes parciais da palavra

`--partial-word-negatives` transforma cada positivo **clean do split de treino**
(nunca validacao/teste, nunca sinteticos) em tres negativos: inicio ("Nu..."),
fim ("...clea") e meio, cada um com 25-55% da regiao falada, sobre um piso de
ruido medido no proprio audio. Inicio tende a ficar na borda direita da janela e
fim na esquerda, como quando a palavra entra ou sai da janela deslizante. Os WAVs
vao para `<saida>/partial_word/`, com `parent_file` e hashes no manifesto, e o
tipo `partial_word` recebe o mesmo peso fixo dos confusores. Risco: um corte de
mais de ~60% pode ensinar o modelo a rejeitar palavras faladas rapido; confira o
recall de Eric/Gabriel e a regra de fala curta antes de promover.

## Treinar o modelo

### Treinamento multispeaker v3

O v7 e o modelo atualmente embutido no firmware. Os candidatos treinados ainda
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

O treinador multispeaker exporta seu proprio `nuclea_int8.tflite`. O exemplo
abaixo e do pipeline legado v2g, nao do modelo atualmente promovido.

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
  output\output_multispeaker_v7_reviewed\nuclea_int8.tflite `
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
mostrar `INMP441: BCLK=41 WS=42 SD=40` e nao deve mostrar `ROBOT_DISPLAY: Animacao`.
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
em 3.3 V. Monte com a alimentacao desligada. O alto-falante atual e de
**4 ohms e 5 W**. O MAX98357A entrega no maximo cerca de 3,2 W em 4 ohms com
5 V; um alto-falante de 5 W suporta essa potencia com folga, mas nao fica mais
alto por isso. O teste musical confirmou brownout com a alimentacao anterior
do PC; use uma alimentacao 5 V adequada ao conjunto (2 A ou mais) e um
capacitor eletrolitico de 470 a 1000 uF entre VIN e GND, perto do modulo.

GAIN conectado diretamente ao GND aumenta o ganho de 9 para 12 dB sem mudar
o firmware. Para 15 dB, use resistor de 100 kohms entre GAIN e GND. Conectar
GAIN ao VIN reduz o ganho, nao aumenta. Mais ganho nao aumenta a potencia
maxima do amplificador e pode causar distorcao. Com o limitador abaixo, prefira
GAIN aberto (9 dB) ou em GND (12 dB). Referencia:
[MAX98357A: controle de ganho](https://learn.adafruit.com/adafruit-max98357-i2s-class-d-mono-amp/pinouts).

No menu `Nuclea device audio`, `NUCLEA_SPEAKER_ENABLED` vem habilitado.
Os pinos sao configuraveis em `NUCLEA_SPEAKER_BCLK_GPIO`,
`NUCLEA_SPEAKER_WS_GPIO` e `NUCLEA_SPEAKER_DIN_GPIO`.

### Volume, passa-altas e limitador

Todo audio do alto-falante (TTS, `onsfx` e `offsfx`) passa por
`main/speaker_dsp.h` antes do I2S, nesta ordem:

| Opcao | Padrao | Efeito |
| --- | --- | --- |
| `NUCLEA_SPEAKER_VOLUME_PERCENT` | 100 | Volume digital |
| `NUCLEA_SPEAKER_BOOST_DB` | 6 | Ganho extra antes do limitador; aumenta a fala media |
| `NUCLEA_SPEAKER_HIGHPASS_HZ` | 150 | Passa-altas de 2a ordem; 0 desliga |
| `NUCLEA_SPEAKER_LIMIT_DBFS` | -3 | Teto dos picos enviados ao amplificador |

Antes, os picos do TTS chegavam a 0 dBFS e saturavam o amplificador (som
"estourado"). O passa-altas remove graves que um alto-falante pequeno nao
reproduz e que so consomem potencia e fazem o cone distorcer. O limitador tem
ataque instantaneo e liberacao de 80 ms: nenhum pico passa do teto, e o ganho
extra deixa a fala mais alta sem cortar a onda.

Ajuste na placa, ouvindo:

- Ainda distorce nas silabas fortes: baixe `NUCLEA_SPEAKER_LIMIT_DBFS` para -6
  ou deixe GAIN aberto (9 dB).
- Limpo, mas baixo: suba `NUCLEA_SPEAKER_BOOST_DB` para 9 ou 12.
- Voz fina demais: baixe `NUCLEA_SPEAKER_HIGHPASS_HZ` para 100.

Ao fim de cada reproducao, `SPEAKER: Playback ended` informa `limiter`
(maior reducao aplicada, em dB) e `clipped`. `clipped` maior que zero indica
amostras ja saturadas na origem: corrija o nivel no TTS/gateway, pois o
limitador nao recupera uma onda ja cortada. Fixar o alto-falante numa caixa
fechada ou baffle aumenta bastante o volume percebido e os medios-graves.

Com o alto-falante habilitado, o ESP envia `responseMode=speaker` junto ao WAV
para `/api/device-audio`. A NucleaInterface atualizada devolve PCM16 mono a
24 kHz em NDJSON na mesma conexao. O firmware valida os pacotes, acumula um
buffer limitado em PSRAM e reproduz sem esperar o audio completo. Nao ha
decodificador MP3: mantenha o workflow `nuclea-streaming.json` e o runtime de
streaming. Nao e necessario deixar o navegador aberto.

Durante gravacao, efeitos, envio, espera e reproducao TTS, novas wakewords sao
ignoradas: nao cancelam nem substituem o pedido atual. A captura continua sendo
drenada, mas a inferencia fica pausada durante efeitos/HTTP/reproducao, evitando
trabalho desnecessario e acionamentos pela propria resposta. O buffer e
liberado somente apos o worker terminar o pedido e a reproducao.
Ao terminar ou falhar, ha dois segundos para drenar captura e eco antes de
aceitar outra wakeword com uma nova janela. Audio invalido nao e repetido
automaticamente. Essa pausa de deteccao nao e cancelamento acustico de eco.

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
o amplificador deve indicar `I2S1 TX BCLK=14 WS=21 DIN=13`, seguido de volume,
boost, passa-altas e limite configurados.
Os testes de software e a compilacao nao substituem a validacao do som na placa.

## Remocao da musica de teste

O modo de teste musical e seu PCM foram removidos. A compilacao normal com
visor habilitado gera uma imagem LittleFS contendo somente os nove GIFs.
Execute o flash completo, nao apenas `app-flash`, para substituir tambem a
particao de arquivos e remover a musica da memoria acessivel do ESP:

```powershell
cd esp32_wakeword
idf.py -B build-speaker -p COM9 build flash monitor
```

Substitua `COM9` pela porta atual. Isso preserva as credenciais na NVS.
Nao use `erase-flash`. O agente nao atualiza a memoria fisica da placa
apenas alterando ou compilando os arquivos no computador.

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
grava no minimo 3 segundos. A extensao usa um limiar adaptativo congelado a
cada deteccao: o maior entre **RMS da janela da wakeword - 10 dB** e
**ruido ambiente + 8 dB**, limitado entre -65 e 0 dBFS. O ambiente e estimado
pelo percentil 20 dos ultimos 100 blocos de repouso (cerca de 2 s), com
referencia provisoria de -60 dBFS antes de 25 blocos. Efeitos, resposta TTS,
gravacao e cooldown nao alimentam essa estimativa.
Exige 100 ms continuos acima do limiar para confirmar atividade; picos
isolados nao renovam a gravacao. Depois de confirmar, ha histerese de 3 dB:
cair abaixo desse segundo limiar encerra a atividade e exige nova confirmacao.
Atividade confirmada renova uma margem de 1,5 segundo, sem ultrapassar 12 s. Por exemplo,
atividade ate 4,5 s leva o termino para 6 s; sem atividade perto do fim, o WAV
termina em 3 s. Ruido/TV suficientemente altos ainda podem prorrogar: isto e
um filtro de energia, nao um classificador de fala. Os parametros sao iniciais
e precisam ser conferidos no ambiente real, sobretudo com pouco contraste
entre a voz e o ruido. Isso nao altera o modelo/limiar da wakeword.
No inicio, o log `AUDIO_RECORDER: Atividade adaptativa` informa wake, ambiente,
on e off em dBFS. `NUCLEA_SILENCE_DBFS` so e usado como fallback quando nao ha
referencia valida da wakeword. Referencias sao preservadas apos onsfx.
Com os efeitos habilitados, os tempos comecam depois do som inicial; sem efeitos,
o firmware preserva os 400 ms de pre-roll anteriores a deteccao. Sao contados pelas amostras,
nao pelo atraso de processamento. O ultimo bloco e limitado para nao ultrapassar
a duracao calculada. Em `Nuclea device audio`, os parametros sao
`NUCLEA_MIN_RECORDING_MS=3000`, `NUCLEA_SILENCE_MS=1500` e
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
- A duracao minima de 3 s e a maxima de 12 s continuam valendo para o comando,
  sem contar os sons. Os efeitos acrescentam seu tempo ao ciclo: aproximadamente
  0,85 s no inicio, uma margem de 150 ms e 0,63 s no fim, mais o esvaziamento I2S.
- Os efeitos passam pelo mesmo volume, passa-altas e limitador da resposta TTS
  (veja [Volume, passa-altas e limitador](#volume-passa-altas-e-limitador)).

Os arquivos `main/assets/recording/onsfx.pcm` e `offsfx.pcm` sao embutidos no firmware
como PCM16 little-endian, mono, 24 kHz, sem cabecalho WAV. Nao precisam do
gateway, TTS, rede, MP3 decoder ou FFmpeg no ESP. Os originais `onsfx.mp4` e
`offsfx.mp4` ficam em `main/assets/recording/source/`, sem alteracoes.
Somente o silencio inicial/final do `onsfx` foi removido.
Para reduzir o volume dos dois efeitos, que estavam estourados, o `onsfx` recebeu
-3 dB e o `offsfx` passou a +3,63 dB (antes +6,63 dB). Ambos ficaram com RMS
em torno de -19 dBFS e pico abaixo de -5 dBFS. O `offsfx` continua com nivel RMS
proximo do `onsfx`, sem
recortar sua duracao nem saturar as amostras PCM. Isso nao garante o mesmo
volume percebido, pois os efeitos possuem timbres diferentes.

Para regenerar em `esp32_wakeword/main/assets/recording` (FFmpeg instalado):

```powershell
ffmpeg -y -i source/onsfx.mp4 -map 0:a:0 -af "atrim=start=0.53:end=1.38,asetpts=PTS-STARTPTS,volume=-3dB" -ac 1 -ar 24000 -c:a pcm_s16le -f s16le onsfx.pcm
ffmpeg -y -i source/offsfx.mp4 -map 0:a:0 -af "volume=3.63dB" -ac 1 -ar 24000 -c:a pcm_s16le -f s16le offsfx.pcm
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
`nuclea_gif_player_fixed/data/`:

| Arquivo | Frames | Duracao | Uso |
| --- | ---: | ---: | --- |
| `sleep2.gif` | 72 | 6,00 s | Repouso, em loop |
| `wake-open2.gif` | 24 | 2,00 s | Olhos abertos -> fechados (fechar) |
| `wake-open2-reverse.gif` | 24 | 2,00 s | Reverso exato de `wake-open2.gif` (abrir) |
| `idle.gif` | 97 | 8,08 s | Olhos abertos, em loop |
| `loadingtrans.gif` | 12 | 1,00 s | Idle -> loading, 1,5 s apos enviar o comando (corta o idle) |
| `loading.gif` | 24 | 2,00 s | Em loop enquanto o modelo processa a requisicao |
| `loadingtrans-reverse.gif` | 11 | 1,00 s | Loading -> idle, uma vez antes da resposta |
| `smile.gif`, `elegant.gif` | | | Reacoes a resposta |
| `dizzy.gif`, `angry.gif`, `cry.gif` | | | Reacoes a chacoalhos |

Nao e preciso gravar o sketch Arduino nem executar o uploader LittleFS
separadamente. A imagem LittleFS e gerada durante o build e incluida no flash.
Mantenha os nomes e a resolucao 280x240. Os quatro primeiros GIFs sao
obrigatorios; uma expressao opcional ausente/invalida usa idle, sem desativar
todo o visor. Nao deixe outros arquivos em `data/`: todos entram na imagem.

Ao trocar `wake-open2.gif`, regenere o reverso (requer Pillow). O script confere que
cada imagem e cada tempo do resultado sao identicos ao original invertido:

```powershell
python esp32_wakeword/tools/reverse_gif.py `
  nuclea_gif_player_fixed/data/wake-open2.gif nuclea_gif_player_fixed/data/wake-open2-reverse.gif
```

Frames identicos consecutivos sao unidos, somando seus tempos; por isso
`wake-open.gif` tem 51 frames e a mesma duracao.

Por padrao, o visor mostra o robo dormindo desde a inicializacao, inclusive
durante a configuracao Wi-Fi. Isso e apenas um estado visual, nao deep sleep.
Nenhum GIF e espelhado por software; `sleep2.gif` ja vem na orientacao final.
O detector inicia depois da conexao Wi-Fi, como no fluxo anterior.

Uma wakeword aceita inicia a gravacao e envia o evento de abertura dos olhos,
tocando `wake-open.gif`. Fechar os olhos toca `wake.gif`. As duas transicoes
sao decodificadas da flash como as demais animacoes, sem cache em PSRAM: com
53 frames, o cache antigo exigiria 7,1 MB dos 8 MB de PSRAM.
Depois, `idle.gif` permanece em loop durante a gravacao e o HTTP.
Quando o primeiro pacote PCM valido da resposta TTS chega, ocorre um sorteio:
**45% idle, 30% smile e 25% elegant**. A expressao escolhida toca um ciclo
inteiro e retorna ao idle. Onsfx, offsfx, pings e erros sem audio nao geram
esse sorteio. Um pacote aceito indica inicio de recebimento, nao garante
que toda a resposta terminara sem erro.
O tempo de inatividade comeca ao concluir ou falhar o envio: por padrao,
30 segundos. A transicao normal fecha os olhos e retorna a `sleep.gif`.
A wakeword aceita sai imediatamente do loop de `sleep.gif`, entre transferencias
de frames, e inicia a abertura dos olhos antes do onsfx e da gravacao. Nao
aguarda os quase seis segundos do ciclo de repouso nem o envio do comando.
As demais trocas aguardam o fim do ciclo atual e a duracao do ultimo frame.
Uma deteccao durante o fechamento agenda a reabertura apos ele terminar.
Esse caso adia somente o visual; a gravacao nao aguarda o GIF.

### Reacoes a chacoalhos (piezo)

**Modo atual: batidas** (`NUCLEA_PIEZO_KNOCK_MODE=y`). Com 220k em serie e o
pull-down interno, cada batida gera so 1 ou 2 pulsos, pouco para o detector de
chacoalho continuo descrito abaixo. Neste modo, **3 batidas em ate 2 s**
(`NUCLEA_PIEZO_KNOCKS`, `NUCLEA_PIEZO_KNOCK_WINDOW_MS`) disparam a mesma
sequencia de reacoes. Pulsos a menos de 150 ms um do outro contam como uma
batida. O monitor mostra `PIEZO: Batida 1/3`, `2/3` e `Batidas confirmadas`.
Depois de colocar 1 Mohm entre os terminais do piezo, desmarque o modo batidas
e `NUCLEA_PIEZO_PULLDOWN` para usar o chacoalho continuo.

O piezo e lido pelo periferico PCNT, que conta pulsos em hardware com filtro
de glitch. A cada 20 ms, `main/piezo_sensor.cc` envia a `ObserveMotion` se
houve pulso nos ultimos `NUCLEA_PIEZO_HOLD_MS` (100 ms por padrao) e a janela teve pelo menos
`NUCLEA_PIEZO_MIN_PULSES` pulsos (3 por padrao). Aumentar ambos reduz a sensibilidade:

- Mais de 1 segundo de movimento forte continuo confirma um evento.
- Pulsos curtos ou lacunas de amostragem maiores que 100 ms nao qualificam.
- Movimento mantido gera somente um evento; exige 250 ms de quietude para rearmar.
- Primeiro evento: dizzy e depois idle.
- Segundo: dizzy, angry e depois idle.
- Terceiro: dizzy, cry e depois idle; reinicia a contagem.
- Dois minutos sem novo evento confirmado reiniciam a sequencia no proximo evento.

As reacoes aguardam o fim do GIF atual e sao enfileiradas com memoria limitada.
Eventos excedentes sao descartados com aviso. O primeiro dizzy corta a animacao atual na hora (inclusive sleep e abertura dos olhos); reacoes seguintes aguardam o ciclo.

Ligacao atual, com o menu `Nuclea robot display` > `NUCLEA_PIEZO_*`:

```text
ESP32-S3                         Disco piezo
========                         ===========
GPIO 1 -------[ 220k ]-------+-- terminal + (vermelho)
                             |
                           [1M]  (opcional; desmarque o pull-down interno)
                             |
GND -------------------------+-- terminal - (preto)
```

Montagem atual: 220k em serie, sem o 1M. O pull-down interno (cerca de 45k)
fica ligado e forma um divisor com o 220k: o pino recebe so cerca de 1/6 da
tensao do piezo, entao apenas batidas/trancos fortes contam. Para mais
sensibilidade, coloque 1 Mohm entre os terminais do piezo e desmarque
`NUCLEA_PIEZO_PULLDOWN`. Nunca desmarque o pull-down sem o 1M: o pino fica
flutuando e conta ruido.

- **Nao use GPIO 19/20.** Sao D-/D+ da USB nativa, usada para gravar e
  monitorar esta placa: com o piezo no GPIO 20 a porta COM some apos o boot.
  O build recusa 19/20 enquanto o console USB estiver ligado. GPIO 1, 2, 8, 9
  e 10 tambem estao livres.
- Um disco piezo golpeado gera dezenas de volts. O resistor em serie limita a
  corrente nos diodos de protecao do ESP; nao ligue o disco direto no GPIO por
  muito tempo. O pull-down interno (cerca de 45 kohms) descarrega o disco; com
  o resistor de 1 Mohm externo, ele fica mais sensivel a movimentos lentos.
- O pino digital so conta pulsos acima de cerca de 1,6 V: batidas e chacoalhos
  com impacto, nao inclinacao suave. O disco precisa estar preso ao corpo do
  robo, de preferencia com um pequeno peso colado no centro.

Para testar, abra o monitor e chacoalhe: `PIEZO: pulsos=N forte=M/50 amostras`
aparece a cada segundo com atividade. Chacoalhando por mais de 1 s, o visor
registra `Chacoalho confirmado`. Sem nenhuma linha `PIEZO: pulsos`, confira a
ligacao. Se `forte` ficar com falhas mesmo chacoalhando, aumente
`NUCLEA_PIEZO_HOLD_MS` (por exemplo 300).

No menu `Nuclea robot display`, ajuste o tempo, clock SPI e offsets do painel,
ou desabilite o visor. O padrao e SPI 40 MHz, orientacao horizontal e offsets
X=20/Y=0. Se a imagem ficar deslocada, ajuste esses offsets conforme a tela;
a orientacao e as cores ainda precisam ser confirmadas no hardware real.

Captura I2S (prioridade 6), inferencia (4), envio HTTP (2) e visor (1) sao
separados. A inferencia roda no core 1; captura, alto-falante (3), envio e
visor usam core 0. O visor permanece abaixo das tarefas de audio/rede e nao
disputa mais o core ocupado pelas inferencias longas.
Nos frames intermediarios, o tempo de decodificacao/transferencia integra o
intervalo do GIF, sem somar outra espera completa. O ultimo frame ainda
fica visivel pelo seu intervalo inteiro antes das trocas normais; sair do
repouso por wakeword e a excecao para responder prontamente ao usuario.
Nao ha descarte de frames nas outras animacoes nem garantia de FPS fixo.
Durante um envio, a captura continua, mas deteccao e interrupcao por nova
wakeword ficam desativadas. O buffer da gravacao so e reutilizado apos o
worker confirmar o encerramento. Apenas o worker HTTP fecha/libera seu
cliente e consome a confirmacao de parada do alto-falante.
Se a fila de captura atrasar, o firmware registra o descarte e recompoe
a janela; uma gravacao com lacuna e descartada em vez de enviar audio incompleto.
Erros de leitura e overflow DMA/I2S tambem sinalizam lacunas. O historico de
confirmacao da wakeword e limpo entre pedidos e apos lacunas, preservando cooldown.

Falha de montagem nao formata a flash; falha de inicializacao do visor
permite continuar sem ele.
O firmware nao recebe eventos de fim de reproducao do navegador: o temporizador
se baseia no fim do HTTP, nao no fim audivel do TTS.

### Diagnosticar lentidao do visor e HTTP 403

A cada aproximadamente cinco segundos, `ROBOT_DISPLAY: perf` informa o numero
de frames na janela, `decode_avg_ms`, `lcd_avg_ms`, `frame_max_ms`, memoria
interna livre e pilha livre. Os tempos incluem preempcoes por tarefas de
maior prioridade; envie algumas dessas linhas durante repouso e resposta
para comparar o comportamento real, sem alterar os limiares da wakeword.
`stack_livre` agora usa diretamente os bytes devolvidos pelo ESP-IDF;
versoes anteriores multiplicavam incorretamente esse numero por quatro.

HTTP 401/403 e uma recusa de acesso, nao um indicador de sobrecarga da CPU.
No gateway atual, 401/403 do n8n sao repassados ao ESP. Confira se a chave
salva no portal corresponde a credencial Header Auth do webhook, com nome
`X-Nuclea-Key`. Para confirmar a origem, procure o mesmo `request_id` nos
logs do gateway (`code=authentication_failed` indica recusa do n8n).
O firmware registra uma orientacao ao receber esses status, nunca a chave.
Nao remova a autenticacao para corrigir animacao lenta.

### Tamanho das animacoes e memoria

Os nove GIFs atuais somam 10.539.924 bytes de flash, dentro da particao
LittleFS de 0xCF0000 (13,5 MB). Na RAM, o visor usa apenas o canvas RGB565 e o
buffer de restauracao do decoder em PSRAM (2 x 134.400 bytes) e uma faixa DMA
interna; o antigo cache de 4 MB do `wake.gif` foi removido.
Os GIFs fornecidos continuam intactos, sem reduzir cores, resolucao ou
quantidade de frames; somente `wake-open.gif` e gerado a partir deles.

### Validacao essencial da integracao

```powershell
cd esp32_wakeword
python -m unittest tools.test_visual_contract tools.test_audio_bridge_contract tools.test_wifi_portal_contract
idf.py build
python -m unittest tools.test_capture_stack_budget
idf.py -p COM9 flash monitor
```

O build verifica a maquina visual por `static_assert`: pesos do sorteio,
trocas apenas entre ciclos, sequencia/timeout dos chacoalhos, fila limitada,
retorno ao idle, duracao minima, rearme e falhas de amostragem do sensor.
O controle de gravacao verifica cinco cenarios adicionais por `static_assert`:
silencio com WAV de 3 s, renovacao da margem de 1,5 s, volume continuo limitado
a 12 s, silencio inicial sem encerramento antecipado e buffer cheio sem escrita.
Tambem verifica o BOOT: acionamento apos 3 segundos, acionamento unico por
pressao e reinicio da contagem apos soltar o botao.
O teste de pilha analisa o objeto compilado com `xtensa-esp32s3-elf-objdump`,
disponivel no terminal ESP-IDF. Se nao estiver no PATH, defina `XTENSA_OBJDUMP`
com o caminho do executavel. Sem compilador ou objeto, esse teste e ignorado;
ele mede a reserva local da funcao, nao substitui a medicao de pilha no hardware.
Tambem verifica o limitador (nenhum pico acima do teto, fala comum sem
reducao, passa-altas removendo DC) e a envoltoria do piezo (chacoalho de 1,5 s
confirma; batida isolada ou chacoalho curto nao).
No hardware, confira `Animacao: /robot/wake-open.gif`, a pinagem `BCLK=41 WS=42 SD=40`,
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
confira os GPIOs do microfone e regrave. A linha `ROBOT_DISPLAY: Animacao`
significa que o visor ainda esta habilitado no firmware gravado.

Se `audio` variar mas `q_in` ficar constante, revise o DSP. Se `q_in` variar e
`q_out` permanecer saturado, confirme se TFLite, tabelas MFCC e fontes C++ foram
promovidos juntos.

`A stack overflow in task inmp441_capture` e um crash real, nao um erro de
Wi-Fi ou de MFCC. A captura atual usa buffers fora da pilha e registra
`captura_stack_livre`; recompile e regrave para aplicar a correcao. A mensagem
`Fila de audio atrasada` indica descarte de blocos, nao necessariamente crash.
