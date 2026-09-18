"""Configuracao do caso: rede, concentradores e dispositivos de armazenamento.

Le o `force.json` (topologia, ja convertido para OpenDSS na Fase 1) e o
`config.json` do trabalho original (alocacao de RED por no) e monta as
estruturas que os modelos de otimizacao consomem.

Papeis, na nomenclatura da tese (subsecao 6.1.2):
  AP  Agente Prosumidor      -> um por no de baixa tensao
  AC  Agente Concentrador    -> um por transformador de distribuicao
  AD  Agente DSO             -> um, na subestacao
  AM  Agente Mercado         -> um, coordena a decomposicao dual

Armazenamento: o do PROSUMIDOR e programado pelo proprio prosumidor e o DSO so
o influencia por preco; o de REDE e despachado diretamente pelo DSO como
servico ancilar.
"""

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
# Onde ficam os perfis, o preco e o reservatorio de cenarios. Cada rede de teste
# leva os seus junto do circuito, para ser autocontida; `MARKET_DATA_DIR` aponta
# para essa pasta. Sem a variavel, vale a pasta do proprio pacote, que e a da
# rede da tese.
DATA_DIR = Path(os.environ.get("MARKET_DATA_DIR", PKG_DIR.parent / "data"))
# Dentro do container o pacote e montado fora da arvore do repositorio, entao o
# caminho da rede e parametrizavel.
GRID_DIR = Path(os.environ.get(
    "MARKET_GRID_DIR",
    PKG_DIR.parents[1] / "grid-opentes" / "src" / "data" / "MVLV75"))

PERIODS = 96
DT_H = 0.25

# Limites operacionais da rede (subsecao 6.2.2 da tese).
V_MIN = 0.97
V_MAX = 1.03
# Tolerancia para CONTAR violacao. O otimizador do DSO cola a solucao no limite,
# e sem tolerancia o contador acusa violacao a 1e-13 pu de distancia, que e ruido
# de ponto flutuante. A folga aqui e varias ordens de grandeza menor que o erro
# da propria linearizacao (~1e-4 pu), entao nao esconde violacao real.
V_TOL = 1e-9
# Margem de seguranca aplicada aos limites DENTRO do modelo do DSO. A restricao
# de tensao e linearizada, e o otimizador cola a solucao exatamente no limite: o
# erro da linearizacao (1e-4 a 6e-4 pu, medido na validacao de sensitivity.py)
# vira violacao no fluxo de potencia completo. Sem esta margem, a negociacao
# promete 0,9700 pu e o OpenDSS entrega 0,96924.
#
# NAO existe na tese, que usa a mesma restricao linearizada sem recuo. Aparece
# quando a restricao passa a atuar de fato.
V_BACKOFF = float(os.environ.get("MARKET_V_BACKOFF", "1e-3"))

# Limiar de ACAO da fase de operacao, que pode ser mais rigoroso que o limite.
# O limite regulatorio continua sendo V_MIN e V_MAX: e contra eles que o
# resultado final e contado. Este limiar decide apenas QUANDO o DSO intervem.
# Operar com uma banda mais estreita que a norma e pratica de concessionaria,
# agir antes de violar, e aqui serve para exercitar o mecanismo de operacao sem
# afrouxar a margem da restricao. Padrao igual a V_MIN, isto e, sem rigor extra.
V_ACAO_MIN = float(os.environ.get("MARKET_V_ACAO_MIN", str(V_MIN)))
V_ACAO_MAX = float(os.environ.get("MARKET_V_ACAO_MAX", str(V_MAX)))

# Fator de potencia do armazenamento. A Eq. 6.16 supoe dQ = 0, o que vale para um
# dispositivo que nao mexe em reativo. Um inversor comum, porem, opera com fator
# de potencia constante, e ai o reativo acompanha o ativo e a hipotese passa a
# dominar o erro da restricao: medido no `sensitivity.py`, o erro sobe de 2,6e-5
# para 1,0e-3 pu, quarenta vezes.
#
# `none` (padrao) reproduz a tese exatamente, porque o termo dV/dQ zera. Um
# numero entre 0 e 1 liga o termo com tan(acos(pf)).
_pf = os.environ.get("MARKET_STORAGE_PF", "none")
STORAGE_PF = None if _pf.lower() in ("none", "", "0") else float(_pf)
STORAGE_TAN_PHI = 0.0 if STORAGE_PF is None else math.tan(math.acos(STORAGE_PF))

# Pesos das funcoes objetivo.
CK = 1.0        # concentrador, Eq. 6.25
A_PROSUMER = 0.2   # DSO, peso do armazenamento de prosumidor (p1 no codigo original)
B_NETWORK = 0.8    # DSO, peso do armazenamento de rede    (p2 no codigo original)
D_ENERGY = 0.8     # Dl da Eq. 6.26 (fixo em 0,8 no codigo original)


@dataclass
class Storage:
    node: int
    size_kwh: float
    max_flow_kw: float
    min_soc_kwh: float
    max_soc_kwh: float


@dataclass
class Concentrator:
    name: str
    mv_node: int
    lv_node: int
    kva: float
    nodes: list
    prosumer_storage: list = field(default_factory=list)
    network_storage: list = field(default_factory=list)


@dataclass
class Case:
    lv_nodes: list
    all_nodes: list                 # todos menos a subestacao, na ordem de S
    concentrators: list
    prosumer_storage: dict          # no -> Storage
    network_storage: dict           # no -> Storage

    @property
    def prosumer_storage_nodes(self):
        return sorted(self.prosumer_storage)

    @property
    def network_storage_nodes(self):
        return sorted(self.network_storage)

    @property
    def prosumer_nodes(self):
        """TODOS os nos de baixa tensao sob algum concentrador.

        E quem negocia no mercado, com ou sem bateria: o
        `start_pade_agents.py` do trabalho original cria um `ProsumerAgent` por
        no de baixa tensao. Nao confundir com `prosumer_storage_nodes`, que sao
        os que entram na negociacao de lambda, porque so eles tem programacao de
        armazenamento a acoplar.
        """
        return sorted({n for c in self.concentrators for n in c.nodes})


def _storage(node, params):
    return Storage(node=node,
                   size_kwh=float(params["size"]),
                   max_flow_kw=float(params["max_energy_flow"]),
                   min_soc_kwh=float(params["min_soc"]),
                   max_soc_kwh=float(params["max_soc"]))


def load_case(config_json):
    """Monta o caso a partir do force.json (rede) e do config.json (dispositivos)."""
    force = json.loads((GRID_DIR / "force.json").read_text())
    config = json.loads(Path(config_json).read_text())

    lv_nodes = [n["name"] for n in force["nodes"] if n["voltage_level"] == "low voltage"]
    all_nodes = [n["name"] for n in force["nodes"] if n["name"] != 0]

    prosumer_storage = {int(k): _storage(int(k), v)
                        for k, v in config["devices"]["storage_device"]["params"].items()}
    network_storage = {int(k): _storage(int(k), v)
                       for k, v in config["devices"]["dso_storage_device"]["params"].items()}

    concentrators = []
    for t in force["transformers"]:
        nodes = [n for n in t["nodes"] if n in lv_nodes]
        concentrators.append(Concentrator(
            name=t["name"],
            mv_node=t["source"],
            lv_node=t["target"],
            kva=float(t["power"]),
            nodes=nodes,
            prosumer_storage=[n for n in nodes if n in prosumer_storage],
            network_storage=[n for n in nodes if n in network_storage],
        ))

    # Um no de armazenamento que nao caia sob nenhum transformador ficaria fora
    # da negociacao sem ninguem perceber: o force.json tem casos assim (o
    # trafo_6_55 lista o no 54, que pertence ao trafo_5_35).
    assigned = {n for c in concentrators for n in c.prosumer_storage}
    orphans = set(prosumer_storage) - assigned
    if orphans:
        raise ValueError(f"nos com armazenamento de prosumidor sem concentrador: {sorted(orphans)}")

    return Case(lv_nodes=lv_nodes, all_nodes=all_nodes, concentrators=concentrators,
                prosumer_storage=prosumer_storage, network_storage=network_storage)


def describe(case):
    print(f"{len(case.lv_nodes)} prosumidores em {len(case.concentrators)} concentradores")
    print(f"{len(case.prosumer_storage)} armazenamentos de prosumidor, "
          f"{len(case.network_storage)} de rede")
    for c in case.concentrators:
        print(f"  {c.name:<14} {c.kva:>6.1f} kVA  {len(c.nodes):>2} nos  "
              f"armaz. prosumidor {len(c.prosumer_storage):>2}  rede {len(c.network_storage):>2}")
