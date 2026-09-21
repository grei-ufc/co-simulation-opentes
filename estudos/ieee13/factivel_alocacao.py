"""Folga residual minima do dia com o limite de cada no igual a rede + prosumidor.

Confere se uma alocacao candidata e factivel. Argumento: JSON com um dicionario
por alocacao, {"nome": {"no": potencia_kW, ...}}.

Uso, a partir da raiz do repositorio:

    export CPLEX_HOME=$HOME/IBM/CPLEX_Studio2211/cplex
    docker run --rm --network none -v "$PWD:/r" \
      -v "$PWD/simulators/market-opentes:/market" \
      -v "$PWD/simulators/grid-opentes/src/data:/grid-data" \
      -v "$CPLEX_HOME:/opt/cplex:ro" \
      -e MARKET_GRID_DIR=/grid-data/13Bus -e MARKET_DATA_DIR=/grid-data/13Bus \
      -w /market opentes/pade:local python /r/estudos/ieee13/factivel_alocacao.py '{"atual": {"646": 1000, "645": 700}}'
"""
import sys, json
sys.path.insert(0, "/market")
import pyomo.environ as pyo
from market_opentes.config import PERIODS, V_MIN, V_MAX, V_BACKOFF, load_case
from market_opentes.dual import load_sensitivity
case = load_case("/grid-data/13Bus/config.json")
nodes, v0, s = load_sensitivity()
idx = {n: i for i, n in enumerate(case.all_nodes)}
PROS = case.prosumer_nodes
sol = pyo.SolverFactory("cplex", executable="/opt/cplex/bin/x86-64_linux/cplex")
for nome, cap in json.loads(sys.argv[1]).items():
    cap = {int(k): v for k, v in cap.items()}
    pior = 0.0
    for t in range(PERIODS):
        m = pyo.ConcreteModel()
        m.N = pyo.Set(initialize=PROS, ordered=True)
        m.p = pyo.Var(m.N, bounds=lambda m, n: (-cap.get(n, 0.0), cap.get(n, 0.0)))
        m.f = pyo.Var(bounds=(0, None)); m.c = pyo.ConstraintList()
        for i, _ in enumerate(case.all_nodes):
            dv = sum(-float(s[t][i, idx[n]]) * m.p[n] for n in PROS)
            m.c.add(float(v0[t][i]) + dv <= V_MAX - V_BACKOFF + m.f)
            m.c.add(float(v0[t][i]) + dv >= V_MIN + V_BACKOFF - m.f)
        m.o = pyo.Objective(expr=m.f); sol.solve(m); pior = max(pior, pyo.value(m.f))
    print(f"{nome:10s} total {sum(cap.values()):6.0f} kW  folga residual {1000*pior:.3f} mpu")
