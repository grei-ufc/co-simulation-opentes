"""Tipos compartilhados pelas camadas do wrapper OpenDSS."""

from dataclasses import dataclass, field
from typing import Any


class OpenDSSException(Exception):
    """Custom exception for OpenDSS interface related errors."""

    pass


@dataclass
class ElementSnapshot:
    """Everything read from one circuit element in a single engine visit.

    Holds the terminal layout together with the raw ``powers`` and
    ``currents_mag_ang`` arrays, so every per-phase quantity of the element can
    be derived without going back to the engine.

    As perdas ficam de fora dessa primeira visita: são duas leituras a mais por
    elemento, e só as linhas e os transformadores as expõem. Pagá-las em toda
    leitura de potência sairia caro num alimentador de 123 barras para nada.
    :meth:`~._reader.ReaderMixin._element_losses` as preenche na primeira vez
    que alguém pedir, e o cache vale até a próxima solução como o resto.
    """

    full_name: str
    n_cond: int
    n_term: int
    n_phases: int
    node_order: list[int]
    powers: Any
    currents_mag_ang: Any
    losses: Any = None
    phase_losses: Any = None


@dataclass
class SolutionSnapshot:
    """Results cache scoped to one solution of the circuit.

    Cleared by :meth:`OpenDSS.invalidate_snapshot` on every solve and on every
    circuit edit, so reads never serve values from a superseded solution.

    Bus quantities are kept as the raw flat arrays returned by the engine rather
    than pre-folded per bus: folding every bus costs more than the bulk read
    itself, and a scenario that monitors two buses should not pay for 132.
    Magnitudes and angles come from different engine calls and are fetched
    independently, so asking only for magnitudes never reads the angles.
    """

    bus_vmag_pu: Any = None
    bus_volts: Any = None
    elements: dict[tuple[str, str], ElementSnapshot] = field(default_factory=dict)

    def clear(self) -> None:
        self.bus_vmag_pu = None
        self.bus_volts = None
        self.elements.clear()
