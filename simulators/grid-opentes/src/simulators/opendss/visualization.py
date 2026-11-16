"""Visualização web pronta para os modelos do adaptador OpenDSS.

Liga o simulador ``WebVis`` ao grid do OpenDSS numa chamada: configura o que é
desenhado, declara como cada tipo é colorido, conecta as entidades e fixa as
barras nas coordenadas do circuito.

Fica fora de ``simulators/webvis`` de propósito. Aquele diretório é um fork
LGPL-2.1 do mosaik-web e continua sem saber nada de OpenDSS, enquanto os
presets daqui dependem dos nomes de atributo deste adaptador. O webvis é usado
só pela sua API mosaik pública (``set_config``, ``set_etypes``, ``Topology``,
``set_node_positions``).
"""

import copy

from mosaik.util import connect_many_to_one

from ..webvis.webvis_sim import etype_attrs

# Como cada modelo do adaptador aparece no desenho. Os limites de cor são pontos
# de partida: recalibre-os por circuito passando um dicionário em `show`.
PRESETS = {
    "Bus": {
        "cls": "pqbus",
        "attrs": ["V1_pu", "V2_pu", "V3_pu"],
        "series": ["A", "B", "C"],
        # A fase mais baixa é a que decide se a barra está em conformidade.
        "aggregate": "min",
        "unit": "V [pu]",
        "default": 1.0,
        "min": 0.90,
        "max": 1.10,
        # Escala do botão "desb": 5% de amplitude entre fases já é muito.
        "spread_max": 0.05,
    },
    "Load": {
        "cls": "load",
        "attrs": ["P_out_mw"],
        "unit": "P [MW]",
        "default": 0,
        "min": 0,
        # Varia muito entre alimentadores (as cargas do IEEE123 vão de 20 a
        # 210 kW nominais): quase sempre vale recalibrar.
        "max": 0.1,
        # Menor que as barras: a carga se pendura na rede, não é um ponto dela.
        "radius": 5,
    },
    "PVSystem": {
        "cls": "gen",
        # Em pu da placa do próprio inversor. A escala é compartilhada por todos
        # os PVs, e em kW um inversor pequeno ficaria verde o dia inteiro ao
        # lado de um grande. Por fase, para responder aos botões A/B/C.
        "attrs": ["P1_pu", "P2_pu", "P3_pu"],
        "series": ["A", "B", "C"],
        "aggregate": "mean",
        "unit": "P [pu da placa]",
        "default": 0,
        "min": 0,
        "max": 1.0,
        "radius": 7,
    },
    "Storage": {
        "cls": "storage",
        # Com min=0 o fundo da escala é verde e o topo vermelho, então bateria
        # cheia aparece vermelha. Para ver carga e descarga, use ["P_act"] com
        # min=-max (kW, positivo = descarregando).
        "attrs": ["SoC"],
        "unit": "SoC [pu]",
        "default": 0,
        "min": 0,
        "max": 1.0,
        "radius": 7,
    },
}

# Sem as cargas: num alimentador grande elas encobrem o traçado. No IEEE123 são
# 91 dos 231 nós, semeados em volta de barras que ficam a ~48 px umas das outras.
# Sem os reguladores: a representação deles no desenho ainda não está definida.
DEFAULT_SHOW = ("Bus", "PVSystem", "Storage")

# Viram arestas entre as barras, em vez de nós.
#
# A chave precisa estar aqui. Um tipo que não esteja nem em `merge_types` nem
# nos `etypes` é removido do grafo, e como a chave é a ponte entre duas barras,
# todo o trecho a jusante dela viraria uma componente solta no layout de forças.
MERGE_TYPES = ["Line", "Transformer", "Switch"]


def resolve_etypes(show):
    """Configuração por tipo a partir de ``show``.

    Args:
        show: Nomes de tipo, resolvidos por :data:`PRESETS`; ou um dicionário
            ``{tipo: configuração}``, usado como está.

    Returns:
        Dicionário ``{tipo: configuração}``, independente dos presets: alterá-lo
        não altera :data:`PRESETS`.

    Raises:
        ValueError: Se um nome não tiver preset.
    """
    if isinstance(show, dict):
        return copy.deepcopy(show)

    unknown = [name for name in show if name not in PRESETS]
    if unknown:
        raise ValueError(
            f"Sem preset para {unknown}. Disponíveis: {sorted(PRESETS)}. "
            "Para um tipo sem preset, passe `show` como dicionário."
        )
    return {name: copy.deepcopy(PRESETS[name]) for name in show}


def attach_webvis(world, dss_sim, grid, webvis, show=DEFAULT_SHOW, timeline_hours=24):
    """Desenha o grid do OpenDSS no navegador.

    Só o que está em ``show`` aparece. O resto da simulação (controladores,
    inversores, coletores de dados) fica de fora sem precisar ser listado.

    Args:
        world: O ``mosaik.World`` da simulação.
        dss_sim: Simulador OpenDSS, de ``world.start("DSS", ...)``.
        grid: Entidade ``Grid`` criada por ele.
        webvis: Simulador ``WebVis``, de ``world.start("WebVis", ...)``.
        show: O que desenhar; ver :func:`resolve_etypes`.
        timeline_hours: Janela da linha do tempo aberta ao clicar num nó.

    Returns:
        A entidade ``Topology`` do webvis.
    """
    etypes = resolve_etypes(show)
    children = list(grid.children)

    webvis.set_config(merge_types=MERGE_TYPES, timeline_hours=timeline_hours)
    webvis.set_etypes(etypes)
    topology = webvis.Topology()

    for model_type, conf in etypes.items():
        entities = [e for e in children if e.type == model_type]
        attrs = etype_attrs(conf)
        # Um tipo sem entidade neste circuito (Storage num alimentador sem
        # bateria) simplesmente não aparece; não é erro.
        if not entities or not attrs:
            continue
        connect_many_to_one(world, entities, topology, *attrs)
        print(f"{len(entities):>3} {model_type} conectadas à visualização")

    positions = dss_sim.get_bus_positions()
    known = {e.full_id: positions[e.eid] for e in children if e.eid in positions}
    webvis.set_node_positions(known)
    print(f"{len(known):>3} barras com coordenada real (as demais ficam no layout de forças)")

    return topology
