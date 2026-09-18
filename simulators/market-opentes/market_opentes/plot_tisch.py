"""Figura da rede LPWA 6TiSCH (Fase 5): PER por distancia e alcance.

Reproduz a Figura 42 da tese a partir do levantamento de enlaces que o
`comm-opentes/Tisch.cc` grava no arranque (`tisch_links.csv`), e acrescenta o que
a figura da tese nao mostra: quais desses enlaces sobrevivem ao limiar de PER 0,5
e viram aresta da matriz de adjacencia.

Mesma paleta e mesma gramatica visual das outras figuras do mercado.
"""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]
INK = "#0b0b0b"
MUTED = "#52514e"
GRID = "0.85"
PER_THRESHOLD = 0.5


def _style(ax, xlabel, ylabel, title):
    ax.set_xlabel(xlabel, color=MUTED, fontsize=9)
    ax.set_ylabel(ylabel, color=MUTED, fontsize=9)
    ax.set_title(title, color=INK, fontsize=11, loc="left")
    ax.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8)


def plot(links_csv, out_png, max_distance=1000.0):
    df = pd.read_csv(links_csv)
    df = df[df["distance_m"] > 0]
    near = df[df["distance_m"] <= max_distance]

    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.0))

    # (a) PER por distancia: a Figura 42 da tese. O espalhamento vertical e o
    # Pister-Hack: a 1 km ha enlaces com PER baixo, porque o desvio sorteado
    # daquele par calhou de ser pequeno.
    ax = axes[0]
    # Separar por enlace ou nao evita uma leitura errada. A adjacencia vem da
    # matriz publicada, e o PER vem do modelo de propagacao: existem pares com
    # PER abaixo do limiar que a matriz NAO declara como enlace, porque o
    # orcamento de enlace real da tese e mais apertado que o do modelo. Pintar
    # tudo de uma cor so faria esses pontos parecerem contradicao.
    com = near[near["adjacent"] == 1]
    sem = near[near["adjacent"] == 0]
    ax.scatter(sem["distance_m"], sem["per"], s=4, alpha=0.18,
               color=MUTED, edgecolors="none", label="par sem enlace na matriz")
    ax.scatter(com["distance_m"], com["per"], s=5, alpha=0.45,
               color=SERIES[0], edgecolors="none", label="par com enlace")
    ax.axhline(PER_THRESHOLD, color=SERIES[1], linewidth=1.2, linestyle="--",
               label=f"limiar de enlace, PER = {PER_THRESHOLD}")
    _style(ax, "distancia (m)", "PER",
           "(a) PER por distancia, modelo de Pister-Hack")
    ax.set_ylim(-0.05, 1.05)
    ax.legend(frameon=False, fontsize=8, loc="upper left",
              bbox_to_anchor=(0.02, 0.96))

    # (b) Que fracao dos pares tem enlace, por faixa de distancia. Com a matriz
    # vinda do Apendice C, isto mostra o alcance REAL da rede da tese, que a
    # figura dela nao exibe.
    ax = axes[1]
    edges = np.arange(0, max_distance + 1e-9, 100.0)
    centers = (edges[:-1] + edges[1:]) / 2
    total, _ = np.histogram(near["distance_m"], bins=edges)
    kept, _ = np.histogram(near[near["adjacent"] == 1]["distance_m"], bins=edges)
    frac = np.divide(kept, total, out=np.zeros_like(centers), where=total > 0)
    ax.bar(centers, frac, width=88, color=SERIES[2], edgecolor="none")
    _style(ax, "distancia (m)", "fracao de pares com enlace",
           "(b) alcance efetivo da matriz publicada")
    ax.set_ylim(0, 1.02)

    fig.tight_layout()
    fig.savefig(out_png, dpi=160)
    n_adj = int((df["adjacent"] == 1).sum())
    print(f"gravado {out_png}")
    print(f"  {len(df)} pares, {n_adj} enlaces viaveis "
          f"({100.0 * n_adj / len(df):.1f}%), "
          f"PER medio dos viaveis {df[df['adjacent'] == 1]['per'].mean():.4f}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--links", default="data/tisch_links.csv")
    p.add_argument("--out", default="data/tisch_per.png")
    a = p.parse_args()
    plot(Path(a.links), Path(a.out))
