# Rodada v4: negativos revisados e Raisa

## Dados incluidos

- Usuario aprovou o uso dos `negative_silence` como negativos.
- 68 negativos existentes de nove pastas, incluindo 22 da Raisa.
- Variacoes de ganho de -6, +6 e +12 dB desses negativos, somente no treino.
- Positivos e negativos da mesma origem mantem o mesmo grupo de gravacao.
- Raisa: 11 originais, 11 tratados e 66 aumentados existentes; todos derivados
  de 11 ocorrencias na mesma gravacao. Uma copia PCM identica foi deduplicada.
- Arquivos apagados na revisao continuam apagados, mesmo quando o manifesto os lista.
- Nenhum WAV, manifesto-fonte ou modelo ativo foi alterado.

Treino final: 15 vozes, 8.450 exemplos, 40 epocas, pesos restaurados da epoca 32.
Modelo temporal FULL INT8 com 12.840 bytes, sem mudanca no contrato MFCC.

## Resultado e limites

**Ainda reprovado para substituir o modelo ativo:** ha falsos acionamentos
em cenas novas. Nao houve promocao automatica nem alteracao do firmware.

Limiar calibrado: `0.84765625`; alta confianca: `0.98`.
Teste negativo reservado: quatro falsos positivos em 289 janelas.
Silencio digital e DC: score zero.

Replay de trechos do inicio/meio/fim, cerca de tres minutos por fonte:

| Fonte | Eventos a 160 ms | Eventos a 320 ms |
| --- | ---: | ---: |
| Ambiente novo | 8 | 4 |
| Ambiente calmo novo | 0 | 0 |
| Conversa nova | 10 | 8 |
| Musica nova | 3 | 2 |
| Silencio absoluto | 0 | 0 |

Em teste de estresse, 500/587 positivos foram reconhecidos a 20 dB de SNR
e 443/587 a 10 dB. Esses positivos foram usados no treinamento: os numeros
nao sao uma estimativa independente de generalizacao. O limiar tambem difere
do v3; nao atribua variacoes de metricas somente a inclusao dos novos dados.

Os arquivos de diagnostico ja foram inspecionados em rodadas anteriores.
O replay nao e uma certificacao cega nem uma validacao no ESP32 real.

## Artefatos

Pasta: `output_multispeaker_v4_reviewed/`.

- `nuclea_final.keras`: pesos treinados.
- `nuclea_int8.tflite`: candidato INT8, experimental.
- `data_manifest.json`: exemplos efetivamente usados, rotulos e grupos.
- `data_audit.json`: confirmacao dos negativos, contagens e exclusoes.
- `results.json`: calibracao, metricas e bloqueio de promocao.
- `stream_evaluation.json`: eventos por cenario, estresse e confirmacao temporal.

SHA-256 do TFLite:

```text
eb36cfe1fcd27a457d9925018d953789113f892f6ec5c670119cd4446a619915
```

O proximo ajuste de dados deve atacar os falsos acionamentos em cenarios
variados e preservar novas gravacoes independentes para avaliacao. Repetir
augmentation dos mesmos recortes nao garante resolver esse problema.
