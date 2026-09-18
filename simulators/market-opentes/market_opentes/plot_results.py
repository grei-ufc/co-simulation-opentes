"""Figuras de resultado do mercado transativo (Fase 7).

Tres figuras, uma por pergunta:

  tensao_mercado.png    a negociacao resolve a violacao na rede real?
  operacao.png          a fase de operacao corrige o desvio da previsao?
  comunicacao.png       quanto a perda de pacotes custa a negociacao?

A convergencia da decomposicao dual fica em `plot_convergence.py`, que ja existe.

Cores: slots 1 a 3 da paleta de referencia, em ordem fixa. Uma escala por eixo,
legenda sempre que houver duas ou mais series, grade recessiva.
"""

import argparse
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .config import V_MAX, V_MIN  # noqa: E402

SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]
INK = "#0b0b0b"
MUTED = "#52514e"
GRID = "0.85"


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


def _hours(n):
    return np.arange(n) * 0.25


def plot_voltage(output_dir, out_path):
    """Tensao minima e maxima da rede ao longo do dia, com e sem negociacao.

    Os dois quadros existem porque a restricao que aperta muda com o caso: com a
    demanda da tese o problema e SUBTENSAO no pico da tarde, e um grafico so da
    maxima esconderia isso inteiro.
    """
    series = {}
    for tag in ("baseline", "negociado"):
        df = pd.read_csv(Path(output_dir) / f"result_{tag}.csv", index_col=0)
        cols = [c for c in df.columns if c.endswith("V1_pu")]
        series[tag] = df[cols].values

    fig, (ax_min, ax_max) = plt.subplots(1, 2, figsize=(11, 4.2))
    labels = {"baseline": "sem negociacao", "negociado": "com negociacao"}
    for i, tag in enumerate(("baseline", "negociado")):
        v = series[tag]
        # A linha de base fica por cima: e nela que estao as excursoes fora dos
        # limites, e o caso negociado a cobriria em quase todo o dia.
        z = 3 if tag == "baseline" else 2
        ax_min.plot(_hours(len(v)), v.min(axis=1), linewidth=2, color=SERIES[i],
                    label=labels[tag], zorder=z)
        ax_max.plot(_hours(len(v)), v.max(axis=1), linewidth=2, color=SERIES[i],
                    label=labels[tag], zorder=z)

    for ax, limit, titulo, ylabel in (
            (ax_min, V_MIN, "Tensao minima da rede", "tensao minima [pu]"),
            (ax_max, V_MAX, "Tensao maxima da rede", "tensao maxima [pu]")):
        ax.axhline(limit, color=MUTED, linestyle="--", linewidth=1)
        ax.annotate(f"limite {limit:.2f} pu", xy=(0.4, limit),
                    xytext=(0.4, limit + 0.0015), color=MUTED, fontsize=8)
        _style(ax, "hora do dia", ylabel, titulo)
        ax.set_xlim(0, 24)
        ax.set_xticks(range(0, 25, 6))
        ax.legend(frameon=False, fontsize=9, loc="best")

    fig.suptitle("Fluxo de potencia completo (OpenDSS) sobre a programacao acordada",
                 fontsize=11, color=INK, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(out_path, dpi=150)
    print(f"gravado {out_path}")


def _load_operation(log_path):
    """Registro da operacao, do `run.json` novo ou do formato antigo.

    Os agentes gravavam um `operation_log.json` proprio; hoje gravam tudo num
    `run/run.json`, com a operacao numa chave. Aceitar os dois evita que a figura
    fique lendo um arquivo velho em silencio, que foi exatamente o que aconteceu.
    """
    log = json.loads(Path(log_path).read_text())
    if isinstance(log, dict):
        log = log.get("operation", [])
    # Chaves do registro novo, traduzidas para as que a figura usa. O nivel e
    # derivado do motivo quando nao vem explicito: o registro dos agentes diz
    # POR QUE o intervalo fechou, e e disso que sai quem agiu.
    saida = []
    for r in log:
        nivel = r.get("level")
        if nivel is None:
            motivo = r.get("motivo", "")
            if motivo == "resolvido pelo armazenamento de rede":
                nivel = "1"
            elif r.get("rounds"):
                nivel = "2"
            else:
                nivel = "-"
        saida.append({"t": r["t"],
                      "v_min_before": r.get("v_min_before"),
                      "v_min_after": r.get("v_min_after"),
                      "level": nivel})
    return [r for r in saida
            if r["v_min_before"] is not None and r["v_min_after"] is not None]


def plot_operation(log_path, out_path):
    """Fase de operacao: violacao antes e depois da intervencao."""
    log = _load_operation(log_path)
    if not log:
        print(f"sem registro de operacao utilizavel em {log_path}; pulando")
        return
    t = np.array([r["t"] for r in log]) * 0.25
    before = np.array([r["v_min_before"] for r in log])
    after = np.array([r["v_min_after"] for r in log])
    acted = [r for r in log if r["level"] != "-"]

    fig, ax = plt.subplots(figsize=(8, 4))
    # Quando nenhum intervalo exige intervencao, as duas curvas coincidem e a
    # figura passaria a impressao de que uma delas sumiu. Melhor dizer que nao
    # houve o que corrigir do que desenhar duas linhas identicas com legenda.
    inerte = not acted and np.allclose(before, after)
    if inerte:
        ax.plot(t, after, linewidth=2, color=SERIES[0],
                label="tensao minima da rede")
        ax.annotate("nenhum intervalo exigiu intervencao",
                    xy=(0.5, 0.06), xycoords="axes fraction", ha="center",
                    fontsize=9, color=MUTED)
    else:
        ax.plot(t, before, linewidth=2, color=SERIES[1], label="antes da intervencao")
        ax.plot(t, after, linewidth=2, color=SERIES[0], label="depois")
    ax.axhline(V_MIN, color=MUTED, linestyle="--", linewidth=1)

    # Os marcadores dizem QUEM agiu, nao QUAL serie: por isso distinguem-se pela
    # forma e ficam em tinta neutra. Reusar a cor de uma serie para outro
    # significado quebraria a leitura por cor.
    for level, marker in (("rede", "o"), ("leilao", "^")):
        pts = [r for r in acted if r["level"] == level]
        if pts:
            ax.scatter([r["t"] * 0.25 for r in pts],
                       [r["v_min_before"] for r in pts],
                       s=44, marker=marker, facecolor="white", edgecolor=INK,
                       linewidth=1.3, zorder=4,
                       label=("nivel 1: armazenamento de rede" if level == "rede"
                              else "nivel 2: leilao de operacao"))

    _style(ax, "hora do dia", "tensao minima da rede [pu]",
           "Fase de operacao: desvio da previsao e correcao a cada 15 min")
    ax.set_xlim(0, 24)
    ax.set_xticks(range(0, 25, 3))
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"gravado {out_path}")


def plot_dlmp(dlmp_csv, out_path):
    """Adicional de preco por no e por intervalo (a Figura 45 da tese, em 2D).

    A tese usa barras 3D; um mapa de calor mostra o mesmo sem a oclusao que as
    barras causam. Escala sequencial de UM tom, claro para escuro, porque a
    grandeza e magnitude e nao categoria.
    """
    rows = list(csv.DictReader(open(dlmp_csv)))
    col = "adder_eur_mwh" if "adder_eur_mwh" in rows[0] else "adder_signal"
    nodes = sorted({int(r["node"]) for r in rows})
    periods = sorted({int(r["t"]) for r in rows})
    grid = np.zeros((len(nodes), len(periods)))
    idx = {n: i for i, n in enumerate(nodes)}
    for r in rows:
        grid[idx[int(r["node"])], int(r["t"])] = float(r[col])

    fig, ax = plt.subplots(figsize=(9, 4.4))
    im = ax.imshow(grid, aspect="auto", origin="lower", cmap="Blues",
                   extent=(0, 24, 0, len(nodes)))
    unidade = "EUR/MWh" if col.endswith("eur_mwh") else "sinal (nao monetario)"
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label(f"adicional sobre o preco spot [{unidade}]", color=MUTED,
                   fontsize=9)
    cbar.ax.tick_params(colors=MUTED, labelsize=8)
    ax.set_yticks(np.arange(len(nodes)) + 0.5)
    ax.set_yticklabels([str(n) for n in nodes], fontsize=6)
    _style(ax, "hora do dia", "no com armazenamento de prosumidor",
           "Preco locacional: adicional descoberto na negociacao")
    ax.grid(False)
    ax.set_xticks(range(0, 25, 3))
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"gravado {out_path}")


def plot_communication(rows, out_path):
    """Custo da perda de pacotes: rodadas concluidas e retransmissoes."""
    fig, ax = plt.subplots(figsize=(7, 4))
    losses = [r["loss"] * 100 for r in rows]
    rounds = [r["rounds"] for r in rows]
    colors = [SERIES[0] if r["converged"] else SERIES[1] for r in rows]

    bars = ax.bar([f"{l:.0f}%" for l in losses], rounds, color=colors, width=0.55)
    for bar, row in zip(bars, rows):
        estado = "convergiu" if row["converged"] else "nao convergiu"
        ax.annotate(f"{row['rounds']}\n{estado}",
                    xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                    xytext=(0, 4), textcoords="offset points",
                    ha="center", fontsize=8, color=MUTED)

    ax.axhline(17, color=MUTED, linestyle="--", linewidth=1)
    ax.annotate("17 rodadas: canal ideal", xy=(-0.4, 17.4), fontsize=8, color=MUTED)
    _style(ax, "perda de pacotes", "rodadas concluidas",
           "Negociacao sob perda, com retransmissao (3 tentativas)")
    ax.set_ylim(0, 22)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"gravado {out_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default="../../output/market",
                    help="pasta com result_baseline.csv e result_negociado.csv")
    ap.add_argument("--operation-log", default="data/run/run.json")
    ap.add_argument("--out-dir", default="data")
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    plot_voltage(args.output_dir, out / "tensao_mercado.png")
    dlmp_csv = out / "dlmp.csv"
    if dlmp_csv.exists():
        plot_dlmp(dlmp_csv, out / "dlmp.png")
    plot_operation(args.operation_log, out / "operacao.png")
    # Medido nas corridas da Fase 5 (backend lossy, 3 retransmissoes).
    plot_communication([
        {"loss": 0.00, "rounds": 17, "converged": True},
        {"loss": 0.02, "rounds": 17, "converged": True},
        {"loss": 0.05, "rounds": 16, "converged": False},
        {"loss": 0.10, "rounds": 3, "converged": False},
    ], out / "comunicacao.png")


if __name__ == "__main__":
    main()
