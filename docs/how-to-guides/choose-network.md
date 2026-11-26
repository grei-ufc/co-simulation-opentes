# Escolher a rede de comunicação

A rede padrão é a do projeto: o OMNeT++ do TSCC (`NET_BACKEND=omnet`), com o
6TiSCH com TSCH da tese. `TSCC_CANAL`, `TSCC_TOPOLOGIA` e `TSCC_SUBESTACAO`
trocam o canal, a topologia e a subestação; `ideal` e `lossy` servem a testes
rápidos. Qual usar depende da pergunta do estudo.

## Qual backend

| Pergunta | Backend | Variáveis |
|---|---|---|
| o mercado converge e o que ele faz com a tensão, rápido? | `ideal` | nenhuma |
| a negociação sobrevive a mensagens perdidas? | `lossy` | `NET_DROP_PROBABILITY` |
| quanto tempo a negociação gasta numa rede de rádio real? | `omnet` (padrão), `Link_6TiSCH_TSCH` | `TISCH_CELLS` |
| uma rede de medição inteligente atual cabe no orçamento? | `omnet`, `TISCH_MAC=wisun` | `TISCH_RATE_BPS` |
| e com outra tecnologia (PLC, RF Mesh, celular, cabo)? | `omnet` | `TSCC_CANAL`, `TSCC_TOPOLOGIA`, `TSCC_SUBESTACAO` |

`NET_TIME_SCALE=0.02` é o padrão; com `1.0`, cada rodada esperaria em relógio
real todo o atraso da rede, que passa de minutos na 6TiSCH.

## Fatias por enlace na 6TiSCH

```bash
TISCH_CELLS=5 OPENTES_SAIDA=market_6tisch_c5 ./run.sh market
```

Cada fatia leva um quadro de 127 bytes por *slotframe* de 4,04 s. O padrão, 2, é
a calibração com os tempos da tese. O tempo de rede cai na proporção das
fatias, e o ciclo 3 cabe nos 300 s a partir de 4 ou 5 fatias. O console aceita
de 1 a 20.

## Taxa do Wi-SUN FAN

```bash
TISCH_MAC=wisun TISCH_RATE_BPS=150000 OPENTES_SAIDA=market_wisun_150k ./run.sh market
```

`50000` é o rádio da tese. `150000` e `300000` transmitem mais rápido, mas a
sensibilidade do rádio cai e a rede perde enlaces: a 300 kbps a negociação não
fecha na IEEE 13, porque a ligação da subestação ao resto do alimentador passa a
depender de enlaces com erro alto.

## Variações para isolar efeitos

| Variação | Variável | Efeito |
|---|---|---|
| agentes na mesma coordenada ligados por cabo | `TISCH_ARGS='--**.tisch.colocated_wired=true'` | o DSO, o mercado e o concentrador, que na IEEE 13 ficam na subestação, deixam de conversar por rádio |
| tamanhos de mensagem da implementação de referência | `NET_MESSAGE_SIZE=declarado` | a rede recebe as classes de tamanho fixas da tese, em vez do conteúdo serializado |
| tempo limite fixo por rodada | `MARKET_ROUND_TIMEOUT=<segundos>` | substitui o tempo limite calculado pelo backend |

`TISCH_ARGS` passa qualquer parâmetro do `Tisch.ned` para a linha de comando do
OMNeT++, sem editar o arquivo.

## A pasta de saída

Pelo console, a pasta é montada sozinha a partir da configuração
([Usando o console](../tutorials/console.md#uma-pasta-por-configuracao)). Pela
linha de comando, defina `OPENTES_SAIDA`, ou a execução grava em
`output/market/` por cima da rede ideal.
