"""Transformer operations on the OpenDSS circuit.

Standalone functions that receive an active ``py_dss_interface.DSS`` instance
and encapsulate transformer detection and static data reading.

Transformers matter to the co-simulation for a reason that is easy to miss:
they are the only path between some parts of a feeder. In the IEEE34 the two
regulator banks are transformers (``814`` to ``814r``, ``852`` to ``852r``), so
a topology built from lines alone falls apart into disconnected islands.
"""

from __future__ import annotations

from typing import Any


def get_regulated_transformers(dss: Any) -> set[str]:
    """Names (lowercase) of the transformers driven by a ``RegControl``."""
    if not dss.regcontrols.count:
        return set()

    regulated = set()
    for name in dss.regcontrols.names:
        dss.regcontrols.name = name
        regulated.add(str(dss.regcontrols.transformer).lower())
    return regulated


def get_all_transformers_info(dss: Any) -> dict[str, dict[str, Any]]:
    """Static data of every enabled transformer, indexed by name.

    The winding buses come from ``cktelement.bus_names`` rather than from the
    ``buses=`` property string, which OpenDSS reports in a format that varies
    with how the transformer was declared.

    Args:
        dss: Active ``py_dss_interface.DSS`` instance.

    Returns:
        Mapping of transformer name to its static data. Empty if the circuit has
        no transformer.
    """
    infos: dict[str, dict[str, Any]] = {}

    if not dss.transformers.count:
        return infos

    regulated = get_regulated_transformers(dss)

    for name in dss.transformers.names:
        dss.transformers.name = name
        dss.circuit.set_active_element(f"Transformer.{name}")

        if not dss.cktelement.is_enabled:
            continue

        bus_names = list(dss.cktelement.bus_names)
        infos[name] = {
            "name": name,
            "buses": bus_names,
            "phases": dss.cktelement.num_phases,
            "windings": dss.transformers.num_windings,
            "kva": dss.transformers.kva,
            "kvs": _winding_kvs(dss),
            "tap": dss.transformers.tap,
            "is_regulated": name.lower() in regulated,
        }

    return infos


def _winding_kvs(dss: Any) -> list[float]:
    """Rated kV of each winding of the active transformer.

    Reading it winding by winding leaves ``dss.transformers.wdg`` pointing at
    the last one, so it is restored: a later read of a winding-scoped property
    would otherwise silently refer to the wrong winding.
    """
    original = dss.transformers.wdg
    kvs = []

    for winding in range(1, dss.transformers.num_windings + 1):
        dss.transformers.wdg = winding
        kvs.append(dss.transformers.kv)

    dss.transformers.wdg = original
    return kvs
