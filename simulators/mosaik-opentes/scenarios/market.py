"""Cenario de mercado transativo: negociacao em PADE, rede em OpenDSS.

Fase de programacao da operacao (subsecao 6.1.2 da tese de Lucas S. Melo, 2022),
sobre a rede MVLV75 (75 barras, 5 transformadores, 68 prosumidores).

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

Comparacao: com CONTROL_ENABLED=0 os agentes publicam a programacao PROPOSTA
pelos prosumidores, sem negociacao, que e a linha de base.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import re

import mosaik

PADE_HOST = os.environ.get("PADE_HOST", "pade-market")
PADE_PORT = os.environ.get("PADE_PORT", "5678")
OPENDSS_HOST = os.environ.get("OPENDSS_HOST", "opendss")
ELEC_COLLECTOR_HOST = os.environ.get("ELEC_COLLECTOR_HOST", "elec-collector")

CIRCUITO_DSS = os.environ.get("MARKET_CIRCUIT", "/app/src/data/MVLV75/Master.dss")
OUTPUT_DIR = Path(os.environ.get("MOSAIK_OUTPUT_DIR", "/app/output/market"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
RESULT_TAG = os.environ.get("RESULT_TAG", "negociado")
RESULT_CSV = str(OUTPUT_DIR / f"result_{RESULT_TAG}.csv")

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
        # A demanda liquida REALIZADA por no tambem vai para o coletor: e a
        # grandeza da Figura 55 e das Tabelas 20 e 21 do Apendice A da tese, e
        # sem grava-la nao ha como confrontar no a no com elas. So a tensao ia.
        world.connect(agent, monitor, "P_kw")
        n_ligados += 1

    for bus in buses:
        world.connect(bus, monitor, "V1_pu", "V2_pu", "V3_pu")

    if not n_ligados:
        raise SystemExit(
            "nenhuma carga com o nome `Load_<no>` no circuito; o mercado nao "
            f"tem o que acionar. Cargas encontradas: {sorted(loads)[:8]}")
    print(f"   {n_ligados} nos acionados pelos agentes, "
          f"{len(buses)} barras registradas")
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
