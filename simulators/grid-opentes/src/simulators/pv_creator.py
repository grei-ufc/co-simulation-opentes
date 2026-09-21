"""Curvas de irradiancia e temperatura dos cinco PVs do IEEE 13 barras.

Adaptado do `pv_creator.py` do tsre-der-opentes (versao 1.1.1), de onde veio a
versao 1.0.0 que gerou as curvas originais deste repositorio. Cada PV le uma
estacao solar do BR-PVGen (`src/data/InfoPV/solar_station/PS_00N.csv`, 15 min)
e a curva e reamostrada para 5 min.

O QUE A VERSAO NOVA CORRIGE
---------------------------
A 1.0.0 gravava a temperatura do modulo dividida por 25 (`T / 25`), uma
temperatura "em pu" que nenhum consumidor da curva entende assim: o `TDaily` do
OpenDSS, o `PVPanelModel` e o `gen_ieee13_market.py` leem graus Celsius e
aplicam a curva P-T de [0, 25, 75, 100] C. Com a curva em 0,7 a 1,8 "graus", o
painel ficava o dia inteiro na regiao de modulo gelado, com fator de potencia
por temperatura perto de 1,19, e o PV do IEEE 13 gerava 17% a mais de energia
do que as mesmas estacoes produzem. A temperatura agora e gravada em graus
Celsius.

FILTROS DE DADO, TODOS DO UPSTREAM
----------------------------------
- Irradiancia negativa vai a zero: e o ruido noturno do piranometro, de 36 a 50
  amostras por estacao no dia usado, e nao geracao negativa.
- Irradiancia ausente vai a zero; irradiancia acima de 1,5 pu rejeita a curva.
- Temperatura ausente vai a 25 C; temperatura fora de [-40, 85] C (IEC 61215)
  rejeita a curva.
- Reamostragem por PCHIP em vez de linear. O PCHIP preserva a forma dos dados:
  entre dois pontos de 15 min ele nao ultrapassa os valores vizinhos, entao nao
  cria irradiancia negativa na borda do amanhecer nem pico que a estacao nao
  mediu, o que um spline cubico faria.
- Cada PV e conferido contra o circuito compilado: fases declaradas e nos
  existentes na barra (`pv_validator.validar_no_circuito`).

O QUE NAO VEIO
--------------
A alocacao aleatoria de PVs, o arredondamento da potencia para o inversor
comercial mais proximo (que levaria os 5 MW do PV1 para 350 kVA) e a conversao
de PV bifasico em monofasico com sorteio da fase. Os cinco PVs deste caso sao
fixos e fazem parte do benchmark.

A irradiancia passou a ser normalizada por 1000 W/m2 (condicao padrao de teste),
com `irrad=1.0` no PVSystem e `irradiance_base=1.0` no painel. Antes era por
800 W/m2 com `irrad=0.8`; o produto e o mesmo, a potencia nao muda por isso.

Uso, dentro do container grid:

    python src/simulators/pv_creator.py
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import py_dss_interface

import pv_validator as val

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SRC = Path(__file__).resolve().parents[1]
INFO_PV = SRC / "data" / "InfoPV"
METADADOS = INFO_PV / "power_station_metadata.csv"
ESTACOES = INFO_PV / "solar_station"
DATA = SRC / "data" / "13Bus"
CIRCUITO = DATA / "IEEE13Nodeckt.dss"

PASSO = "5min"
PONTOS_DIA = 288
INICIO = 96              # o dia usado e o segundo da serie de 15 min de cada estacao
DATA_INICIAL = "2026-01-01 00:00:00"
IRRAD_REF_WM2 = 1000.0   # condicao padrao de teste
TEMP_PADRAO_C = 25.0

# Os cinco PVs do benchmark. A curva N e a estacao PS_00N.
PVS = [
    {"name": "PV1", "bus": "646.3.2", "phases": 2, "kv": 4.16, "kva": 5000, "curva": 1},
    {"name": "PV2", "bus": "632.1.2.3", "phases": 3, "kv": 4.16, "kva": 3000, "curva": 2},
    {"name": "PV3", "bus": "634.1.2.3", "phases": 3, "kv": 0.48, "kva": 3000, "curva": 3},
    {"name": "PV4", "bus": "645.3", "phases": 1, "kv": 2.4, "kva": 2000, "curva": 4},
    {"name": "PV5", "bus": "652.1", "phases": 1, "kv": 2.4, "kva": 2000, "curva": 5},
]

# Curvas do PVSystem, as mesmas que o `PVPanelModel` e o gerador do mercado usam.
PT_X, PT_Y = [0, 25, 75, 100], [1.2, 1.0, 0.8, 0.6]
EF_X, EF_Y = [0.1, 0.2, 0.4, 1.0], [0.86, 0.90, 0.93, 0.97]


def pchip(x, y, xq):
    """Interpolacao cubica de Hermite que preserva a forma (Fritsch-Carlson).

    E o mesmo interpolador do `scipy.interpolate.PchipInterpolator`, que o
    `interpolate(method="pchip")` do pandas chama. Fica escrito aqui para o
    container grid nao precisar do scipy so por isso.
    """
    x, y, xq = (np.asarray(v, dtype=float) for v in (x, y, xq))
    h = np.diff(x)
    delta = np.diff(y) / h
    d = np.zeros_like(y)
    # pontos internos: media harmonica ponderada, zero onde a inclinacao muda
    # de sinal ou zera, o que impede o ultrapassamento
    w1, w2 = 2 * h[1:] + h[:-1], h[1:] + 2 * h[:-1]
    mesmo_sinal = (delta[:-1] * delta[1:]) > 0
    with np.errstate(divide="ignore", invalid="ignore"):
        hm = (w1 + w2) / (w1 / delta[:-1] + w2 / delta[1:])
    d[1:-1] = np.where(mesmo_sinal, hm, 0.0)

    def borda(h0, h1, m0, m1):
        dd = ((2 * h0 + h1) * m0 - h0 * m1) / (h0 + h1)
        if np.sign(dd) != np.sign(m0):
            return 0.0
        if np.sign(m0) != np.sign(m1) and abs(dd) > abs(3 * m0):
            return 3 * m0
        return dd

    d[0] = borda(h[0], h[1], delta[0], delta[1])
    d[-1] = borda(h[-1], h[-2], delta[-1], delta[-2])

    k = np.clip(np.searchsorted(x, xq, side="right") - 1, 0, len(h) - 1)
    t = (xq - x[k]) / h[k]
    h00 = (1 + 2 * t) * (1 - t) ** 2
    h10 = t * (1 - t) ** 2
    h01 = t ** 2 * (3 - 2 * t)
    h11 = t ** 2 * (t - 1)
    return h00 * y[k] + h10 * h[k] * d[k] + h01 * y[k + 1] + h11 * h[k] * d[k + 1]


def curvas_da_estacao(arquivo):
    """Irradiancia (pu de 1000 W/m2) e temperatura (C) de um dia, a cada 5 min."""
    bruto = pd.read_csv(arquivo)
    dia = bruto.iloc[INICIO:INICIO + 96 + 1]      # 97 pontos: fecha o dia em 24:00

    irrad = (dia["poa_irradiance_wm2"] / IRRAD_REF_WM2).clip(lower=0).fillna(0)
    val.validar_irradiancia(irrad, arquivo.name)
    temp = dia["panel_temperature_celsius"].fillna(TEMP_PADRAO_C)
    val.validar_temperatura(temp, arquivo.name)

    x = np.arange(len(dia)) * 3.0                 # passos de 5 min
    xq = np.arange(PONTOS_DIA, dtype=float)
    g = np.round(pchip(x, irrad.to_numpy(), xq), 6)
    t = np.round(pchip(x, temp.to_numpy(), xq), 6)
    return pd.Series(g), pd.Series(t)


def gravar_csv(caminho, indice, colunas):
    df = pd.DataFrame(colunas)
    df.insert(0, "index", indice.strftime("%Y-%m-%d %H:%M:%S"))
    df.to_csv(caminho, index=False)


def gravar_shapes(irrad, temp):
    """Loadshapes de irradiancia e Tshapes de temperatura para o OpenDSS."""
    def fmt(v):
        return ", ".join(f"{x:.6f}" for x in v)

    linhas = ["! Gerado por src/simulators/pv_creator.py. Nao editar a mao.",
              "! Irradiancia em pu de 1000 W/m2; temperatura do modulo em graus C.",
              ""]
    for col, v in irrad.items():
        linhas.append(f"New Loadshape.{col} npts={len(v)} minterval=5 mult=({fmt(v)})")
    for col, v in temp.items():
        linhas.append(f"New Tshape.{col} npts={len(v)} minterval=5 temp=({fmt(v)})")
    (DATA / "ieee13_shape_pv_5min.dss").write_text("\n".join(linhas) + "\n")


def gravar_pvsystems():
    xy = lambda xs: ", ".join(str(x) for x in xs)   # noqa: E731
    linhas = [
        "! Gerado por src/simulators/pv_creator.py. Nao editar a mao.",
        "",
        f"New XYCurve.MyPvsT npts=4 xarray=[{xy(PT_X)}] yarray=[{xy(PT_Y)}]",
        f"New XYCurve.MyEff npts=4 xarray=[{xy(EF_X)}] yarray=[{xy(EF_Y)}]",
        "",
        "! A barra 646 e alimentada pelo ramal 632-645-646, ambos os trechos na",
        "! configuracao 603, cujo faseamento oficial e \"C B N\" (IEEE 13 Node Test",
        "! Feeder, tabela de configuracoes de linha): 646 so tem as fases B e C.",
        "! Declarado como `phases=3 Bus1=646.1.2.3`, o terminal da fase A ficava",
        "! ligado a um no que nenhum outro elemento usa, e 37% da potencia do PV1 era",
        "! injetada nele. O `pv_validator.validar_no_circuito` recusa essa declaracao.",
    ]
    for pv in PVS:
        i = pv["name"][2:]
        linhas += [
            f"New PVSystem.{pv['name']} phases={pv['phases']} Bus1={pv['bus']} "
            f"kV={pv['kv']} kVA={pv['kva']} irrad=1.0 Pmpp={pv['kva']}",
            f"~ temperature={TEMP_PADRAO_C:g} PF=1 EffCurve=MyEff P-TCurve=MyPvsT",
            f"~ Daily=my_shape{i}_irrad TDaily=my_shape{i}_temperature",
            "~ Vminpu=0.001 Model=1",
            "",
        ]
    (DATA / "ieee13_pv.dss").write_text("\n".join(linhas))


def main():
    val.validar_caminhos(METADADOS, ESTACOES, CIRCUITO)
    meta = val.carregar_metadados(METADADOS)

    dss = py_dss_interface.DSS()
    dss.text(f'compile "{CIRCUITO}"')
    val.validar_no_circuito(PVS, dss)

    irrad, temp = {}, {}
    for pv in PVS:
        i = pv["name"][2:]
        estacao = meta.iloc[pv["curva"] - 1]["id"]
        g, t = curvas_da_estacao(ESTACOES / f"{estacao}.csv")
        val.validar_curvas_interpoladas(pv["name"], g, t, PONTOS_DIA, estacao)
        irrad[f"my_shape{i}_irrad"] = g
        temp[f"my_shape{i}_temperature"] = t
        logger.info("%s em %s (%g kVA): %s, irradiancia ate %.3f pu, "
                    "temperatura %.1f a %.1f C", pv["name"], pv["bus"], pv["kva"],
                    estacao, g.max(), t.min(), t.max())

    dia = pd.date_range(DATA_INICIAL, periods=PONTOS_DIA, freq=PASSO)
    dois_dias = pd.date_range(DATA_INICIAL, periods=2 * PONTOS_DIA, freq=PASSO)
    gravar_csv(DATA / "ieee13_shape_pv_5min.csv", dia, irrad)
    gravar_csv(DATA / "ieee13_temperature_5min.csv", dia, temp)
    # 48 h: o mesmo dia repetido, para o experimento que confere se o ciclo
    # diario se repete
    gravar_csv(DATA / "ieee13_shape_pv_5min_48h.csv", dois_dias,
               {k: pd.concat([v, v], ignore_index=True) for k, v in irrad.items()})
    gravar_csv(DATA / "ieee13_temperature_5min_48h.csv", dois_dias,
               {k: pd.concat([v, v], ignore_index=True) for k, v in temp.items()})
    gravar_shapes(irrad, temp)
    gravar_pvsystems()
    logger.info("gravados em %s", DATA)


if __name__ == "__main__":
    main()
