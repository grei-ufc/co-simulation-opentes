# CLI

O ponto de entrada é o `run.sh`, na raiz. Com o link da
[Instalação](../getting-started/installation.md#o-comando-opentes-opcional), o
mesmo script responde como `opentes`, de qualquer pasta.

## Uso

```text
opentes             console interativo, com menu
opentes <comando>
opentes --help      lista os comandos e as variáveis mais usadas
```

Sem argumentos, num terminal interativo, abre o console
([Usando o console](../tutorials/console.md)). `opentes console` faz o mesmo
explicitamente.

## Comandos

| Comando | O que faz | Grava | Tempo |
|---|---|---|---|
| `market` | co-simulação completa, em duas passadas sobre a mesma demanda realizada: `baseline` (programação dos prosumidores, sem mecanismo) e `negociado` (negociação multiagente e fase de operação) | `result_baseline.csv`, `result_negociado.csv`, `run.json` | ~1 min; 17 a 18 com a 6TiSCH |
| `centralizado` | a mesma negociação, sem agentes nem mosaik, mais a liquidação | `figuras.npz`, `history.json`, `dlmp.csv`, `flexibility.csv`, `transactions.csv`, `market_series.csv` | ~1 min |
| `figuras` | as figuras a partir das saídas dos dois comandos acima | `figuras/` | segundos |
| `caso` | regenera o caso IEEE 13 e as duas matrizes de sensibilidade | `simulators/grid-opentes/src/data/13Bus/` | ~1 min |

`market` e `centralizado` exigem o `CPLEX_HOME` e geram a matriz de
sensibilidade da formulação em uso, se ela faltar.

## Pasta de resultados

| Condição | Pasta |
|---|---|
| `OPENTES_SAIDA` definida | `output/$OPENTES_SAIDA/` |
| `MARKET_FASE=1` (padrão) | `output/market/` |
| `MARKET_FASE=0` | `output/market_por_no/` |

## Exemplos

```bash
export CPLEX_HOME=$HOME/IBM/CPLEX_Studio2211/cplex
opentes centralizado && opentes market && opentes figuras
MARKET_FASE=0 opentes market
NET_BACKEND=omnet NET_TIME_SCALE=0.02 opentes market
NET_BACKEND=omnet NET_TIME_SCALE=0.02 TISCH_MAC=wisun OPENTES_SAIDA=market_wisun_50k opentes market
```

Qualquer variável de [Variáveis de ambiente](environment-variables.md) vale na
frente do comando.

## Como o `run.sh` executa

- Antes e depois de cada comando, derruba os contêineres e a rede do compose
  (`docker compose down --remove-orphans`).
- No `market`, sobe `comm` (só com `NET_BACKEND=omnet`), depois `grid`,
  `collector` e `pade`, e só então o `mosaik`. Espera cada um pelo log, nunca
  por TCP.
- Ao final, devolve a posse de `output/` e do caso a quem rodou o script, porque
  os contêineres gravam como root.
