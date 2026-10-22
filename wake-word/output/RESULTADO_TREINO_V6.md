# Rodada v6: sorteio controlado, sem Thayza

Executada em 2026-10-19. **Candidato nao aprovado. O firmware ativo foi preservado.**
Foi feito um unico sorteio e treinamento, sem repetir seeds para escolher pelo teste.

## Parametros sorteados

| Parametro | Valor |
| --- | --- |
| Seed | 1204528219 |
| Learning rate inicial | 0.0006735104736469071 |
| Dropout | 0.3 |
| Batch | 32 |
| Arquitetura | DS-CNN temporal, MFCC 1 x 13 x 49 x 1 |
| Epocas | 17 executadas; pesos restaurados da epoca 5 |
| Selecao de pesos | Perda de validacao, paciencia 12; limite 65 epocas |
| TFLite INT8 | 12.840 bytes |
| Limiar calibrado | 0.81640625; alta confianca 0.98 |
| Quantizacao de entrada | escala 3.139904022216797; zero point 73 |

Seed, configuracao e manifestos estao em `output_multispeaker_v6_random/`.
O sorteio usa faixas limitadas: LR 0.0003-0.001 log-uniforme, dropout 0.2/0.3/0.4,
batch 32/64. A seed tambem controla augmentation, shuffle e amostragem INT8.
Isso nao garante identidade bit a bit entre plataformas e versoes TensorFlow.

## Dataset e separacao

- Thayza excluida de treino, validacao e teste, incluindo negativos e augmentations.
  A pasta `wakeword_thayza(deprecated)` foi preservada, nao apagada.
- Treino: 7.822 exemplos. Validacao: 34 positivos Lara/Ryam e 540 negativos.
- Teste: 165 positivos (Gabriel 15, Eric INMP441 sessao 002: 150) e 562 negativos.
- Sem `--final-fit`: as vozes/sessoes acima nao participam do ajuste de pesos.
- Positivos com saudacoes continuam positivos, sem filtro lexical destrutivo.
- Mantido o corpus v5 de negativos dificeis, com seus blocos temporais separados.
  Apenas blocos de treino entram nas misturas de ruido e dialogo.
- O limiar foi calibrado na validacao, nunca no teste. A calibracao atual continua
  selecionando pelo limite negativo e pelo silencio, nao otimizando recall positivo.

Essas gravacoes ja foram usadas em diagnosticos anteriores. Blocos temporais da
mesma fonte nao equivalem a novas sessoes; esta rodada nao e certificacao cega.

## Resultados INT8

| Avaliacao | Resultado |
| --- | --- |
| Validacao positiva | 24/34 (70,6%) |
| Validacao negativa | 2/540 falsos positivos (0,37%) |
| Teste Gabriel | 15/15 (100%) |
| Teste Eric, sessao INMP441 reservada | 62/150 (41,3%) |
| Teste positivo agregado | 77/165 (46,7%) |
| Teste negativo | 8/562 falsos positivos (1,42%) |
| Positivos com ruido a 20 dB SNR | 68/165 (41,2%) |
| Positivos com ruido a 10 dB SNR | 44/165 (26,7%) |
| Silencio digital/DC | scores 0, 0, 0 |

Replay temporal com regra 2 de 3 ou um score >= 0.98 e cooldown de 2 segundos:

| Fonte | Tempo avaliado | Eventos, 160 ms | Eventos, 320 ms |
| --- | --- | --- | --- |
| Ambiente | 180 s | 0 | 0 |
| Ambiente calmo | 119,6 s | 0 | 0 |
| Conversas | 180 s | 8 | 1 |
| Musica | 68,2 s | 0 | 0 |
| Silencio absoluto | 180 s | 0 | 0 |

A v5 teve 3 eventos em conversas nos mesmos trechos a 160 ms; a v6 teve 8.
O recall agregado de v5 e v6 nao e diretamente comparavel: os positivos
reservados sao diferentes. Nao houve disparo em silencio neste replay,
mas isso nao garante ausencia de disparos em outros ambientes.

A simulacao temporal em oito recortes por locutor, duas fases e silencio ao redor,
detectou Eric 12/16 e Gabriel 16/16 a 160 ms; a 320 ms, 4/16 e 11/16.
E um diagnostico pequeno com contexto artificial, nao recall fisico do ESP32.
As 11 frases anotadas da Raisa foram detectadas, mas sao exemplos de treino.

## Decisao

**Nao promover.** O sorteio nao resolveu a transferencia para a sessao INMP441
reservada e aumentou disparos em conversas no replay de 160 ms. Aumentar epocas
ou baixar limiar sem novos criterios nao garante melhoria. A proxima etapa util
continua sendo revisar limites da palavra nos recortes e validar novas sessoes
INMP441, com positivos e negativos dos mesmos locutores.

Nao houve gravacao ou teste fisico no ESP32. Nenhum audio original foi alterado.

SHA-256 do candidato:

```text
ae2f31285ba6e0f3762529a9a06d4399344de91c77f100051a581350d4fc70f2
```

## Limpeza e verificacoes

Removidos 176.910.175 bytes (aproximadamente 177 MB): bundles v3 descartados,
rodada v5 invalidada e caches antigos `features.npz`. Lista exata em
`cleanup_v6.json`. Mantidos dataset, codigo-fonte, relatorios, modelos v4/v5
de comparacao, modelo-base valido da mineracao e artefatos ativos v2g.
Os scripts antigos importados pelo treinador ou citados nos fluxos de conversao
foram preservados; nao foram considerados inutilizados apenas pela idade.

19 testes essenciais aprovados (12 de dados, 4 de mineracao, 3 de configuracao).
Auditoria confirmou exclusao completa de Thayza, grupos/hashes reais separados
entre splits, configuracao reproduzivel e SHA-256 ativo inalterado:

```text
AF197A126D607AEF903068A665BCF766281A739E514F377A106A44AAC17EEC3E
```
