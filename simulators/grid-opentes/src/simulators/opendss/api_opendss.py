import copy
import datetime
import math

import mosaik_api_v3

from .element_specs import MODEL_SPECS, build_meta
from .opendss_wrapper import OpenDSS, OpenDSSException

# O grafo da topologia faz a mesma leitura de barras que o adaptador; as duas
# resoluções vivem no builder para não divergirem.
from .topology_builder import parse_bus as _parse_bus
from .topology_builder import resolve_nodes as _resolve_nodes


def _as_float(value, default=0.0):
    """Converte uma propriedade DSS (sempre string) para float, com fallback."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value, default=0):
    """Converte uma propriedade DSS (sempre string) para int, com fallback."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


# O motor normaliza a propriedade lida para "True"/"False", mas o circuito pode
# tê-la declarado como `switch=y` (IEEE13) ou `switch=yes` (IEEE123).
_TRUTHY = frozenset({"true", "yes", "y", "1"})


def _as_bool(value):
    """Converte uma propriedade DSS (sempre string) para bool."""
    return str(value).strip().lower() in _TRUTHY


# A META e derivada do registry em element_specs.py, nao escrita a mao:
# assim ela nao pode declarar um atributo que o simulador nao implementa.
META = build_meta()


class OpenDSSSimulator(mosaik_api_v3.Simulator):
    def __init__(self):
        super().__init__(META)
        self.sid = None
        self.dss_wrapper = None
        self.step_size = None
        self.entity_map = {}
        self.profiles = {}
        self.shape_data_cache = {}
        self.time_resolution = 1.0

        self._children = []
        self._extra_info = {}
        self._eids_by_type = {}
        self._type_by_eid = {}
        self._bus_eids = {}
        self._pv_nameplate = {}
        self._line_ampacity = {}
        self._load_nameplate = {}
        self._generator_nameplate = {}
        self._power_factor = {}

    # ------------------------------------------------------------------
    # Metadados das entidades
    # ------------------------------------------------------------------

    def get_extra_info(self):
        """Metadados estáticos de cada entidade, indexados por eid.

        Em mosaik >= 3.3 os mesmos dados chegam ao cenário direto em
        ``entity.extra_info``; este método dá acesso por eid sem percorrer a
        árvore de filhos.
        """
        return self._extra_info

    def _info_by_type(self, model_type):
        return [self._extra_info[eid] for eid in self._eids_by_type.get(model_type, [])]

    def _map_by_type(self, model_type):
        return {eid: self._extra_info[eid] for eid in self._eids_by_type.get(model_type, [])}

    @property
    def detected_regulators(self):
        return self._info_by_type("RegControl")

    @property
    def detected_pvsystems(self):
        return self._info_by_type("PVSystem")

    @property
    def detected_storages(self):
        return self._info_by_type("Storage")

    @property
    def detected_generators(self):
        return self._info_by_type("Generator")

    @property
    def detected_transformers(self):
        return self._info_by_type("Transformer")

    @property
    def detected_switches(self):
        return self._info_by_type("Switch")

    @property
    def regulator_map(self):
        return self._map_by_type("RegControl")

    @property
    def pvsystem_map(self):
        return self._map_by_type("PVSystem")

    def pv_nameplate(self, name):
        """Placa de um PVSystem: ``(Pmpp em kW, número de fases)``.

        Guardada na criação das entidades porque não dá para relê-la do motor
        depois: :func:`~.element_specs.write_pvsystem` reescreve o ``pmpp`` do
        elemento a cada passo com o setpoint recebido, então o valor corrente é
        a geração comandada, e não a capacidade do inversor.

        Args:
            name: Nome do PVSystem no OpenDSS.

        Returns:
            Tupla ``(pmpp, fases)``, ou ``(0.0, 0)`` se o nome não for de um
            PVSystem conhecido.
        """
        return self._pv_nameplate.get(name, (0.0, 0))

    def power_factor(self, model_type, name):
        """Fator de potência declarado de um elemento, por nome no OpenDSS.

        Indexado por ``(modelo, nome)``, e não pelo eid: um escritor que
        montasse o eid à mão erraria em silêncio se o formato mudasse — o
        ``pf`` cairia no default e a reativa sairia zerada sem nada acusando.
        Foi o que aconteceu enquanto o eid do PVSystem carregava a barra.

        Args:
            model_type: Nome do modelo mosaik (``'PVSystem'``, ``'Storage'``).
            name: Nome do elemento no OpenDSS.

        Returns:
            O fator de potência, ou ``1.0`` se o elemento não for conhecido —
            um ``pf`` que ninguém declarou não inventa reativa.
        """
        return self._power_factor.get((model_type, name), 1.0)

    def load_nameplate(self, name):
        """Potência nominal de uma carga: ``(kW, kvar)``.

        Guardada na criação porque não dá para relê-la do motor depois: o laço
        de ``LoadShape`` em :meth:`step` reescreve o ``kW`` e o ``kvar`` da
        carga a cada passo, então o valor corrente é o do perfil, e não a placa.
        Mesma razão de :meth:`pv_nameplate`.

        É contra ela que o multiplicador ``S_mult`` incide. Escalar os dois pelo
        mesmo fator preserva o fator de potência declarado — escalar a potência
        aparente a ``pf`` constante é a mesma conta.

        Args:
            name: Nome da carga no OpenDSS.

        Returns:
            Tupla ``(kw, kvar)``, ou ``(0.0, 0.0)`` se o nome não for de uma
            carga conhecida.
        """
        return self._load_nameplate.get(name, (0.0, 0.0))

    def generator_nameplate(self, name):
        """Potência nominal de um gerador: ``(kW, kvar)``.

        Guardada na criação pela mesma razão de :meth:`load_nameplate`: o
        despacho e o laço de curvas em :meth:`step` reescrevem o ``kW`` e o
        ``kvar`` do elemento, então o valor corrente é o comandado. É contra ela
        que ``P_mult`` incide, e dela que sai a reativa de um ``P_set`` sem
        ``Q_set``.

        Args:
            name: Nome do gerador no OpenDSS.

        Returns:
            Tupla ``(kw, kvar)``, ou ``(0.0, 0.0)`` se o nome não for de um
            gerador conhecido.
        """
        return self._generator_nameplate.get(name, (0.0, 0.0))

    def line_ampacity(self, name):
        """Limites de corrente de uma linha: ``(normal, emergencial)`` em A.

        Lida uma vez na criação das entidades porque é dado do circuito
        compilado, não da solução: relê-la a cada passo custaria uma ida ao
        motor por linha para devolver sempre o mesmo número.

        Args:
            name: Nome da linha no OpenDSS.

        Returns:
            Tupla ``(normal, emergencial)``, ou ``(0.0, 0.0)`` se o nome não for
            de uma linha conhecida.
        """
        return self._line_ampacity.get(name, (0.0, 0.0))

    @property
    def storage_map(self):
        return self._map_by_type("Storage")

    @property
    def generator_map(self):
        return self._map_by_type("Generator")

    def init(
        self,
        sid,
        time_resolution,
        topofile,
        step_size=900,
        output_graph_path=None,
        buscoords=None,
        tolerance=None,
        max_iterations=None,
        fail_on_error=True,
        **sim_params,
    ):
        """Inicializa o simulador e compila o circuito.

        Na compilação, os PVSystems trocam as curvas de eficiência e de
        derating térmico e os limiares de corte por versões ideais, para que a
        potência comandada seja a injetada. As curvas declaradas continuam em
        ``extra_info``. Ver :func:`~.opendss_pv.idealize_pvsystems`.

        Args:
            sid: Identificador do simulador no mosaik.
            time_resolution: Resolução temporal do mosaik.
            topofile: Arquivo ``.dss`` do circuito. Um simulador atende a um
                único circuito: o motor OpenDSS é compartilhado por todo o
                processo, então um segundo circuito substituiria o primeiro.
            step_size: Passo de simulação, em segundos.
            output_graph_path: Se informado, exporta o grafo do circuito.
            buscoords: Arquivo de coordenadas das barras (``Buscoords``) a
                carregar depois do circuito. Vários alimentadores do IEEE trazem
                o arquivo mas não o carregam no ``.dss`` principal; sem ele as
                coordenadas em ``extra_info`` ficam todas em zero.
            tolerance: Critério de convergência do fluxo. ``None`` mantém o
                padrão do motor (``1e-4``), folgado para co-simulação.
            max_iterations: Limite de iterações. ``None`` mantém o padrão do
                motor (``15``), que não basta para um salto grande de ponto de
                operação — o primeiro passo depois do setup, ou uma manobra de
                chave. O modelo ``Circuit`` reporta ``converged`` e
                ``iterations`` de cada passo.
            fail_on_error: Com ``True`` (padrão), um erro do motor — comando
                recusado, fluxo que não convergiu — interrompe a simulação. Com
                ``False`` ele só é impresso, e a simulação segue: é o caminho de
                quem prefere não perder a execução inteira por um passo ruim, e
                registra quais passos não convergiram pelo ``converged`` do
                modelo ``Circuit``. Erros de uso — elemento ou propriedade
                inexistente, multiplicador fora da faixa — interrompem de
                qualquer forma.
        """
        self.sid = sid
        self.time_resolution = time_resolution
        self.step_size = step_size
        self.dss_wrapper = OpenDSS(
            topofile=topofile,
            time_step=datetime.timedelta(seconds=self.step_size),
            start_time=datetime.datetime(2025, 1, 1),
            tolerance=tolerance,
            max_iterations=max_iterations,
            fail_on_error=fail_on_error,
        )

        if buscoords is not None:
            self.dss_wrapper.load_buscoords(buscoords)

        if output_graph_path is not None:
            self.dss_wrapper.grafo_tsdq(output_graph_path)

        return self.meta

    def create(self, num, model, **model_params):
        if model != "Grid":
            raise ValueError(
                "Use 'Grid' model to initialize the system. Access elements via children."
            )
        if num != 1:
            raise ValueError(f"exactly one Grid entity must be created, got num={num}")
        if self._children:
            raise ValueError("Grid was already created")

        return self._create_grid()

    def setup_done(self):
        """Resolve o fluxo inicial depois de todas as entidades e conexões.

        Sem isso, o primeiro ``get_data`` — o que alimenta as conexões
        ``time_shifted`` com dados iniciais — leria a solução feita durante a
        compilação, antes de qualquer ajuste feito depois dela, na criação das
        entidades ou pelo cenário via ``get_dss_wrapper``.
        """
        self.dss_wrapper.run_dss()

    # ------------------------------------------------------------------
    # Criação de entidades
    # ------------------------------------------------------------------

    def _create_grid(self):
        self._add_circuit()
        # As barras vêm primeiro: são as âncoras que todos os demais
        # elementos referenciam em `rel`.
        self._add_buses()
        self._add_loads()
        self._add_lines()
        self._add_transformers()
        self._add_regulators()
        self._add_storages()
        self._add_pvsystems()
        self._add_generators()

        return [
            {
                "eid": "Grid-0",
                "type": "Grid",
                "children": self._children,
                "rel": [],
            }
        ]

    def _add_child(self, eid, model_type, name, rel=None, extra_info=None):
        """Registra uma entidade filha com sua topologia e seus metadados.

        O ``extra_info`` entregue ao cenário é uma cópia. Compartilhar o objeto
        daria ao cenário local uma referência viva para o estado interno do
        simulador, enquanto um cenário remoto receberia um retrato congelado —
        a mesma escrita produziria resultados diferentes conforme o transporte.

        Args:
            eid: Identificador mosaik da entidade.
            model_type: Nome do modelo declarado na META.
            name: Nome do elemento no OpenDSS.
            rel: eids aos quais a entidade está conectada (barras).
            extra_info: Metadados estáticos expostos ao cenário.
        """
        self.entity_map[eid] = name
        self._extra_info[eid] = extra_info or {}
        self._eids_by_type.setdefault(model_type, []).append(eid)
        self._type_by_eid[eid] = model_type
        self._children.append(
            {
                "eid": eid,
                "type": model_type,
                "rel": rel or [],
                "extra_info": copy.deepcopy(self._extra_info[eid]),
            }
        )

    def _bus_rel(self, bus_string, owner):
        """Resolve a referência de barra de um elemento para o eid da barra.

        O mosaik constrói o grafo de entidades com ``add_edge``, que cria nós
        inexistentes em silêncio — uma referência pendurada corromperia o grafo
        sem erro nenhum. Por isso a resolução é validada aqui.

        Args:
            bus_string: Barra como o OpenDSS reporta (``'671.1.2.3'``).
            owner: eid do elemento, usado só na mensagem de aviso.

        Returns:
            Lista com o eid da barra, ou lista vazia se a barra não existe.
        """
        bus_name, _ = _parse_bus(bus_string)
        eid = self._bus_eids.get(bus_name.lower())

        if eid is None:
            print(
                f"[OpenTES][AVISO] {owner}: barra '{bus_string}' nao esta na lista "
                f"de barras do circuito; a entidade ficara sem topologia (rel)."
            )
            return []

        return [eid]

    def _add_circuit(self):
        """Cria a entidade que representa o circuito inteiro.

        Uma só, sem ``rel``: ela não fica em barra nenhuma. Existe para que o
        cenário possa registrar se cada passo convergiu — ver
        :func:`~.element_specs.read_circuit`.
        """
        summary = self.dss_wrapper.get_circuit_summary()
        self._add_child("Circuit-0", "Circuit", summary["name"], rel=[], extra_info=summary)

    def _add_buses(self):
        for name, info in self.dss_wrapper.get_all_buses_info().items():
            eid = f"Bus-{name}"
            self._bus_eids[name.lower()] = eid

            # As coordenadas ficam cruas, com o flag ao lado: sem ele, uma barra
            # sem coordenada é indistinguível de uma que fica de fato na origem.
            self._add_child(eid, "Bus", name, rel=[], extra_info={"name": name, **info})

    def _add_loads(self):
        loads_df = self.dss_wrapper.get_all_elements("Load")
        if loads_df.empty:
            return

        for full_name, row in loads_df.iterrows():
            name = full_name.split(".")[1]
            eid = f"Load-{name}"
            bus_name, nodes = _parse_bus(row.get("bus1", ""))
            phases = _as_int(row.get("phases"), len(nodes) or 3)
            nodes = _resolve_nodes(nodes, phases)

            # Base do multiplicador `S_mult`; ver load_nameplate().
            kw = _as_float(row.get("kW"))
            kvar = _as_float(row.get("kvar"))
            self._load_nameplate[name] = (kw, kvar)

            self._add_child(
                eid,
                "Load",
                name,
                rel=self._bus_rel(row.get("bus1", ""), eid),
                extra_info={
                    "name": name,
                    "bus": bus_name,
                    "nodes": nodes,
                    "phases": phases,
                    "kv": _as_float(row.get("kV")),
                    "kw": kw,
                    "kvar": kvar,
                    "pf": _as_float(row.get("pf"), 1.0),
                    "conn": row.get("conn", ""),
                },
            )
            self._check_profile(eid, name, "Load", kw, kvar)

    def _add_lines(self):
        """Cria as linhas do circuito, separando as chaves num modelo próprio.

        No OpenDSS os dois são a mesma classe ``Line``; o que os distingue é a
        propriedade ``switch``. Separá-los aqui é o que impede uma chave — trecho
        de impedância desprezível, que existe para manobrar — de entrar nas
        estatísticas de carregamento e perdas das linhas que transportam
        potência de fato.
        """
        lines_df = self.dss_wrapper.get_all_elements("Line")
        if lines_df.empty:
            return

        for full_name, row in lines_df.iterrows():
            name = full_name.split(".")[1]
            # A propriedade vem no DataFrame de propriedades que já foi lido, e
            # o motor a normaliza para "True"/"False" seja qual for a forma
            # declarada no .dss (`switch=y`, `switch=yes`).
            is_switch = _as_bool(row.get("Switch", row.get("switch", "False")))
            model_type = "Switch" if is_switch else "Line"
            eid = f"{model_type}-{name}"
            bus1, nodes1 = _parse_bus(row.get("bus1", ""))
            bus2, nodes2 = _parse_bus(row.get("bus2", ""))
            phases = _as_int(row.get("phases"), len(nodes1) or 3)
            nodes1 = _resolve_nodes(nodes1, phases)
            nodes2 = _resolve_nodes(nodes2, phases)

            # Denominador do carregamento; ver line_ampacity().
            norm_amps, emerg_amps = self.dss_wrapper.get_ampacity(name, "Line")
            self._line_ampacity[name] = (norm_amps, emerg_amps)

            self._add_child(
                eid,
                model_type,
                name,
                rel=(
                    self._bus_rel(row.get("bus1", ""), eid)
                    + self._bus_rel(row.get("bus2", ""), eid)
                ),
                extra_info={
                    "name": name,
                    "bus1": bus1,
                    "bus2": bus2,
                    "nodes1": nodes1,
                    "nodes2": nodes2,
                    "phases": phases,
                    "length": _as_float(row.get("length")),
                    "linecode": row.get("linecode", ""),
                    # Expostos para que o cenário veja contra o que o
                    # carregamento está sendo medido — e perceba quando é o
                    # padrão do OpenDSS, e não um dado do alimentador.
                    "norm_amps": norm_amps,
                    "emerg_amps": emerg_amps,
                    # Redundante com o tipo da entidade, mas quem recebe só o
                    # extra_info (o exportador de topologia, um relatório) não
                    # enxerga o tipo.
                    "is_switch": is_switch,
                },
            )

    def _add_transformers(self):
        """Cria uma entidade por transformador, ligada às barras dos enrolamentos.

        Sem elas o grafo de entidades se parte: os bancos de reguladores do
        IEEE34 (``814``/``814r``, ``852``/``852r``) e as elevadoras de
        subestação são transformadores, não linhas, e as barras dos dois lados
        ficariam sem nada as ligando.
        """
        for name, info in self.dss_wrapper.get_all_transformers_info().items():
            eid = f"Transformer-{name}"
            buses = info.get("buses", [])
            info["eid_dss"] = eid

            parsed = [_parse_bus(bus) for bus in buses]
            info["bus_names"] = [bus_name for bus_name, _ in parsed]
            info["nodes"] = [_resolve_nodes(nodes, info.get("phases")) for _, nodes in parsed]

            if len(buses) > 2:
                print(
                    f"[OpenTES][AVISO] Transformer.{name} tem {len(buses)} enrolamentos; "
                    "apenas os dois primeiros entram na topologia."
                )

            rel = []
            for bus in buses[:2]:
                rel += self._bus_rel(bus, eid)

            self._add_child(eid, "Transformer", name, rel=rel, extra_info=info)

    def _add_regulators(self):
        regulators = self.dss_wrapper.get_all_regulators_info()
        if not regulators:
            return

        # Os transformadores já existem (_create_grid os cria antes). Nomes em
        # minúsculas porque o motor não garante a mesma caixa nos dois lados.
        transformers = {
            self.entity_map[eid].lower(): eid for eid in self._eids_by_type.get("Transformer", [])
        }

        for info in regulators:
            name = info["name"]
            eid = f"RegControl-{name}"
            info["eid_dss"] = eid
            info["bus"] = info["target_bus"]
            info["phase"] = info["target_phase"]

            self._add_child(
                eid,
                "RegControl",
                name,
                rel=self._regulator_rel(info, eid, transformers),
                extra_info=info,
            )
            print(
                f"[OpenTES] Regulador detectado: {name} @ "
                f"{info['target_bus']}.{info['target_phase']}"
            )

    def _regulator_rel(self, info, eid, transformers):
        """Barras entre as quais o regulador fica: as do transformador que comanda.

        O regulador é um elemento série, então o ``rel`` declara o par de barras
        do trecho que ele ocupa, como faz uma linha. Não aponta para o próprio
        ``Transformer``: ele ganharia um terceiro vizinho no grafo de entidades
        e deixaria de poder ser desenhado como aresta.

        Args:
            info: Dados do regulador, de ``get_all_regulators_info``.
            eid: Identificador da entidade, para as mensagens.
            transformers: Mapa nome do transformador (minúsculas) -> eid.

        Returns:
            Lista de eids de barra. Se o transformador não for encontrado, só a
            barra regulada, com aviso.
        """
        trafo_eid = transformers.get(str(info.get("trafo", "")).lower())
        if trafo_eid is None:
            print(
                f"[OpenTES][AVISO] {eid}: transformador '{info.get('trafo')}' nao "
                "encontrado; o regulador fica ligado so a barra que regula."
            )
            return self._bus_rel(info["target_bus"], eid)

        rel = []
        for bus in self._extra_info[trafo_eid].get("bus_names", [])[:2]:
            rel += self._bus_rel(bus, eid)
        return rel or self._bus_rel(info["target_bus"], eid)

    def _add_storages(self):
        for name, info in self.dss_wrapper.get_all_storages_info().items():
            eid = f"Storage-{name}"
            bus_name, nodes = _parse_bus(info.get("bus", ""))
            phases = info.get("num_phases") or len(nodes) or 3
            info["eid_dss"] = eid
            info["name"] = name
            info["bus"] = bus_name
            info["nodes"] = _resolve_nodes(nodes, phases)
            info["phases"] = phases
            self._power_factor[("Storage", name)] = _as_float(info.get("pf"), 1.0)
            self._warn_if_storage_reactive_is_capped(name, info)

            self._add_child(
                eid,
                "Storage",
                name,
                rel=self._bus_rel(bus_name, eid),
                extra_info=info,
            )
            print(
                f"[OpenTES] Storage detectado: {name} @ {bus_name} | "
                f"kW_rated: {info['kw_rated']} | kWh_rated: {info['kwh_rated']}"
            )

    def _add_pvsystems(self):
        pv_infos = self.dss_wrapper.get_all_pvsystems_info()
        if not pv_infos:
            return

        for name, info in pv_infos.items():
            bus_name, nodes = _parse_bus(info.get("bus", ""))
            phases = info.get("num_phases") or len(nodes) or 3
            eid = f"PVSystem-{name}"
            info["eid_dss"] = eid
            info["name"] = name
            info["bus"] = bus_name
            info["nodes"] = _resolve_nodes(nodes, phases)
            info["phases"] = phases

            # Antes que a co-simulação comece a reescrever o pmpp do elemento;
            # ver pv_nameplate().
            self._pv_nameplate[name] = (_as_float(info.get("pmpp")), phases)
            self._power_factor[("PVSystem", name)] = _as_float(info.get("pf"), 1.0)
            self._warn_if_inverter_cannot_deliver(name, info)

            self._add_child(
                eid,
                "PVSystem",
                name,
                rel=self._bus_rel(bus_name, eid),
                extra_info=info,
            )
            print(
                f"[OpenTES] PVSystem detectado: {name} @ {bus_name} | "
                f"Pmpp: {info['pmpp']} kW | kVA: {info['kva']}"
            )

    def _add_generators(self):
        """Cria uma entidade por gerador, ligada à sua barra.

        Um gerador que declara curva (``daily``/``yearly``) passa a segui-la no
        :meth:`step`, como uma carga: em snapshot o OpenDSS a ignora, e o
        gerador ficaria parado no kW nominal o estudo inteiro.
        """
        for name, info in self.dss_wrapper.get_all_generators_info().items():
            eid = f"Generator-{name}"
            bus_name, nodes = _parse_bus(info.get("bus", ""))
            phases = info.get("num_phases") or len(nodes) or 3
            info["eid_dss"] = eid
            info["bus"] = bus_name
            info["nodes"] = _resolve_nodes(nodes, phases)
            info["phases"] = phases

            # Antes que o despacho comece a reescrever o kW; ver
            # generator_nameplate().
            kw, kvar = _as_float(info.get("kw")), _as_float(info.get("kvar"))
            self._generator_nameplate[name] = (kw, kvar)

            self._add_child(
                eid,
                "Generator",
                name,
                rel=self._bus_rel(bus_name, eid),
                extra_info=info,
            )
            self._check_profile(eid, name, "Generator", kw, kvar)
            print(
                f"[OpenTES] Generator detectado: {name} @ {bus_name} | "
                f"kW: {kw} | kvar: {kvar} | kVA: {info['kva']}"
            )

    def _warn_if_storage_reactive_is_capped(self, name, info):
        """Avisa se o ``kvarMax`` da bateria corta a reativa do fator de potência.

        O OpenDSS limita a reativa de um ``Storage`` ao ``kvarMax``, cujo padrão
        **não acompanha o tamanho da bateria** — uma de 200 kW sai com 25 kvar
        de teto. Movida por ``P_mult``, a bateria pediria ``P·tan(acos(pf))``, e
        o que passa do teto é cortado em silêncio: o resultado é um fator de
        potência diferente do declarado, sem nada dizendo.

        Como no ``normamps`` das linhas, o dado pertence ao ``.dss``: declare
        ``kvarMax`` junto do ``pf``.
        """
        kw_rated = _as_float(info.get("kw_rated"))
        pf = _as_float(info.get("pf"), 1.0)
        kvar_max = _as_float(info.get("kvar_max"))

        if not kw_rated or not kvar_max or not 0.0 < pf < 1.0:
            return

        necessario = abs(kw_rated * math.tan(math.acos(pf)))
        if necessario > kvar_max * (1 + 1e-9):
            print(
                f"[OpenTES][AVISO] Storage.{name}: a plena potencia com pf={pf:g} "
                f"pede {necessario:.1f} kvar, mas kvarMax e {kvar_max:.1f}. O "
                "OpenDSS corta o excedente, e o fator de potencia efetivo fica "
                "acima do declarado. Declare kvarMax no .dss."
            )

    def _warn_if_inverter_cannot_deliver(self, name, info):
        """Avisa se o inversor não tem kVA para a plena geração com o ``pf`` dele.

        Movido por ``P_mult``, o PV entrega ``P = mult · pmpp`` de ativa mais
        ``Q = P·tan(acos(pf))`` de reativa, e a aparente vale ``P / pf`` —
        máxima em ``mult = 1``. A infactibilidade, portanto, **depende só do que
        o circuito declara**, não do passo: dá para conferir uma vez aqui, em
        vez de repetir um aviso por passo no meio do log de um alimentador com
        dezenas de usinas.

        O OpenDSS não recusa a operação: ele limita a saída ao kVA, e o
        resultado é uma geração menor do que a curva pediu, sem nada dizendo.
        """
        pmpp = _as_float(info.get("pmpp"))
        kva = _as_float(info.get("kva"))
        pf = _as_float(info.get("pf"), 1.0)

        if not pmpp or not kva or not 0.0 < pf <= 1.0:
            return

        necessario = pmpp / pf
        if necessario > kva * (1 + 1e-9):
            print(
                f"[OpenTES][AVISO] PVSystem.{name}: a plena geracao com pf={pf:g} "
                f"exige {necessario:.1f} kVA, mas o inversor tem {kva:.1f} kVA. "
                "Movido por P_mult, o OpenDSS limitara a saida ao kVA e a geracao "
                "ficara abaixo da curva. Aumente o kVA ou aproxime o pf de 1."
            )

    def _check_profile(self, eid, name, element, base_kw, base_kvar):
        """Registra a LoadShape associada a uma carga ou gerador, se houver.

        Em snapshot o OpenDSS não aplica a curva declarada; quem a reproduz é o
        laço de :meth:`step`. Uma falha aqui não é inofensiva: sem perfil, o
        elemento fica congelado no valor nominal durante toda a simulação. Por
        isso é sinalizada em vez de ignorada.

        Args:
            eid: Identificador mosaik do elemento.
            name: Nome do elemento no OpenDSS.
            element: Classe OpenDSS (``'Load'`` ou ``'Generator'``).
            base_kw: Potência ativa nominal, sobre a qual o multiplicador incide.
            base_kvar: Potência reativa nominal.
        """
        shape_name = None
        try:
            yearly = self.dss_wrapper.get_property(name, "yearly", element)
            daily = self.dss_wrapper.get_property(name, "daily", element)
            if isinstance(yearly, str) and yearly.lower() not in ["none", "constant", ""]:
                shape_name = yearly
            if isinstance(daily, str) and daily.lower() not in ["none", "constant", ""]:
                shape_name = daily

        except OpenDSSException as exc:
            print(
                f"[OpenTES][AVISO] Nao foi possivel ler o perfil de {element}.{name}: "
                f"{exc}. O elemento ficara fixo no valor nominal."
            )

        if shape_name:
            self.profiles[eid] = {
                "element": element,
                "shape_name": shape_name,
                "base_kw": base_kw,
                "base_kvar": base_kvar,
            }

            if shape_name not in self.shape_data_cache:
                self._cache_loadshape(shape_name)

    def _cache_loadshape(self, shape_name):
        """Lê uma LoadShape uma vez e guarda seus multiplicadores.

        As peculiaridades do motor — ``npts`` maior que o vetor, intervalo em
        s/min/h, curva inexistente — ficam na fachada; ver
        :meth:`~._reader.ReaderMixin.get_loadshape`. Aqui fica só a política do
        adaptador: uma curva sem intervalo declarado anda no passo da simulação.

        Se a leitura falhar, o perfil fica ausente do cache e ``step()`` deixa
        os elementos que o usam parados no valor nominal — daí o aviso dizer a
        consequência, e não só o erro.
        """
        try:
            shape = self.dss_wrapper.get_loadshape(shape_name)
            if shape["interval_s"] is None:
                shape["interval_s"] = self.step_size
            self.shape_data_cache[shape_name] = shape

        except Exception as exc:
            print(
                f"[OpenTES][ERRO] Falha ao ler a LoadShape '{shape_name}': {exc}. "
                "Os elementos que a usam ficarao fixos no valor nominal."
            )

    def step(self, time, inputs, max_advance):
        self._apply_inputs(inputs)

        # O elemento movido de fora não é tocado pela LoadShape do .dss. Sem isto
        # o laço abaixo reescreveria kW e kvar logo depois de `_apply_inputs`,
        # apagando a entrada em silêncio — e só nos elementos que têm perfil, de
        # modo que obedecer ou não dependeria do arquivo de dados. Qualquer
        # entrada conta: num gerador, um `Q_set` sozinho também suspende a curva
        # naquele passo.
        movidos_de_fora = {eid for eid, attrs in inputs.items() if any(attrs.values())}

        # CARGAS E GERADORES COM CURVA NO .dss
        for eid, profile in self.profiles.items():
            if eid in movidos_de_fora:
                continue
            shape_name = profile["shape_name"]
            if shape_name not in self.shape_data_cache:
                continue
            data = self.shape_data_cache[shape_name]
            # npts foi conciliado com o tamanho real dos arrays em
            # _cache_loadshape, entao o indice esta sempre dentro dos limites.
            idx = math.floor(time / data["interval_s"]) % data["npts"]
            pmult = data["p_mult"][idx]
            qmult = data["q_mult"][idx]

            if data["use_actual"]:
                p_set = pmult
                q_set = qmult
            else:
                p_set = profile["base_kw"] * pmult
                q_set = profile["base_kvar"] * qmult

            self.dss_wrapper.set_power(
                self.entity_map[eid], p=p_set, q=q_set, element=profile["element"]
            )

        # 2. RESOLVER FLUXO DE POTÊNCIA (SNAPSHOT)
        self.dss_wrapper.run_dss()

        return time + self.step_size

    def _apply_inputs(self, inputs):
        """Aplica as entradas do mosaik ao circuito, roteadas pelo registry.

        Cada atributo é reduzido a um único valor pelo agregador declarado no
        seu :class:`~.element_specs.InputSpec`, de modo que comandos
        concorrentes sejam somados ou sinalizados — nunca descartados em
        silêncio. O valor agregado é conferido contra os ``bounds`` do mesmo
        ``InputSpec``, quando declarados.
        """
        for eid, attrs in inputs.items():
            spec = self._spec_of(eid)
            if spec is None or spec.writer is None:
                continue

            values = {}
            for attr, sources in attrs.items():
                if attr not in spec.inputs or not sources:
                    continue
                entrada = spec.inputs[attr]
                values[attr] = entrada.check(
                    attr, eid, entrada.aggregator(attr, eid, sources.values())
                )

            if not values:
                continue

            try:
                spec.writer(self, self.entity_map[eid], values)
            except Exception as exc:
                # Uma escrita de controle perdida faz a simulação divergir do
                # que o controlador comandou, sem nada no resultado indicando
                # isso. Parar é preferível a produzir um dia inteiro de dados
                # silenciosamente errados.
                raise OpenDSSException(f"Failed to apply {values} to {eid}: {exc}") from exc

    def get_data(self, outputs):
        data = {}
        for eid, attrs in outputs.items():
            spec = self._spec_of(eid)
            if spec is None:
                continue
            data[eid] = spec.reader(self, self.entity_map[eid], attrs, spec)
        return data

    def _spec_of(self, eid):
        """Especificação do modelo de *eid*, ou ``None`` se não for deste simulador."""
        model_type = self._type_by_eid.get(eid)
        if model_type is None:
            return None
        return MODEL_SPECS.get(model_type)

    def get_dss_wrapper(self):
        return self.dss_wrapper

    def get_detected_regulators(self):
        return self.detected_regulators

    def get_detected_pvsystems(self):
        return self.detected_pvsystems

    def get_detected_storages(self):
        return self.detected_storages

    def get_detected_generators(self):
        return self.detected_generators

    def get_detected_transformers(self):
        return self.detected_transformers

    def get_detected_switches(self):
        """Metadados das chaves do circuito — as linhas com ``switch=yes``."""
        return self.detected_switches

    def get_bus_positions(self):
        """Coordenadas das barras que as têm, indexadas por eid.

        Serve à visualização: com as coordenadas reais o alimentador é desenhado
        como no diagrama, em vez do arranjo que a simulação de forças inventa.
        Barras sem coordenada declarada ficam de fora, para que o consumidor
        possa decidir o que fazer com elas.

        Returns:
            Mapa ``eid -> (x, y)``.
        """
        return {
            eid: (info["x"], info["y"])
            for eid, info in self._map_by_type("Bus").items()
            if info.get("coord_defined")
        }


if __name__ == "__main__":
    import mosaik_api_v3

    mosaik_api_v3.start_simulation(OpenDSSSimulator())
