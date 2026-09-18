"""Dashboard de apresentacao do cenario IEEE 13 Bus Smart PV.

Le o CSV de resultado da co-simulacao (output/result_run_ieee13_cosim_pv_5min.csv)
e os perfis climaticos de entrada, e gera um painel com 4 graficos pensados para
apresentacao:

  1. Irradiancia solar (perfil do dia) - entrada climatica por PV.
  2. Geracao fotovoltaica - P_dc dos paineis (DC) e P_meas injetado na rede.
  3. Tensoes nas barras monitoradas (V_pu) ao longo do dia - so fases existentes.
  4. Temperatura dos modulos - entrada climatica por PV.

Por default usa backend Agg e salva em output/ieee13_dashboard.png. Passe
--show para abrir interativamente (WebAgg).

Uso:
    docker compose run --rm --no-deps mosaik python plot_ieee13.py
"""

import argparse
import os
import sys
from pathlib import Path

import matplotlib

if "--show" in sys.argv:
    matplotlib.use("WebAgg")
else:
    matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd


REPO_DATA_DIR = Path(os.environ.get("GRID_DATA_DIR", "/grid-data/13Bus"))
OUTPUT_DIR = Path(os.environ.get("MOSAIK_OUTPUT_DIR", "/app/output/ieee13"))

CSV_IRRAD_IN = REPO_DATA_DIR / "ieee13_shape_pv_5min.csv"
CSV_TEMP_IN = REPO_DATA_DIR / "ieee13_temperature_5min.csv"
RESULT_CSV = OUTPUT_DIR / "result_run_ieee13_cosim_pv_5min.csv"
DASHBOARD_PNG = OUTPUT_DIR / "ieee13_dashboard.png"


def _load_result():
    df = pd.read_csv(RESULT_CSV)
    df["date"] = pd.to_datetime(df["date"], format="mixed")
    return df.set_index("date")


def plot_comprehensive_results(show: bool = False) -> int:
    for p in (CSV_IRRAD_IN, CSV_TEMP_IN, RESULT_CSV):
        if not p.exists():
            print(f"[plot] arquivo nao encontrado: {p}")
            return 1

    print("[plot] carregando datasets...")
    df_irr = pd.read_csv(CSV_IRRAD_IN)
    df_tmp = pd.read_csv(CSV_TEMP_IN)
    df = _load_result()
    if df.empty:
        print("[plot] resultado vazio")
        return 1

    hours = df.index.hour + df.index.minute / 60.0

    pdc_cols = [c for c in df.columns if "P_dc" in c]
    pmeas_cols = [c for c in df.columns if "P_meas" in c]
    # tensoes: ignora fases inexistentes (trechos monofasicos -> ~0)
    vpu_cols = [c for c in df.columns if "_pu" in c and df[c].mean() > 0.5]

    fig, axs = plt.subplots(4, 1, figsize=(14, 13), sharex=False)
    fig.suptitle(
        "OpenTES — Co-simulação IEEE 13 Bus + Smart PV (1 dia, passo de 5 min)",
        fontsize=16, fontweight="bold",
    )

    # eixo X em hora do dia (cada amostra de entrada = 5 min a partir da meia-noite)
    h_irr = [i * 5.0 / 60.0 for i in range(len(df_irr))]
    h_tmp = [i * 5.0 / 60.0 for i in range(len(df_tmp))]

    # 1. Irradiancia
    irr_cols = [c for c in df_irr.columns if c.lower() not in ("time", "timestamp", "date", "index")]
    for col in irr_cols:
        axs[0].plot(h_irr, df_irr[col], linewidth=1.6, label=col.replace("my_shape", "PV ").replace("_irrad", ""))
    axs[0].set_title("1) Irradiância solar (entrada climática)", fontsize=11, fontweight="bold")
    axs[0].set_ylabel("Irradiância [pu]")
    axs[0].set_xlabel("Hora do dia")
    axs[0].set_xlim(0, 24); axs[0].set_xticks(range(0, 25, 2))
    axs[0].grid(True, linestyle="--", alpha=0.5)
    axs[0].legend(loc="upper right", fontsize=8, ncol=5)

    # 2. Geracao PV: P_dc total e P_meas total
    if pdc_cols:
        axs[1].plot(hours, df[pdc_cols].sum(axis=1), color="#d62728", linewidth=2.2, label="ΣP_dc painéis (DC)")
    if pmeas_cols:
        axs[1].plot(hours, df[pmeas_cols].sum(axis=1), color="#2ca02c", linewidth=2.2, linestyle="--", label="ΣP_meas injetado na rede")
    axs[1].set_title("2) Geração fotovoltaica agregada (5 PVs, Pmpp total = 15 MW)", fontsize=11, fontweight="bold")
    axs[1].set_ylabel("Potência [kW]")
    axs[1].set_xlabel("Hora do dia")
    axs[1].set_xlim(0, 24); axs[1].set_xticks(range(0, 25, 2))
    axs[1].grid(True, linestyle="--", alpha=0.5)
    axs[1].legend(loc="upper right", fontsize=9)

    # 3. Tensoes nas barras
    for col in sorted(vpu_cols):
        label = col.replace("DSS-0.", "").replace("Bus-", "Barra ").replace("_pu", "")
        axs[2].plot(hours, df[col], linewidth=1.3, label=label)
    axs[2].axhline(1.05, color="grey", linestyle=":", linewidth=1)
    axs[2].axhline(0.92, color="grey", linestyle=":", linewidth=1)
    axs[2].set_title("3) Tensões nas barras (V_pu) — limites ANEEL 0.92–1.05 pu tracejados", fontsize=11, fontweight="bold")
    axs[2].set_ylabel("Tensão [pu]")
    axs[2].set_xlabel("Hora do dia")
    axs[2].set_xlim(0, 24); axs[2].set_xticks(range(0, 25, 2))
    axs[2].set_ylim(0.88, 1.08)
    axs[2].grid(True, linestyle="--", alpha=0.5)
    axs[2].legend(loc="lower left", fontsize=7, ncol=5)

    # 4. Temperatura
    tmp_cols = [c for c in df_tmp.columns if c.lower() not in ("time", "timestamp", "date", "index")]
    for col in tmp_cols:
        axs[3].plot(h_tmp, df_tmp[col], linewidth=1.6, label=col.replace("my_shape", "PV ").replace("_temperature", ""))
    axs[3].set_title("4) Temperatura dos módulos (entrada climática)", fontsize=11, fontweight="bold")
    axs[3].set_ylabel("Temperatura [pu]")
    axs[3].set_xlabel("Hora do dia")
    axs[3].set_xlim(0, 24); axs[3].set_xticks(range(0, 25, 2))
    axs[3].grid(True, linestyle="--", alpha=0.5)
    axs[3].legend(loc="upper right", fontsize=8, ncol=5)

    plt.tight_layout(rect=[0, 0, 1, 0.97])
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(DASHBOARD_PNG, dpi=150)
    print(f"[plot] dashboard salvo em {DASHBOARD_PNG}")
    if show:
        plt.show()
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show", action="store_true", help="exibe via WebAgg")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    raise SystemExit(plot_comprehensive_results(show=args.show))
