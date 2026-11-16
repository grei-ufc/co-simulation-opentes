"""Escritas no circuito OpenDSS.

Toda escrita invalida o cache da solucao, direta ou indiretamente via
``run_command``, para que nenhuma leitura sirva valores de uma solucao
superada.
"""

from __future__ import annotations

from typing import Any

from . import opendss_pv
from ._types import OpenDSSException

# Tolerância relativa ao conferir um valor numérico relido do motor.
_VALUE_TOLERANCE = 1e-6

# Terminal pelo qual uma chave é aberta. É o que o próprio IEEE123 usa para as
# suas chaves normalmente abertas; ver `set_is_open`.
SWITCH_TERMINAL = 2


def _values_match(read_back: Any, written: Any) -> bool:
    """Compara o valor relido com o escrito, sem falsos negativos de formatação.

    O motor devolve as propriedades como texto, e ``get_property`` converte para
    float quando dá. Comparar as duas representações como string reprovava
    escritas corretas — escrever ``kW=1100`` e reler ``1100.0`` dá
    ``"1100" != "1100.0"``. Números são comparados numericamente; o resto,
    como texto sem diferenciar maiúsculas.
    """
    try:
        return abs(float(read_back) - float(written)) <= _VALUE_TOLERANCE * max(
            1.0, abs(float(written))
        )
    except (TypeError, ValueError):
        return str(read_back).strip().lower() == str(written).strip().lower()


class WriterMixin:
    """Ajuste de potencias, propriedades, taps e estado de elementos."""

    def set_power(
        self,
        name: str,
        p: float | None = None,
        q: float | None = None,
        element: str = "Load",
    ) -> None:
        """Define a potência ativa e reativa de uma carga, gerador ou bateria.

        Load e Generator guardam a potência nas propriedades ``kW`` e ``kvar``,
        e a escrita é direta; ``None`` deixa a grandeza como está.

        Storage precisa também de um estado coerente com o sinal: ``p > 0``
        descarrega, ``p < 0`` carrega e ``p == 0`` deixa a bateria ociosa. Sem
        ``p`` nada é escrito; sem ``q``, a reativa vai a zero.

        PVSystem não tem ``kW``: a saída é calculada de ``Pmpp`` e da
        irradiância, e o motor recusaria o comando (``Unknown parameter "kW"``).
        É barrado aqui, antes de chegar a ele, apontando para
        :meth:`set_pvsystem_pq`.

        Args:
            name: Nome do elemento.
            p: Potência ativa, em kW.
            q: Potência reativa, em kvar.
            element: Classe do elemento: ``'Load'``, ``'Generator'`` ou
                ``'Storage'``.

        Raises:
            OpenDSSException: Se *element* for um PVSystem — um erro de uso, que
                interrompe mesmo com ``fail_on_error`` desligado.
        """
        if element.lower() in ("pvsystem", "pv"):
            raise OpenDSSException(
                f'set_power nao comanda o PVSystem "{name}": a classe nao tem kW, e a '
                "saida e calculada de Pmpp e irradiancia. Use set_pvsystem_pq."
            )

        if element.lower() != "storage":
            cmd = f"edit {element}.{name}"
            if p is not None:
                cmd += f" kW={p}"
            if q is not None:
                cmd += f" kvar={q}"
            self.run_command(cmd)
        else:
            if p is None:
                return
            if q is None:
                q = 0.0

            if p > 0:
                state_str = "Discharging"
            elif p < 0:
                state_str = "Charging"
            else:
                state_str = "Idling"

            if state_str == "Idling":
                cmd = f"Edit Storage.{name} State={state_str}"
            else:
                cmd = f"Edit Storage.{name} State={state_str} kW={p} kvar={q}"

            self.run_command(cmd)

    def set_property(
        self, name: str, property_name: str, value: Any, element: str = "Load"
    ) -> None:
        """Set an element property and confirm the engine accepted it.

        Args:
            name: Element name.
            property_name: DSS property to write.
            value: Value to write.
            element: Element class.

        Raises:
            OpenDSSException: If the property does not exist for that element,
                or if reading it back does not match what was written.
        """
        # Validar antes de escrever: a mensagem lista as propriedades validas, o
        # que o motor nao faz. Com as caixas de dialogo ligadas -- o padrao do
        # OpenDSS --, mandar uma propriedade inexistente ainda abria uma no
        # Windows e travava a execucao; hoje elas ficam desligadas fora da
        # compilacao (ver _dialogs_while_compiling).
        valid = self.get_all_properties(name, element)
        if property_name.lower() not in [p.lower() for p in valid]:
            self.fail(
                f'{element}.{name} has no property "{property_name}". '
                f"Valid options: {', '.join(sorted(valid))}"
            )
            return

        self.run_command(f"edit {element}.{name} {property_name}={value}")

        new_value = self.get_property(name, property_name, element)
        if not _values_match(new_value, value):
            self.fail(
                f"Failed to set {element}.{name}.{property_name}: "
                f"wrote {value!r}, engine reports {new_value!r}"
            )

    def remove_loadshape(self, name: str, element: str = "Load") -> None:
        """Removes the associated loadshape, setting the mode to constant."""
        self.set_property(name, "yearly", "constant", element)

    def set_is_open(
        self, name: str, open: bool = True, element: str = "Line", term: int | None = None
    ) -> None:
        """Opens or closes an element — by default, as a switch with one state.

        Abrir usa o **terminal 2**, que é a convenção do próprio circuito: é
        assim que o IEEE123 abre as suas chaves normalmente abertas
        (``open Line.Sw7 terminal=2``). Adotá-la faz o estado produzido aqui
        ficar indistinguível do que vem declarado no ``.dss``.

        Fechar fecha **os dois** terminais. Fechar só o terminal 2 deixaria
        aberta a chave que alguém tivesse aberto pelo terminal 1, e o comando
        falharia em silêncio — com a corrente seguindo em zero.

        Não é preciso invalidar o cache aqui: ``run_command`` já o faz.

        Args:
            name: Element name.
            open: ``True`` abre, ``False`` fecha.
            element: Element class.
            term: Terminal a comandar. ``None`` (padrão) aplica a convenção de
                chave descrita acima.
        """
        full_name = f"{element}.{name}"

        if term is not None:
            self.run_command(f"{'Open' if open else 'Close'} {full_name} term={term}")
            return

        if open:
            self.run_command(f"Open {full_name} term={SWITCH_TERMINAL}")
            return

        for terminal in (1, 2):
            self.run_command(f"Close {full_name} term={terminal}")

    def set_tap(self, name: str, tap: int, max_tap: int = 16) -> None:
        """Sets the tap of a RegControl, clamping it to the max value."""
        # self.set_element(name, 'RegControl')
        self.invalidate_snapshot()
        self.dss.regcontrols.name = name
        tap = int(min(max(tap, -max_tap), max_tap))
        self.dss.regcontrols.tap_number = tap

    def set_pt_ratio(self, name: str, pt_ratio: float) -> None:
        """Sets the Potential Transformer (PT) Ratio of a CapControl."""
        self.invalidate_snapshot()
        self.set_element(name, "CapControl")
        self.dss.capcontrols.pt_ratio = pt_ratio

    def set_pvsystem_pq(self, name: str, p_des: float, q_des: float):
        """Forca valores de P e Q em um PVSystem."""
        self.invalidate_snapshot()
        opendss_pv.set_pvsystem_pq(self.dss, name, p_des, q_des)

    def set_storage_soc(self, name: str, soc_pu: float) -> None:
        """Force the state of charge of a Storage element.

        Args:
            name: Storage name (without the ``Storage.`` prefix).
            soc_pu: Target state of charge in per unit; clamped to ``[0, 1]``.
        """
        soc_pu = min(max(float(soc_pu), 0.0), 1.0)
        self.run_command(f"Edit Storage.{name} %stored={soc_pu * 100.0}")
