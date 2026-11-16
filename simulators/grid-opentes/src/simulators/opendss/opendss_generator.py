"""Generator element operations on the OpenDSS circuit.

Standalone functions that receive an active ``py_dss_interface.DSS`` instance
and encapsulate reading of static generator parameters and the voltage band
adjustment applied on load.
"""

from __future__ import annotations

from typing import Any

# Faixa de tensao que o carregamento do circuito poe no lugar da declarada. Ver
# relax_voltage_band.
RELAXED_VMINPU = 0.001
RELAXED_VMAXPU = 10.0


def relax_voltage_band(dss: Any) -> dict[str, dict[str, float]]:
    """Abre a faixa de tensão em que todo Generator mantém a potência comandada.

    Fora de ``Vminpu``/``Vmaxpu`` (0,9 a 1,1 pu por padrão), o OpenDSS troca o
    modelo do gerador por uma impedância constante, e a potência entregue
    passa a depender da tensão: medido, 100 kW comandados numa barra a 0,97 pu,
    com ``Vminpu=0.99``, saem 96 kW. Na co-simulação a potência chega pronta —
    de um controlador ou de uma curva — e tem de sair igual.

    Args:
        dss: Active ``py_dss_interface.DSS`` instance.

    Returns:
        A faixa que o circuito declarava, por Generator, lida antes da troca:
        ``vminpu`` e ``vmaxpu``.
    """
    names = _generator_names(dss)
    declared = {name: _read_voltage_band(dss, name) for name in names}

    for name in names:
        dss.text(f"Edit Generator.{name} Vminpu={RELAXED_VMINPU} Vmaxpu={RELAXED_VMAXPU}")

    return declared


def get_all_generators_info(
    dss: Any, declared: dict[str, dict[str, float]] | None = None
) -> dict[str, dict[str, Any]]:
    """Return static data for every Generator element in the circuit.

    Args:
        dss: Active ``py_dss_interface.DSS`` instance.
        declared: Faixa de tensão declarada no circuito, por Generator, como
            devolvida por :func:`relax_voltage_band`. Os geradores listados
            nela reportam essa faixa, e não a relaxada que o motor usa de fato;
            os demais são lidos do motor.

    Returns:
        Dictionary mapping Generator names to parameter dictionaries.
    """
    generator_infos: dict[str, dict[str, Any]] = {}
    declared = declared or {}

    for name in _generator_names(dss):
        dss.circuit.set_active_element(f"Generator.{name}")
        bus = dss.cktelement.bus_names[0]
        num_phases = dss.cktelement.num_phases

        band = dict(declared[name]) if name in declared else _read_voltage_band(dss, name)

        generator_infos[name] = {
            "name": name,
            "bus": bus,
            "num_phases": num_phases,
            "kv": _as_float(dss.text(f"? Generator.{name}.kV")),
            # Base do multiplicador: com P = mult x kW, a reativa vale
            # mult x kvar, o que preserva o pf declarado -- inclusive o
            # adiantado, em que pf e kvar sao negativos.
            "kw": _as_float(dss.text(f"? Generator.{name}.kW")),
            "kvar": _as_float(dss.text(f"? Generator.{name}.kvar")),
            "pf": _as_float(dss.text(f"? Generator.{name}.pf"), 1.0),
            "kva": _as_float(dss.text(f"? Generator.{name}.kVA")),
            "model": int(_as_float(dss.text(f"? Generator.{name}.model"), 1.0)),
            "conn": dss.text(f"? Generator.{name}.conn"),
            "status": dss.text(f"? Generator.{name}.status"),
            "daily": dss.text(f"? Generator.{name}.daily"),
            "yearly": dss.text(f"? Generator.{name}.yearly"),
            **band,
        }

    return generator_infos


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _as_float(value: Any, default: float = 0.0) -> float:
    """Converte uma propriedade DSS (sempre string) para float, com fallback."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _generator_names(dss: Any) -> list[str]:
    """Nomes dos Generators do circuito; vazio se não houver nenhum."""
    if not dss.generators.count:
        return []
    names = dss.generators.names
    if not names or str(names[0]).upper() == "NONE":
        return []
    return list(names)


def _read_voltage_band(dss: Any, name: str) -> dict[str, float]:
    """``Vminpu`` e ``Vmaxpu`` de um Generator, como estão no motor."""
    return {
        "vminpu": _as_float(dss.text(f"? Generator.{name}.Vminpu")),
        "vmaxpu": _as_float(dss.text(f"? Generator.{name}.Vmaxpu")),
    }
