# Redes de comunicação

Este tutorial roda a mesma negociação com as mensagens passando por três redes
e mostra onde ver o efeito de cada uma. O resultado elétrico é o mesmo nas três;
o que muda é o tempo que a negociação gasta na rede.

O modelo de cada rede está em
[A rede de comunicação](../explanation/communication-network.md).

## 1. 6TiSCH, a rede da tese

```bash
NET_BACKEND=omnet NET_TIME_SCALE=0.02 OPENTES_SAIDA=market_omnet ./run.sh market
```

Na primeira vez, o contêiner `comm` compila o OMNeT++ (alguns minutos). Depois o
`run.sh` espera o servidor anunciar `[6TiSCH] pronto`. A co-simulação leva de 17
a 18 minutos.

`NET_TIME_SCALE=0.02` comprime o atraso de rede antes de aplicá-lo no relógio
real: o tempo de rede continua sendo medido inteiro, mas a espera de verdade é 2%
dele.

## 2. Wi-SUN FAN, o mesmo rádio com acesso por disputa

```bash
NET_BACKEND=omnet NET_TIME_SCALE=0.02 TISCH_MAC=wisun OPENTES_SAIDA=market_wisun_50k ./run.sh market
```

Leva pouco mais de um minuto.

## 3. Canal com perda

```bash
NET_BACKEND=lossy NET_DROP_PROBABILITY=0.05 NET_TIME_SCALE=0.02 OPENTES_SAIDA=market_perda ./run.sh market
```

Cada mensagem se perde com 5% de probabilidade, e os agentes retransmitem quando o
tempo limite da rodada estoura. O tempo limite acompanha `NET_TIME_SCALE`: com
0,02 ele fica em 3 s; com 1,0, em 60 s por perda. Com 5% de perda, a negociação
fecha nas mesmas 42 rodadas, com 18 retransmissões, e o resultado elétrico é
idêntico ao da entrega ideal.

## Onde olhar

Em cada pasta, o `run.json` registra o tempo de rede de cada ciclo e as
retransmissões. Com as redes do OMNeT++, o `run.sh` grava também o
`msg_trace.csv`, com uma linha por mensagem (remetente, destino, tamanho, atraso,
perda). As figuras de comunicação saem com o `./run.sh figuras` apontado para a
pasta:

```bash
OPENTES_SAIDA=market_omnet ./run.sh figuras
```

| Figura | O que mostra |
|---|---|
| `mensagens.png` | tamanho e tempo de recepção de cada mensagem ao longo da co-simulação |
| `mensagens_distribuicao.png` | histograma e distribuição acumulada das mesmas duas grandezas |
| `per_distancia.png` | taxa de erro de pacote contra a distância entre agentes |

## O que esperar

| Rede | Ciclo 3 por rodada | Co-simulação |
|---|---|---|
| 6TiSCH, 2 fatias | 474 a 541 s | ~17 min |
| Wi-SUN FAN, 50 kbps | 5 a 6 s | 1,2 min |

O orçamento de rede de cada ciclo é de 300 s. Na 6TiSCH com 2 fatias, o ciclo 3
passa dele em todas as 42 rodadas; com 5 fatias ou mais, ou com a Wi-SUN, cabe.
A tabela completa, com 1 a 20 fatias e as três taxas do Wi-SUN, está em
[Resultados](../results.md#comparacao-de-redes-6tisch-com-mais-fatias-e-wi-sun-fan).
Para escolher a rede de um estudo, veja
[Escolher a rede de comunicação](../how-to-guides/choose-network.md).
