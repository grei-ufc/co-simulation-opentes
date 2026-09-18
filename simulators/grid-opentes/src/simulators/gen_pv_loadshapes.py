"""Gera ieee13_shape_pv_5min.dss (Loadshapes de irradiância + Tshapes de
temperatura) a partir dos CSVs ieee13_shape_pv_5min.csv e
ieee13_temperature_5min.csv.

Motivo: o pv_creator.py gera os CSVs e o ieee13_pv.dss (que referencia
``Daily=my_shapeN_irrad`` e ``TDaily=my_shapeN_temperature``), mas NÃO gera as
loadshapes correspondentes. Sem elas, o OpenDSS não cria os PVSystems
(``get_detected_pvsystems()`` retorna vazio). Este script fecha essa lacuna a
partir dos próprios dados já existentes.

Uso (dentro do container grid, com o volume src montado):

    python src/simulators/gen_pv_loadshapes.py
"""

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "13Bus"
IRRAD_CSV = DATA_DIR / "ieee13_shape_pv_5min.csv"
TEMP_CSV = DATA_DIR / "ieee13_temperature_5min.csv"
OUTPUT_DSS = DATA_DIR / "ieee13_shape_pv_5min.dss"

INTERVAL_MIN = 5


def _fmt(values):
    return ", ".join(f"{v:.6f}" for v in values)


def main():
    irrad = pd.read_csv(IRRAD_CSV)
    temp = pd.read_csv(TEMP_CSV)

    lines = [
        "! Loadshapes (irradiancia) e Tshapes (temperatura) geradas a partir de",
        "! ieee13_shape_pv_5min.csv e ieee13_temperature_5min.csv.",
        "! Necessarias para o ieee13_pv.dss referenciar Daily/TDaily dos PVSystems.",
        "",
    ]

    for col in irrad.columns:
        if col.strip().lower() in ("index", "time", "timestamp", "date", ""):
            continue
        vals = irrad[col].tolist()
        lines.append(
            f"New Loadshape.{col} npts={len(vals)} minterval={INTERVAL_MIN} mult=({_fmt(vals)})"
        )

    for col in temp.columns:
        if col.strip().lower() in ("index", "time", "timestamp", "date", ""):
            continue
        vals = temp[col].tolist()
        lines.append(
            f"New Tshape.{col} npts={len(vals)} minterval={INTERVAL_MIN} temp=({_fmt(vals)})"
        )

    OUTPUT_DSS.write_text("\n".join(lines) + "\n")
    n_loadshapes = sum(1 for l in lines if l.startswith("New Loadshape"))
    n_tshapes = sum(1 for l in lines if l.startswith("New Tshape"))
    print(f"Gerado {OUTPUT_DSS} ({n_loadshapes} Loadshapes + {n_tshapes} Tshapes)")


if __name__ == "__main__":
    main()
