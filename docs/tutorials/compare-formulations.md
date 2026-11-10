# Comparando formulações

Este tutorial reproduz a comparação central do projeto: o mesmo mercado
analisado por barra, como na tese de referência, e por fase, com dois modelos de
inversor. Cada formulação grava numa pasta própria, então as três ficam lado a
lado em `output/`.

## As três formulações

| Formulação | Variáveis | Pasta |
|---|---|---|
| por barra | `MARKET_FASE=0` | `output/market_por_no/` |
| por fase, inversor de quatro fios (padrão) | `MARKET_FASE=1` | `output/market/` |
| por fase, inversor de três fios | `MARKET_DISPOSITIVO=equilibrado` | `output/market_equilibrado/` |

O porquê de cada uma está em [O modelo de mercado](../explanation/market-model.md#a-analise-por-fase).

## 1. Por fase

```bash
./run.sh centralizado && ./run.sh market && ./run.sh figuras
```

## 2. Por barra

```bash
export MARKET_FASE=0
./run.sh centralizado && ./run.sh market && ./run.sh figuras
unset MARKET_FASE
```

Na primeira vez, o `run.sh` gera a matriz de sensibilidade por barra
(`sensitivity_day.npz`).

## 3. Inversor de três fios

```bash
export MARKET_DISPOSITIVO=equilibrado OPENTES_SAIDA=market_equilibrado
./run.sh centralizado && ./run.sh market && ./run.sh figuras
unset MARKET_DISPOSITIVO OPENTES_SAIDA
```

`OPENTES_SAIDA` mantém esta execução fora de `output/market/`. Pelo console, a
pasta é escolhida sozinha.

## O que comparar

Na co-simulação (passada negociada), contando leituras barra-fase-intervalo:

| Formulação | > 1,03 pu | < 0,97 pu | fora da ANSI A | rodadas |
|---|---:|---:|---:|---:|
| por barra | 134 | 18 | 3 | 48 |
| por fase, quatro fios | 9 | 28 | 0 | 42 |
| por fase, três fios | 11 | 26 | 0 | 63 |

Na negociação centralizada, a energia deslocada pelo armazenamento:

| Formulação | Energia deslocada |
|---|---:|
| por barra | 6.903 kWh |
| por fase, quatro fios | 7.527 kWh |
| por fase, três fios | 8.987 kWh |

A figura que mostra a diferença é `tensao_operacao.png` em cada pasta: por barra
ela traz a média das fases, que não passa de 1,03 pu, enquanto as fases
individuais passam. A leitura completa dos números está em
[Resultados](../results.md).
