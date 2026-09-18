"""Diagrama unifilar de uma rede de teste, no estilo da figura da tese.

Lê o `force.json` (topologia) e o `config.json` (alocação de dispositivos) da
pasta da rede e desenha barras, linhas, transformadores, módulos fotovoltaicos e
armazenamento, com a mesma convenção da figura de referência: azul para o
armazenamento do prosumidor, vermelho para o da rede.

O desenho é gerado por código, e não à mão, para acompanhar a rede quando ela for
redimensionada.

    python src/simulators/plot_grid.py src/data/BT38
"""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle  # noqa: E402

TINTA = "#111111"
AZUL = "#1f4fd8"          # armazenamento do prosumidor
VERMELHO = "#d81f1f"      # armazenamento de rede

R_BARRA = 0.085           # raio do marcador de barra, em unidades de dados
PASSO_H = 1.15            # vão entre barras de uma cadeia horizontal
PASSO_V = 0.95            # idem, vertical


# ---------------------------------------------------------------------------
# Símbolos
# ---------------------------------------------------------------------------

def barra(ax, x, y, rotulo, dx=0.0, dy=0.24, ha="center", va="bottom"):
    ax.add_patch(Circle((x, y), R_BARRA, facecolor=TINTA, edgecolor=TINTA,
                        zorder=5))
    ax.text(x + dx, y + dy, str(rotulo), ha=ha, va=va,
            fontsize=8.5, fontweight="bold", color=TINTA, zorder=6)


def linha(ax, p0, p1):
    ax.plot([p0[0], p1[0]], [p0[1], p1[1]], color=TINTA, linewidth=1.5,
            zorder=2, solid_capstyle="round")


def transformador(ax, x, y, rotulo):
    """Dois círculos entrelaçados, o símbolo usual de transformador de dois
    enrolamentos."""
    r = 0.20
    for dy in (r * 0.62, -r * 0.62):
        ax.add_patch(Circle((x, y + dy), r, facecolor="white",
                            edgecolor=TINTA, linewidth=1.5, zorder=4))
    ax.text(x - 0.30, y, rotulo, ha="right", va="center", fontsize=7.4,
            fontweight="bold", color=TINTA, zorder=6, linespacing=1.4)


def descida(ax, x, y_topo, y_base, horizontais, salto=0.15):
    """Trecho vertical que desce até um alimentador, com salto onde cruza uma
    linha horizontal já desenhada.

    O salto é a notação usual de desenho elétrico para cruzamento sem conexão.
    Sem ele, a descida de um transformador passa por cima do alimentador de
    outro e o desenho sugere uma ligação que não existe.
    """
    cortes = sorted({yc for (xa, xb, yc) in horizontais
                     if min(xa, xb) - 1e-6 < x < max(xa, xb) + 1e-6
                     and y_base < yc < y_topo}, reverse=True)
    y = y_topo
    for yc in cortes:
        linha(ax, (x, y), (x, yc + salto))
        ang = np.linspace(90.0, -90.0, 40) * np.pi / 180.0
        ax.plot(x + salto * np.cos(ang), yc + salto * np.sin(ang),
                color=TINTA, linewidth=1.5, zorder=3, solid_capstyle="round")
        y = yc - salto
    linha(ax, (x, y), (x, y_base))


def modulo_pv(ax, x, y, escala=1.0):
    """Glifo de módulo fotovoltaico: um retângulo com a grade de células."""
    w, h = 0.30 * escala, 0.19 * escala
    ax.add_patch(Rectangle((x - w / 2, y - h / 2), w, h, facecolor="white",
                           edgecolor=TINTA, linewidth=1.1, zorder=5))
    for i in (1, 2):
        ax.plot([x - w / 2 + i * w / 3] * 2, [y - h / 2, y + h / 2],
                color=TINTA, linewidth=0.7, zorder=6)
    ax.plot([x - w / 2, x + w / 2], [y] * 2, color=TINTA, linewidth=0.7, zorder=6)


def bateria(ax, x, y, cor, escala=1.0):
    """Glifo de armazenamento: uma célula com o raio dentro."""
    w, h = 0.15 * escala, 0.24 * escala
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                                boxstyle="round,pad=0,rounding_size=0.02",
                                facecolor="white", edgecolor=cor,
                                linewidth=1.4, zorder=5))
    ax.add_patch(Rectangle((x - w * 0.18, y + h / 2), w * 0.36, h * 0.10,
                           facecolor=cor, edgecolor=cor, zorder=5))
    ax.plot([x + w * 0.10, x - w * 0.06, x + w * 0.06, x - w * 0.10],
            [y + h * 0.26, y + h * 0.02, y - h * 0.02, y - h * 0.26],
            color=cor, linewidth=1.2, zorder=6, solid_joinstyle="miter")


# ---------------------------------------------------------------------------
# Layout: árvore ortogonal
# ---------------------------------------------------------------------------

def _enraizar(vizinhos, raiz, pai):
    """Árvore enraizada na primeira barra do alimentador."""
    filhos, pilha = {}, [(raiz, pai)]
    while pilha:
        n, p = pilha.pop()
        fs = [v for v in vizinhos.get(n, []) if v != p]
        filhos[n] = fs
        pilha.extend((f, n) for f in fs)
    return filhos


def _seguinte(b, filhos, dentro, nivel, alt, nivel_atual):
    """Qual filho continua a cadeia.

    Quando o `force.json` traz o nível de ramificação do trecho, a cadeia segue
    pelo trecho de MESMO nível: o tronco é uma propriedade do projeto da rede, é
    o que decide o calibre do cabo, e não algo a adivinhar pela forma do grafo.
    Sem esse dado, cai no critério de sempre, o filho de maior altura, que é o
    caso da rede da tese.
    """
    cand = [f for f in filhos[b] if f not in dentro]
    if not cand:
        return None
    mesmos = [f for f in cand if nivel.get((b, f)) == nivel_atual]
    if mesmos:
        return mesmos[0]
    if any(nivel.get((b, f)) is not None for f in cand):
        return None
    return max(cand, key=lambda f: alt[f])


def _altura(n, filhos, memo):
    if n not in memo:
        memo[n] = 1 + max((_altura(f, filhos, memo) for f in filhos[n]),
                          default=0)
    return memo[n]


def _empacotar(no, filhos, alt, nivel, glifos, pos, eixos, livre,
               eixo, sent, x, y, nivel_atual=0):
    """Coloca a cadeia que começa em `no` e, recursivamente, os seus ramais.

    A cadeia segue pelo filho de maior altura, o que identifica o tronco sem
    precisar de metadado nenhum no `force.json`. Os ramais saem perpendiculares:
    alternando os dois lados quando a cadeia é horizontal, e sempre para a
    direita quando é vertical.

    O empacotamento é sequencial, e por isso NÃO produz sobreposição: antes de
    avançar para a próxima barra da cadeia, o cursor pula o espaço que a
    subárvore da barra atual ocupa na direção de avanço. Devolve o quanto a
    cadeia se estende no seu próprio eixo e o quanto ocupa no eixo perpendicular,
    que é o que o chamador precisa reservar.
    """
    cadeia, dentro = [no], {no}
    while True:
        f = _seguinte(cadeia[-1], filhos, dentro, nivel, alt, nivel_atual)
        if f is None:
            break
        cadeia.append(f)
        dentro.add(f)

    passo = PASSO_H if eixo == 0 else PASSO_V
    passo_perp = PASSO_V if eixo == 0 else PASSO_H
    cur = ult = perp_max = 0.0
    # Os ramais alternam os dois lados da cadeia, contando ao longo dela e não
    # por barra: com cada barra sustentando um ramal só, alternar por barra
    # jogaria todos para o mesmo lado e a faixa do alimentador ficaria com o
    # dobro da altura necessária.
    n_ramais = 0

    for b in cadeia:
        pos[b] = (x + sent * cur, y) if eixo == 0 else (x, y + sent * cur)
        eixos[b] = eixo
        ult = cur
        laterais = [f for f in filhos[b] if f not in dentro]
        ocupados, extra = set(), 0.0
        for r in laterais:
            if eixo == 0:
                lado = -1 if n_ramais % 2 == 0 else 1     # o primeiro desce
                n_ramais += 1
                origem = (pos[b][0], pos[b][1] + lado * PASSO_V)
            else:
                lado = 1                            # ramal horizontal, à direita
                origem = (pos[b][0] + PASSO_H, pos[b][1])
            ocupados.add(lado)
            par_f, perp_f = _empacotar(r, filhos, alt, nivel, glifos, pos,
                                       eixos, livre, 1 - eixo, lado, *origem,
                                       nivel_atual=nivel_atual + 1)
            perp_max = max(perp_max, passo_perp + par_f)
            extra = max(extra, perp_f)
        # o lado que sobrou é onde cabem o rótulo e os dispositivos
        livre[b] = 1 if 1 not in ocupados else -1
        cur += passo + extra
        # Numa cadeia vertical os dispositivos ficam à direita, em fila, e essa
        # fila ocupa espaço no eixo do chamador. Sem reservá-lo, o rótulo da
        # barra seguinte cai em cima do glifo da anterior, que foi o que
        # aconteceu na primeira versão deste desenho.
        if eixo == 1:
            perp_max = max(perp_max, 0.36 * glifos.get(b, 0) + 0.45)

    return ult, perp_max


def posicionar(rede, eixos=None, livre=None, glifos=None,
               folga=1.5, passo_mt=3.6):
    """Média tensão numa linha horizontal, e cada alimentador na sua própria
    faixa, logo abaixo do respectivo transformador.

    `eixos` e `livre`, se passados, recebem por barra o eixo da cadeia a que ela
    pertence e o lado sem ramal. O desenho usa os dois para decidir onde põem o
    rótulo e a pilha de dispositivos.
    """
    eixos = {} if eixos is None else eixos
    livre = {} if livre is None else livre
    glifos = {} if glifos is None else glifos
    mt = [n["name"] for n in rede["nodes"]
          if n["voltage_level"] == "medium voltage"]
    ordem_mt = {b: i for i, b in enumerate(mt)}

    vizinhos, nivel = {}, {}
    for l in rede["links"]:
        vizinhos.setdefault(l["source"], []).append(l["target"])
        vizinhos.setdefault(l["target"], []).append(l["source"])
        nivel[(l["source"], l["target"])] = l.get("level")
        nivel[(l["target"], l["source"])] = l.get("level")

    # cada alimentador é empacotado no seu próprio referencial
    faixas, topo = [], 0.0
    for t in rede["transformers"]:
        raiz = t["target"]
        filhos = _enraizar(vizinhos, raiz, t["source"])
        alt = {}
        for n in filhos:
            _altura(n, filhos, alt)
        local = {}
        _empacotar(raiz, filhos, alt, nivel, glifos, local, eixos, livre,
                   0, 1, 0.0, 0.0)
        ys = [p[1] for p in local.values()]
        dy = topo - max(ys) - (folga + 0.4 if not faixas else folga)
        faixas.append((t, local, dy))
        topo = min(ys) + dy

    # e depois deslocado para debaixo da sua barra de média tensão
    pos = {}
    for t, local, dy in faixas:
        x_mt = ordem_mt[t["source"]] * passo_mt
        # A descida não cai exatamente sob a barra de média tensão: ela cruza os
        # alimentadores já colocados, e cair sobre uma barra deles sugere uma
        # ligação que não existe. O desvio vem do espaço livre, e não de um
        # valor fixo, porque o passo da média tensão e o vão da baixa não são
        # comensuráveis.
        # o espaço ocupado inclui a fila de glifos das barras de cadeia
        # vertical, que se estende para a direita da barra
        ocupado = []
        for b, (px, _) in pos.items():
            ocupado.append(px)
            if eixos.get(b) == 1:
                # a fila sai para o lado sem ramal, que pode ser qualquer um
                for k in range(glifos.get(b, 0)):
                    ocupado.append(px + livre.get(b, 1) * 0.36 * (k + 1))
        if ocupado:
            cand = [0.20 * PASSO_H + 0.05 * PASSO_H * i for i in range(32)]
            dx = x_mt + max(cand, key=lambda c: min(abs(x_mt + c - o)
                                                    for o in ocupado))
        else:
            dx = x_mt
        for b, (px, py) in local.items():
            pos[b] = (px + dx, py + dy)

    for i, b in enumerate(mt):
        pos[b] = (i * passo_mt, 0.0)
    return pos


# ---------------------------------------------------------------------------
# Desenho
# ---------------------------------------------------------------------------

def desenhar(pasta, saida):
    pasta = Path(pasta)
    rede = json.loads((pasta / "force.json").read_text())
    cfg = json.loads((pasta / "config.json").read_text())
    pv = {int(k) for k in cfg["devices"]["stochastic_gen"]["params"]}
    b_pros = {int(k) for k in cfg["devices"]["storage_device"]["params"]}
    b_rede = {int(k) for k in cfg["devices"]["dso_storage_device"]["params"]}

    eixos, livre = {}, {}
    glifos = {n["name"]: sum(n["name"] in c for c in (pv, b_pros, b_rede))
              for n in rede["nodes"]}
    pos = posicionar(rede, eixos, livre, glifos)
    raizes = {t["target"] for t in rede["transformers"]}

    mt_nomes = {n["name"] for n in rede["nodes"]
                if n["voltage_level"] == "medium voltage"}

    xs_ = [x for x, _ in pos.values()]
    ys_ = [y for _, y in pos.values()]
    x0, x1 = min(xs_) - 1.2, max(xs_) + 1.3
    y0, y1 = min(ys_) - 2.6, max(ys_) + 1.0
    esc = 0.58
    fig, ax = plt.subplots(figsize=((x1 - x0) * esc, (y1 - y0) * esc))

    # linhas; a que entra num transformador é desenhada à parte
    horizontais = []
    for l in rede["links"]:
        a, b = l["source"], l["target"]
        if a not in pos or b not in pos:
            continue
        if a in mt_nomes and b not in mt_nomes:
            continue
        linha(ax, pos[a], pos[b])
        if abs(pos[a][1] - pos[b][1]) < 1e-9:
            horizontais.append((pos[a][0], pos[b][0], pos[a][1]))

    # transformadores: descida da média tensão até a raiz do alimentador
    for i, t in enumerate(rede["transformers"], start=1):
        xs, ys = pos[t["source"]]
        xr, yr = pos[t["target"]]
        ym, yc = ys - 0.62, ys - 1.05
        linha(ax, (xs, ys), (xs, ym + 0.30))
        transformador(ax, xs, ym, f"T{i}  {t['power']:g} kVA\n13,8/0,38 kV")
        linha(ax, (xs, ym - 0.30), (xs, yc))
        linha(ax, (xs, yc), (xr, yc))
        descida(ax, xr, yc, yr, horizontais)

    # Barras e dispositivos. O rótulo e a pilha de dispositivos ficam em lados
    # distintos, e nunca do lado por onde sai um ramal: numa cadeia horizontal o
    # rótulo vai acima e os dispositivos abaixo; numa vertical o rótulo vai à
    # esquerda e os dispositivos à direita.
    for n in rede["nodes"]:
        b = n["name"]
        if b not in pos:
            continue
        x, y = pos[b]
        if b in mt_nomes:
            barra(ax, x, y, b, dy=0.26)
            continue
        vertical = eixos.get(b, 0) == 1
        lado = livre.get(b, 1)
        if vertical:
            # Numa cadeia vertical os glifos saem para o lado sem ramal, e o
            # rótulo vai acima, deslocado para o lado OPOSTO ao dos glifos. Pôr
            # o rótulo na horizontal da barra o faria cair ou sobre a fila de
            # glifos ou sobre o sub-ramal, que ocupam os dois lados.
            barra(ax, x, y, b, dx=-0.14 * lado, dy=0.24,
                  ha="left" if lado < 0 else "right", va="bottom")
        elif b in raizes:
            # na raiz do alimentador a descida do transformador chega por cima
            barra(ax, x, y, b, dx=-0.26, dy=0.0, ha="right", va="center")
        elif lado > 0:
            barra(ax, x, y, b, dy=0.24)
        else:
            barra(ax, x, y, b, dy=-0.26, va="top")
        # Numa cadeia horizontal rótulo e glifos disputam o mesmo lado, o que
        # sobrou do ramal, então a pilha começa depois do rótulo. Numa vertical
        # o rótulo fica à esquerda e a pilha à direita, sem disputa.
        d = 0.36 if (vertical or b in raizes) else 0.66
        for tem, glifo in ((b in pv, lambda X, Y: modulo_pv(ax, X, Y)),
                           (b in b_pros, lambda X, Y: bateria(ax, X, Y, AZUL)),
                           (b in b_rede, lambda X, Y: bateria(ax, X, Y, VERMELHO))):
            if not tem:
                continue
            glifo(x + lado * d, y) if vertical else glifo(x, y + lado * d)
            d += 0.36

    itens = [
        Line2D([], [], marker="s", color="none", markerfacecolor="white",
               markeredgecolor=VERMELHO, markersize=9, markeredgewidth=1.4,
               label="Dispositivo de armazenamento de rede"),
        Line2D([], [], marker="s", color="none", markerfacecolor="white",
               markeredgecolor=AZUL, markersize=9, markeredgewidth=1.4,
               label="Dispositivo de armazenamento de prosumidor"),
        Line2D([], [], marker="s", color="none", markerfacecolor="white",
               markeredgecolor=TINTA, markersize=9, markeredgewidth=1.1,
               label="Modulo de geracao fotovoltaica"),
    ]
    ax.legend(handles=itens, loc="lower left", frameon=False, fontsize=9,
              handletextpad=0.8, borderaxespad=0.4)

    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.tight_layout(pad=0.3)
    fig.savefig(saida, dpi=170, facecolor="white")
    print(f"gravado {saida}")
    print(f"  {len(rede['nodes'])} barras, {len(rede['transformers'])} "
          f"transformadores, {len(pv)} com geracao, {len(b_pros)} com bateria "
          f"de prosumidor, {len(b_rede)} com bateria de rede")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pasta", help="pasta da rede (com force.json e config.json)")
    ap.add_argument("-o", "--out", default=None)
    a = ap.parse_args()
    saida = a.out or str(Path(a.pasta) / "diagrama.png")
    desenhar(a.pasta, saida)
