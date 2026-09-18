"""Tabelas 20 e 21 do Apêndice A: demanda líquida por nó, nossa contra a da tese.

A tese publica, para cada nó, a demanda líquida máxima e mínima da fase de
OPERAÇÃO com o horário de ocorrência. É a grandeza que combina carga, geração e
armazenamento, e portanto o teste mais direto de se o caso de estudo é o mesmo:
se os dados de entrada e o despacho coincidem, estas 68 linhas coincidem.

Entrada:
  result_negociado.csv          colunas `PadeMarket-0.<eid>-P_kw`, uma por nó
  data/tese/demanda_por_no.csv  as Tabelas 20 e 21 transcritas

    python -m market_opentes.comparar_demanda --result output/market/result_negociado.csv
"""

import argparse
import csv
import re
from pathlib import Path

import numpy as np

from .config import DT_H, PERIODS


def _hhmm(t):
    m = int(round(t * DT_H * 60))
    return f"{m // 60:02d}:{m % 60:02d}"


def nossa(result_csv):
    """Máximo e mínimo da demanda líquida por nó, com o intervalo em que ocorre."""
    with open(result_csv) as f:
        linhas = list(csv.reader(f))
    cab = linhas[0]
    col = {}
    for i, h in enumerate(cab):
        m = re.search(r"PadeMarket-0\.node_(\d+)-P_kw", h)
        if m:
            col[int(m.group(1))] = i
    if not col:
        raise SystemExit("o CSV nao tem colunas P_kw: rode a co-simulacao com a "
                         "versao atual de scenarios/market.py")
    out = {}
    for no, i in col.items():
        v = np.array([float(l[i]) for l in linhas[1:] if l and l[i] != ""])
        out[no] = (int(v.argmax()), float(v.max()), int(v.argmin()), float(v.min()))
    return out


def tese(caminho):
    out = {}
    for r in csv.DictReader(open(caminho)):
        out[int(r["node"])] = (r["hora_max"], r["p_max_kw"],
                               r["hora_min"], r["p_min_kw"])
    return out


def comparar(result_csv, tese_csv, out_csv=None, mostrar=12):
    a, b = nossa(result_csv), tese(tese_csv)
    linhas = []
    for no in sorted(set(a) & set(b)):
        i_max, v_max, i_min, v_min = a[no]
        h_max, p_max, h_min, p_min = b[no]
        d_max = v_max - float(p_max) if p_max else None
        # a tese so lista o minimo dos nos que exportam
        d_min = v_min - float(p_min) if p_min else None
        linhas.append(dict(node=no,
                           nosso_hora_max=_hhmm(i_max), nosso_p_max=round(v_max, 2),
                           tese_hora_max=h_max, tese_p_max=p_max,
                           erro_max=None if d_max is None else round(d_max, 2),
                           nosso_hora_min=_hhmm(i_min), nosso_p_min=round(v_min, 2),
                           tese_hora_min=h_min, tese_p_min=p_min,
                           erro_min=None if d_min is None else round(d_min, 2)))
    if out_csv:
        with open(out_csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(linhas[0]))
            w.writeheader(); w.writerows(linhas)
        print(f"gravado {out_csv}")

    e_max = np.array([l["erro_max"] for l in linhas if l["erro_max"] is not None])
    e_min = np.array([l["erro_min"] for l in linhas if l["erro_min"] is not None])
    iguais_h = sum(1 for l in linhas if l["nosso_hora_max"] == l["tese_hora_max"])
    print(f"\n  {len(linhas)} nos comparados")
    print(f"  maximo: erro medio {e_max.mean():+.2f} kW, |erro| medio "
          f"{np.abs(e_max).mean():.2f} kW, pior {np.abs(e_max).max():.2f} kW")
    print(f"          dentro de 0,20 kW: {int((np.abs(e_max) <= 0.2).sum())} de {len(e_max)}")
    print(f"          mesmo horario: {iguais_h} de {len(linhas)}")
    if len(e_min):
        print(f"  minimo: erro medio {e_min.mean():+.2f} kW, |erro| medio "
              f"{np.abs(e_min).mean():.2f} kW, pior {np.abs(e_min).max():.2f} kW")
        print(f"          dentro de 0,20 kW: {int((np.abs(e_min) <= 0.2).sum())} de {len(e_min)}")

    piores = sorted((l for l in linhas if l["erro_max"] is not None),
                    key=lambda l: -abs(l["erro_max"]))[:mostrar]
    print(f"\n  os {mostrar} nos de maior discrepancia no maximo:")
    print(f"  {'no':>3} {'nosso':>16} {'tese':>16} {'erro':>7}")
    for l in piores:
        print(f"  {l['node']:>3} {l['nosso_hora_max']:>7} {l['nosso_p_max']:>8.2f} "
              f"{l['tese_hora_max']:>7} {float(l['tese_p_max']):>8.2f} "
              f"{l['erro_max']:>+7.2f}")
    return linhas


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--result", default="/app/output/market/result_negociado.csv")
    p.add_argument("--tese", default="data/tese/demanda_por_no.csv")
    p.add_argument("--out", default="data/demanda_vs_tese.csv")
    a = p.parse_args()
    comparar(a.result, a.tese, a.out)
