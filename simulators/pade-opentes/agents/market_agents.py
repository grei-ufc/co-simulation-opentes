#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sistema multi-agentes do mercado transativo (fase de programacao da operacao).

Porte dos agentes de `market-simulation` (tese de Lucas S. Melo, 2022, subsecao
6.1.2) para PADE 3.0 e Mosaik 3. Quatro papeis, mais o solver:

  AP  ProsumerAgent     um por no de baixa tensao com armazenamento
  AC  ConcentratorAgent um por transformador de distribuicao
  AD  DSOAgent          um, com o modelo da rede e as restricoes operacionais
  AM  MarketAgent       um, coordena a decomposicao dual e o preco sombra
      SolverAgent       resolve os modelos fora do reactor do Twisted

O QUE MUDOU EM RELACAO AO ORIGINAL
----------------------------------
1. UM simulador Mosaik para todos os agentes. O original subia um simulador por
   agente (68 prosumidores + 5 concentradores + DSO + mercado = 75 sockets TCP,
   `start_mosaik_sim.py:344-373`). Aqui um unico `MosaikCon` vive no agente de
   mercado e os demais agentes sao alcancados pelo registro `AGENTS`. E o padrao
   que o `agent_example_1_mosaik_updated.py` ja usava no cenario Volt/Var.

2. API do Mosaik 2.2 -> 3.0: `step(time, inputs, max_advance)`, `init` com
   `time_resolution`.

3. Conteudo das mensagens em JSON, nao `pickle` + `literal_eval`. Alem de
   fragil, o tamanho serializado alimenta o modelo de rede na Fase 5, entao a
   escolha de serializacao afeta resultado.

4. `handle_all_proposes` so dispara quando TODAS as propostas chegam, e o
   timeout do `FipaContractNetProtocol` esta comentado no PADE (protocols.py).
   Aqui cada rodada arma um timeout proprio: sem ele, uma unica mensagem
   perdida trava a rodada e, como o `step_done` sai de dentro do handler, trava
   tambem o Mosaik. Isso e inofensivo com comunicacao ideal e essencial na
   Fase 5, com o OMNeT++ descartando pacotes.

SEQUENCIA (fase de programacao, quatro ciclos)
----------------------------------------------
  ciclo 1  AC pede aos seus AP a programacao de armazenamento
  ciclo 2  AD pede aos AC as programacoes agregadas
  ciclo 3  AM pede aos AC e ao AD suas analises
  ciclo 4  iterativo: AC e AD reotimizam com o preco sombra corrente, o AM
           atualiza lambda (Eq. 6.30) e testa a convergencia

Quando a rodada fecha, o `step_done` libera o Mosaik e a programacao acordada
passa a ser publicada como potencia de cada no a cada passo de 15 min.
"""

import json
import math
import os
import sys
from pathlib import Path

import numpy as np
from pade.acl.aid import AID
from pade.acl.messages import ACLMessage
from pade.behaviours.protocols import (FipaContractNetProtocol,
                                       FipaRequestProtocol,
                                       FipaSubscribeProtocol)
from pade.core.agent import Agent
from pade.drivers.mosaik_driver import MosaikCon
from pade.misc.utility import defer_to_thread, display_message
from twisted.internet import reactor

MARKET_PKG = os.environ.get("MARKET_OPENTES_PATH", "/market")
sys.path.insert(0, MARKET_PKG)

from market_opentes.config import (PERIODS, STORAGE_TAN_PHI,   # noqa: E402
                                   load_case)
from market_opentes.dual import load_profiles, load_sensitivity  # noqa: E402
from market_opentes.optimization import (solve_concentrator, solve_dso,  # noqa: E402
                                         solve_prosumer)
from market_opentes.operation import realized_profiles, voltage_at  # noqa: E402
from market_opentes.scenarios import build_scenarios          # noqa: E402

# Host dos AID: e o endereco que os agentes usam para se CONECTAR entre si.
# O listenTCP liga em todas as interfaces de qualquer jeito, entao o Mosaik
# continua alcancando o processo de fora do container.
HOST = os.environ.get("PADE_AGENT_HOST", "127.0.0.1")
BASE_PORT = int(os.environ.get("PADE_PORT", "5678"))
AMS_PORT = int(os.environ.get("AMS_PORT", "8000"))
STEP_SIZE = int(os.environ.get("AGENT_STEP_SIZE", "900"))
CONFIG_JSON = os.environ.get("MARKET_CONFIG", "/market/data/config.json")
ALPHA = float(os.environ.get("MARKET_ALPHA", "0.6"))
EPS = float(os.environ.get("MARKET_EPS", "1e-3"))
MAX_ROUNDS = int(os.environ.get("MARKET_MAX_ROUNDS", "30"))
N_SCENARIOS = int(os.environ.get("MARKET_SCENARIOS", "1"))
# Espera antes de retransmitir, em segundos de RELOGIO REAL. Precisa ser coerente
# com o `NET_TIME_SCALE` da camada de rede, que comprime o atraso nominal: com
# escala 0,02, uma entrega de 150 s nominais leva 3 s reais, e um timeout de 600 s
# reais equivale a esperar 8 horas de rede antes de reenviar. Quando a escala e
# conhecida, o valor e derivado dela; `MARKET_ROUND_TIMEOUT` sobrepoe.
def _round_timeout():
    explicito = os.environ.get("MARKET_ROUND_TIMEOUT")
    if explicito:
        return float(explicito)
    escala = float(os.environ.get("NET_TIME_SCALE", "1.0"))
    if os.environ.get("NET_BACKEND", "ideal") == "ideal":
        return 120.0
    # Folga de cinco vezes sobre o pior caso plausivel de entrega nesta rede,
    # cerca de 200 s nominais por mensagem, com piso para nao ficar curto demais.
    return max(20.0, 5.0 * 200.0 * escala)


ROUND_TIMEOUT = _round_timeout()

# Posicao dos tres ciclos de troca de mensagens dentro da janela de 15 min
# (subsecao 6.1.2 da tese): AC com seus AP no minuto 1, AD com os AC no minuto 5,
# AM com AC e AD no minuto 10. Sao ORCAMENTOS, nao esperas: a negociacao inteira
# acontece dentro de um passo do Mosaik, com o relogio da co-simulacao parado, e
# o que interessa e se o tempo de REDE de cada ciclo cabe na fatia dele.
WINDOW_S = float(os.environ.get("MARKET_WINDOW_S", "900"))
CYCLE_START_S = (60.0, 300.0, 600.0)
CYCLE_BUDGET_S = (CYCLE_START_S[1] - CYCLE_START_S[0],
                  CYCLE_START_S[2] - CYCLE_START_S[1],
                  WINDOW_S - CYCLE_START_S[2])
CYCLE_NAMES = ("ciclo1_AC_AP", "ciclo2_AD_AC", "ciclo3_AM_AC_AD")

# Camada de rede, quando instalada. Serve para contabilizar o tempo de rede por
# ciclo; sem ela os ciclos continuam existindo, so nao ha o que medir.
LINK = None


def begin_cycle(index, t=None):
    """Abre a contabilidade de rede do ciclo dado (0, 1 ou 2).

    `t` e o intervalo de 15 min, quando a fase de operacao esta rodando. Sem ele
    o traco de mensagens nao tem tempo de co-simulacao e nao da para reproduzir
    a Figura 58 da tese, que e um grafico contra esse tempo.
    """
    if LINK is not None:
        LINK.begin_cycle(CYCLE_NAMES[index], t)


def close_cycle(index, label=""):
    """Fecha o ciclo e diz se o tempo de rede coube no orcamento dele."""
    if LINK is None:
        return None
    c = LINK.end_cycle()
    if c is None:
        return None
    c["budget_s"] = CYCLE_BUDGET_S[index]
    c["fits"] = c["max_delay"] <= CYCLE_BUDGET_S[index]
    if not c["fits"]:
        display_message("mercado", f"{CYCLE_NAMES[index]}{label}: tempo de rede "
                                   f"{c['max_delay']:.0f} s ESTOURA o orcamento de "
                                   f"{CYCLE_BUDGET_S[index]:.0f} s")
    return c
# Retransmissoes por rodada. O FIPA nao define retransmissao: o protocolo supoe
# que a camada de transporte entrega. Com o OMNeT++ descartando pacotes, uma
# unica mensagem perdida em ~24 por rodada mata a rodada, entao sem isto a
# negociacao nao sobrevive a nenhuma perda realista.
# Retransmissoes antes de desistir de um destinatario. Tres bastavam com a rede
# idealizada; sobre a topologia publicada da tese NAO bastam. O enlace 5-36, por
# exemplo, e admitido com PER 0,4, que a Tabela 7 aceita por estar abaixo do
# limiar de 0,5: uma mensagem de 1250 bytes ocupa dez quadros e perde 27,5% dos
# datagramas mesmo com as retentativas do MAC. Com tres tentativas a negociacao
# aborta na primeira rodada; com dez ela converge.
MAX_RETRIES = int(os.environ.get("MARKET_MAX_RETRIES", "10"))
# 0 = linha de base: publica a programacao PROPOSTA pelos prosumidores, sem
# negociacao, para medir o que a rede sofreria sem o mecanismo.
NEGOTIATE = os.environ.get("MARKET_NEGOTIATE", "1") == "1"
# Fase de operacao: a cada passo de 15 min o DSO confere o desvio da previsao e,
# se houver violacao, corrige. Dia realizado = outro dia do reservatorio de
# cenarios, para que exista desvio.
OPERATION = os.environ.get("MARKET_OPERATION", "1") == "1"
REALIZED_DAY = int(os.environ.get("MARKET_REALIZED_DAY", "9"))
# Circuito para o fluxo de potencia da fase de operacao. O agente DSO precisa do
# ponto de operacao REALIZADO, e nao de uma extrapolacao linear do ponto do dia
# seguinte: medido, a extrapolacao erra ate 7,2e-3 pu, sete vezes a margem de
# seguranca. A tese resolve o fluxo de carga na operacao
# (`analyse_auction_grid_restrictions` chama `run_powerflow_in_pandapower`), e
# aqui e o mesmo: o solver abre o circuito e resolve.
MARKET_CIRCUIT = os.environ.get("MARKET_CIRCUIT",
                                "/grid-data/MVLV75/Master.dss")

_BUS_CACHE = None


def _bus_name(node):
    """Nome da barra no OpenDSS para um no do mercado.

    As redes geradas pelo repositorio nomeiam as barras como `n{no}`, e essa
    continua sendo a regra. Uma rede publicada, como a IEEE 13, tem nomes
    proprios que nao se pode renomear sem perder a correspondencia com a
    referencia: nesse caso o `force.json` traz o nome da barra em cada no.
    Mesma funcao de `sensitivity.py`, que roda no outro container.
    """
    global _BUS_CACHE
    if _BUS_CACHE is None:
        arq = Path(os.environ.get("MARKET_GRID_DIR",
                                  Path(MARKET_CIRCUIT).parent)) / "force.json"
        try:
            dados = json.loads(arq.read_text())
            _BUS_CACHE = {n["name"]: n["bus"] for n in dados["nodes"] if "bus" in n}
        except OSError:
            _BUS_CACHE = {}
    return _BUS_CACHE.get(node, f"n{node}")
# Qual demanda a REDE ve. E independente de a fase de operacao estar ligada:
# a demanda realizada e a mesma realidade fisica em todos os cenarios
# comparados, e o que muda entre eles e se os agentes reagem a ela. Amarrar as
# duas coisas faria a linha de base rodar sobre uma demanda diferente da do caso
# negociado, e a comparacao deixaria de isolar o efeito do mecanismo.
USE_REALIZED = os.environ.get("MARKET_REALIZED", "1") == "1"
OP_MAX_ROUNDS = int(os.environ.get("MARKET_OP_MAX_ROUNDS", "30"))
# O leilao de tempo real liquida em TODA janela, como no original, e nao apenas
# quando o armazenamento de rede nao basta. Ver `collect_operation`.
OP_AUCTION_ALWAYS = os.environ.get("MARKET_OP_AUCTION_ALWAYS", "1") not in ("0", "")

AGENTS = {}          # localname -> instancia, para o simulador Mosaik alcancar

MOSAIK_MODELS = {
    "api_version": "3.0",
    "type": "time-based",
    "models": {
        "MarketMAS": {
            "public": True,
            "params": ["node"],
            "attrs": ["P_kw", "Q_kvar", "lambda_max", "round_count"],
        },
    },
}


def _json(payload):
    return json.dumps(payload)


def _parse(content):
    return json.loads(content)


def _curto(serie, casas=6):
    """Serie com precisao limitada, para nao gastar rede com digito de ruido.

    Um float de dupla precisao serializa em ate 17 algarismos; a negociacao
    converge com tolerancia 1e-4. Os digitos alem do sexto sao bytes que
    trafegam sem carregar informacao usada.
    """
    return [round(float(x), casas) for x in serie]


def _set_content(message, payload):
    """Define o conteudo e ANOTA o tamanho serializado da mensagem.

    O `ACLMessage` do PADE 2.2 tinha `set_message_length`, usado pela integracao
    com o ns-3 para dimensionar o pacote; o PADE 3.0 removeu isso junto com o
    modulo `pade.simul`. Como o modelo de rede da Fase 5 precisa do tamanho,
    guardamos em `message_length` como atributo simples. Quem consumir deve ler
    com `getattr(msg, "message_length", None)`.
    """
    content = _json(payload)
    message.set_content(content)
    message.message_length = len(content.encode("utf-8"))
    return message


def _violations(v):
    """Quantos pares (no, intervalo) exigem ACAO da fase de operacao.

    Usa `V_ACAO_MIN`/`V_ACAO_MAX`, que por padrao sao o proprio limite. Com um
    limiar mais rigoroso o DSO passa a intervir antes de violar; a contagem do
    RESULTADO, que sai dos CSV contra 0,97 e 1,03, nao muda.
    """
    from market_opentes.config import V_ACAO_MAX, V_ACAO_MIN, V_TOL
    return int((v < V_ACAO_MIN - V_TOL).sum() + (v > V_ACAO_MAX + V_TOL).sum())


def _reply(message, performative, payload):
    answer = message.create_reply()
    answer.set_performative(performative)
    return _set_content(answer, payload)


# ---------------------------------------------------------------------------
# Solver: roda os modelos em thread separada, para nao travar o reactor
# ---------------------------------------------------------------------------

class SolverProtocol(FipaRequestProtocol):
    def __init__(self, agent):
        super().__init__(agent=agent, message=None, is_initiator=False)

    def handle_request(self, message):
        super().handle_request(message)
        request = _parse(message.content)
        defer_to_thread(lambda: self.agent.dispatch(request),
                        lambda result: self._answer(message, result))

    def _answer(self, message, result):
        self.agent.send(_reply(message, ACLMessage.INFORM, result))


class SolverAgent(Agent):
    """Resolve os modelos Pyomo sob demanda (papel do `solver_agent.py`)."""

    def __init__(self, aid, case, profiles, price, sensitivity):
        super().__init__(aid=aid, debug=False)
        self.case = case
        self.profiles, self.price = profiles, price
        self.v0, self.s = sensitivity
        self.realized = realized_profiles(REALIZED_DAY) if OPERATION else None
        self.v0_real = None
        if OPERATION:
            self.v0_real = self._solve_operation_points()
            display_message(self.aid.localname,
                            f"{len(self.v0_real)} pontos de operacao resolvidos "
                            "no fluxo de potencia")
        self.behaviours.append(SolverProtocol(self))

    def _solve_operation_points(self):
        """Resolve o fluxo de potencia nos 96 intervalos da demanda REALIZADA.

        Feito UMA vez, no arranque e na thread principal, por dois motivos.
        Primeiro, o OpenDSS via py_dss_interface NAO e thread-safe: chama-lo de
        dentro do `defer_to_thread` do solver derruba o processo com
        `std::bad_alloc`. Segundo, o V0 depende so da demanda, nao das variaveis
        de decisao, entao nao ha o que recalcular a cada rodada. O custo e de
        cerca de um segundo para o dia inteiro.

        Cuidado: o py_dss_interface troca o diretorio de trabalho do processo ao
        instanciar e ao compilar. Sem restaurar, o logger do PADE tenta criar
        `logs/` dentro do circuito e quebra se o volume for somente-leitura.
        """
        import py_dss_interface

        cwd = os.getcwd()
        try:
            dss = py_dss_interface.DSS()
            dss.text(f'Compile "{MARKET_CIRCUIT}"')
            tan_phi = math.tan(math.acos(0.9))
            pontos = []
            for t in range(PERIODS):
                for node in self.case.lv_nodes:
                    if node in self.realized:
                        kw = float(self.realized[node][t])
                        dss.text(f"Edit Load.Load_{node} kW={kw} "
                                 f"kvar={kw * tan_phi}")
                dss.text("Solve")
                v = []
                for node in self.case.all_nodes:
                    dss.circuit.set_active_bus(_bus_name(node))
                    mags = [m for m in dss.bus.vmag_angle_pu[0::2] if m > 1e-6]
                    v.append(sum(mags) / len(mags))
                pontos.append(np.array(v))
        finally:
            os.chdir(cwd)
        return pontos

    def _operation_point(self, t):
        """Tensao base do intervalo, no ponto de operacao REALIZADO.

        O desvio nao e variavel de decisao: e deslocamento do ponto de operacao.
        Ele poderia entrar por extrapolacao linear (`shifted_v0`), mas medido
        isso erra ate 7,2e-3 pu contra o fluxo de potencia, sete vezes a margem
        de seguranca do modelo, e os agentes passam a corrigir uma tensao que
        nao e a da rede. Por isso o fluxo e RESOLVIDO aqui.
        """
        deviation = {n: float(self.realized[n][t] - self.profiles[n][t])
                     for n in self.profiles if n in self.realized}
        base_kw = {n: np.array([float(self.realized[n][t])])
                   for n in self.case.lv_nodes if n in self.realized}
        return self.v0_real[t], base_kw, float(sum(deviation.values()))

    def on_start(self):
        super().on_start()
        AGENTS[self.aid.localname] = self

    def dispatch(self, request):
        kind = request["kind"]
        if kind == "prosumer":
            node = request["node"]
            scenarios = build_scenarios(
                node, n_reduced=N_SCENARIOS,
                deterministic_demand=self.profiles[node],
                deterministic_price=self.price)
            # `.get`, e nao `[]`: todo no de baixa tensao e prosumidor e
            # contrata nos dois mercados; so alguns tem bateria. E o que o
            # `ReferenceModel.py` do trabalho original faz, com `p_bilateral`
            # fora do `if has_storage`.
            decision = solve_prosumer(scenarios, self.case.prosumer_storage.get(node))
            return {"node": node,
                    "schedule": decision["storage"].tolist(),
                    "bilateral": decision["bilateral"].tolist(),
                    "spot": decision["spot"].tolist()}

        if kind == "concentrator":
            nodes = request["nodes"]
            out = solve_concentrator(
                nodes,
                {n: np.array(request["p_init"][str(n)]) for n in nodes},
                {n: np.array(request["lam"][str(n)]) for n in nodes},
                self.case.prosumer_storage)
            return {"schedule": {str(n): out[n].tolist() for n in nodes}}

        if kind == "dso":
            pros = self.case.prosumer_storage_nodes
            net = self.case.network_storage_nodes
            p, q = solve_dso(
                self.case, self.profiles,
                {n: np.array(request["p_init"][str(n)]) for n in pros},
                {n: np.array(request["q_init"][str(n)]) for n in net},
                {n: np.array(request["lam"][str(n)]) for n in pros},
                self.v0, self.s)
            return {"p": {str(n): p[n].tolist() for n in pros},
                    "q": {str(n): q[n].tolist() for n in net}}

        if kind in ("operation_level1", "operation_dso", "operation_concentrator"):
            return self._dispatch_operation(kind, request)

        raise ValueError(f"pedido desconhecido ao solver: {kind}")

    def _dispatch_operation(self, kind, request):
        t = int(request["t"])
        pros = self.case.prosumer_storage_nodes
        net = self.case.network_storage_nodes
        v0_t, base_kw, desvio = self._operation_point(t)

        if kind == "operation_concentrator":
            nodes = request["nodes"]
            out = solve_concentrator(
                nodes,
                {n: np.array(request["p_init"][str(n)]) for n in nodes},
                {n: np.array(request["lam"][str(n)]) for n in nodes},
                self.case.prosumer_storage, periods=1)
            return {"schedule": {str(n): out[n].tolist() for n in nodes}}

        p_t = {n: np.array(request["p_init"][str(n)]) for n in pros}
        q_t = {n: np.array(request["q_init"][str(n)]) for n in net}
        lam_t = {n: np.array(request["lam"][str(n)]) for n in pros}
        # Estado de carga do armazenamento de REDE, acumulado ao longo do dia.
        # Sem isto cada janela resolvia com a bateria de volta a 50%, o que a
        # tornava uma fonte de energia infinita: 8 kW disponiveis nas 95 janelas
        # dao 190 kWh de um dispositivo de 20 kWh. Era por isso que o
        # armazenamento de rede SEMPRE bastava e o leilao nunca abria.
        # Vem no pedido: quem sabe o que foi de fato APLICADO nos intervalos
        # anteriores e o agente de mercado, nao o solver.
        soc_rede = {int(k): float(v)
                    for k, v in request.get("soc_rede", {}).items()} or None

        if kind == "operation_level1":
            antes = voltage_at(self.case, v0_t, self.s[t], p_t, q_t)
            viol_antes = _violations(antes)
            if not viol_antes:
                return {"t": t, "deviation": desvio, "violations_before": 0,
                        "violations_after": 0, "level": "-",
                        "v_min_before": float(antes.min()),
                        "v_min_after": float(antes.min()),
                        "p": {str(n): v.tolist() for n, v in p_t.items()},
                        "q": {str(n): v.tolist() for n, v in q_t.items()}}
            try:
                p, q = solve_dso(self.case, base_kw, p_t, q_t, lam_t,
                                 v0_t[None, :], self.s[t:t + 1], periods=1,
                                 fix_prosumer=True, soc0=soc_rede)
                depois = voltage_at(self.case, v0_t, self.s[t], p, q)
            except RuntimeError:
                p, q, depois = p_t, q_t, antes
            return {"t": t, "deviation": desvio, "violations_before": viol_antes,
                    "violations_after": _violations(depois), "level": "rede",
                    "v_min_before": float(antes.min()),
                    "v_min_after": float(depois.min()),
                    "p": {str(n): np.asarray(v).tolist() for n, v in p.items()},
                    "q": {str(n): np.asarray(v).tolist() for n, v in q.items()}}

        # operation_dso: o leilao de operacao, sem fixar o prosumidor
        p, q = solve_dso(self.case, base_kw, p_t, q_t, lam_t,
                         v0_t[None, :], self.s[t:t + 1], periods=1,
                         soc0=soc_rede)
        depois = voltage_at(self.case, v0_t, self.s[t], p, q)
        return {"t": t, "violations_after": _violations(depois),
                "v_min_after": float(depois.min()),
                "p": {str(n): v.tolist() for n, v in p.items()},
                "q": {str(n): v.tolist() for n, v in q.items()}}


class SolverClient(FipaRequestProtocol):
    """Lado iniciador: quem precisa de um modelo resolvido usa isto."""

    def __init__(self, agent):
        super().__init__(agent=agent, message=None, is_initiator=True)
        self.callback = None

    def ask(self, request, callback):
        self.callback = callback
        message = ACLMessage(ACLMessage.REQUEST)
        message.set_protocol(ACLMessage.FIPA_REQUEST_PROTOCOL)
        message.add_receiver(AID(name="solver"))
        _set_content(message, request)
        self.message = message
        self.on_start()

    def handle_inform(self, message):
        if self.callback:
            self.callback(_parse(message.content))


# ---------------------------------------------------------------------------
# Despacho da programacao acordada: FIPA-Subscribe
#
# Fechada a negociacao, a programacao precisa CHEGAR a quem a executa. No
# original isso e feito por Subscribe/Publish (`DSOPublisherProtocol`,
# `BESSPublisherProtocol`, `ProsumerSubscriberProtocol`), e a versao anterior
# daqui simplesmente aplicava o resultado da otimizacao do DSO sem ato
# comunicativo nenhum. Alem de infiel a arquitetura, isso SUBESTIMA o trafego que
# a analise de comunicacao mede.
#
# A cadeia e: os prosumidores assinam o seu concentrador, os concentradores
# assinam o DSO. No aceite, o DSO publica aos concentradores, cada concentrador
# despacha o armazenamento de rede sob ele e publica aos seus prosumidores, e as
# confirmacoes sobem no caminho inverso ate o agente de mercado.
# ---------------------------------------------------------------------------

class DispatchPublisher(FipaSubscribeProtocol):
    """Lado publicador: aceita assinaturas e distribui a programacao."""

    def __init__(self, agent, on_all_confirmed=None):
        super().__init__(agent, message=None, is_initiator=False)
        self._on_all_confirmed = on_all_confirmed
        self.expected = 0
        self.confirmed = 0

    def handle_subscribe(self, message):
        self.register(message.sender)
        answer = message.create_reply()
        answer.set_performative(ACLMessage.AGREE)
        self.agent.send(_set_content(answer, {"ok": True}))

    def publish(self, payload):
        self.expected = len(self.subscribers)
        self.confirmed = 0
        if not self.expected:
            if self._on_all_confirmed:
                self._on_all_confirmed()
            return
        message = ACLMessage(ACLMessage.INFORM)
        message.set_protocol(ACLMessage.FIPA_SUBSCRIBE_PROTOCOL)
        _set_content(message, payload)
        self.notify(message)

    def handle_inform(self, message):
        # NAO chamar super(): o handle_inform da classe base do PADE e o do
        # comportamento de registro no AMS e tenta desserializar a tabela de
        # agentes, enchendo o log de erro.
        payload = _parse(message.content)
        if payload.get("confirm") != "DISPATCH":
            return
        self.confirmed += 1
        if self.confirmed >= self.expected and self._on_all_confirmed:
            self._on_all_confirmed()


class DispatchSubscriber(FipaSubscribeProtocol):
    """Lado assinante: recebe a programacao, aplica e confirma."""

    def __init__(self, agent, publisher_name, on_dispatch):
        message = ACLMessage(ACLMessage.SUBSCRIBE)
        message.set_protocol(ACLMessage.FIPA_SUBSCRIBE_PROTOCOL)
        message.add_receiver(AID(name=publisher_name))
        _set_content(message, {"subscribe": agent.aid.localname})
        super().__init__(agent, message, is_initiator=True)
        self._on_dispatch = on_dispatch

    def handle_agree(self, message):
        pass

    def handle_inform(self, message):
        payload = _parse(message.content)
        if "dispatch" not in payload:
            return
        # O assinante so confirma DEPOIS de aplicar; num concentrador, aplicar
        # inclui repassar aos seus proprios assinantes.
        self._on_dispatch(payload["dispatch"],
                          lambda: self.agent.send(
                              _reply(message, ACLMessage.INFORM,
                                     {"confirm": "DISPATCH"})))


# ---------------------------------------------------------------------------
# AP: Agente Prosumidor
# ---------------------------------------------------------------------------

class ProsumerParticipant(FipaContractNetProtocol):
    def __init__(self, agent):
        super().__init__(agent=agent, message=None, is_initiator=False)

    def handle_cfp(self, message):
        super().handle_cfp(message)
        request = _parse(message.content)
        if request.get("action") != "SCHEDULE":
            return

        t = request.get("t")
        if t is not None:
            # Ciclo 1 da fase de operacao: um intervalo so, e a programacao ja
            # foi decidida na fase anterior, entao nao ha o que reotimizar. O
            # prosumidor apenas informa o valor que vai executar.
            valor = float(self.agent.dispatched[t]) if self.agent.dispatched is not None else 0.0
            self.agent.send(_reply(message, ACLMessage.PROPOSE,
                                   {"node": self.agent.node, "t": t,
                                    "schedule": [valor]}))
            return

        self.agent.solver.ask(
            {"kind": "prosumer", "node": self.agent.node},
            lambda result: self.agent.send(
                _reply(message, ACLMessage.PROPOSE,
                       {"node": self.agent.node, "schedule": result["schedule"]})))


class ProsumerAgent(Agent):
    def __init__(self, aid, node, concentrator_name):
        super().__init__(aid=aid, debug=False)
        self.node = node
        self.schedule = None
        self.dispatched = None
        self.solver = SolverClient(self)
        self.behaviours.append(self.solver)
        self.behaviours.append(ProsumerParticipant(self))
        self.subscriber = DispatchSubscriber(self, concentrator_name,
                                             self._apply_dispatch)
        self.behaviours.append(self.subscriber)

    def _apply_dispatch(self, dispatch, confirm):
        """Recebe a programacao acordada do seu armazenamento e confirma."""
        series = dispatch.get(str(self.node))
        if series is not None:
            self.dispatched = np.array(series)
        confirm()

    def on_start(self):
        super().on_start()
        AGENTS[self.aid.localname] = self


# ---------------------------------------------------------------------------
# AC: Agente Concentrador
# ---------------------------------------------------------------------------

class ConcentratorInitiator(FipaContractNetProtocol):
    """Ciclo 1: pede aos prosumidores a programacao proposta.

    A conclusao do ciclo e decidida por CONTAGEM PROPRIA, e nao pelo
    `handle_all_proposes` do PADE. O motivo esta em `collect_propose` do agente
    de mercado: com entrega atrasada, os contadores internos do protocolo e o
    conjunto agregado deixam de coincidir.
    """

    def __init__(self, agent, message):
        super().__init__(agent=agent, message=message, is_initiator=True)

    def handle_propose(self, message):
        super().handle_propose(message)
        payload = _parse(message.content)
        self.agent.p_init[int(payload["node"])] = np.array(payload["schedule"])
        if len(self.agent.p_init) >= len(self.agent.nodes):
            self.agent.on_prosumers_ready()

    def handle_all_proposes(self, proposes):
        # A contagem e feita em handle_propose; aqui so se garante o fecho caso
        # o PADE dispare este caminho primeiro.
        super().handle_all_proposes(proposes)
        if len(self.agent.p_init) >= len(self.agent.nodes):
            self.agent.on_prosumers_ready()


class ConcentratorParticipant(FipaContractNetProtocol):
    """Ciclos 2 a 4: responde ao DSO e ao agente de mercado."""

    def __init__(self, agent):
        super().__init__(agent=agent, message=None, is_initiator=False)

    def handle_cfp(self, message):
        super().handle_cfp(message)
        request = _parse(message.content)
        action = request.get("action")

        if action == "REPORT":          # ciclo 2: so devolve o que os AP propuseram
            resposta = {"p_init": {str(n): self.agent.p_init[n].tolist()
                                   for n in self.agent.storage_nodes
                                   if n in self.agent.p_init}}
            if "t" in request:
                resposta["t"] = request["t"]
                # Na operacao o AC informa tambem o armazenamento de rede sob
                # ele, que e o recurso que o AD tenta usar primeiro.
                resposta["q_init"] = {
                    str(n): [float(self.agent.network_dispatch[n][request["t"]])]
                    for n in self.agent.network_storage
                    if self.agent.network_dispatch is not None
                    and n in self.agent.network_dispatch}
            self.agent.send(_reply(message, ACLMessage.PROPOSE, resposta))
            return

        if action == "OPERATE_AUCTION":  # leilao de operacao, um periodo so
            nodes = self.agent.storage_nodes
            self.agent.solver.ask(
                {"kind": "operation_concentrator", "t": request["t"],
                 "nodes": nodes,
                 "p_init": {str(n): request["p_init"][str(n)] for n in nodes},
                 "lam": {str(n): request["lam"][str(n)] for n in nodes}},
                lambda result: self.agent.send(
                    _reply(message, ACLMessage.PROPOSE,
                           {"round": request.get("round"),
                            "schedule": {k: _curto(v)
                                         for k, v in result["schedule"].items()}})))
            return

        if action == "REOPTIMIZE":       # ciclo 4: reotimiza com o preco sombra
            # O preco sombra chega indexado POR NO. Casar por posicao seria um
            # erro silencioso: cada concentrador cuida de um subconjunto dos nos
            # e receberia o lambda de outro prosumidor, o que ainda converge,
            # mas mais devagar e para outro ponto.
            nodes = self.agent.storage_nodes
            self.agent.solver.ask(
                {"kind": "concentrator", "nodes": nodes,
                 "p_init": {str(n): self.agent.p_init[n].tolist() for n in nodes},
                 "lam": {str(n): request["lam"][str(n)] for n in nodes}},
                lambda result: self.agent.send(
                    _reply(message, ACLMessage.PROPOSE,
                           {"round": request.get("round"),
                            "schedule": {k: _curto(v)
                                         for k, v in result["schedule"].items()}})))


class ConcentratorAgent(Agent):
    def __init__(self, aid, name, nodes, storage_nodes, on_ready,
                 network_storage=()):
        super().__init__(aid=aid, debug=False)
        self.name = name
        # `nodes` sao TODOS os prosumidores sob este transformador, que e com
        # quem o ciclo 1 fala. `storage_nodes` sao os que tem bateria, que sao
        # os unicos com variavel a acoplar na negociacao de lambda. Confundir os
        # dois tirava 43 dos 68 nos da MVLV75 do mercado e do trafego.
        self.nodes = nodes
        self.storage_nodes = storage_nodes
        self.p_init = {}
        self._on_ready = on_ready
        self._reported = False
        self._retries = 0
        self.retransmissions = 0
        # Quantas programacoes se perderam de vez. Precisa ser contado: com a
        # politica de entrar com zero, a perda deixa de derrubar a execucao e
        # passaria a ser invisivel no resultado.
        self.sem_resposta = 0
        self._timeout_call = None
        self.solver = SolverClient(self)
        self.behaviours.append(self.solver)
        self.behaviours.append(ConcentratorParticipant(self))
        self.cycle1 = None
        self.op_t = None            # intervalo, quando o ciclo 1 e de operacao
        # Papel do AC na tese: acionar os dispositivos de armazenamento de rede
        # sob o seu transformador. O DSO decide, o concentrador despacha.
        self.network_storage = network_storage
        self.network_dispatch = None
        self.publisher = DispatchPublisher(self)
        self.behaviours.append(self.publisher)
        self.subscriber = DispatchSubscriber(self, "dso", self._apply_dispatch)
        self.behaviours.append(self.subscriber)
        self._confirm_to_dso = None

    def _apply_dispatch(self, dispatch, confirm):
        """Aciona o armazenamento de rede e repassa aos prosumidores."""
        rede = {n: dispatch["network"][str(n)] for n in self.network_storage
                if str(n) in dispatch.get("network", {})}
        self.network_dispatch = {n: np.array(v) for n, v in rede.items()}
        display_message(self.aid.localname,
                        f"despachando {len(self.network_dispatch)} armazenamentos "
                        f"de rede e repassando a {len(self.nodes)} prosumidores")
        self._confirm_to_dso = confirm
        self.publisher._on_all_confirmed = self._on_prosumers_confirmed
        prosumer_part = {str(n): dispatch["prosumer"][str(n)]
                         for n in self.nodes if str(n) in dispatch.get("prosumer", {})}
        self.publisher.publish({"dispatch": prosumer_part})

    def _on_prosumers_confirmed(self):
        if self._confirm_to_dso:
            self._confirm_to_dso()
            self._confirm_to_dso = None

    def on_start(self):
        super().on_start()
        AGENTS[self.aid.localname] = self

    def request_schedules(self, t=None, on_ready=None):
        """Ciclo 1: pede a programacao aos prosumidores.

        Com `t` a solicitacao e da fase de operacao e pede so aquele intervalo,
        que e a diferenca que a tese aponta entre as duas fases: "as programacoes
        enviadas pelos AP e AC sao compostas apenas pelo valor programado para o
        proximo intervalo de tempo".
        """
        self.op_t = t
        if on_ready is not None:
            self._on_ready = on_ready
        self._reported = False
        self.p_init = {}
        if not self.nodes:
            self.on_prosumers_ready()
            return
        self._retries = 0
        self._send_cfp(self.nodes)

    def _send_cfp(self, nodes):
        """Envia (ou reenvia) o CFP do ciclo 1 aos prosumidores dados.

        O ciclo 1 precisa do mesmo tratamento do ciclo 4: sem timeout, uma
        proposta de prosumidor perdida deixa o concentrador esperando para
        sempre, e a negociacao inteira nunca comeca.
        """
        message = ACLMessage(ACLMessage.CFP)
        message.set_protocol(ACLMessage.FIPA_CONTRACT_NET_PROTOCOL)
        for node in nodes:
            message.add_receiver(AID(name=f"prosumer{node}"))
        payload = {"action": "SCHEDULE"}
        if self.op_t is not None:
            payload["t"] = self.op_t
        _set_content(message, payload)
        if self.cycle1 is None:
            self.cycle1 = ConcentratorInitiator(self, message)
            self.behaviours.append(self.cycle1)
        else:
            self.cycle1.message = message
        self.cycle1.on_start()
        self._timeout_call = self.call_later(ROUND_TIMEOUT, self._on_timeout)

    def _on_timeout(self):
        if self._reported:
            return
        faltando = [n for n in self.nodes if n not in self.p_init]
        if not faltando:
            self.on_prosumers_ready()
            return
        if self._retries < MAX_RETRIES:
            self._retries += 1
            self.retransmissions += len(faltando)
            display_message(self.aid.localname,
                            f"ciclo 1: timeout, retransmitindo para {faltando} "
                            f"(tentativa {self._retries}/{MAX_RETRIES})")
            self._send_cfp(faltando)
            return
        # Mesma politica que o DSO ja aplica no ciclo 2: quem nao respondeu nem
        # apos as retransmissoes entra com programacao NULA. Sem preencher, o
        # buraco em `p_init` so aparece dois ciclos depois, como um KeyError
        # dentro do `handle_cfp` do ciclo 4, que derruba o processo do agente e
        # trava a co-simulacao inteira. Foi o que aconteceu na primeira corrida
        # sobre a rede 6TiSCH da tese: o no 36 perdeu a proposta e a falha
        # apareceu num ponto sem relacao com a causa.
        #
        # A escolha nao e neutra e por isso fica registrada: o prosumidor
        # silencioso perde a chance de ser remunerado pelo ajuste, e a rede
        # perde o recurso dele.
        display_message(self.aid.localname,
                        f"ciclo 1: TIMEOUT definitivo, sem programacao de "
                        f"{faltando}: entram com zero")
        n_periodos = 1 if self.op_t is not None else PERIODS
        for n in faltando:
            self.p_init[n] = np.zeros(n_periodos)
        self.sem_resposta += len(faltando)
        self.on_prosumers_ready()

    def on_prosumers_ready(self):
        # `handle_all_proposes` pode ser chamado mais de uma vez pelo PADE (uma
        # por PROPOSE que fecha a contagem, e de novo pelo comportamento
        # temporizado). Sem esta guarda, o ciclo 1 termina varias vezes e o
        # agente de mercado abre rodadas concorrentes sobre o mesmo lambda.
        if self._reported:
            return
        self._reported = True
        if self._timeout_call is not None and self._timeout_call.active():
            self._timeout_call.cancel()
        self._on_ready(self.name)


# ---------------------------------------------------------------------------
# AD: Agente DSO
# ---------------------------------------------------------------------------

class DSOParticipant(FipaContractNetProtocol):
    def __init__(self, agent):
        super().__init__(agent=agent, message=None, is_initiator=False)

    def handle_cfp(self, message):
        super().handle_cfp(message)
        request = _parse(message.content)
        action = request.get("action")

        if action == "REOPTIMIZE":
            # `p_init` e `q_init` chegam so na primeira rodada e ficam guardados:
            # sao constantes na negociacao. Ver `_cfp_payload` do agente de
            # mercado.
            if "p_init" in request:
                self.agent.cache_p_init = request["p_init"]
                self.agent.cache_q_init = request["q_init"]
            if self.agent.cache_p_init is None:
                display_message(self.agent.aid.localname,
                                "REOPTIMIZE sem p_init e sem cache: a primeira "
                                "rodada nao chegou")
                return
            self.agent.solver.ask(
                {"kind": "dso",
                 "p_init": self.agent.cache_p_init,
                 "q_init": self.agent.cache_q_init,
                 "lam": request["lam"]},
                lambda result: self.agent.send(
                    _reply(message, ACLMessage.PROPOSE,
                           {"round": request.get("round"),
                            "p": {k: _curto(v) for k, v in result["p"].items()},
                            "q": {k: _curto(v) for k, v in result["q"].items()}})))
            return

        if action in ("OPERATE", "OPERATE_AUCTION"):
            # OPERATE e o primeiro nivel de interferencia: o DSO tenta corrigir
            # so com o armazenamento de rede. OPERATE_AUCTION e uma rodada do
            # leilao de operacao, com o armazenamento do prosumidor tambem.
            kind = ("operation_level1" if action == "OPERATE"
                    else "operation_dso")
            self.agent.solver.ask(
                {"kind": kind, "t": request["t"],
                 "p_init": request["p_init"], "q_init": request["q_init"],
                 "lam": request["lam"]},
                lambda result: self.agent.send(
                    _reply(message, ACLMessage.PROPOSE,
                           dict(result, round=request.get("round")))))


class ReportInitiator(FipaContractNetProtocol):
    """Ciclo 2: o AD pede as programacoes agregadas aos AC."""

    def __init__(self, agent, message):
        super().__init__(agent=agent, message=message, is_initiator=True)

    def handle_propose(self, message):
        super().handle_propose(message)
        self.agent.collect_report(message)


class DSOAgent(Agent):
    def __init__(self, aid, on_dispatch_done=None):
        super().__init__(aid=aid, debug=False)
        self.solver = SolverClient(self)
        self.behaviours.append(self.solver)
        self.behaviours.append(DSOParticipant(self))
        self.publisher = DispatchPublisher(self, on_dispatch_done)
        self.behaviours.append(self.publisher)
        self.reports = {}
        # `p_init` e `q_init` do ciclo 4 chegam so na primeira rodada; ver
        # `MarketAgent._cfp_payload`.
        self.cache_p_init = None
        self.cache_q_init = None
        self.report_behaviour = None
        self._report_on_ready = None
        self._report_expected = set()
        self._report_timeout = None

    # ---- ciclo 2: o AD pede aos AC as programacoes ------------------------
    def request_reports(self, names, on_ready, t=None):
        """Solicita a cada concentrador a programacao que ele agregou.

        Este ciclo EXISTIA so no papel: o tratador de `REPORT` estava escrito no
        concentrador, mas ninguem enviava o CFP, e o agente de mercado lia
        `p_init` direto da memoria do concentrador. O atalho pulava a rede
        inteira, e com isso o ciclo 2 nao aparecia em nenhuma medicao de
        comunicacao. A tese o descreve como ato comunicativo do AD com os AC.
        """
        self._report_on_ready = on_ready
        self._report_expected = set(names)
        self._report_all = set(names)
        self._report_t = t
        self._report_retries = 0
        self.reports = {}
        self._send_report_cfp(names, t)

    def _send_report_cfp(self, names, t):
        message = ACLMessage(ACLMessage.CFP)
        message.set_protocol(ACLMessage.FIPA_CONTRACT_NET_PROTOCOL)
        for name in names:
            message.add_receiver(AID(name=name))
        _set_content(message, {"action": "REPORT"} if t is None
                     else {"action": "REPORT", "t": t})
        if self.report_behaviour is None:
            self.report_behaviour = ReportInitiator(self, message)
            self.behaviours.append(self.report_behaviour)
        else:
            self.report_behaviour.message = message
        self.report_behaviour.on_start()
        self._report_timeout = self.call_later(ROUND_TIMEOUT, self._on_report_timeout)

    def collect_report(self, message):
        sender = getattr(message.sender, "localname", "?")
        payload = _parse(message.content)
        self.reports[sender] = payload
        self._report_expected.discard(sender)
        if not self._report_expected:
            self._finish_reports()

    def report_retransmissions(self):
        return getattr(self, "retransmissions", 0)

    def _on_report_timeout(self):
        """Reenvia aos faltantes, como fazem os ciclos 1 e 3.

        Sem isto o ciclo 2 desistia na primeira perda e o mercado seguia sem a
        programacao daquele concentrador, o que na pratica zera a flexibilidade
        de todos os prosumidores sob ele. O FIPA nao define retransmissao, e essa
        e a mesma lacuna ja tratada nos outros dois ciclos.
        """
        if not self._report_expected:
            self._finish_reports()
            return
        if self._report_retries < MAX_RETRIES:
            self._report_retries += 1
            faltando = sorted(self._report_expected)
            self.retransmissions = getattr(self, "retransmissions", 0) + len(faltando)
            display_message(self.aid.localname,
                            f"ciclo 2: timeout, retransmitindo para {faltando} "
                            f"(tentativa {self._report_retries}/{MAX_RETRIES})")
            self._send_report_cfp(faltando, self._report_t)
            return
        display_message(self.aid.localname,
                        f"ciclo 2: TIMEOUT definitivo, sem relatorio de "
                        f"{sorted(self._report_expected)}")
        self._finish_reports()

    def _finish_reports(self):
        if self._report_timeout is not None and self._report_timeout.active():
            self._report_timeout.cancel()
        callback, self._report_on_ready = self._report_on_ready, None
        if callback is not None:
            callback(self.reports)

    def dispatch(self, prosumer_schedule, network_schedule):
        """Publica a programacao acordada aos concentradores."""
        display_message(self.aid.localname,
                        f"publicando o despacho a {len(self.publisher.subscribers)} "
                        "concentradores")
        self.publisher.publish({"dispatch": {
            "prosumer": {str(n): v for n, v in prosumer_schedule.items()},
            "network": {str(n): v for n, v in network_schedule.items()}}})

    def on_start(self):
        super().on_start()
        AGENTS[self.aid.localname] = self


# ---------------------------------------------------------------------------
# AM: Agente Mercado, que tambem hospeda a conexao com o Mosaik
# ---------------------------------------------------------------------------

class OperationInitiator(FipaContractNetProtocol):
    """Ciclo da fase de operacao: um intervalo, dois niveis."""

    def __init__(self, agent, message):
        super().__init__(agent=agent, message=message, is_initiator=True)

    def handle_propose(self, message):
        super().handle_propose(message)
        self.agent.collect_operation(message)


class MarketInitiator(FipaContractNetProtocol):
    """Ciclo 4: uma rodada de negociacao com os AC e o AD."""

    def __init__(self, agent, message):
        super().__init__(agent=agent, message=message, is_initiator=True)

    def handle_propose(self, message):
        super().handle_propose(message)
        self.agent.collect_propose(message)

    def handle_all_proposes(self, proposes):
        super().handle_all_proposes(proposes)
        self.agent.try_close_round()


class MarketAgent(Agent):
    def __init__(self, aid, case, profiles, price, sensitivity):
        super().__init__(aid=aid, debug=False)
        self.case = case
        self.profiles, self.price = profiles, price
        self.v0, self.s = sensitivity

        # A rede ve a demanda REALIZADA, nao a prevista: e o que existe de fato.
        # A previsao serve para PROGRAMAR; o desvio entre as duas e o que a fase
        # de operacao corrige. Sem isso o desvio so existiria dentro dos agentes
        # e o OpenDSS nunca o veria, tornando a fase de operacao inobservavel.
        self.realized = realized_profiles(REALIZED_DAY) if USE_REALIZED else None
        self.p_init = {}
        self.q_init = {n: np.zeros(PERIODS) for n in case.network_storage_nodes}
        self.lam = {n: np.zeros(PERIODS) for n in case.prosumer_storage_nodes}
        # De quais nos cada concentrador cuida. Serve para enderecar o CFP do
        # ciclo 4: cada um recebe so o preco sombra dos seus.
        self._nos_do_concentrador = {f"concentrator_{c.name}": list(c.prosumer_storage)
                                     for c in case.concentrators}
        self.x = {}
        self.y = {}
        self.q = {}
        self.round = 0
        self.expected = ({f"concentrator_{c.name}" for c in case.concentrators}
                         | {"dso"})
        self.replied = set()
        self.retries = 0
        self.retransmissions = 0
        self.history = []
        self.converged = False
        self.pending_concentrators = set()
        self._negotiating = False

        self.mosaik_sim = MarketMosaikSim(self)
        self.round_behaviour = None
        self._timeout_call = None
        self._dispatch_timeout = None
        self.op_behaviour = None
        self.op_t = 0
        self.op_round = 0
        self.op_x = {}
        self.op_lam = {}
        self.op_result = None
        self.operation_log = []
        self.op_v_min_before = None

    def on_start(self):
        super().on_start()
        AGENTS[self.aid.localname] = self

    # ---- ciclo 1: cada AC pede aos seus AP ---------------------------------
    def start_negotiation(self):
        display_message(self.aid.localname, "iniciando a fase de programacao")
        self.pending_concentrators = {c.name for c in self.case.concentrators}
        begin_cycle(0)
        for c in self.case.concentrators:
            AGENTS[f"concentrator_{c.name}"].request_schedules()

    def concentrator_ready(self, name):
        self.pending_concentrators.discard(name)
        if self.pending_concentrators or self._negotiating:
            return
        self._negotiating = True
        close_cycle(0)
        # ---- ciclo 2: o AD pede aos AC as programacoes agregadas -----------
        begin_cycle(1)
        AGENTS["dso"].request_reports(
            [f"concentrator_{c.name}" for c in self.case.concentrators],
            self._on_reports)

    def _on_reports(self, reports):
        close_cycle(1)
        for payload in reports.values():
            for node, series in payload.get("p_init", {}).items():
                self.p_init[int(node)] = np.array(series)

        # Politica para quem nao respondeu ao CFP nem apos as retransmissoes: a
        # flexibilidade dele nao entra na negociacao (programacao nula). E uma
        # decisao de mercado, nao um detalhe de implementacao, e muda o
        # resultado: o prosumidor silencioso perde a chance de ser remunerado
        # pelo ajuste, e a rede perde o recurso dele.
        ausentes = [n for n in self.case.prosumer_storage_nodes if n not in self.p_init]
        if ausentes:
            display_message(self.aid.localname,
                            f"sem programacao de {ausentes}: entram com zero")
            for n in ausentes:
                self.p_init[n] = np.zeros(PERIODS)
        if not NEGOTIATE:
            display_message(self.aid.localname,
                            f"{len(self.p_init)} programacoes recebidas; "
                            "LINHA DE BASE, sem negociacao")
            self.y = dict(self.p_init)
            self.q = {n: np.zeros(PERIODS) for n in self.case.network_storage_nodes}
            self.converged = True
            self.mosaik_sim.release_step()
            return
        display_message(self.aid.localname,
                        f"{len(self.p_init)} programacoes recebidas; abrindo a negociacao")
        self.next_round()

    # ---- ciclo 4: rodadas de negociacao ------------------------------------
    def next_round(self):
        self.round += 1
        # Ciclo 3: cada rodada da descoberta do preco sombra e uma passagem
        # completa AM -> AC/AD -> AM, e cada uma tem que caber na fatia do ciclo.
        begin_cycle(2)
        self.replied = set()
        self.retries = 0
        self._send_cfp(sorted(self.expected))

    def _cfp_payload(self, receiver):
        """Conteudo do CFP da rodada, ENDERECADO ao destinatario.

        Quem consome o que, lido dos dois `handle_cfp`: o concentrador usa
        apenas o `lam` DOS NOS DELE, e tira o `p_init` da propria memoria; o DSO
        usa `lam`, `p_init` e `q_init` de todos, porque a restricao de tensao e
        global. Mandar o pacote inteiro para todos era desperdicio puro, e era o
        que fazia o CFP nao trafegar na rede da tese: 35.663 bytes em 281
        quadros, com 99,93% de perda no pior enlace.

        As series vao com 6 casas decimais. A tolerancia da negociacao e 1e-4 no
        criterio de parada, quatro ordens de grandeza acima do que se descarta.
        """
        base = {"action": "REOPTIMIZE", "round": self.round}
        if receiver != "dso":
            nos = self._nos_do_concentrador.get(receiver, [])
            base["lam"] = {str(n): _curto(self.lam[n]) for n in nos}
            return base
        pros = self.case.prosumer_storage_nodes
        base["lam"] = {str(n): _curto(self.lam[n]) for n in pros}
        # `p_init` e `q_init` so vao na PRIMEIRA rodada. O primeiro e constante
        # ao longo da negociacao (e a programacao que os prosumidores
        # propuseram no ciclo 1) e o segundo e saida do proprio DSO. Reenviar os
        # dois a cada rodada era mandar de volta o que o destinatario ja tem.
        if self.round <= 1:
            base["p_init"] = {str(n): _curto(self.p_init[n]) for n in pros}
            base["q_init"] = {str(n): _curto(self.q_init[n])
                              for n in self.case.network_storage_nodes}
        return base

    def _send_cfp(self, receivers):
        """Envia (ou reenvia) o CFP da rodada corrente aos destinatarios dados.

        Uma mensagem POR destinatario, e nao uma com varios: o conteudo agora
        depende de quem recebe. A contabilidade da rodada e propria, por
        remetente (`collect_propose`), entao dividir a mensagem nao afeta o
        fecho do ciclo, e o reenvio a um subconjunto ja era feito assim.
        """
        for name in receivers:
            self._enviar_cfp_a(name)
        # Timeout proprio, UM por rodada e nao um por destinatario: o
        # `FipaContractNetProtocol` do PADE tem o dele comentado, entao uma
        # proposta perdida travaria a rodada e o Mosaik.
        if self._timeout_call is not None and self._timeout_call.active():
            self._timeout_call.cancel()
        self._timeout_call = self.call_later(ROUND_TIMEOUT, self._on_timeout)

    def _enviar_cfp_a(self, name):
        message = ACLMessage(ACLMessage.CFP)
        message.set_protocol(ACLMessage.FIPA_CONTRACT_NET_PROTOCOL)
        message.add_receiver(AID(name=name))
        _set_content(message, self._cfp_payload(name))

        if self.round_behaviour is None:
            self.round_behaviour = MarketInitiator(self, message)
            self.behaviours.append(self.round_behaviour)
        else:
            self.round_behaviour.message = message
        self.round_behaviour.on_start()

    def _on_timeout(self):
        faltando = sorted(self.expected - self.replied)
        if self.retries < MAX_RETRIES:
            self.retries += 1
            self.retransmissions += len(faltando)
            display_message(self.aid.localname,
                            f"rodada {self.round}: timeout, retransmitindo o CFP "
                            f"para {faltando} (tentativa {self.retries}/{MAX_RETRIES})")
            self._send_cfp(faltando)
            return
        display_message(self.aid.localname,
                        f"rodada {self.round}: TIMEOUT definitivo, sem resposta de "
                        f"{faltando} apos {MAX_RETRIES} tentativas")
        self.converged = False
        self._finish()

    def collect_propose(self, message):
        """Registra UMA proposta e tenta fechar a rodada.

        A contabilidade e propria, por remetente e por numero de rodada, em vez
        de depender de `received_qty == cfp_qty` do `FipaContractNetProtocol`.
        Com entrega instantanea os dois coincidem; com atraso, nao: as respostas
        chegam intercaladas e o protocolo do PADE conclui o ciclo com o conjunto
        incompleto. Foi assim que o ciclo 1 agregou 19 das 25 programacoes com a
        camada de rede ligada, mesmo sem nenhuma perda.
        """
        payload = _parse(message.content)
        if payload.get("round") != self.round:
            # Resposta de uma rodada anterior: ignorar, senao o lambda seria
            # atualizado com um residuo que mistura duas rodadas.
            return
        sender = getattr(message.sender, "localname", "?")
        self.replied.add(sender)
        if "schedule" in payload:                          # concentrador
            for node, series in payload["schedule"].items():
                self.x[int(node)] = np.array(series)
        else:                                              # DSO
            self.y = {int(n): np.array(v) for n, v in payload["p"].items()}
            self.q = {int(n): np.array(v) for n, v in payload["q"].items()}
        self.try_close_round()

    def try_close_round(self):
        pros = self.case.prosumer_storage_nodes
        if self.replied != self.expected:
            return
        if not self.y or any(n not in self.x for n in pros):
            return
        if self._timeout_call is not None and self._timeout_call.active():
            self._timeout_call.cancel()
        self.replied = set()

        c3 = close_cycle(2, f" (rodada {self.round})")
        residual = np.array([self.x[n] - self.y[n] for n in pros])
        d_lam = ALPHA * residual
        for i, n in enumerate(pros):
            self.lam[n] = self.lam[n] + d_lam[i]

        self.history.append({
            "round": self.round,
            "d_lambda_max": float(np.abs(d_lam).max()),
            "residual_max": float(np.abs(residual).max()),
            "lambda_max": float(max(np.abs(v).max() for v in self.lam.values())),
            # Programacao que cada lado adotou NESTA rodada, por no. E o dado das
            # Figuras 51 e 52 da tese, que comparam o que o AC propoe com o que o
            # AD aceita ao longo das iteracoes.
            "x": {str(n): self.x[n].tolist() for n in pros if n in self.x},
            "y": {str(n): self.y[n].tolist() for n in pros if n in self.y},
            "cycle3_net_s": c3["max_delay"] if c3 else None,
        })
        extra = f" rede={c3['max_delay']:.0f} s" if c3 else ""
        display_message(self.aid.localname,
                        f"rodada {self.round}: |dlambda|={np.abs(d_lam).max():.3e} "
                        f"|x-y|={np.abs(residual).max():.4f} kW{extra}")

        if np.abs(d_lam).max() <= EPS:
            self.converged = True
            self._accept()
        elif self.round >= MAX_ROUNDS:
            self.converged = False
            self._finish()
        else:
            self._reject()
            self.call_later(0.05, self.next_round)

    def _decision(self, performative):
        """Fecha a rodada com ACCEPT ou REJECT para todos os participantes.

        A mensagem carrega apenas o numero da rodada. Ela levava tambem o preco
        sombra dos 25 nos por 96 intervalos, em precisao total, e NINGUEM lia:
        nao ha `handle_reject_propose` nem `handle_accept_propose` em lugar
        nenhum, e o preco da rodada seguinte ja vai no proximo CFP.

        Medido, isso custava 51.898 bytes por destinatario POR RODADA, ou 409
        quadros. No enlace de PER 0,400 da rede da tese a entrega de um
        datagrama desse tamanho e 0,00%, e sem receber o fecho da rodada o
        participante nao aceitava o CFP seguinte. Era a maior mensagem da
        negociacao inteira, maior que o proprio CFP.
        """
        answer = ACLMessage(performative)
        answer.set_protocol(ACLMessage.FIPA_CONTRACT_NET_PROTOCOL)
        for c in self.case.concentrators:
            answer.add_receiver(AID(name=f"concentrator_{c.name}"))
        answer.add_receiver(AID(name="dso"))
        _set_content(answer, {"round": self.round})
        self.send(answer)

    def _reject(self):
        self._decision(ACLMessage.REJECT_PROPOSAL)

    def _accept(self):
        self._decision(ACLMessage.ACCEPT_PROPOSAL)
        # A negociacao so termina quando a programacao acordada tiver CHEGADO a
        # quem a executa. O DSO publica aos concentradores, que despacham o
        # armazenamento de rede e repassam aos prosumidores; a confirmacao sobe
        # de volta e cai em `dispatch_done`.
        display_message(self.aid.localname, "acordo fechado; iniciando o despacho")
        self._dispatch_timeout = self.call_later(ROUND_TIMEOUT, self._on_dispatch_timeout)
        AGENTS["dso"].dispatch(
            {n: self.y[n].tolist() for n in self.case.prosumer_storage_nodes},
            {n: self.q[n].tolist() for n in self.case.network_storage_nodes})

    # ---- fase de operacao, a cada 15 min ----------------------------------
    def start_operation(self, t):
        """Fase de operacao do intervalo t (subsecao 6.1.2).

        Os mesmos tres ciclos da programacao, com a programacao reduzida a UM
        intervalo, e nos mesmos instantes da janela de 15 min: AC com seus AP no
        minuto 1, AD com os AC no minuto 5, AM com AC e AD no minuto 10.

        O ciclo 3 aqui tem dois niveis. Primeiro o DSO tenta corrigir o desvio so
        com o armazenamento de rede; se nao bastar, o agente de mercado abre o
        leilao, que e a mesma decomposicao dual sobre um periodo so.
        """
        self.op_t = t
        # Ciclo 1: cada AC pede aos seus AP a programacao do intervalo.
        begin_cycle(0, t)
        self.pending_op_concentrators = {c.name for c in self.case.concentrators}
        for c in self.case.concentrators:
            AGENTS[f"concentrator_{c.name}"].request_schedules(t=t,
                                                               on_ready=self._op_cycle2)
        return

    def _op_cycle2(self, name):
        """Ciclo 2 da operacao: o AD pede aos AC o que eles agregaram."""
        self.pending_op_concentrators.discard(name)
        if self.pending_op_concentrators:
            return
        close_cycle(0, f" (t={self.op_t})")
        begin_cycle(1, self.op_t)
        AGENTS["dso"].request_reports(
            [f"concentrator_{c.name}" for c in self.case.concentrators],
            self._op_cycle3, t=self.op_t)

    def _op_cycle3(self, reports):
        close_cycle(1, f" (t={self.op_t})")
        begin_cycle(2, self.op_t)
        self._start_operation_check(self.op_t)

    def _start_operation_check(self, t):
        self.op_t = t
        self.op_round = 0
        self.op_lam = {n: np.zeros(1) for n in self.case.prosumer_storage_nodes}
        self.op_retries = 0
        self.op_violations_before = 0
        self.replied = set()
        payload = {
            "action": "OPERATE", "t": t, "round": 0,
            "lam": {str(n): [0.0] for n in self.case.prosumer_storage_nodes},
            "p_init": {str(n): [float(self.y[n][t])]
                       for n in self.case.prosumer_storage_nodes},
            "q_init": {str(n): [float(self.q[n][t])]
                       for n in self.case.network_storage_nodes},
            "soc_rede": self.soc_rede(t),
        }
        self._payload = payload
        message = ACLMessage(ACLMessage.CFP)
        message.set_protocol(ACLMessage.FIPA_CONTRACT_NET_PROTOCOL)
        message.add_receiver(AID(name="dso"))
        _set_content(message, payload)
        if self.op_behaviour is None:
            self.op_behaviour = OperationInitiator(self, message)
            self.behaviours.append(self.op_behaviour)
        else:
            self.op_behaviour.message = message
        self.op_behaviour.on_start()
        self._timeout_call = self.call_later(ROUND_TIMEOUT, self._on_op_timeout)

    def _on_op_timeout(self):
        """Retransmite ao que falta, como os ciclos 1 e 4 ja faziam.

        Sem isto, uma resposta perdida no leilao encerrava o intervalo sem
        correcao nenhuma, ou, antes da correcao do cancelamento acima, travava a
        co-simulacao.
        """
        faltando = sorted(self.expected - self.replied) if self.op_round else []
        if faltando and self.op_retries < MAX_RETRIES:
            self.op_retries += 1
            display_message(self.aid.localname,
                            f"t={self.op_t}: timeout no leilao, retransmitindo "
                            f"para {faltando} ({self.op_retries}/{MAX_RETRIES})")
            self._enviar_cfp_operacao(faltando)
            return
        display_message(self.aid.localname,
                        f"t={self.op_t}: TIMEOUT na operacao"
                        + (f", sem resposta de {faltando}" if faltando else ""))
        self.mosaik_sim.release_step()

    def soc_rede(self, t):
        """Estado de carga de cada armazenamento de REDE no inicio do intervalo.

        Integra o despacho JA APLICADO nos intervalos anteriores, a partir da
        fracao inicial. Sem isto cada janela resolvia com a bateria de volta ao
        estado inicial, o que a tornava fonte de energia infinita: 8 kW nas 95
        janelas dao 190 kWh de um dispositivo de 20 kWh. Era por isso que o
        armazenamento de rede sempre bastava e o leilao nunca abria.
        """
        from market_opentes.config import DT_H
        from market_opentes.optimization import INIT_SOC_FRACTION
        out = {}
        for n, st in self.case.network_storage.items():
            soc = INIT_SOC_FRACTION * st.max_soc_kwh
            soc += float(np.sum(self.q[n][:t])) * DT_H
            out[str(n)] = float(np.clip(soc, st.min_soc_kwh, st.max_soc_kwh))
        return out

    def _cancela_timeout_op(self):
        if self._timeout_call is not None and self._timeout_call.active():
            self._timeout_call.cancel()

    def collect_operation(self, message):
        payload = _parse(message.content)
        t = self.op_t

        if self.op_round == 0:
            # Nivel 1: um destinatario so, o DSO. Chegou a resposta, acabou.
            self._cancela_timeout_op()
            # Resposta do primeiro nivel. A tensao ANTES da intervencao so e
            # medida aqui; se o leilao abrir, o payload dele substitui
            # `op_result` e o valor se perderia.
            self.op_v_min_before = payload.get("v_min_before")
            self.op_violations_before = payload.get("violations_before", 0)
            self.op_result = payload
            if payload["violations_after"] == 0:
                self._apply_operation(payload)
            # O leilao de tempo real abre SEMPRE, e nao so quando o
            # armazenamento de rede nao basta.
            #
            # O desenho anterior, de dois niveis com o leilao como contingencia,
            # era invencao nossa. Medido, ele nunca abria: a correcao de tensao
            # necessaria e de 0,51 mpu em media e o desvio maximo e de 0,871 kW,
            # contra 184 kW de capacidade de armazenamento de rede. Ele sobra por
            # duas ordens de grandeza, entao a contingencia jamais dispara.
            #
            # No `market_agent.py` do trabalho original o `MARKET_AUCTION` e
            # disparado por tempo, uma vez por janela, para todos os
            # concentradores e o DSO, sem teste de violacao nenhum. Um mercado
            # spot de tempo real liquida sempre, inclusive quando nao ha o que
            # corrigir; e o que da conteudo ao ciclo 3 e as Figuras 56 e 57.
            if OP_AUCTION_ALWAYS or payload["violations_after"]:
                self._op_next_round()
                return
            self._finish_operation("resolvido pelo armazenamento de rede"
                                   if payload["violations_before"]
                                   else "sem violacao")
            return

        # Rodada do leilao: junta concentradores e DSO. O timeout NAO pode ser
        # cancelado aqui: sao seis destinatarios, e cancelar na primeira
        # resposta deixava o agente esperando para sempre pelas que faltavam.
        # Como o leilao so abre quando o armazenamento de rede nao basta, o
        # defeito ficou latente ate a fase de operacao passar a agir.
        sender = getattr(message.sender, "localname", "?")
        self.replied.add(sender)
        if "schedule" in payload:
            for node, series in payload["schedule"].items():
                self.op_x[int(node)] = np.array(series)
        else:
            self.op_result = payload
        if self.replied != self.expected or not self.op_result:
            return
        self._cancela_timeout_op()

        pros = self.case.prosumer_storage_nodes
        y_op = {n: np.array(self.op_result["p"][str(n)]) for n in pros}
        residual = np.array([self.op_x[n] - y_op[n] for n in pros])
        for i, n in enumerate(pros):
            self.op_lam[n] = self.op_lam[n] + ALPHA * residual[i]

        if (np.abs(ALPHA * residual).max() <= EPS
                or self.op_round >= OP_MAX_ROUNDS
                or self.op_result["violations_after"] == 0):
            self._apply_operation(self.op_result)
            # Com o leilao liquidando em toda janela, o motivo precisa dizer se
            # havia o que corrigir; senao as 95 janelas ficam indistinguiveis.
            houve = self.op_violations_before
            self._finish_operation(
                f"leilao em {self.op_round} rodadas"
                + ("" if houve else " (sem violacao)"))
        else:
            self._op_next_round()

    def _op_next_round(self):
        self.op_round += 1
        self.op_x = {}
        self.op_result = None
        self.replied = set()
        t = self.op_t
        payload = {
            "action": "OPERATE_AUCTION", "t": t, "round": self.op_round,
            "lam": {str(n): self.op_lam[n].tolist()
                    for n in self.case.prosumer_storage_nodes},
            "p_init": {str(n): [float(self.y[n][t])]
                       for n in self.case.prosumer_storage_nodes},
            "q_init": {str(n): [float(self.q[n][t])]
                       for n in self.case.network_storage_nodes},
            "soc_rede": self.soc_rede(t),
        }
        self._payload = payload
        self.op_retries = 0
        self._enviar_cfp_operacao(sorted(self.expected))

    def _enviar_cfp_operacao(self, receivers):
        """Envia (ou reenvia) o CFP do leilao de operacao aos destinatarios dados."""
        message = ACLMessage(ACLMessage.CFP)
        message.set_protocol(ACLMessage.FIPA_CONTRACT_NET_PROTOCOL)
        for name in receivers:
            message.add_receiver(AID(name=name))
        _set_content(message, self._payload)
        self.op_behaviour.message = message
        self.op_behaviour.on_start()
        self._cancela_timeout_op()
        self._timeout_call = self.call_later(ROUND_TIMEOUT, self._on_op_timeout)

    def _apply_operation(self, payload):
        """Grava a correcao do intervalo na programacao que vai para a rede."""
        t = self.op_t
        for node, series in payload["p"].items():
            self.y[int(node)][t] = float(series[0])
        for node, series in payload["q"].items():
            self.q[int(node)][t] = float(series[0])

    def _finish_operation(self, motivo):
        c3 = close_cycle(2, f" (t={self.op_t})")
        r = self.op_result or {}
        self.operation_log.append({
            "t": self.op_t, "motivo": motivo,
            "cycle3_net_s": c3["max_delay"] if c3 else None,
            "deviation_kw": r.get("deviation", 0.0),
            "v_min_before": r.get("v_min_before", self.op_v_min_before),
            "v_min_after": r.get("v_min_after"),
            # Mesma preservacao que `v_min_before`: quando o leilao abre, o
            # payload dele substitui `op_result` e a contagem de violacoes ANTES
            # da intervencao se perderia. Sem isto, uma janela que exigiu leilao
            # era registrada como se nao tivesse tido violacao nenhuma, o que
            # falseia a estatistica da fase de operacao.
            "violations_before": r.get("violations_before",
                                       self.op_violations_before),
            "violations_after": r.get("violations_after", 0),
            "rounds": self.op_round,
        })
        if r.get("violations_before"):
            display_message(self.aid.localname,
                            f"t={self.op_t}: {r.get('violations_before')} violacoes, "
                            f"{motivo}, restam {r.get('violations_after', 0)}")
        self.mosaik_sim.release_step()

    def dispatch_done(self):
        if self._dispatch_timeout is not None and self._dispatch_timeout.active():
            self._dispatch_timeout.cancel()
        display_message(self.aid.localname, "despacho confirmado por todos")
        self._finish()

    def _on_dispatch_timeout(self):
        display_message(self.aid.localname,
                        "TIMEOUT no despacho: nem todos confirmaram")
        self._finish()

    def _finish(self):
        status = "convergiu" if self.converged else "NAO convergiu"
        display_message(self.aid.localname,
                        f"negociacao encerrada: {status} em {self.round} rodadas, "
                        f"{self.retransmissions} retransmissoes")
        self.mosaik_sim.release_step()


# ---------------------------------------------------------------------------
# Ponte com o Mosaik
# ---------------------------------------------------------------------------

class MarketMosaikSim(MosaikCon):
    """Um unico simulador Mosaik para todo o sistema multi-agentes."""

    def __init__(self, agent):
        super().__init__(MOSAIK_MODELS, agent)
        self.step_size = STEP_SIZE
        self.entities = {}       # eid -> no

    def init(self, sid, time_resolution=1.0, step_size=STEP_SIZE, **kwargs):
        self.step_size = int(step_size)
        return MOSAIK_MODELS

    def create(self, num, model, node=None, **params):
        eid = f"node_{node}"
        self.entities[eid] = int(node)
        return [{"eid": eid, "type": model}]

    def step(self, time, inputs, max_advance=0):
        self.time = time
        if time == 0:
            # A negociacao acontece antes do dia comecar. O passo fica ABERTO
            # ate a rodada fechar; quem o libera e o `release_step`.
            self.agent.call_later(0.1, self.agent.start_negotiation)
            return None
        if OPERATION:
            # Fase de operacao: a cada 15 min o DSO confere o desvio realizado.
            # O passo fica aberto do mesmo jeito.
            t = min(int(time // self.step_size), PERIODS - 1)
            self.agent.call_later(0.05, self.agent.start_operation, t)
            return None
        return time + self.step_size

    def release_step(self):
        self.step_done()

    def get_data(self, outputs):
        t = min(int(self.time // self.step_size), PERIODS - 1)
        agent = self.agent
        data = {}
        for eid, attrs in outputs.items():
            node = self.entities[eid]
            data[eid] = {}
            for attr in attrs:
                if attr == "P_kw":
                    data[eid][attr] = float(agent.node_power(node, t))
                elif attr == "Q_kvar":
                    data[eid][attr] = float(agent.node_reactive(node, t))
                elif attr == "lambda_max":
                    data[eid][attr] = float(
                        max(np.abs(v).max() for v in agent.lam.values()))
                elif attr == "round_count":
                    data[eid][attr] = float(agent.round)
        return data


def _node_power(self, node, t):
    """Potencia total do no: demanda liquida mais os armazenamentos acordados.

    A demanda e a REALIZADA quando ha fase de operacao; a prevista, quando nao
    ha. Nos dois casos e a mesma grandeza fisica para todos os cenarios
    comparados, entao a comparacao entre com e sem negociacao continua valida.
    """
    fonte = self.realized if self.realized is not None else self.profiles
    total = float(fonte.get(node, np.zeros(PERIODS))[t])
    if node in self.y:
        total += float(self.y[node][t])
    if node in self.q:
        total += float(self.q[node][t])
    return total


def _node_reactive(self, node, t):
    """Reativo do no: fator de potencia 0,9 sobre a demanda, mais o do armazenamento.

    Com `MARKET_STORAGE_PF=none`, que e o padrao, o armazenamento nao injeta
    reativo e sobra a hipotese dQ = 0 da Eq. 6.16 da tese. Com um fator de
    potencia configurado, o reativo do dispositivo entra AQUI tambem, e nao so no
    modelo do DSO: se entrasse so num lado, a restricao passaria a ser resolvida
    contra uma rede que se comporta de outro jeito, que e pior que ignorar o
    termo nos dois.
    """
    fonte = self.realized if self.realized is not None else self.profiles
    q = float(fonte.get(node, np.zeros(PERIODS))[t]) * 0.4843
    if STORAGE_TAN_PHI:
        if node in self.y:
            q += float(self.y[node][t]) * STORAGE_TAN_PHI
        if node in self.q:
            q += float(self.q[node][t]) * STORAGE_TAN_PHI
    return q


MarketAgent.node_power = _node_power
MarketAgent.node_reactive = _node_reactive


# ---------------------------------------------------------------------------

def build_agents():
    case = load_case(CONFIG_JSON)
    profiles, price = load_profiles()
    sensitivity = load_sensitivity()[1:]

    agents = []
    port = BASE_PORT

    market = MarketAgent(AID(name=f"market@{HOST}:{port}"), case, profiles, price,
                         sensitivity)
    agents.append(market)
    port += 1

    agents.append(SolverAgent(AID(name=f"solver@{HOST}:{port}"), case, profiles,
                              price, sensitivity))
    port += 1

    agents.append(DSOAgent(AID(name=f"dso@{HOST}:{port}"), market.dispatch_done))
    port += 1

    concentrador_do_no = {}
    for c in case.concentrators:
        agents.append(ConcentratorAgent(AID(name=f"concentrator_{c.name}@{HOST}:{port}"),
                                        c.name, c.nodes, c.prosumer_storage,
                                        market.concentrator_ready,
                                        network_storage=c.network_storage))
        for node in c.nodes:
            concentrador_do_no[node] = f"concentrator_{c.name}"
        port += 1

    for node in case.prosumer_nodes:
        agents.append(ProsumerAgent(AID(name=f"prosumer{node}@{HOST}:{port}"), node,
                                    concentrador_do_no[node]))
        port += 1

    return case, agents


def _install_network(agents, case=None):
    """Camada de rede opcional entre os agentes (Fase 5)."""
    import network_link
    backend = os.environ.get("NET_BACKEND", "ideal")
    if backend == "ideal" and not os.environ.get("NET_TRACE"):
        return None
    # O 6TiSCH precisa saber onde cada agente esta: o PER e funcao da distancia.
    node_map = network_link.node_map_from_case(case) if case is not None else None
    link = network_link.install(agents, backend, os.environ.get("NET_TRACE"),
                                float(os.environ.get("NET_TIME_SCALE", "1.0")),
                                node_map=node_map)
    if backend == "omnet":
        info = link.backend.info()
        print(f"[rede] 6TiSCH: {info['nodes']} nos, {info['links']} enlaces, "
              f"PER medio {info['mean_link_per']:.4f}, "
              f"{info['mean_hops']:.2f} saltos em media, "
              f"{info['unreachable_pairs']} pares sem rota", flush=True)
    return link


RUN_DIR = Path(os.environ.get("MARKET_RUN_DIR", "/market/data/run"))


def _dump_run(market, link):
    """Grava o que a execucao produziu, para as figuras e tabelas."""
    try:
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            # Procedencia: sem isto, duas execucoes com configuracoes diferentes
            # sobrescrevem o mesmo arquivo e as figuras saem misturadas em
            # silencio. Ja aconteceu.
            "config": {
                "net_backend": os.environ.get("NET_BACKEND", "ideal"),
                "message_size": os.environ.get("NET_MESSAGE_SIZE", "real"),
                "realized_mode": os.environ.get("MARKET_REALIZED_MODE", "perturb"),
                "v_backoff": os.environ.get("MARKET_V_BACKOFF", "1e-3"),
                "max_rounds": MAX_ROUNDS,
                "scenarios": N_SCENARIOS,
                "storage_pf": os.environ.get("MARKET_STORAGE_PF", "none"),
                "operation": bool(OPERATION),
            },
            "rounds": market.round,
            "converged": market.converged,
            "history": market.history,
            "operation": market.operation_log,
            "cycles": link.cycles if link is not None else [],
            "cycle_budget_s": dict(zip(CYCLE_NAMES, CYCLE_BUDGET_S)),
            # Programacoes que se perderam de vez no ciclo 1 e entraram com
            # zero. Sem este numero a perda fica invisivel no resultado.
            "schedules_lost": sum(
                getattr(a, "sem_resposta", 0) for a in AGENTS.values()),
            "retransmissions": market.retransmissions,
        }
        (RUN_DIR / "run.json").write_text(json.dumps(payload))
        print(f"[mercado] execucao gravada em {RUN_DIR / 'run.json'}", flush=True)
    except Exception as exc:                       # nao derruba o encerramento
        print(f"[mercado] nao consegui gravar a execucao: {exc}", flush=True)


def start_market_loop(agents, case=None):
    """`start_loop` do PADE, mais o preenchimento do diretorio de agentes.

    O `Agent._send` so entrega a mensagem se o destinatario estiver em
    `agentInstance.table`, e quem preenche essa tabela e o AMS, um processo
    separado que o `pade start-runtime` sobe. Sem AMS, a tabela fica vazia e as
    mensagens sao DESCARTADAS EM SILENCIO (o aviso so sai com debug=True). Foi
    exatamente isso que travou a primeira execucao: os CFP saiam e nada voltava.

    Como aqui o conjunto de agentes e fixo e conhecido no arranque, a tabela e
    semeada direto. Isso dispensa o AMS, e tambem evita que o trafego de
    registro e de keep-alive dele polua a medicao de comunicacao da Fase 5.
    """
    reactor.suggestThreadPoolSize(30)
    for agent in agents:
        agent.update_ams(agent.ams)
        agent.on_start()
        agent.ILP = reactor.listenTCP(agent.aid.port, agent.agentInstance)

    directory = {agent.aid.localname: agent.aid for agent in agents}
    for agent in agents:
        agent.agentInstance.table.update(directory)

    # Sinal de prontidao: so agora as portas estao abertas. Quem espera por este
    # processo (o run.sh, o Mosaik) deve esperar por ESTA linha, e nao pela que
    # anuncia a criacao dos agentes, que sai antes do listenTCP.
    print(f"[market-mas] pronto: {len(agents)} agentes ouvindo a partir da porta "
          f"{BASE_PORT}", flush=True)

    link = _install_network(agents, case)
    globals()["LINK"] = link
    if link is not None:
        reactor.addSystemEventTrigger(
            "before", "shutdown",
            lambda: (print(f"[rede] {link.summary()}", flush=True), link.close()))

    # O historico e o registro da operacao so existiam na memoria do agente e
    # morriam com o processo. Sao a fonte das Figuras 51, 52 e 58 da tese.
    market = agents[0]
    reactor.addSystemEventTrigger("before", "shutdown",
                                  lambda: _dump_run(market, link))

    reactor.run()


if __name__ == "__main__":
    case, agents = build_agents()
    print(f"[market-mas] {len(agents)} agentes: 1 mercado, 1 solver, 1 DSO, "
          f"{len(case.concentrators)} concentradores, "
          f"{len(case.prosumer_storage_nodes)} prosumidores", flush=True)
    ams = {"name": HOST, "port": AMS_PORT}
    for agent in agents:
        agent.update_ams(ams)
    start_market_loop(agents, case)
