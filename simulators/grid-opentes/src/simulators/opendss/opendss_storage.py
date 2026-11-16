"""Storage element operations on the OpenDSS circuit.

Standalone functions that receive an active ``py_dss_interface.DSS`` instance
and encapsulate reading of static battery parameters.
"""

from __future__ import annotations

from typing import Any


def get_all_storages_info(dss: Any) -> dict[str, dict[str, Any]]:
    """Return static data for every Storage element in the circuit.

    Args:
        dss: Active ``py_dss_interface.DSS`` instance.

    Returns:
        Dictionary mapping Storage names to parameter dictionaries.
    """
    storage_infos: dict[str, dict[str, Any]] = {}

    dss.circuit.set_active_class("Storage")
    if dss.active_class.count == 0:
        return storage_infos

    names = dss.active_class.names
    if not names or names[0] is None or str(names[0]).lower() == "none":
        return storage_infos

    for full_name in names:
        name = full_name.split(".")[-1] if "." in full_name else full_name

        dss.circuit.set_active_element(f"Storage.{name}")
        bus = dss.cktelement.bus_names[0]
        num_phases = dss.cktelement.num_phases

        kw_rated = float(dss.text(f"? Storage.{name}.kWrated"))
        kwh_rated = float(dss.text(f"? Storage.{name}.kWhrated"))
        kwh_stored = float(dss.text(f"? Storage.{name}.kWhstored"))
        pct_reserve = float(dss.text(f"? Storage.{name}.%reserve"))
        eff_charge = float(dss.text(f"? Storage.{name}.%EffCharge"))
        eff_discharge = float(dss.text(f"? Storage.{name}.%EffDischarge"))
        pct_idling = float(dss.text(f"? Storage.{name}.%IdlingkW"))
        daily = dss.text(f"? Storage.{name}.daily")
        charge_trigger = float(dss.text(f"? Storage.{name}.chargeTrigger"))
        discharge_trigger = float(dss.text(f"? Storage.{name}.dischargeTrigger"))

        # Base da reativa quando a bateria e movida por multiplicador:
        # com P = mult x kWrated, a reativa vale P x tan(acos(pf)).
        pf = float(dss.text(f"? Storage.{name}.pf") or 1.0)
        # Teto da reativa. O padrao do OpenDSS nao acompanha o tamanho da
        # bateria (uma de 200 kW sai com 25 kvar), e o excedente e cortado.
        kvar_max = float(dss.text(f"? Storage.{name}.kvarMax") or 0.0)

        storage_infos[name] = {
            "name": name,
            "bus": bus,
            "num_phases": num_phases,
            "kw_rated": kw_rated,
            "pf": pf,
            "kvar_max": kvar_max,
            "kwh_rated": kwh_rated,
            "kwh_stored": kwh_stored,
            "pct_reserve": pct_reserve,
            "eff_charge": eff_charge,
            "eff_discharge": eff_discharge,
            "pct_idling": pct_idling,
            "daily": daily,
            "charge_trigger": charge_trigger,
            "discharge_trigger": discharge_trigger,
        }

    return storage_infos
