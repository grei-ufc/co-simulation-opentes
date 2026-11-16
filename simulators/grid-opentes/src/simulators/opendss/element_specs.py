"""Declarative registry mapping mosaik models to OpenDSS elements.

This table is the single source of truth for what each model exposes. The
mosaik ``META``, the input routing in ``step()`` and the output reads in
``get_data()`` are all derived from it, so a declared attribute cannot drift
away from the code that implements it.

Adding a model means adding one :class:`ModelSpec` here — not editing META,
``step`` and ``get_data`` in three places and hoping they agree.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from ._utils import ABSENT, normalize_zero, sum_phases

# Fontes de leitura de um elemento, resolvidas sob demanda por `read_phases`.
SOURCE_P = "p"
SOURCE_Q = "q"
SOURCE_P_SUM = "p_sum"
SOURCE_Q_SUM = "q_sum"
SOURCE_I_MAG = "i_mag"
SOURCE_I_ANG = "i_ang"
SOURCE_P_LOSS = "p_loss"
SOURCE_Q_LOSS = "q_loss"
SOURCE_P_LOSS_SUM = "p_loss_sum"
SOURCE_Q_LOSS_SUM = "q_loss_sum"

_POWER_SOURCES = (SOURCE_P, SOURCE_Q, SOURCE_P_SUM, SOURCE_Q_SUM)
_LOSS_SOURCES = (SOURCE_P_LOSS, SOURCE_Q_LOSS, SOURCE_P_LOSS_SUM, SOURCE_Q_LOSS_SUM)


# ----------------------------------------------------------------------
# Agregadores de entrada
# ----------------------------------------------------------------------


def sum_values(attr: str, eid: str, values: Iterable[Any]) -> Any:
    """Soma as contribuições de todos os simuladores conectados.

    Padrão para setpoints de potência, onde vários controladores podem
    legitimamente contribuir para o mesmo elemento.
    """
    return sum(values)


def single_value(attr: str, eid: str, values: Iterable[Any]) -> Any:
    """Espera exatamente um valor; avisa e usa o primeiro se houver mais.

    Para grandezas em que somar não faz sentido físico (posição de tap, SoC
    alvo). Antes esses casos pegavam ``list(values)[0]`` silenciosamente, o que
    descartava comandos concorrentes sem deixar rastro.
    """
    values = list(values)
    if len(values) > 1:
        print(
            f"[OpenTES][AVISO] {eid}.{attr} recebeu {len(values)} valores "
            f"concorrentes ({values}); usando o primeiro."
        )
    return values[0]


# ----------------------------------------------------------------------
# Especificações
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class InputSpec:
    """Como um atributo de entrada do mosaik é reduzido a um único valor.

    Attributes:
        aggregator: Como reduzir as contribuições de vários simuladores a um
            valor só.
        bounds: Faixa ``(mínimo, máximo)`` aceita, ou ``None`` para não
            restringir. Declarada aqui, ao lado do atributo e no mesmo registro
            de onde a META é derivada, em vez de enterrada no escritor.
    """

    aggregator: Callable[[str, str, Iterable[Any]], Any] = sum_values
    bounds: tuple[float, float] | None = None

    def check(self, attr: str, eid: str, value: Any) -> Any:
        """Devolve *value*, ou interrompe se ele estiver fora da faixa.

        A faixa é o contrato da curva. Um multiplicador fora dela significa que
        o arquivo não é o que o cenário pensa — unidade errada, coluna trocada,
        normalização esquecida — e seguir produziria um estudo inteiro de dados
        errados a partir de uma entrada que ninguém pretendeu.

        Raises:
            ValueError: Se houver ``bounds`` e *value* cair fora deles.
        """
        if self.bounds is None:
            return value

        low, high = self.bounds
        if not low <= value <= high:
            raise ValueError(
                f"{eid}.{attr} recebeu {value!r}, fora da faixa [{low}, {high}]. "
                "O valor é um multiplicador da placa do elemento, não uma "
                "potência: confira a unidade e a coluna da curva."
            )
        return value


@dataclass(frozen=True)
class ModelSpec:
    """Contrato de um modelo mosaik atendido por este simulador.

    Attributes:
        dss_class: Classe OpenDSS correspondente (``None`` para ``Bus``, que
            não é um elemento de circuito).
        reader: ``(sim, name, attrs, spec) -> dict`` com os valores de saída.
        writer: ``(sim, name, values) -> None`` aplicando as entradas já
            agregadas; ``None`` para modelos somente de leitura.
        inputs: Atributos de entrada aceitos e como agregá-los.
        attr_map: Atributo de saída -> ``(fonte, índice, fator)``.
        extra_outputs: Saídas que o *reader* produz fora do ``attr_map``.
        terminal: Terminal lido (1 para elementos shunt, 1 ou 2 para linhas).
        public: Se o cenário pode instanciar o modelo diretamente.
        params: Parâmetros aceitos na criação.
    """

    dss_class: str | None
    reader: Callable[..., dict[str, Any]]
    writer: Callable[..., None] | None = None
    inputs: dict[str, InputSpec] = field(default_factory=dict)
    attr_map: dict[str, tuple[str, int, float]] = field(default_factory=dict)
    extra_outputs: tuple[str, ...] = ()
    terminal: int = 1
    public: bool = False
    params: tuple[str, ...] = ()

    @property
    def outputs(self) -> tuple[str, ...]:
        return tuple(self.attr_map) + self.extra_outputs

    @property
    def attrs(self) -> list[str]:
        """Todos os atributos do modelo, na ordem entradas -> saídas.

        Um atributo pode ser lido e escrito (``tap``), então a lista é
        deduplicada preservando a ordem.
        """
        return list(dict.fromkeys([*self.inputs, *self.outputs]))


def phase_attr_map(
    p: tuple[str, ...] = (),
    q: tuple[str, ...] = (),
    i_mag: tuple[str, ...] = (),
    i_ang: tuple[str, ...] = (),
    p_total: tuple[str, ...] = (),
    q_total: tuple[str, ...] = (),
    p_loss: tuple[str, ...] = (),
    q_loss: tuple[str, ...] = (),
    p_loss_total: tuple[str, ...] = (),
    q_loss_total: tuple[str, ...] = (),
    sign: int = 1,
    scale: float = 1.0,
) -> dict[str, tuple[str, int, float]]:
    """Monta o mapa atributo -> (fonte, índice, fator) de um elemento trifásico.

    Args:
        p, q: Nomes dos atributos de potência ativa/reativa por fase.
        i_mag, i_ang: Nomes dos atributos de módulo/ângulo de corrente por fase.
        p_total, q_total: Nomes dos atributos de total somado nas fases.
        p_loss, q_loss: Nomes dos atributos de perda ativa/reativa por fase.
        p_loss_total, q_loss_total: Nomes dos atributos de perda total do
            elemento.
        sign: ``-1`` inverte a convenção do OpenDSS para injeção positiva.
        scale: Fator de unidade aplicado aos totais (ex.: ``1/1000`` para MW).

    Returns:
        Mapa pronto para ``ModelSpec.attr_map``.
    """
    mapping: dict[str, tuple[str, int, float]] = {}

    for source, names in ((SOURCE_P, p), (SOURCE_Q, q)):
        for index, attr in enumerate(names):
            mapping[attr] = (source, index, float(sign))

    # Correntes são magnitudes: a convenção de sinal não se aplica.
    for source, names in ((SOURCE_I_MAG, i_mag), (SOURCE_I_ANG, i_ang)):
        for index, attr in enumerate(names):
            mapping[attr] = (source, index, 1.0)

    # Perda é dissipação, sempre positiva no sentido do elemento: nem o `sign`
    # da injeção nem o `scale` dos totais se aplicam. A escala fica de fora
    # porque o nome do atributo de perda já carrega a unidade em que ele sai.
    for source, names in ((SOURCE_P_LOSS, p_loss), (SOURCE_Q_LOSS, q_loss)):
        for index, attr in enumerate(names):
            mapping[attr] = (source, index, 1.0)

    for source, names in ((SOURCE_P_SUM, p_total), (SOURCE_Q_SUM, q_total)):
        for attr in names:
            mapping[attr] = (source, 0, sign * scale)

    for source, names in ((SOURCE_P_LOSS_SUM, p_loss_total), (SOURCE_Q_LOSS_SUM, q_loss_total)):
        for attr in names:
            mapping[attr] = (source, 0, 1.0)

    return mapping


# ----------------------------------------------------------------------
# Leitores
# ----------------------------------------------------------------------


def read_phases(sim, name: str, attrs: Iterable[str], spec: ModelSpec) -> dict[str, Any]:
    """Lê grandezas por fase de um elemento, buscando só as fontes necessárias.

    Potências, correntes e perdas vêm de chamadas distintas ao motor, então cada
    uma é buscada apenas se algum atributo pedido depender dela — e no máximo
    uma vez.
    """
    cache: dict[str, list[float]] = {}

    def source(kind: str) -> list[float]:
        if kind not in cache:
            if kind in _POWER_SOURCES:
                values_p, values_q = sim.dss_wrapper.get_phase_powers(
                    name, element=spec.dss_class, terminal=spec.terminal
                )
                cache[SOURCE_P] = values_p
                cache[SOURCE_Q] = values_q
                # sum_phases, e não sum: uma fase ausente é NaN, e o embutido
                # contaminaria o total de todo elemento que não é trifásico.
                cache[SOURCE_P_SUM] = [sum_phases(values_p)]
                cache[SOURCE_Q_SUM] = [sum_phases(values_q)]
            elif kind in _LOSS_SOURCES:
                # Perda é do elemento inteiro, não de um terminal: o `terminal`
                # do spec não entra aqui.
                loss_p, loss_q = sim.dss_wrapper.get_phase_losses(name, element=spec.dss_class)
                cache[SOURCE_P_LOSS] = loss_p
                cache[SOURCE_Q_LOSS] = loss_q
                # O total vem do motor, e não da soma das fases: ele conta
                # também o neutro. Ver `get_element_losses`.
                total_p, total_q = sim.dss_wrapper.get_element_losses(name, element=spec.dss_class)
                cache[SOURCE_P_LOSS_SUM] = [total_p]
                cache[SOURCE_Q_LOSS_SUM] = [total_q]
            else:
                mags, angs = sim.dss_wrapper.get_phase_currents(
                    name, element=spec.dss_class, terminal=spec.terminal
                )
                cache[SOURCE_I_MAG] = mags
                cache[SOURCE_I_ANG] = angs
        return cache[kind]

    result: dict[str, Any] = {}
    for attr in attrs:
        mapping = spec.attr_map.get(attr)
        if mapping is None:
            continue
        kind, index, factor = mapping
        result[attr] = normalize_zero(source(kind)[index] * factor)
    return result


def read_bus(sim, name: str, attrs: Iterable[str], spec: ModelSpec) -> dict[str, Any]:
    """Lê tensões de barra; módulo e ângulo vêm de leituras em bloco distintas.

    Só por fase, com :data:`~._utils.ABSENT` na fase que a barra não tem.
    Resumir a barra num escalar (mínimo, média, desequilíbrio) fica com quem
    consome — a visualização já faz a sua redução sobre as três fases.
    """
    cache: dict[str, list[float]] = {}
    result: dict[str, Any] = {}

    def source(kind: str) -> list[float]:
        if kind not in cache:
            cache[kind] = (
                sim.dss_wrapper.get_bus_vmag_pu(name)
                if kind == "vmag"
                else sim.dss_wrapper.get_bus_vang(name)
            )
        return cache[kind]

    for attr in attrs:
        mapping = spec.attr_map.get(attr)
        if mapping is None:
            continue
        kind, index, factor = mapping
        result[attr] = source(kind)[index] * factor

    return result


CIRCUIT_OUTPUTS = (
    "converged",
    "iterations",
    "P_mw",
    "Q_mvar",
    "Ploss_mw",
    "Qloss_mvar",
)


def read_circuit(sim, name: str, attrs: Iterable[str], spec: ModelSpec) -> dict[str, Any]:
    """Estado da solução e totais do alimentador inteiro.

    ``converged`` é a razão de este modelo existir. Um passo que parou no limite
    de iterações produz tensões com a mesma aparência das de um passo bom, e sem
    um atributo que o registre não há como o resultado de um estudo de vários
    dias dizer em quais instantes ele não pode ser levado a sério.

    Com ``fail_on_error`` ligado — o padrão — a simulação nem chega aqui: o
    :meth:`~._engine.EngineMixin.run_dss` interrompe. Este modelo serve a quem
    prefere seguir e marcar, o que exige desligar o erro.

    As leituras vêm do motor, não do cache da solução: são escalares de uma
    chamada só. Os totais por classe de ``get_circuit_info`` ficam de fora de
    propósito — as chaves são rótulos com espaço, que não servem de atributo
    mosaik.
    """
    attrs = list(attrs)
    result: dict[str, Any] = {}

    if "converged" in attrs or "iterations" in attrs:
        converged, iterations = sim.dss_wrapper.get_solution_state()
        if "converged" in attrs:
            result["converged"] = converged
        if "iterations" in attrs:
            result["iterations"] = iterations

    if "P_mw" in attrs or "Q_mvar" in attrs:
        p_kw, q_kvar = sim.dss_wrapper.get_circuit_power()
        if "P_mw" in attrs:
            result["P_mw"] = p_kw / 1000.0
        if "Q_mvar" in attrs:
            result["Q_mvar"] = q_kvar / 1000.0

    if "Ploss_mw" in attrs or "Qloss_mvar" in attrs:
        p_loss_kw, q_loss_kvar = sim.dss_wrapper.get_losses()
        if "Ploss_mw" in attrs:
            result["Ploss_mw"] = p_loss_kw / 1000.0
        if "Qloss_mvar" in attrs:
            result["Qloss_mvar"] = q_loss_kvar / 1000.0

    return result


def read_regulator(sim, name: str, attrs: Iterable[str], spec: ModelSpec) -> dict[str, Any]:
    """Lê tensão, corrente e tap de um regulador."""
    wanted = {a for a in attrs if a in ("v_meas", "i_meas", "tap")}
    if not wanted:
        return {}

    info = sim.regulator_map.get(f"RegControl-{name}")
    if info is None:
        return {}

    measurements = sim.dss_wrapper.get_regulator_measurements(info)
    keys = {"v_meas": "v", "i_meas": "i", "tap": "tap"}
    return {attr: measurements[keys[attr]] for attr in wanted}


LINE_LOADING_OUTPUTS = ("Loading1_pct", "Loading2_pct", "Loading3_pct")

# Compartilhado por `Line` e `Switch`: no motor as duas são a mesma classe, e a
# chave lê as mesmas grandezas elétricas que a linha.
#
# As perdas saem em kW/kvar, e o nome diz isso: o sufixo `_w` das potências é
# herdado e não corresponde à unidade que o motor entrega.
LINE_ATTR_MAP = phase_attr_map(
    p=("P1_w", "P2_w", "P3_w"),
    q=("Q1_var", "Q2_var", "Q3_var"),
    i_mag=("I1_A", "I2_A", "I3_A"),
    i_ang=("I1_ang", "I2_ang", "I3_ang"),
    p_loss=("Ploss1_kw", "Ploss2_kw", "Ploss3_kw"),
    q_loss=("Qloss1_kvar", "Qloss2_kvar", "Qloss3_kvar"),
    p_loss_total=("Ploss_kw",),
    q_loss_total=("Qloss_kvar",),
)


def read_line(sim, name: str, attrs: Iterable[str], spec: ModelSpec) -> dict[str, Any]:
    """Lê grandezas por fase mais o carregamento em % da ampacidade da linha.

    Em amperes não dá para dizer se uma linha está folgada ou no limite: 200 A
    são metade da capacidade de um tronco e o dobro da de um ramal. O
    carregamento põe as duas na mesma escala, e é por fase porque é por fase que
    a corrente desequilibra — a fase mais carregada é que decide.

    !!! warning "O denominador costuma ser um padrão do motor"
        Quando o circuito não declara ``normamps`` — nem na linha nem no
        ``LineCode`` —, o OpenDSS usa 400 A para qualquer linha, e é contra esse
        número que a conta é feita. Nenhum dos alimentadores que acompanham o
        projeto declara ampacidade. Ver :meth:`~._reader.ReaderMixin.get_ampacity`.
    """
    attrs = list(attrs)
    result = read_phases(sim, name, attrs, spec)

    wanted = [attr for attr in attrs if attr in LINE_LOADING_OUTPUTS]
    if not wanted:
        return result

    norm_amps, _ = sim.line_ampacity(name)

    # Sem limite conhecido não há em relação a que normalizar. ABSENT diz isso
    # com a mesma convenção da fase que não existe, e mantém a divisão fora do
    # caminho de um denominador zero.
    if norm_amps <= 0:
        result.update(dict.fromkeys(wanted, ABSENT))
        return result

    # Releitura barata: o snapshot do elemento já está em cache desde a chamada
    # de read_phases, e só é invalidado por uma escrita.
    mags, _ = sim.dss_wrapper.get_phase_currents(
        name, element=spec.dss_class, terminal=spec.terminal
    )

    for index, attr in enumerate(LINE_LOADING_OUTPUTS):
        # NaN se propaga sozinho: a fase que a linha não tem continua ausente no
        # carregamento, em vez de virar um zero que pareceria linha descarregada.
        if attr in wanted:
            result[attr] = normalize_zero(100.0 * mags[index] / norm_amps)

    return result


def read_switch(sim, name: str, attrs: Iterable[str], spec: ModelSpec) -> dict[str, Any]:
    """Lê as mesmas grandezas de uma linha, mais o estado da chave.

    ``is_open`` é do elemento, não de um terminal: ver
    :meth:`~._reader.ReaderMixin.get_is_open`. Uma chave aberta continua sendo
    lida — com corrente zero —, e não some da coleta.
    """
    result = read_line(sim, name, attrs, spec)
    if "is_open" in attrs:
        result["is_open"] = sim.dss_wrapper.get_is_open(name, element=spec.dss_class)
    return result


def read_storage(sim, name: str, attrs: Iterable[str], spec: ModelSpec) -> dict[str, Any]:
    """Lê grandezas por fase mais o estado de carga da bateria."""
    result = read_phases(sim, name, attrs, spec)
    if "SoC" in attrs:
        result["SoC"] = sim.dss_wrapper.get_storage_soc(name)
    return result


# Injeção positiva: inverte a convenção do OpenDSS, em que gerar é potência
# negativa. Vale para o attr_map do PVSystem e para as leituras em pu.
PV_SIGN = -1

PV_PU_OUTPUTS = ("P1_pu", "P2_pu", "P3_pu", "P_pu")


def read_pvsystem(sim, name: str, attrs: Iterable[str], spec: ModelSpec) -> dict[str, Any]:
    """Lê grandezas por fase mais a geração normalizada pela placa do inversor.

    Em kW absolutos não existe escala de cor que sirva a um alimentador com
    inversores de tamanhos diferentes — e nem sequer é preciso variar a placa
    para o problema aparecer. No IEEE13 os seis PVs têm os mesmos 1000 kW de
    Pmpp, mas os trifásicos entregam ~333 kW por fase e os monofásicos 1000 kW:
    uma escala calibrada para uns satura nos outros.

    Em pu da própria placa os dois leem ``1.0`` a plena geração, e a faixa passa
    a ser ``0..1`` em qualquer circuito.

    Cada fase é normalizada pela parcela que lhe cabe (``Pmpp / fases``), de
    modo que um PV monofásico a plena geração também marca ``1.0``. As fases que
    o inversor não tem continuam em ``0.0``, como no restante do adaptador.
    """
    attrs = list(attrs)
    result = read_phases(sim, name, attrs, spec)

    wanted = [attr for attr in attrs if attr in PV_PU_OUTPUTS]
    if not wanted:
        return result

    rated, phases = sim.pv_nameplate(name)

    # Um inversor sem placa conhecida não tem em relação a que ser normalizado;
    # devolver 0.0 mantém o atributo presente, sem inventar uma referência.
    if not rated or not phases:
        result.update(dict.fromkeys(wanted, 0.0))
        return result

    # Releitura barata: o snapshot do elemento já está em cache desde a chamada
    # de read_phases, e só é invalidado por uma escrita.
    powers, _ = sim.dss_wrapper.get_phase_powers(
        name, element=spec.dss_class, terminal=spec.terminal
    )
    per_phase = rated / phases

    for attr in wanted:
        if attr == "P_pu":
            result[attr] = normalize_zero(PV_SIGN * sum_phases(powers) / rated)
        else:
            # NaN se propaga sozinho: a fase que o inversor não tem continua
            # ausente em pu, e não vira um zero que pareceria geração nula.
            result[attr] = normalize_zero(PV_SIGN * powers[int(attr[1]) - 1] / per_phase)

    return result


# ----------------------------------------------------------------------
# Escritores
# ----------------------------------------------------------------------


def write_switch(sim, name: str, values: dict[str, Any]) -> None:
    """Abre ou fecha a chave.

    A convenção de terminais — abrir pelo 2, fechar os dois — vive no wrapper,
    em :meth:`~._writer.WriterMixin.set_is_open`.
    """
    if "is_open" in values:
        sim.dss_wrapper.set_is_open(name, open=bool(values["is_open"]), element="Line")


def write_tap(sim, name: str, values: dict[str, Any]) -> None:
    if "tap" in values:
        sim.dss_wrapper.set_tap(name=name, tap=int(values["tap"]))


def reactive_from_pf(p: float, pf: float) -> float:
    """Reativa que acompanha uma ativa *p* sob o fator de potência *pf*.

    ``Q = P · tan(acos(pf))``. A reativa de um inversor não sai da potência
    disponível no painel: sai da folga de kVA do próprio inversor — é por isso
    que se sobredimensiona o inversor em relação ao ``pmpp``. Toda a potência do
    painel vira ativa, e esta função diz o que a acompanha.

    O sinal segue o de *p*, de modo que uma bateria carregando (ativa negativa)
    também absorva reativa.

    Args:
        p: Potência ativa, em kW.
        pf: Fator de potência declarado, em ``(0, 1]``.

    Returns:
        Potência reativa, em kvar. Zero para ``pf`` unitário ou fora da faixa
        válida — um ``pf`` que o circuito não declarou não inventa reativa.
    """
    if not 0.0 < pf < 1.0:
        return 0.0
    return p * math.tan(math.acos(pf))


def _single_source(values: dict[str, Any], multiplier: str, absolutes: tuple[str, ...]) -> None:
    """Recusa o elemento comandado ao mesmo tempo por multiplicador e por potência.

    Os dois caminhos declaram a mesma grandeza de formas diferentes, e aplicar
    um significa descartar o outro. Num estudo longo, o que sobra é uma potência
    que ninguém pediu.

    Raises:
        ValueError: Se *multiplier* chegar junto de qualquer um de *absolutes*.
    """
    if multiplier not in values:
        return

    conflitos = [attr for attr in absolutes if attr in values]
    if conflitos:
        raise ValueError(
            f"{multiplier} chegou junto de {', '.join(conflitos)}. O multiplicador "
            "deriva a potência da placa do elemento, e os dois caminhos comandam a "
            "mesma grandeza: conecte só um deles a este elemento."
        )


def write_storage(sim, name: str, values: dict[str, Any]) -> None:
    """Aplica setpoints de potência e, se enviado, força o estado de carga.

    Aceita dois caminhos, nunca os dois juntos: ``P_set``/``Q_set`` em kW e
    kvar absolutos, ou ``P_mult``, um multiplicador de -1 a 1 sobre a potência
    nominal — negativo carrega, positivo descarrega. A reativa que acompanha o
    multiplicador vem do ``pf`` declarado.

    ``SoC_set`` existe para o padrão em que um modelo de bateria externo é dono
    da física e o elemento do OpenDSS apenas espelha o estado dele.
    """
    _single_source(values, "P_mult", ("P_set", "Q_set"))

    if "P_mult" in values:
        info = sim.storage_map.get(f"Storage-{name}", {})
        p = values["P_mult"] * info.get("kw_rated", 0.0)
        sim.dss_wrapper.set_power(
            name,
            p=p,
            q=reactive_from_pf(p, sim.power_factor("Storage", name)),
            element="Storage",
        )
    elif "P_set" in values or "Q_set" in values:
        sim.dss_wrapper.set_power(
            name,
            p=values.get("P_set"),
            q=values.get("Q_set"),
            element="Storage",
        )

    if "SoC_set" in values:
        sim.dss_wrapper.set_storage_soc(name, values["SoC_set"])


def write_pvsystem(sim, name: str, values: dict[str, Any]) -> None:
    """Aplica a geração comandada, por potência absoluta ou por multiplicador.

    ``P_des``/``Q_des`` chegam em kW e kvar — o caminho de um simulador de
    inversor. ``P_mult`` é um multiplicador de 0 a 1 sobre o ``pmpp`` da placa:
    toda a potência do painel vira ativa, e a reativa sai do ``pf`` declarado.
    Os dois caminhos são exclusivos.
    """
    _single_source(values, "P_mult", ("P_des", "Q_des"))

    if "P_mult" in values:
        rated, _ = sim.pv_nameplate(name)
        p = values["P_mult"] * rated
        pf = sim.power_factor("PVSystem", name)
        sim.dss_wrapper.set_pvsystem_pq(name, p, reactive_from_pf(p, pf))
        return

    sim.dss_wrapper.set_pvsystem_pq(
        name,
        values.get("P_des", 0.0),
        values.get("Q_des", 0.0),
    )


def write_generator(sim, name: str, values: dict[str, Any]) -> None:
    """Aplica o despacho do gerador, por potência absoluta ou por multiplicador.

    ``P_set``/``Q_set`` chegam em kW e kvar. Sem ``Q_set``, a reativa acompanha
    a ativa pelo ``pf`` declarado — calculada da placa, e não do estado do
    motor, que guardaria o ``Q_set`` de um passo anterior. ``Q_set`` sozinho
    ajusta só a reativa.

    ``P_mult`` é um multiplicador de 0 a 1 sobre o ``kW`` da placa, e escala o
    ``kvar`` pelo mesmo fator, como na carga. Daria o mesmo que
    :func:`reactive_from_pf` para ``pf`` atrasado, mas o gerador também aceita
    ``pf`` adiantado — negativo, com ``kvar`` negativo —, que aquela função
    zeraria. Os dois caminhos são exclusivos.

    A placa vem de :meth:`~.api_opendss.OpenDSSSimulator.generator_nameplate`,
    e não do motor: depois do primeiro despacho o ``kW`` corrente é o comandado.
    """
    _single_source(values, "P_mult", ("P_set", "Q_set"))
    kw, kvar = sim.generator_nameplate(name)

    if "P_mult" in values:
        mult = values["P_mult"]
        p, q = mult * kw, mult * kvar
    elif "P_set" in values:
        p = values["P_set"]
        q = values["Q_set"] if "Q_set" in values else (p * kvar / kw if kw else 0.0)
    else:
        p, q = None, values["Q_set"]

    sim.dss_wrapper.set_power(name, p=p, q=q, element="Generator")


def write_load(sim, name: str, values: dict[str, Any]) -> None:
    """Move a carga por P_kw / Q_kvar diretos ou por multiplicador S_mult.

    P_kw e Q_kvar comandam a potência ativa e reativa da carga diretamente
    (por exemplo, para cargas controladas como veículos elétricos).

    S_mult escala ativamente e reativamente pelo mesmo fator sobre a potência
    nominal, preservando o fator de potência da carga: escalar a potência
    aparente a ``pf`` constante é essa mesma conta.

    A placa vem de :meth:`~.api_opendss.OpenDSSSimulator.load_nameplate`, e não
    do motor: o laço de ``LoadShape`` reescreve a potência da carga a cada
    passo, então o valor corrente é o do perfil.
    """
    if "P_kw" in values or "Q_kvar" in values:
        sim.dss_wrapper.set_power(
            name,
            p=values.get("P_kw"),
            q=values.get("Q_kvar"),
            element="Load",
        )
        return

    if "S_mult" not in values:
        return

    kw, kvar = sim.load_nameplate(name)
    mult = values["S_mult"]
    sim.dss_wrapper.set_power(name, p=mult * kw, q=mult * kvar, element="Load")


# ----------------------------------------------------------------------
# Registry
# ----------------------------------------------------------------------

MODEL_SPECS: dict[str, ModelSpec] = {
    "Circuit": ModelSpec(
        # Como o Bus, não é um elemento de circuito: é o circuito inteiro.
        dss_class=None,
        reader=read_circuit,
        extra_outputs=CIRCUIT_OUTPUTS,
    ),
    "Bus": ModelSpec(
        dss_class=None,
        reader=read_bus,
        attr_map={
            "V1_pu": ("vmag", 0, 1.0),
            "V2_pu": ("vmag", 1, 1.0),
            "V3_pu": ("vmag", 2, 1.0),
            "V1_ang": ("vang", 0, 1.0),
            "V2_ang": ("vang", 1, 1.0),
            "V3_ang": ("vang", 2, 1.0),
        },
    ),
    "Load": ModelSpec(
        dss_class="Load",
        reader=read_phases,
        writer=write_load,
        # Suporta multiplicador da placa (S_mult) ou potências ativas/reativas diretas (P_kw, Q_kvar).
        # Uma carga que recebe inputs num passo não é tocada pelo laço de LoadShape naquele passo.
        inputs={
            "S_mult": InputSpec(aggregator=single_value, bounds=(0.0, 1.0)),
            "P_kw": InputSpec(),
            "Q_kvar": InputSpec(),
        },
        # Convenção do OpenDSS: carga consome com sinal positivo.
        attr_map=phase_attr_map(
            p_total=("P_out_mw",),
            q_total=("Q_out_mvar",),
            scale=1 / 1000.0,
        ),
    ),
    "Line": ModelSpec(
        dss_class="Line",
        reader=read_line,
        attr_map=LINE_ATTR_MAP,
        # Corrente em % da ampacidade da linha. Ver read_line.
        extra_outputs=LINE_LOADING_OUTPUTS,
    ),
    "Switch": ModelSpec(
        # No motor a chave continua sendo uma Line: é o mesmo elemento, com a
        # propriedade `switch=yes`. Só o mosaik as separa.
        dss_class="Line",
        reader=read_switch,
        writer=write_switch,
        inputs={"is_open": InputSpec(aggregator=single_value)},
        # Eletricamente é uma linha, e lê as mesmas grandezas: fechada, conduz a
        # corrente inteira do trecho, e o carregamento dela contra a ampacidade
        # continua valendo.
        attr_map=LINE_ATTR_MAP,
        extra_outputs=("is_open", *LINE_LOADING_OUTPUTS),
    ),
    "Transformer": ModelSpec(
        dss_class="Transformer",
        reader=read_phases,
        # Terminal 1 (enrolamento primário): é o lado por onde a potência entra,
        # então o sinal segue a mesma convenção das linhas.
        #
        # Os nomes trazem a unidade real (kW/kvar, como o OpenDSS reporta), ao
        # contrário do sufixo `_w` herdado pela Line.
        attr_map=phase_attr_map(
            p=("P1_kw", "P2_kw", "P3_kw"),
            q=("Q1_kvar", "Q2_kvar", "Q3_kvar"),
            i_mag=("I1_A", "I2_A", "I3_A"),
            i_ang=("I1_ang", "I2_ang", "I3_ang"),
            p_total=("P_total_kw",),
            q_total=("Q_total_kvar",),
            # Perda do transformador inteiro (cobre + ferro), e não de um
            # enrolamento: é o que sobra entre os dois lados.
            p_loss=("Ploss1_kw", "Ploss2_kw", "Ploss3_kw"),
            q_loss=("Qloss1_kvar", "Qloss2_kvar", "Qloss3_kvar"),
            p_loss_total=("Ploss_kw",),
            q_loss_total=("Qloss_kvar",),
        ),
    ),
    "RegControl": ModelSpec(
        dss_class="RegControl",
        reader=read_regulator,
        writer=write_tap,
        inputs={"tap": InputSpec(aggregator=single_value)},
        extra_outputs=("tap", "v_meas", "i_meas"),
    ),
    "Storage": ModelSpec(
        dss_class="Storage",
        reader=read_storage,
        writer=write_storage,
        public=True,
        inputs={
            "P_set": InputSpec(),
            "Q_set": InputSpec(),
            "SoC_set": InputSpec(aggregator=single_value),
            # O único dos três que carrega e descarrega, daí a faixa negativa.
            "P_mult": InputSpec(aggregator=single_value, bounds=(-1.0, 1.0)),
        },
        # sign=-1: injeção na rede é positiva para o cenário.
        attr_map=phase_attr_map(
            p=("P1", "P2", "P3"),
            q=("Q1", "Q2", "Q3"),
            i_mag=("I1_A", "I2_A", "I3_A"),
            p_total=("P_act",),
            q_total=("Q_act",),
            sign=-1,
        ),
        extra_outputs=("SoC",),
    ),
    "PVSystem": ModelSpec(
        dss_class="PVSystem",
        reader=read_pvsystem,
        writer=write_pvsystem,
        public=True,
        inputs={
            "P_des": InputSpec(),
            "Q_des": InputSpec(),
            "P_mult": InputSpec(aggregator=single_value, bounds=(0.0, 1.0)),
        },
        attr_map=phase_attr_map(
            p=("P1", "P2", "P3"),
            q=("Q1", "Q2", "Q3"),
            i_mag=("I1_A", "I2_A", "I3_A"),
            p_total=("P_meas",),
            q_total=("Q_meas",),
            sign=PV_SIGN,
        ),
        # Geração em pu da placa: comparável entre inversores de tamanhos e
        # números de fase diferentes. Ver read_pvsystem.
        extra_outputs=PV_PU_OUTPUTS,
    ),
    "Generator": ModelSpec(
        dss_class="Generator",
        reader=read_phases,
        writer=write_generator,
        public=True,
        inputs={
            "P_set": InputSpec(),
            "Q_set": InputSpec(),
            # Multiplicador do kW da placa; o kvar segue pelo mesmo fator.
            "P_mult": InputSpec(aggregator=single_value, bounds=(0.0, 1.0)),
        },
        # sign=-1: injeção na rede é positiva para o cenário.
        attr_map=phase_attr_map(
            p=("P1", "P2", "P3"),
            q=("Q1", "Q2", "Q3"),
            i_mag=("I1_A", "I2_A", "I3_A"),
            p_total=("P_meas",),
            q_total=("Q_meas",),
            sign=-1,
        ),
    ),
}


def build_meta() -> dict[str, Any]:
    """Gera a META do mosaik a partir do registry.

    Derivar em vez de escrever à mão é o que impede a META de declarar
    atributos que o simulador não produz.
    """
    models: dict[str, Any] = {
        "Grid": {
            "public": True,
            "params": [
                "topofile",
                "step_size",
                "output_graph_path",
                "buscoords",
                "tolerance",
                "max_iterations",
                "fail_on_error",
            ],
            "attrs": [],
        }
    }
    for model, spec in MODEL_SPECS.items():
        models[model] = {
            "public": spec.public,
            "params": list(spec.params),
            "attrs": spec.attrs,
        }

    return {
        "api_version": "3.0",
        "type": "time-based",
        "models": models,
        "extra_methods": [
            "get_dss_wrapper",
            "get_extra_info",
            "get_detected_regulators",
            "get_detected_pvsystems",
            "get_detected_storages",
            "get_detected_generators",
            "get_detected_transformers",
            "get_detected_switches",
            "get_bus_positions",
        ],
    }
