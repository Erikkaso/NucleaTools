# Gravacoes reais revisadas

Os candidatos mantidos em `review/` foram validados manualmente pelo usuario.
Os WAVs preparados usam PCM16, mono, 16 kHz e janelas de um segundo.

## Arquivos mantidos

- `review/`: recortes originais selecionados, preservados sem alteracao.
- `clean/`: copias dos positivos selecionados.
- `augmented/`: variacoes e copias filtradas quando indicadas pela triagem.
- `negative_silence/`: recortes de ambiente/silencio; conferir antes de rotular.
- `manifest.csv`: origem, tempos e metodo de extracao dos candidatos iniciais; pode listar recortes removidos na revisao.
- `metadata.csv`: exemplos preparados e grupos de origem usados no treinamento.
- `augmentation_report.json`: contagens e diagnosticos de ruido por recorte.

## Origem das gravacoes

| Pasta | Gravacoes |
| --- | --- |
| `wakeword_alexesm` | `alexes.ogg` |
| `wakeword_gabriel` | `gabriel.ogg` |
| `wakeword_ivanildo` | `ivanildo.ogg` |
| `wakeword_lara` | `lara.ogg` |
| `wakeword_raisa` | `raisa.ogg` (estrutura `positive/` com manifesto) |
| `wakeword_ryam` | `ryam.ogg` |
| `wakeword_sarah` | `sarah.ogg` |
| `wakeword_talles` | `talles.ogg` e `sara.ogg` (continuacao de Talles, nao Sarah) |
| `wakeword_valentina` | `valentina.ogg` |

O filtro gera uma copia adicional e preserva o original. A triagem por energia
nao mede SNR real, nao separa vozes e nao recupera saturacao.
Separe treino e avaliacao por gravacao de origem, mantendo suas variacoes juntas.
O treinador `train_models/train_multispeaker_v3.py` descobre essas pastas
automaticamente. O treinador antigo v2 usa uma lista fixa de falantes.
Gerar augmentation ou treinar nao atualiza automaticamente o modelo do ESP32.

Na politica v5, `wakeword_thayza(deprecated)` e reservada exclusivamente para
teste: 19 positivos limpos, sem suas augmentations no treino ou calibracao INT8.
O sufixo `(deprecated)` nao altera a identidade do locutor no pipeline.
Na rodada v6, `--exclude-speaker thayza` substitui essa reserva por exclusao
completa: nem treino, nem validacao, nem teste. Os arquivos originais permanecem.
Na v7 essa exclusao continua. Apos a revisao manual, use `--reviewed-clean-only`:
augmentations antigas nao refletem os recortes removidos e nao devem ser usadas.
As variantes novas ficam no output da rodada, somente para exemplos de treino.
Copias clean cujo `parent_file` declarado foi apagado tambem sao ignoradas;
nao regenere positivos automaticamente a partir dos antigos candidatos review.
Positivos com frases, como `Oi Nuclea` ou `Bom dia Nuclea`, continuam positivos.
O manifesto preserva `original_phrase` quando a anotacao existe; isso nao
equivale a uma verificacao automatica da posicao exata da wakeword no recorte.

Em 2026-10-15 o usuario confirmou a revisao dos negativos. O parametro
`--include-reviewed-negatives` inclui os WAVs existentes em `negative_silence/`
ou `negative/`, sem reconstruir arquivos excluidos. Para a Raisa estao presentes
11 originais, 11 copias tratadas, 66 augmentations e 22 negativos; os positivos
derivam de 11 ocorrencias da mesma gravacao, nao de 88 pronuncias independentes.
