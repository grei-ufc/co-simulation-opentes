"""Leituras do circuito OpenDSS.

Todas as consultas servem a ultima solucao e passam pelo cache de
:class:`~._types.SolutionSnapshot`, entao repetir uma leitura no mesmo passo
nao custa nova ida ao motor. Resolva o fluxo antes de ler.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
import py_dss_interface

from . import (
    opendss_bus,
    opendss_generator,
    opendss_loadshape,
    opendss_pv,
    opendss_regulator,
    opendss_storage,
    opendss_transformer,
)
from ._types import ElementSnapshot, OpenDSSException
from ._utils import ABSENT, map_to_phases, sum_phases

# Classes totalizadas por get_circuit_info, na ordem das chaves.
CIRCUIT_INFO_CLASSES = ("Load", "PVSystem", "Generator", "Storage")


class ReaderMixin:
    """Consultas de barras, elementos, propriedades e totais do circuito."""

    def get_all_buses(self) -> list[str]:
        """Returns a list of all bus names in the circuit."""
        return self.dss.circuit.buses_names

    def get_all_buses_info(self) -> dict[str, dict[str, Any]]:
        """Dados estáticos de todas as barras: tensão base, nós e coordenadas.

        A mesma leitura que o grafo da topologia faz; ver
        :func:`~.opendss_bus.read_bus_info`.
        """
        return opendss_bus.get_all_buses_info(self.dss)

    def get_all_elements(self, element: str = "Load") -> pd.DataFrame:
        """
        Returns a DataFrame containing all properties for all elements of a specific class.

        Args:
            element (str): The element class (e.g., 'Load', 'Line').

        Returns:
            pd.DataFrame: DataFrame indexed by the full element name.
        """
        try:
            self.dss.circuit.set_active_class(element)
        except py_dss_interface.errors.DSSException:
            # A classe nao existe no OpenDSS: nao ha elementos a listar.
            return pd.DataFrame()

        # CORREÇÃO DEFINITIVA: Checa se existem elementos antes de acessar os nomes
        if self.dss.active_class.count == 0:
            return pd.DataFrame()

        # Agora é seguro pedir os nomes
        names = self.dss.active_class.names

        # Dupla checagem de segurança
        if not names or names[0] is None or names[0].lower() == "none":
            return pd.DataFrame()

        all_data = {}
        for name in names:
            full_name = f"{element}.{name}"
            self.dss.circuit.set_active_element(full_name)

            element_data = {}
            prop_names = self.dss.dsselement.property_names
            for i, prop_name in enumerate(prop_names, 1):
                element_data[prop_name] = self.dss.dssproperties.value_read(str(i))

            all_data[full_name] = element_data

        df = pd.DataFrame.from_dict(all_data, orient="index")
        return df

    def _element_snapshot(self, name: str, element: str) -> ElementSnapshot:
        """Terminal layout plus powers and currents of one element, read once per solve.

        Activating an element and pulling its arrays costs one engine round-trip
        each. Within a single step every attribute of an element is derived from
        the same three arrays, so they are fetched together and reused until the
        next solve or circuit edit.

        Args:
            name: Element name.
            element: Element class.

        Returns:
            The cached :class:`ElementSnapshot` for this element.
        """
        key = (element.lower(), name.lower())
        snapshot = self._snapshot.elements.get(key)

        if snapshot is None:
            self.set_element(name, element)
            snapshot = ElementSnapshot(
                full_name=self.dss.cktelement.name,
                n_cond=self.dss.cktelement.num_conductors,
                n_term=self.dss.cktelement.num_terminals,
                n_phases=self.dss.cktelement.num_phases,
                node_order=list(self.dss.cktelement.node_order),
                powers=self.dss.cktelement.powers,
                currents_mag_ang=self.dss.cktelement.currents_mag_ang,
            )
            self._snapshot.elements[key] = snapshot

        return snapshot

    def _element_losses_snapshot(self, name: str, element: str) -> ElementSnapshot:
        """Snapshot of *element* with the loss arrays filled in.

        Losses cost two engine reads that most elements never need, so they are
        fetched the first time they are asked for rather than with the rest of
        the snapshot. Both arrays come from the same visit: a caller wanting the
        per-phase breakdown almost always wants the total next to it, and the
        two are only comparable when they describe the same solution.

        Args:
            name: Element name.
            element: Element class.

        Returns:
            The cached :class:`ElementSnapshot`, with ``losses`` and
            ``phase_losses`` populated.
        """
        snapshot = self._element_snapshot(name, element)

        if snapshot.losses is None:
            self.set_element(name, element)
            snapshot.losses = self.dss.cktelement.losses
            snapshot.phase_losses = self.dss.cktelement.phase_losses

        return snapshot

    @property
    def node_index(self) -> dict[str, list[tuple[int, int]]]:
        """Position of each bus phase inside the engine's flat nodal arrays.

        The node layout is a property of the compiled circuit, not of a
        solution, so it is built once and reused across steps.

        Returns:
            Mapping of lowercase bus name to a list of
            ``(phase_index, array_position)`` pairs, where ``phase_index`` is
            0-based and ``array_position`` indexes ``circuit.nodes_names``.
        """
        if self._node_index is None:
            self._node_index = self._build_node_index()
        return self._node_index

    def _build_node_index(self) -> dict[str, list[tuple[int, int]]]:
        """Parse ``circuit.nodes_names`` once into a per-bus position lookup."""
        index: dict[str, list[tuple[int, int]]] = {}

        for position, node_name in enumerate(self.dss.circuit.nodes_names):
            bus, _, node_str = node_name.rpartition(".")
            try:
                node = int(node_str)
            except ValueError:
                continue
            if not 1 <= node <= 3:
                continue
            index.setdefault(bus.lower(), []).append((node - 1, position))

        return index

    def _bus_positions(self, bus: str) -> list[tuple[int, int]]:
        """Positions for *bus*, or an empty list after reporting an unknown bus."""
        bus_key = bus.lower().split(".")[0]
        positions = self.node_index.get(bus_key)

        if positions is None:
            self.fail(f'Bus "{bus}" not found in circuit voltages')
            return []

        return positions

    def get_bus_vmag_pu(self, bus: str) -> list[float]:
        """Per-unit voltage magnitude per phase of one bus.

        Served from a single bulk read of the whole circuit
        (``circuit.buses_vmag_pu``), cached until the next solve or edit. Only
        the requested bus is unpacked, so monitoring a couple of buses does not
        cost the whole circuit.

        Args:
            bus: Bus name, with or without a node suffix (``'675'`` or ``'675.1'``).

        Returns:
            ``[|V1|, |V2|, |V3|]`` in per unit; phases the bus lacks are
            :data:`~._utils.ABSENT` (``NaN``).

        Raises:
            OpenDSSException: If the bus is not in the circuit and
                ``fail_on_error`` is set.
        """
        if self._snapshot.bus_vmag_pu is None:
            self._snapshot.bus_vmag_pu = self.dss.circuit.buses_vmag_pu
        mags = self._snapshot.bus_vmag_pu

        phases = [ABSENT, ABSENT, ABSENT]
        for phase_idx, position in self._bus_positions(bus):
            phases[phase_idx] = mags[position]
        return phases

    def get_bus_vang(self, bus: str) -> list[float]:
        """Voltage angle per phase of one bus, in degrees.

        Angles come from ``circuit.buses_volts``, read and cached separately
        from the magnitudes so that a scenario asking only for magnitudes never
        pays for this call.

        Args:
            bus: Bus name, with or without a node suffix.

        Returns:
            ``[ang1, ang2, ang3]`` in degrees; phases the bus lacks are
            :data:`~._utils.ABSENT` (``NaN``).

        Raises:
            OpenDSSException: If the bus is not in the circuit and
                ``fail_on_error`` is set.
        """
        if self._snapshot.bus_volts is None:
            self._snapshot.bus_volts = self.dss.circuit.buses_volts
        volts = self._snapshot.bus_volts

        phases = [ABSENT, ABSENT, ABSENT]
        for phase_idx, position in self._bus_positions(bus):
            phases[phase_idx] = math.degrees(
                math.atan2(volts[2 * position + 1], volts[2 * position])
            )
        return phases

    def get_bus_voltage_pu(self, bus: str) -> tuple[list[float], list[float]]:
        """Per-unit magnitude and angle per phase of one bus.

        Convenience over :meth:`get_bus_vmag_pu` and :meth:`get_bus_vang`; reads
        both arrays. Prefer the individual methods when only one is needed.

        Args:
            bus: Bus name, with or without a node suffix.

        Returns:
            Tuple ``([|V1|, |V2|, |V3|], [ang1, ang2, ang3])`` in per unit and
            degrees.
        """
        return self.get_bus_vmag_pu(bus), self.get_bus_vang(bus)

    @staticmethod
    def _terminal_nodes_and_slice(
        snapshot: ElementSnapshot, terminal: int
    ) -> tuple[list[int], slice]:
        """Node numbers and the value slice for one terminal of *snapshot*.

        OpenDSS lays out ``powers``/``currents`` as ``num_terminals`` blocks of
        ``num_conductors`` complex pairs. ``node_order`` follows the same layout
        with one node number per conductor, so both are sliced identically.

        Using ``num_conductors`` (rather than ``num_phases``) is what makes this
        work uniformly for wye elements with a neutral, delta elements, lines,
        and transformer windings.

        Args:
            snapshot: Element snapshot to slice.
            terminal: 1-based terminal (or winding) number.

        Returns:
            Tuple of the terminal's node numbers and the ``slice`` selecting its
            values inside a flat ``[re, im, re, im, ...]`` OpenDSS array.

        Raises:
            OpenDSSException: If *terminal* is out of range for the element.
        """
        if not 1 <= terminal <= snapshot.n_term:
            raise OpenDSSException(
                f'Terminal {terminal} is out of range for "{snapshot.full_name}" '
                f"({snapshot.n_term} terminal(s))"
            )

        start = (terminal - 1) * snapshot.n_cond
        nodes = snapshot.node_order[start : start + snapshot.n_cond]
        return nodes, slice(2 * start, 2 * (start + snapshot.n_cond))

    def get_phase_powers(
        self, name: str, element: str = "Load", terminal: int = 1
    ) -> tuple[list[float], list[float]]:
        """Active and reactive power per phase, positioned by the element's nodes.

        A forma do retorno não depende do número de fases do elemento: são
        sempre três valores, indexados por fase, com :data:`~._utils.ABSENT`
        (``NaN``) onde o elemento não tem condutor. É o que permite ler um
        monofásico e um trifásico pelo mesmo caminho, sem que o chamador precise
        descobrir o formato antes de interpretar os números.

        Args:
            name: Element name.
            element: Element class (``'Load'``, ``'PVSystem'``, ``'Line'``, ...).
            terminal: Terminal to read (1 for shunt elements; 1 or 2 for lines;
                winding number for transformers).

        Returns:
            Tuple ``([P1, P2, P3], [Q1, Q2, Q3])`` in kW and kvar, using the
            native OpenDSS sign convention (load positive).
        """
        snapshot = self._element_snapshot(name, element)
        nodes, values = self._terminal_nodes_and_slice(snapshot, terminal)
        powers = snapshot.powers[values]
        return map_to_phases(nodes, powers[0::2]), map_to_phases(nodes, powers[1::2])

    def get_phase_currents(
        self, name: str, element: str = "Load", terminal: int = 1
    ) -> tuple[list[float], list[float]]:
        """Current magnitude and angle per phase, positioned by the element's nodes.

        Args:
            name: Element name.
            element: Element class (``'Load'``, ``'PVSystem'``, ``'Line'``, ...).
            terminal: Terminal to read (1 for shunt elements; 1 or 2 for lines;
                winding number for transformers).

        Returns:
            Tuple ``([|I1|, |I2|, |I3|], [ang1, ang2, ang3])`` in amperes and
            degrees.
        """
        snapshot = self._element_snapshot(name, element)
        nodes, values = self._terminal_nodes_and_slice(snapshot, terminal)
        currents = snapshot.currents_mag_ang[values]
        return map_to_phases(nodes, currents[0::2]), map_to_phases(nodes, currents[1::2])

    def get_ampacity(self, name: str, element: str = "Line") -> tuple[float, float]:
        """Current limits of an element: the normal and the emergency ratings.

        É o denominador do carregamento. O valor é estático — pertence ao
        circuito compilado, e não a uma solução —, então quem o usa a cada passo
        deve guardá-lo em vez de reler daqui.

        Uma linha que não declara ``normamps`` herda o do seu ``LineCode``; a
        herança é resolvida pelo motor, então não é preciso procurar o linecode
        nem interpretar a propriedade como texto. **Quando ninguém declara nada,
        o OpenDSS entrega o padrão dele — 400 A normais e 600 A emergenciais —
        para qualquer linha, do tronco ao ramal monofásico.** Nenhum dos
        alimentadores que acompanham o projeto declara ampacidade.

        Args:
            name: Element name.
            element: Element class (``'Line'``, ``'Transformer'``).

        Returns:
            Tuple ``(normal, emergencial)`` em amperes.
        """
        self.set_element(name, element)
        return self.dss.cktelement.norm_amps, self.dss.cktelement.emerg_amps

    def get_phase_losses(self, name: str, element: str = "Line") -> tuple[list[float], list[float]]:
        """Power lost inside one element, broken down per phase.

        A perda é do elemento inteiro, e não de um terminal: o motor soma
        ``V·conj(I)`` sobre todos os terminais, que é justamente o que sobra
        entre o que entra por um lado e o que sai pelo outro. Por isso não há
        argumento ``terminal`` aqui, ao contrário de :meth:`get_phase_powers`.

        Só faz sentido físico em elementos série — ``Line`` e ``Transformer``.
        Num elemento shunt de um terminal (carga, PV, bateria) o mesmo cálculo
        devolve a própria potência do elemento, não uma perda.

        A parcela de uma fase pode ser negativa em linhas com acoplamento mútuo
        forte e correntes desequilibradas: parte da perda é atribuída à fase
        vizinha. É a repartição que fica estranha, não o total.

        Args:
            name: Element name.
            element: Element class (``'Line'``, ``'Transformer'``).

        Returns:
            Tuple ``([P1, P2, P3], [Q1, Q2, Q3])`` in **kW and kvar**; phases
            the element does not have are :data:`~._utils.ABSENT` (``NaN``).
        """
        snapshot = self._element_losses_snapshot(name, element)

        # O motor entrega 2*num_phases valores, [P1, Q1, P2, Q2, ...], na ordem
        # dos condutores do terminal 1 — daí o corte do node_order.
        nodes = snapshot.node_order[: snapshot.n_phases]
        values = snapshot.phase_losses
        return map_to_phases(nodes, values[0::2]), map_to_phases(nodes, values[1::2])

    def get_element_losses(self, name: str, element: str = "Line") -> tuple[float, float]:
        """Total power lost inside one element.

        O escalar que acompanha :meth:`get_phase_losses`, e não a soma dela: o
        motor conta aqui todos os condutores, o neutro inclusive, enquanto a
        versão por fase só percorre os condutores de fase. Num neutro
        solidamente aterrado as duas coincidem; num neutro flutuante, que tem
        tensão própria, o total é o número correto.

        Args:
            name: Element name.
            element: Element class (``'Line'``, ``'Transformer'``).

        Returns:
            Tuple ``(P, Q)`` in **kW and kvar**. O motor reporta este par em
            W/var — ao contrário do de :meth:`get_phase_losses`, que já vem em
            kW/kvar —, e a conversão acontece aqui para que as duas leituras
            saiam do wrapper na mesma unidade.
        """
        p_w, q_var = self._element_losses_snapshot(name, element).losses
        return p_w / 1000.0, q_var / 1000.0

    def get_power_total(
        self, name: str, element: str = "Load", terminal: int = 1
    ) -> tuple[float, float]:
        """Active and reactive power of an element, summed over its phases.

        The scalar counterpart of :meth:`get_phase_powers`. Separating the two
        is what removes the need for a ``total`` flag that changes the return
        shape.

        Args:
            name: Element name.
            element: Element class.
            terminal: Terminal to read.

        Returns:
            Tuple ``(P, Q)`` in kW and kvar, native OpenDSS sign convention.
            Both are :data:`~._utils.ABSENT` if the element has no phase.
        """
        active, reactive = self.get_phase_powers(name, element=element, terminal=terminal)
        # sum_phases, e não sum: as fases ausentes são NaN, e o embutido faria
        # o total de todo elemento não trifásico virar NaN.
        return sum_phases(active), sum_phases(reactive)

    def get_all_complex(self, name: str, element: str = "Load") -> dict[str, tuple]:
        """Returns a dictionary with all complex quantities (V, I, S) for the element."""
        self.set_element(name, element)
        return {
            "Voltages": self.dss.cktelement.voltages,
            "VoltagesMagAng": self.dss.cktelement.voltages_mag_ang,
            "Currents": self.dss.cktelement.currents,
            "CurrentsMagAng": self.dss.cktelement.currents_mag_ang,
            "Powers": self.dss.cktelement.powers,
        }

    def get_all_properties(self, name: str, element: str = "Load") -> list[str]:
        """Returns a list of property names available for the element."""
        self.set_element(name, element)
        return self.dss.dsselement.property_names

    def get_property(self, name: str, property_name: str, element: str = "Load") -> float | str:
        """Reads the value of a specific property of an element."""
        all_properties = self.get_all_properties(name, element)
        if property_name.lower() not in [p.lower() for p in all_properties]:
            raise OpenDSSException(
                f'Could not find {property_name} property for {element} "{name}"'
            )

        idx = [p.lower() for p in all_properties].index(property_name.lower()) + 1
        value = self.dss.dssproperties.value_read(str(idx))

        try:
            return float(value)
        except (ValueError, TypeError):
            return value

    def get_is_open(self, name: str, element: str = "Line", term: int | None = None) -> bool:
        """Whether the element is open — by default, at any of its terminals.

        Uma chave tem **um** estado, mas o OpenDSS tem um por terminal, e
        ``is_terminal_open`` responde pelo terminal que recebe (ao contrário do
        que diz a docstring do ``py-dss-interface``, que fala em "any
        terminal"). Olhar só o terminal 1 faria passar por fechada a chave que o
        circuito abriu pelo outro lado — é o caso das duas chaves normalmente
        abertas do IEEE123, que o ``.dss`` abre com ``terminal=2``.

        Args:
            name: Element name.
            element: Element class.
            term: Terminal a consultar. ``None`` (padrão) responde pelo
                elemento: aberto se **qualquer** terminal estiver aberto.

        Returns:
            ``True`` se aberto.
        """
        self.set_element(name, element)

        if term is not None:
            return bool(self.dss.cktelement.is_terminal_open(term))

        return any(
            bool(self.dss.cktelement.is_terminal_open(t))
            for t in range(1, self.dss.cktelement.num_terminals + 1)
        )

    def get_tap(self, name: str) -> int:
        """Gets the current tap of a RegControl."""
        # self.set_element(name, 'RegControl')
        self.dss.regcontrols.name = name
        return self.dss.regcontrols.tap_number

    def get_pt_ratio(self, name: str) -> float:
        """Gets the PT Ratio of a CapControl."""
        self.set_element(name, "CapControl")
        return self.dss.capcontrols.pt_ratio

    def get_loadshape(self, name: str) -> dict[str, Any]:
        """Multiplicadores, número de pontos e intervalo de uma LoadShape.

        Ver :func:`~.opendss_loadshape.read_loadshape`, que concilia o ``npts``
        com o vetor real e recusa uma curva inexistente ou vazia.
        """
        return opendss_loadshape.read_loadshape(self.dss, name)

    def get_circuit_summary(self) -> dict[str, Any]:
        """Dados estáticos do circuito compilado e os ajustes do solucionador.

        Returns:
            Dict com ``name``, ``num_buses``, ``num_nodes``, ``tolerance`` e
            ``max_iterations`` — os ajustes em vigor, para o cenário registrar
            contra que critério as tensões do estudo foram resolvidas.
        """
        return {
            "name": self.dss.circuit.name,
            "num_buses": self.dss.circuit.num_buses,
            "num_nodes": self.dss.circuit.num_nodes,
            "tolerance": self.dss.solution.tolerance,
            "max_iterations": self.dss.solution.max_iterations,
        }

    def get_solution_state(self) -> tuple[bool, int]:
        """Se a última solução convergiu, e em quantas iterações.

        Lido do motor, e não do cache: são dois escalares de uma chamada só.

        Returns:
            Tupla ``(converged, iterations)``. O motor devolve ``converged``
            como inteiro (0/1); aqui ele já sai booleano.
        """
        return bool(self.dss.solution.converged), self.dss.solution.iterations

    def get_circuit_power(self) -> tuple[float, float]:
        """
        Gets the total active and reactive power of the circuit.

        Note: This inverts the standard OpenDSS sign convention (where generation is positive)
        so that grid consumption is positive and injection into the grid is negative
        (or vice versa, depending on reference, but signs are flipped from native output).

        Returns:
            Tuple[float, float]: (P_kW, Q_kvar).
        """
        p_kw, q_kvar = self.dss.circuit.total_power
        p_kw, q_kvar = -p_kw, -q_kvar

        if np.isnan(p_kw) or np.isnan(q_kvar):
            self.fail(f"NaN output for circuit power: ({p_kw}, {q_kvar})")
        return p_kw, q_kvar

    def get_losses(self) -> tuple[float, float]:
        """
        Gets the total circuit losses.

        Returns:
            Tuple[float, float]: (P_kW, Q_kvar).
        """
        p_w, q_var = self.dss.circuit.losses
        return p_w / 1000.0, q_var / 1000.0

    def get_total_power(self, element: str = "Load") -> tuple[float, float]:
        """
        Calculates the aggregated power for a specific class of elements.

        Args:
            element (str): The class name (e.g., 'Load', 'PVSystem', 'Storage').

        Returns:
            Tuple[float, float]: Total (P_kW, Q_kvar).
        """
        p_total, q_total = 0.0, 0.0

        try:
            self.dss.circuit.set_active_class(element)
        except py_dss_interface.errors.DSSException:
            return 0.0, 0.0

        if self.dss.active_class.count == 0:
            return 0.0, 0.0

        idx = self.dss.active_class.first()
        while idx > 0:
            powers = self.dss.cktelement.powers
            p_total += sum(powers[0::2])
            q_total += sum(powers[1::2])
            idx = self.dss.active_class.next()

        # For Storage, we invert the sign to match injection/consumption conventions
        if element == "Storage":
            return -p_total, -q_total

        return p_total, q_total

    def get_circuit_info(self) -> dict[str, float]:
        """Summary of the system state for the current solution.

        Reads only; solve first via :meth:`~._engine.EngineMixin.run_dss`.
        (It used to re-solve on its own, which made a getter silently advance
        the simulation.)

        Returns:
            Dict[str, float]: Dictionary containing Total P/Q (MW/MVAR) and Losses.
        """
        p_total_kw, q_total_kvar = self.get_circuit_power()
        p_loss_kw, q_loss_kvar = self.get_losses()
        # Toda classe entra, com zero se o circuito não tiver nenhum elemento
        # dela: o conjunto de chaves não depende do circuito.
        total_by_class = {
            class_name: self.get_total_power(class_name) for class_name in CIRCUIT_INFO_CLASSES
        }

        out = {
            "Total P (MW)": p_total_kw / 1000,
            "Total Loss P (MW)": p_loss_kw / 1000,
        }
        for class_name, (p, _q) in total_by_class.items():
            display_name = "PV" if class_name == "PVSystem" else class_name
            out[f"Total {display_name} P (MW)"] = p / 1000

        out.update(
            {
                "Total Q (MVAR)": q_total_kvar / 1000,
                "Total Loss Q (MVAR)": q_loss_kvar / 1000,
            }
        )
        for class_name, (_p, q) in total_by_class.items():
            display_name = "PV" if class_name == "PVSystem" else class_name
            out[f"Total {display_name} Q (MVAR)"] = q / 1000
        return out

    def get_all_regulators_info(self):
        """Detecta todos os RegControls e retorna seus dados estaticos."""
        return opendss_regulator.get_all_regulators_info(self.dss)

    def get_regulator_measurements(self, reg_info):
        """Le tensao, corrente e tap de um regulador."""
        return opendss_regulator.get_regulator_measurements(self.dss, reg_info)

    def get_all_transformers_info(self):
        """Retorna dados estaticos de todos os transformadores habilitados."""
        return opendss_transformer.get_all_transformers_info(self.dss)

    def get_pvsystem_power(self, name: str):
        """Le P e Q medidos nos terminais de um PVSystem."""
        return opendss_pv.get_pvsystem_power(self.dss, name)

    def get_all_pvsystems_info(self):
        """Retorna dados estaticos e curvas de todos os PVSystems.

        As curvas e os limiares de corte sao os que o circuito declara, e nao
        os ideais que o carregamento pos no motor: e deles que um simulador de
        inversor precisa. Ver :meth:`_idealize_pvsystems`.
        """
        return opendss_pv.get_all_pvsystems_info(self.dss, self._declared_pv_conversion)

    def get_all_generators_info(self):
        """Retorna dados estaticos de todos os Generators.

        A faixa de tensao (``vminpu``/``vmaxpu``) e a que o circuito declara, e
        nao a relaxada que o carregamento pos no motor. Ver
        :meth:`_relax_generators`.
        """
        return opendss_generator.get_all_generators_info(self.dss, self._declared_generator_band)

    def get_all_storages_info(self):
        """Retorna dados estaticos de todos os elementos Storage."""
        return opendss_storage.get_all_storages_info(self.dss)

    def get_storage_soc(self, name: str) -> float:
        """State of charge of a Storage element, in per unit.

        Args:
            name: Storage name (without the ``Storage.`` prefix).

        Returns:
            State of charge between 0.0 and 1.0.
        """
        self.dss.storages.name = name
        return self.dss.storages.pu_soc
