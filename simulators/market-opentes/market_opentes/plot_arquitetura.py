"""Diagramas de arquitetura e de fluxo, na identidade do GREI.

Duas figuras, ambas releituras de diagramas da tese de referência com as
ferramentas efetivamente usadas aqui:

  arquitetura_simsg.png    os blocos da co-simulação e como se ligam, com
                           OMNeT++, OpenDSS e Pyomo no lugar de ns-3, pandapower
                           e PySP.
  fluxo_cosimulacao.png    o diagrama de atividades das fases de programação e
                           de operação, com os três ciclos de mensagens e a
                           correção da fase de operação.

São desenhadas por código, e não à mão, para poderem ser refeitas quando a
arquitetura mudar.
"""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

# Paleta do manual de marca do GREI.
VERDE = "#2F5E4B"
VERDE_CLARO = "#E0F1E6"
CREME = "#F4FFEB"
TINTA = "#16241D"
CINZA = "#64786C"
LINHA = "#C3D4C6"
AMARELO = "#FBF3D9"
AZUL = "#DCE9F6"
LARANJA = "#F8EAE0"
BRANCO = "#FFFFFF"

FONTE = {"family": "sans-serif", "size": 8.2}


def caixa(ax, x, y, w, h, texto, fundo=BRANCO, borda=LINHA, cor=TINTA,
          tam=8.2, negrito=False, raio=0.02):
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle=f"round,pad=0,rounding_size={raio}",
        linewidth=1.0, edgecolor=borda, facecolor=fundo, zorder=2))
    ax.text(x + w / 2, y + h / 2, texto, ha="center", va="center",
            fontsize=tam, color=cor, zorder=3, linespacing=1.35,
            fontweight="bold" if negrito else "normal")


def seta(ax, p0, p1, cor=CINZA, estilo="-|>", tracejada=False, curva=0.0):
    ax.add_patch(FancyArrowPatch(
        p0, p1, arrowstyle=estilo, mutation_scale=9, linewidth=1.0,
        color=cor, zorder=1, shrinkA=1, shrinkB=1,
        linestyle=(0, (3, 2)) if tracejada else "solid",
        connectionstyle=f"arc3,rad={curva}"))


def rotulo(ax, x, y, texto, cor=CINZA, tam=7.2, ha="center"):
    ax.text(x, y, texto, ha=ha, va="center", fontsize=tam, color=cor, zorder=4)


# ---------------------------------------------------------------------------
# Arquitetura: releitura do diagrama de blocos da tese
# ---------------------------------------------------------------------------

def arquitetura(out_png):
    fig, ax = plt.subplots(figsize=(11.5, 6.2))
    ax.set_xlim(0, 100); ax.set_ylim(0, 56); ax.axis("off")

    # Painel do ambiente de co-simulação
    ax.add_patch(FancyBboxPatch(
        (30, 2), 68, 52, boxstyle="round,pad=0,rounding_size=0.8",
        linewidth=1.2, edgecolor=VERDE, facecolor=VERDE_CLARO, zorder=0))
    ax.text(32, 51.4, "Ambiente de co-simulação", fontsize=9.5,
            color=VERDE, fontweight="bold", va="center")

    # Orquestrador
    caixa(ax, 33, 42, 62, 7.5, "", fundo=CREME, borda=VERDE)
    ax.text(34.5, 48.2, "Orquestrador  ·  Mosaik 3.5", fontsize=8.6,
            color=VERDE, fontweight="bold", va="center")
    for i, (rot, dx) in enumerate((("tempo de simulação", 0),
                                   ("entrega de mensagens", 20),
                                   ("descrição do cenário", 40))):
        caixa(ax, 35 + dx, 43, 18, 3.6, rot, fundo=BRANCO, borda=LINHA, tam=7.4)

    # Simuladores
    sims = [
        (33, 26, 18, 11, "PADE 3.0\n\nagentes e\nprotocolos FIPA", "Python 3.12"),
        (54, 26, 18, 11, "OMNeT++\n\nrede de\ncomunicação 6TiSCH", "C++, ZMQ"),
        (75, 26, 20, 11, "OpenDSS\n\nfluxo de potência\nnão linear", "py-dss-interface"),
    ]
    for x, y, w, h, txt, sub in sims:
        caixa(ax, x, y, w, h, txt, fundo=BRANCO, borda=VERDE, tam=8.0)
        rotulo(ax, x + w / 2, y - 1.6, sub, tam=6.9)
        seta(ax, (x + w / 2, y + h), (x + w / 2, 42))

    # Simuladores de RED
    caixa(ax, 33, 8, 39, 10, "Simuladores de recursos distribuídos\n\n"
                             "geração fotovoltaica  ·  armazenamento\n"
                             "carga não controlável",
          fundo=BRANCO, borda=LINHA, tam=7.8)
    seta(ax, (52, 18), (52, 26))

    caixa(ax, 75, 8, 20, 10, "Coletor\n\ngrava o estado\nelétrico em CSV",
          fundo=BRANCO, borda=LINHA, tam=7.8)
    seta(ax, (85, 18), (85, 26))

    # Blocos externos
    externos = [
        (2, 42, 24, 8, "Solver matemático\nCPLEX, via Pyomo", LARANJA,
         "chamada de sistema"),
        (2, 28, 24, 8, "Arquivos de configuração\nrede, dispositivos, preços", LARANJA,
         "leitura de arquivo"),
        (2, 14, 24, 8, "Resultados\nCSV, JSON e figuras", LARANJA,
         "escrita de arquivo"),
    ]
    for x, y, w, h, txt, cor, via in externos:
        caixa(ax, x, y, w, h, txt, fundo=cor, borda="#E0C4B0", tam=7.8)
        seta(ax, (x + w, y + h / 2), (30, y + h / 2), tracejada=True)
        rotulo(ax, (x + w + 30) / 2, y + h / 2 + 1.5, via, tam=6.6)

    ax.text(50, 0.6,
            "Releitura da arquitetura de referência (MELO, 2022, Fig. 33) com as "
            "ferramentas adotadas neste trabalho",
            ha="center", fontsize=7.2, color=CINZA)

    fig.tight_layout(pad=0.4)
    fig.savefig(out_png, dpi=170, facecolor="white")
    print(f"gravado {out_png}")


# ---------------------------------------------------------------------------
# Fluxo: releitura do diagrama de atividades das duas fases
# ---------------------------------------------------------------------------

def fluxo(out_png):
    fig, ax = plt.subplots(figsize=(12.2, 6.6))
    ax.set_xlim(0, 122); ax.set_ylim(0, 66); ax.axis("off")

    # Faixas das duas fases
    ax.add_patch(FancyBboxPatch((1, 2), 56, 60,
                                boxstyle="round,pad=0,rounding_size=0.8",
                                linewidth=1.0, edgecolor="#B9CDE8",
                                facecolor=AZUL, zorder=0))
    ax.add_patch(FancyBboxPatch((59, 2), 62, 60,
                                boxstyle="round,pad=0,rounding_size=0.8",
                                linewidth=1.0, edgecolor="#E3D7A8",
                                facecolor=AMARELO, zorder=0))
    ax.text(3, 59.6, "Fase de programação  ·  dia anterior, 96 intervalos",
            fontsize=8.6, color="#2C5480", fontweight="bold", va="center")
    ax.text(61, 59.6, "Fase de operação  ·  a cada 15 minutos, 1 intervalo",
            fontsize=8.6, color="#8A6D1F", fontweight="bold", va="center")

    L = 15.5   # largura padrão de caixa
    H = 5.0

    # ---- programação ----------------------------------------------------
    ax.add_patch(plt.Circle((8, 55), 1.1, color=TINTA, zorder=3))
    caixa(ax, 14, 52.5, L, H, "ciclo 1\nAC pede aos AP", fundo=BRANCO, borda=VERDE)
    seta(ax, (9.2, 55), (14, 55))

    caixa(ax, 14, 44.5, L, H, "ciclo 2\nAD pede aos AC", fundo=BRANCO, borda=VERDE)
    seta(ax, (21.7, 52.5), (21.7, 49.5))

    caixa(ax, 14, 36.5, L, H, "ciclo 3\nAM abre a rodada", fundo=BRANCO, borda=VERDE)
    seta(ax, (21.7, 44.5), (21.7, 41.5))

    ax.add_patch(plt.Polygon([[21.7, 34.5], [26, 31.5], [21.7, 28.5], [17.4, 31.5]],
                             closed=True, facecolor=BRANCO, edgecolor=VERDE,
                             linewidth=1.0, zorder=2))
    rotulo(ax, 21.7, 31.5, "violação?", tam=6.8, cor=TINTA)
    seta(ax, (21.7, 36.5), (21.7, 34.5))
    rotulo(ax, 33, 32.6, "não", tam=6.9)
    seta(ax, (26, 31.5), (61, 31.5))

    caixa(ax, 6, 19, 14, 5.6, "AC resolve\nseu modelo", fundo=BRANCO, borda=LINHA, tam=7.6)
    caixa(ax, 24, 19, 14, 5.6, "AD resolve\nseu modelo", fundo=BRANCO, borda=LINHA, tam=7.6)
    ax.plot([6, 38], [26.6, 26.6], color=TINTA, linewidth=2.4, zorder=3)
    seta(ax, (21.7, 28.5), (21.7, 26.9))
    rotulo(ax, 18.6, 27.9, "sim", tam=6.9)
    seta(ax, (13, 26.6), (13, 24.6)); seta(ax, (31, 26.6), (31, 24.6))
    ax.plot([6, 38], [17.4, 17.4], color=TINTA, linewidth=2.4, zorder=3)
    seta(ax, (13, 19), (13, 17.5)); seta(ax, (31, 19), (31, 17.5))

    caixa(ax, 14, 10, L, 5.4, "AM atualiza λ\ne testa convergência",
          fundo=BRANCO, borda=VERDE, tam=7.6)
    seta(ax, (21.7, 17.4), (21.7, 15.4))
    ax.add_patch(plt.Polygon([[21.7, 8.6], [25.6, 6], [21.7, 3.4], [17.8, 6]],
                             closed=True, facecolor=BRANCO, edgecolor=VERDE,
                             linewidth=1.0, zorder=2))
    rotulo(ax, 21.7, 6, "convergiu?", tam=6.8, cor=TINTA)
    seta(ax, (21.7, 10), (21.7, 8.6))
    rotulo(ax, 12.5, 7.2, "não", tam=6.9)
    seta(ax, (17.8, 6), (4, 6)); seta(ax, (4, 6), (4, 39)); seta(ax, (4, 39), (14, 39))
    caixa(ax, 30, 3.4, 24, 5.2, "AM publica λ acordado\npara AC e AD",
          fundo=VERDE_CLARO, borda=VERDE, tam=7.6)
    seta(ax, (25.6, 6), (30, 6)); rotulo(ax, 27.8, 7.2, "sim", tam=6.9)

    # ---- operação -------------------------------------------------------
    caixa(ax, 61, 52.5, L, H, "ciclo 1\nAC pede o intervalo", fundo=BRANCO, borda=VERDE)
    caixa(ax, 61, 44.5, L, H, "ciclo 2\nAD pede aos AC", fundo=BRANCO, borda=VERDE)
    seta(ax, (68.7, 52.5), (68.7, 49.5))

    caixa(ax, 61, 35.5, L, 6.0, "AD resolve o\nFLUXO DE POTÊNCIA\ndo intervalo",
          fundo=VERDE_CLARO, borda=VERDE, tam=7.4)
    seta(ax, (68.7, 44.5), (68.7, 41.5))
    seta(ax, (61, 31.5), (68.7, 31.5)); seta(ax, (68.7, 31.5), (68.7, 35.5))

    ax.add_patch(plt.Polygon([[88, 40], [93, 37], [88, 34], [83, 37]],
                             closed=True, facecolor=BRANCO, edgecolor=VERDE,
                             linewidth=1.0, zorder=2))
    rotulo(ax, 88, 37, "há violação?", tam=6.8, cor=TINTA)
    seta(ax, (76.5, 38.5), (83, 37))
    rotulo(ax, 96.5, 38.4, "não: encerra o passo", tam=6.9, ha="left")
    seta(ax, (93, 37), (116, 37))
    ax.add_patch(plt.Circle((117.4, 37), 1.0, facecolor="white",
                            edgecolor=TINTA, linewidth=1.0, zorder=3))
    ax.add_patch(plt.Circle((117.4, 37), 0.55, color=TINTA, zorder=4))

    caixa(ax, 78, 24, 22, 6.4, "AD tenta corrigir só com o\narmazenamento DE REDE",
          fundo=BRANCO, borda=VERDE, tam=7.5)
    seta(ax, (88, 34), (88, 30.4)); rotulo(ax, 91, 32.4, "sim", tam=6.9)

    ax.add_patch(plt.Polygon([[89, 21], [94, 18], [89, 15], [84, 18]],
                             closed=True, facecolor=BRANCO, edgecolor=VERDE,
                             linewidth=1.0, zorder=2))
    rotulo(ax, 89, 18, "resolveu?", tam=6.8, cor=TINTA)
    seta(ax, (89, 24), (89, 21))
    rotulo(ax, 99, 19.4, "sim: despacha", tam=6.9, ha="left")
    seta(ax, (94, 18), (116, 18))
    ax.add_patch(plt.Circle((117.4, 18), 1.0, facecolor="white",
                            edgecolor=TINTA, linewidth=1.0, zorder=3))
    ax.add_patch(plt.Circle((117.4, 18), 0.55, color=TINTA, zorder=4))

    caixa(ax, 61, 8, 26, 6.4, "leilão de operação\nAM abre rodadas de um intervalo",
          fundo=VERDE_CLARO, borda=VERDE, tam=7.5)
    seta(ax, (84, 18), (74, 18)); seta(ax, (74, 18), (74, 14.4))
    rotulo(ax, 78.5, 19.2, "não", tam=6.9)

    ax.text(61, 0.8,
            "Releitura do diagrama de atividades da referência (MELO, 2022) com as "
            "mudanças deste trabalho: o ciclo 2 passou a existir como troca de "
            "mensagens, e a fase de operação resolve o fluxo de potência real.",
            ha="center", fontsize=7.0, color=CINZA)

    fig.tight_layout(pad=0.4)
    fig.savefig(out_png, dpi=170, facecolor="white")
    print(f"gravado {out_png}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", default="data")
    a = p.parse_args()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    arquitetura(out / "arquitetura_simsg.png")
    fluxo(out / "fluxo_cosimulacao.png")
