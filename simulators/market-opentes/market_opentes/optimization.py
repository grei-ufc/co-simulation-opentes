"""Modelos de otimizacao do SiMTES, portados para Pyomo moderno.

Correspondencia com a tese de Lucas S. Melo (2022), subsecao 6.1.4:

  solve_prosumer     Eq. 6.1 a 6.9    Agente Prosumidor
  solve_concentrator Eq. 6.25 e 6.26  Agente Concentrador
  solve_dso          Eq. 6.27 a 6.29  Agente DSO

O que mudou em relacao a implementacao original (`market-simulation`):

1. O modelo do prosumidor era estocastico de dois estagios resolvido com PySP,
   que foi removido do Pyomo 6. Aqui ele e escrito na FORMA EXTENSIVA: um unico
   problema com uma copia das variaveis de segundo estagio por cenario,
   compartilhando as de primeiro estagio. Com um cenario de probabilidade 1 o
   modelo e o deterministico; com nove e o da tese. PySP so era necessario para
   decompor arvores grandes, o que nao e o caso com nove cenarios.

2. A restricao de tensao do DSO usava `J^-1_21` do pandapower. Aqui usa a matriz
   de sensibilidade dV/dP obtida do OpenDSS (ver
   grid-opentes/src/simulators/sensitivity.py). Sinal: S e dV/dP_injecao, e o
   armazenamento entra como carga, entao dV = -S . (p_prosumidor + p_rede).

3. A restricao de carregamento (Eq. 6.28) e aplicada por transformador,
   somando a carga base do trafo e o armazenamento sob ele. A implementacao
   original generalizava para todos os ramos por uma matriz de incidencia; a
   versao por transformador e a da tese e e a que tem limite conhecido
   (potencia nominal do trafo).

4. O solver e configuravel (`MARKET_SOLVER`, default cplex).

Convencao de sinal da potencia de armazenamento: POSITIVA carregando (consome
da rede), negativa descarregando. E a mesma do codigo original.
"""

import os

import numpy as np
import pyomo.environ as pyo
from pyomo.opt import SolverFactory, SolverStatus, TerminationCondition

from .config import (A_PROSUMER, B_NETWORK, CK, D_ENERGY, DT_H, PERIODS,
                     V_BACKOFF, V_MAX, V_MIN)

SOLVER_NAME = os.environ.get("MARKET_SOLVER", "cplex")
SOLVER_PATH = os.environ.get("MARKET_SOLVER_PATH")

BILATERAL_PRICE = 38.0    # EUR/MWh, valor do stochastic_model/config.json
BILATERAL_MAX_KW = 5.0
INIT_SOC_FRACTION = 0.2   # soc[0] = 0,2 * max_soc, como no ReferenceModel
# Estado de carga ao fim do dia nao pode ficar abaixo do inicial. NAO existe na
# Eq. 6.9 da tese, e a ausencia tem efeito visivel: como a energia que sobra na
# bateria no ultimo intervalo nao vale nada na funcao objetivo, o modelo a
# despeja. Sem esta restricao, os 25 armazenamentos descarregam ao mesmo tempo no
# intervalo 95 (50 kW agregados) e a tensao sobe a 1,02 pu.
TERMINAL_SOC = os.environ.get("MARKET_TERMINAL_SOC", "1") == "1"
# Multa por desviar do programado no mercado de tempo real, em EUR/MWh.
#
# A subsecao 6.1.1 da tese descreve esta multa ("a diferenca entre o valor de
# energia programado e o valor de energia efetivamente gerado ou consumido e
# submetida a um valor mais elevado como forma de estimulo ao prosumidor para
# obedecer sua programacao") e a Figura 36 mostra a faixa passivel dela. As
# Equacoes 6.1 a 6.9 NAO tem esse termo.
#
# Sem ele o modelo e neutro ao risco e o mercado de tempo real nao tem limite de
# quantidade, entao o ambiente bilateral nao cumpre funcao de protecao: medido,
# fica em 1,5% da energia com um cenario e 1,3% com nove. Com a multa, desviar do
# programado custa, e contratar antecipadamente passa a valer.
#
# Default 0,0 = formulacao da tese.
DEVIATION_PENALTY = float(os.environ.get("MARKET_DEVIATION_PENALTY", "0.0"))
# Aversao ao risco (CVaR de Rockafellar-Uryasev). beta = 0 e a formulacao da
# tese, neutra ao risco.
#
# Medido: nem a incerteza sozinha nem a multa por desvio dao funcao ao mercado
# bilateral (1,5%, 1,3% e 1,4% da energia). O motivo e estrutural: sob
# NEUTRALIDADE AO RISCO a escolha entre um contrato de preco fixo e um mercado de
# preco variavel e uma comparacao de esperancas, e a multa por desvio nao muda
# isso porque comprar mais no bilateral reduz o NIVEL do spot, nao a DISPERSAO
# dele entre cenarios. Um contrato de preco fixo so ganha papel proprio quando o
# agente e averso ao risco, que e o que este termo introduz.
CVAR_BETA = float(os.environ.get("MARKET_CVAR_BETA", "0.0"))
CVAR_ALPHA = float(os.environ.get("MARKET_CVAR_ALPHA", "0.95"))


def _solver():
    solver = (SolverFactory(SOLVER_NAME, executable=SOLVER_PATH) if SOLVER_PATH
              else SolverFactory(SOLVER_NAME))
    if SOLVER_NAME == "cplex":
        # O barrier do CPLEX resolve os QP daqui sem crossover e, quando o otimo
        # cai colado no ponto de partida (`p = p_init`, que e o que acontece na
        # primeira rodada, com lambda ainda zerado), ele para com "Barrier cannot
        # determine infeasibility" e devolve `unknown`, com residuo de 3e-2 kW.
        # O crossover refina a solucao ate uma base otima verificavel. Nao muda o
        # otimo, so garante que o solver saiba que chegou nele.
        solver.options["barrier crossover"] = 1
    return solver


def _solve(model, label):
    res = _solver().solve(model)
    ok = (res.solver.status == SolverStatus.ok
          and res.solver.termination_condition == TerminationCondition.optimal)
    if not ok:
        raise RuntimeError(
            f"{label}: solver terminou em {res.solver.termination_condition}")
    return model


# ---------------------------------------------------------------------------
# Agente Prosumidor (Eq. 6.1 a 6.9)
# ---------------------------------------------------------------------------

def solve_prosumer(scenarios, storage=None, bilateral_price=BILATERAL_PRICE,
                   bilateral_max=BILATERAL_MAX_KW):
    """Programacao de compra bilateral, de mercado spot e do armazenamento.

    Args:
        scenarios: lista de (probabilidade, demanda_liquida_kw[96], preco_spot[96]).
            A demanda liquida ja desconta a geracao PV. Um unico cenario com
            probabilidade 1,0 equivale ao modelo deterministico.
        storage: `Storage` do no, ou None se o prosumidor nao tiver armazenamento.

    Returns:
        dict com tres arrays de 96 posicoes:
          `storage`   potencia liquida do armazenamento em kW (positiva carregando)
          `bilateral` energia contratada no mercado bilateral, em kW
          `spot`      lance no mercado de tempo real, em kW (negativo = venda),
                      no cenario de maior probabilidade
        As duas ultimas alimentam o registro de transacoes (settlement.py). Sem
        armazenamento, o prosumidor ainda contrata: o modelo e resolvido do mesmo
        jeito, so sem as variaveis de bateria.
    """
    # Sem armazenamento o prosumidor CONTINUA contratando: o `start_pade_agents.py`
    # do trabalho original cria um agente por no de baixa tensao, todos pedem a
    # otimizacao ao solver, e `bilateral_contract_purchase` volta sempre; o
    # `has_storage` la so decide se a programacao da bateria e real ou zeros
    # (`solver_agent.py`, linha 107). Este modulo devolvia um esqueleto com o
    # bilateral zerado, o que contradizia a propria docstring acima e tirava do
    # mercado os 43 nos sem bateria da MVLV75.
    tem_arm = storage is not None

    probs = np.array([s[0] for s in scenarios], dtype=float)
    if not np.isclose(probs.sum(), 1.0):
        raise ValueError(f"as probabilidades dos cenarios somam {probs.sum()}, nao 1")

    m = pyo.ConcreteModel(name="prosumidor")
    m.T = pyo.Set(initialize=range(PERIODS), ordered=True)
    m.Z = pyo.Set(initialize=range(len(scenarios)), ordered=True)

    # --- primeiro estagio: contrato bilateral e programacao do armazenamento ---
    m.p_bilateral = pyo.Var(m.T, domain=pyo.NonNegativeReals, bounds=(0.0, bilateral_max))
    if tem_arm:
        m.p_charge = pyo.Var(m.T, domain=pyo.NonNegativeReals)
        m.p_discharge = pyo.Var(m.T, domain=pyo.NonNegativeReals)
        m.soc = pyo.Var(m.T, domain=pyo.NonNegativeReals,
                        bounds=(storage.min_soc_kwh, storage.max_soc_kwh))
        m.b_charge = pyo.Var(m.T, domain=pyo.Binary)
        m.b_discharge = pyo.Var(m.T, domain=pyo.Binary)

    # --- segundo estagio: lance no mercado de tempo real, por cenario ---
    m.p_spot = pyo.Var(m.Z, m.T, domain=pyo.Reals)
    if DEVIATION_PENALTY > 0.0:
        # Primeiro estagio: o quanto o prosumidor PROGRAMA comprar no spot. O
        # desvio de cada cenario em relacao a isso e o que paga multa.
        m.p_spot_plan = pyo.Var(m.T, domain=pyo.Reals)
        m.dev_pos = pyo.Var(m.Z, m.T, domain=pyo.NonNegativeReals)
        m.dev_neg = pyo.Var(m.Z, m.T, domain=pyo.NonNegativeReals)
        m.deviation = pyo.Constraint(
            m.Z, m.T,
            rule=lambda m, z, t: m.p_spot[z, t] - m.p_spot_plan[t]
            == m.dev_pos[z, t] - m.dev_neg[z, t])

    # Eq. 6.6 a 6.9: operacao do armazenamento
    if tem_arm:
        m.excl = pyo.Constraint(m.T,
                                rule=lambda m, t: m.b_charge[t] + m.b_discharge[t] <= 1)
        m.lim_charge = pyo.Constraint(
            m.T, rule=lambda m, t: m.p_charge[t] <= m.b_charge[t] * storage.max_flow_kw)
        m.lim_discharge = pyo.Constraint(
            m.T, rule=lambda m, t: m.p_discharge[t] <= m.b_discharge[t] * storage.max_flow_kw)
        m.soc_init = pyo.Constraint(
            expr=m.soc[0] == INIT_SOC_FRACTION * storage.max_soc_kwh)
        m.soc_memory = pyo.ConstraintList()
        for t in range(PERIODS - 1):
            m.soc_memory.add(
                m.soc[t + 1] == m.soc[t] + (m.p_charge[t] - m.p_discharge[t]) * DT_H)
        if TERMINAL_SOC:
            last = PERIODS - 1
            m.soc_terminal = pyo.Constraint(
                expr=m.soc[last] + (m.p_charge[last] - m.p_discharge[last]) * DT_H
                >= INIT_SOC_FRACTION * storage.max_soc_kwh)

    # Eq. 6.3 a 6.5: balanco energetico e regra do mercado de tempo real.
    #
    # O modelo original decidia a direcao destas restricoes com `value(aux2)`,
    # lendo o valor CORRENTE das variaveis de armazenamento, que na construcao
    # do modelo e zero. Ou seja, na pratica a direcao vinha da demanda liquida
    # SEM armazenamento. Aqui isso e explicito: a direcao e dada pelo parametro
    # de demanda liquida, que e conhecido, e nao pelo estado inicial de uma
    # variavel de decisao.
    m.balance = pyo.ConstraintList()
    m.spot_rule = pyo.ConstraintList()
    for z, (_, demand, _) in enumerate(scenarios):
        for t in range(PERIODS):
            net = demand[t] + ((m.p_charge[t] - m.p_discharge[t])
                               if tem_arm else 0.0)
            if demand[t] >= 0.0:      # consumo maior que producao
                m.balance.add(m.p_bilateral[t] + m.p_spot[z, t] >= net)
                m.spot_rule.add(m.p_spot[z, t] >= 0.0)
            else:                     # excedente de geracao
                m.balance.add(m.p_spot[z, t] >= net)
                m.spot_rule.add(m.p_spot[z, t] <= 0.0)

    if CVAR_BETA > 0.0:
        # Custo por cenario, para o CVaR.
        m.cost_z = pyo.Var(m.Z, domain=pyo.Reals)
        m.cost_z_def = pyo.Constraint(
            m.Z,
            rule=lambda m, z: m.cost_z[z] == (
                sum(m.p_bilateral[t] * bilateral_price * DT_H for t in m.T)
                + sum(m.p_spot[z, t] * scenarios[z][2][t] * DT_H for t in m.T)))
        m.var_cost = pyo.Var(domain=pyo.Reals)          # VaR
        m.excess = pyo.Var(m.Z, domain=pyo.NonNegativeReals)
        m.cvar_excess = pyo.Constraint(
            m.Z, rule=lambda m, z: m.excess[z] >= m.cost_z[z] - m.var_cost)

    # Eq. 6.1: custo esperado
    def obj(m):
        bilateral = sum(m.p_bilateral[t] * bilateral_price * DT_H for t in m.T)
        spot = sum(prob * sum(m.p_spot[z, t] * price[t] * DT_H for t in m.T)
                   for z, (prob, _, price) in enumerate(scenarios))
        total = bilateral + spot
        if DEVIATION_PENALTY > 0.0:
            total += sum(
                prob * sum((m.dev_pos[z, t] + m.dev_neg[z, t])
                           * DEVIATION_PENALTY * DT_H for t in m.T)
                for z, (prob, _, _) in enumerate(scenarios))
        if CVAR_BETA > 0.0:
            cvar = m.var_cost + (1.0 / (1.0 - CVAR_ALPHA)) * sum(
                prob * m.excess[z] for z, (prob, _, _) in enumerate(scenarios))
            total = (1.0 - CVAR_BETA) * total + CVAR_BETA * cvar
        return total

    m.obj = pyo.Objective(rule=obj, sense=pyo.minimize)

    _solve(m, "prosumidor")
    # O lance de tempo real e por cenario; para o registro de transacoes usa-se o
    # de maior probabilidade, que e o que o prosumidor levaria ao mercado.
    z_ref = int(np.argmax(probs))
    return {
        "storage": (np.array([pyo.value(m.p_charge[t]) - pyo.value(m.p_discharge[t])
                              for t in range(PERIODS)])
                    if tem_arm else np.zeros(PERIODS)),
        "bilateral": np.array([pyo.value(m.p_bilateral[t]) for t in range(PERIODS)]),
        "spot": np.array([pyo.value(m.p_spot[z_ref, t]) for t in range(PERIODS)]),
    }


# ---------------------------------------------------------------------------
# Agente Concentrador (Eq. 6.25 e 6.26)
# ---------------------------------------------------------------------------

def solve_concentrator(nodes, p_init, lam, storages, ck=CK, d_energy=D_ENERGY,
                       periods=None, soc0=None):
    """Reprograma o armazenamento dos prosumidores sob um concentrador.

    Args:
        nodes: nos com armazenamento de prosumidor sob este concentrador.
        p_init: {no: array[96]} programacao proposta pelos prosumidores.
        lam: {no: array[96]} preco sombra vindo do agente de mercado.
        storages: {no: Storage}.

    Returns:
        {no: array[96]} programacao resultante.
    """
    if not nodes:
        return {}

    periods = PERIODS if periods is None else periods
    m = pyo.ConcreteModel(name="concentrador")
    m.N = pyo.Set(initialize=nodes, ordered=True)
    m.T = pyo.Set(initialize=range(periods), ordered=True)
    m.p = pyo.Var(m.N, m.T, domain=pyo.Reals)
    m.soc = pyo.Var(m.N, m.T, domain=pyo.NonNegativeReals)

    m.lim = pyo.Constraint(
        m.N, m.T,
        rule=lambda m, n, t: pyo.inequality(-storages[n].max_flow_kw, m.p[n, t],
                                            storages[n].max_flow_kw))
    m.soc_bounds = pyo.Constraint(
        m.N, m.T,
        rule=lambda m, n, t: pyo.inequality(storages[n].min_soc_kwh, m.soc[n, t],
                                            storages[n].max_soc_kwh))
    m.soc_init = pyo.Constraint(
        m.N, rule=lambda m, n: m.soc[n, 0] == (
            INIT_SOC_FRACTION * storages[n].max_soc_kwh if soc0 is None else soc0[n]))
    m.soc_memory = pyo.ConstraintList()
    for n in nodes:
        for t in range(periods - 1):
            m.soc_memory.add(m.soc[n, t + 1] == m.soc[n, t] + m.p[n, t] * DT_H)

    # Eq. 6.26: a energia total movimentada nao pode cair abaixo de uma fracao
    # da que o prosumidor programou (o concentrador altera a forma, nao o
    # montante). O sinal depende de a programacao original ser liquida de carga
    # ou de descarga, como no `energy_constraint` do codigo original.
    m.energy = pyo.ConstraintList()
    for n in nodes:
        total = float(np.sum(p_init[n]))
        expr = sum(m.p[n, t] for t in range(periods))
        if total >= 0.0:
            m.energy.add(expr >= d_energy * total)
        else:
            m.energy.add(expr <= d_energy * total)

    # Eq. 6.25
    def obj(m):
        return sum(ck * (m.p[n, t] - float(p_init[n][t])) ** 2
                   + float(lam[n][t]) * m.p[n, t]
                   for n in m.N for t in m.T)

    m.obj = pyo.Objective(rule=obj, sense=pyo.minimize)

    _solve(m, "concentrador")
    return {n: np.array([pyo.value(m.p[n, t]) for t in range(periods)]) for n in nodes}


# ---------------------------------------------------------------------------
# Agente DSO (Eq. 6.27 a 6.29)
# ---------------------------------------------------------------------------

def solve_dso(case, base_load, p_prosumer_init, p_network_init, lam, v0, s,
              a=A_PROSUMER, b=B_NETWORK, periods=None, fix_prosumer=False,
              soc0=None):
    """Reprograma armazenamento para nao violar tensao nem carregamento.

    Args:
        case: `Case` com nos, concentradores e dispositivos.
        base_load: {no: array[96]} carga liquida base (consumo menos geracao).
        p_prosumer_init: {no: array[96]} programacao do armazenamento do prosumidor.
        p_network_init: {no: array[96]} programacao do armazenamento de rede.
        lam: {no: array[96]} preco sombra.
        v0: array (96, n_nos) tensoes do ponto de operacao base.
        s: array (96, n_nos, n_nos) sensibilidade EFETIVA dV/dP_injecao [pu/kW],
            ja com o reativo do dispositivo dobrado dentro (ver
            `dual.load_sensitivity`).

    Returns:
        (p_prosumer, p_network): cada um {no: array[96]}.
    """
    pros_nodes = case.prosumer_storage_nodes
    net_nodes = case.network_storage_nodes
    node_index = {n: i for i, n in enumerate(case.all_nodes)}

    periods = PERIODS if periods is None else periods
    m = pyo.ConcreteModel(name="dso")
    m.T = pyo.Set(initialize=range(periods), ordered=True)
    m.NP = pyo.Set(initialize=pros_nodes, ordered=True)
    m.NR = pyo.Set(initialize=net_nodes, ordered=True)
    m.p = pyo.Var(m.NP, m.T, domain=pyo.Reals)      # armazenamento do prosumidor
    m.q = pyo.Var(m.NR, m.T, domain=pyo.Reals)      # armazenamento de rede
    m.soc = pyo.Var(m.NR, m.T, domain=pyo.NonNegativeReals)

    m.lim_p = pyo.Constraint(
        m.NP, m.T,
        rule=lambda m, n, t: pyo.inequality(-case.prosumer_storage[n].max_flow_kw,
                                            m.p[n, t],
                                            case.prosumer_storage[n].max_flow_kw))
    m.lim_q = pyo.Constraint(
        m.NR, m.T,
        rule=lambda m, n, t: pyo.inequality(-case.network_storage[n].max_flow_kw,
                                            m.q[n, t],
                                            case.network_storage[n].max_flow_kw))
    m.soc_bounds = pyo.Constraint(
        m.NR, m.T,
        rule=lambda m, n, t: pyo.inequality(case.network_storage[n].min_soc_kwh,
                                            m.soc[n, t],
                                            case.network_storage[n].max_soc_kwh))
    m.soc_init = pyo.Constraint(
        m.NR,
        rule=lambda m, n: m.soc[n, 0] == (
            INIT_SOC_FRACTION * case.network_storage[n].max_soc_kwh
            if soc0 is None else soc0[n]))
    m.soc_memory = pyo.ConstraintList()
    for n in net_nodes:
        for t in range(periods - 1):
            m.soc_memory.add(m.soc[n, t + 1] == m.soc[n, t] + m.q[n, t] * DT_H)

    # Primeiro nivel de interferencia da fase de operacao (subsecao 6.1.4.3): o
    # DSO tenta resolver a violacao usando SO o armazenamento de rede, sem tocar
    # na programacao dos prosumidores.
    if fix_prosumer:
        m.fixed_prosumer = pyo.ConstraintList()
        for n in pros_nodes:
            for t in range(periods):
                m.fixed_prosumer.add(m.p[n, t] == float(p_prosumer_init[n][t]))

    # Eq. 6.29: limites de tensao. dV = -S . (p + q), porque S e dV/dP_injecao e
    # o armazenamento carregando e carga.
    #
    # Se o dispositivo tiver fator de potencia constante, o reativo acompanha o
    # ativo e o efeito ja vem somado em `s`: a mesma variavel de decisao move as
    # duas potencias, entao a sensibilidade efetiva basta. Ver
    # `dual.load_sensitivity`.
    m.voltage = pyo.ConstraintList()
    for t in range(periods):
        s_t = s[t]
        for i, node in enumerate(case.all_nodes):
            dv = sum(-float(s_t[i, node_index[n]]) * m.p[n, t] for n in pros_nodes)
            dv += sum(-float(s_t[i, node_index[n]]) * m.q[n, t] for n in net_nodes)
            m.voltage.add(pyo.inequality(V_MIN + V_BACKOFF,
                                         float(v0[t][i]) + dv,
                                         V_MAX - V_BACKOFF))

    # Eq. 6.28: carregamento do transformador. A carga base entra na conta,
    # senao a restricao nao significa nada.
    m.loading = pyo.ConstraintList()
    for c in case.concentrators:
        # `MARKET_TRAFO_KVA` forca um valor unico para todos os transformadores.
        # Existe para reproduzir a tese, que usa 250 kVA uniformes vindos do std
        # type do pandapower: com esse valor a restricao de carregamento nunca
        # atua. Sem a chave, valem os 45 a 112,5 kVA do force.json.
        kva = float(os.environ["MARKET_TRAFO_KVA"]) if os.environ.get("MARKET_TRAFO_KVA") else c.kva
        limit_kw = kva * 0.9        # potencia ativa maxima, com fp 0,9
        for t in range(periods):
            base = float(sum(base_load[n][t] for n in c.nodes if n in base_load))
            expr = base
            expr += sum(m.p[n, t] for n in c.prosumer_storage)
            expr += sum(m.q[n, t] for n in c.network_storage)
            m.loading.add(pyo.inequality(-limit_kw, expr, limit_kw))

    # Eq. 6.27
    def obj(m):
        term = sum(a * (m.p[n, t] - float(p_prosumer_init[n][t])) ** 2
                   - float(lam[n][t]) * m.p[n, t]
                   for n in m.NP for t in m.T)
        term += sum(b * (m.q[n, t] - float(p_network_init[n][t])) ** 2
                    for n in m.NR for t in m.T)
        return term

    m.obj = pyo.Objective(rule=obj, sense=pyo.minimize)

    _solve(m, "dso")
    p_out = {n: np.array([pyo.value(m.p[n, t]) for t in range(periods)]) for n in pros_nodes}
    q_out = {n: np.array([pyo.value(m.q[n, t]) for t in range(periods)]) for n in net_nodes}
    return p_out, q_out
