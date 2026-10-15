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
| `wakeword_ryam` | `ryam.ogg` |
| `wakeword_sarah` | `sarah.ogg` |
| `wakeword_talles` | `talles.ogg` e `sara.ogg` (continuacao de Talles, nao Sarah) |
| `wakeword_valentina` | `valentina.ogg` |

O filtro gera uma copia adicional e preserva o original. A triagem por energia
nao mede SNR real, nao separa vozes e nao recupera saturacao.
Separe treino e avaliacao por gravacao de origem, mantendo suas variacoes juntas.
A inclusao desses falantes no treinamento ainda depende da configuracao do
treinador; gerar augmentation nao atualiza automaticamente o modelo do ESP32.
