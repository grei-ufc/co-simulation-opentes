# market-opentes

Camada de mercado transativo do OpenTES: modelos de otimizacao e a decomposicao
dual da fase de programacao da operacao, portados da tese de doutorado de Lucas
S. Melo (2022) e do repositorio `market-simulation`.

Este pacote roda o mecanismo de forma **centralizada**, sem PADE e sem Mosaik.
E de proposito: separa o risco numerico (a decomposicao converge? em quantas
rodadas?) do risco de comunicacao, que so aparece quando os agentes entram.

| arquivo | conteudo |
|---|---|
| `data_prep.py` | recorta um dia de perfis do SimBench e de precos do Nordpool, mais um reservatorio de dias alternativos |
| `config.py` | monta o caso: nos, concentradores e dispositivos de armazenamento |
| `scenarios.py` | amostragem e reducao de cenarios por distancia de Kantorovich (subsecao 6.1.4.1) |
| `optimization.py` | modelos do prosumidor (Eq. 6.1-6.9), concentrador (6.25-6.26) e DSO (6.27-6.29) |
| `dual.py` | laco de decomposicao dual e atualizacao do preco sombra (Eq. 6.30) |
| `settlement.py` | registro de transacoes, preco locacional (DLMP) e valoracao da flexibilidade |
| `plot_convergence.py` | figura de convergencia (residuo primal e preco sombra) |

O modelo do prosumidor e ESTOCASTICO e parametrizado pelo numero de cenarios:
`--scenarios 1` e o deterministico (previsao unica), `--scenarios 3` produz os 9
cenarios de preco-potencia da tese. PySP nao e necessario: com nove cenarios a
forma extensiva e um unico MIQP escrito direto em Pyomo.

## Dependencias e o solver

Python: `pyomo`, `numpy`, `pandas`, `matplotlib` (ver `pyproject.toml`). Todas
entram na imagem `opentes/pade:local`.

**O solver nao entra no repositorio nem na imagem.** O padrao e o IBM ILOG CPLEX,
cuja licenca academica e nominal e intransferivel: distribui-la junto do codigo
violaria os termos, e este repositorio e publico. Quem clonar o projeto recebe
todo o codigo e nenhum solver.

### O que funciona sem o CPLEX

| Componente | Sem solver |
|---|---|
| Conversao da rede (`gen_market_grid.py`) | funciona |
| Sensibilidade dV/dP (`sensitivity.py`) | funciona |
| Perfis e cenarios (`data_prep.py`, `scenarios.py`) | funciona |
| Cenarios `ieee13`, `star`, `integrated` do repositorio | funcionam (nao usam otimizacao) |
| Modelos do prosumidor, concentrador e DSO | **nao rodam** |
| `dual.py` e o cenario `market` | **nao rodam** |
| Figuras a partir de historicos ja gravados | funcionam |

Ou seja, a parte eletrica e de comunicacao do OpenTES nao depende disso; a
camada de mercado depende inteiramente.

### Como obter o CPLEX

1. IBM Academic Initiative (gratuito para uso academico, requer conta
   institucional): https://www.ibm.com/academic/topic/data-science
   Baixe o **ILOG CPLEX Optimization Studio** para Linux x86-64 e instale, por
   exemplo em `~/IBM/CPLEX_Studio2211`.
2. A versao `pip install cplex` NAO serve: a Community Edition e limitada a
   1000 variaveis e 1000 restricoes, e o modelo do DSO tem cerca de 7 mil
   variaveis so na malha de 74 nos por 96 periodos.
3. Aponte o caminho antes de rodar:

```bash
export CPLEX_HOME=$HOME/IBM/CPLEX_Studio2211/cplex     # para o docker compose
export MARKET_SOLVER_PATH=$CPLEX_HOME/bin/x86-64_linux/cplex   # para rodar fora do container
```

O `docker-compose.yaml` monta `${CPLEX_HOME}` em `/opt/cplex:ro` dentro do
container `pade-market`. Sem a variavel, o compose monta um caminho inexistente
e o cenario de mercado falha ao resolver o primeiro modelo, com mensagem do
Pyomo dizendo que o executavel nao foi encontrado.

### Alternativas livres, e por que nao sao o padrao

Foi medido, nos modelos deste pacote e em porte real:

| modelo | HiGHS via Pyomo | CPLEX |
|---|---|---|
| QP 74x96 (DSO, concentrador) | falha: a interface do Pyomo nao aceita objetivo quadratico | 1,7 s |
| MILP 20x96 | 0,70 s | 0,22 s |
| MIQP 20x96 (prosumidor) | falha | 1,5 s |

A limitacao e da interface Pyomo-HiGHS, nao do HiGHS, que resolve QP convexo. As
saidas seriam reformular o objetivo quadratico como linear com desvios em modulo
(o que muda a formulacao da tese e a convergencia da decomposicao dual, que se
apoia na convexidade estrita), trocar Pyomo por cvxpy/OSQP nesses dois modelos,
ou usar IPOPT ou Gurobi academico, que suportam QP pelo Pyomo e nao foram
testados aqui. Trocar o solver e uma variavel de ambiente:

```bash
export MARKET_SOLVER=ipopt
```

## Como rodar

```bash
# 1. perfis do dia. So e preciso rodar para REGERAR os dados: os CSVs de
#    entrada ja estao versionados em data/, e este e o unico passo que depende
#    do repositorio market-simulation (SimBench e Nordpool).
python -m market_opentes.data_prep --market-simulation ../../../market-simulation

# 2. tensao base e sensibilidade dV/dP do dia (precisa do OpenDSS: container grid)
docker run --rm -v "$PWD/../grid-opentes/src:/app/src" -v "$PWD:/market" \
  opentes/grid:local python /app/src/simulators/sensitivity.py day \
  --load-csv /market/data/load_kw.csv --pv-csv /market/data/pv_kw.csv \
  --out /market/data/sensitivity_day.npz

# 3. decomposicao dual
python -m market_opentes.dual --config data/config.json \
  --alpha 0.6 --eps 1e-3 --scenarios 3 --out data/history.json

# 3b. fase de operacao (a cada 15 min, sobre o desvio da previsao)
python -m market_opentes.operation --config data/config.json \
  --realized-day 9 --out data/operation_log.json

# 3c. liquidacao: transacoes, DLMP e flexibilidade
python -m market_opentes.dual --config data/config.json --settle-dir data

# 4. figuras
python -m market_opentes.plot_results --output-dir ../../output/market
python -m market_opentes.plot_convergence data/history.json -o data/convergencia.png
```

> **Sobre o DLMP**: com o `Ck = 1` da tese, lambda NAO esta em unidade monetaria,
> e as colunas de preco saem com o sufixo `_signal` em vez de `_eur_mwh`. Calibre
> `MARKET_CK_EUR` (em EUR/kW^2.h) para obter preco. Ver docs/MERCADO.md.

## Resultados medidos na rede MVLV75

A carga base ja viola por conta propria: 331 pontos abaixo de 0,97 pu, com minima
de 0,9410 pu no intervalo 71, ou seja **17:45**, que e exatamente o horario
critico de subtensao que a tese relata (entre 17:45 e 19:15). O DSO elimina a
violacao ja na primeira rodada; as rodadas seguintes negociam quem paga o ajuste.

Verificado com FLUXO DE POTENCIA COMPLETO no OpenDSS, nao com o modelo
linearizado que a negociacao usa para decidir:

| caso | faixa de tensao | abaixo de 0,97 pu |
|---|---|---:|
| sem negociacao | 0,93803 a 1,02503 pu | 336 |
| negociado, sem margem de seguranca | 0,96924 a 1,02361 pu | 104 |
| **negociado** | **0,97020 a 1,02330 pu** | **0** |

A linha do meio e o motivo de existir a `V_BACKOFF`: o otimizador do DSO cola a
solucao exatamente no limite e fica sem margem contra o erro da propria
linearizacao (1e-4 a 6e-4 pu). Com uma margem de 1e-3 pu aplicada aos limites
dentro do modelo, a promessa se confirma no fluxo nao linear.

Convergencia, medida pelo RESIDUO PRIMAL e nao pelo criterio da tese:

| caso | rodadas | residuo final | lambda final |
|---|---:|---:|---:|
| 1 cenario (deterministico), alpha 0,6 | >60 | 0,0041 kW | 5,133 |
| 9 cenarios (estocastico), alpha 0,6 | 30 | 0,0016 kW | 4,221 |
| 1 cenario, passo decrescente alpha0 2,0 | 45 | 0,0222 kW | 5,116 |

Duas leituras. O prosumidor que decide sob incerteza programa de forma menos
agressiva, estressa menos a rede e converge mais rapido. E o passo decrescente
**parece** melhor pelo criterio da tese (45 rodadas contra mais de 60) e e cinco
vezes pior pelo residuo primal: o teste `|dlambda| <= eps` disparou porque o
passo encolheu para 2,0/45, nao porque as partes chegaram a acordo. Compare
sempre pelo residuo.

### Passo do subgradiente

| alpha | rodadas | residuo final | comportamento |
|---:|---:|---:|---|
| 0,25 | 37 | 0,0035 kW | decai, razao 0,875 |
| 0,50 | 20 | 0,0018 kW | decai, razao 0,75 |
| 0,60 | 17 | 0,0016 kW | decai, razao 0,70 |
| 0,65 | >40 | 0,0091 kW | estaciona acima da tolerancia |
| 0,75 | >40 | 2,14 kW | ciclo limite |
| 2,00 | >40 | 4,00 kW | satura em 2x o limite de potencia |

Com passo constante o subgradiente converge a uma VIZINHANCA do otimo cujo raio
cresce com o passo. Acima de 0,6 o raio ultrapassa a tolerancia. `--step-rule
diminishing` (alpha/w) remove o precipicio: com alpha0 = 2,0 chega ao mesmo
residuo em 8 rodadas. Cuidado ao ler o criterio `|dlambda| <= eps` nesse modo:
ele pode disparar pela queda do passo e nao pela do residuo. Compare pelo
residuo primal.

## Sobre o passo do subgradiente

O codigo original usa `alpha = 5e-4`, mas atualiza o preco sombra com um residuo
expresso em W, enquanto as variaveis dos modelos de otimizacao estao em kW. O
passo efetivo equivale a `alpha = 0.5` com residuo em kW, que e o valor usado
aqui. Rodar com `--alpha 5e-4` reproduz a constante literal do codigo antigo e
nao converge em tempo util.


## Fase 5: a camada de comunicacao

`pade-opentes/agents/network_link.py` desvia o envio de mensagens FIPA para um
modelo de rede, sem tocar no nucleo do PADE (compartilhado com os cenarios
`star`, `ieee13` e `integrated`). E o sucessor do `pade.simul` do PADE 2.2, que
fazia isso com o ns-3 e foi removido na versao 3.0.

```bash
NET_BACKEND=lossy NET_DROP_PROBABILITY=0.02 NET_TIME_SCALE=0.05 \
  MARKET_ROUND_TIMEOUT=20 MARKET_MAX_RETRIES=3 NET_TRACE=trace.csv \
  python3 agents/market_agents.py
```

Backends: `ideal` (canal perfeito), `lossy` (o mesmo modelo fenomenologico do
`NetworkNode.cc`, em Python) e `omnet` (cliente ZMQ para o container `comm`,
pendente do lado servidor). `NET_TIME_SCALE` comprime o atraso: a negociacao
inteira acontece dentro de um passo do Mosaik, com o relogio da co-simulacao
parado, e o atraso e aplicado no relogio do reactor.

### O que a camada de rede revelou

Duas coisas que a comunicacao ideal escondia, ambas corrigidas:

1. **O `FipaContractNetProtocol` do PADE supoe entrega imediata.** Com atraso, os
   contadores internos (`received_qty` contra `cfp_qty`) e o conjunto agregado
   deixam de coincidir: o ciclo 1 concluia com 19 das 25 programacoes, SEM
   nenhuma perda. Os agentes passaram a fazer contabilidade propria, por
   remetente e por numero de rodada.

2. **O FIPA nao define retransmissao.** Uma rodada tem cerca de 24 mensagens; a
   probabilidade de perder ao menos uma a 5% e de 71%. Sem retransmissao, a
   negociacao nao sobrevive a nenhuma perda realista. Os ciclos 1 e 4 ganharam
   timeout com reenvio apenas aos que faltam, e uma politica explicita para o
   agente que nunca responde: entra com programacao nula, ou seja, perde a
   chance de ser remunerado pelo ajuste e a rede perde o recurso dele.

### Resultado

| Perda | Retransmissao | Convergiu | Rodadas | Retransmissoes | Tempo |
|---:|---|---|---:|---:|---:|
| 0% | nao se aplica | sim | 17 | 0 | 94 s |
| 5% | desligada | **nao** | 1 | 0 | 23 s |
| 2% | 3 tentativas | sim | 17 | 7 | 211 s |

Com retransmissao, a perda de pacotes custa TEMPO, nao correcao: o numero de
rodadas e o preco sombra final nao mudam. Sem ela, a negociacao morre na
primeira rodada. Atraso medido no cenario de 2%: media de 6,0 s e maximo de
17,9 s por mensagem, dominado pelo tempo de transmissao das mensagens grandes
(o vetor de preco sombra tem 25 series de 96 valores), na mesma ordem de
grandeza da rede LPWA da tese, que entrega entre 10 e 90 s.
