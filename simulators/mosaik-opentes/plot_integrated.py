"""Dashboard COMPLETO do cenario integrado (acoplamento causal Volt/Var, 5 PVs).

Reune, num unico painel, os dois dominios da co-simulacao OpenTES — aproveitando
os graficos do `star` (comunicacao) e do `ieee13` (rede eletrica), agora
ATRELADOS no mesmo cenario, com os 5 inversores co-simulados e sob Volt/Var:

  Entrada climatica (5 PVs):     1) irradiancia solar   2) temperatura dos modulos
  Rede eletrica (IEEE 13):       3) geracao FV agregada 4) tensoes p.u. nas 13 barras
  Rede de comunicacao (OMNeT++): 5) integridade de pacotes (entregues x dropados)
                                 6) latencia exata       7) jitter distribuido
  Controle:                      8) efeito Volt/Var nas 5 barras dos PVs

Le os CSVs de output/integrated/ e os perfis climaticos de entrada; salva
output/integrated/dashboard_integrated.png.
"""

import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


OUT = Path(os.environ.get("MOSAIK_OUTPUT_DIR", "/app/output/integrated"))
DATA = Path(os.environ.get("GRID_DATA_DIR", "/grid-data/13Bus"))
PNG = OUT / "dashboard_integrated.png"

# 13 nos canonicos do IEEE 13 Barras (ignora sourcebus / rg60 / 670 internos).
IEEE13_NODES = ["650", "632", "633", "634", "645", "646", "671",
                "692", "675", "680", "684", "611", "652"]
# barras dos 5 PVs (PV1@646, PV2@632, PV3@634, PV4@645, PV5@652)
PV_BUSES = ["646", "632", "634", "645", "652"]
PMPP = {"1": 5000.0, "2": 3000.0, "3": 3000.0, "4": 2000.0, "5": 2000.0}


def _load(tag):
    df = pd.read_csv(OUT / f"result_{tag}.csv")
    df["date"] = pd.to_datetime(df["date"], format="mixed")
    df = df.set_index("date")
    df["h"] = df.index.hour + df.index.minute / 60.0
    return df


def _vmean(df, bus):
    cs = [c for c in df.columns if f"Bus-{bus}-" in c and "_pu" in c]
    return df[cs].where(df[cs] > 0.5).mean(axis=1) if cs else None


def _col(df, key):
    cs = [c for c in df.columns if key in c]
    return df[cs[0]] if cs else None


def _flatten_comm(tag, attr):
    df = pd.read_csv(OUT / f"comm_trace_{tag}.csv")
    sub = df[df["Atributo"] == attr]
    hs, vs = [], []
    for _, r in sub.iterrows():
        h = int(r["Tempo"]) / 3600.0
        for x in str(r["Valor"]).split("|||"):
            if x not in ("", "nan"):
                try:
                    vs.append(float(x)); hs.append(h)
                except ValueError:
                    pass
    return hs, vs


def _packets(tag):
    df = pd.read_csv(OUT / f"comm_trace_{tag}.csv")
    df = df[df["Atributo"].isin(["packets_sent", "packets_received", "packets_dropped"])].copy()
    df["Valor"] = pd.to_numeric(df["Valor"], errors="coerce")
    p = df.pivot_table(index="Tempo", columns="Atributo", values="Valor", aggfunc="first")
    return int(p["packets_sent"].max()), int(p["packets_received"].max()), int(p["packets_dropped"].max())


def main() -> int:
    for tag in ("baseline", "volt_var"):
        if not (OUT / f"result_{tag}.csv").exists():
            print(f"[plot] falta result_{tag}.csv — rode ./run.sh integrated")
            return 1

    b, v = _load("baseline"), _load("volt_var")
    hv = v["h"].values
    df_irr = pd.read_csv(DATA / "ieee13_shape_pv_5min.csv")
    df_tmp = pd.read_csv(DATA / "ieee13_temperature_5min.csv")
    h_in = [i * 5.0 / 60.0 for i in range(len(df_irr))]

    fig, axs = plt.subplots(4, 2, figsize=(17, 18))
    fig.suptitle(
        "OpenTES — Dashboard da Co-simulação Integrada IEEE 13 Barras (5 PVs, rede elétrica ⟷ comunicação)",
        fontsize=16, fontweight="bold",
    )

    # 1) Irradiancia
    ax = axs[0, 0]
    for c in [c for c in df_irr.columns if "irrad" in c]:
        ax.plot(h_in, df_irr[c], lw=1.5, label=c.replace("my_shape", "PV ").replace("_irrad", ""))
    ax.set_title("1) Irradiância solar (entrada climática — 5 PVs)", fontweight="bold", fontsize=11)
    ax.set_ylabel("Irradiância [pu]"); ax.legend(fontsize=8, ncol=5); ax.grid(alpha=.4)

    # 2) Temperatura
    ax = axs[0, 1]
    for c in [c for c in df_tmp.columns if "temperature" in c]:
        ax.plot(h_in, df_tmp[c], lw=1.5, label=c.replace("my_shape", "PV ").replace("_temperature", ""))
    ax.set_title("2) Temperatura dos módulos (entrada climática — 5 PVs)", fontweight="bold", fontsize=11)
    ax.set_ylabel("Temperatura [pu]"); ax.legend(fontsize=8, ncol=5); ax.grid(alpha=.4)

    # 3) Geracao FV agregada: Sigma P_meas injetado (5 PVs) e Sigma disponivel
    ax = axs[1, 0]
    pv_cols = [c for c in v.columns if "PVSystem-pv" in c and "P_meas" in c]
    if pv_cols:
        gen = v[pv_cols].sum(axis=1)
        if gen.median() < 0:
            gen = -gen
        ax.plot(hv, gen, color="#2ca02c", lw=2.0, label=f"Σ P_meas injetado ({len(pv_cols)} PVs)")
    gen_av = None
    for n, pmpp in PMPP.items():
        c = f"my_shape{n}_irrad"
        if c in df_irr.columns:
            gen_av = df_irr[c] * pmpp if gen_av is None else gen_av + df_irr[c] * pmpp
    if gen_av is not None:
        ax.plot(h_in, gen_av, color="#d62728", lw=1.4, ls="--", label="Σ disponível (irradiância × Pmpp)")
    ax.set_title("3) Geração fotovoltaica agregada (5 PVs co-simulados)", fontweight="bold", fontsize=11)
    ax.set_ylabel("Potência [kW]"); ax.legend(fontsize=8); ax.grid(alpha=.4)

    # 4) Tensoes p.u. nas 13 barras canonicas (caso Volt/Var)
    ax = axs[1, 1]
    for bus in IEEE13_NODES:
        s = _vmean(v, bus)
        if s is not None and s.notna().any():
            ax.plot(hv, s, lw=1.0, label=bus)
    ax.axhline(1.05, color="grey", ls=":", lw=0.8); ax.axhline(0.95, color="grey", ls=":", lw=0.8)
    ax.set_title("4) Tensões nas 13 barras (p.u.) — caso Volt/Var (limites ANEEL)", fontweight="bold", fontsize=11)
    ax.set_ylabel("Tensão [pu]"); ax.legend(fontsize=7, ncol=7, loc="lower center"); ax.grid(alpha=.4)

    # 5) Integridade de pacotes — PIZZA (estilo grafico_trafego.png)
    ax = axs[2, 0]
    sent, rec, drop = _packets("volt_var")
    deliv = sent - drop
    if drop > 0:
        ax.pie([deliv, drop],
               labels=[f"Entregues\n{deliv}", f"Dropados\n{drop}"],
               colors=["#2ca02c", "#d62728"], autopct="%1.1f%%", startangle=140,
               wedgeprops={"edgecolor": "black"}, textprops={"fontsize": 10})
    else:
        ax.pie([sent], labels=[f"Entregues\n{sent}"], colors=["#2ca02c"],
               autopct="%1.1f%%", startangle=140, wedgeprops={"edgecolor": "black"})
    ax.set_title(f"5) Integridade dos pacotes (enviados: {sent} | perda {100*drop/sent:.1f}%)",
                 fontweight="bold", fontsize=11)

    # 6) Latencia exata por pacote
    ax = axs[2, 1]
    hl, lat = _flatten_comm("volt_var", "latencies_out")
    ax.scatter(hl, [x * 1000 for x in lat], s=10, color="#9467bd", alpha=0.5)
    ax.set_title("6) Latência exata por pacote", fontweight="bold", fontsize=11)
    ax.set_ylabel("Latência [ms]"); ax.set_xlim(0, 24); ax.set_xticks(range(0, 25, 4)); ax.grid(alpha=.4)

    # 7) Jitter distribuido
    ax = axs[3, 0]
    hj, jit = _flatten_comm("volt_var", "jitters_out")
    ax.scatter(hj, [x * 1000 for x in jit], s=10, color="#8c564b", alpha=0.5)
    ax.set_title("7) Jitter distribuído (atraso estocástico por pacote)", fontweight="bold", fontsize=11)
    ax.set_ylabel("Jitter [ms]"); ax.set_xlabel("Hora do dia")
    ax.set_xlim(0, 24); ax.set_xticks(range(0, 25, 4)); ax.grid(alpha=.4)

    # 8) Efeito Volt/Var nas 5 barras dos PVs (baseline tracejado x controle solido)
    ax = axs[3, 1]
    cores = ["#1f77b4", "#ff7f0e", "#2ca02c", "#9467bd", "#8c564b"]
    for bus, cor in zip(PV_BUSES, cores):
        vb, vv = _vmean(b, bus), _vmean(v, bus)
        if vb is not None:
            ax.plot(b["h"], vb, color=cor, lw=0.9, ls=":", alpha=0.7)
            ax.plot(hv, vv, color=cor, lw=1.5, label=f"Bus {bus}")
    ax.axhspan(0.98, 1.02, color="grey", alpha=0.12)  # faixa morta do Volt/Var
    ax.axhline(1.0, color="grey", ls=":", lw=0.8)
    ax.set_title("8) Efeito Volt/Var nas 5 barras PV  (····· baseline | —— com controle)",
                 fontweight="bold", fontsize=11)
    ax.set_ylabel("Tensão [pu]"); ax.set_xlabel("Hora do dia")
    ax.set_xlim(0, 24); ax.set_xticks(range(0, 25, 4))
    ax.legend(fontsize=8, ncol=5, loc="lower center"); ax.grid(alpha=.4)

    plt.tight_layout(rect=[0, 0, 1, 0.97])
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(PNG, dpi=140)
    print(f"[plot] dashboard salvo em {PNG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
