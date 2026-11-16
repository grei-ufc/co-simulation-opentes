"""Modelo de dados do grafo do circuito e seu formato JSON.

O grafo só informa o que o modelo compilado declara: as barras, os elementos
série que as ligam e os elementos pendurados em cada uma. Não classifica barra
nenhuma — uma barra com carga e PV lista os dois elementos, e decidir o que ela
"é" fica a critério de quem consome o JSON.

Cada dado aparece num lugar só. A identidade de arestas e elementos é o par
``(type, name)``, e ``type`` usa os nomes dos modelos mosaik do adaptador
(``Line``, ``Switch``, ``PVSystem``...): ``f"{type}-{name}"`` é o eid da
entidade, que prefixa as colunas do CSV dos resultados
(``DSS-0.PVSystem-pv-4-P_meas``).
"""

from dataclasses import asdict, dataclass, field

# Sobe a cada mudança incompatível do formato. O formato anterior, sem o campo,
# trazia ``node_type`` e o envelope ``metadata``.
SCHEMA_VERSION = 2


@dataclass
class NetworkNode:
    """Barra do circuito.

    ``name`` sai como o OpenDSS lista as barras — minúsculas, sem sufixo de
    nós —, e é por ele que arestas e elementos referenciam a barra.
    ``x``/``y`` ficam ``None`` quando a barra não consta do ``BusCoords``.
    """

    name: str
    kv_base: float
    nodes: list[int]
    x: float | None = None
    y: float | None = None


@dataclass
class NetworkEdge:
    """Elemento série que liga duas barras (Line, Switch, Transformer).

    ``regcontrols`` lista os RegControls que comandam o transformador, cada um
    com a barra do enrolamento que regula. É lista porque nada impede dois
    RegControls no mesmo transformador, e vem vazia nas demais arestas.
    """

    type: str
    name: str

    source: str
    target: str

    phases: int
    open: bool

    regcontrols: list[dict] = field(default_factory=list)


@dataclass
class NetworkElement:
    """Elemento conectado a uma só barra (Vsource, Load, PVSystem...).

    Enquanto :class:`NetworkEdge` liga duas barras, um elemento pendura-se numa
    só. ``bus`` segue a normalização de :attr:`NetworkNode.name`, para que o
    vínculo elemento/barra seja um join direto. ``phases`` e ``nodes`` não se
    repetem: uma carga monofásica em delta tem uma fase e dois nós.
    """

    type: str
    name: str

    bus: str
    nodes: list[int] = field(default_factory=list)
    phases: int = 0


class NetworkGraph:
    """Barras indexadas por ``name``; arestas e elementos por ``(type, name)``."""

    def __init__(self):

        self.nodes = {}
        self.edges = {}
        self.elements = {}

    def add_node(self, node):

        self.nodes[node.name] = node

    def add_edge(self, edge):

        self.edges[(edge.type, edge.name)] = edge

    def add_element(self, element):

        self.elements[(element.type, element.name)] = element

    @property
    def total_nodes(self):

        return len(self.nodes)

    @property
    def total_edges(self):

        return len(self.edges)

    @property
    def total_elements(self):

        return len(self.elements)


def serialize_graph(graph):
    """Converte o grafo para o dicionário consumido pela visualização.

    Os três mapas viram vetores: as chaves dos mapas repetiriam campos que cada
    item já traz. Única fonte do formato — o wrapper e o script
    ``util/topologia`` serializam pelo mesmo caminho.

    Args:
        graph: :class:`NetworkGraph` montado.

    Returns:
        Dicionário com as chaves ``version``, ``nodes``, ``edges`` e
        ``elements``.
    """
    return {
        "version": SCHEMA_VERSION,
        "nodes": [asdict(node) for node in graph.nodes.values()],
        "edges": [asdict(edge) for edge in graph.edges.values()],
        "elements": [asdict(element) for element in graph.elements.values()],
    }
