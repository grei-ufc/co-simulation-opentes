"""Dimensionamento do armazenamento pela matriz de sensibilidade do caso.

1) menor limite uniforme por no que zera a violacao do dia (folga residual);
2) com 1000 kW por no, a menor potencia total por intervalo: pico e energia por no.

Uso, a partir da raiz do repositorio:

    export CPLEX_HOME=$HOME/IBM/CPLEX_Studio2211/cplex
    docker run --rm --network none -v "$PWD:/r" \
      -v "$PWD/simulators/market-opentes:/market" \
      -v "$PWD/simulators/grid-opentes/src/data:/grid-data" \
      -v "$CPLEX_HOME:/opt/cplex:ro" \
      -e MARKET_GRID_DIR=/grid-data/13Bus -e MARKET_DATA_DIR=/grid-data/13Bus \
      -w /market opentes/pade:local python /r/estudos/ieee13/dimensionamento.py 
"""
import sys
sys.path.insert(0, "/market")
import pyomo.environ as pyo
from market_opentes.config import PERIODS, V_MIN, V_MAX, V_BACKOFF, load_case
from market_opentes.dual import load_sensitivity

case = load_case("/grid-data/13Bus/config.json")
nodes, v0, s = load_sensitivity()
idx = {n: i for i, n in enumerate(case.all_nodes)}
PROS = case.prosumer_nodes
sol = pyo.SolverFactory("cplex", executable="/opt/cplex/bin/x86-64_linux/cplex")


def folga(lim):
    pior = 0.0
    for t in range(PERIODS):
        m = pyo.ConcreteModel()
        m.N = pyo.Set(initialize=PROS, ordered=True)
        m.p = pyo.Var(m.N, bounds=(-lim, lim))
        m.f = pyo.Var(bounds=(0, None))
        m.c = pyo.ConstraintList()
        for i, _ in enumerate(case.all_nodes):
            dv = sum(-float(s[t][i, idx[n]]) * m.p[n] for n in PROS)
            m.c.add(float(v0[t][i]) + dv <= V_MAX - V_BACKOFF + m.f)
            m.c.add(float(v0[t][i]) + dv >= V_MIN + V_BACKOFF - m.f)
        m.o = pyo.Objective(expr=m.f, sense=pyo.minimize)
        sol.solve(m)
        pior = max(pior, float(pyo.value(m.f)))
    return pior


print("limite uniforme por no -> folga residual")
for lim in (200, 400, 600, 800, 1000):
    f = folga(lim)
    print(f"  {lim:>5} kW  {1000 * f:7.2f} mpu {'FACTIVEL' if f < 1e-6 else ''}")

LIM = 1000.0
pico = {n: 0.0 for n in PROS}
energia = {n: 0.0 for n in PROS}
for t in range(PERIODS):
    m = pyo.ConcreteModel()
    m.N = pyo.Set(initialize=PROS, ordered=True)
    m.p = pyo.Var(m.N, bounds=(-LIM, LIM))
    m.a = pyo.Var(m.N, bounds=(0, None))
    m.c = pyo.ConstraintList()
    for i, _ in enumerate(case.all_nodes):
        dv = sum(-float(s[t][i, idx[n]]) * m.p[n] for n in PROS)
        m.c.add(float(v0[t][i]) + dv <= V_MAX - V_BACKOFF)
        m.c.add(float(v0[t][i]) + dv >= V_MIN + V_BACKOFF)
    m.a1 = pyo.Constraint(m.N, rule=lambda m, n: m.a[n] >= m.p[n])
    m.a2 = pyo.Constraint(m.N, rule=lambda m, n: m.a[n] >= -m.p[n])
    m.o = pyo.Objective(expr=sum(m.a[n] for n in PROS), sense=pyo.minimize)
    sol.solve(m)
    for n in PROS:
        p = float(pyo.value(m.p[n]))
        pico[n] = max(pico[n], abs(p))
        energia[n] += abs(p) * 0.25
print("necessidade por no (1000 kW por no, minimo total):")
for n in PROS:
    if pico[n] > 1:
        print(f"  no {n:<4} {pico[n]:7.0f} kW  {energia[n]:8.0f} kWh")
print(f"  TOTAL   {sum(pico.values()):7.0f} kW  {sum(energia.values()):8.0f} kWh")
