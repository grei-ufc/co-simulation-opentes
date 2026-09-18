"""Saídas equivalentes às da tese que ainda não existiam aqui.

Três produtos, um por lacuna registrada na seção 3.5 do `REVISAO_TESE.md`:

  tensao_por_no.csv   Tabelas 18 e 19 do Apêndice A: tensão máxima e mínima por
                      nó, com o horário de ocorrência.
  programacao_no.png  Figuras 51 e 52: a programação que o AC propõe e a que o AD
                      aceita, para um nó, ao longo das rodadas de negociação.
  ciclos.png          quanto tempo de rede cada ciclo consumiu, contra a fatia
                      que ele tem dentro da janela de 15 minutos. NAO e a Figura
                      58: aquela e por mensagem e sai do `plot_msgs.py`.

As duas primeiras leem `result_negociado.csv` e `run/run.json`, que a execução dos
agentes grava. Mesma paleta e gramática visual das outras figuras do mercado.
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

from .config import DT_H, PERIODS  # noqa: E402

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


def _hhmm(t):
    """Rótulo de horário do intervalo t, com passo de 15 minutos."""
    minutos = int(round(t * DT_H * 60))
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


# ---------------------------------------------------------------------------
# Tabelas 18 e 19: tensão extrema por nó, com horário
# ---------------------------------------------------------------------------

def tabela_tensao(result_csv, out_csv):
    df = pd.read_csv(result_csv, index_col=0)
    cols = [c for c in df.columns if c.endswith("V1_pu")]
    rows = []
    for c in cols:
        v = df[c].values
        i_max, i_min = int(np.argmax(v)), int(np.argmin(v))
        # A coluna vem como `DSS-0.Bus-n<barra>-V1_pu`. Separar por ponto ou por
        # traço pega o índice do simulador, não a barra: o que identifica a barra
        # é o campo que começa com `n`.
        no = next(part[1:] for part in c.split("-")
                  if part.startswith("n") and part[1:].isdigit())
        rows.append({"no": no,
                     "v_max_pu": round(float(v[i_max]), 5), "hora_max": _hhmm(i_max),
                     "v_min_pu": round(float(v[i_min]), 5), "hora_min": _hhmm(i_min)})
    rows.sort(key=lambda r: r["v_min_pu"])
    out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    pior = rows[0]
    print(f"gravado {out_csv} ({len(rows)} nos)")
    print(f"  pior subtensao: no {pior['no']} com {pior['v_min_pu']} pu as {pior['hora_min']}")
    return rows


# ---------------------------------------------------------------------------
# Figuras 51 e 52: a programação por nó ao longo das rodadas
# ---------------------------------------------------------------------------

def _procedencia(run):
    """Rotulo curto com a configuracao que produziu a execucao."""
    c = run.get("config") or {}
    if not c:
        return ""
    return (f"rede={c.get('net_backend', '?')}  "
            f"msg={c.get('message_size', '?')}  "
            f"backoff={c.get('v_backoff', '?')}  "
            f"demanda={c.get('realized_mode', '?')}")


def _carimbo(fig, run):
    """Carimba a procedencia no rodape da figura.

    As figuras saem de execucoes diferentes: a de ciclos exige uma camada de rede
    e o `run.sh market` roda com entrega ideal. Sem o carimbo, duas figuras da
    mesma pasta parecem do mesmo experimento quando nao sao.
    """
    texto = _procedencia(run)
    if texto:
        fig.subplots_adjust(bottom=fig.subplotpars.bottom + 0.06)
        fig.text(0.99, 0.012, texto, ha="right", va="bottom",
                 fontsize=7, color=MUTED)


def programacao_no(run_json, out_png, node=None):
    run = json.loads(Path(run_json).read_text())
    history = [h for h in run["history"] if h.get("x") and h.get("y")]
    if not history:
        print("sem programacao por no no historico; nada a plotar")
        return

    if node is None:
        # O nó em que as duas partes mais discordaram ao longo da negociação: é
        # onde a figura mostra alguma coisa.
        nos = list(history[0]["x"])
        node = max(nos, key=lambda n: max(
            np.abs(np.array(h["x"][n]) - np.array(h["y"][n])).max()
            for h in history if n in h["x"] and n in h["y"]))
    node = str(node)

    fig, axes = plt.subplots(2, 1, figsize=(9.5, 6.0), sharex=True)
    # Poucas rodadas, senão a figura vira um borrão. Espaçadas em escala
    # logarítmica e não uniforme: o movimento da negociação acontece quase todo
    # nas primeiras rodadas, e quatro pontos equidistantes deixariam três deles
    # empilhados sobre a solução final.
    n = len(history)
    idx = sorted({0, min(1, n - 1), min(4, n - 1), n - 1})
    cmap = plt.get_cmap("viridis")
    t = np.arange(PERIODS)

    for ax, chave, titulo in ((axes[0], "x", f"(a) proposta do AC, no {node}"),
                              (axes[1], "y", f"(b) aceita pelo AD, no {node}")):
        for k, i in enumerate(idx):
            h = history[i]
            if node not in h[chave]:
                continue
            ax.plot(t, h[chave][node], linewidth=1.4,
                    color=cmap(k / max(1, len(idx) - 1)),
                    label=f"rodada {h['round']}")
        _style(ax, "", "potencia do armazenamento (kW)", titulo)
    axes[1].set_xlabel("intervalo de 15 min", color=MUTED, fontsize=9)
    # Legenda fora da área de dados: dentro dela cobria justamente o trecho em
    # que as curvas se separam.
    axes[0].legend(frameon=False, fontsize=8, ncol=len(idx),
                   loc="lower center", bbox_to_anchor=(0.5, 1.10))

    fig.tight_layout()
    _carimbo(fig, run)
    fig.savefig(out_png, dpi=160)
    print(f"gravado {out_png} (no {node}, {len(history)} rodadas)")


# ---------------------------------------------------------------------------
# Figura 58: o tempo de rede de cada ciclo contra a fatia dele
# ---------------------------------------------------------------------------

def ciclos(run_json, out_png):
    run = json.loads(Path(run_json).read_text())
    cycles = run.get("cycles") or []
    if not cycles:
        print("sem contabilidade por ciclo; rode com NET_BACKEND=omnet ou lossy")
        return
    budget = run.get("cycle_budget_s", {})

    por_nome = {}
    for c in cycles:
        por_nome.setdefault(c["name"], []).append(c["max_delay"])
    nomes = list(por_nome)

    fig, ax = plt.subplots(figsize=(8.6, 4.4))
    x = np.arange(len(nomes))
    medias = [float(np.mean(por_nome[n])) for n in nomes]
    # O acumulado e o que decide: um ciclo que se repete gasta a fatia dele
    # tantas vezes quantas rodar. Sem esta barra o ciclo 3 parece folgado, quando
    # e justamente ele que nao cabe na fase de operacao.
    totais = [float(np.sum(por_nome[n])) for n in nomes]
    repeticoes = [len(por_nome[n]) for n in nomes]
    orcamentos = [budget.get(n, 0.0) for n in nomes]

    ax.bar(x - 0.19, medias, width=0.36, color=SERIES[0],
           label="por execucao do ciclo")
    ax.bar(x + 0.19, totais, width=0.36, color=SERIES[1],
           label="acumulado na negociacao")
    for i, (o, r) in enumerate(zip(orcamentos, repeticoes)):
        if o:
            ax.hlines(o, i - 0.45, i + 0.45, color=INK, linewidth=1.6,
                      linestyle="--",
                      label="fatia na janela de 15 min" if i == 0 else None)
        if r > 1:
            ax.annotate(f"{r} rodadas", (i + 0.19, totais[i]),
                        textcoords="offset points", xytext=(0, 4),
                        ha="center", fontsize=8, color=MUTED)
    ax.set_xticks(x)
    ax.set_xticklabels([n.replace("_", " ") for n in nomes], fontsize=8)
    ax.set_yscale("log")
    _style(ax, "", "segundos (escala log)",
           "Tempo de rede por ciclo contra a fatia disponivel")
    # Legenda fora da area de dados: dentro dela cobria a linha do orcamento.
    ax.legend(frameon=False, fontsize=8, loc="lower center",
              bbox_to_anchor=(0.5, 1.06), ncol=3)

    fig.tight_layout()
    _carimbo(fig, run)
    fig.savefig(out_png, dpi=160)
    print(f"gravado {out_png}")
    for n, m, tot, r, o in zip(nomes, medias, totais, repeticoes, orcamentos):
        cabe = "cabe" if o and tot <= o else ("ESTOURA" if o else "sem fatia")
        print(f"  {n:<18} {r:2d}x {m:6.1f} s = {tot:8.1f} s  "
              f"fatia {o:6.0f} s  {cabe}")



if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--result", default="/app/output/market/result_negociado.csv")
    p.add_argument("--run", default="data/run/run.json")
    p.add_argument("--out-dir", default="data")
    p.add_argument("--node", default=None)
    a = p.parse_args()
    out = Path(a.out_dir)

    if Path(a.result).exists():
        tabela_tensao(a.result, out / "tensao_por_no.csv")
    else:
        print(f"sem {a.result}; pulando a tabela de tensao")
    if Path(a.run).exists():
        programacao_no(a.run, out / "programacao_no.png", a.node)
        ciclos(a.run, out / "ciclos.png")
    else:
        print(f"sem {a.run}; rode a co-simulacao primeiro")
