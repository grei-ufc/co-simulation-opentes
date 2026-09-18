"""Figura do estudo de 48h: mostra que o ciclo diário se repete (dia 1 ≈ dia 2)
após a correção do solve. Tensão da barra crítica (652) ao longo de 2 dias, com e
sem controle Volt/Var. Lê output/sensibilidade_48h/result_{baseline,volt_var}.csv.
"""
import os
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

OUT = Path(os.environ.get("MOSAIK_OUTPUT_DIR", "output/sensibilidade_48h"))
CRIT = "652"


def _load(tag):
    d = pd.read_csv(OUT / f"result_{tag}.csv")
    d["date"] = pd.to_datetime(d["date"], format="mixed")
    d["h"] = (d["date"] - d["date"].iloc[0]).dt.total_seconds() / 3600.0
    cs = [c for c in d.columns if f"Bus-{CRIT}-" in c and "_pu" in c]
    s = d[cs].apply(pd.to_numeric, errors="coerce")
    d["V"] = s.where(s > 0.5).mean(axis=1)
    return d


def main():
    b, v = _load("baseline"), _load("volt_var")
    fig, ax = plt.subplots(figsize=(15, 6))
    fig.suptitle("OpenTES — Estudo de 48h: o ciclo diário se repete (Bus 652, após correção do solve)",
                 fontsize=14, fontweight="bold")
    ax.plot(b["h"], b["V"], color="#7f7f7f", lw=1.6, ls=":", label="sem controle (baseline)")
    ax.plot(v["h"], v["V"], color="#2ca02c", lw=1.8, label="com Volt/Var")
    ax.axvline(24, color="black", lw=1.2, alpha=0.6)
    ax.text(24, ax.get_ylim()[1], " fronteira dia 1 | dia 2", va="top", fontsize=9, style="italic")
    ax.axhline(1.05, color="#d62728", ls="--", lw=1, label="limites ANEEL (0,95 / 1,05)")
    ax.axhline(0.95, color="#d62728", ls="--", lw=1)
    for db in [12, 36]:  # meio-dia de cada dia
        ax.axvspan(db - 0.2, db + 0.2, color="#fff3b0", alpha=0.0)
    ax.set_xlabel("Horas decorridas (2 dias)"); ax.set_ylabel("Tensão [pu]")
    ax.set_xlim(0, 48); ax.set_xticks(range(0, 49, 6)); ax.grid(alpha=.3)
    ax.legend(fontsize=10, loc="lower center", ncol=3)
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(OUT / "ciclo_48h.png", dpi=150)
    print(f"[plot] {OUT / 'ciclo_48h.png'}")


if __name__ == "__main__":
    raise SystemExit(main())
