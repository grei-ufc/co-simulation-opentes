"""PVSystem operations on the OpenDSS circuit.

Standalone functions that receive an active ``py_dss_interface.DSS`` instance
and encapsulate parameter reading, XY-curve lookups, PQ control, and
measurements.
"""

from __future__ import annotations

import copy
from typing import Any

# Curvas planas, de fator 1 em toda a faixa, e limiar de corte (em % do kVA)
# que o carregamento do circuito poe no lugar dos declarados. Ver
# idealize_pvsystems.
IDEAL_EFF_CURVE = "EffIdeal_Cosim"
IDEAL_PT_CURVE = "PTIdeal_Cosim"
IDEAL_CUT_PCT = 0.0001


def idealize_pvsystems(dss: Any) -> dict[str, dict[str, Any]]:
    """Troca a conversão DC/AC nativa de todo PVSystem por uma ideal.

    A potência de um PVSystem chega ao motor já calculada — pelo inversor
    modelado em outro simulador, ou pela curva de multiplicadores — e entra
    como ``pmpp`` com ``irradiance=1`` (ver :func:`set_pvsystem_pq`). O modelo
    nativo ainda a multiplicaria pela ``EffCurve`` e pela ``P-TCurve``, e
    desligaria o inversor abaixo do ``%cutin``, que por padrão é 20 % do kVA:
    a injeção sairia menor que a comandada, e zerada nas pontas do dia, sem
    nada avisando.

    Cada PVSystem passa a usar duas curvas planas e limiares de corte
    praticamente nulos, de modo que a potência escrita é a que sai.

    Args:
        dss: Active ``py_dss_interface.DSS`` instance.

    Returns:
        O modelo de conversão que o circuito declarava, por PVSystem, lido
        antes da troca: ``pct_cutin``, ``pct_cutout``, ``pt_curve_x``/``_y`` e
        ``eff_curve_x``/``_y``. É o que um simulador de inversor precisa para
        aplicar essas perdas do lado dele.
    """
    names = _pvsystem_names(dss)
    declared = {name: _read_conversion_model(dss, name) for name in names}
    if not names:
        return declared

    dss.text(f"New XYCurve.{IDEAL_EFF_CURVE} npts=2 xarray=[0.0 1.0] yarray=[1.0 1.0]")
    dss.text(f"New XYCurve.{IDEAL_PT_CURVE} npts=2 xarray=[0.0 100.0] yarray=[1.0 1.0]")

    for name in names:
        dss.text(
            f"Edit PVSystem.{name} %cutin={IDEAL_CUT_PCT} %cutout={IDEAL_CUT_PCT} "
            f"EffCurve={IDEAL_EFF_CURVE} P-TCurve={IDEAL_PT_CURVE}"
        )

    return declared


def get_all_pvsystems_info(
    dss: Any, declared: dict[str, dict[str, Any]] | None = None
) -> dict[str, dict[str, Any]]:
    """Return static data and curves for every PVSystem in the circuit.

    Automatically reads the attached XYCurves (``P-TCurve``, ``EffCurve``)
    for each inverter.

    Args:
        dss: Active ``py_dss_interface.DSS`` instance.
        declared: Modelo de conversão declarado no circuito, por PVSystem, como
            devolvido por :func:`idealize_pvsystems`. Os PVSystems listados
            nele reportam essas curvas e limiares, e não os ideais que o motor
            usa de fato; os demais são lidos do motor.

    Returns:
        Dictionary mapping PVSystem names to parameter dictionaries.
    """
    pv_infos: dict[str, dict[str, Any]] = {}
    declared = declared or {}

    for name in _pvsystem_names(dss):
        dss.pvsystems.name = name

        pmpp = dss.pvsystems.pmpp
        kva = dss.pvsystems.kva
        irradiance = dss.pvsystems.irradiance
        daily = dss.text(f"? PVSystem.{name}.daily")

        bus_name = dss.cktelement.bus_names[0]
        num_phases = dss.cktelement.num_phases

        # Tensao nominal do elemento: linha-linha se trifasico, linha-neutro se
        # monofasico. E a base de v_pu para as curvas volt-var e volt-watt do
        # inversor, entao precisa acompanhar o PVSystem e nao a barra.
        kv = _as_float(dss.text(f"? PVSystem.{name}.kV"))

        # Base da reativa quando o PV e movido por multiplicador: com
        # P = mult x pmpp, a reativa vale P x tan(acos(pf)). Ver write_pvsystem.
        pf = _as_float(dss.text(f"? PVSystem.{name}.pf"), 1.0)

        if name in declared:
            conversion = copy.deepcopy(declared[name])
        else:
            conversion = _read_conversion_model(dss, name)

        pv_infos[name] = {
            "pmpp": pmpp,
            "kva": kva,
            "kv": kv,
            "pf": pf,
            "irradiance": irradiance,
            "daily": daily,
            **conversion,
            "bus": bus_name,
            "num_phases": num_phases,
        }

    return pv_infos


def set_pvsystem_pq(dss: Any, name: str, p_des: float, q_des: float) -> None:
    """Force active and reactive power values on a PVSystem, bypassing curves.

    Args:
        dss: Active ``py_dss_interface.DSS`` instance.
        name: PVSystem name (without the ``PVSystem.`` prefix).
        p_des: Desired active power (kW, signed for injection).
        q_des: Desired reactive power (kvar).
    """
    dss.circuit.set_active_element(f"PVSystem.{name}")
    p_abs = abs(p_des)

    if p_abs > 0.001:
        cmd = f"Edit PVSystem.{name} pmpp={p_abs} irradiance=1.0 kvar={q_des}"
        dss.text(cmd)
    else:
        cmd = f"Edit PVSystem.{name} irradiance=0.0 kvar={q_des}"
        dss.text(cmd)


def get_pvsystem_power(dss: Any, name: str) -> tuple[float, float]:
    """Read active and reactive power from a PVSystem.

    Args:
        dss: Active ``py_dss_interface.DSS`` instance.
        name: PVSystem name (without the ``PVSystem.`` prefix).

    Returns:
        Tuple ``(P_kW, Q_kvar)`` with inverted sign convention (injection).
    """
    dss.circuit.set_active_element(f"PVSystem.{name}")
    powers = dss.cktelement.powers
    p_meas = -sum(powers[0:6:2])
    q_meas = -sum(powers[1:6:2])
    return p_meas, q_meas


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _as_float(value: Any, default: float = 0.0) -> float:
    """Converte uma propriedade DSS (sempre string) para float, com fallback."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _pvsystem_names(dss: Any) -> list[str]:
    """Nomes dos PVSystems do circuito; vazio se não houver nenhum."""
    names = dss.pvsystems.names
    if not names or names[0].upper() == "NONE":
        return []
    return list(names)


def _read_conversion_model(dss: Any, name: str) -> dict[str, Any]:
    """Limiares de corte e curvas de eficiência e P-T de um PVSystem, como no motor."""
    cutin = float(dss.text(f"? PVSystem.{name}.%cutin"))
    cutout = float(dss.text(f"? PVSystem.{name}.%cutout"))

    pt_x, pt_y = _read_xy_curve(dss, dss.text(f"? PVSystem.{name}.P-TCurve"))
    eff_x, eff_y = _read_xy_curve(dss, dss.text(f"? PVSystem.{name}.EffCurve"))

    return {
        "pct_cutin": cutin,
        "pct_cutout": cutout,
        "pt_curve_x": pt_x,
        "pt_curve_y": pt_y,
        "eff_curve_x": eff_x,
        "eff_curve_y": eff_y,
    }


def _read_xy_curve(dss: Any, curve_name: str) -> tuple[list[float], list[float]]:
    """Read the X and Y arrays from an OpenDSS XYCurve.

    Args:
        dss: Active ``py_dss_interface.DSS`` instance.
        curve_name: Name of the XYCurve element.

    Returns:
        Tuple of ``(x_values, y_values)`` as lists of floats.
    """
    if not curve_name:
        return [], []
    dss.xycurves.name = curve_name
    x = list(dss.xycurves.x_array)
    y = list(dss.xycurves.y_array)
    return x, y
