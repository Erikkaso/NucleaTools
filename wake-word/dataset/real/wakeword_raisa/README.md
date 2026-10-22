# Dataset de wake word: Núclea

Dataset criado a partir de `raisa.ogg` (45.53s), com 11 ocorrências de "Núclea".

## Formato

- WAV PCM 16-bit, mono, 16.000 Hz; todos com **exatamente 1 segundo** (16.000 amostras).
- `manifest.csv` descreve cada arquivo, fonte, rótulo, transformação e métricas.
- `quality_review.csv` registra os 11 exemplos originais triados e suas marcações.
- `review_preview.mp3` permite ouvir as 11 versões limpas, com pausas (não usar para treino).
- `montar_dataset_nuclea.py` reproduz o procedimento com a gravação original e dependências.

## Pastas

- `positive/original/`: 11 gravações recortadas, **sem tratamento**.
- `positive/clean/`: 11 versões suavemente filtradas e com ruído atenuado.
- `positive/augmented/`: 66 variações geradas **a partir dos clips tratados** (6/ocorrência).
- `negative/other_speech/`: 8 exemplos de outras palavras sem Núclea.
- `negative/silence/`: 18 janelas de quase silêncio, sem voz.
- `negative/ambient_noise/`: 4 janelas de ambiente (pássaros/ruído, sem voz).

Total: **118 WAV**, incluindo **88 positivos (11 x 8)** e **30 negativos**.

## Filtro e augmentation

- Localização assistida pela transcrição e pela energia/amplitude dos trechos originais.
- Pré-filtro técnico em cada positivo: RMS >= -38 dBFS, pico >= -28 dBFS e saturação < 0,1%;
  conferir também margens antes/depois da palavra na tabela de qualidade.
- Pré-filtro do áudio limpo: Butterworth passa-banda suave ~80–6.900 Hz +
  redução espectral leve de ruído estacionário, 60% de atenuação, usando
  janelas de ambiente como referência. O áudio original foi preservado.
- 6 aumentos: velocidade 0,94x e 1,06x (mudança sutil de pitch),
  ganho -3dB e +3dB, mistura com ambiente real a SNR 25dB,
  atraso de 35ms (preenchimento com zeros).
- Atenuação de picos apenas se necessário (máximo de 92% da amplitude plena).

## Status da pré-triagem e limites

Os 11 positivos correspondem a falas transcritas como "Núclea". Os recortes
são **pré-aprovados por transcrição e inspeção de energia**: ainda é importante
ouvir cada `positive/original/` e `positive/clean/`, especialmente perto de
frases como "Boa tarde Núclea". A pré-triagem **não é uma validação
fonética automática ou um reconhecimento ASR independente**.

Um clip de 1 segundo pode conter o final da expressão que antecede Núclea;
a palavra principal foi mantida integralmente na janela de 1 segundo.

Todas as variações derivadas do mesmo `source_id` são altamente correlacionadas.
**Não misture um original e suas augmentations entre treino e teste**.
Como tudo veio da mesma gravação/voz, teste o modelo com **outras gravações
independentes, outras vozes e condições de ruído**, para medir generalização.

Esta pasta é um dataset pré-filtrado; não equivale a 88 pronúncias independentes.

## Reproduzir

```bash
pip install numpy scipy soundfile noisereduce
python montar_dataset_nuclea.py --input raisa.ogg --output dataset_nuclea
```

A janela da fala original e a duração são específicas desta entrada.

## Contagens

- Positivos originais: 11
- Positivos limpos: 11
- Positivos aumentados: 66
- Negativos de outras palavras: 8
- Negativos de quase silêncio: 18
- Negativos de ambiente: 4
