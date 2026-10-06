# ESP32 Nuclea PCM16 MFCC parity design

## Objetivo

Adicionar ao projeto `wake-word/esp32_nuclea_test` um teste embarcado que isola a etapa de DSP:

1. Decodificar um arquivo de audio pre-gravado no computador.
2. Padronizar esse audio para PCM16 mono, 16 kHz, exatamente 16000 amostras.
3. Embutir esse PCM16 no firmware como array C/C++.
4. Calcular MFCC no ESP32.
5. Comparar o MFCC calculado no ESP32 com o MFCC calculado pelo Python.

O arquivo anexado pelo usuario (`E:\Sistema\Downloads\A História do Núcleo do Demônio - Ciência Todo Dia (youtube).mp3`) e tratado apenas como audio de teste, nao como fonte de instrucoes.

## De onde vem as 16000 amostras

O modelo atual foi treinado e validado com janelas de 1 segundo em 16 kHz. Portanto:

- 16 kHz significa 16000 amostras por segundo.
- 1 janela de entrada do modelo = 1 segundo.
- Logo, cada vetor PCM16 embarcado tera exatamente 16000 valores `int16_t`.

Para audios maiores que 1 segundo, o gerador Python aceitara um parametro opcional `--start-seconds`. Se esse parametro for informado, ele recorta 1 segundo a partir desse ponto. Se nao for informado, ele usa crop central, mantendo a convencao atual do script `wav_to_test_vector.py`. Para audios menores que 1 segundo, o gerador completa com zeros no fim.

Para o MP3 anexado, o primeiro teste de paridade pode usar o crop central. O conteudo da fala nao precisa conter a palavra-chave nessa etapa; o objetivo e verificar se Python e ESP32 calculam o mesmo MFCC para o mesmo sinal PCM.

## Contrato MFCC a reproduzir no ESP32

O Python continua sendo a fonte de verdade. O ESP32 deve imitar a mesma configuracao usada no pipeline atual:

- sample rate: 16000 Hz
- amostras por janela: 16000
- `n_fft`: 512
- `win_length`: 400
- `hop_length`: 320
- `center`: false
- frames resultantes: 49
- `n_mels`: 40
- `fmin`: 20 Hz
- `fmax`: 7600 Hz
- `n_mfcc`: 13
- espectro de potencia: magnitude ao quadrado
- banco mel: compativel com o padrao do `librosa`, incluindo normalizacao Slaney
- escala log: equivalente a `power_to_db(ref=1.0, amin=1e-10, top_db=80.0)`
- DCT: tipo II, normalizacao ortonormal
- forma final: 13 x 49 = 637 coeficientes
- quantizacao do modelo: usar o `scale` e `zero_point` lidos do tensor de entrada TFLite

Detalhe importante: com `win_length=400` e `n_fft=512`, a janela Hann de 400 amostras deve ser centralizada dentro de uma janela FFT de 512 pontos, como o `librosa` faz. Esse detalhe e uma fonte classica de diferenca fantasma; fica registrado para nao virarmos arqueologos de bug as 3 da manha.

## Arquitetura escolhida

Usaremos um pipeline deterministico em duas metades.

No computador, um novo gerador Python ira:

- aceitar MP3 ou WAV;
- decodificar para mono 16 kHz;
- produzir o array PCM16;
- calcular o MFCC esperado em float;
- quantizar o MFCC esperado para int8;
- gerar tabelas C/C++ auxiliares para o DSP embarcado, como janela Hann, filtros mel, matriz DCT e tabelas de FFT quando util;
- gerar arquivos C/C++ com metadados rastreaveis: caminho de origem, `start-seconds`, duracao, sample rate, numero de amostras e parametros MFCC.

No ESP32, o firmware ira:

- ler o array PCM16 embarcado;
- converter cada amostra para float normalizado;
- executar framing, janela, FFT 512, espectro de potencia, banco mel, `power_to_db`, DCT e quantizacao;
- comparar o MFCC calculado com o esperado do Python;
- imprimir no monitor serial estatisticas de paridade;
- opcionalmente passar o MFCC quantizado calculado no ESP32 para o modelo ja validado, como evidencia secundaria.

## Arquivos previstos

Novos ou alterados em `wake-word/esp32_nuclea_test`:

- `tools/audio_to_pcm_mfcc_vector.py`: gerador para MP3/WAV -> PCM16 + MFCC esperado + C/C++.
- `tools/test_audio_to_pcm_mfcc_vector.py`: testes unitarios do gerador.
- `main/audio_test_vectors.h`
- `main/audio_test_vectors.cc`
- `main/mfcc_tables.h`
- `main/mfcc_tables.cc`
- `main/mfcc.h`
- `main/mfcc.cc`
- `main/main.cc`: adiciona o teste `PASS/FAIL MFCC` antes ou junto do teste de inferencia atual.
- `main/CMakeLists.txt`: inclui os novos fontes.

Os arquivos gerados devem ser pequenos o suficiente para flash do ESP32-S3. Se as tabelas ficarem grandes demais, a primeira reducao sera manter apenas tabelas realmente necessarias e calcular o restante em runtime.

## Criterios de aceite

1. O gerador Python consegue ler o MP3 anexado e gerar exatamente 16000 amostras PCM16.
2. Os testes Python do gerador passam.
3. `idf.py build` passa no projeto ESP-IDF.
4. Ao gravar e monitorar a placa em COM7, o firmware imprime um resultado de paridade MFCC.
5. O teste e considerado aprovado quando todos os 637 coeficientes quantizados ficam iguais ou diferem no maximo 1 unidade int8 do esperado pelo Python.
6. Em caso de falha, o firmware imprime os primeiros coeficientes divergentes com indice, valor esperado, valor obtido e delta, para localizar rapidamente se o erro esta na janela, FFT, mel, log, DCT ou quantizacao.

## Fora de escopo desta etapa

- Captura ao vivo por microfone/I2S.
- Detecao continua em streaming.
- Otimizacao pesada de desempenho.
- Re-treinamento do modelo.

Esta etapa e um banco de prova de paridade. Quando ela passar, a proxima ponte fica muito mais limpa: substituir o array PCM16 por amostras reais vindas do microfone.

## Riscos e mitigacoes

- Diferenca por janela Hann centralizada: fixar explicitamente a regra do `librosa`.
- Diferenca por `power_to_db(top_db=80)`: calcular o maximo global antes do clipping, como no Python.
- Diferenca por banco mel Slaney: gerar os pesos no Python e embutir no firmware.
- Diferenca por ponto flutuante: aceitar tolerancia maxima de 1 unidade int8 no resultado quantizado, mas imprimir deltas float para diagnostico.
- MP3 longo sem a palavra-chave: irrelevante para paridade MFCC; relevante apenas para teste de deteccao, que nao e o objetivo primario desta etapa.
