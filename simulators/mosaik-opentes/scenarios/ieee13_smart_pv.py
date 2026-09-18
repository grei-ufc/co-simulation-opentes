"""Cenário Mosaik IEEE 13 Bus com Smart PV.

Adaptado do upstream `grei-ufc/tsre-der-opentes/src/scenarios/scenario_13bus_smart_pv_docker.py`
(commit 0e9f4fee4fc6, Paulo Victor, 2026-05-26) para a topologia OpenTES de 4
containers:

- O cenário roda dentro do container ``mosaik`` (e não no host).
- Hostnames vêm do Docker DNS (``opendss``, ``pv-panel``, ``smart-inverter``,
  ``csv-data-1``, ``csv-data-2``) em vez de ``localhost:porta``.
- O collector elétrico passou a viver no próprio container Mosaik
  (``collectors.elec_collector:Collector``), não como container remoto.
- O DSS e os CSVs são lidos do volume ``./simulators/grid-opentes/src``
  montado em ``/app/src`` dos containers remotos.
- O CSV de resultado é escrito em ``/app/output/...`` dentro do container
  ``mosaik`` (volume ``./output`` mapeado pelo compose).

Para rodar:

```bash
docker compose up -d opendss pv-panel smart-inverter csv-data-1 csv-data-2
MOSAIK_SCENARIO=scenarios/ieee13_smart_pv.py docker compose run --rm mosaik
```

ou via env var no compose (``mosaik.environment.MOSAIK_SCENARIO``).
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mosaik


# ------------------------------------------------------------------------------
# Paths dentro dos containers
# ------------------------------------------------------------------------------
CONTAINER_DATA = "/app/src/data/13Bus"
CIRCUITO_DSS = f"{CONTAINER_DATA}/run_ieee13_cosim_pv_5min.dss"
IRRADIANCE = f"{CONTAINER_DATA}/ieee13_shape_pv_5min.csv"
TEMPERATURE = f"{CONTAINER_DATA}/ieee13_temperature_5min.csv"
OUTPUT_DIR = Path(os.environ.get("MOSAIK_OUTPUT_DIR", "/app/output/ieee13"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
RESULT_CSV = str(OUTPUT_DIR / "result_run_ieee13_cosim_pv_5min.csv")

START_DATE = os.environ.get("MOSAIK_START_DATE", "2026-01-01 00:00:00")
STEP_SIZE = int(os.environ.get("MOSAIK_STEP_SIZE", "300"))  # 5 min
N_PASSOS = int(os.environ.get("MOSAIK_N_PASSOS", "288"))
END_TIME = N_PASSOS * STEP_SIZE


SIM_CONFIG = {
    "DSS": {"connect": f"{os.environ.get('OPENDSS_HOST', 'opendss')}:5671"},
    "PVSimulator": {"connect": f"{os.environ.get('PV_HOST', 'pv-panel')}:5678"},
    "InverterSim": {"connect": f"{os.environ.get('INVERTER_HOST', 'smart-inverter')}:5680"},
    "CSV_Irr": {"connect": f"{os.environ.get('CSV_IRR_HOST', 'csv-data-1')}:5675"},
    "CSV_Temp": {"connect": f"{os.environ.get('CSV_TEMP_HOST', 'csv-data-2')}:5676"},
    "Collector": {"connect": f"{os.environ.get('ELEC_COLLECTOR_HOST', 'elec-collector')}:5673"},
}


def run_scenario():
    with mosaik.World(SIM_CONFIG) as world:
        print("[mosaik] conectando aos simuladores remotos...")

        dss_sim = world.start("DSS", topofile=CIRCUITO_DSS, step_size=STEP_SIZE)
        pv_sim = world.start("PVSimulator", step_size=STEP_SIZE)
        inv_sim = world.start("InverterSim", step_size=STEP_SIZE)
        csv_sim_irr = world.start("CSV_Irr", sim_start=START_DATE, datafile=IRRADIANCE)
        csv_sim_temp = world.start("CSV_Temp", sim_start=START_DATE, datafile=TEMPERATURE)
        collector = world.start(
            "Collector",
            start_date=START_DATE,
            output_file=RESULT_CSV,
            print_results=False,
        )

        print("[mosaik] instanciando a grid OpenDSS...")
        grid = dss_sim.Grid()
        csv_data_irr = csv_sim_irr.Data.create(1)
        csv_data_temp = csv_sim_temp.Data.create(1)
        monitor = collector.Monitor()

        pv_info = dss_sim.get_detected_pvsystems()
        pvs_dss_map = {e.eid: e for e in grid.children if e.type == "PVSystem"}
        buses_map = {e.eid: e for e in grid.children if e.type == "Bus"}

        for info in pv_info:
            pv_name = info["name"]
            eid_dss = info["eid_dss"]
            bus_full = info.get("bus", "")
            bus_base = bus_full.split(".")[0]

            if eid_dss not in pvs_dss_map:
                continue
            pv_dss_obj = pvs_dss_map[eid_dss]

            bus_eid = f"Bus-{bus_base}"
            if bus_eid not in buses_map:
                print(f"[mosaik] aviso: barramento {bus_eid} não encontrado para realimentação")
                continue
            bus_obj = buses_map[bus_eid]

            pv_panel_obj = pv_sim.PVPanel.create(
                1,
                P_mpp=info["pmpp"],
                irradiance_base=0.8,
                pt_curve_x=info["pt_curve_x"],
                pt_curve_y=info["pt_curve_y"],
            )[0]

            inv_obj = inv_sim.Inverter.create(
                1,
                kVA=info["kva"],
                phase_mode="AVG",
                eff_curve_x=info["eff_curve_x"],
                eff_curve_y=info["eff_curve_y"],
                ctrl_config={"Volt_Var": False, "Const_PF": False},
            )[0]

            pv_number = "".join(filter(str.isdigit, pv_name))
            col_irrad = f"my_shape{pv_number}_irrad"
            col_temp = f"my_shape{pv_number}_temperature"
            world.connect(csv_data_irr[0], pv_panel_obj, (col_irrad, "irradiance"))
            world.connect(csv_data_temp[0], pv_panel_obj, (col_temp, "temperature"))
            world.connect(pv_panel_obj, inv_obj, ("P_dc", "P_dc"))

            world.connect(
                bus_obj,
                inv_obj,
                ("V1_pu", "V_meas_1"),
                ("V2_pu", "V_meas_2"),
                ("V3_pu", "V_meas_3"),
                time_shifted=True,
                initial_data={"V1_pu": 1.0, "V2_pu": 1.0, "V3_pu": 1.0},
            )

            world.connect(inv_obj, pv_dss_obj, ("P_ac", "P_des"), ("Q_ac", "Q_des"))

            world.connect(pv_panel_obj, monitor, "irradiance", "temperature", "P_dc")
            world.connect(inv_obj, monitor, "P_ac", "Q_ac")
            world.connect(pv_dss_obj, monitor, "P_meas", "Q_meas")
            world.connect(pv_dss_obj, monitor, "P1", "P2", "P3", "Q1", "Q2", "Q3")

        # Monitoramento de tensoes de barra (metrica-chave de coerencia do IEEE 13).
        for target_name in ("650", "632", "671", "680", "611"):
            target_eid = f"Bus-{target_name}"
            bus_entities = [e for e in grid.children if e.eid == target_eid]
            if bus_entities:
                world.connect(bus_entities[0], monitor, "V1_pu", "V2_pu", "V3_pu")
                print(f"[mosaik] monitorando barra {target_eid}")

        print(f"[mosaik] iniciando simulação ({N_PASSOS} passos, step={STEP_SIZE}s)")
        world.run(until=END_TIME, print_progress=False)
        print(f"[mosaik] simulação concluída. resultados em {RESULT_CSV}")


if __name__ == "__main__":
    run_scenario()
