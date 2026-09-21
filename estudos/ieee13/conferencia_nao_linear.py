"""Confere a programacao negociada no fluxo NAO LINEAR do OpenDSS.

Tres casos: base sem armazenamento, negociado com o regulador respondendo ao
mercado e negociado com a derivacao fixada pela demanda prevista. Le a
programacao do `figuras.npz` da negociacao centralizada.

Uso, a partir da raiz do repositorio:

    docker run --rm --network none -v "$PWD:/r" opentes/grid:local \
      python /r/estudos/ieee13/conferencia_nao_linear.py /r/simulators/grid-opentes/src/data/13Bus /r/output/market_13Bus
"""
import csv, math, sys
import numpy as np
import py_dss_interface

D = sys.argv[1]; OUT = sys.argv[2]
tan = math.tan(math.acos(0.9))


def ler(a):
    with open(a) as f:
        r = csv.reader(f); nos = [int(x) for x in next(r)]
        return nos, np.array([[float(x) for x in row] for row in r])


nos, L = ler(f"{D}/load_kw.csv"); _, P = ler(f"{D}/pv_kw.csv")
NET = L - P
z = np.load(f"{OUT}/figuras.npz", allow_pickle=True)
pros = [int(x) for x in z["prosumer_nodes"]]; rede = [int(x) for x in z["network_nodes"]]
Y = z["y"]; Q = z["q"]
arm = {}
for i, n in enumerate(pros): arm[n] = arm.get(n, 0) + Y[i]
for i, n in enumerate(rede): arm[n] = arm.get(n, 0) + Q[i]


def rodar(com_mercado, congelar_taps=False):
    dss = py_dss_interface.DSS(); dss.text(f'compile "{D}/Master.dss"')
    porfase = []; media = []
    for t in range(96):
        if congelar_taps:
            dss.text("Batchedit RegControl..* enabled=yes maxtapchange=16")
            for i, n in enumerate(nos):
                dss.text(f"Edit Load.Load_{n} kW={NET[t,i]} kvar={NET[t,i]*tan}")
            dss.solution.solve()
            dss.text("Batchedit RegControl..* enabled=no")
        for i, n in enumerate(nos):
            p_arm = float(arm[n][t]) if (com_mercado and n in arm) else 0.0
            dss.text(f"Edit Load.Load_{n} kW={NET[t,i] + p_arm} kvar={NET[t,i]*tan}")
        dss.solution.solve()
        for b in dss.circuit.buses_names:
            if b in ("sourcebus", "650", "rg60"): continue
            dss.circuit.set_active_bus(b)
            if not dss.bus.kv_base or dss.bus.kv_base <= 0: continue
            m = [x for x in dss.bus.vmag_angle_pu[0::2] if x > 1e-6]
            porfase += m; media.append(sum(m) / len(m))
    return np.array(porfase), np.array(media)


for rot, cm, cg in (("CASO BASE, sem armazenamento", False, False),
                    ("NEGOCIADO, regulador respondendo ao mercado", True, False),
                    ("NEGOCIADO, derivacao travada pela previsao", True, True)):
    pf, md = rodar(cm, cg)
    print(f"=== {rot} ===")
    for nome, v in (("media das fases", md), ("por fase", pf)):
        print(f"  {nome:16s} faixa {v.min():.4f} a {v.max():.4f}   <0,97: {(v<0.97).sum():>4}"
              f"   >1,03: {(v>1.03).sum():>4}   fora de A: {((v<0.95)|(v>1.05)).sum():>4} de {len(v)}")
