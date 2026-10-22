# Rodada v7: dataset revisado e split aleatorio do Eric

Executada em 2026-10-19. O candidato melhorou neste diagnostico, mas **nao foi
promovido ao ESP32**: ainda houve falsos acionamentos e falta validacao fisica.

## Respeito a revisao manual

- Thayza excluida de todos os splits, inclusive derivados e negativos.
- Apenas positivos clean existentes foram considerados. Pastas antigas
  `augmented/` e aliases `original/` nao entraram nesta rodada.
- Cinco clean da Raisa foram ignorados porque seus `parent_file` originais
  foram removidos. Nenhum candidato apagado foi restaurado de manifestos/review.
- 426 positivos clean elegiveis antes da checagem de tamanho. Um arquivo de
  21.559 amostras foi rejeitado, nao truncado: ficaram 425 positivos humanos.
- Os arquivos do dataset, incluindo augmentations antigas, foram preservados.
  Os derivados antigos continuam no disco, mas NAO foram usados.

Foram gerados 1.077 WAVs novos, tres por positivo clean de treino, em
`output_multispeaker_v7_reviewed/augmented/`. As operacoes sao ganho,
deslocamento seguro e mistura de ruido/dialogo de treino, sem pitch ou time
stretch. O deslocamento nao e aplicado se descartaria energia significativa.
Nao houve novo recorte automatico da palavra. Cada WAV tem um segundo,
PCM16 mono a 16 kHz, com parent_file e hashes no manifesto; o MFCC usa o mesmo
PCM gravado no arquivo. Nenhuma variante de teste/validacao foi gerada.

## Split e tamanho

Eric foi separado ANTES da augmentation: componentes de janelas sobrepostas
permanecem juntos. O sorteio e estratificado por gravacao, com aproximadamente
80/10/10 dos grupos, nao uma proporcao exata dos WAVs. A deduplicacao PCM usa
preferencia por teste/validacao para nao deixar copias no treino.

| Split | Total de exemplos | Eric clean | Outros positivos reais |
| --- | --- | --- | --- |
| Treino | 6.344 | 165 | 194 |
| Validacao | 581 | 19 | Lara 14, Ryam 8 |
| Teste | 587 | 15 | Gabriel 10 |

O treino tambem inclui os 1.077 derivados, 160 positivos sinteticos limitados
por peso e os negativos. As linhas de Eric aumentadas totalizam 660 no treino.
Foram deduplicadas 168 copias PCM, alem do arquivo longo rejeitado.

Os tempos INMP441 vieram dos manifestos de captura. Para o legado `voz.ogg`,
a janela foi estimada pelos metadados de inicio, padding e velocidade original.
A auditoria nao encontrou janelas positivas Eric sobrepostas entre splits nem
hashes reais/grupos iguais entre splits. Isso nao verifica automaticamente se
cada palavra esta inteira: a aprovacao dos recortes e a revisao do usuario.

**Limitacao importante:** Eric compartilha locutor e sessoes entre treino e
teste. Trata-se de teste aleatorio de recortes, nao de sessao desconhecida.
Gabriel continua fora do treino; Lara/Ryam ficam na validacao. Esses datasets
ja foram inspecionados em rodadas anteriores e nao constituem teste cego.

## Treinamento

Mesmos parametros da v6, sem novo sorteio:

| Parametro | Valor |
| --- | --- |
| Seed | 1204528219 |
| Learning rate inicial | 0.0006735104736469071 |
| Dropout / batch | 0.3 / 32 |
| Arquitetura | DS-CNN temporal, MFCC 1 x 13 x 49 x 1 |
| Epocas | 26 executadas, pesos restaurados da epoca 14 |
| Selecao dos pesos | Perda ponderada de validacao, paciencia 12; nao pelo teste |
| Limiar INT8 | 0.93359375; alta confianca 0.98 |
| TFLite | 12.840 bytes; saida [negativo, Nuclea] |
| Entrada INT8 | escala 3.174777030944824; zero point 71 |

A calibracao usa negativos de validacao, com meta de ate 1% por janela e
nenhum acionamento nos negativos de silencio/ambiente usados na calibracao.
O limiar nao foi reduzido para melhorar o resultado do teste.

## Resultados medidos

| Avaliacao INT8 | Resultado |
| --- | --- |
| Eric, validacao | 18/19 reconhecidos (94,7%) |
| Lara, validacao | 10/14 (71,4%) |
| Ryam, validacao | 3/8 (37,5%) |
| Validacao agregada positiva | 31/41 (75,6%) |
| Validacao negativa | 1/540 falso positivo (0,19%) |
| Eric, teste | 14/15 reconhecidos (93,3%) |
| Gabriel, teste | 10/10 (100%) |
| Teste agregado positivo | 24/25 (96%) |
| Teste negativo | 7/562 falsos positivos por janela (1,25%) |
| Teste positivo + ruido a 20 dB SNR | 21/25 (84%) |
| Teste positivo + ruido a 10 dB SNR | 17/25 (68%) |
| Silencio digital/DC | scores 0, 0, 0 |

Os sete erros negativos foram dois de ambiente INMP441, quatro de fala negativa
INMP441 e um de Common Voice. Nao houve erro nos negativos sinteticos calmos,
matched_silence ou mined_quiet de teste. A contagem por janela nao e a contagem
de acionamentos apos confirmacao temporal.

Replay com regra 2 de 3 ou um score >= 0.98 e cooldown de dois segundos:

| Fonte | Duracao amostrada | Eventos 160 ms | Eventos 320 ms |
| --- | --- | --- | --- |
| Ambiente | 180 s | 0 | 0 |
| Ambiente calmo | 119,6 s | 0 | 0 |
| Conversas | 180 s | 1 | 0 |
| Musica | 68,2 s | 1 | 0 |
| Silencio absoluto | 180 s | 0 | 0 |

A v6 teve oito eventos e a v7 dois nos mesmos trechos negativos a 160 ms.
Os 96% positivos NAO sao comparaveis diretamente aos 46,7% da v6: a revisao
mudou os recortes, o tamanho do teste e o split do Eric. Nao e possivel atribuir
o ganho exclusivamente a limpeza, nem afirmar 96% para qualquer voz/ambiente.
O desempenho de Ryam e a queda com ruido continuam sendo limitacoes.

Na simulacao temporal, oito recortes por locutor com duas fases de janela e
silencio artificial resultaram em Eric 16/16 e Gabriel 15/16 a 160 ms; a 320 ms,
16/16 e 12/16. Sao tentativas correlacionadas de um diagnostico pequeno, nao
novas pronuncias independentes nem deteccao medida no hardware.
As seis frases anotadas restantes da Raisa foram detectadas; sao dados de treino.

## Artefatos e verificacoes

Em `output_multispeaker_v7_reviewed/`: `nuclea_final.keras`, `nuclea_int8.tflite`,
`training_config.json`, `data_manifest.json`, `data_audit.json`, `features.npz`,
`results.json`, `stream_evaluation.json` e os WAVs novos em `augmented/`.

SHA-256 do candidato:

```text
6b4321b5b38a4fd793080b0a3889a0aeff7bda30dba1acd31063689266728aaf
```

25 testes essenciais aprovados: 12 de dados, 6 de revisao/split, 3 de
configuracao e 4 de mineracao. Auditoria verificou exclusao de Thayza, hashes
dos 1.077 WAVs novos, parentes existentes e separacao de grupos/intervalos.
O hash do modelo ativo continua:

```text
AF197A126D607AEF903068A665BCF766281A739E514F377A106A44AAC17EEC3E
```

**Ainda nao aprovado para promover:** dois disparos no replay e nenhuma
validacao fisica de arena, latencia, recall e falsos acionamentos no ESP32.
