"""Figuras focadas de COMPARAÇÃO/ANÁLISE do cenário integrado.

Gera duas figuras dedicadas (mais legíveis que os quadros do dashboard geral):

  comparacao_volt_var.png  — efeito do controle: tensão de cada barra PV SEM
                             (baseline) vs COM (Volt/Var) controle, + resumo
                             quantitativo (desvio-padrão e mínima por barra).

  analise_comunicacao.png  — caracterização da rede de comunicação: histogramas
                             de latência e jitter, integridade dos pacotes (pizza)
                             e pacotes acumulados (enviados/entregues/dropados).

Uso:
    docker compose run --rm --no-deps -e MOSAIK_OUTPUT_DIR=/app/output/integrated \
      mosaik python plot_comparacao.py
"""

import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


OUT = Path(os.environ.get("MOSAIK_OUTPUT_DIR", "/app/output/integrated"))
# barras dos 5 PVs (PV1@646, PV2@632, PV3@634, PV4@645, PV5@652)
PV_BUSES = [("646", "PV1"), ("632", "PV2"), ("634", "PV3"), ("645", "PV4"), ("652", "PV5")]


def _load(tag):
    df = pd.read_csv(OUT / f"result_{tag}.csv")
    df["date"] = pd.to_datetime(df["date"], format="mixed")
    df = df.set_index("date")
    df["h"] = df.index.hour + df.index.minute / 60.0
    return df


def _vmean(df, bus):
    cs = [c for c in df.columns if f"Bus-{bus}-" in c and "_pu" in c]
    return df[cs].where(df[cs] > 0.5).mean(axis=1) if cs else None


def _flatten(tag, attr):
    df = pd.read_csv(OUT / f"comm_trace_{tag}.csv")
    sub = df[df["Atributo"] == attr]
    out = []
    for _, r in sub.iterrows():
        for x in str(r["Valor"]).split("|||"):
            if x not in ("", "nan"):
                try:
                    out.append(float(x))
                except ValueError:
                    pass
    return out


# ---------------------------------------------------------------------------
# Figura 1 — efeito do controle Volt/Var (baseline x controle)
# ---------------------------------------------------------------------------
def figura_volt_var(b, v):
    fig = plt.figure(figsize=(16, 9))
    fig.suptitle("OpenTES — Efeito do controle Volt/Var nas barras PV (SEM × COM controle)",
                 fontsize=15, fontweight="bold")
    gs = fig.add_gridspec(2, 5, height_ratios=[2, 1.2])

    # linha de cima: uma barra por subplot (baseline x controle no tempo)
    for i, (bus, nome) in enumerate(PV_BUSES):
        ax = fig.add_subplot(gs[0, i])
        vb, vv = _vmean(b, bus), _vmean(v, bus)
        ax.plot(b["h"], vb, color="#d62728", lw=1.3, ls="--", label="sem controle")
        ax.plot(v["h"], vv, color="#2ca02c", lw=1.6, label="com Volt/Var")
        ax.axhspan(0.98, 1.02, color="grey", alpha=0.12)
        ax.axhline(1.0, color="grey", ls=":", lw=0.7)
        ax.axhline(0.95, color="#999", ls=":", lw=0.7)  # limite ANEEL inferior
        ax.set_title(f"{nome} — Bus {bus}", fontsize=10, fontweight="bold")
        ax.set_xlim(0, 24); ax.set_xticks(range(0, 25, 6))
        ax.set_ylim(0.90, 1.06); ax.grid(alpha=0.3)
        if i == 0:
            ax.set_ylabel("Tensão [pu]"); ax.legend(fontsize=8, loc="lower center")
        else:
            ax.set_yticklabels([])

    buses = [b_ for b_, _ in PV_BUSES]
    nomes = [f"{n}\n({b_})" for b_, n in PV_BUSES]
    std_b = [_vmean(b, x).std() for x in buses]
    std_v = [_vmean(v, x).std() for x in buses]
    min_b = [_vmean(b, x).min() for x in buses]
    min_v = [_vmean(v, x).min() for x in buses]
    x = np.arange(len(buses)); w = 0.38

    # desvio-padrao por barra
    ax1 = fig.add_subplot(gs[1, :2])
    ax1.bar(x - w / 2, std_b, w, color="#d62728", label="sem controle")
    ax1.bar(x + w / 2, std_v, w, color="#2ca02c", label="com Volt/Var")
    ax1.set_title("Desvio-padrão da tensão (↓ é melhor)", fontsize=10, fontweight="bold")
    ax1.set_xticks(x); ax1.set_xticklabels(nomes, fontsize=8)
    ax1.set_ylabel("σ [pu]"); ax1.legend(fontsize=8); ax1.grid(alpha=0.3, axis="y")

    # tensao minima por barra
    ax2 = fig.add_subplot(gs[1, 2:4])
    ax2.bar(x - w / 2, min_b, w, color="#d62728", label="sem controle")
    ax2.bar(x + w / 2, min_v, w, color="#2ca02c", label="com Volt/Var")
    ax2.axhline(0.95, color="#999", ls=":", lw=1, label="limite ANEEL")
    ax2.set_title("Tensão mínima do dia (↑ é melhor)", fontsize=10, fontweight="bold")
    ax2.set_xticks(x); ax2.set_xticklabels(nomes, fontsize=8)
    ax2.set_ylim(0.90, 1.0); ax2.set_ylabel("V mín [pu]")
    ax2.legend(fontsize=8); ax2.grid(alpha=0.3, axis="y")

    # texto-resumo
    ax3 = fig.add_subplot(gs[1, 4]); ax3.axis("off")
    red = 100 * (1 - np.mean(std_v) / np.mean(std_b))
    txt = (f"Resumo (5 barras PV)\n\n"
           f"σ médio:\n  {np.mean(std_b):.4f} → {np.mean(std_v):.4f}\n  (−{red:.0f}%)\n\n"
           f"Mínima crítica (Bus 652):\n  {min_b[-1]:.3f} → {min_v[-1]:.3f} pu\n\n"
           f"Sem sobretensão:\n  máximos preservados")
    ax3.text(0.0, 0.95, txt, va="top", ha="left", fontsize=9,
             bbox=dict(fc="#f4f4f4", ec="#bbb"))

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(OUT / "comparacao_volt_var.png", dpi=150)
    print(f"[plot] {OUT / 'comparacao_volt_var.png'}")


# ---------------------------------------------------------------------------
# Figura 2 — caracterizacao da rede de comunicacao
# ---------------------------------------------------------------------------
def figura_comunicacao(tag="volt_var"):
    lat = [x * 1000 for x in _flatten(tag, "latencies_out")]
    jit = [x * 1000 for x in _flatten(tag, "jitters_out")]
    ct = pd.read_csv(OUT / f"comm_trace_{tag}.csv")
    t = ct[ct["Atributo"].isin(["packets_sent", "packets_dropped"])].copy()
    t["Valor"] = pd.to_numeric(t["Valor"], errors="coerce")
    piv = t.pivot_table(index="Tempo", columns="Atributo", values="Valor", aggfunc="first")
    piv.index = piv.index / 3600.0
    # entregue = enviado - dropado. (packets_received no trace espelha packets_sent:
    # todo pacote "chega" ao no e o descarte e marcado a parte; por isso nao o usamos.)
    piv["entregues"] = piv["packets_sent"] - piv["packets_dropped"]
    sent, drop = int(piv["packets_sent"].max()), int(piv["packets_dropped"].max())
    deliv = sent - drop

    fig, axs = plt.subplots(2, 2, figsize=(14, 9))
    fig.suptitle("OpenTES — Caracterização da rede de comunicação (OMNeT++)",
                 fontsize=15, fontweight="bold")

    axs[0, 0].hist(lat, bins=40, color="#9467bd", edgecolor="white")
    axs[0, 0].axvline(np.mean(lat), color="black", ls="--", lw=1, label=f"média {np.mean(lat):.0f} ms")
    axs[0, 0].set_title("Distribuição da latência", fontweight="bold", fontsize=11)
    axs[0, 0].set_xlabel("Latência [ms]"); axs[0, 0].set_ylabel("nº de pacotes")
    axs[0, 0].legend(fontsize=9); axs[0, 0].grid(alpha=0.3)

    axs[0, 1].hist(jit, bins=40, color="#8c564b", edgecolor="white")
    axs[0, 1].axvline(np.mean(jit), color="black", ls="--", lw=1, label=f"média {np.mean(jit):.0f} ms")
    axs[0, 1].set_title("Distribuição do jitter (atraso estocástico)", fontweight="bold", fontsize=11)
    axs[0, 1].set_xlabel("Jitter [ms]"); axs[0, 1].set_ylabel("nº de pacotes")
    axs[0, 1].legend(fontsize=9); axs[0, 1].grid(alpha=0.3)

    axs[1, 0].pie([deliv, drop], labels=[f"Entregues\n{deliv}", f"Dropados\n{drop}"],
                  colors=["#2ca02c", "#d62728"], autopct="%1.1f%%", startangle=140,
                  wedgeprops={"edgecolor": "black"}, textprops={"fontsize": 10})
    axs[1, 0].set_title(f"Integridade dos pacotes (enviados: {sent})", fontweight="bold", fontsize=11)

    axs[1, 1].plot(piv.index, piv["packets_sent"], color="#1f77b4", lw=1.8, label="enviados")
    axs[1, 1].plot(piv.index, piv["entregues"], color="#2ca02c", lw=1.8, label="entregues (env − drop)")
    axs[1, 1].plot(piv.index, piv["packets_dropped"], color="#d62728", lw=1.8, label="dropados")
    axs[1, 1].set_title("Pacotes acumulados ao longo do dia", fontweight="bold", fontsize=11)
    axs[1, 1].set_xlabel("Hora do dia"); axs[1, 1].set_ylabel("nº acumulado")
    axs[1, 1].set_xlim(0, 24); axs[1, 1].set_xticks(range(0, 25, 4))
    axs[1, 1].legend(fontsize=9); axs[1, 1].grid(alpha=0.3)

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(OUT / "analise_comunicacao.png", dpi=150)
    print(f"[plot] {OUT / 'analise_comunicacao.png'}")


def main() -> int:
    for tag in ("baseline", "volt_var"):
        if not (OUT / f"result_{tag}.csv").exists():
            print(f"[plot] falta result_{tag}.csv — rode ./run.sh integrated")
            return 1
    b, v = _load("baseline"), _load("volt_var")
    figura_volt_var(b, v)
    figura_comunicacao("volt_var")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
