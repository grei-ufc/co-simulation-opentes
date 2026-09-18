"""Figura MULTI-SEMENTE do experimento de sensibilidade a perda de pacotes.

Agrega varias sementes por nivel de perda: barras = MEDIA, barras de erro =
DESVIO entre sementes. Transforma a sobretensao noturna intermitente numa
FREQUENCIA (em quantas sementes a barra 652 passou de 1,0 pu de madrugada).

Mantem o layout de 4 paineis em barras (mesmo estilo de sensibilidade_perda.png),
so adicionando as barras de erro.

Le output/sensibilidade_perda_multiseed/result_<tag>.csv (tag = baseline,
loss000, loss100, ou lossNNN_sS). Salva sensibilidade_perda_multiseed.png. Uso:
  docker compose run --rm --no-deps \
    -e MOSAIK_OUTPUT_DIR=/app/output/sensibilidade_perda_multiseed \
    mosaik python plot_loss_multiseed.py
"""

import os
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


OUT = Path(os.environ.get("MOSAIK_OUTPUT_DIR", "/app/output/sensibilidade_perda_multiseed"))
CRIT = "652"
PV_BUSES = ["646", "632", "634", "645", "652"]
# 'turbo': cores fortes e de alto contraste em toda a faixa (azul->vermelho),
# para distinguir os muitos niveis de perda (0..100% em passos de 5%).
CMAP = plt.get_cmap("turbo")


def _color(p):
    return CMAP(p / 100.0)


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
    return df[cs].apply(pd.to_numeric, errors="coerce").abs().sum(axis=1)


def _delivered_pct(tag):
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


def _discover():
    """{loss%: [tags]} a partir dos result_*.csv presentes."""
    levels = {}
    for f in OUT.glob("result_loss*.csv"):
        m = re.match(r"result_loss(\d+)(?:_s\d+)?$", f.stem)
        if m:
            levels.setdefault(int(m.group(1)), []).append(f.stem.replace("result_", ""))
    return {k: sorted(v) for k, v in sorted(levels.items())}


def main() -> int:
    if not (OUT / "result_baseline.csv").exists():
        print(f"[plot] falta result_baseline.csv em {OUT}")
        return 1
    levels = _discover()
    if not levels:
        print(f"[plot] nenhum result_loss*.csv em {OUT} — rode ./run.sh loss-multiseed")
        return 1

    base_df = _load("baseline")
    Vb = _vmean(base_df, CRIT)
    base_mean = Vb.mean()

    rows, vday = [], {}  # vday[loss] = (h, mean V652 entre sementes)
    for loss, tags in levels.items():
        lifts, qs, delivs, ovs, vseries = [], [], [], [], []
        h = None
        for tag in tags:
            d = _load(tag)
            V = _vmean(d, CRIT)
            lifts.append(1000 * (V.mean() - base_mean))
            qs.append(_q_total(d).mean())
            delivs.append(_delivered_pct(tag))
            ovs.append(1.0 if V[d["h"] >= 21].max() > 1.05 else 0.0)  # violacao ANEEL (>1,05) a noite
            vseries.append(V.values); h = d["h"].values
        n = len(tags)
        rows.append(dict(
            loss=loss, n=n,
            lift=np.mean(lifts), lift_sd=np.std(lifts),
            q=np.mean(qs), q_sd=np.std(qs),
            deliv=np.nanmean(delivs), deliv_sd=np.nanstd(delivs),
            ov_freq=100 * np.mean(ovs)))
        L = min(len(s) for s in vseries)
        vday[loss] = (h[:L], np.mean([s[:L] for s in vseries], axis=0))
    M = pd.DataFrame(rows).sort_values("loss").reset_index(drop=True)

    print("\n=== Sensibilidade multi-semente (Bus 652) ===")
    print(M.to_string(index=False, float_format=lambda x: f"{x:7.2f}"))
    print("  lift/q/deliv = media entre sementes (±sd); ov_freq = % de sementes com "
          "V652>1,0 pu de madrugada; n = nº de sementes")

    fig, axs = plt.subplots(2, 2, figsize=(15, 10))
    fig.suptitle("OpenTES — Sensibilidade do Volt/Var à perda de pacotes (multi-semente, Bus 652)",
                 fontsize=15, fontweight="bold")
    x = np.arange(len(M)); cols = [_color(p) for p in M["loss"]]
    rots = [f"{int(p)}%" for p in M["loss"]]
    ebar = dict(capsize=3, ecolor="black", error_kw={"lw": 1})

    # 1) tensao da barra 652 ao longo do dia (media entre sementes, por nivel)
    ax = axs[0, 0]
    ax.plot(base_df["h"], Vb, color="black", ls=":", lw=1.5, label="sem controle", zorder=6)
    for loss in M["loss"]:
        hh, vv = vday[loss]
        ax.plot(hh, vv, color=_color(loss), lw=1.6, label=f"{int(loss)}% perda")
    ax.axhline(1.05, color="purple", ls="--", lw=1, label="1,05 pu (limite ANEEL)")
    ax.axhline(0.95, color="#999", ls="--", lw=1, label="ANEEL 0,95")
    ax.set_title("Tensão da barra 652 ao longo do dia (média entre sementes)", fontweight="bold", fontsize=11)
    ax.set_xlabel("Hora do dia"); ax.set_ylabel("Tensão [pu]")
    ax.set_xlim(0, 24); ax.set_xticks(range(0, 25, 4)); ax.grid(alpha=.3)
    ax.legend(fontsize=7, ncol=2, loc="lower center")

    # 2) beneficio (lift medio) com barras de erro
    ax = axs[0, 1]
    bcols = ["#2ca02c" if l > 0.2 else ("#d62728" if l < -0.2 else "#7f7f7f") for l in M["lift"]]
    ax.bar(x, M["lift"], yerr=M["lift_sd"], color=bcols, **ebar)
    ax.axhline(0, color="black", lw=1)
    ax.set_title("Benefício do controle — lift médio vs baseline (±desvio entre sementes)",
                 fontweight="bold", fontsize=11)
    ax.set_ylabel("Δ tensão média [mV]   (+ ajuda / − atrapalha)")
    ax.set_xticks(x); ax.set_xticklabels(rots, fontsize=8); ax.grid(alpha=.3, axis="y")

    # 3) esforco (Q) com barras de erro
    ax = axs[1, 0]
    ax.bar(x, M["q"], yerr=M["q_sd"], color=cols, **ebar)
    ax.set_title("Reativo injetado (médio ± desvio entre sementes)", fontweight="bold", fontsize=11)
    ax.set_ylabel("Σ|Q| médio [kvar]")
    ax.set_xticks(x); ax.set_xticklabels(rots, fontsize=8); ax.grid(alpha=.3, axis="y")

    # 4) FREQUENCIA de sobretensao noturna (a anomalia virou estatistica)
    ax = axs[1, 1]
    ax.bar(x, M["ov_freq"], color=cols)
    ax.set_title("Violação de sobretensão noturna (V652 > 1,05 pu — ANEEL)", fontweight="bold", fontsize=11)
    ax.set_ylabel("% das sementes"); ax.set_ylim(0, 105)
    ax.set_xticks(x); ax.set_xticklabels(rots, fontsize=8); ax.grid(alpha=.3, axis="y")
    for i, (fr, nn) in enumerate(zip(M["ov_freq"], M["n"])):
        ax.text(i, fr + 2, f"{int(round(fr/100*nn))}/{nn}", ha="center", fontsize=8)

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(OUT / "sensibilidade_perda_multiseed.png", dpi=150)
    print(f"\n[plot] {OUT / 'sensibilidade_perda_multiseed.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
