"""Carregamento termico dos condutores ao longo do dia.

POR QUE ISTO EXISTE
-------------------
A Eq. 6.13 da tese limita a potencia do TRANSFORMADOR, e a Eq. 6.14 a tensao.
Nao ha restricao de corrente de condutor na formulacao, embora o texto que
descreve o agente DSO mencione "limite termico dos condutores e transformadores".
Acrescentar a restricao iria ALEM da tese, nao em direcao a ela.

Antes de decidir se ela faz falta, mede-se. Este modulo percorre o dia com a
demanda realizada mais a programacao acordada e compara a corrente de cada linha
com a ampacidade do proprio LineCode. Se nenhum condutor chegar perto do limite,
a omissao nao tem consequencia nesta rede, e a afirmacao passa a ser verificavel
em vez de suposta.

Precisa do `py_dss_interface`, entao roda na imagem `opentes/pade:local`:

    docker run --rm -v .../market-opentes:/market -v .../data:/grid-data:ro \
      -e MARKET_GRID_DIR=/grid-data/MVLV75 opentes/pade:local \
      python3 -m market_opentes.loading
"""
import json
import os
import sys
import numpy as np
import py_dss_interface

from .config import PERIODS, load_case
from .dual import load_profiles
from .operation import realized_profiles

MASTER = os.environ["MARKET_GRID_DIR"] + "/Master.dss"
RUN_JSON = os.environ.get("MARKET_RUN_JSON", "data/run/run.json")
CONFIG = os.environ.get("MARKET_CONFIG", "data/config.json")

run = json.loads(open(RUN_JSON).read())
case = load_case(CONFIG)
net, _ = load_profiles()
real = realized_profiles(9)

# Programacao final acordada, da ultima rodada do historico.
hist = [h for h in run["history"] if h.get("y")]
y = {int(n): np.array(v) for n, v in hist[-1]["y"].items()} if hist else {}

cwd = os.getcwd()
dss = py_dss_interface.DSS()
dss.text(f'Compile "{MASTER}"')
tan_phi = float(np.tan(np.arccos(0.9)))

pior = 0.0
pior_info = None
carregamentos = []
for t in range(PERIODS):
    for node in case.lv_nodes:
        kw = float(real.get(node, net.get(node, np.zeros(PERIODS)))[t])
        if node in y:
            kw += float(y[node][t])
        dss.text(f"Edit Load.Load_{node} kW={kw} kvar={kw * tan_phi}")
    dss.text("Solve")
    for name in dss.lines.names:
        dss.circuit.set_active_element(f"Line.{name}")
        i = np.array(dss.cktelement.currents_mag_ang[0::2][:3])
        amps = float(i.max())
        norm = float(dss.lines.norm_amps)
        if norm > 0:
            pct = 100.0 * amps / norm
            carregamentos.append(pct)
            if pct > pior:
                pior, pior_info = pct, (name, t, amps, norm)
os.chdir(cwd)

c = np.array(carregamentos)
print(f"carregamento dos condutores em {PERIODS} intervalos x {len(dss.lines.names)} linhas")
print(f"  mediana {np.median(c):.2f}%  p99 {np.percentile(c, 99):.2f}%  maximo {c.max():.2f}%")
n, t, a, norm = pior_info
print(f"  pior: {n} no intervalo {t} com {a:.1f} A de {norm:.0f} A")
print(f"  acima de 100%: {int((c > 100).sum())} pontos de {c.size}")
