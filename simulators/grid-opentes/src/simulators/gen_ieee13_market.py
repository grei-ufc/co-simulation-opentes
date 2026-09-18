"""Monta o caso de mercado transativo sobre a IEEE 13 barras.

POR QUE UM GERADOR, E NAO ARQUIVOS ESCRITOS A MAO
-------------------------------------------------
A IEEE 13 e um modelo publicado e conferido (IEEE 13 Node Test Feeder,
Distribution System Analysis Subcommittee). Transcrever a topologia a mao para o
`force.json` do mercado abriria espaco para divergir do circuito sem ninguem
perceber. Aqui a topologia e LIDA do circuito ja compilado: barras, nos por
barra, linhas, transformadores e cargas saem do proprio OpenDSS.

O QUE ESTE CASO E, E O QUE ELE NAO E
------------------------------------
A camada de mercado da tese pressupoe uma rede MT/BT com varios transformadores
de distribuicao, um Agente Concentrador por transformador e um Agente Prosumidor
por no de baixa tensao. A IEEE 13 tem UM transformador de distribuicao (XFM-1,
633 para 634) e uma unica barra de baixa tensao. Nesse caso o Concentrador que
agrega os prosumidores e um so, e ele e o proprio alimentador:

  Agente Concentrador  ->  cabeceira do alimentador, transformador da subestacao
                           de 5 MVA (115 kV / 4,16 kV)
  Agente Prosumidor    ->  uma por barra com carga ou geracao: 611, 632, 634,
                           645, 646, 652, 670, 671, 675 e 692

Isso e uma REINTERPRETACAO da arquitetura, nao a arquitetura da tese. Fica
registrada aqui porque muda o significado da restricao de carregamento (Eq.
6.28), que passa a limitar o alimentador inteiro em vez de um transformador de
distribuicao.

DECISOES DE CONVERSAO, TODAS MEDIDAS
------------------------------------
- **Uma carga por no.** A interface do mercado (`loading.py`,
  `market_agents.py`, `sensitivity.py`) escreve `Edit Load.Load_{no} kW=...`,
  ou seja, um elemento por no. As cargas oficiais ficam desabilitadas e cada no
  ganha um `Load_{no}` na MESMA barra, com as MESMAS fases e a MESMA ligacao
  (estrela ou triangulo) da carga oficial. Onde a barra tem tres fases com
  potencias diferentes (634, 670 e 675), o desequilibrio ENTRE FASES da carga se
  perde, porque um elemento `Load` do OpenDSS e equilibrado entre as fases que
  ocupa. Nas demais barras nao ha o que perder: a carga oficial ja e monofasica
  ou trifasica equilibrada.

- **Modelo de carga 1 (potencia constante) em todas.** As cargas oficiais usam os
  modelos 1, 2 e 5. A restricao de tensao do DSO e linearizada em dV/dP com
  potencia constante; manter carga de impedancia constante deixaria o modelo do
  agente e o fluxo de potencia falando de coisas diferentes. `Vminpu` e `Vmaxpu`
  alargados pelo mesmo motivo, como em `gen_market_grid.py`.

- **O PV entra como carga negativa.** Os `PVSystem` ficam desabilitados e a
  geracao vai para o `pv_kw.csv`, que o mercado subtrai da demanda. Consequencia
  a registrar: o PV4 fica fisicamente na fase C da barra 645 e a carga daquela
  barra na fase B, entao no caso de mercado ele passa a injetar na fase B. E o
  unico PV cuja fase muda.

- **Regulador de tensao com o ajuste oficial e derivacoes livres.** Ver a secao
  de regulador abaixo.

Uso, dentro do container grid:

    python src/simulators/gen_ieee13_market.py
"""

import json
import math
from pathlib import Path

import numpy as np
import py_dss_interface

DATA = Path(__file__).resolve().parents[1] / "data" / "13Bus"
BASE_DSS = DATA / "IEEE13Nodeckt_w_loadcurve.dss"

PERIODS = 96          # o mercado trabalha em 96 intervalos de 15 min
DT_MIN = 15

# Barra da subestacao, que vira o no 0 e fica fora da negociacao.
SUBESTACAO = "sourcebus"
# `rg60` e o unico nome de barra nao numerico da rede. O mercado indexa os nos
# por inteiro, entao ele recebe um numero livre.
RENOMEAR = {"rg60": 660, SUBESTACAO: 0}

# Barras que hospedam prosumidor: as que tem carga ou geracao.
PROSUMIDORES = [611, 632, 634, 645, 646, 652, 670, 671, 675, 692]

# Barras que NAO entram na rede vista pelo mercado. Sao os terminais internos da
# subestacao: a saida do transformador (650) e a saida do banco de reguladores
# (rg60). Nao sao ponto de conexao de consumidor e, o que decide, estao a MONTANTE
# de todo o alimentador: medida no proprio dV/dP, a sensibilidade da rg60 a
# injecao em qualquer no com bateria e de 0,05 upu/kW, tres ordens de grandeza
# abaixo da de uma barra de carga. Deixa-las na restricao de tensao do DSO torna
# o problema INFACTIVEL por construcao, porque a rg60 sobe a 1,0416 pu com carga
# leve e nenhum agente pode faze-la descer. O regulador continua atuando no
# circuito; o que sai e a exigencia de que o mercado responda por ele.
FORA_DA_REDE = {"650", "rg60"}

# Onde cada PV esta, e a potencia de placa e do inversor.
PV_POR_NO = {646: ("PV1", 5000, 5000), 632: ("PV2", 3000, 3000),
             634: ("PV3", 3000, 3000), 645: ("PV4", 2000, 2000),
             652: ("PV5", 2000, 2000)}
PT_X, PT_Y = [0, 25, 75, 100], [1.2, 1.0, 0.8, 0.6]
EF_X, EF_Y = [0.1, 0.2, 0.4, 1.0], [0.86, 0.90, 0.93, 0.97]
IRRAD_BASE = 0.8

# Derivacoes do regulador na solucao publicada. Nao sao usadas como valor fixo
# (ver a secao de regulador no ESTUDO_IEEE13.md), ficam registradas para conferir
# o circuito contra a referencia.
TAPS_PUBLICADOS = (10, 8, 11)

# Armazenamento, dimensionado por MEDICAO e nao por regra de bolso.
#
# O procedimento esta no ESTUDO_IEEE13.md: para cada um dos 96 intervalos
# resolve-se, com a matriz de sensibilidade do proprio caso, a menor injecao
# total que mantem TODAS as barras dentro da faixa. Com 1000 kW por no o dia
# inteiro fica factivel; abaixo disso sobra folga (800 kW deixam 0,98 mpu de
# violacao residual, 600 kW deixam 6,3 mpu). A necessidade medida soma 7737 kW
# e 12,3 MWh de energia movimentada, concentrada em 646, 634, 645 e 652, que sao
# as barras onde o PV excede a carga local com folga.
#
# A divisao entre os dois tipos segue a arquitetura: REDE onde o DSO precisa de
# alavanca direta, isto e nas barras que violam, e PROSUMIDOR em todos os nos,
# porque e ele que participa do mercado. O total fica com margem sobre os
# 7737 kW medidos, para o mecanismo ter espaco de negociacao em vez de operar
# colado no limite.
ARMAZ_REDE = {646: 1500.0, 645: 1000.0, 634: 1000.0, 652: 900.0}
ARMAZ_PROSUMIDOR = {611: 500.0, 632: 500.0, 634: 400.0, 645: 300.0, 646: 400.0,
                    652: 300.0, 670: 800.0, 671: 900.0, 675: 900.0, 692: 400.0}
HORAS_DE_ARMAZENAMENTO = 3.3          # capacidade em kWh por kW de potencia
SOC_MIN, SOC_MAX = 0.1, 0.9


# ---------------------------------------------------------------------------
# Leitura do circuito
# ---------------------------------------------------------------------------
def _no(bus):
    """Nome da barra do OpenDSS para o inteiro que o mercado usa."""
    b = bus.split(".")[0].lower()
    # `RENOMEAR.get(b, int(b))` nao serve: o `int(b)` do default e avaliado
    # sempre, inclusive para os nomes que estao justamente no dicionario porque
    # nao sao numericos.
    return RENOMEAR[b] if b in RENOMEAR else int(b)


def ler_circuito():
    dss = py_dss_interface.DSS()
    dss.text(f'compile "{BASE_DSS}"')
    dss.text("Set mode=snap")
    dss.text("Solve")

    barras = {}
    for b in dss.circuit.buses_names:
        dss.circuit.set_active_bus(b)
        barras[b.lower()] = {"nos": list(dss.bus.nodes),
                             "kv_base": float(dss.bus.kv_base)}

    linhas = []
    for n in dss.lines.names:
        dss.lines.name = n
        linhas.append({"name": n, "bus1": dss.lines.bus1, "bus2": dss.lines.bus2,
                       "length": float(dss.lines.length),
                       "linecode": dss.lines.linecode})

    cargas = {}
    dss.circuit.set_active_class("Load")
    for n in dss.active_class.names:
        cargas[n] = {"bus1": dss.text(f"? Load.{n}.bus1"),
                     "phases": int(dss.text(f"? Load.{n}.phases")),
                     "conn": dss.text(f"? Load.{n}.conn").strip().lower(),
                     "kv": float(dss.text(f"? Load.{n}.kV")),
                     "kw": float(dss.text(f"? Load.{n}.kW")),
                     "kvar": float(dss.text(f"? Load.{n}.kvar")),
                     "daily": dss.text(f"? Load.{n}.daily")}

    formas = {}
    dss.circuit.set_active_class("LoadShape")
    for n in dss.active_class.names:
        if n == "default":
            continue
        mult = dss.text(f"? LoadShape.{n}.mult")
        formas[n] = {"mult": [float(x) for x in
                              mult.strip("[] ").replace(",", " ").split()],
                     "intervalo_s": float(dss.text(f"? LoadShape.{n}.sinterval"))}
    return barras, linhas, cargas, formas


# ---------------------------------------------------------------------------
# force.json
# ---------------------------------------------------------------------------
def montar_force(barras, linhas, cargas):
    cargas_por_no = {}
    for nome, c in cargas.items():
        cargas_por_no.setdefault(_no(c["bus1"]), []).append((nome, c["kw"]))

    nos = []
    for bus, info in barras.items():
        if bus in FORA_DA_REDE:
            continue
        n = _no(bus)
        base = sum(kw for _, kw in cargas_por_no.get(n, []))
        nos.append({
            "name": n,
            # "low voltage" e o que o `config.py` usa para decidir quem e
            # prosumidor. Aqui isso NAO e o nivel de tensao eletrico: a IEEE 13
            # e um alimentador de media tensao quase inteiro. E o papel no
            # mercado.
            "voltage_level": "low voltage" if n in PROSUMIDORES else "medium voltage",
            "active_power": base,
            "reactive_power": sum(cargas[nm]["kvar"] for nm, _ in cargas_por_no.get(n, [])),
            "id": n,
            "bus": bus,
            "kv_base": info["kv_base"],
            "fases": info["nos"],
            "loads": sorted(nm for nm, _ in cargas_por_no.get(n, [])),
        })
    nos.sort(key=lambda x: x["name"])

    links = [{"name": l["name"], "type": "line",
              "length": l["length"], "source": _no(l["bus1"]),
              "target": _no(l["bus2"]), "level": None, "linecode": l["linecode"]}
             for l in linhas]
    links += [
        {"name": "reg1_2_3", "type": "regulator", "length": 0.0,
         "source": 650, "target": 660, "level": None, "linecode": None},
        {"name": "xfm1", "type": "transformer", "length": 0.0,
         "source": 633, "target": 634, "level": None, "linecode": None},
        {"name": "sub", "type": "transformer", "length": 0.0,
         "source": 0, "target": 650, "level": None, "linecode": None},
    ]

    transformadores = [{
        "name": "alimentador_650",
        "source": 0,
        "target": 650,
        # Transformador da subestacao. Com um unico transformador de
        # distribuicao na rede, o Concentrator que agrega os prosumidores e a
        # propria cabeceira do alimentador.
        "power": 5000.0,
        "nodes": list(PROSUMIDORES),
        "bess_nodes": sorted(ARMAZ_REDE),
        "prosumer_bess_nodes": sorted(ARMAZ_PROSUMIDOR),
    }]

    return {"directed": False, "multigraph": False, "graph": {},
            "nodes": nos, "links": links, "transformers": transformadores}


# ---------------------------------------------------------------------------
# Perfis de 96 intervalos
# ---------------------------------------------------------------------------
def perfis(cargas, formas):
    """Carga e geracao por no, em 96 intervalos de 15 min."""
    carga = {n: np.zeros(PERIODS) for n in PROSUMIDORES}
    for nome, c in cargas.items():
        n = _no(c["bus1"])
        if n not in carga:
            continue
        f = formas[c["daily"].lower()]
        passo_s = f["intervalo_s"]
        for t in range(PERIODS):
            # Mesma indexacao do `api_opendss.step`: o instante do intervalo cai
            # dentro de um ponto da curva, sem interpolar.
            k = int(t * DT_MIN * 60 // passo_s) % len(f["mult"])
            carga[n][t] += c["kw"] * f["mult"][k]

    irr = np.genfromtxt(DATA / "ieee13_shape_pv_5min.csv", delimiter=",",
                        names=True, dtype=None, encoding="utf-8")
    tmp = np.genfromtxt(DATA / "ieee13_temperature_5min.csv", delimiter=",",
                        names=True, dtype=None, encoding="utf-8")
    pv = {n: np.zeros(PERIODS) for n in PROSUMIDORES}
    for n, (nome, pmpp, kva) in PV_POR_NO.items():
        i = nome[2:]
        for t in range(PERIODS):
            k = t * DT_MIN // 5
            g = float(irr[f"my_shape{i}_irrad"][k])
            temp = float(tmp[f"my_shape{i}_temperature"][k])
            p_dc = pmpp * IRRAD_BASE * g * np.interp(temp, PT_X, PT_Y)
            if p_dc <= 0:
                continue
            pv[n][t] = min(p_dc * np.interp(p_dc / kva, EF_X, EF_Y), kva)
    return carga, pv


def escrever_csv(caminho, dados):
    nos = sorted(dados)
    linhas = [",".join(str(n) for n in nos)]
    for t in range(PERIODS):
        linhas.append(",".join(f"{dados[n][t]:.6f}" for n in nos))
    caminho.write_text("\n".join(linhas) + "\n")


def escrever_master(barras, cargas):
    """Circuito do caso de mercado: a IEEE 13 oficial com as cargas do mercado."""
    cargas_por_no = {}
    for nome, c in cargas.items():
        cargas_por_no.setdefault(_no(c["bus1"]), []).append((nome, c))

    linhas = [
        "! Caso de mercado transativo sobre a IEEE 13 barras.",
        "! Gerado por src/simulators/gen_ieee13_market.py. Nao editar a mao.",
        "!",
        "! A rede e a IEEE 13 oficial, sem alteracao: linhas, transformadores,",
        "! regulador e capacitores vem do arquivo original. O que muda e a",
        "! camada de carga, porque a interface do mercado escreve uma carga por",
        "! no. Ver o cabecalho do gerador para as decisoes de conversao.",
        "",
        "Clear",
        # Caminho relativo: o OpenDSS resolve a partir do diretorio do arquivo
        # compilado, e os dois ficam na mesma pasta. Absoluto quebraria quando a
        # pasta e montada em outro ponto dentro do container.
        f'Redirect {BASE_DSS.name}',
        "",
        "! As cargas oficiais saem de cena; quem representa a demanda agora e o",
        "! `Load_{no}`, que o agente escreve a cada intervalo.",
        "Batchedit Load..* enabled=no",
        "! O PV entra como carga negativa, pelo pv_kw.csv.",
        "Batchedit PVSystem..* enabled=no",
        "",
    ]
    for n in PROSUMIDORES:
        itens = cargas_por_no.get(n, [])
        if itens:
            ref = itens[0][1]
            bus, fases, conn, kv = ref["bus1"], ref["phases"], ref["conn"], ref["kv"]
            if len(itens) > 1:      # 634, 670 e 675: tres cargas monofasicas
                bus = f"{n}.1.2.3"
                fases, conn = 3, "wye"
                kv = round(barras[str(n)]["kv_base"] * math.sqrt(3), 4)
            total = sum(c["kw"] for _, c in itens)
        else:                        # 632: so tem geracao
            bus, fases, conn = f"{n}.1.2.3", 3, "wye"
            kv = round(barras[str(n)]["kv_base"] * math.sqrt(3), 4)
            total = 0.0
        linhas.append(
            f"New Load.Load_{n} bus1={bus} phases={fases} conn={conn} model=1 "
            f"kV={kv} kW={total:.3f} kvar={total * math.tan(math.acos(0.9)):.3f} "
            f"Vminpu=0.8 Vmaxpu=1.2")

    linhas += [
        "",
        "! Regulador com o ajuste oficial (vreg=122, banda 2 V, PT 20, CT 700,",
        "! R=3, X=9) e derivacoes LIVRES. Ver ESTUDO_IEEE13.md: congelar as",
        "! derivacoes em qualquer valor faz a rede violar por conta do",
        "! regulador, e nao da carga ou da geracao.",
        "Batchedit RegControl..* maxtapchange=16",
        "Set ControlMode=static",
        "Set MaxControlIter=100",
        "",
        "Set mode=snap",
        "Set number=1",
        "Solve",
    ]
    (DATA / "Master.dss").write_text("\n".join(linhas) + "\n")


def escrever_config(carga):
    def armaz(potencia):
        tamanho = potencia * HORAS_DE_ARMAZENAMENTO
        return {"size": round(tamanho, 1),
                "max_energy_flow": round(potencia, 1),
                "min_soc": round(SOC_MIN * tamanho, 1),
                "max_soc": round(SOC_MAX * tamanho, 1)}

    cfg = {
        "qtd_nodes_mv": len([n for n in PROSUMIDORES if n != 634]),
        "max_demand_kva": 5000,
        "devices": {
            "user_action_device": {"params": {
                str(n): {"size": round(float(carga[n].max()), 3)} for n in PROSUMIDORES}},
            "stochastic_gen": {"params": {
                str(n): {"size": float(PV_POR_NO[n][1])} for n in sorted(PV_POR_NO)}},
            "storage_device": {"params": {
                str(n): armaz(p) for n, p in sorted(ARMAZ_PROSUMIDOR.items())}},
            "dso_storage_device": {"params": {
                str(n): armaz(p) for n, p in sorted(ARMAZ_REDE.items())}},
        },
        "nodes_lv": list(PROSUMIDORES),
        "nodes_mv": [0, 633, 680, 684],
    }
    (DATA / "config.json").write_text(json.dumps(cfg, indent=1) + "\n")


def escrever_pool(carga, pv):
    """Reservatorio de dias alternativos para o modelo estocastico.

    A IEEE 13 tem UMA curva de carga e UM dia de irradiancia. Nao ha base de
    dados de onde recortar dias diferentes, como o SimBench da MVLV75. Os nove
    dias aqui sao construidos a partir do dia base com um fator multiplicativo
    por dia e um deslocamento temporal, semente fixa. Sao variabilidade
    SINTETICA, e nao dias medidos: servem para exercitar o modelo estocastico,
    nao para afirmar nada sobre incerteza real nesta rede.
    """
    rng = np.random.default_rng(13)
    nos = sorted(carga)
    # A serie de preco spot e a mesma da MVLV75 (Nordpool, recortada pelo
    # `data_prep`), para que a economia dos dois casos seja comparavel. O pacote
    # do mercado nao esta sempre montado no mesmo lugar, entao procura-se.
    candidatos = [p / "market-opentes" / "data" / "spot_price.csv"
                  for p in (DATA.parents[2], DATA.parents[3], Path("/app/simulators"),
                            Path(__file__).resolve().parents[3])]
    fonte = next((c for c in candidatos if c.exists()), None)
    if fonte is None:
        raise SystemExit("spot_price.csv do market-opentes nao encontrado em "
                         + ", ".join(str(c) for c in candidatos))
    preco = np.genfromtxt(fonte, delimiter=",", skip_header=1)[:PERIODS]
    L, P, PR = [], [], []
    for d in range(9):
        fator_c = 1.0 + rng.normal(0, 0.10)
        fator_p = 1.0 + rng.normal(0, 0.15)
        desloc = int(rng.integers(-2, 3))
        L.append(np.array([np.roll(carga[n], desloc) * fator_c for n in nos]))
        P.append(np.array([np.roll(pv[n], desloc) * max(fator_p, 0.0) for n in nos]))
        PR.append(preco * (1.0 + rng.normal(0, 0.08)))
    np.savez(DATA / "scenario_pool.npz", nodes=np.array(nos),
             load=np.array(L), pv=np.array(P), price=np.array(PR))
    np.savetxt(DATA / "spot_price.csv", preco, header="price", comments="", fmt="%.4f")


# ---------------------------------------------------------------------------
# Topologia de radio, para a figura de PER por distancia
# ---------------------------------------------------------------------------
# A tese publica a topologia 6TiSCH da MVLV75 (Apendices B e C). Para a IEEE 13
# nao existe topologia publicada, entao ela e CONSTRUIDA aqui, e isso precisa
# ficar dito em qualquer figura que saia dela.
#
# As coordenadas do `IEEE13Node_BusXY.csv` sao de desenho, nao de escala: entre
# 650 e 632 sao 100 unidades para 2000 pes, e entre 632 e 645 sao 100 unidades
# para 500 pes. Usa-las como metros daria distancias erradas por um fator de
# quatro. Aqui as DIRECOES vem do desenho e os COMPRIMENTOS vem do `length` real
# de cada linha, entao a geometria resultante respeita o alimentador.
FREQ_HZ = 915e6
TX_DBM, TX_GAIN, RX_GAIN = 0.0, 0.0, 0.0
SHIFT_DB = 40.0
SENSIBILIDADE_DBM = -106.37
LIMIAR_PER = 0.5
# Tabela 7 da tese: PER em funcao do RSSI acima do nivel de sensibilidade.
PER_TABELA = [1.0, 0.8, 0.4, 0.15, 0.03, 0.006, 0.0015, 0.0]
PES_PARA_M = 0.3048


def _per_do_rssi(rssi):
    acima = rssi - SENSIBILIDADE_DBM
    if acima <= 0:
        return 1.0
    i = int(acima)
    if i >= len(PER_TABELA) - 1:
        return PER_TABELA[-1]
    f = acima - i
    return PER_TABELA[i] * (1 - f) + PER_TABELA[i + 1] * f


def posicoes_em_metros(linhas):
    """Coordenadas por barra, com direcao do desenho e comprimento real."""
    esquema = {}
    for linha in (DATA / "IEEE13Node_BusXY.csv").read_text().splitlines():
        if not linha.strip():
            continue
        nome, x, y = [c.strip() for c in linha.split(",")]
        esquema[nome.lower()] = np.array([float(x), float(y)])

    ligacoes = {}
    for l in linhas:
        a, b = l["bus1"].split(".")[0].lower(), l["bus2"].split(".")[0].lower()
        ligacoes.setdefault(a, []).append((b, l["length"] * PES_PARA_M))
        ligacoes.setdefault(b, []).append((a, l["length"] * PES_PARA_M))
    # o regulador e o transformador nao sao linha, mas ligam barras
    for a, b in (("650", "rg60"), ("rg60", "632"), ("633", "634"),
                 ("671", "692"), ("sourcebus", "650")):
        ligacoes.setdefault(a, []).append((b, 0.0))
        ligacoes.setdefault(b, []).append((a, 0.0))

    pos = {"sourcebus": np.array([0.0, 0.0])}
    fila = ["sourcebus"]
    while fila:
        atual = fila.pop(0)
        for vizinho, comprimento in ligacoes.get(atual, []):
            if vizinho in pos or vizinho not in esquema:
                continue
            direcao = esquema[vizinho] - esquema.get(atual, esquema[vizinho])
            norma = float(np.hypot(*direcao))
            if norma < 1e-9:
                direcao, norma = np.array([1.0, 0.0]), 1.0
            pos[vizinho] = pos[atual] + direcao / norma * max(comprimento, 1.0)
            fila.append(vizinho)
    return pos


def escrever_tisch(linhas, semente=13):
    rng = np.random.default_rng(semente)
    pos = posicoes_em_metros(linhas)
    nomes = sorted(pos)
    saida = ["i,j,name_i,name_j,distance_m,rssi_dbm,per,adjacent"]
    viaveis = 0
    for i in range(len(nomes)):
        for j in range(i + 1, len(nomes)):
            d = float(np.hypot(*(pos[nomes[i]] - pos[nomes[j]])))
            if d < 1e-9:
                rssi, per = 0.0, 0.0
            else:
                fspl = 20.0 * math.log10(3e8 / (4.0 * math.pi * d * FREQ_HZ))
                rssi = TX_DBM + TX_GAIN + RX_GAIN + fspl - rng.uniform(0.0, SHIFT_DB)
                per = _per_do_rssi(rssi)
            ok = per < LIMIAR_PER
            viaveis += ok
            saida.append(f"{i},{j},{nomes[i]},{nomes[j]},{d:.4f},{rssi:.4f},"
                         f"{per:.6f},{1 if ok else 0}")
    (DATA / "tisch_links.csv").write_text("\n".join(saida) + "\n")

    # O arquivo de posicoes e indexado pelos NOS DO MERCADO, e nao pelos nomes
    # de barra do OpenDSS, porque e por eles que o `node_map_from_case` procura:
    # `prosumer671` vira "671", o concentrador vira o no de media tensao dele
    # (aqui o 0, a subestacao) e o AD e o AM viram "DSO" e "Market". Um nome que
    # o servidor nao acha e entregue SEM ATRASO, sem aviso nenhum, entao errar
    # aqui produz uma co-simulacao que roda e mede uma rede que nao existe.
    linhas_xy = ["node,x_m,y_m"]
    for n in nomes:
        linhas_xy.append(f"{_no(n)},{pos[n][0]:.2f},{pos[n][1]:.2f}")
    # O AD e o AM ficam na subestacao, como no Apendice B da tese, onde os dois
    # dividem a coordenada (0,0).
    sub = pos[SUBESTACAO]
    linhas_xy.append(f"DSO,{sub[0]:.2f},{sub[1]:.2f}")
    linhas_xy.append(f"Market,{sub[0]:.2f},{sub[1]:.2f}")
    (DATA / "nodes_xy.csv").write_text("\n".join(linhas_xy) + "\n")
    return len(nomes) + 2, viaveis


def main():
    barras, linhas, cargas, formas = ler_circuito()
    force = montar_force(barras, linhas, cargas)
    (DATA / "force.json").write_text(json.dumps(force, indent=1) + "\n")

    carga, pv = perfis(cargas, formas)
    escrever_csv(DATA / "load_kw.csv", carga)
    escrever_csv(DATA / "pv_kw.csv", pv)
    escrever_master(barras, cargas)
    escrever_config(carga)
    escrever_pool(carga, pv)
    n_radio, viaveis = escrever_tisch(linhas)

    liquida = sum(carga.values()) - sum(pv.values())
    print(f"{len(force['nodes'])} nos, {len(PROSUMIDORES)} prosumidores, "
          f"1 concentrador (alimentador de 5 MVA)")
    print(f"carga  pico {sum(carga.values()).max():7.1f} kW   "
          f"minima {sum(carga.values()).min():7.1f} kW")
    print(f"PV     pico {sum(pv.values()).max():7.1f} kW")
    print(f"liquida  de {liquida.min():7.1f} a {liquida.max():7.1f} kW")
    print(f"armazenamento  rede {sum(ARMAZ_REDE.values()):.0f} kW   "
          f"prosumidor {sum(ARMAZ_PROSUMIDOR.values()):.0f} kW")
    print(f"radio 6TiSCH construido: {n_radio} posicoes, {viaveis} enlaces viaveis")


if __name__ == "__main__":
    main()
