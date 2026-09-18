"""Geracao e reducao de cenarios para o modelo estocastico do prosumidor.

Porte de `stochastic_model/generate_scenarios.py` do trabalho original, sem
PySP. O procedimento e o da subsecao 6.1.4.1 da tese:

  Passo 1: amostra N cenarios de carga, de geracao e de preco direto da base de
           dados (dias diferentes do SimBench e do Nordpool) e reduz cada
           conjunto de N para 3, por selecao direta da distancia de Kantorovich.
  Passo 2: combina carga x geracao, resultando em 9 cenarios de potencia, com
           probabilidade dada pelo produto das individuais.
  Passo 3: reduz os 9 cenarios de potencia para 3.
  Passo 4: combina os 3 de potencia com os 3 de preco, resultando nos 9 cenarios
           finais de preco-potencia usados na otimizacao.

Quem nao tem geracao pula o passo 2: os 3 cenarios de consumo ja sao os de
potencia, como diz o texto da tese.
"""

import numpy as np

from .config import DATA_DIR


def load_pool():
    """Reservatorio de dias alternativos gerado por `data_prep`."""
    data = np.load(DATA_DIR / "scenario_pool.npz")
    nodes = [int(x) for x in data["nodes"]]
    index = {n: i for i, n in enumerate(nodes)}
    return index, data["load"], data["pv"], data["price"]


def reduce_kantorovich(scenarios, keep, probs=None):
    """Reducao por selecao direta da distancia de Kantorovich.

    Args:
        scenarios: array (n, T) com um cenario por linha.
        keep: quantos cenarios manter.
        probs: probabilidades iniciais; uniformes se omitido.

    Returns:
        {indice_do_cenario: probabilidade}, com as probabilidades dos cenarios
        descartados redistribuidas para o mantido mais proximo.
    """
    scenarios = np.asarray(scenarios, dtype=float)
    n = len(scenarios)
    if keep >= n:
        p = probs if probs is not None else np.full(n, 1.0 / n)
        return {i: float(p[i]) for i in range(n)}
    if probs is None:
        probs = np.full(n, 1.0 / n)
    probs = np.asarray(probs, dtype=float)

    # Passo 0: matriz de custos (distancia euclidiana entre cenarios).
    costs = np.linalg.norm(scenarios[:, None, :] - scenarios[None, :, :], axis=2)

    # Passo 1: escolhe o cenario de menor distancia de Kantorovich.
    kant = costs @ probs
    chosen = [int(np.argmin(kant))]
    cost = costs[chosen[0], :]
    new_costs = costs.copy()

    # Passo 2: repete, atualizando a matriz de custos com o minimo entre o custo
    # ao cenario ja escolhido e o custo original.
    for _ in range(keep - 1):
        updated = new_costs.copy()
        for i in range(n):
            if i not in chosen:
                updated[i, :] = np.minimum(cost[i], new_costs[i, :])
        new_costs = updated
        kant = new_costs @ probs
        kant[chosen] = np.inf
        pick = int(np.argmin(kant))
        chosen.append(pick)
        cost = new_costs[pick, :]

    # Passo 3: redistribui a probabilidade dos descartados para o mantido mais
    # proximo de cada um.
    out = {i: float(probs[i]) for i in chosen}
    for j in range(n):
        if j in chosen:
            continue
        for k in np.argsort(costs[j, :])[1:]:
            if int(k) in chosen:
                out[int(k)] += float(probs[j])
                break
    return out


def _combine(a_probs, a_data, b_probs, b_data, op):
    """Produto cartesiano de dois conjuntos de cenarios."""
    data, probs = [], []
    for i, pi in a_probs.items():
        for j, pj in b_probs.items():
            data.append(op(a_data[i], b_data[j]))
            probs.append(pi * pj)
    return np.array(data), np.array(probs)


def build_scenarios(node, n_reduced=3, deterministic_demand=None,
                    deterministic_price=None):
    """Cenarios (probabilidade, demanda_liquida_kw, preco) para um prosumidor.

    `n_reduced = 1` devolve o caso deterministico: um cenario de probabilidade 1
    com a previsao passada em `deterministic_demand`/`deterministic_price`.
    """
    if n_reduced <= 1:
        return [(1.0, np.asarray(deterministic_demand, dtype=float),
                 np.asarray(deterministic_price, dtype=float))]

    index, load, pv, price = load_pool()
    i = index[node]
    load_scn = load[:, i, :]
    pv_scn = pv[:, i, :]

    load_probs = reduce_kantorovich(load_scn, n_reduced)
    price_probs = reduce_kantorovich(price, n_reduced)

    if np.abs(pv_scn).max() > 0.0:
        gen_probs = reduce_kantorovich(pv_scn, n_reduced)
        power, power_probs = _combine(load_probs, load_scn, gen_probs, pv_scn,
                                      lambda l, g: l - g)
        keep = reduce_kantorovich(power, n_reduced, power_probs)
        power_data = np.array([power[k] for k in keep])
        power_probs = np.array([keep[k] for k in keep])
    else:
        power_data = np.array([load_scn[k] for k in load_probs])
        power_probs = np.array([load_probs[k] for k in load_probs])

    scenarios = []
    price_keys = list(price_probs)
    for pd_, pp in zip(power_data, power_probs):
        for k in price_keys:
            scenarios.append((float(pp * price_probs[k]), pd_, price[k]))

    total = sum(p for p, _, _ in scenarios)
    return [(p / total, d, pr) for p, d, pr in scenarios]
