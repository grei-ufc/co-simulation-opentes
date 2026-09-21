"""Custo da convencao de reativo da demanda liquida no pior intervalo do caso base.

Compara kvar = kW liquido x tan(acos 0,9) com kvar = 0 nos nos que exportam
(PV em fator de potencia unitario).

Uso, a partir da raiz do repositorio:

    docker run --rm --network none -v "$PWD:/r" opentes/grid:local \
      python /r/estudos/ieee13/convencao_reativo.py /r/simulators/grid-opentes/src/data/13Bus
"""
import csv, math, sys
import numpy as np
import py_dss_interface
D = sys.argv[1]
tan = math.tan(math.acos(0.9))
def ler(a):
    with open(a) as f:
        r = csv.reader(f); nos = [int(x) for x in next(r)]
        return nos, np.array([[float(x) for x in row] for row in r])
nos, L = ler(f"{D}/load_kw.csv"); _, P = ler(f"{D}/pv_kw.csv")
NET = L - P
def tensoes(t, zera_export):
    dss = py_dss_interface.DSS(); dss.text(f'compile "{D}/Master.dss"')
    for i, n in enumerate(nos):
        kw = NET[t, i]
        kvar = 0.0 if (zera_export and kw < 0) else kw * tan
        dss.text(f"Edit Load.Load_{n} kW={kw} kvar={kvar}")
    dss.text("Solve")
    v = {}
    for b in dss.circuit.buses_names:
        if b in ("sourcebus", "650", "rg60"): continue
        dss.circuit.set_active_bus(b)
        m = [x for x in dss.bus.vmag_angle_pu[0::2] if x > 1e-6]
        v[b] = sum(m) / len(m)
    return v
pior = max(range(96), key=lambda t: max(tensoes(t, False).values()))
a = tensoes(pior, False); b = tensoes(pior, True)
barra = max(a, key=a.get)
print(f"pior intervalo {pior} ({pior*15//60:02d}:{pior*15%60:02d}), barra {barra}")
print(f"  convencao atual            {a[barra]:.4f} pu, excesso sobre 1,029: {1000*(a[barra]-1.029):.1f} mpu")
print(f"  kvar = 0 quando exporta    {max(b.values()):.4f} pu (barra {max(b, key=b.get)}), diferenca {1000*(a[barra]-max(b.values())):.1f} mpu")
