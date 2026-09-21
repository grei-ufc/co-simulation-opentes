"""Tres configuracoes do regulador ao longo do dia, IEEE 13 com os cinco PVs.

Snapshot a cada passo de 5 min, cargas pelo multiplicador da LoadShape (10 min),
PV imposto como pmpp = P_ac do painel e do inversor calculado das curvas, 38 nos
(todas as fases exceto a fonte). Reporta a fracao fora da faixa A (0,95 a 1,05
pu) e fora de 0,97 a 1,03 pu. `irrad_base` e 1.0 para as curvas atuais, em pu de
1000 W/m2.

Uso, a partir da raiz do repositorio:

    docker run --rm --network none -v "$PWD:/r" opentes/grid:local \
      python /r/estudos/ieee13/regulador.py /r/simulators/grid-opentes/src/data/13Bus 1.0
"""
import csv
import sys

import numpy as np
import py_dss_interface

D = sys.argv[1]
IRRAD_BASE = float(sys.argv[2])
N, PASSO = 288, 300
PT_X, PT_Y = [0, 25, 75, 100], [1.2, 1.0, 0.8, 0.6]
EF_X, EF_Y = [0.1, 0.2, 0.4, 1.0], [0.86, 0.90, 0.93, 0.97]
PVS = {"pv1": (5000, 5000), "pv2": (3000, 3000), "pv3": (3000, 3000),
       "pv4": (2000, 2000), "pv5": (2000, 2000)}


def ler(arq):
    out = {}
    with open(arq) as f:
        for r in csv.DictReader(f):
            for k, v in r.items():
                if k != "index":
                    out.setdefault(k, []).append(float(v))
    return out


irr = ler(f"{D}/ieee13_shape_pv_5min.csv")
tmp = ler(f"{D}/ieee13_temperature_5min.csv")


def p_ac(nome, k):
    pmpp, kva = PVS[nome]
    n = nome[2:]
    p_dc = pmpp * IRRAD_BASE * irr[f"my_shape{n}_irrad"][k] * np.interp(
        tmp[f"my_shape{n}_temperature"][k], PT_X, PT_Y)
    if p_dc <= 0:
        return 0.0
    return min(p_dc * np.interp(p_dc / kva, EF_X, EF_Y), kva)


CONF = {
    "publicadas": ["Batchedit RegControl..* maxtapchange=0",
                   "Transformer.Reg1.Taps=[1.0 1.0625]",
                   "Transformer.Reg2.Taps=[1.0 1.0500]",
                   "Transformer.Reg3.Taps=[1.0 1.06875]"],
    "inicializacao": ["Batchedit RegControl..* maxtapchange=0"],
    "livres": ["Batchedit RegControl..* maxtapchange=16", "Set ControlMode=static"],
}


def rodar(extra, com_pv=True):
    dss = py_dss_interface.DSS()
    dss.text(f'compile "{D}/IEEE13Nodeckt_w_loadcurve.dss"')
    dss.text(f"Redirect {D}/ieee13_shape_pv_5min.dss")
    dss.text(f"Redirect {D}/ieee13_pv.dss")
    dss.text("Set ControlMode=Time")
    for c in extra:
        dss.text(c)
    if not com_pv:
        dss.text("Batchedit PVSystem..* enabled=no")
    dss.text("Set mode=snap")
    dss.text("Set number=1")
    dss.circuit.set_active_class("Load")
    cargas = {n: (float(dss.text(f"? Load.{n}.kW")), float(dss.text(f"? Load.{n}.kvar")),
                  dss.text(f"? Load.{n}.daily")) for n in dss.active_class.names}
    formas = {}
    for i in range(1, 11):
        m = dss.text(f"? LoadShape.LoadShape{i}.mult")
        formas[f"LoadShape{i}"] = [float(x) for x in m.strip("[] ").replace(",", " ").split()]
    barras = list(dss.circuit.buses_names)
    pu, carga_tot, pv_tot = [], [], []
    for k in range(N):
        c = 0.0
        for nome, (kw, kvar, shp) in cargas.items():
            m = formas[shp][(k * PASSO // 600) % 144]
            dss.text(f"Edit Load.{nome} kW={kw * m} kvar={kvar * m}")
            c += kw * m
        p = 0.0
        if com_pv:
            for nome in PVS:
                pk = p_ac(nome, k)
                p += pk
                dss.text(f"Edit PVSystem.{nome} pmpp={max(pk, 1e-6)} irradiance=1.0 pf=1")
        dss.solution.solve()
        for b in barras:
            dss.circuit.set_active_bus(b)
            if not dss.bus.kv_base or dss.bus.kv_base <= 0 or b.lower() == "sourcebus":
                continue
            for v in list(dss.bus.vmag_angle_pu[0::2]):
                if v > 1e-6:
                    pu.append(v)
        carga_tot.append(c)
        pv_tot.append(p)
    return np.array(pu), np.array(carga_tot), np.array(pv_tot)


if __name__ == "__main__":
    for nome, extra in CONF.items():
        v, c, p = rodar(extra)
        print(f"{nome:14s} leituras={len(v)} faixa {v.min():.4f} a {v.max():.4f}  "
              f"fora de A {100 * ((v < 0.95) | (v > 1.05)).mean():5.1f}%  "
              f"acima de 1,05: {(v > 1.05).sum()}  "
              f"fora de 0,97-1,03 {100 * ((v < 0.97) | (v > 1.03)).mean():5.1f}%  "
              f"carga {c.min():.0f} a {c.max():.0f} kW  PV pico {p.max():.0f} kW  "
              f"PV energia {p.sum() / 12:.0f} kWh")
    v, c, p = rodar(CONF["publicadas"], com_pv=False)
    print(f"publicadas sem PV: acima de 1,05 {100 * (v > 1.05).mean():.1f}%, carga minima {c.min():.0f} kW")
