"""Voltage regulator operations on the OpenDSS circuit.

Standalone functions that receive an active ``py_dss_interface.DSS`` instance
and encapsulate regulator detection, parameter reading, and measurements.
"""

from __future__ import annotations

from typing import Any

from ._types import OpenDSSException


def freeze_regulators(dss: Any) -> None:
    """Trava o controle automático de todo RegControl, sem mexer no tap.

    Os taps só mudam por um controlador externo, pelo atributo ``tap`` do
    adaptador. ``MaxTapChange=0`` impede o laço de controle do OpenDSS de
    movê-los a cada solução, e a posição fica a que o ``.dss`` declara até um
    comando externo mudá-la.

    Até esta versão o travamento acontecia dentro de
    :func:`get_all_regulators_info`, que além disso zerava os taps: a primeira
    solução, no construtor, ainda saía com o controle nativo agindo, e um tap
    declarado no ``.dss`` era trocado pelo neutro.

    Args:
        dss: Active ``py_dss_interface.DSS`` instance.
    """
    if not dss.regcontrols.count:
        return

    for name in dss.regcontrols.names:
        dss.regcontrols.name = name
        dss.regcontrols.max_tap_change = 0


def get_all_regulators_info(dss: Any) -> list[dict[str, Any]]:
    """Detect every RegControl and return its static data.

    Includes topology information (Transformer, Winding, Bus, Phase). Só lê:
    não trava nem move os taps — isso é de :func:`freeze_regulators`, no
    carregamento do circuito.

    Args:
        dss: Active ``py_dss_interface.DSS`` instance.

    Returns:
        List of dictionaries, one per detected regulator. Empty if the circuit
        has no ``RegControl``. ``tap_ini`` é o tap no momento da leitura; na
        criação das entidades, o declarado no ``.dss``.
    """
    reg_list: list[dict[str, Any]] = []

    if not dss.regcontrols.count:
        return reg_list

    for name in dss.regcontrols.names:
        dss.regcontrols.name = name

        info: dict[str, Any] = {
            "name": name,
            "vreg": dss.regcontrols.forward_vreg,
            "band": dss.regcontrols.forward_band,
            "pt_ratio": dss.regcontrols.pt_ratio,
            "ct_primary": dss.regcontrols.ct_primary,
            "R": dss.regcontrols.forward_r,
            "X": dss.regcontrols.forward_x,
            "delay": dss.regcontrols.delay,
            "tap_delay": dss.regcontrols.tap_delay,
            "trafo": dss.regcontrols.transformer,
            "winding": dss.regcontrols.winding,
            "tap_ini": dss.regcontrols.tap_number,
        }

        # Resolve o barramento alvo a partir do transformer
        trafo_name = info["trafo"]
        winding_idx = info["winding"]
        dss.circuit.set_active_element(f"Transformer.{trafo_name}")
        full_bus_name = dss.cktelement.bus_names[winding_idx - 1]

        if "." in full_bus_name:
            parts = full_bus_name.split(".")
            info["target_bus"] = parts[0]
            try:
                info["target_phase"] = int(parts[1])
            except (ValueError, TypeError):
                info["target_phase"] = 1
        else:
            info["target_bus"] = full_bus_name
            info["target_phase"] = 1

        reg_list.append(info)

    return reg_list


def get_regulator_measurements(dss: Any, reg_info: dict[str, Any]) -> dict[str, Any]:
    """Read voltage, current, and tap position of a regulator.

    Args:
        dss: Active ``py_dss_interface.DSS`` instance.
        reg_info: Dictionary returned by :func:`get_all_regulators_info`.

    Returns:
        Dictionary with keys ``'v'`` (complex), ``'i'`` (complex),
        and ``'tap'`` (int).

    Raises:
        OpenDSSException: If the regulator's winding or phase cannot be
            resolved. This used to be swallowed, and the caller received zeros
            that a controller could not tell apart from a real measurement.
    """
    name = reg_info["name"]
    phase = reg_info["target_phase"]

    dss.regcontrols.name = name

    return {
        "tap": dss.regcontrols.tap_number,
        "v": _bus_phase_voltage(dss, reg_info["target_bus"], phase),
        "i": _winding_phase_current(dss, reg_info["trafo"], reg_info["winding"], phase, name),
    }


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _bus_phase_voltage(dss: Any, bus: str, phase: int) -> complex:
    """Complex voltage of one bus phase, in Volts."""
    real, imag = _get_bus_voltage_raw(dss, bus, phase)
    return complex(real, imag)


def _winding_phase_current(
    dss: Any, transformer: str, winding: int, phase: int, reg_name: str
) -> complex:
    """Complex current on one phase of a transformer winding, in Amperes.

    The conductor carrying *phase* is located through ``node_order`` rather than
    assumed to sit at position ``phase - 1``. That assumption held only for
    regulators on phase 1: a single-phase regulator on phase 3 has a single
    conductor, so indexing at position 2 raised ``IndexError`` — which the old
    bare ``except`` turned into a silent zero current, disabling line drop
    compensation on every phase but the first.

    Args:
        dss: Active ``py_dss_interface.DSS`` instance.
        transformer: Transformer name driven by the regulator.
        winding: 1-based winding (terminal) number.
        phase: Phase (node) number to read.
        reg_name: Regulator name, for error messages.

    Returns:
        Complex current of that phase.

    Raises:
        OpenDSSException: If the winding is out of range or the phase is not
            connected to it.
    """
    dss.circuit.set_active_element(f"Transformer.{transformer}")

    n_cond = dss.cktelement.num_conductors
    n_term = dss.cktelement.num_terminals

    if not 1 <= winding <= n_term:
        raise OpenDSSException(
            f'RegControl "{reg_name}": winding {winding} is out of range for '
            f"Transformer.{transformer} ({n_term} winding(s))"
        )

    start = (winding - 1) * n_cond
    nodes = list(dss.cktelement.node_order)[start : start + n_cond]

    if phase not in nodes:
        raise OpenDSSException(
            f'RegControl "{reg_name}": phase {phase} is not connected to winding '
            f"{winding} of Transformer.{transformer} (nodes {nodes})"
        )

    offset = nodes.index(phase)
    currents = dss.cktelement.currents[2 * start : 2 * (start + n_cond)]
    return complex(currents[2 * offset], currents[2 * offset + 1])


def _get_bus_voltage_raw(dss: Any, bus: str, phase: int) -> tuple[float, float]:
    """Return the (real, imaginary) voltage for a single bus phase in Volts.

    Args:
        dss: Active ``py_dss_interface.DSS`` instance.
        bus: Bus name to query.
        phase: Phase number (1-based) to extract.

    Returns:
        Tuple of ``(real_voltage, imag_voltage)`` in Volts.

    Raises:
        OpenDSSException: If the bus does not carry *phase*. Falling back to
            the first node instead would hand the regulator another phase's
            voltage without saying so.
    """
    dss.circuit.set_active_bus(bus)
    v = dss.bus.voltages
    nodes = dss.bus.nodes

    if phase not in nodes:
        raise OpenDSSException(f'Bus "{bus}" has no phase {phase} (nodes {list(nodes)})')

    idx = nodes.index(phase)
    return v[0::2][idx], v[1::2][idx]
