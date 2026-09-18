#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agentes do cenario causal Volt/Var (evolucao do first.py) — N inversores.

Mesma ideia do first.py original (agentes trocando mensagens via OMNeT++), agora
com N PARES de agentes, um par por inversor fotovoltaico co-simulado:

  AgenteA_i (medidor):     le a tensao da barra do PV_i e a publica como mensagem
                           FIPA-ACL na rede de comunicacao (OMNeT++), marcada com
                           a barra de origem.
  AgenteB_i (controlador): recebe a tensao da SUA barra JA ATRASADA pela rede e
                           aplica Volt/Var no inversor do PV_i:
                             P (ativa)  = solar disponivel (P_avail_in)
                             Q (reativa)= f(tensao),  S = sqrt(P^2 + Q^2) <= kVA
                           e devolve (P_ref, Q_ref) para o PVSystem_i -> OpenDSS.

Latencia/jitter/perda de pacotes do OMNeT++ afetam a tensao que cada controlador
efetivamente "ve". O controle liga/desliga por agente (param control_enabled),
permitindo comparar a co-simulacao SEM controle (baseline) e COM controle.

NUM_PVS (env, default 5) define quantos pares medidor/controlador sobem.
"""

import json
import math
import os

from pade.acl.aid import AID
from pade.core.agent import Agent
from pade.drivers.mosaik_driver import MosaikCon
from pade.misc.utility import display_message, start_loop


STEP_SIZE = int(os.environ.get('AGENT_STEP_SIZE', '300'))
NUM_PVS = int(os.environ.get('NUM_PVS', '5'))

MOSAIK_MODELS = {
    'api_version': '3.0',
    'type': 'time-based',
    'models': {
        'PadeAgent': {
            'public': True,
            'params': [
                'agent_id', 'bus', 'control_enabled', 'kva',
                'v_ref', 'v_deadband', 'v_min', 'v_max', 'q_max_pct',
            ],
            'attrs': [
                'val_in', 'val_out',   # comunicacao (mensagens via OMNeT++)
                'V_in',                # entrada do medidor (tensao da barra)
                'P_avail_in',          # entrada do controlador (solar disponivel)
                'P_ref', 'Q_ref',      # saida do controlador (setpoint do inversor)
            ],
        },
    },
}

ACTIVE_AGENTS = {}


class MosaikSim(MosaikCon):
    def __init__(self, agent, step_size=STEP_SIZE):
        super().__init__(MOSAIK_MODELS, agent)
        self.step_size = step_size

    def create(self, num, model, agent_id, **params):
        ag = ACTIVE_AGENTS.get(agent_id)
        if ag is not None:
            ag.configurar(**params)
        return [{'eid': agent_id, 'type': model}]

    def step(self, time, inputs, max_advance=0):
        for eid, attrs in inputs.items():
            ag = ACTIVE_AGENTS.get(eid)
            if ag is None:
                continue
            if 'V_in' in attrs:  # medidor
                vals = [v for v in attrs['V_in'].values()
                        if isinstance(v, (int, float)) and v > 0.1]
                if vals:
                    ag.ao_medir_tensao(sum(vals) / len(vals), time)
            if 'P_avail_in' in attrs:  # controlador: solar disponivel define P
                ag.p_ref = float(list(attrs['P_avail_in'].values())[0])
            if 'val_in' in attrs:  # controlador: tensao (atrasada) define Q
                bruto = list(attrs['val_in'].values())[0]
                if bruto:
                    for msg in str(bruto).split('|||'):
                        if msg:
                            ag.receber_mensagem_da_rede(msg)
        return time + self.step_size

    def get_data(self, outputs):
        data = {}
        for eid, attrs in outputs.items():
            ag = ACTIVE_AGENTS.get(eid)
            data[eid] = {}
            for attr in attrs:
                if ag is None:
                    continue
                if attr == 'val_out':
                    data[eid]['val_out'] = ag.val_out
                    ag.val_out = ''
                elif attr == 'P_ref':
                    data[eid]['P_ref'] = ag.p_ref
                elif attr == 'Q_ref':
                    data[eid]['Q_ref'] = ag.q_ref
        return data


class AgenteComunicador(Agent):
    """Medidor (nome 'AgenteA_*') ou controlador Volt/Var (nome 'AgenteB_*')."""

    def __init__(self, aid, is_sender=False):
        super().__init__(aid=aid, debug=False)
        self.val_out = ''
        self.p_ref = 0.0
        self.q_ref = 0.0
        self.v_seen = 0.0
        self.bus = '?'
        self.is_sender = is_sender
        self.control_enabled = True
        self.kva = 3000.0
        self.v_ref = 1.0
        self.v_deadband = 0.01
        self.v_min = 0.95
        self.v_max = 1.05
        self.q_max_pct = 0.44
        if self.is_sender:
            self.mosaik_sim = MosaikSim(self)

    def configurar(self, bus=None, control_enabled=None, kva=None, v_ref=None,
                   v_deadband=None, v_min=None, v_max=None, q_max_pct=None):
        if bus is not None:
            self.bus = str(bus)
        if control_enabled is not None:
            self.control_enabled = bool(int(control_enabled))
        if kva is not None:
            self.kva = float(kva)
        if v_ref is not None:
            self.v_ref = float(v_ref)
        if v_deadband is not None:
            self.v_deadband = float(v_deadband)
        if v_min is not None:
            self.v_min = float(v_min)
        if v_max is not None:
            self.v_max = float(v_max)
        if q_max_pct is not None:
            self.q_max_pct = float(q_max_pct)

    @property
    def _is_medidor(self):
        return self.aid.localname.startswith('AgenteA')

    def on_start(self):
        super().on_start()
        ACTIVE_AGENTS[self.aid.localname] = self
        papel = 'medidor' if self._is_medidor else 'controlador Volt/Var'
        display_message(self.aid.localname, f'online ({papel}) ligado ao OMNeT++.')

    # ---- Medidor: publica a tensao da sua barra na rede ----
    def ao_medir_tensao(self, v_meas, time):
        self.v_seen = v_meas
        msg = {
            'sender': self.aid.localname,
            'bus': self.bus,
            'ontology': 'medicao_tensao',
            'conversation_id': f'meas-{self.bus}-t{time}',
            'V_meas': round(v_meas, 6),
            't': time,
        }
        self.val_out = json.dumps(msg)

    # ---- Controlador: Volt/Var a partir da tensao (atrasada) da SUA barra ----
    def _volt_var_q(self, v):
        if not self.control_enabled:
            return 0.0
        q_cap = math.sqrt(max(0.0, self.kva ** 2 - self.p_ref ** 2))
        q_max = min(self.q_max_pct * self.kva, q_cap)
        hi = self.v_ref + self.v_deadband
        lo = self.v_ref - self.v_deadband
        if v > hi:
            return -q_max * min(1.0, (v - hi) / max(1e-6, self.v_max - hi))
        if v < lo:
            return +q_max * min(1.0, (lo - v) / max(1e-6, lo - self.v_min))
        return 0.0

    def receber_mensagem_da_rede(self, json_string):
        try:
            msg = json.loads(json_string)
        except Exception:
            return
        # processa apenas a medicao da SUA barra
        if msg.get('bus') != self.bus or 'V_meas' not in msg:
            return
        v = float(msg['V_meas'])
        self.v_seen = v
        self.q_ref = self._volt_var_q(v)


if __name__ == '__main__':
    host = '0.0.0.0'
    base_port = int(os.environ.get('PADE_PORT', '5678'))
    ams_config = {'name': host, 'port': int(os.environ.get('AMS_PORT', '8000'))}

    agentes = []
    port = base_port
    primeiro = True
    for i in range(1, NUM_PVS + 1):
        a = AgenteComunicador(AID(name=f'AgenteA_{i}@{host}:{port}'), is_sender=primeiro)
        primeiro = False
        port += 1
        b = AgenteComunicador(AID(name=f'AgenteB_{i}@{host}:{port}'), is_sender=False)
        port += 1
        agentes.extend([a, b])

    for ag in agentes:
        ag.update_ams(ams_config)

    start_loop(agentes)
