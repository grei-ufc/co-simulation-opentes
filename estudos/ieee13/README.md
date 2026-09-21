# Medições do caso IEEE 13

Scripts que produzem os números da montagem e da conferência do caso de mercado
sobre o IEEE 13 barras. Cada um traz no cabeçalho o comando de uso, a partir da
raiz do repositório. Os que usam o OpenDSS rodam no contêiner `grid`; os que usam
o CPLEX, no contêiner `pade`, com o solver montado de `CPLEX_HOME`.

| script | contêiner | o que mede |
|---|---|---|
| `regulador.py` | grid | as três configurações do regulador ao longo do dia (fração fora da faixa A) |
| `dimensionamento.py` | pade + CPLEX | folga residual por limite uniforme por nó e necessidade mínima de armazenamento |
| `factivel_alocacao.py` | pade + CPLEX | se uma alocação candidata de armazenamento zera a violação do dia |
| `conferencia_nao_linear.py` | grid | a programação negociada no fluxo não linear, com o regulador livre e com a derivação fixada pela previsão |
| `convencao_reativo.py` | grid | quanto do excesso de tensão no pior intervalo vem da convenção de reativo da demanda líquida |
| `sigma_perda.py` | nenhum | redução do desvio-padrão da tensão por nível de perda, sobre a saída do `./run.sh loss-multiseed` |

A ordem para refazer tudo depois de mudar as curvas de PV ou a alocação:

1. `python src/simulators/pv_creator.py` e `python src/simulators/gen_ieee13_market.py`, no contêiner `grid` (ver `simulators/grid-opentes`);
2. a sensibilidade diária (`sensitivity.py day`) e a negociação centralizada (`market_opentes.dual --settle-dir`), como em `Docs_Externo/ESTUDO_IEEE13.md`;
3. os scripts desta pasta;
4. `./run.sh market` com `MARKET_NETWORK=13Bus`, `./run.sh integrated` e `./run.sh loss-multiseed`.
