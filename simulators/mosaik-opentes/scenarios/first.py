"""Cenario integrado OpenTES — evolucao causal do first.py (Volt/Var no inversor).

O first.py original ja unia os 3 simuladores isolados do TSCC:
    PADE (agentes)  <->  OMNeT++ (rede)  <->  Mosaik (orquestrador) + Collector

Aqui ele e ADAPTADO (nao reescrito do zero) para fechar o laco com a rede
eletrica do TSRE (OpenDSS / IEEE 13 Barras). NAO ha bateria: o atuador e o
proprio inversor fotovoltaico, com controle Volt/Var:

  [OpenDSS] --(tensao)--> AgenteA(medidor) --> OMNeT++ --(atraso/perda)-->
  AgenteB(controlador Volt/Var) --(P ativa, Q reativa)--> PVSystem --> [OpenDSS]
                                                                            |
                                                              (proximo passo, loop fecha)

  - P (ativa)   = potencia solar disponivel (cadeia irradiancia -> PV panel)
  - Q (reativa) = funcao da tensao recebida pela rede (regula a tensao)
  - S = sqrt(P^2 + Q^2) <= kVA do inversor

Toda a tensao passa pela camada de comunicacao (OMNeT++); latencia/jitter/perda
sao contabilizados no benchmark. O controle liga/desliga por CONTROL_ENABLED,
permitindo comparar a co-simulacao SEM controle (baseline) e COM controle.

Saidas em /app/output/integrated/ (sufixadas por RESULT_TAG):
  - result_<tag>.csv     : trajetorias eletricas (V, P_ref, Q_ref, P_meas, ...)
  - comm_trace_<tag>.csv : rastro das mensagens via OMNeT++ (telemetria de rede)
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mosaik


PADE_HOST = os.environ.get('PADE_HOST', 'pade-integrated')
PADE_PORT = os.environ.get('PADE_PORT', '5678')

CONTAINER_DATA = "/app/src/data/13Bus"
CIRCUITO_DSS = f"{CONTAINER_DATA}/run_ieee13_cosim_pv_5min.dss"
IRRADIANCE = f"{CONTAINER_DATA}/{os.environ.get('MOSAIK_IRRADIANCE_FILE', 'ieee13_shape_pv_5min.csv')}"
TEMPERATURE = f"{CONTAINER_DATA}/{os.environ.get('MOSAIK_TEMPERATURE_FILE', 'ieee13_temperature_5min.csv')}"

OUTPUT_DIR = Path(os.environ.get("MOSAIK_OUTPUT_DIR", "/app/output/integrated"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
RESULT_TAG = os.environ.get("RESULT_TAG", "volt_var")
RESULT_CSV = str(OUTPUT_DIR / f"result_{RESULT_TAG}.csv")
COMM_CSV = str(OUTPUT_DIR / f"comm_trace_{RESULT_TAG}.csv")

START_DATE = os.environ.get("MOSAIK_START_DATE", "2026-01-01 00:00:00")
STEP_SIZE = int(os.environ.get("MOSAIK_STEP_SIZE", "300"))   # 5 min
N_PASSOS = int(os.environ.get("MOSAIK_N_PASSOS", "288"))
END_TIME = N_PASSOS * STEP_SIZE

# 1 = Volt/Var ativo | 0 = baseline (inversor injeta so a solar, Q=0)
CONTROL_ENABLED = os.environ.get("CONTROL_ENABLED", "1")
# Ganho do Volt/Var: fracao do kVA disponivel como reativo maximo, e faixa morta.
# Com varios inversores + atraso de rede, ganho alto desestabiliza; manter suave.
Q_MAX_PCT = float(os.environ.get("Q_MAX_PCT", "0.05"))
V_DEADBAND = float(os.environ.get("V_DEADBAND", "0.02"))


sim_config = {
    # --- comunicacao (do first.py original) ---
    'OmnetSim':      {'python': 'omnet_wrapper:OmnetAdapter'},
    'ColetorSim':    {'python': 'collectors.comm_collector:Coletor'},
    'PadeSim':       {'connect': f'{PADE_HOST}:{PADE_PORT}'},
    # --- rede eletrica (TSRE) ---
    'DSS':           {'connect': f"{os.environ.get('OPENDSS_HOST', 'opendss')}:5671"},
    'PVSimulator':   {'connect': f"{os.environ.get('PV_HOST', 'pv-panel')}:5678"},
    'CSV_Irr':       {'connect': f"{os.environ.get('CSV_IRR_HOST', 'csv-data-1')}:5675"},
    'CSV_Temp':      {'connect': f"{os.environ.get('CSV_TEMP_HOST', 'csv-data-2')}:5676"},
    'ElecCollector': {'connect': f"{os.environ.get('ELEC_COLLECTOR_HOST', 'elec-collector')}:5673"},
}


def create_scenario(world):
    modo = "COM controle (Volt/Var)" if CONTROL_ENABLED == "1" else "SEM controle (baseline)"
    print(f"🌍 Cenario causal {modo}: OpenDSS <-> OMNeT++ <-> PADE...")

    dss_sim = world.start('DSS', topofile=CIRCUITO_DSS, step_size=STEP_SIZE)
    pv_sim = world.start('PVSimulator', step_size=STEP_SIZE)
    csv_irr = world.start('CSV_Irr', sim_start=START_DATE, datafile=IRRADIANCE)
    csv_temp = world.start('CSV_Temp', sim_start=START_DATE, datafile=TEMPERATURE)
    elec_collector = world.start('ElecCollector', start_date=START_DATE,
                                 output_file=RESULT_CSV, print_results=False)
    pade_sim = world.start('PadeSim')
    omnet_sim = world.start('OmnetSim', step_size=STEP_SIZE)
    coletor_sim = world.start('ColetorSim', output_file=COMM_CSV)

    grid = dss_sim.Grid()
    pv_info = dss_sim.get_detected_pvsystems()
    pvs_map = {e.eid: e for e in grid.children if e.type == 'PVSystem'}
    buses_map = {e.eid.lower(): e for e in grid.children if e.type == 'Bus'}

    # entidades de comunicacao e registro (compartilhadas pelos N PVs)
    rede_omnet = omnet_sim.NetworkNode(node_type='NetworkNode')
    comm_monitor = coletor_sim.Monitor()
    elec_monitor = elec_collector.Monitor()
    irr = csv_irr.Data.create(1)[0]
    tmp = csv_temp.Data.create(1)[0]

    # ==========================================================
    # Um par medidor/controlador por PV — TODOS co-simulados e (opcionalmente)
    # sob Volt/Var. A tensao de cada barra trafega pelo OMNeT++ ate o seu agente.
    # ==========================================================
    n_ctrl = 0
    for info in pv_info:
        n = ''.join(filter(str.isdigit, info['name']))      # '1'..'5'
        pv_dss = pvs_map.get(info['eid_dss'])
        bus_name = info.get('bus', '').split('.')[0]
        bus = buses_map.get(f'bus-{bus_name}')
        if pv_dss is None or bus is None:
            print(f"   [aviso] PV {info['name']} / Bus {bus_name} nao encontrado — pulando")
            continue

        # painel PV (irradiancia/temperatura -> P_dc disponivel)
        panel = pv_sim.PVPanel.create(
            1, P_mpp=info['pmpp'], irradiance_base=0.8,
            pt_curve_x=info['pt_curve_x'], pt_curve_y=info['pt_curve_y'])[0]
        world.connect(irr, panel, (f'my_shape{n}_irrad', 'irradiance'))
        world.connect(tmp, panel, (f'my_shape{n}_temperature', 'temperature'))

        medidor = pade_sim.PadeAgent(agent_id=f'AgenteA_{n}', bus=bus_name)
        ctrl = pade_sim.PadeAgent(
            agent_id=f'AgenteB_{n}', bus=bus_name,
            control_enabled=CONTROL_ENABLED, kva=info['kva'],
            v_ref=1.0, v_deadband=V_DEADBAND, v_min=0.95, v_max=1.05,
            q_max_pct=Q_MAX_PCT)

        # PONTE 1 (observacao): Bus -> medidor (time_shifted; reporta o ultimo
        # estado resolvido e quebra o ciclo DSS->PADE->PVSystem->DSS)
        world.connect(bus, medidor, ('V1_pu', 'V_in'), ('V2_pu', 'V_in'), ('V3_pu', 'V_in'),
                      time_shifted=True,
                      initial_data={'V1_pu': 1.0, 'V2_pu': 1.0, 'V3_pu': 1.0})
        # comunicacao: medidor -> OMNeT++ -> controlador (mensagem marcada com a barra)
        world.connect(medidor, rede_omnet, ('val_out', 'val_in'))
        world.connect(rede_omnet, ctrl, ('val_out', 'val_in'),
                      time_shifted=True, initial_data={'val_out': ''})
        # solar disponivel (P) chega localmente ao controlador
        world.connect(panel, ctrl, ('P_dc', 'P_avail_in'))
        # PONTE 2 (atuacao): controlador -> inversor PVSystem -> OpenDSS
        world.connect(ctrl, pv_dss, ('P_ref', 'P_des'), ('Q_ref', 'Q_des'))

        # registro do PV
        world.connect(panel, elec_monitor, 'P_dc')
        world.connect(ctrl, elec_monitor, 'P_ref', 'Q_ref')
        n_ctrl += 1

    print(f"   co-simulando {n_ctrl} PVs (controle Volt/Var por barra: "
          f"{'ON' if CONTROL_ENABLED == '1' else 'OFF/baseline'})")

    # ==========================================================
    # REGISTRO: telemetria da rede + tensao de TODAS as barras + potencia dos PVs
    # ==========================================================
    world.connect(rede_omnet, comm_monitor,
                  'status', 'packets_sent', 'packets_received', 'packets_dropped',
                  'packet_sizes_out', 'latencies_out', 'jitters_out', 'val_out')
    for e in grid.children:
        if e.type == 'Bus':
            world.connect(e, elec_monitor, 'V1_pu', 'V2_pu', 'V3_pu')
        elif e.type == 'PVSystem':
            world.connect(e, elec_monitor, 'P_meas', 'Q_meas')


if __name__ == '__main__':
    print("🎬 Iniciando o Orquestrador Mosaik (cenario integrado causal Volt/Var)...")
    with mosaik.World(sim_config) as world:
        create_scenario(world)
        world.run(until=END_TIME, print_progress=False)
    print("✅ Co-simulacao finalizada.")
    print(f"   eletrico:    {RESULT_CSV}")
    print(f"   comunicacao: {COMM_CSV}")
