# Redes de comunicação

Este tutorial roda a mesma negociação com as mensagens passando por redes
diferentes e mostra onde ver o efeito de cada uma. O resultado elétrico é o
mesmo em todas; o que muda é o tempo que a negociação gasta na rede.

A rede do projeto é a do TSCC (`teams/tscc-com-opentes`), no OMNeT++, no modo de
consulta por mensagem: cada envio de um agente atravessa os nós, as filas e os
canais da topologia IEEE 13. O modelo de cada canal está em
[A rede de comunicação](../explanation/communication-network.md).

## 1. 6TiSCH com TSCH, o padrão

```bash
./run.sh market
```

É a rede da tese (Melo, 2022) dentro do OMNeT++ do TSCC: canal
`Link_6TiSCH_TSCH`, malha pelo modelo de rádio da tese e subestação pelo rádio.
Na primeira vez, o contêiner `comm-tscc` compila o OMNeT++ (alguns minutos).
Depois o `run.sh` espera a rede anunciar `[TSCC] pronto`. A co-simulação leva
de 17 a 24 minutos.

`NET_TIME_SCALE=0.02`, o padrão, comprime o atraso de rede antes de aplicá-lo
no relógio real: o tempo de rede continua sendo medido inteiro, mas a espera de
verdade é 2% dele.

## 2. Wi-SUN FAN, o mesmo rádio com acesso por disputa

```bash
TISCH_MAC=wisun OPENTES_SAIDA=market_wisun_50k ./run.sh market
```

Leva cerca de 5 minutos.

## 3. Os outros canais e topologias do TSCC

```bash
# o 6TiSCH simplificado do TSCC, em estrela, com a subestação por cabo
TSCC_CANAL=Link_6TiSCH TSCC_TOPOLOGIA=estrela TSCC_SUBESTACAO=cabo \
  MARKET_ROUND_TIMEOUT=6 OPENTES_SAIDA=market_6tisch_estrela ./run.sh market
```

`TSCC_CANAL` aceita qualquer canal do `Profiles.ned` do TSCC (`Link_6TiSCH`,
`Link_WiSUN`, `RFMesh`, `PLC`, `Link_4G`, `Link_5G`, `Link_Wired`...), e vários
separados por vírgula se alternam entre os enlaces. `TSCC_TOPOLOGIA` escolhe
entre a malha da tese e a estrela; `TSCC_SUBESTACAO`, entre o rádio e o cabo para
o concentrador, o DSO e o mercado. Nos canais com perda por distância, cada
mensagem perdida espera o tempo limite da rodada antes da retransmissão:
`MARKET_ROUND_TIMEOUT=6` encurta essa espera em relógio, sem mudar o resultado.
O levantamento dos enlaces simulados fica em `output/<pasta>/tscc_links.csv`.

## 4. Entrega ideal e canal com perda

```bash
NET_BACKEND=ideal OPENTES_SAIDA=market_ideal ./run.sh market
NET_BACKEND=lossy NET_DROP_PROBABILITY=0.05 OPENTES_SAIDA=market_perda ./run.sh market
```

A entrega ideal leva cerca de um minuto e serve de controle. No canal com perda,
cada mensagem se perde com a probabilidade dada, e os agentes retransmitem
quando o tempo limite da rodada estoura (3 s com `NET_TIME_SCALE=0.02`). Com 5%
de perda, a negociação fecha nas mesmas 42 rodadas, com 18 retransmissões, e o
resultado elétrico é idêntico ao da entrega ideal.

## 5. Referência: o servidor 6TiSCH da tese

```bash
COMM=tese OPENTES_SAIDA=market_tese ./run.sh market
```

`COMM=tese` troca a rede do projeto pelo servidor 6TiSCH de `temp/comm-opentes`,
que implementa a rede da tese diretamente. Ele fica como referência de
validação: com os canais da tese e a mesma topologia de rádio
(`TSCC_ENLACES=/grid-data/13Bus/tisch_links.csv`), a rede do projeto dá as mesmas
42 rodadas, os mesmos tempos de ciclo e o mesmo resultado elétrico.

## Onde olhar

Em cada pasta, o `run.json` registra o tempo de rede de cada ciclo e as
retransmissões. Com as redes do OMNeT++, o `run.sh` grava também o
`msg_trace.csv`, com uma linha por mensagem (remetente, destino, tamanho, atraso,
perda). As figuras de comunicação saem com o `./run.sh figuras` apontado para a
pasta:

```bash
OPENTES_SAIDA=market ./run.sh figuras
```

| Figura | O que mostra |
|---|---|
| `mensagens.png` | tamanho e tempo de recepção de cada mensagem ao longo da co-simulação |
| `mensagens_distribuicao.png` | histograma e distribuição acumulada das mesmas duas grandezas |
| `per_distancia.png` | taxa de erro de pacote contra a distância entre agentes, do `tisch_links.csv` do caso |

## O que esperar

Medido em 26/11/2026, na rede do projeto, com o mercado padrão (42 rodadas e o
mesmo resultado elétrico em todas):

| Rede | Ciclo 3 por rodada | Mensagens perdidas e recuperadas | Co-simulação |
|---|---|---|---|
| 6TiSCH com TSCH, malha, rádio (padrão) | 474 a 542 s | 0 a 7 de cerca de 3.000 | 17 a 24 min |
| Wi-SUN FAN, 50 kbps | 5,3 a 5,9 s | 5 | 5 min |
| 6TiSCH simplificado, estrela, cabo | 3 ms | 436 de 3.593 (12%) | 22 min |
| Entrega ideal | 0 | 0 | 1 min |

O orçamento de rede de cada ciclo é de 300 s. No 6TiSCH com TSCH e 2 fatias, o
ciclo 3 passa dele em todas as 42 rodadas; com 5 fatias ou mais, com o Wi-SUN, ou
com a subestação por cabo, cabe.
A tabela completa, com 1 a 20 fatias e as três taxas do Wi-SUN, está em
[Resultados](../results.md#comparacao-de-redes-6tisch-com-mais-fatias-e-wi-sun-fan).
Para escolher a rede de um estudo, veja
[Escolher a rede de comunicação](../how-to-guides/choose-network.md).
