"""Extrai os perfis diarios de carga, geracao PV e preco spot para a rede MVLV75.

Fonte: os mesmos dados do trabalho original, que ficam no repositorio
`market-simulation`:
  - SimBench `1-MVLV-urban-5.303-1-no_sw` (LoadProfile.csv e RESProfile.csv,
    resolucao de 15 min, ano inteiro);
  - precos day-ahead do Nordpool (`market-data/`).

O que este script faz e recortar UM dia e escrever tres CSVs compactos em
`data/`, para o pacote nao depender de arrastar o SimBench inteiro (35 mil
linhas por arquivo) nem do repositorio antigo em tempo de execucao.

ESCALONAMENTO DA CARGA
---------------------
O perfil bruto do SimBench e normalizado entre 0 e 1 e multiplicado pelo `size`
do dispositivo `user_action_device` do config.json. E o que a classe `UserLoad`
do `prosumer.py` original faz: `UserLoad(max_dem_value=device_params['size'])`,
com a curva normalizada e multiplicada por esse valor.

Uma versao anterior escalava pelo `active_power` do no no force.json, que da uma
carga 2,7 vezes menor (soma de 67,3 kW contra 182,8 kW) e por isso produzia um
caso base sem nenhuma violacao, ao contrario da tese, que relata subtensao entre
17:45 e 19:15.

OS DEMAIS DISPOSITIVOS DO PROSUMIDOR
------------------------------------
O config.json aloca ainda `shiftable_load` (68 nos), `buffering_device` (54) e
`freely_control_gen` (3). Eles NAO entram na demanda: no `Prosumer.step` do
`prosumer.py` original as tres contribuicoes estao comentadas (linhas 591, 603 e
609), de modo que os dispositivos sao instanciados, recebem `step()` e o
resultado e descartado. So `stochastic_gen`, `user_action_device` e
`storage_device` compoem o `p_out` que chega a rede. Reproduzimos esse
comportamento; implementa-los mudaria o caso em relacao a tese em vez de
aproxima-lo dela.

A geracao PV usa o `size` do `stochastic_gen`, que existe em 34 dos 68 nos de
baixa tensao (50% de penetracao, subsecao 6.2.1 da tese).

Uso:

    python -m market_opentes.data_prep [--market-simulation CAMINHO]
"""

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

PKG_DIR = Path(__file__).resolve().parent
DATA_DIR = PKG_DIR.parent / "data"
# .../simulators/market-opentes/market_opentes -> .../simulators
SIMULATORS_DIR = PKG_DIR.parents[1]
# Dentro do container o pacote e montado fora da arvore do repositorio, entao o
# caminho da rede e parametrizavel.
GRID_DIR = Path(os.environ.get(
    "MARKET_GRID_DIR",
    SIMULATORS_DIR / "grid-opentes" / "src" / "data" / "MVLV75"))

# Dia recortado do ano do SimBench. O trabalho original usava
# start_day = 15 dias + 1 mes (load_data.py), ou seja, meados de fevereiro.
DAY_OFFSET = 45          # dia do ano (base 0)
SPOT_DAY_OFFSET = 15     # mesmo indice usado no market_agent original
POOL_DAYS = 10           # dias alternativos para amostrar cenarios
POOL_DAY_STRIDE = 3      # espacamento entre eles, para nao amostrar dias vizinhos
PERIODS = 96             # 15 min
DT_H = 0.25


def _load_force():
    return json.loads((GRID_DIR / "force.json").read_text())


def _slice_day(profile_df, column, day=DAY_OFFSET):
    start = day * PERIODS
    values = profile_df[column].values[start:start + PERIODS]
    return np.asarray(values, dtype=float)


def _normalize(values):
    lo, hi = values.min(), values.max()
    if hi - lo < 1e-12:
        return np.zeros_like(values)
    return (values - lo) / (hi - lo)


def build(ms_path):
    ms = Path(ms_path)
    sb = ms / "1-MVLV-urban-5.303-1-no_sw"

    load_profile = pd.read_csv(sb / "LoadProfile.csv", delimiter=";")
    res_profile = pd.read_csv(sb / "RESProfile.csv", delimiter=";")
    # As mesmas fatias do load_data.py original: as cargas e a geracao de BT.
    load_df = pd.read_csv(sb / "Load.csv", delimiter=";")[138:242]
    gen_df = pd.read_csv(sb / "RES.csv", delimiter=";")[134:]

    force = _load_force()
    config = json.loads((ms / "config.json").read_text())
    lv_nodes = [n["name"] for n in force["nodes"] if n["voltage_level"] == "low voltage"]
    # Pico de demanda por no: o `size` do user_action_device, como na tese.
    peak_kw = {int(k): v["size"]
               for k, v in config["devices"]["user_action_device"]["params"].items()}
    pv_size = {int(k): v["size"] for k, v in config["devices"]["stochastic_gen"]["params"].items()}

    load_cols = {}
    pv_cols = {}
    for i, node in enumerate(lv_nodes):
        prof = load_df.iloc[i % len(load_df)].profile
        shape = _normalize(_slice_day(load_profile, f"{prof}_pload"))
        load_cols[str(node)] = peak_kw[node] * shape

        if node in pv_size:
            gprof = gen_df.iloc[i % len(gen_df)].profile
            gshape = _slice_day(res_profile, gprof)
            gshape = gshape / gshape.max() if gshape.max() > 0 else gshape
            pv_cols[str(node)] = pv_size[node] * gshape
        else:
            pv_cols[str(node)] = np.zeros(PERIODS)

    # Preco day-ahead do Nordpool, coluna SpotPriceEUR, com o mesmo recorte de
    # `load_data.get_spot_prices_data(spot_index=15)`: 6 meses + 15 dias.
    prices = pd.read_csv(ms / "market-data" / "Nordpool_Market_Data-3.csv")
    start_h = SPOT_DAY_OFFSET * 24 + 24 * 30 * 6
    hourly = prices["SpotPriceEUR"].values[start_h:start_h + 24]
    # Dados horarios: cada valor vale os 4 intervalos de 15 min do periodo.
    spot = np.repeat(np.asarray(hourly, dtype=float), 4)

    # Reservatorio de dias alternativos, para o modelo estocastico do prosumidor
    # amostrar cenarios de carga, geracao e preco (subsecao 6.1.4.1 da tese: a
    # amostragem e feita direto na base de dados).
    load_pool, pv_pool, price_pool = [], [], []
    for d in range(POOL_DAYS):
        offset = DAY_OFFSET + (d + 1) * POOL_DAY_STRIDE
        load_pool.append(np.array([
            peak_kw[node] * _normalize(_slice_day(load_profile,
                                                  f"{load_df.iloc[i % len(load_df)].profile}_pload",
                                                  offset))
            for i, node in enumerate(lv_nodes)]))
        day_pv = []
        for i, node in enumerate(lv_nodes):
            if node in pv_size:
                g = _slice_day(res_profile, gen_df.iloc[i % len(gen_df)].profile, offset)
                g = g / g.max() if g.max() > 0 else g
                day_pv.append(pv_size[node] * g)
            else:
                day_pv.append(np.zeros(PERIODS))
        pv_pool.append(np.array(day_pv))
        h = (SPOT_DAY_OFFSET + d + 1) * 24 + 24 * 30 * 6
        price_pool.append(np.repeat(prices["SpotPriceEUR"].values[h:h + 24].astype(float), 4))

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(load_cols).to_csv(DATA_DIR / "load_kw.csv", index=False)
    pd.DataFrame(pv_cols).to_csv(DATA_DIR / "pv_kw.csv", index=False)
    pd.DataFrame({"price": spot}).to_csv(DATA_DIR / "spot_price.csv", index=False)
    np.savez(DATA_DIR / "scenario_pool.npz",
             nodes=np.array(lv_nodes),
             load=np.array(load_pool),      # (dias, nos, 96)
             pv=np.array(pv_pool),
             price=np.array(price_pool))    # (dias, 96)

    total_load = sum(v.sum() for v in load_cols.values()) * DT_H
    total_pv = sum(v.sum() for v in pv_cols.values()) * DT_H
    print(f"gravado em {DATA_DIR}")
    print(f"  load_kw.csv   {PERIODS}x{len(load_cols)}  energia diaria {total_load:.1f} kWh"
          f"  pico agregado {np.sum(list(load_cols.values()), axis=0).max():.1f} kW")
    print(f"  pv_kw.csv     {PERIODS}x{len(pv_cols)}  energia diaria {total_pv:.1f} kWh"
          f"  pico agregado {np.sum(list(pv_cols.values()), axis=0).max():.1f} kW")
    print(f"  spot_price.csv  {PERIODS} valores, {spot.min():.2f} a {spot.max():.2f}")
    print(f"  scenario_pool.npz  {POOL_DAYS} dias alternativos de carga, PV e preco")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market-simulation",
                    default=str(SIMULATORS_DIR.parents[1].parent / "market-simulation"),
                    help="caminho do repositorio market-simulation (dados de origem)")
    args = ap.parse_args()
    build(args.market_simulation)


if __name__ == "__main__":
    main()
