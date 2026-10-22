# Treinamento multispeaker v5: negativos dificeis

Relatorio consolidado em 2026-10-16. **Experimental, nao aprovado para o ESP32.**
O modelo ativo `v2g_replay_hardneg` nao foi alterado.

Manutencao em 2026-10-19: a rodada invalidada `output_multispeaker_v5_seed` foi
apagada. Os caches antigos de features tambem foram removidos; modelos validos,
manifestos e metricas foram preservados. Thayza e excluida de toda a nova rodada
v6; a politica descrita abaixo e o historico da v5.

## Dados e protocolo

- 14 vozes humanas no treino. Thayza exclusivamente no teste, com 19 positivos
  limpos; nenhuma variacao dela no treino, nas misturas ou calibracao INT8.
- `wakeword_thayza(deprecated)` e normalizada como identidade `thayza`, sem
  renomear a pasta. Frases como `Oi Nuclea` e `Bom dia Nuclea` continuam positivas.
- Treino: 8.902 exemplos; validacao: 538 negativos; teste: 19 positivos e
  545 negativos. Augmentations nao equivalem a novas pronuncias independentes.
- Positivos recebem variacao de ganho, deslocamento seguro e mistura de ruido/
  dialogo de fontes de treino. Silencio e DC entram como negativos explicitos.
- Um positivo Eric de 21.559 amostras foi excluido por nao ter um segundo;
  o original foi preservado, sem recorte arbitrario ou conversao em negativo.

Cada fonte de `background_test2` foi dividida em blocos 60/20/20, com margem
de dois segundos antes da validacao e do teste. Apenas o bloco de treino foi
pontuado pelo modelo-base. Foram exportados 485 negativos dificeis e 127 de
cobertura para treino, mais 256 de validacao e 256 de teste, sem mineracao
por score nos blocos reservados. Apenas negativos de treino compoem misturas.

As fontes herdam o rotulo negativo do corpus existente; nao houve nova escuta
ou transcricao individual nesta etapa. Os blocos sao da mesma gravacao e as
fontes ja foram inspecionadas em diagnosticos anteriores: nao sao teste cego.
Thayza tambem apareceu em rodadas anteriores, embora nao nesta rodada.

## Modelo e calibracao

- Rede temporal DS-CNN, entrada MFCC `1 x 13 x 49 x 1`, saida `[negativo, Nuclea]`.
- 63 epocas executadas, pesos restaurados da epoca 55 por perda de treino;
  teste nao selecionou pesos nem limiar.
- TFLite INT8: 12.840 bytes, escala de entrada `3.1069743633270264`, zero point `76`.
- Limiar `0.87109375`, alta confianca `0.98`; confirmacao temporal 2 de 3 ou
  um score de alta confianca.
- Calibracao somente nos negativos de validacao: 5/538 falsos positivos por
  janela (0,93%). A meta de 1% nao e uma garantia em dados novos.

SHA-256 do candidato `output_multispeaker_v5_hardneg/nuclea_int8.tflite`:

```text
59b705265df4eb114d56c9086c9823d8e05798b06492a8429229557e77838ff0
```

## Resultados medidos

| Avaliacao INT8 | Resultado |
| --- | --- |
| Thayza, recortes limpos reservados | 11/19 detectados (57,9%) |
| Negativos de teste, por janela | 8/545 falsos positivos (1,47%) |
| Silencio/DC sinteticos | 0/3 acionamentos |
| Thayza + ruido a 20 dB SNR | 13/19 detectados (68,4%) |
| Thayza + ruido a 10 dB SNR | 6/19 detectados (31,6%) |
| Simulacao temporal Thayza, avanco 160 ms | 7/16 tentativas detectadas |
| Simulacao temporal Thayza, avanco 320 ms | 6/16 tentativas detectadas |

O ruido pode alterar o score para cima ou para baixo; 20 dB superar o recorte
limpo nao prova maior robustez. A simulacao temporal usa oito clipes conhecidos,
duas fases de janela e silencio ao redor; nao mede recall real do hardware.

Replay de negativos: mesmos trechos para v5 e v4, com confirmacao temporal.
O v4 foi recalibrado na mesma validacao, para comparacao negativa equivalente.

| Fonte | Duracao avaliada | v5 eventos 160/320 ms | v4 recalibrado 160/320 ms |
| --- | --- | --- | --- |
| Ambiente | 180 s | 0 / 0 | 1 / 0 |
| Ambiente calmo | 119,6 s | 0 / 0 | 0 / 0 |
| Conversas | 180 s | 3 / 1 | 5 / 3 |
| Musica | 68,2 s | 0 / 0 | 0 / 0 |
| Silencio absoluto | 180 s | 0 / 0 | 0 / 0 |

Sao aproximadamente 12,1 minutos amostrados, nao as gravacoes completas.
Com os limiares originais do v4, seriam 11/7 eventos no total; recalibrado,
6/3. O v5 teve 3/1: melhora nesse diagnostico, mas ainda ha falsos acionamentos.
Nao compare recall positivo com v4 como teste independente: v4 treinou Thayza.

As 11 amostras anotadas da Raisa, incluindo saudacoes, foram detectadas.
Todas sao de treino: isso verifica preservacao dos exemplos, nao generalizacao
para frases novas. A posicao exata da palavra nao foi anotada automaticamente.

## Decisao e proximos dados

**Nao promover.** A reducao de falsos acionamentos veio com recall insuficiente
na voz reservada. Silencio nao disparou nos testes realizados, mas nao ha
garantia para qualquer ambiente. Nao se deve baixar o limiar apenas para
compensar as falhas, pois as conversas ainda geram scores altos.

O proximo passo util e coletar novas sessoes INMP441 de varias pessoas,
com a palavra isolada e em frases, anotando inicio/fim da palavra. Reservar
sessoes inteiras para teste e coletar falas parecidas sem a wakeword dos mesmos
locutores ajuda a separar voz, frase e ambiente da palavra-alvo. A validacao
final tambem precisa de replay longo e medicoes no ESP32 real.

## Rastreabilidade

- Modelo-base valido: `output_multispeaker_v5_seed_holdout`, hash
  `78ee283e163a21588e9dbda8bbbcb6bf6d4a944d081c4fbb4c02736e20bbad6f`.
- `output_multispeaker_v5_seed` e uma rodada invalidada por identificar a pasta
  renomeada como outra voz. Nao foi usada na mineracao nem no ajuste final.
- Corpus: `dataset/mined_hard_negative_v5/manifest.json`, com hashes e intervalos.
- Auditoria: `output_multispeaker_v5_hardneg/data_audit.json` e `data_manifest.json`.
- Metricas: `output_multispeaker_v5_hardneg/results.json` e `stream_evaluation.json`.
- 16 testes essenciais de separacao, silencio, calibracao e mineracao aprovados.
- Sem gravacao do firmware ou validacao fisica nesta rodada.
