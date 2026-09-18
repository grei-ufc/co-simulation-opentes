"""Topologia de radio 6TiSCH para as redes geradas pelo repositorio (BT16, BT38).

POR QUE EXISTE
--------------
O servidor 6TiSCH (`comm-opentes/Tisch.cc`) precisa da posicao de cada agente:
e da distancia entre dois radios que sai o PER do enlace. A tese publica as
posicoes da MVLV75 no Apendice B; as redes proprias nao tem nenhuma. Sem arquivo
de posicoes, o servidor entrega SEM ATRASO todo agente que nao encontra, e a
co-simulacao roda medindo uma rede que nao existe. O `run.sh` recusa rodar nesse
caso, e este modulo produz o arquivo que falta.

A GEOMETRIA
-----------
O `force.json` das redes geradas por `gen_test_grid.py` traz a arvore e o
comprimento de cada trecho, mas nenhuma coordenada. O diagrama unifilar
(`plot_grid.posicionar`) tem coordenadas, porem de desenho, sem escala. Aqui as
DIRECOES vem do desenho e os COMPRIMENTOS vem do `length` real de cada linha, o
mesmo principio usado na IEEE 13. A distancia em linha reta entre dois agentes
sai dessa geometria.

O transformador nao tem linha no `force.json`: a barra de baixa tensao fica no
poste dele, a TRAFO_M metros da barra de media tensao.

A adjacencia NAO e publicada para estas redes. O servidor a reconstroi pelo
limiar de PER 0,5, com o orcamento de radio padrao (0 dBm, sem ganho de antena).
Na MVLV75 essa reconstrucao deu uma rede duas vezes e meia mais densa que a
publicada, ou seja, resultados de comunicacao OTIMISTAS. Vale o mesmo aviso aqui.

O QUE O ARQUIVO PRECISA CONTER
------------------------------
Os nomes que o `node_map_from_case` (network_link.py) procura: cada no de baixa
tensao, o no de media tensao de cada transformador, que e onde fica o Agente
Concentrador, e "DSO" e "Market", que ficam na subestacao (no 0), como no
Apendice B da tese.

Uso, dentro do container grid:

    python src/simulators/gen_tisch_topology.py BT16 BT38
"""

import json
import math
import sys
from pathlib import Path

import numpy as np

try:
    from plot_grid import posicionar
except ImportError:                      # executado como pacote
    from simulators.plot_grid import posicionar

DATA = Path(__file__).resolve().parents[1] / "data"
TRAFO_M = 10.0

# Mesmo modelo do Tisch.cc: Friis a 915 MHz, Pister-Hack de 0 a 40 dB, Tabela 7
# da tese e limiar de PER 0,5.
FREQ_HZ = 915e6
TX_DBM = 0.0
SHIFT_DB = 40.0
SENSIBILIDADE_DBM = -106.37
PER_TABELA = [1.0, 0.8, 0.4, 0.15, 0.03, 0.006, 0.0015, 0.0]
LIMIAR_PER = 0.5


def posicoes(rede):
    """Coordenadas em metros por no: direcao do desenho, comprimento real."""
    esquema = posicionar(rede)
    viz = {}
    for l in rede["links"]:
        metros = float(l["length"]) * 1000.0          # force.json em km
        viz.setdefault(l["source"], []).append((l["target"], metros))
        viz.setdefault(l["target"], []).append((l["source"], metros))
    for t in rede["transformers"]:
        viz.setdefault(t["source"], []).append((t["target"], TRAFO_M))
        viz.setdefault(t["target"], []).append((t["source"], TRAFO_M))

    pos = {0: np.zeros(2)}
    fila = [0]
    while fila:
        a = fila.pop(0)
        for b, metros in viz.get(a, []):
            if b in pos:
                continue
            d = np.subtract(esquema[b], esquema[a])
            norma = float(np.hypot(*d))
            d = np.array([1.0, 0.0]) if norma < 1e-9 else d / norma
            pos[b] = pos[a] + d * metros
            fila.append(b)
    return pos


def _per(rssi):
    acima = rssi - SENSIBILIDADE_DBM
    if acima <= 0:
        return 1.0
    i = int(acima)
    return PER_TABELA[min(i, len(PER_TABELA) - 1)]


def conectividade(pos, rede, sorteios=400, semente=7):
    """Fracao dos sorteios de Pister-Hack em que todos os agentes se alcancam.

    O servidor sorteia o desvio de propagacao uma vez por enlace. Um sorteio
    desfavoravel pode isolar um concentrador da subestacao, e ai toda mensagem do
    ciclo 2 e do ciclo 3 daquele alimentador e descartada. Melhor saber antes.
    """
    nos = sorted(pos, key=str)
    idx = {n: i for i, n in enumerate(nos)}
    xy = np.array([pos[n] for n in nos])
    dist = np.hypot(*(xy[:, None, :] - xy[None, :, :]).transpose(2, 0, 1))
    with np.errstate(divide="ignore"):
        fspl = 20.0 * np.log10(3e8 / (4.0 * math.pi * np.maximum(dist, 1e-9) * FREQ_HZ))
    pr = TX_DBM + fspl

    lv = [n["name"] for n in rede["nodes"] if n["voltage_level"] == "low voltage"]
    exigidos = set(lv) | {t["source"] for t in rede["transformers"]}
    rng = np.random.default_rng(semente)
    ok = 0
    for _ in range(sorteios):
        rssi = pr - rng.uniform(0.0, SHIFT_DB, size=pr.shape)
        viavel = np.vectorize(_per)(rssi) < LIMIAR_PER
        viavel = np.triu(viavel, 1)
        pai = list(range(len(nos)))

        def raiz(k):
            while pai[k] != k:
                pai[k] = pai[pai[k]]
                k = pai[k]
            return k
        for i, j in zip(*np.nonzero(viavel)):
            pai[raiz(i)] = raiz(j)
        r0 = raiz(idx[0])
        ok += all(raiz(idx[n]) == r0 for n in exigidos)
    return ok / sorteios


def gerar(nome):
    pasta = DATA / nome
    rede = json.loads((pasta / "force.json").read_text())
    pos = posicoes(rede)

    faltando = [n["name"] for n in rede["nodes"] if n["name"] not in pos]
    if faltando:
        raise SystemExit(f"{nome}: nos fora da arvore a partir da subestacao: {faltando}")

    linhas = ["node,x_m,y_m"]
    for n in sorted(pos):
        linhas.append(f"{n},{pos[n][0]:.2f},{pos[n][1]:.2f}")
    linhas.append(f"DSO,{pos[0][0]:.2f},{pos[0][1]:.2f}")
    linhas.append(f"Market,{pos[0][0]:.2f},{pos[0][1]:.2f}")
    (pasta / "nodes_xy.csv").write_text("\n".join(linhas) + "\n")

    # Distancias que decidem se a rede de radio fecha
    d_sub = [float(np.hypot(*pos[t["source"]])) for t in rede["transformers"]]
    d_fim = []
    for t in rede["transformers"]:
        c = pos[t["source"]]
        d_fim.append(max(float(np.hypot(*(pos[n] - c))) for n in t["nodes"]))
    frac = conectividade(pos, rede)
    print(f"{nome}: {len(pos)} posicoes + DSO + Market")
    print(f"  subestacao ate os concentradores: {', '.join(f'{d:.0f} m' for d in d_sub)}")
    print(f"  concentrador ate o prosumidor mais distante: "
          f"{', '.join(f'{d:.0f} m' for d in d_fim)}")
    print(f"  todos os agentes alcancaveis em {100 * frac:.1f}% dos sorteios de "
          f"propagacao")
    return frac


if __name__ == "__main__":
    for nome in sys.argv[1:] or ["BT16", "BT38"]:
        gerar(nome)
