"""Constrói o grafo do circuito a partir do modelo OpenDSS.

Tudo aqui é derivado do modelo compilado — quem está ligado a cada barra, quais
elementos série as ligam, quais transformadores um RegControl comanda. O grafo
informa e não classifica: uma barra com carga e PV lista os dois elementos, e
decidir se ela é "de carga" ou "de geração" fica a critério de quem consome o
JSON.

A versão anterior classificava cada barra num ``node_type`` por uma ordem de
precedência própria, e o que perdia a disputa sumia — a carga de uma barra com
PV não aparecia em lugar nenhum.
"""

from .graph_model import (
    NetworkEdge,
    NetworkElement,
    NetworkGraph,
    NetworkNode,
)
from .opendss_bus import get_all_buses_info
from .opendss_regulator import get_all_regulators_info

# Classes cujos elementos entram no grafo, na ordem em que aparecem nele. O
# nome da classe é o ``type`` do elemento: coincide com o modelo mosaik do
# adaptador, e Vsource e Capacitor, que não têm modelo, seguem a mesma regra.
ELEMENT_CLASSES = ("Vsource", "Load", "Capacitor", "PVSystem", "Storage", "Generator")


def parse_bus(bus_reference):
    """Separa a referência de barra do OpenDSS em nome e nós.

    Args:
        bus_reference: Barra como o OpenDSS reporta, com ou sem nós
            (``'671.1.2.3'``, ``'646.2'``, ``'634'``).

    Returns:
        Tupla ``(nome, nós)``. A lista de nós fica vazia quando a barra não
        traz sufixo, caso em que o OpenDSS assume todas as fases do elemento.
        O nome sai como o OpenDSS o reporta; normalizar fica a cargo de quem
        chama, porque só o grafo trabalha em minúsculas.
    """
    name, _, nodes = str(bus_reference or "").partition(".")
    if not nodes:
        return name, []
    return name, [int(n) for n in nodes.split(".") if n.isdigit()]


def resolve_nodes(nodes, phases):
    """Completa os nós implícitos de uma barra sem sufixo.

    ``Bus1=634`` num elemento trifásico significa ``634.1.2.3``; o OpenDSS
    simplesmente omite o sufixo. Sem essa resolução o consumidor receberia uma
    lista vazia e teria de tratar o caso à parte.

    Args:
        nodes: Nós explícitos vindos de :func:`parse_bus`.
        phases: Número de fases do elemento.

    Returns:
        Lista de nós; os ``phases`` primeiros quando não havia sufixo.
    """
    if nodes:
        return nodes
    return list(range(1, max(int(phases or 0), 0) + 1))


def _bus_name(bus_reference):
    """Nome da barra sem sufixo de nós, normalizado para minúsculas."""
    return parse_bus(bus_reference)[0].lower()


# =====================================================
# ELEMENTOS
# =====================================================


def _class_names(dss, dss_class):
    """Nomes dos elementos de uma classe, sem o prefixo da classe.

    Enumera pela classe ativa, e não pelas interfaces tipadas: a de Storage não
    é confiável nesta versão do ``py_dss_interface``, e Vsource e Capacitor
    ficam no mesmo caminho das demais.

    Args:
        dss: Instância ativa de ``py_dss_interface.DSS``.
        dss_class: Classe do OpenDSS (``"Load"``, ``"Storage"``...).

    Returns:
        Lista de nomes, vazia quando o circuito não tem elementos da classe.
    """
    dss.circuit.set_active_class(dss_class)

    if dss.active_class.count == 0:
        return []

    # Classe vazia volta como ['None'], uma string, e não como lista vazia.
    names = dss.active_class.names
    if not names or names[0] is None or str(names[0]).lower() == "none":
        return []

    return [str(name).split(".")[-1] for name in names]


def _element_at_active(dss, name, element_type):
    """Monta o :class:`NetworkElement` do elemento já ativo no circuito."""
    bus_name, nodes = parse_bus(dss.cktelement.bus_names[0])
    phases = dss.cktelement.num_phases

    return NetworkElement(
        type=element_type,
        name=name,
        bus=bus_name.lower(),
        nodes=resolve_nodes(nodes, phases),
        phases=phases,
    )


def collect_elements(dss):
    """Um elemento por instância habilitada de cada classe de :data:`ELEMENT_CLASSES`.

    O que fica numa barra só aparece aqui: a fonte, as cargas, os capacitores e
    a geração distribuída. Três PVs monofásicos numa barra trifásica são três
    elementos, cada um com a sua fase.

    Args:
        dss: Instância ativa de ``py_dss_interface.DSS``.

    Returns:
        Lista de :class:`~.graph_model.NetworkElement`, agrupada por classe na
        ordem de :data:`ELEMENT_CLASSES`.
    """
    elements = []

    for dss_class in ELEMENT_CLASSES:
        for name in _class_names(dss, dss_class):
            dss.circuit.set_active_element(f"{dss_class}.{name}")
            if dss.cktelement.is_enabled:
                elements.append(_element_at_active(dss, name, dss_class))

    return elements


def add_elements(graph, elements):
    """Adiciona os elementos coletados ao grafo."""
    for element in elements:
        graph.add_element(element)


def collect_regcontrols(dss):
    """RegControls agrupados pelo transformador que comandam.

    Substitui a antiga classificação ``regulator_bus``: em vez de marcar a
    barra, o grafo diz qual transformador é regulado e qual barra o controle
    regula — a do enrolamento declarado no RegControl.

    Args:
        dss: Instância ativa de ``py_dss_interface.DSS``.

    Returns:
        Mapa do nome do transformador, em minúsculas, para a lista de
        ``{"name", "bus"}`` dos RegControls que o comandam.
    """
    by_transformer = {}

    for info in get_all_regulators_info(dss):
        by_transformer.setdefault(info["trafo"].lower(), []).append(
            {"name": info["name"], "bus": info["target_bus"].lower()}
        )

    return by_transformer


# =====================================================
# NÓS
# =====================================================


def add_nodes(graph, dss):
    """Adiciona uma entrada por barra, com tensão base, nós e coordenadas.

    Args:
        graph: Grafo em construção.
        dss: Instância ativa de ``py_dss_interface.DSS``.
    """
    for bus, info in get_all_buses_info(dss).items():
        # Sem coordenada no BusCoords, o OpenDSS reporta (0, 0). Esse zero não é
        # uma posição, e quem desenhasse a barra ali a poria na origem.
        has_coords = info["coord_defined"]

        graph.add_node(
            NetworkNode(
                name=_bus_name(bus),
                kv_base=info["kv_base"],
                nodes=info["nodes"],
                x=info["x"] if has_coords else None,
                y=info["y"] if has_coords else None,
            )
        )


# =====================================================
# ARESTAS
# =====================================================


def _is_open(dss) -> bool:
    """Se o elemento ativo está aberto em algum terminal.

    Espelha :meth:`~._reader.ReaderMixin.get_is_open`, que não pode ser usado
    aqui: este módulo fala direto com o motor, sem o wrapper.
    """
    return any(
        bool(dss.cktelement.is_terminal_open(terminal))
        for terminal in range(1, dss.cktelement.num_terminals + 1)
    )


def _is_switch(dss) -> bool:
    """Se a linha ativa foi declarada com ``switch=yes``.

    Espelha :meth:`~._reader.ReaderMixin.get_property`, pelo mesmo motivo de
    :func:`_is_open`. O motor normaliza o valor para ``"True"``/``"False"``,
    seja qual for a forma declarada no ``.dss``.
    """
    properties = [name.lower() for name in dss.dsselement.property_names]
    if "switch" not in properties:
        return False
    return dss.dssproperties.value_read(str(properties.index("switch") + 1)) == "True"


def _add_element_edges(graph, dss, iterator, type_of, regcontrols=None):
    """Adiciona uma aresta por elemento habilitado de uma classe.

    A identidade da aresta é o **nome do elemento**, não o par de barras. Usar o
    par fazia elementos em paralelo colidirem e se sobrescreverem: os três
    reguladores de fase do IEEE13 ligam ``650`` a ``rg60`` e viravam uma aresta
    só, perdendo dois.

    Args:
        graph: Grafo em construção.
        dss: Instância ativa de ``py_dss_interface.DSS``.
        iterator: Interface tipada da classe.
        type_of: Função que recebe ``dss``, com o elemento ativo, e devolve o
            ``type`` da aresta.
        regcontrols: Saída de :func:`collect_regcontrols`, para as classes que
            podem ser reguladas.
    """
    regcontrols = regcontrols or {}

    if not iterator.count:
        return

    index = iterator.first()
    while index > 0:
        if not dss.cktelement.is_enabled:
            index = iterator.next()
            continue

        bus_names = dss.cktelement.bus_names
        if len(bus_names) >= 2:
            bus1 = _bus_name(bus_names[0])
            bus2 = _bus_name(bus_names[1])

            if bus1 != bus2:
                name = iterator.name
                graph.add_edge(
                    NetworkEdge(
                        type=type_of(dss),
                        name=name,
                        source=bus1,
                        target=bus2,
                        phases=dss.cktelement.num_phases,
                        # Uma chave aberta continua existindo fisicamente,
                        # mas não conduz: o consumidor pode desenhá-la
                        # tracejada em vez de a aresta sumir do grafo.
                        #
                        # Os dois terminais entram na conta. Olhar só o
                        # primeiro dava as chaves normalmente abertas do
                        # IEEE123 como fechadas, porque o circuito as abre
                        # pelo terminal 2 (`open Line.Sw7 terminal=2`).
                        open=_is_open(dss),
                        regcontrols=regcontrols.get(name.lower(), []),
                    )
                )

        index = iterator.next()


def add_line_edges(graph, dss):
    """Adiciona uma aresta por linha habilitada, com as chaves à parte.

    No OpenDSS chave e linha são a mesma classe ``Line``; o adaptador as separa
    nos modelos ``Line`` e ``Switch`` pela propriedade ``switch``, e o grafo usa
    a mesma divisão.
    """
    _add_element_edges(graph, dss, dss.lines, lambda d: "Switch" if _is_switch(d) else "Line")


def add_transformer_edges(graph, dss, regcontrols):
    """Adiciona uma aresta por transformador habilitado, com seus RegControls."""
    _add_element_edges(graph, dss, dss.transformers, lambda d: "Transformer", regcontrols)


# =====================================================
# BUILD
# =====================================================


def build_graph(dss):
    """Monta o grafo do circuito compilado.

    Args:
        dss: Instância ativa de ``py_dss_interface.DSS``.

    Returns:
        :class:`~.graph_model.NetworkGraph` com uma barra por nó, um elemento
        série por aresta e um elemento por instância de :data:`ELEMENT_CLASSES`.
    """
    graph = NetworkGraph()

    # A coleta mexe no elemento ativo do circuito e a montagem dos nós mexe na
    # barra ativa; varrer tudo antes de construir evita que um passo reponha o
    # estado de que o outro depende.
    elements = collect_elements(dss)
    regcontrols = collect_regcontrols(dss)

    add_nodes(graph, dss)
    add_elements(graph, elements)
    add_line_edges(graph, dss)
    add_transformer_edges(graph, dss, regcontrols)

    return graph
