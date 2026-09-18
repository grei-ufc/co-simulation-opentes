"""Figura de convergencia da decomposicao dual.

Dois quadros, porque as duas grandezas respondem perguntas diferentes:

  - residuo primal |x - y|: as duas partes chegaram a mesma programacao? E o que
    diz se a negociacao funcionou. Escala log, porque a convergencia e
    geometrica e o que interessa e a razao de decaimento (reta = geometrica,
    patamar = ciclo limite).
  - preco sombra maximo: para onde o sinal economico converge.

O grafico NAO mostra tensao de proposito: o DSO respeita as restricoes na sua
propria solucao mesmo quando a negociacao nao converge, entao uma curva de
tensao daria a impressao de sucesso em casos que falharam.

Uso:

    python -m market_opentes.plot_convergence data/history_*.json -o figura.png
"""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def plot(histories, labels, out_path, eps=None):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))

    for hist, label in zip(histories, labels):
        rounds = [h["round"] for h in hist]
        ax1.semilogy(rounds, [h["residual_max"] for h in hist], marker="o",
                     markersize=3, label=label)
        ax2.plot(rounds, [h["lambda_max"] for h in hist], marker="o",
                 markersize=3, label=label)

    if eps:
        ax1.axhline(eps, color="0.5", linestyle="--", linewidth=1)
        ax1.annotate("tolerancia", xy=(0.02, eps), xycoords=("axes fraction", "data"),
                     va="bottom", fontsize=8, color="0.4")

    ax1.set_xlabel("rodada de negociacao")
    ax1.set_ylabel(r"residuo primal $\max|x - y|$  [kW]")
    ax1.set_title("acordo entre concentrador e DSO")
    ax1.grid(True, which="both", alpha=0.3)
    ax1.legend(fontsize=8)

    ax2.set_xlabel("rodada de negociacao")
    ax2.set_ylabel(r"$\max\ \lambda$")
    ax2.set_title("preco sombra")
    ax2.grid(True, alpha=0.3)
    ax2.legend(fontsize=8)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"gravado {out_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("history", nargs="+", help="arquivos JSON gerados por dual.py --out")
    ap.add_argument("-o", "--out", default="convergencia.png")
    ap.add_argument("--labels", default=None,
                    help="rotulos separados por ponto-e-virgula, na ordem dos arquivos")
    ap.add_argument("--eps", type=float, default=1e-3)
    args = ap.parse_args()

    histories = [json.loads(Path(p).read_text()) for p in args.history]
    labels = (args.labels.split(";") if args.labels
              else [Path(p).stem for p in args.history])
    plot(histories, labels, args.out, args.eps)


if __name__ == "__main__":
    main()
