"""Reusable helpers for normalizing three-phase data returned by OpenDSS.

Uma fase que o elemento não tem é reportada como ``NaN``, e não como ``0.0``.
São coisas diferentes: um inversor ao amanhecer entrega zero, e esse zero é uma
medição legítima que precisa aparecer no gráfico; a fase B de um ramal
monofásico não existe e não tem valor nenhum. Enquanto as duas eram ``0.0``,
quem consumia os dados só podia escolher entre esconder as duas — o que
apagava a geração noturna — ou mostrar as duas, o que fazia a fase inexistente
parecer uma tensão colapsada.
"""

import math
from collections.abc import Iterable, Sequence

# Ausência de fase. Exportado para que quem consome os dados teste com
# ``math.isnan`` em vez de comparar com um sentinela.
ABSENT = math.nan


def map_to_phases(nodes: Sequence[int], values: Sequence[float]) -> list[float]:
    """Place per-conductor *values* at the index of the phase they belong to.

    OpenDSS returns element quantities ordered by *conductor*, not by phase. A
    single-phase element connected to ``bus.3`` reports one conductor value that
    belongs to phase 3 — padding it to the right would wrongly report it as
    phase 1. This function uses the element's node numbers (from
    ``cktelement.node_order``) to put each value in its real position.

    Node ``0`` is the neutral/ground conductor and is skipped. Nodes above 3
    (secondary windings, extra conductors) are skipped as well.

    Args:
        nodes: Node number of each conductor on one terminal, e.g. ``[3, 0]``
            for a single-phase element on phase 3 with a neutral.
        values: One value per conductor, in the same order as *nodes*.

    Returns:
        A list of exactly three floats, indexed by phase (``[p1, p2, p3]``).
        Positions with no conductor are :data:`ABSENT` (``NaN``).
    """
    phases = [ABSENT, ABSENT, ABSENT]
    for node, value in zip(nodes, values, strict=False):
        if 1 <= node <= 3:
            phases[node - 1] = value
    return phases


def normalize_zero(value: float) -> float:
    """Troca ``-0.0`` por ``0.0``.

    A convenção de injeção positiva multiplica a leitura por ``-1``, e um zero
    medido vira ``-0.0``. Os dois são numericamente iguais e desenham no mesmo
    ponto, mas o zero negativo aparece como ``-0.0000`` no tooltip — e agora que
    o zero é exibido em vez de escondido, isso passou a ser visível.

    ``NaN`` atravessa inalterado.
    """
    return value + 0.0


def present_phases(values: Iterable[float]) -> list[float]:
    """Só as fases que existem, descartando as :data:`ABSENT`.

    O zero medido é preservado: é justamente o que distingue esta função de
    filtrar por veracidade, como o código fazia enquanto a ausência era ``0.0``.
    """
    return [v for v in values if not math.isnan(v)]


def sum_phases(values: Iterable[float]) -> float:
    """Total das fases presentes.

    Somar com ``sum`` embutido contaminaria o total: um único ``NaN`` torna o
    resultado ``NaN``, e o total de um elemento monofásico — que é o valor que
    o cenário monitora — deixaria de existir.

    Returns:
        A soma das fases presentes, ou :data:`ABSENT` se não houver nenhuma.
    """
    present = present_phases(values)
    return sum(present) if present else ABSENT
