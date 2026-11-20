"""Cenario de mercado transativo: negociacao em PADE, rede em OpenDSS.

Fase de programacao da operacao (Melo, 2022, secao 6.1.2) sobre a IEEE 13
barras: 10 prosumidores, um concentrador, 14 bancos de armazenamento.

    t = 0        o sistema multi-agentes negocia: os prosumidores propoem a
                 programacao do armazenamento, o DSO verifica as restricoes e o
                 agente de mercado itera o preco sombra ate as duas partes
                 concordarem. O passo do Mosaik fica ABERTO ate a rodada fechar.

    t = 0..24h   a programacao acordada e aplicada no OpenDSS em intervalos de
                 15 min, e as tensoes sao registradas com FLUXO DE POTENCIA
                 COMPLETO.

O segundo trecho e o que da valor ao primeiro: a negociacao decide com o modelo
LINEARIZADO (dV = S . dP), e aqui se verifica se a promessa se confirma na
solucao nao linear. Sem isso, o resultado da negociacao seria uma afirmacao
sobre o proprio modelo dela.

Comparacao: com MARKET_NEGOTIATE=0 os agentes publicam a programacao PROPOSTA
pelos prosumidores, sem negociacao, que e a linha de base.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import re

import mosaik

PADE_HOST = os.environ.get("PADE_HOST", "pade")
PADE_PORT = os.environ.get("PADE_PORT", "5678")
OPENDSS_HOST = os.environ.get("OPENDSS_HOST", "grid")
ELEC_COLLECTOR_HOST = os.environ.get("ELEC_COLLECTOR_HOST", "collector")

CIRCUITO_DSS = os.environ.get("MARKET_CIRCUIT", "/app/src/data/13Bus/Master.dss")
OUTPUT_DIR = Path(os.environ.get("MOSAIK_OUTPUT_DIR", "/app/output/market"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
RESULT_TAG = os.environ.get("RESULT_TAG", "negociado")
RESULT_CSV = str(OUTPUT_DIR / f"result_{RESULT_TAG}.csv")

# Analise por fase (MARKET_FASE=1): o armazenamento de cada fase vai para a carga
# monofasica `Port_<no>_<fase>` do circuito, e o Load_<no> leva so a demanda.
FASE = os.environ.get("MARKET_FASE", "0") == "1"
# Regulador: `previsao` aplica, a cada passo, as derivacoes do ponto de operacao da
# previsao, que o DSO usou para calcular a matriz de sensibilidade; `neutro` aplica
# a derivacao 0. O comando vai nos dois modos, porque sem ele o simulador OpenDSS
# deixa as derivacoes onde o circuito as resolveu ao compilar.
REGULADOR = os.environ.get("MARKET_REGULADOR", "previsao")

START_DATE = os.environ.get("MOSAIK_START_DATE", "2026-01-01 00:00:00")
STEP_SIZE = int(os.environ.get("MOSAIK_STEP_SIZE", "900"))      # 15 min
N_PASSOS = int(os.environ.get("MOSAIK_N_PASSOS", "96"))
END_TIME = N_PASSOS * STEP_SIZE

sim_config = {
    "PadeMarket": {"connect": f"{PADE_HOST}:{PADE_PORT}"},
    "DSS": {"connect": f"{OPENDSS_HOST}:5671"},
    "ElecCollector": {"connect": f"{ELEC_COLLECTOR_HOST}:5673"},
}


def create_scenario(world):
    dss_sim = world.start("DSS", topofile=CIRCUITO_DSS, step_size=STEP_SIZE)
    pade_sim = world.start("PadeMarket", step_size=STEP_SIZE)
    collector = world.start("ElecCollector", start_date=START_DATE,
                            output_file=RESULT_CSV, print_results=False)

    grid = dss_sim.Grid()
    monitor = collector.Monitor()

    loads = {e.eid: e for e in grid.children if e.type == "Load"}
    buses = [e for e in grid.children if e.type == "Bus"]

    # Um agente prosumidor por no de baixa tensao com armazenamento; os demais
    # nos tem a carga acionada pelo mesmo mecanismo, com armazenamento nulo.
    # So entram as cargas do MERCADO, que seguem a convencao `Load_<no>` usada
    # pelo resto da camada (`Edit Load.Load_{no}` no loading.py, no
    # sensitivity.py e no market_agents.py). Antes o laco pegava toda carga do
    # circuito e supunha que o nome terminasse em `_<numero>`, o que so vale
    # para as redes geradas aqui. Num circuito montado sobre uma rede publicada
    # convivem as duas: a IEEE 13 mantem as cargas oficiais (`671`, `634a`,
    # `675b`, ...) desabilitadas ao lado das do mercado, e o `int()` estourava
    # em `Load-671`.
    padrao = re.compile(r"^load-load_(\d+)$", re.IGNORECASE)
    n_ligados = 0
    ignoradas = []
    for eid, load in loads.items():
        m = padrao.match(eid)
        if m is None:
            ignoradas.append(eid)
            continue
        node = m.group(1)
        agent = pade_sim.MarketMAS(node=int(node))
        world.connect(agent, load, ("P_kw", "P_kw"), ("Q_kvar", "Q_kvar"))
        # A demanda liquida REALIZADA por no tambem vai para o coletor, ao lado
        # da tensao: e o que a figura de demanda da operacao mostra.
        world.connect(agent, monitor, "P_kw")
        n_ligados += 1

    n_portas = 0
    if FASE:
        porta_re = re.compile(r"^load-port_(\d+)_([123])$", re.IGNORECASE)
        for eid, load in loads.items():
            m = porta_re.match(eid)
            if m is None:
                continue
            agent = pade_sim.MarketMAS(node=int(m.group(1)), porta=int(m.group(2)))
            world.connect(agent, load, ("P_kw", "P_kw"), ("Q_kvar", "Q_kvar"))
            # Registrada tambem, para que a demanda liquida do no (carga mais
            # armazenamento) possa ser reconstituida somando as portas.
            world.connect(agent, monitor, "P_kw")
            n_portas += 1
        if not n_portas:
            raise SystemExit("MARKET_FASE=1, mas o circuito nao tem cargas "
                             "Port_<no>_<fase> (ver gen_ieee13_market.py)")
        ignoradas = [e for e in ignoradas if not porta_re.match(e)]

    n_reg = 0
    for reg in (e for e in grid.children if e.type == "RegControl"):
        agent = pade_sim.Regulador(nome=reg.eid.split("-", 1)[1])
        world.connect(agent, reg, ("tap", "tap"))
        n_reg += 1

    for bus in buses:
        world.connect(bus, monitor, "V1_pu", "V2_pu", "V3_pu")

    if not n_ligados:
        raise SystemExit(
            "nenhuma carga com o nome `Load_<no>` no circuito; o mercado nao "
            f"tem o que acionar. Cargas encontradas: {sorted(loads)[:8]}")
    print(f"   {n_ligados} nos acionados pelos agentes, "
          + (f"{n_portas} portas por fase, " if FASE else "")
          + (f"{n_reg} reguladores "
             f"{'pela previsao' if REGULADOR == 'previsao' else 'na derivacao 0'}, "
             if n_reg else "")
          + f"{len(buses)} barras registradas")
    if ignoradas:
        print(f"   {len(ignoradas)} cargas fora da convencao do mercado, "
              f"ignoradas: {sorted(ignoradas)[:6]}")


if __name__ == "__main__":
    print("Cenario de mercado transativo (PADE + OpenDSS)...")
    with mosaik.World(sim_config) as world:
        create_scenario(world)
        world.run(until=END_TIME, print_progress=False)
    print("Concluido.")
    print(f"   eletrico: {RESULT_CSV}")
