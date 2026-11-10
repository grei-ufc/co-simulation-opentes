# Primeira Simulação

Este passo a passo roda o estudo completo do cenário padrão: análise por fase,
inversor de quatro fios, regulador seguindo a previsão e entrega ideal das
mensagens entre os agentes. Pressupõe a [Instalação](installation.md) feita e o
`CPLEX_HOME` definido.

## 1. A negociação centralizada

```bash
./run.sh centralizado
```

Roda a decomposição dual num laço único, sem agentes nem mosaik, e grava a
liquidação. Leva cerca de um minuto. Na primeira vez, antes de começar, o
`run.sh` gera a matriz de sensibilidade por fase
(`simulators/grid-opentes/src/data/13Bus/sensitivity_fase.npz`).

O terminal mostra uma linha por rodada, com o desacordo entre concentrador e
operador, o preço sombra máximo e a tensão mínima e máxima prevista. A última
linha deve ser:

```
convergiu em 42 rodadas (|x-y|/Pmax = 9.05e-04 <= 1e-03)
```

## 2. A co-simulação

```bash
./run.sh market
```

Sobe os contêineres na ordem certa e roda duas passadas sobre a mesma demanda
realizada:

- **baseline**: os prosumidores executam a programação que propuseram, sem
  negociação;
- **negociado**: os agentes negociam no primeiro passo do mosaik e, nos 96
  passos de 15 minutos seguintes, o operador confere e corrige o desvio da
  demanda realizada.

Leva cerca de um minuto com a entrega ideal. Ao fim, `output/market/` tem
`result_baseline.csv`, `result_negociado.csv` e `run.json`.

## 3. As figuras

```bash
./run.sh figuras
```

Grava as figuras em `output/market/figuras/`. Para começar, abra
`tensao_operacao.png`, a tensão de cada fase de cada barra ao longo do dia na
co-simulação: na análise por fase, só 9 leituras passam de 1,03 pu, nenhuma
acima de 1,031 pu.

## O que conferir

| Saída | Valor esperado |
|---|---|
| rodadas da negociação | 42 |
| leituras de fase acima de 1,03 pu (negociado) | 9 |
| leituras abaixo de 0,97 pu (negociado) | 28 |
| leituras fora da ANSI C84.1 faixa A (negociado) | 0 |

Os números vêm de [Resultados](../results.md), que também traz a comparação
com a análise por barra. A lista completa de arquivos está em
[Arquivos de saída](../reference/output-files.md).

## Próximos passos

- [Usando o console](../tutorials/console.md): o mesmo fluxo pelo menu, com a
  configuração guardada entre sessões.
- [Comparando formulações](../tutorials/compare-formulations.md): por barra,
  por fase e inversor de três fios.
- [Redes de comunicação](../tutorials/communication-networks.md): a mesma
  negociação com as mensagens passando pela 6TiSCH ou pela Wi-SUN FAN.
