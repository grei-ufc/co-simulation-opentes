#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camada de rede para as mensagens FIPA: atraso, perda e telemetria.

Sucessor do `pade.simul` do PADE 2.2, que desviava toda mensagem ACL para um
`SimulAgent` e de la para o servidor ns-3, devolvendo o instante de entrega
(`market-simulation/pade-cosimul/pade/simul/simul_agent.py`). Esse modulo foi
removido no PADE 3.0 junto com o `mode='simulation'`, entao no PADE 3.0 o
`Agent.send` vai direto para `reactor.connectTCP` e nenhuma mensagem passa por
simulador de rede nenhum.

Aqui o desvio e reconstruido SEM tocar no nucleo do PADE, que e compartilhado
com os outros cenarios do repositorio: o `_send` do agente e substituido em
tempo de execucao (`install`), e a entrega passa a ser agendada pelo backend.

BACKENDS
--------
`ideal`    entrega tudo, sem atraso. E o caso de controle da Fase 5.
`lossy`    modelo fenomenologico igual ao do NetworkNode.cc do comm-opentes:
           sorteia a perda, e o atraso e propagacao + transmissao (tamanho da
           mensagem sobre a banda) + jitter exponencial. Permite rodar o
           experimento de perda sem depender do OMNeT++.
`omnet`    cliente ZMQ do servidor de rotas 6TiSCH do container `comm-tisch`
           (`comm-opentes/Tisch.cc`, configuracao `-c tisch`). E a rede LPWA da
           tese: PER por distancia pelo modelo de Pister-Hack, matriz de
           adjacencia com limiar de PER 0,5, roteamento multi-salto e atraso
           vindo do slotframe do TSCH. Cada envio vira uma consulta com origem,
           destino e tamanho, e a resposta traz atraso e descarte daquele par.

TEMPO
-----
O atraso e aplicado no relogio do reactor do Twisted, porque a negociacao inteira
acontece DENTRO de um passo do Mosaik, com o relogio da co-simulacao parado.
`time_scale` comprime esse atraso: a rede LPWA da tese entrega entre 10 e 90 s
por mensagem, o que faria cada rodada levar minutos de relogio real. Com
`time_scale = 0.01` o padrao temporal e preservado e o experimento fica viavel.
O valor NAO simulado (o atraso nominal) e o que vai para a telemetria.

IDENTIDADE DOS AGENTES
----------------------
O canal `lossy` so precisa do tamanho da mensagem. O 6TiSCH precisa saber QUEM
fala com QUEM, porque o PER depende da distancia entre os dois radios. O `route`
passa origem e destino em todos os backends, e o `node_map` traduz o nome local
do agente para o nome da posicao no Apendice B da tese.
"""

import csv
import os
import random
import threading
import time

from pade.acl.messages import ACLMessage
from twisted.internet import reactor

# Parametros do canal, com os mesmos defaults do comm-opentes/omnetpp.ini.
BANDWIDTH_BPS = float(os.environ.get("NET_BANDWIDTH_BPS", "50000"))
DROP_PROBABILITY = float(os.environ.get("NET_DROP_PROBABILITY", "0.0"))
JITTER_MEAN_S = float(os.environ.get("NET_JITTER_MEAN", "0.05"))
PROPAGATION_S = float(os.environ.get("NET_PROPAGATION", "0.010"))
TIME_SCALE = float(os.environ.get("NET_TIME_SCALE", "1.0"))
SEED = int(os.environ.get("NET_SEED", "0"))

# Tamanho da mensagem informado a rede. `real` usa o conteudo serializado, que e
# o que de fato trafega. `thesis` reproduz os valores DECLARADOS pelo trabalho
# original, que sao arbitrarios e nao tem relacao com o conteudo. A opcao existe
# para tornar a diferenca mensuravel, nao para escolher a mentira.
#
# O original usa TRES classes, e nao duas. Varrendo os 42 `set_message_length`
# de `market_agent.py`, `bess_agent.py`, `dso_agent.py` e `prosumer_agent.py`:
#
#   100 bytes fixos        CFP, AGREE, SUBSCRIBE e INFORM de confirmacao ('OK',
#                          confirmacao de assinatura). E a classe MAIS FREQUENTE,
#                          porque um CFP enderecado a N destinatarios conta N
#                          vezes.
#   uniforme 100 a 500     um caso so: a PROPOSE do prosumidor no leilao de tempo
#                          real, ou seja, na fase de OPERACAO
#                          (`prosumer_agent.py`, linha 310).
#   uniforme 1000 a 1500   PROPOSE, REQUEST e INFORM que carregam conteudo
#                          serializado, e ACCEPT/REJECT_PROPOSAL que carregam o
#                          multiplicador de Lagrange.
#
# Uma versao anterior deste arquivo lia so o `market_agent.py` e mapeava CFP para
# 100 e TODO o resto para 1000 a 1500. Isso inverte a distribuicao da Figura 59
# da tese, em que cerca de 94% das mensagens ficam abaixo de 500 bytes: passavam
# a ser a minoria. E como o tempo de entrega no 6TiSCH cresce com o numero de
# quadros, e 100 bytes cabem em um quadro contra 8 a 12 para 1000 a 1500, o erro
# multiplicava por quase dez o tempo de rede da maioria das mensagens.
MESSAGE_SIZE = os.environ.get("NET_MESSAGE_SIZE", "real")
THESIS_CONTROL_BYTES = 100
THESIS_BID_RANGE = (100, 500)
THESIS_PAYLOAD_RANGE = (1000, 1500)
# Abaixo disto um INFORM e confirmacao, e nao carga util. O original separa os
# dois casos por construcao ('OK' contra `pickle.dumps(config)`); aqui a
# separacao vem do conteudo real, que e a mesma distincao medida.
THESIS_CONTROL_MAX_BYTES = 64
# Performativas que o original sempre manda com 100 bytes.
CONTROLE = frozenset(x for x in (
    getattr(ACLMessage, n, None)
    for n in ("CFP", "AGREE", "SUBSCRIBE", "REFUSE", "FAILURE")) if x is not None)


class IdealBackend:
    """Canal perfeito: nada se perde, nada atrasa."""

    name = "ideal"

    def transmit(self, size_bytes, sender=None, receiver=None):
        return 0.0, False


class LossyBackend:
    """Perda por sorteio e atraso de propagacao, transmissao e jitter."""

    name = "lossy"

    def __init__(self, drop_probability=DROP_PROBABILITY, bandwidth_bps=BANDWIDTH_BPS,
                 jitter_mean=JITTER_MEAN_S, propagation=PROPAGATION_S, seed=SEED):
        self.drop_probability = drop_probability
        self.bandwidth_bps = bandwidth_bps
        self.jitter_mean = jitter_mean
        self.propagation = propagation
        self.rng = random.Random(seed)

    def transmit(self, size_bytes, sender=None, receiver=None):
        if self.rng.random() < self.drop_probability:
            return 0.0, True
        transmission = (size_bytes * 8.0) / self.bandwidth_bps
        jitter = self.rng.expovariate(1.0 / self.jitter_mean) if self.jitter_mean > 0 else 0.0
        return self.propagation + transmission + jitter, False


class OmnetBackend:
    """Cliente do servidor de rotas 6TiSCH do container `comm-tisch`.

    Uma consulta por envio, sincrona. O custo e de dezenas de microssegundos por
    mensagem em ZMQ local, desprezivel perto do que a propria rede simulada
    cobra, e mantem a ordem dos eventos: quem pergunta primeiro e atendido
    primeiro, que e o que o servidor OMNeT++ supoe.

    O acesso e serializado por trava. Um socket REQ tem maquina de estados
    propria, alterna send e recv e NAO e seguro para uso concorrente; o
    `SolverProtocol` responde de dentro de um `defer_to_thread`, entao ha mais de
    uma thread enviando. Sem a trava o socket para com "Operation cannot be
    accomplished in current state" no meio da negociacao.
    """

    name = "omnet"

    def __init__(self, host=None, port=None, node_map=None, timeout_ms=120000):
        import zmq

        self.host = host or os.environ.get("OMNET_HOST", "comm-tisch")
        self.port = int(port or os.environ.get("OMNET_NET_PORT", "5556"))
        self.node_map = node_map or {}
        self.unmapped = set()
        self.timeout_ms = timeout_ms
        self._zmq = zmq
        self._lock = threading.Lock()
        self._ctx = zmq.Context.instance()
        self._sock = None
        self._open()
        self.hops = []

    def _open(self):
        self._sock = self._ctx.socket(self._zmq.REQ)
        self._sock.setsockopt(self._zmq.RCVTIMEO, self.timeout_ms)
        self._sock.setsockopt(self._zmq.LINGER, 0)
        self._sock.connect(f"tcp://{self.host}:{self.port}")

    def _ask(self, payload):
        with self._lock:
            try:
                self._sock.send_json(payload)
                return self._sock.recv_json()
            except self._zmq.ZMQError:
                # Um REQ que perdeu o sincronismo nao volta sozinho: so refazendo
                # o socket. Melhor cair aqui, com a causa a vista, do que seguir
                # com uma rede que nao responde.
                self._sock.close()
                self._open()
                raise

    def _name(self, aid_name):
        if aid_name in self.node_map:
            return self.node_map[aid_name]
        # Sem posicao no Apendice B o no nao existe no modelo de radio. O
        # servidor entrega sem atraso e o registro fica aqui, para nao passar
        # despercebido.
        self.unmapped.add(aid_name)
        return aid_name

    def info(self):
        return self._ask({"action": "info"})

    def transmit(self, size_bytes, sender=None, receiver=None):
        reply = self._ask({"action": "route",
                           "src": self._name(sender),
                           "dst": self._name(receiver),
                           "bytes": int(size_bytes)})
        self.hops.append(int(reply.get("hops", 0)))
        return float(reply.get("delay", 0.0)), bool(reply.get("dropped", False))

    def close(self):
        # Fecha so o socket. O `stop` encerraria a simulacao OMNeT++ do outro
        # lado, e o servidor e compartilhado: quem controla o ciclo de vida dele
        # e o compose, nao o cliente.
        self._sock.close()


BACKENDS = {"ideal": IdealBackend, "lossy": LossyBackend, "omnet": OmnetBackend}


class NetworkLink:
    """Desvia o envio de mensagens dos agentes para o modelo de rede."""

    def __init__(self, backend, trace_path=None, time_scale=TIME_SCALE):
        self.backend = backend
        self.time_scale = time_scale
        self._rng = random.Random(SEED)
        # Contabilidade por ciclo. A tese posiciona os tres ciclos de troca de
        # mensagens nos minutos 1, 5 e 10 da janela de 15 min, o que so significa
        # alguma coisa se der para dizer QUANTO tempo de rede cada ciclo gastou.
        # Como as mensagens de um ciclo viajam em paralelo, o custo do ciclo e o
        # MAIOR atraso dele, nao a soma.
        self.cycle = None
        self.cycles = []
        # Intervalo de 15 min em curso, quando a fase de operacao esta rodando.
        # Serve para duas coisas: separar a PROPOSE do leilao de tempo real, que
        # o original manda menor, e dar ao traco o tempo de CO-SIMULACAO, sem o
        # qual nao da para reproduzir a Figura 58 da tese.
        self.ctx_t = None
        self.sent = 0
        self.dropped = 0
        self.delays = []
        self._trace = None
        self._writer = None
        if trace_path:
            self._trace = open(trace_path, "w", newline="")
            self._writer = csv.writer(self._trace)
            self._writer.writerow(["wall_time", "t", "ciclo", "sender", "receiver",
                                   "performative", "bytes", "delay_s", "dropped"])

    def begin_cycle(self, name, t=None):
        """Abre um balde de contabilidade para o ciclo dado."""
        self.ctx_t = t
        self.cycle = {"name": name, "messages": 0, "dropped": 0, "max_delay": 0.0,
                      "bytes": 0, "t": t}
        self.cycles.append(self.cycle)
        return self.cycle

    def end_cycle(self):
        c, self.cycle = self.cycle, None
        return c

    def _conteudo(self, message):
        """Tamanho do conteudo serializado, em bytes."""
        size = getattr(message, "message_length", None)
        if size:
            return int(size)
        content = message.content or ""
        return len(content.encode("utf-8")) if isinstance(content, str) else len(content)

    def _size(self, message):
        real = self._conteudo(message)
        if MESSAGE_SIZE != "thesis":
            return real
        perf = message.performative
        if perf in CONTROLE:
            return THESIS_CONTROL_BYTES
        if perf == ACLMessage.INFORM and real <= THESIS_CONTROL_MAX_BYTES:
            return THESIS_CONTROL_BYTES
        # A unica PROPOSE de faixa curta do original e a do PROSUMIDOR no leilao
        # de tempo real: `prosumer_agent.py` linha 310, e so ela. As propostas do
        # concentrador ao DSO e ao agente de mercado carregam programacao e ficam
        # na faixa alta, que e o que a Figura 58(a) mostra em azul e verde. Duas
        # condicoes, portanto: fase de operacao (ha intervalo corrente) e
        # remetente prosumidor.
        if (perf == ACLMessage.PROPOSE and self.ctx_t is not None
                and str(getattr(message.sender, "localname", "")).startswith(
                    "prosumer")):
            return self._rng.randint(*THESIS_BID_RANGE)
        return self._rng.randint(*THESIS_PAYLOAD_RANGE)

    @staticmethod
    def _instrumentacao(message, receiver):
        """A mensagem e do PADE, e nao da arquitetura?

        O `Agent.react` do PADE reenvia uma COPIA de tudo o que recebe para o
        agente `sniffer`, embrulhada num INFORM marcado como mensagem de sistema.
        O sniffer e ferramenta de depuracao do framework: nao existe na
        arquitetura da tese, nao e no da rede 6TiSCH e nao consome o meio LPWA.

        Modelar essas copias como trafego distorce tudo o que se mede. Medido
        numa corrida da fase de operacao sobre a rede da tese: elas eram METADE
        das mensagens, todas na faixa de 1000 a 1500 bytes porque embrulham a
        original, e todas com atraso zero porque o destino nao tem no na rede.
        Com elas dentro, a distribuicao de tamanho da Figura 59 saia invertida e
        a mediana do tempo de recepcao caia para 0,1 s.

        Elas continuam sendo ENTREGUES; apenas nao passam pelo modelo de rede.
        """
        if getattr(message, "system_message", False):
            return True
        nome = getattr(receiver, "localname", "") or ""
        rem = getattr(getattr(message, "sender", None), "localname", "") or ""
        # O SOLVER tambem nao e da arquitetura. Ele existe aqui porque o
        # `py_dss_interface` e o Pyomo nao podem rodar na thread do reactor, e o
        # trabalho original tem o mesmo recurso (`solver_agent.py`). Ele NAO
        # aparece na topologia publicada: o `nodes_xy.csv` do Apendice B tem 78
        # posicoes, os 75 nos eletricos mais o DSO e o Mercado, e nenhuma para
        # ele. Nem aparece nas Figuras 58 e 59, que so mostram AC, AD e AM.
        #
        # Medido antes desta exclusao: 36% do trafego da programacao era de e
        # para o solver, com mediana de 2.916 bytes e maximo de 102.534, contra
        # mediana de 26 bytes do resto. Era ele que estourava o enlace ruim e
        # deixava o `concentrator_trafo_5_35` sem resposta, e nao o CFP.
        for x in (nome, rem):
            if x.startswith(("sniffer", "ams", "solver")):
                return True
        return False

    def route(self, agent, original_send, message, receivers):
        """Chamado no lugar do `Agent._send`."""
        for receiver in receivers:
            if self._instrumentacao(message, receiver):
                original_send(message, [receiver])
                continue
            size = self._size(message)
            src = getattr(message.sender, "localname", None)
            dst = getattr(receiver, "localname", None)
            delay, dropped = self.backend.transmit(size, src, dst)
            self.sent += 1
            if self.cycle is not None:
                self.cycle["messages"] += 1
                self.cycle["bytes"] += size
                if dropped:
                    self.cycle["dropped"] += 1
                else:
                    self.cycle["max_delay"] = max(self.cycle["max_delay"], delay)
            if self._writer:
                self._writer.writerow([
                    f"{time.time():.6f}",
                    "" if self.ctx_t is None else self.ctx_t,
                    self.cycle["name"] if self.cycle else "",
                    getattr(message.sender, "localname", "?"),
                    getattr(receiver, "localname", "?"),
                    message.performative, size, f"{delay:.6f}", int(dropped)])
                self._trace.flush()
            if dropped:
                self.dropped += 1
                continue
            self.delays.append(delay)
            if delay <= 0.0:
                original_send(message, [receiver])
            else:
                reactor.callLater(delay * self.time_scale, original_send,
                                  message, [receiver])

    def summary(self):
        delivered = self.sent - self.dropped
        out = {
            "backend": self.backend.name,
            "sent": self.sent,
            "delivered": delivered,
            "dropped": self.dropped,
            "drop_rate": self.dropped / self.sent if self.sent else 0.0,
            "delay_mean_s": sum(self.delays) / len(self.delays) if self.delays else 0.0,
            "delay_max_s": max(self.delays) if self.delays else 0.0,
        }
        if self.cycles:
            por_nome = {}
            for c in self.cycles:
                d = por_nome.setdefault(c["name"], {"n": 0, "delay": 0.0})
                d["n"] += 1
                d["delay"] += c["max_delay"]
            out["cycle_mean_s"] = {k: v["delay"] / v["n"] for k, v in por_nome.items()}
        hops = getattr(self.backend, "hops", None)
        if hops:
            out["hops_mean"] = sum(hops) / len(hops)
            out["hops_max"] = max(hops)
        return out

    def close(self):
        if self._trace:
            self._trace.close()
        if hasattr(self.backend, "close"):
            self.backend.close()


def node_map_from_case(case):
    """Nome local do agente para nome da posicao no Apendice B da tese.

    O AM e o AD ficam ambos em (0,0) no apendice. O agente de solucao nao existe
    na tese: e um servico de calculo do proprio AM, entao divide a posicao dele e
    nao gasta radio.
    """
    mapping = {"market": "Market", "dso": "DSO", "solver": "Market"}
    for c in case.concentrators:
        # O concentrador fica no transformador, ou seja, no no de media tensao.
        mapping[f"concentrator_{c.name}"] = str(c.mv_node)
    for node in case.lv_nodes:
        mapping[f"prosumer{node}"] = str(node)
    return mapping


def install(agents, backend_name=None, trace_path=None, time_scale=TIME_SCALE,
            node_map=None):
    """Instala a camada de rede nos agentes dados.

    Substitui `agent._send` por uma versao que consulta o backend. Nao toca no
    `pade/core/agent.py`, que e compartilhado com os cenarios `star`, `ieee13` e
    `integrated`.
    """
    backend_name = backend_name or os.environ.get("NET_BACKEND", "ideal")
    if backend_name not in BACKENDS:
        raise ValueError(f"backend de rede desconhecido: {backend_name}")
    kwargs = {"node_map": node_map} if backend_name == "omnet" else {}
    link = NetworkLink(BACKENDS[backend_name](**kwargs), trace_path, time_scale)

    for agent in agents:
        original = agent._send

        def routed(message, receivers, _agent=agent, _original=original):
            link.route(_agent, _original, message, receivers)

        agent._send = routed

    print(f"[rede] backend={backend_name} tamanho={MESSAGE_SIZE} time_scale={time_scale}"
          + (f" trace={trace_path}" if trace_path else ""), flush=True)
    return link
