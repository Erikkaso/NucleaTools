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

### Esquema rapido: ESP32-S3, microfone e LED

O esquema abaixo corresponde ao `sdkconfig` atual: microfone nos GPIOs
**4/5/6**, visor habilitado e LED RGB integrado no **GPIO 48**.
Os numeros sao os GPIOs impressos na placa, nao a posicao fisica dos pinos.
Desligue o USB e qualquer outra alimentacao antes de montar ou alterar fios.

```text
ESP32-S3                         INMP441
========                         =======
3V3 ---------------------------- VDD
GND ---------+------------------ GND
             +------------------ L/R  (canal esquerdo)
GPIO 4 ------------------------- SCK / BCLK
GPIO 5 ------------------------- WS
GPIO 6 <------------------------ SD   (audio do microfone)

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
GPIO 10 ------------------------ SCK / SCL
GPIO 11 ------------------------ MOSI / SDA
GPIO 12 ------------------------ CS
GPIO 9 ------------------------- DC
GPIO 8 ------------------------- RST / RES
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
inicia o detector. Uma deteccao gera `Wakeword detectada` e inicia a gravacao
PCM16 mono a 16 kHz, com 400 ms de audio anteriores a deteccao. Por padrao, ela
grava no minimo 5 segundos. Audio com RMS >= -32 dBFS renova uma margem de
1,5 segundo apos a ultima atividade, sem ultrapassar 12 segundos. Por exemplo,
atividade ate 4,5 s leva o termino para 6 s; sem atividade perto do fim, o WAV
termina em 5 s. Ruido alto tambem pode prorrogar: e deteccao de volume, nao VAD.
Os tempos incluem os 400 ms anteriores a deteccao e sao contados pelas amostras,
nao pelo atraso de processamento. O ultimo bloco e limitado para nao ultrapassar
a duracao calculada. Em `Nuclea device audio`, os parametros sao
`NUCLEA_MIN_RECORDING_MS=5000`, `NUCLEA_SILENCE_MS=1500` e
`NUCLEA_MAX_RECORDING_MS=12000`; o maximo permitido e 12 segundos.

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
O controle de gravacao verifica cinco cenarios adicionais por `static_assert`:
silencio com WAV de 5 s, renovacao da margem de 1,5 s, volume continuo limitado
a 12 s, silencio inicial sem encerramento antecipado e buffer cheio sem escrita.
Tambem verifica o BOOT: acionamento apos 3 segundos, acionamento unico por
pressao e reinicio da contagem apos soltar o botao.
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
