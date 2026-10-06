# Wake word Nuclea

Detector local da palavra de ativacao **Nuclea** para ESP32-S3 com microfone
INMP441. O firmware processa audio a 16 kHz, calcula MFCC e executa um modelo
TensorFlow Lite INT8 no proprio microcontrolador.

## Modelo ativo

- Variante: `v2g_replay_hardneg`
- Entrada: `1 x 13 x 49 x 1`, MFCC INT8
- Janela: 1 segundo
- Avanco entre inferencias: 160 ms
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
| SCK/BCLK | GPIO 11 |
| WS | GPIO 10 |
| SD | GPIO 12 |

O LED RGB integrado usa o GPIO 48. No boot ele testa vermelho, verde e azul.
Quando a wake word e aceita, o LED verde alterna entre ligado e apagado.

## Compilar e gravar

Use um terminal ESP-IDF 5.5.x:

```powershell
cd esp32_wakeword
idf.py set-target esp32s3
idf.py build
idf.py -p COM9 flash monitor
```

Troque `COM9` pela porta da placa. Depois do boot, diga **Nuclea**. Uma deteccao
valida gera `Wakeword detectada` no monitor e alterna o LED.

## Testes

```powershell
python -m unittest discover -s train_models -p "test_*.py"
python -m unittest discover -s tools -p "test_*.py"
python -m unittest discover -s esp32_wakeword\tools -p "test_*.py"
```

## Diagnostico

- `audio` e `peak`: nivel recebido pelo INMP441.
- `score` e `max_score`: probabilidade da wake word.
- `q_in`: faixa INT8 dos MFCC enviados ao modelo.
- `q_out`: saidas INT8 para negativo e positivo.
- `positivos`: estado da confirmacao temporal.

Se `audio` variar mas `q_in` ficar constante, revise o DSP. Se `q_in` variar e
`q_out` permanecer saturado, confirme se TFLite, tabelas MFCC e fontes C++ foram
promovidos juntos.
