"""Bus operations on the OpenDSS circuit.

Standalone functions that receive an active ``py_dss_interface.DSS`` instance
and encapsulate reading of static bus data. They sit behind the facade: the
adapter reaches them through :meth:`~.opendss_wrapper.OpenDSS.get_all_buses_info`,
and the topology builder calls them directly, so both read a bus the same way.
"""

from __future__ import annotations

from typing import Any


def read_bus_info(dss: Any, name: str) -> dict[str, Any]:
    """Dados estáticos de uma barra, como o motor os reporta.

    As coordenadas saem cruas: sem ``BusCoords``, o motor reporta (0, 0), e só
    o ``coord_defined`` distingue esse zero de uma barra que fica de fato na
    origem. Decidir o que fazer com ele — o grafo troca por ``None``, o
    ``extra_info`` do adaptador mantém o valor e o flag — fica com quem consome.

    Args:
        dss: Active ``py_dss_interface.DSS`` instance.
        name: Nome da barra, como em ``circuit.buses_names``.

    Returns:
        Dict com ``kv_base``, ``nodes``, ``num_nodes``, ``x``, ``y`` e
        ``coord_defined``.
    """
    dss.circuit.set_active_bus(name)
    return {
        "kv_base": dss.bus.kv_base,
        "nodes": list(dss.bus.nodes),
        "num_nodes": dss.bus.num_nodes,
        "x": dss.bus.x,
        "y": dss.bus.y,
        "coord_defined": bool(dss.bus.coord_defined),
    }


def get_all_buses_info(dss: Any) -> dict[str, dict[str, Any]]:
    """Dados estáticos de todas as barras, na ordem do circuito.

    Args:
        dss: Active ``py_dss_interface.DSS`` instance.

    Returns:
        Mapa nome da barra -> dados de :func:`read_bus_info`.
    """
    return {name: read_bus_info(dss, name) for name in dss.circuit.buses_names}
