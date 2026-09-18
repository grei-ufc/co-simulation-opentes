"""Figura do experimento de SENSIBILIDADE do Volt/Var a perda de pacotes.

Le output/sensibilidade_perda/result_{baseline,loss000,loss050,loss100}.csv
(+ comm_trace_*.csv) e mostra como o controle distribuido degrada conforme a
comunicacao piora:

  baseline      -> sem controle (referencia, piso de tensao)
  loss000       -> Volt/Var com 0% de perda  (controle pleno)
  loss050       -> Volt/Var com 50% de perda (controle parcial)
  loss100       -> Volt/Var com 100% de perda (sem comunicacao ~ baseline)

Salva sensibilidade_perda.png. Uso:
  docker compose run --rm --no-deps -e MOSAIK_OUTPUT_DIR=/app/output/sensibilidade_perda \
    mosaik python plot_loss_sweep.py
"""

import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


OUT = Path(os.environ.get("MOSAIK_OUTPUT_DIR", "/app/output/sensibilidade_perda"))
CRIT = "652"  # barra PV mais critica (subtensao)
PV_BUSES = ["646", "632", "634", "645", "652"]
# (tag, rotulo, cor) — gradiente verde (sem perda) -> vermelho (perda total)
RUNS = [
    ("baseline", "sem controle",          "#7f7f7f"),
    ("loss000",  "Volt/Var · 0% perda",   "#2ca02c"),
    ("loss025",  "Volt/Var · 25% perda",  "#9acd32"),
    ("loss030",  "Volt/Var · 30% perda",  "#cddc00"),
    ("loss035",  "Volt/Var · 35% perda",  "#ffd400"),
    ("loss040",  "Volt/Var · 40% perda",  "#ffb000"),
    ("loss045",  "Volt/Var · 45% perda",  "#ff9500"),
    ("loss050",  "Volt/Var · 50% perda",  "#ff7f0e"),
    ("loss075",  "Volt/Var · 75% perda",  "#e6550d"),
    ("loss100",  "Volt/Var · 100% perda", "#d62728"),
]


def _load(tag):
    df = pd.read_csv(OUT / f"result_{tag}.csv")
    df["date"] = pd.to_datetime(df["date"], format="mixed")
    df["h"] = df["date"].dt.hour + df["date"].dt.minute / 60.0
    return df


def _vmean(df, bus):
    cs = [c for c in df.columns if f"Bus-{bus}-" in c and "_pu" in c]
    s = df[cs].apply(pd.to_numeric, errors="coerce")
    return s.where(s > 0.5).mean(axis=1)


def _q_total(df):
    cs = [c for c in df.columns if "Q_meas" in c]
    s = df[cs].apply(pd.to_numeric, errors="coerce").abs()
    return s.sum(axis=1)


def _delivered_pct(tag):
    """% entregue = entregues / tentativas. No trace, packets_sent espelha
    packets_received e ambos contam os ENTREGUES (encaminhados); packets_dropped
    e a parte. Logo tentativas = sent + dropped e entregue% = sent/(sent+drop)."""
    f = OUT / f"comm_trace_{tag}.csv"
    if not f.exists():
        return np.nan
    ct = pd.read_csv(f)
    t = ct[ct["Atributo"].isin(["packets_sent", "packets_dropped"])].copy()
    t["Valor"] = pd.to_numeric(t["Valor"], errors="coerce")
    piv = t.pivot_table(index="Tempo", columns="Atributo", values="Valor", aggfunc="first")
    sent = piv["packets_sent"].max()
    drop = piv["packets_dropped"].max() if "packets_dropped" in piv else 0
    tot = sent + drop
    return 100.0 * sent / tot if tot else np.nan


def main() -> int:
    runs = [r for r in RUNS if (OUT / f"result_{r[0]}.csv").exists()]
    if not runs:
        print(f"[plot] nenhum result_*.csv em {OUT} — rode ./run.sh loss-sweep")
        return 1
    data = {tag: _load(tag) for tag, _, _ in runs}

    # metricas por cenario (lift = efeito vs baseline; med = robusto, min = pior instante)
    rows = []
    Vb = _vmean(data["baseline"], CRIT) if "baseline" in data else None
    base_mean = Vb.mean() if Vb is not None else np.nan
    base_min = Vb.min() if Vb is not None else np.nan
    for tag, rot, cor in runs:
        df = data[tag]
        V = _vmean(df, CRIT)
        sig = float(np.mean([_vmean(df, b).std() for b in PV_BUSES]))
        rows.append(dict(
            tag=tag, rot=rot, cor=cor,
            vmean=V.mean(), vmin=V.min(),
            lift_med=1000 * (V.mean() - base_mean),   # beneficio MEDIO (robusto)
            lift_min=1000 * (V.min() - base_min),      # beneficio no pior instante
            tbelow=100 * (V < 0.95).mean(),            # % do dia em subtensao
            sig=sig, q=_q_total(df).mean(), deliv=_delivered_pct(tag)))
    M = pd.DataFrame(rows)

    print("\n=== Sensibilidade do Volt/Var a perda de pacotes (Bus 652) ===")
    print(M[["rot", "deliv", "vmean", "lift_med", "vmin", "tbelow", "q"]].to_string(
        index=False, float_format=lambda x: f"{x:8.3f}"))
    print("  deliv=% entregue | lift_med=mV vs baseline (+ ajuda, - atrapalha) | "
          "tbelow=% do dia <0,95 | q=Σ|Q| médio [kvar]")

    # ---- figura 2x2 ----
    fig, axs = plt.subplots(2, 2, figsize=(15, 10))
    fig.suptitle("OpenTES — Sensibilidade do controle Volt/Var à perda de pacotes (Bus 652)",
                 fontsize=15, fontweight="bold")

    # 1) tensao da barra critica ao longo do dia
    ax = axs[0, 0]
    for tag, rot, cor in runs:
        ls = ":" if tag == "baseline" else "-"
        lw = 1.3 if tag == "baseline" else 1.8
        ax.plot(data[tag]["h"], _vmean(data[tag], CRIT), color=cor, lw=lw, ls=ls, label=rot)
    ax.axhline(0.95, color="#999", ls="--", lw=1, label="limite ANEEL (0,95)")
    ax.set_title("Tensão da barra crítica (Bus 652) ao longo do dia", fontweight="bold", fontsize=11)
    ax.set_xlabel("Hora do dia"); ax.set_ylabel("Tensão [pu]")
    ax.set_xlim(0, 24); ax.set_xticks(range(0, 25, 4)); ax.grid(alpha=.3)
    ax.legend(fontsize=8, loc="lower center")

    x = np.arange(len(M)); cores = M["cor"].tolist()
    # rotulos compactos nas barras (so a % de perda); legenda completa fica no painel 1
    rots = ["sem\nctrl" if t == "baseline" else f"{int(t.replace('loss','')):d}%" for t in M["tag"]]

    # 2) BENEFICIO do controle = lift medio de tensao vs baseline (+ ajuda / - atrapalha)
    ax = axs[0, 1]
    bar_cols = ["#2ca02c" if l > 0.2 else ("#d62728" if l < -0.2 else "#7f7f7f") for l in M["lift_med"]]
    ax.bar(x, M["lift_med"], color=bar_cols)
    ax.axhline(0, color="black", lw=1)
    ax.set_title("Benefício do controle — lift MÉDIO de tensão vs baseline (Bus 652)",
                 fontweight="bold", fontsize=11)
    ax.set_ylabel("Δ tensão média [mV]   (+ ajuda / − atrapalha)")
    ax.set_xticks(x); ax.set_xticklabels(rots, fontsize=8); ax.grid(alpha=.3, axis="y")
    for i, l in enumerate(M["lift_med"]):
        ax.text(i, l + (0.3 if l >= 0 else -0.5), f"{l:+.1f}", ha="center",
                va="bottom" if l >= 0 else "top", fontsize=9, fontweight="bold")

    # 3) reativo total injetado (esforco de controle)
    ax = axs[1, 0]
    ax.bar(x, M["q"], color=cores)
    ax.set_title("Reativo injetado pelos 5 inversores (médio) — esforço de controle",
                 fontweight="bold", fontsize=11)
    ax.set_ylabel("Σ|Q| médio [kvar]")
    ax.set_xticks(x); ax.set_xticklabels(rots, fontsize=8); ax.grid(alpha=.3, axis="y")
    for i, qq in enumerate(M["q"]):
        ax.text(i, qq, f"{qq:.0f}", ha="center", va="bottom", fontsize=8)

    # 4) informacao entregue vs efeito do controle
    ax = axs[1, 1]
    ax.bar(x, M["deliv"], color=cores)
    ax.set_title("Informação entregue ao controlador (% dos pacotes)", fontweight="bold", fontsize=11)
    ax.set_ylabel("Entregues [%]"); ax.set_ylim(0, 105)
    ax.set_xticks(x); ax.set_xticklabels(rots, fontsize=8); ax.grid(alpha=.3, axis="y")
    for i, dd in enumerate(M["deliv"]):
        txt = "n/d" if np.isnan(dd) else f"{dd:.0f}%"
        ax.text(i, (0 if np.isnan(dd) else dd) + 2, txt, ha="center", fontsize=8)

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(OUT / "sensibilidade_perda.png", dpi=150)
    print(f"\n[plot] {OUT / 'sensibilidade_perda.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
