"""Fase de operacao do sistema transativo (subsecao 6.1.2 da tese).

A fase de programacao (`dual.py`) decide o dia inteiro com base numa PREVISAO.
Na operacao, a cada 15 minutos e com 15 minutos de antecedencia da entrega, a
demanda REALIZADA difere do previsto e o DSO precisa verificar se o desvio viola
alguma restricao. A tese define dois niveis de interferencia:

  nivel 1  o DSO tenta corrigir usando SO o armazenamento de rede, que ele
           despacha diretamente (Eq. 6.12 restrita, `fix_prosumer=True`);
  nivel 2  se nao bastar, o agente de mercado abre um leilao de operacao e a
           decomposicao dual roda sobre UM unico periodo, envolvendo tambem o
           armazenamento dos prosumidores.

Diferenca de porte em relacao a programacao: cada intervalo e um problema de 1
periodo, nao de 96. Os mesmos modelos sao usados, com `periods=1`.

DE ONDE VEM O DESVIO
--------------------
Se a realizacao fosse igual a previsao, a fase de operacao nao teria o que fazer
e o resultado seria vazio. A realizacao vem de um DIA DIFERENTE do reservatorio
de cenarios (`scenario_pool.npz`), o mesmo mecanismo que alimenta o modelo
estocastico do prosumidor. Assim o desvio e realista e reprodutivel, em vez de
ruido inventado.

Uso:

    python -m market_opentes.operation --config CAMINHO/config.json \\
        --first 40 --count 16
"""

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np

from .config import DATA_DIR, PERIODS, V_MAX, V_MIN, V_TOL, load_case
from .dual import load_profiles, load_sensitivity, run
from .optimization import solve_concentrator, solve_dso

ALPHA = 0.6
EPS = 1e-3
MAX_ROUNDS = 30


# Como a demanda REALIZADA difere da programada.
#
# `perturb` e o mecanismo da tese (subsecao 6.2.3): "um mecanismo de alteracao
# aleatoria dos valores de demanda liquida dos prosumidores foi implementado
# podendo alterar os valores programados anteriormente em ate +/- 10%". E o modo
# que torna os resultados de operacao comparaveis aos dela.
#
# `day` toma um dia inteiro diferente do reservatorio de cenarios. Medido, o
# desvio agregado tem mediana de 9,4 kW e maximo de 51,2 kW sobre uma demanda
# liquida tipica de 27 kW, varias vezes o que +/-10% produz. Serve como caso
# severo, nao como reproducao da tese.
REALIZED_MODE = os.environ.get("MARKET_REALIZED_MODE", "perturb")
REALIZED_SPREAD = float(os.environ.get("MARKET_REALIZED_SPREAD", "0.10"))
REALIZED_SEED = int(os.environ.get("MARKET_REALIZED_SEED", "0"))


def realized_profiles(day=0, mode=None, spread=None, seed=None):
    """Demanda liquida realizada, pelo mecanismo escolhido.

    Args:
        day: indice do dia alternativo, usado apenas no modo `day`.
        mode: `perturb` (padrao, o da tese) ou `day`.
        spread: amplitude da perturbacao relativa, so no modo `perturb`.
        seed: semente, para que a realizacao seja a mesma entre execucoes.
    """
    mode = REALIZED_MODE if mode is None else mode
    pool = np.load(DATA_DIR / "scenario_pool.npz")
    nodes = [int(x) for x in pool["nodes"]]

    if mode == "day":
        load = pool["load"][day]
        pv = pool["pv"][day]
        return {n: load[i] - pv[i] for i, n in enumerate(nodes)}

    if mode != "perturb":
        raise ValueError(f"modo de demanda realizada desconhecido: {mode}")

    # A perturbacao e sobre a demanda liquida PROGRAMADA, que e o dia base, e nao
    # sobre um dia qualquer: e disso que a tese fala ao dizer "os valores
    # programados anteriormente".
    spread = REALIZED_SPREAD if spread is None else float(spread)
    rng = np.random.default_rng(REALIZED_SEED if seed is None else seed)
    net, _ = load_profiles()
    return {n: series * (1.0 + rng.uniform(-spread, spread, size=len(series)))
            for n, series in net.items()}


def shifted_v0(case, v0_t, s_t, deviation):
    """Tensao base do intervalo JA com o desvio da demanda realizada embutido.

    Sem isto o otimizador do DSO enxerga a tensao da previsao, conclui que nao ha
    violacao e devolve a programacao intacta, enquanto o desvio real ja violou o
    limite. O desvio nao e variavel de decisao: e um deslocamento do ponto de
    operacao, e por isso entra no V0 e nao nas restricoes.
    """
    idx = {n: i for i, n in enumerate(case.all_nodes)}
    dp = np.zeros(len(case.all_nodes))
    for n, value in deviation.items():
        if n in idx:
            dp[idx[n]] -= float(value)
    return v0_t + s_t @ dp


def voltage_at(case, v0_t, s_t, p_t, q_t):
    """Tensao do intervalo pelo modelo linear, dada a base ja deslocada."""
    idx = {n: i for i, n in enumerate(case.all_nodes)}
    dp = np.zeros(len(case.all_nodes))
    for n, value in p_t.items():
        dp[idx[n]] -= float(value[0])
    for n, value in q_t.items():
        dp[idx[n]] -= float(value[0])
    return v0_t + s_t @ dp


def run_operation(config_json, schedule, first=0, count=PERIODS, alpha=ALPHA,
                  eps=EPS, max_rounds=MAX_ROUNDS, realized_day=0, verbose=True):
    """Roda a fase de operacao sobre uma janela de intervalos."""
    case = load_case(config_json)
    forecast, _ = load_profiles()
    realized = realized_profiles(realized_day)
    _, v0, s = load_sensitivity()

    p_sched, q_sched = schedule["y"], schedule["q"]
    pros = case.prosumer_storage_nodes
    net_nodes = case.network_storage_nodes

    if verbose:
        print(f"\nfase de operacao: intervalos {first} a {first + count - 1} "
              f"(realizacao = dia {realized_day} do reservatorio)")
        print(f"{'t':>4} {'desvio kW':>10} {'V antes':>9} {'viol':>6} "
              f"{'nivel':>7} {'rodadas':>8} {'V depois':>9} {'viol':>6} {'s':>6}")

    log = []
    for t in range(first, min(first + count, PERIODS)):
        t0 = time.time()
        # Desvio da demanda realizada em relacao a previsao, no intervalo.
        deviation = {n: float(realized.get(n, 0.0)[t] - forecast.get(n, np.zeros(PERIODS))[t])
                     for n in forecast}
        desvio_total = sum(deviation.values())

        p_t = {n: np.array([p_sched[n][t]]) for n in pros}
        q_t = {n: np.array([q_sched[n][t]]) for n in net_nodes}

        v0_t = shifted_v0(case, v0[t], s[t], deviation)
        v_before = voltage_at(case, v0_t, s[t], p_t, q_t)
        viol_before = int((v_before < V_MIN - V_TOL).sum()
                          + (v_before > V_MAX + V_TOL).sum())

        level, rounds = "-", 0
        if viol_before:
            # ---- nivel 1: so o armazenamento de rede -----------------------
            base_kw = {n: np.array([forecast.get(n, np.zeros(PERIODS))[t]
                                    + deviation.get(n, 0.0)]) for n in case.lv_nodes}
            lam_t = {n: np.zeros(1) for n in pros}
            try:
                p_new, q_new = solve_dso(
                    case, base_kw, p_t, q_t, lam_t,
                    v0_t[None, :], s[t:t + 1], periods=1, fix_prosumer=True)
                v_after = voltage_at(case, v0_t, s[t], p_new, q_new)
                level = "rede"
            except RuntimeError:
                p_new, q_new, v_after = p_t, q_t, v_before

            # ---- nivel 2: leilao de operacao, decomposicao dual em 1 periodo
            if int((v_after < V_MIN - V_TOL).sum()
                   + (v_after > V_MAX + V_TOL).sum()):
                lam_t = {n: np.zeros(1) for n in pros}
                for rounds in range(1, max_rounds + 1):
                    x = {}
                    for c in case.concentrators:
                        x.update(solve_concentrator(
                            c.prosumer_storage,
                            {n: p_t[n] for n in c.prosumer_storage},
                            {n: lam_t[n] for n in c.prosumer_storage},
                            case.prosumer_storage, periods=1))
                    p_new, q_new = solve_dso(case, base_kw, p_t, q_t, lam_t,
                                             v0_t[None, :], s[t:t + 1], periods=1)
                    residual = np.array([x[n] - p_new[n] for n in pros])
                    d_lam = alpha * residual
                    for i, n in enumerate(pros):
                        lam_t[n] = lam_t[n] + d_lam[i]
                    if np.abs(d_lam).max() <= eps:
                        break
                v_after = voltage_at(case, v0_t, s[t], p_new, q_new)
                level = "leilao"
        else:
            p_new, q_new, v_after = p_t, q_t, v_before

        viol_after = int((v_after < V_MIN - V_TOL).sum()
                         + (v_after > V_MAX + V_TOL).sum())
        dt = time.time() - t0
        log.append({"t": t, "deviation_kw": desvio_total,
                    "v_min_before": float(v_before.min()),
                    "v_max_before": float(v_before.max()),
                    "violations_before": viol_before, "level": level,
                    "rounds": rounds,
                    "v_min_after": float(v_after.min()),
                    "v_max_after": float(v_after.max()),
                    "violations_after": viol_after, "seconds": dt})
        if verbose:
            print(f"{t:>4} {desvio_total:>10.2f} "
                  f"{v_before.min():.4f}/{v_before.max():.4f} {viol_before:>6} "
                  f"{level:>7} {rounds:>8} "
                  f"{v_after.min():.4f}/{v_after.max():.4f} {viol_after:>6} {dt:>6.1f}")

    return log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--first", type=int, default=0)
    ap.add_argument("--count", type=int, default=PERIODS)
    ap.add_argument("--scenarios", type=int, default=1)
    ap.add_argument("--realized-day", type=int, default=0, dest="realized_day")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    print("fase de programacao (dia seguinte)...")
    schedule = run(args.config, alpha=ALPHA, eps=EPS, n_scenarios=args.scenarios,
                   verbose=False)
    print(f"  convergiu em {len(schedule['history'])} rodadas")

    log = run_operation(args.config, schedule, first=args.first, count=args.count,
                        realized_day=args.realized_day)

    total = len(log)
    acted = sum(1 for r in log if r["level"] != "-")
    solved = sum(1 for r in log if r["violations_before"] and not r["violations_after"])
    print(f"\n{total} intervalos: {acted} exigiram intervencao, "
          f"{solved} resolvidos, "
          f"{sum(1 for r in log if r['violations_after'])} ainda com violacao")

    if args.out:
        Path(args.out).write_text(json.dumps(log, indent=1))
        print(f"log gravado em {args.out}")


if __name__ == "__main__":
    main()
