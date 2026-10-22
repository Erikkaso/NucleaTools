# Treinamento multispeaker v3 - 2026-10-15

Nota de manutencao (2026-10-19): os bundles v3 descartados, incluindo
`output_multispeaker_v3_source_controls`, foram removidos a pedido do usuario.
Este relatorio preserva as metricas historicas; os caminhos de artefatos
abaixo descrevem o estado anterior a limpeza, nao arquivos disponiveis hoje.

Relatorio historico. A aprovacao dos negativos e a inclusao da Raisa foram
tratadas posteriormente na [rodada v4](RESULTADO_TREINO_V4.md).

## Estado

**Candidato experimental REPROVADO para substituir o modelo ativo.**
O treinamento foi executado, mas a qualidade solicitada ainda nao foi atingida.
O firmware e o modelo ativo `v2g_replay_hardneg` nao foram substituidos.

Ultimo candidato completo: `output_multispeaker_v3_source_controls/`.
Os demais diretorios `output_multispeaker_v3*` sao experimentos de desenvolvimento,
nao versoes aprovadas. O bundle em `output_multispeaker_v3_release/` tambem e
experimental e nao deve ser promovido como uma correcao validada.

## Dados e treinamento executado

- 14 vozes reais, descobertas automaticamente nas pastas do dataset.
- 576 recortes reais positivos clean; seus derivados ficam no mesmo grupo de origem.
- 8.058 exemplos de treino apos augmentation e inclusao de negativos.
- Pesos equilibrados por voz e gravacao; sinteticos limitados.
- Negativos de fala, conversas, ambiente, musica, silencio, DC e ruido baixo.
- Augmentation de ganho, deslocamento sem cortar a palavra, ruido e dialogos.
- Deduplicacao: 168 copias PCM identicas descartadas; um positivo com tamanho
  diferente de um segundo foi excluido, sem recortar ou alterar o original.
- Nenhum positivo foi rejeitado pelo criterio de silencio/atividade insuficiente.
  Isso nao comprova que todos os recortes contem a palavra inteira.
- 61 epocas executadas; pesos restaurados da epoca 53 pelo early stopping.
- TFLite FULL INT8: 12.840 bytes, entrada `1 x 13 x 49 x 1`, saida de duas classes.
- Nenhum audio original foi modificado.

## Resultados medidos

O teste negativo reservado teve quatro falsos positivos em 289 janelas.
O limiar de calibracao INT8 foi `0.9921875`, acima do limite recomendado pelo
pipeline. A calibracao exige nenhuma ativacao no ambiente/silencio de validacao,
o que tornou esse candidato pouco sensivel.

Replay diagnostico, aproximadamente tres minutos por arquivo, amostrados em
trechos do inicio, meio e fim, com regra temporal de confirmacao e cooldown:

| Fonte | Eventos, avanco 160 ms | Eventos, avanco 320 ms |
| --- | ---: | ---: |
| Ambiente novo | 3 | 3 |
| Ambiente calmo novo | 0 | 0 |
| Conversa nova | 6 | 6 |
| Musica nova | 1 | 1 |
| Silencio absoluto | 0 | 0 |

Os testes adicionais de silencio digital e DC retornaram score zero.
O teste de ruido a 20 dB de SNR reconheceu 398/576 positivos; a 10 dB,
326/576. Esses positivos participaram do ajuste final: sao diagnosticos de
estresse, **nao recall independente**. Os testes temporais tambem usam recortes
conhecidos, balanceados entre gravacoes, com contexto artificial de silencio.

Os arquivos de diagnostico foram inspecionados durante o desenvolvimento de
modelos; nao constituem uma certificacao cega de generalizacao. A avaliacao
nao reproduz o processamento nem a acustica do ESP32 real.

## Artefatos

- `output_multispeaker_v3_source_controls/nuclea_final.keras`
- `output_multispeaker_v3_source_controls/nuclea_int8.tflite`
- `output_multispeaker_v3_source_controls/data_manifest.json`
- `output_multispeaker_v3_source_controls/data_audit.json`
- `output_multispeaker_v3_source_controls/results.json`
- `output_multispeaker_v3_source_controls/stream_evaluation.json`

SHA-256 do ultimo candidato INT8:

```text
20695aa974a2b122bc3ec24aa313a91777ef610dd55fee6e24c5223be6d8bce6
```

## Pendencias para uma nova promocao

- Confirmar a revisao dos `negative_silence` das novas vozes; ficaram fora do treino.
- Conferir se os recortes INMP441 com baixa deteccao contem a palavra inteira.
- Acrescentar negativos do mesmo microfone/ambiente das vozes positivas, incluindo
  as situacoes de falso acionamento, com rotulos revisados.
- Reservar novas sessoes positivas por pessoa, sem reutiliza-las na augmentation
  de treino, para medir generalizacao real do modelo final.
- So promover depois de reduzir falsos acionamentos e validar latencia, arena
  TFLM e deteccao no ESP32-S3.

O numero de exemplos e a acuracia de treino, isoladamente, nao garantem
eficacia da wake word. Aumentar augmentation sem corrigir esses controles
pode apenas ampliar os mesmos vieses.
