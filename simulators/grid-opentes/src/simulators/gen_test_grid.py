"""Gerador de redes de teste de baixa tensão, a partir de uma descrição compacta.

POR QUE ESTE MÓDULO EXISTE
--------------------------
O `gen_market_grid.py` converte o `force.json` da tese de referência: ele lê uma
rede pronta. Aqui é o contrário, a rede é PROJETADA a partir de parâmetros, o que
permite dimensioná-la para exibir os fenômenos que se quer estudar.

O motivo é concreto. A rede da tese tem alimentadores de 60 a 180 m com cabo de
15 mm², e razão de PV instalado sobre carga instalada de 0,37. Com isso a
sobretensão **nunca** aparece: ao meio-dia há exportação líquida, mas espalhada
por cinco alimentadores curtos, o que dá cerca de 0,006 pu de elevação em cada
um. Estudar o mercado nos dois extremos da faixa de tensão exige uma rede em que
os dois extremos ocorram.

O QUE O GERADOR EMITE
---------------------
Tudo o que a camada de mercado consome, para que a rede seja autocontida:

    <NOME>/Master.dss, _LineCodes.dss, _Lines.dss,
           _Transformers.dss, _Loads.dss     circuito OpenDSS
    <NOME>/force.json                        topologia, no formato que o
                                             `config.load_case` já lê
    <NOME>/config.json                       alocação de dispositivos por barra
    <NOME>/load_kw.csv, pv_kw.csv            perfis de 96 intervalos

PROCEDÊNCIA DOS DADOS
---------------------
As FORMAS das curvas de carga e de geração vêm do SimBench, reaproveitadas dos
perfis já usados no projeto; o DIMENSIONAMENTO por barra é deste trabalho. Os
condutores são cabo multiplexado de alumínio com valores de tabela de
concessionária; os transformadores seguem a NBR 5440.
"""

import argparse
import json
import math
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
PERIODOS = 96

# --- condutores --------------------------------------------------------------
# Cabo multiplexado de alumínio, valores de tabela de concessionária. O tronco de
# 70 mm² e o ramal de 35 mm² são os dois calibres usuais em rede secundária.
LINECODES = {
    "MT_336MCM": dict(r=0.190, x=0.380, c=9.5, amps=400,
                      nota="tronco de media tensao, 336 MCM CAA"),
    "BT_TRONCO_70": dict(r=0.443, x=0.083, c=0.0, amps=150,
                         nota="multiplexado 3x70+70 mm2 Al"),
    "BT_RAMAL_35": dict(r=0.868, x=0.093, c=0.0, amps=100,
                        nota="multiplexado 3x35+35 mm2 Al"),
}

# O OpenDSS exige Z0 != Z1. Relação típica de rede aérea.
Z0_R, Z0_X, Z0_C = 3.0, 3.0, 0.5

# --- transformadores (NBR 5440) ---------------------------------------------
TRAFO_VK_PCT = 3.5       # tensao de curto-circuito
TRAFO_VKR_PCT = 1.4      # parte resistiva
TRAFO_PFE_PCT = 0.25     # perdas no ferro
TRAFO_I0_PCT = 0.25      # corrente de excitacao

KV_MT = 13.8
KV_BT = 0.38
FREQ = 60
LOAD_PF = 0.92           # residencial tipico
# A faixa larga impede o OpenDSS de trocar o modelo de carga para impedancia
# constante quando a tensao sai do intervalo, o que mascararia a violacao.
LOAD_VMINPU, LOAD_VMAXPU = 0.7, 1.4


def _bus(n):
    return f"n{n}"


# ---------------------------------------------------------------------------
# Descrição da rede
# ---------------------------------------------------------------------------

def ramal(em, n, ramais=(), vao_m=None):
    """Um ramal lateral de `n` barras, pendurado na barra `em` da cadeia mãe
    (contando de 1). Pode ter os seus próprios ramais.
    """
    return dict(em=em, n=n, ramais=tuple(ramais), vao_m=vao_m)


def alimentador(tronco, vao_m, ramais=()):
    """Descreve um alimentador radial RAMIFICADO: um tronco de `tronco` barras
    igualmente espaçadas, com ramais laterais pendurados nele.

    Uma cadeia única, que era o que este gerador produzia antes, não é o que uma
    rede secundária real parece: o transformador alimenta um tronco e dele saem
    ramais para as ruas transversais. A diferença não é só de desenho. Numa
    cadeia, a impedância até a barra k é a soma de k vãos iguais, e a tensão cai
    de forma monótona; numa árvore, duas barras à mesma distância elétrica ficam
    em ramos distintos e reagem à injeção uma da outra apenas pelo trecho comum
    do caminho. É isso que dá sentido à sensibilidade dV/dP ser uma MATRIZ cheia,
    e não uma diagonal dominante.

    O calibre segue o nível: tronco em 70 mm², ramal em 35 mm², que é a prática
    usual e substitui a regra por posição que havia aqui antes.
    """
    return dict(n=tronco, vao_m=vao_m, ramais=tuple(ramais))


def _expandir(spec, raiz, estado, nivel):
    """Cria as barras de uma cadeia e, recursivamente, as dos seus ramais.

    Registra por barra a DISTÂNCIA elétrica até o transformador, medida ao longo
    do caminho, e o nível de ramificação. A distância é o que decide onde vai a
    geração: numa árvore ela não coincide mais com a ordem de criação.
    """
    cadeia, anterior = [], raiz
    dist = estado["dist"][raiz]
    for _ in range(spec["n"]):
        b = estado["prox"]; estado["prox"] += 1
        dist += spec["vao_m"]
        estado["barras"].append(b)
        estado["dist"][b] = dist
        estado["nivel"][b] = nivel
        estado["linhas"].append(dict(
            nome=f"bt_{anterior}_{b}", de=anterior, para=b,
            km=spec["vao_m"] / 1000.0, nivel=nivel,
            calibre="BT_TRONCO_70" if nivel == 0 else "BT_RAMAL_35"))
        cadeia.append(b)
        anterior = b
    for r in spec["ramais"]:
        mae = cadeia[r["em"] - 1]
        _expandir(dict(n=r["n"], vao_m=r["vao_m"] or spec["vao_m"],
                       ramais=r["ramais"]), mae, estado, nivel + 1)
    return cadeia


def construir(spec):
    """Expande a descrição em listas de barras, linhas e transformadores."""
    barras_mt = [0]                      # 0 e a subestacao
    linhas, trafos, barras_bt = [], [], []
    prox = 1

    # tronco de media tensao: uma barra por transformador
    for i, t in enumerate(spec["transformadores"]):
        b_mt = prox; prox += 1
        barras_mt.append(b_mt)
        origem = barras_mt[-2]
        linhas.append(dict(nome=f"mt_{origem}_{b_mt}", de=origem, para=b_mt,
                           km=t["dist_mt_m"] / 1000.0, calibre="MT_336MCM"))
        t["_barra_mt"] = b_mt

    # alimentadores de baixa tensao
    for t in spec["transformadores"]:
        b_raiz = prox; prox += 1
        barras_bt.append(b_raiz)
        trafos.append(dict(nome=f"trafo_{t['_barra_mt']}_{b_raiz}",
                           mt=t["_barra_mt"], bt=b_raiz, kva=t["kva"]))
        estado = dict(prox=prox, barras=[], linhas=linhas,
                      dist={b_raiz: 0.0}, nivel={b_raiz: 0})
        _expandir(t["alimentador"], b_raiz, estado, 0)
        prox = estado["prox"]
        barras_bt.extend(estado["barras"])
        t["_barra_bt"] = b_raiz
        t["_barras"] = [b_raiz] + estado["barras"]
        t["_dist"] = estado["dist"]
        t["_nivel"] = estado["nivel"]

    return dict(barras_mt=barras_mt, barras_bt=barras_bt,
                linhas=linhas, trafos=trafos, spec=spec)


# ---------------------------------------------------------------------------
# Emissão do circuito OpenDSS
# ---------------------------------------------------------------------------

def emitir_linecodes():
    out = ["! Condutores: cabo multiplexado de aluminio (tabela de concessionaria)",
           "! e tronco de media tensao. Z0 != Z1 e exigencia do OpenDSS.", ""]
    for nome, p in LINECODES.items():
        out.append(
            f"New LineCode.{nome} nphases=3 units=km"
            f" R1={p['r']} X1={p['x']} C1={p['c']}"
            f" R0={p['r'] * Z0_R:.6g} X0={p['x'] * Z0_X:.6g} C0={p['c'] * Z0_C:.6g}"
            f" normamps={p['amps']} emergamps={p['amps']}   ! {p['nota']}")
    return out


def emitir_linhas(rede):
    out = ["! Linhas. Comprimento em km.", ""]
    for l in rede["linhas"]:
        out.append(f"New Line.{l['nome']} phases=3"
                   f" bus1={_bus(l['de'])} bus2={_bus(l['para'])}"
                   f" linecode={l['calibre']} length={l['km']:.6f} units=km")
    return out


def emitir_trafos(rede):
    out = [f"! Transformadores NBR 5440. vk={TRAFO_VK_PCT}%, vkr={TRAFO_VKR_PCT}%.", ""]
    xhl = math.sqrt(max(TRAFO_VK_PCT ** 2 - TRAFO_VKR_PCT ** 2, 1e-9))
    for t in rede["trafos"]:
        out.append(
            f"New Transformer.{t['nome']} phases=3 windings=2"
            f" xhl={xhl:.6g} %loadloss={TRAFO_VKR_PCT:.6g}"
            f" %noloadloss={TRAFO_PFE_PCT} %imag={TRAFO_I0_PCT}"
            f"\n~ wdg=1 bus={_bus(t['mt'])} conn=delta kv={KV_MT} kva={t['kva']}"
            f"\n~ wdg=2 bus={_bus(t['bt'])} conn=wye kv={KV_BT} kva={t['kva']}")
    return out


def emitir_cargas(rede, cargas_kw):
    out = ["! Cargas. P e Q sao sobrescritos pelos agentes em tempo de execucao;",
           "! o valor aqui e o pico, usado quando se roda o circuito sozinho.", ""]
    tan_phi = math.tan(math.acos(LOAD_PF))
    for b in rede["barras_bt"]:
        kw = cargas_kw.get(b, 0.0)
        if kw <= 0:
            continue
        out.append(f"New Load.Load_{b} phases=3 bus1={_bus(b)} kV={KV_BT}"
                   f" kW={kw:.4f} kvar={kw * tan_phi:.4f} model=1"
                   f" vminpu={LOAD_VMINPU} vmaxpu={LOAD_VMAXPU} conn=wye")
    return out


def emitir_master(nome, spec):
    return [
        f"! Rede {nome}: {spec['descricao']}",
        "! Gerada por src/simulators/gen_test_grid.py. NAO EDITAR A MAO.",
        "",
        "Clear",
        f"Set DefaultBaseFrequency={FREQ}",
        "",
        f"New Circuit.{nome} bus1=n0 basekV={KV_MT} pu=1.0 phases=3",
        "! Fonte forte: o objeto de estudo e a queda na rede de distribuicao,",
        "! nao a impedancia do sistema de subtransmissao.",
        "~ MVAsc3=100000 MVAsc1=105000",
        "",
        f"Redirect {nome}_LineCodes.dss",
        f"Redirect {nome}_Lines.dss",
        f"Redirect {nome}_Transformers.dss",
        f"Redirect {nome}_Loads.dss",
        "",
        f"Set VoltageBases=[{KV_MT}, {KV_BT}]",
        "CalcVoltageBases",
        "",
        "Set Mode=snap",
        "Solve",
    ]


# ---------------------------------------------------------------------------
# Topologia e dispositivos, no formato que a camada de mercado já lê
# ---------------------------------------------------------------------------

def emitir_force_json(rede, cargas_kw):
    spec = rede["spec"]
    nodes = []
    for b in rede["barras_mt"]:
        nodes.append(dict(name=b, voltage_level="medium voltage",
                          active_power=0, reactive_power=0, id=b))
    for b in rede["barras_bt"]:
        nodes.append(dict(name=b, voltage_level="low voltage",
                          active_power=round(cargas_kw.get(b, 0.0), 4),
                          reactive_power=0, id=b))
    links = [dict(name=l["nome"], type="line", length=l["km"],
                  source=l["de"], target=l["para"],
                  # nivel de ramificacao: 0 e tronco, 1 e ramal, 2 e sub-ramal.
                  # Vem do projeto da rede, e e o que decide o calibre.
                  level=l.get("nivel"), linecode=l["calibre"])
             for l in rede["linhas"]]
    trafos = []
    for t, s in zip(rede["trafos"], spec["transformadores"]):
        trafos.append(dict(name=t["nome"], source=t["mt"], target=t["bt"],
                           power=t["kva"], nodes=s["_barras"],
                           bess_nodes=s["_rede"], prosumer_bess_nodes=s["_prosumidor"]))
    return dict(directed=False, multigraph=False, graph={},
                nodes=nodes, links=links, transformers=trafos)


def emitir_config_json(rede, cargas_kw, pv_kwp):
    """Alocação de dispositivos por barra, no formato do `config.json` da tese."""
    spec = rede["spec"]
    dev = {}

    dev["user_action_device"] = {"params": {
        str(b): {"size": round(cargas_kw[b], 4)}
        for b in rede["barras_bt"] if cargas_kw.get(b, 0) > 0}}

    dev["stochastic_gen"] = {"params": {
        str(b): {"size": round(kwp, 4)} for b, kwp in sorted(pv_kwp.items())}}

    def _bateria(barras, kwh, fluxo):
        return {"params": {str(b): {
            "size": kwh, "max_energy_flow": fluxo,
            "min_soc": 0.1 * kwh, "max_soc": 0.9 * kwh} for b in sorted(barras)}}

    pros = [b for t in spec["transformadores"] for b in t["_prosumidor"]]
    rede_b = [b for t in spec["transformadores"] for b in t["_rede"]]
    dev["storage_device"] = _bateria(pros, spec["bateria_prosumidor_kwh"],
                                     spec["bateria_prosumidor_kw"])
    dev["dso_storage_device"] = _bateria(rede_b, spec["bateria_rede_kwh"],
                                         spec["bateria_rede_kw"])

    return {"qtd_nodes_mv": len(rede["barras_mt"]),
            "max_demand_kva": sum(t["kva"] for t in rede["trafos"]),
            "devices": dev,
            "nodes_lv": rede["barras_bt"],
            "nodes_mv": rede["barras_mt"]}


# ---------------------------------------------------------------------------
# Perfis
# ---------------------------------------------------------------------------

def formas_do_simbench(origem, quantas):
    """Formas normalizadas de carga e de geração, tiradas dos perfis já no projeto.

    As curvas vêm do SimBench e são reaproveitadas aqui apenas como FORMA: cada
    coluna é dividida pelo próprio máximo, e o dimensionamento por barra é
    aplicado depois. Assim a diversidade entre unidades consumidoras é a de uma
    base real, e não um seno inventado.
    """
    import csv

    def ler(caminho):
        with open(caminho) as f:
            linhas = list(csv.DictReader(f))
        cols = list(linhas[0])
        out = []
        for c in cols:
            v = [float(l[c]) for l in linhas]
            m = max(v)
            out.append([x / m for x in v] if m > 0 else v)
        return out

    carga = ler(origem / "load_kw.csv")
    pv = ler(origem / "pv_kw.csv")
    pv = [c for c in pv if max(c) > 0]        # descarta as barras sem geracao
    return ([carga[i % len(carga)] for i in range(quantas)],
            [pv[i % len(pv)] for i in range(quantas)])


def emitir_perfis(rede, cargas_kw, pv_kwp, origem):
    formas_c, formas_p = formas_do_simbench(origem, len(rede["barras_bt"]))
    carga_col, pv_col = {}, {}
    for i, b in enumerate(rede["barras_bt"]):
        pico = cargas_kw.get(b, 0.0)
        carga_col[b] = [pico * x for x in formas_c[i]]
        kwp = pv_kwp.get(b, 0.0)
        pv_col[b] = [kwp * x for x in formas_p[i]] if kwp > 0 else [0.0] * PERIODOS
    return carga_col, pv_col


def gravar_csv(caminho, colunas, barras):
    linhas = [",".join(str(b) for b in barras)]
    for t in range(PERIODOS):
        linhas.append(",".join(f"{colunas[b][t]:.6f}" for b in barras))
    caminho.write_text("\n".join(linhas) + "\n")


# ---------------------------------------------------------------------------
# Montagem
# ---------------------------------------------------------------------------

def gerar(spec, origem_perfis, destino_raiz=DATA_DIR):
    import random

    rng = random.Random(spec.get("semente", 0))
    rede = construir(spec)

    # --- dimensionamento por barra ------------------------------------------
    cargas_kw, pv_kwp = {}, {}
    for t in spec["transformadores"]:
        barras = t["_barras"][1:]          # a raiz do alimentador nao tem carga
        lo, hi = t["carga_kw"]
        for b in barras:
            cargas_kw[b] = round(rng.uniform(lo, hi), 3)
        n_pv = round(t["fracao_pv"] * len(barras))
        # A geracao vai nas barras mais distantes do transformador, medidas pelo
        # comprimento do CAMINHO e nao pela ordem de criacao: numa arvore as
        # duas coisas deixam de coincidir. E o caso que a concessionaria teme e
        # o que produz sobretensao, porque quanto maior a impedancia acumulada,
        # maior a elevacao que a mesma injecao provoca.
        longe = sorted(barras, key=lambda b: -t["_dist"][b])
        for b in longe[:n_pv]:
            pv_kwp[b] = round(t["pv_kwp"], 3)
        # armazenamento
        cand = list(barras)
        rng.shuffle(cand)
        n_pros = round(t["fracao_bateria_prosumidor"] * len(barras))
        n_rede = round(t["fracao_bateria_rede"] * len(barras))
        t["_prosumidor"] = sorted(cand[:n_pros])
        t["_rede"] = sorted(cand[n_pros:n_pros + n_rede])

    nome = spec["nome"]
    destino = destino_raiz / nome
    destino.mkdir(parents=True, exist_ok=True)

    (destino / f"{nome}_LineCodes.dss").write_text("\n".join(emitir_linecodes()) + "\n")
    (destino / f"{nome}_Lines.dss").write_text("\n".join(emitir_linhas(rede)) + "\n")
    (destino / f"{nome}_Transformers.dss").write_text("\n".join(emitir_trafos(rede)) + "\n")
    (destino / f"{nome}_Loads.dss").write_text("\n".join(emitir_cargas(rede, cargas_kw)) + "\n")
    (destino / "Master.dss").write_text("\n".join(emitir_master(nome, spec)) + "\n")
    (destino / "force.json").write_text(json.dumps(emitir_force_json(rede, cargas_kw), indent=1))
    (destino / "config.json").write_text(json.dumps(emitir_config_json(rede, cargas_kw, pv_kwp), indent=1))

    carga_col, pv_col = emitir_perfis(rede, cargas_kw, pv_kwp, origem_perfis)
    gravar_csv(destino / "load_kw.csv", carga_col, rede["barras_bt"])
    gravar_csv(destino / "pv_kw.csv", pv_col, rede["barras_bt"])

    # O preco spot nao depende da rede: e a serie do Nordpool ja usada no projeto.
    (destino / "spot_price.csv").write_text((origem_perfis / "spot_price.csv").read_text())

    # Reservatorio de dias alternativos, para o modelo estocastico do prosumidor
    # e para o modo severo de demanda realizada. Cada dia e o dia base com um
    # fator por barra, o que preserva a forma e varia o nivel: e o que o
    # prosumidor enxerga como incerteza.
    import numpy as np
    barras = rede["barras_bt"]
    dias_carga, dias_pv, dias_preco = [], [], []
    preco = [float(l) for l in (destino / "spot_price.csv").read_text().split("\n")[1:] if l.strip()]
    for _ in range(spec.get("dias_no_reservatorio", 9)):
        fc = np.array([rng.uniform(0.75, 1.25) for _ in barras])[:, None]
        fp = np.array([rng.uniform(0.80, 1.15) for _ in barras])[:, None]
        dias_carga.append(np.array([carga_col[b] for b in barras]) * fc)
        dias_pv.append(np.array([pv_col[b] for b in barras]) * fp)
        dias_preco.append(np.array(preco) * rng.uniform(0.85, 1.15))
    np.savez(destino / "scenario_pool.npz", nodes=np.array(barras),
             load=np.array(dias_carga), pv=np.array(dias_pv),
             price=np.array(dias_preco))

    # --- resumo --------------------------------------------------------------
    soma_c = sum(cargas_kw.values())
    soma_p = sum(pv_kwp.values())
    print(f"{destino}")
    print(f"  {len(rede['barras_mt'])} barras de MT, {len(rede['barras_bt'])} de BT, "
          f"{len(rede['trafos'])} transformadores, {len(rede['linhas'])} linhas")
    print(f"  carga instalada {soma_c:.1f} kW  |  PV instalado {soma_p:.1f} kWp  "
          f"|  razao {soma_p / soma_c:.2f}")
    for t, tr in zip(spec["transformadores"], rede["trafos"]):
        d = t["_dist"]
        print(f"  {tr['nome']:>14} {tr['kva']:>5} kVA  "
              f"{len(t['_barras']) - 1:>2} barras  "
              f"barra mais distante {max(d.values()):>4.0f} m  "
              f"{len(t['_prosumidor'])} prosumidores, "
              f"{len(t['_rede'])} baterias de rede")
    return destino, rede, cargas_kw, pv_kwp


# ---------------------------------------------------------------------------
# As redes
# ---------------------------------------------------------------------------

# Rede de bancada. Pequena de proposito: serve para iterar rapido sobre o
# mecanismo de mercado, e nao para representar um sistema real em detalhe.
#
# Dimensionamento, e o porque de cada numero:
#   - alimentador de 300 m com tronco de 70 mm2. Com 15 mm2 e 180 m, que e a rede
#     da tese, a elevacao de tensao por kW injetado e pequena demais para a
#     sobretensao aparecer.
#   - cada barra representa um AGRUPAMENTO de unidades consumidoras, e nao uma
#     casa. E como a rede secundaria costuma ser modelada, e e o que da carga
#     compativel com um transformador de 45 kVA: 8 pontos de 6 a 10 kW dao cerca
#     de 60 kW instalados por alimentador, com coincidencia proxima de 0,5.
#   - razao de PV sobre carga proxima de 1,4. E o que faz a exportacao ao
#     meio-dia ter magnitude comparavel ao pico da noite, e portanto os dois
#     extremos da faixa serem exercitados. Alimentadores com essa penetracao
#     existem e sao justamente o caso que motiva o controle transativo.
#   - PV nas barras mais distantes do transformador, que e onde a mesma injecao
#     provoca a maior elevacao.
BT16 = dict(
    nome="BT16",
    descricao="rede de bancada, 2 alimentadores de baixa tensao com alta "
              "penetracao fotovoltaica",
    semente=7,
    bateria_prosumidor_kwh=12.0, bateria_prosumidor_kw=3.6,
    bateria_rede_kwh=30.0, bateria_rede_kw=9.0,
    transformadores=[
        # tronco de 4 barras com tres ramais laterais: 8 barras de carga, a
        # mais distante a 300 m do transformador
        dict(dist_mt_m=400, kva=45,
             alimentador=alimentador(tronco=4, vao_m=60, ramais=(
                 ramal(em=2, n=1), ramal(em=3, n=1), ramal(em=4, n=2))),
             carga_kw=(6.0, 10.0), pv_kwp=7.0, fracao_pv=0.75,
             fracao_bateria_prosumidor=0.625, fracao_bateria_rede=0.25),
        dict(dist_mt_m=350, kva=45,
             alimentador=alimentador(tronco=4, vao_m=60, ramais=(
                 ramal(em=2, n=1), ramal(em=3, n=1), ramal(em=4, n=2))),
             carga_kw=(6.0, 10.0), pv_kwp=7.0, fracao_pv=0.75,
             fracao_bateria_prosumidor=0.625, fracao_bateria_rede=0.25),
    ],
)


# Rede final do trabalho. Diferente da de bancada em intencao, e nao so em
# tamanho: ali os dois alimentadores sao iguais, e a sobretensao e a subtensao
# ocorrem no MESMO alimentador, em horarios diferentes. Aqui elas ocorrem em
# alimentadores DIFERENTES e em horarios diferentes, porque os quatro
# alimentadores tem caracter distinto:
#
#   T1, urbano denso     75 kVA, 210 m, carga alta, pouca geracao no telhado.
#                        Nunca exporta; sofre a queda de tensao do pico noturno.
#   T2, suburbano        45 kVA, 405 m, carga e geracao medias. E o alimentador
#                        neutro, o que serve de referencia.
#   T3, condominio solar 45 kVA, 495 m, geracao em TODAS as barras. E onde a
#                        sobretensao aparece, das 08:45 as 13:30.
#   T4, ponta rural      30 kVA, 660 m com ramal fino, carga baixa e dispersa.
#                        E onde a subtensao e severa, sobretudo das 14:45 as 22:15.
#
# A penetracao DESIGUAL entre alimentadores e o ponto do projeto. No fluxo do dia
# sem armazenamento, nenhum intervalo tem subtensao e sobretensao ao mesmo tempo;
# o preco sombra ainda assume os dois sinais no mesmo intervalo (52 de 96 na
# decomposicao centralizada), porque o armazenamento acopla os intervalos.
#
# A razao global de PV sobre carga fica em 0,39 no pico e 0,41 em energia, na
# faixa do 0,37 da rede da tese. O que produz a sobretensao nao e a razao global,
# e como ela se distribui. Pico de PV sobre pico de carga, medido nos CSV: 0,12
# em T1, 0,44 em T2, 0,72 em T3 e 0,24 em T4. A tese tem 0,37 espalhado por
# igual, e por isso nao ve sobretensao nenhuma.
#
# Calibracao. A violacao precisa ser grande o bastante para ser o objeto do
# estudo e pequena o bastante para o modelo do DSO continuar viavel: nenhum
# despacho de armazenamento traz 1,13 pu para 1,03. Com os valores abaixo a
# decomposicao dual converge em 42 rodadas sem violacao no modelo linear.
BT38 = dict(
    nome="BT38",
    descricao="rede final, 4 alimentadores de baixa tensao com penetracao "
              "fotovoltaica desigual entre eles",
    semente=13,
    bateria_prosumidor_kwh=14.0, bateria_prosumidor_kw=5.0,
    bateria_rede_kwh=40.0, bateria_rede_kw=12.0,
    transformadores=[
        # urbano denso: tronco curto e tres ramais de uma barra, que e a
        # quadra densa servida por um so transformador. 180 m ate a ponta.
        dict(dist_mt_m=600, kva=75,
             alimentador=alimentador(tronco=3, vao_m=45, ramais=(
                 ramal(em=1, n=1), ramal(em=2, n=1), ramal(em=3, n=1))),
             carga_kw=(9.0, 14.0), pv_kwp=4.0, fracao_pv=0.34,
             fracao_bateria_prosumidor=0.50, fracao_bateria_rede=0.17),
        # suburbano: tronco de 5 com dois ramais de 2. 385 m ate a ponta.
        dict(dist_mt_m=800, kva=45,
             alimentador=alimentador(tronco=5, vao_m=55, ramais=(
                 ramal(em=2, n=2), ramal(em=4, n=2))),
             carga_kw=(6.0, 10.0), pv_kwp=6.0, fracao_pv=0.55,
             fracao_bateria_prosumidor=0.55, fracao_bateria_rede=0.22),
        # condominio solar: tronco de 6, um ramal com sub-ramal e outro de 2.
        # 480 m ate a ponta, e geracao em TODAS as barras.
        dict(dist_mt_m=1000, kva=45,
             alimentador=alimentador(tronco=6, vao_m=60, ramais=(
                 ramal(em=3, n=2, ramais=(ramal(em=1, n=1),)),
                 ramal(em=5, n=2))),
             carga_kw=(4.5, 8.0), pv_kwp=4.6, fracao_pv=1.0,
             fracao_bateria_prosumidor=0.55, fracao_bateria_rede=0.18),
        # ponta rural: tronco longo de 8 com dois ramais de 2. 650 m ate a
        # ponta, em cabo fino a partir do primeiro ramal.
        dict(dist_mt_m=1200, kva=30,
             alimentador=alimentador(tronco=8, vao_m=75, ramais=(
                 ramal(em=4, n=2), ramal(em=7, n=2))),
             carga_kw=(3.0, 5.5), pv_kwp=3.0, fracao_pv=0.30,
             fracao_bateria_prosumidor=0.50, fracao_bateria_rede=0.20),
    ],
)

REDES = {"BT16": BT16, "BT38": BT38}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("rede", choices=sorted(REDES), help="qual rede gerar")
    ap.add_argument("--perfis", default=None,
                    help="pasta com load_kw.csv e pv_kw.csv de onde tirar as "
                         "formas (padrao: os perfis do mercado)")
    a = ap.parse_args()
    origem = Path(a.perfis) if a.perfis else (
        Path(__file__).resolve().parents[3] / "market-opentes" / "data")
    gerar(REDES[a.rede], origem)


if __name__ == "__main__":
    main()
