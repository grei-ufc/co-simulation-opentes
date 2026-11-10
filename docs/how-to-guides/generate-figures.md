# Gerar as figuras

```bash
./run.sh figuras
```

Desenha as figuras a partir dos resultados da pasta da configuração atual e as
grava em `<pasta>/figuras/`. Roda na imagem `opentes/mosaik` e leva segundos.

## De qual execução

As figuras usam o que estiver na pasta. Cada uma é pulada se o arquivo de que
depende faltar:

| Figuras | Precisam de | Gerado por |
|---|---|---|
| tensão e demanda sem armazenamento e negociadas, preço sombra, armazenamento de rede, composição, negociação, convergência | `figuras.npz` | `./run.sh centralizado` |
| mercados por nó, preços dos mercados | `market_series.csv` | `./run.sh centralizado` |
| tensão e demanda na operação | `result_negociado.csv` | `./run.sh market` |
| mensagens | `msg_trace.csv` | `./run.sh market` com `NET_BACKEND=omnet` |
| erro de pacote por distância | `tisch_links.csv` do caso | o servidor de rede, com `NET_BACKEND=omnet` |

Por isso o fluxo completo é `centralizado`, `market` e `figuras`, nessa ordem.

## De outra pasta

```bash
OPENTES_SAIDA=market_omnet ./run.sh figuras
MARKET_FASE=0 ./run.sh figuras          # output/market_por_no/
```

## Os arquivos

| Arquivo | Conteúdo |
|---|---|
| `tensao_sem_armazenamento.png` | tensão de cada barra (ou fase) ao longo do dia, sem armazenamento |
| `demanda_sem_armazenamento.png` | demanda líquida de cada barra, sem armazenamento |
| `preco_sombra.png` | o preço sombra por barra (ou por fase) e intervalo |
| `armazenamento_rede.png` | o despacho do armazenamento de rede |
| `tensao_negociada.png`, `demanda_negociada.png` | as mesmas grandezas com a programação negociada |
| `tensao_dois_horarios.png` | a tensão de cada barra em dois horários, com e sem armazenamento |
| `composicao_no_<barra>.png` | carga, armazenamento e tensão de uma barra |
| `negociacao_no_<barra>.png` | a demanda líquida de uma barra ao longo do dia, como o concentrador e o operador a veem a cada rodada |
| `convergencia.png` | a demanda programada pelo concentrador e pelo operador numa barra e horário, rodada a rodada, até coincidirem |
| `tensao_operacao.png`, `demanda_operacao.png` | a co-simulação, a cada 15 min |
| `mercados_por_no.png`, `precos_mercados.png` | energia e preço nos mercados bilateral e spot |
| `mensagens.png`, `mensagens_distribuicao.png` | tamanho e tempo de recepção das mensagens |
| `per_distancia.png` | taxa de erro de pacote contra a distância |

Na análise por fase, as figuras de tensão, preço sombra e armazenamento de rede
têm um painel por fase. O formato de cada figura segue o das figuras de
resultado da tese de referência, para que possam ser postas lado a lado.
