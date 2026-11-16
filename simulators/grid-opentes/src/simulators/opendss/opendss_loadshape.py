"""LoadShape operations on the OpenDSS circuit.

Standalone functions that receive an active ``py_dss_interface.DSS`` instance
and encapsulate reading of load shapes, with the engine's quirks resolved here
instead of in whoever consumes the curve.
"""

from __future__ import annotations

from typing import Any

from ._types import OpenDSSException


def read_loadshape(dss: Any, name: str) -> dict[str, Any]:
    """Multiplicadores de uma LoadShape, com as peculiaridades do motor resolvidas.

    Três peculiaridades ficam aqui, e não em quem consome a curva:

    - Pedir uma curva que não existe **não levanta erro**: a interface mantém
      ativa a curva anterior, e a leitura devolveria os pontos dela com o nome
      pedido. Medido — o motor só registra o código 77003. Por isso o nome
      ativo é conferido.
    - O ``npts`` declarado pode passar do vetor realmente entregue. Conciliar
      aqui, uma vez, evita um ``IndexError`` por passo em quem indexa a curva.
    - O intervalo entre pontos pode estar em segundos, minutos ou horas; vale o
      primeiro declarado.

    Args:
        dss: Active ``py_dss_interface.DSS`` instance.
        name: Nome da LoadShape.

    Returns:
        Dict com ``p_mult``, ``q_mult`` (igual a ``p_mult`` quando a curva não
        declara reativa), ``npts`` (já conciliado), ``interval_s`` (``None``
        se a curva não declara intervalo) e ``use_actual``.

    Raises:
        OpenDSSException: Se a curva não existe ou não tem pontos — uma curva
            vazia faria quem a indexa dividir por zero.
    """
    dss.loadshapes.name = name
    if str(dss.loadshapes.name).lower() != name.lower():
        raise OpenDSSException(f"LoadShape '{name}' nao existe no circuito")

    p_mult = list(dss.loadshapes.p_mult)
    q_mult = list(dss.loadshapes.q_mult)
    npts = dss.loadshapes.npts

    if not p_mult:
        raise OpenDSSException(f"LoadShape '{name}' nao tem pontos")

    if len(p_mult) < npts:
        print(
            f"[OpenTES][AVISO] LoadShape '{name}' declara npts={npts} "
            f"mas entregou {len(p_mult)} pontos; usando {len(p_mult)}."
        )
        npts = len(p_mult)

    if not q_mult or len(q_mult) < npts:
        q_mult = p_mult

    interval = dss.loadshapes.s_interval
    if interval == 0:
        interval = dss.loadshapes.min_interval * 60
    if interval == 0:
        interval = dss.loadshapes.hr_interval * 3600

    return {
        "p_mult": p_mult,
        "q_mult": q_mult,
        "npts": npts,
        "interval_s": interval or None,
        "use_actual": bool(dss.loadshapes.use_actual),
    }
