"""Matrizes de sensibilidade de tensao dV/dP e dV/dQ obtidas do OpenDSS.

CONTEXTO
--------
A restricao de tensao do modelo do DSO e linearizada (Melo, 2022, equacoes 6.14
a 6.17):

    Umin <= U0(t,l) + dU(t,l) <= Umax     com     dU = S . dP

ou seja, so a sensibilidade da tensao a potencia ATIVA, com dQ = 0. Na
formulacao de referencia, S e o bloco dV/dP do Jacobiano invertido de um fluxo
de potencia de Newton-Raphson.

Aqui a mesma grandeza e obtida por perturbacao no proprio OpenDSS: perturba-se a
potencia ativa de um no, resolve-se o fluxo e mede-se a variacao de tensao em
todos os nos. Vantagens: um simulador so, e o metodo nao depende de o solver
expor o Jacobiano (vale para varredura direta-inversa, para rede desbalanceada e
para qualquer elemento de controle que o OpenDSS saiba resolver), e a rede
que o mercado lineariza e a mesma que a co-simulacao resolve.

SOBRE O dQ = 0
--------------
A restricao (6.16) despreza o reativo. Isso vale enquanto o dispositivo
despachado nao mexer em Q, que e o caso do armazenamento sem controle de
reativo. Se ele
mantiver fator de potencia constante, o que e o comportamento padrao de um
inversor comum, a hipotese passa a dominar o erro da restricao.

Por isso `compute_sensitivity` devolve TAMBEM `dV/dQ`, obtida do mesmo jeito, por
perturbacao. Com as duas matrizes a restricao de tensao aceita qualquer politica
de reativo do dispositivo, e a politica "sem reativo" continua sendo a
restricao (6.16), porque o termo simplesmente zera.

CONVENCAO DE SINAL
------------------
`S[i, j] = dV_i / dP_j` e `SQ[i, j] = dV_i / dQ_j`, com P e Q em INJECAO
(positivo = gera, tensao sobe), V em pu, P em kW e Q em kvar. O modelo do DSO
trabalha com potencia de CARGA, entao la as matrizes entram com sinal trocado
(`-S`).

CUSTO
-----
Diferenca central: 2N + 1 fluxos de potencia por ponto de operacao, sendo N o
numero de nos controlaveis. Diferenca adiantada: N + 1, com metade da precisao.

Uso direto (dentro do container grid):

    python src/simulators/sensitivity.py

Matriz por fase, para MARKET_FASE=1 (linhas por (no, fase), colunas pelas portas
`Port_<no>_<fase>` do circuito):

    python src/simulators/sensitivity.py day --por-fase --load-csv ... \
        --pv-csv ... --out .../sensitivity_fase.npz
"""

import json
import os
import math
from pathlib import Path

import numpy as np

# Qual rede. `GRID_DIR` aponta para a pasta do circuito; sem a variavel, vale o
# caso IEEE 13 do mercado.
DATA_DIR = Path(os.environ.get(
    "GRID_DIR", Path(__file__).resolve().parents[1] / "data" / "13Bus"))
MASTER = DATA_DIR / "Master.dss"
FORCE_JSON = DATA_DIR / "force.json"

DEFAULT_PF = 0.9
DEFAULT_DELTA_KW = 1.0


def apply_loads(dss, loads_kw, loads_kvar=None, pf=DEFAULT_PF):
    """Aplica o ponto de operacao com P e Q definidos separadamente.

    O `pf` fixo do OpenDSS acopla Q a P: ao perturbar kW, o kvar acompanharia e a
    sensibilidade medida seria dV/d(P,Q), nao dV/dP. Fixando kvar explicitamente,
    a perturbacao seguinte em kW e de potencia ativa pura, como exige a (6.16).

    `loads_kvar` omitido significa Q derivado de P pelo fator de potencia.
    """
    tan_phi = math.tan(math.acos(pf))
    for node, kw in loads_kw.items():
        kvar = kw * tan_phi if loads_kvar is None else loads_kvar.get(node, 0.0)
        dss.text(f"Edit Load.Load_{node} kW={kw} kvar={kvar}")


_BUS_CACHE = None


def bus_name(node):
    """Nome da barra no OpenDSS para um no do mercado.

    A regra padrao e `n{no}`. Uma rede publicada, como a IEEE 13, tem nomes
    proprios que nao se pode renomear sem perder a correspondencia com a
    referencia: nesse caso o `force.json` traz o nome da barra em cada no, e ele
    manda.
    """
    global _BUS_CACHE
    if _BUS_CACHE is None:
        data = json.loads(FORCE_JSON.read_text())
        _BUS_CACHE = {n["name"]: n["bus"] for n in data["nodes"] if "bus" in n}
    return _BUS_CACHE.get(node, f"n{node}")


def read_voltages(dss, nodes):
    """Tensao em pu por no, media das fases existentes na barra.

    A media so representa a barra quando as fases estao proximas. Numa rede
    desequilibrada como a IEEE 13 ela esconde parte da violacao, e isso esta
    medido no ESTUDO_IEEE13.md. O modelo do DSO e por no, entao e a media que
    ele consegue usar.
    """
    v = np.zeros(len(nodes))
    for i, node in enumerate(nodes):
        dss.circuit.set_active_bus(bus_name(node))
        mags = [m for m in dss.bus.vmag_angle_pu[0::2] if m > 1e-6]
        v[i] = sum(mags) / len(mags)
    return v


def solve(dss):
    dss.text("Solve")
    if not dss.solution.converged:
        raise RuntimeError("fluxo de potencia nao convergiu")


def read_taps(dss):
    """Derivacao de cada regulador, na ordem de `dss.regcontrols.names`."""
    taps = []
    for name in dss.regcontrols.names or []:
        if not name:
            continue
        dss.regcontrols.name = name
        taps.append(dss.regcontrols.tap_number)
    return taps


def compute_sensitivity(dss, nodes, loads_kw, delta_kw=DEFAULT_DELTA_KW,
                        central=True, pf=DEFAULT_PF, reactive=True, taps_out=None):
    """Calcula V0, dV/dP e dV/dQ no ponto de operacao dado.

    Args:
        dss: instancia py_dss_interface com o circuito ja compilado.
        nodes: nos monitorados e perturbados, na ordem das linhas/colunas.
        loads_kw: {no: kW} do ponto de operacao (carga, positiva = consome).
        delta_kw: tamanho da perturbacao, em kW para P e em kvar para Q.
        central: diferenca central (2N+1 fluxos) ou adiantada (N+1 fluxos).
        pf: fator de potencia usado para fixar o Q das cargas.
        reactive: se False, devolve dV/dQ nula e economiza metade dos fluxos.
        taps_out: lista em que se acrescentam as derivacoes do ponto base.

    O ponto base e resolvido com o regulador livre; as perturbacoes, com as
    derivacoes CONGELADAS (ControlMode=OFF). E o ponto da previsao que fixa as
    derivacoes do dia seguinte: o mercado decide depois, com elas como condicao
    de contorno, e o cenario de mercado aplica essas mesmas derivacoes na
    co-simulacao. Ver docs/explanation/market-model.md, "O regulador de tensao".

    Returns:
        (V0, S, SQ): V0 com len(nodes) posicoes em pu; S em pu/kW e SQ em
        pu/kvar, ambas (len(nodes), len(nodes)).
    """
    tan_phi = math.tan(math.acos(pf))
    apply_loads(dss, loads_kw, pf=pf)
    dss.text("Set ControlMode=static")
    solve(dss)
    v0 = read_voltages(dss, nodes)
    if taps_out is not None:
        taps_out.append(read_taps(dss))
    dss.text("Set ControlMode=OFF")

    n = len(nodes)
    s = np.zeros((n, n))
    s_q = np.zeros((n, n))
    for j, node in enumerate(nodes):
        base_kw = loads_kw.get(node, 0.0)
        base_kvar = base_kw * tan_phi

        # injecao +delta  <=>  carga -delta (Q fixo no valor do ponto base)
        dss.text(f"Edit Load.Load_{node} kW={base_kw - delta_kw} kvar={base_kvar}")
        solve(dss)
        v_plus = read_voltages(dss, nodes)

        if central:
            dss.text(f"Edit Load.Load_{node} kW={base_kw + delta_kw} kvar={base_kvar}")
            solve(dss)
            v_minus = read_voltages(dss, nodes)
            s[:, j] = (v_plus - v_minus) / (2.0 * delta_kw)
        else:
            s[:, j] = (v_plus - v0) / delta_kw

        if reactive:
            # Mesma perturbacao, agora so no reativo e com o ativo preso no
            # ponto base: e dV/dQ pura, pelo mesmo motivo que o kvar fica preso
            # ao medir dV/dP.
            dss.text(f"Edit Load.Load_{node} kW={base_kw} kvar={base_kvar - delta_kw}")
            solve(dss)
            vq_plus = read_voltages(dss, nodes)

            if central:
                dss.text(f"Edit Load.Load_{node} kW={base_kw} "
                         f"kvar={base_kvar + delta_kw}")
                solve(dss)
                vq_minus = read_voltages(dss, nodes)
                s_q[:, j] = (vq_plus - vq_minus) / (2.0 * delta_kw)
            else:
                s_q[:, j] = (vq_plus - v0) / delta_kw

        dss.text(f"Edit Load.Load_{node} kW={base_kw} kvar={base_kvar}")

    dss.text("Set ControlMode=static")
    solve(dss)
    return v0, s, s_q


def predict(v0, s, delta_p_kw, s_q=None, delta_q_kvar=None):
    """Tensao prevista pelo modelo linear para uma variacao de injecao.

    Com `s_q` e `delta_q_kvar` a previsao inclui o reativo; sem eles, e a
    restricao (6.16), que despreza o termo.
    """
    v = v0 + s @ np.asarray(delta_p_kw)
    if s_q is not None and delta_q_kvar is not None:
        v = v + s_q @ np.asarray(delta_q_kvar)
    return v


# ----------------------------------------------------------------------------
# Validacao: previsao linear x fluxo de potencia completo
# ----------------------------------------------------------------------------

def _lv_nodes():
    data = json.loads(FORCE_JSON.read_text())
    return [n["name"] for n in data["nodes"] if n["voltage_level"] == "low voltage"]


def _all_nodes_except_slack():
    data = json.loads(FORCE_JSON.read_text())
    return [n["name"] for n in data["nodes"] if n["name"] != 0]


def _base_case_loads():
    data = json.loads(FORCE_JSON.read_text())
    return {n["name"]: n["active_power"]
            for n in data["nodes"] if n["voltage_level"] == "low voltage"}


def compute_day(dss, nodes, loads_by_period, delta_kw=DEFAULT_DELTA_KW,
                central=True, pf=DEFAULT_PF):
    """V0 e S para uma sequencia de pontos de operacao (o dia inteiro).

    `loads_by_period` e uma lista com um dicionario {no: kW} por periodo, um
    ponto de operacao para cada um dos 96 intervalos.
    """
    v0_list, s_list, sq_list, taps = [], [], [], []
    for loads in loads_by_period:
        v0, s, s_q = compute_sensitivity(dss, nodes, loads, delta_kw, central, pf,
                                         taps_out=taps)
        v0_list.append(v0)
        s_list.append(s)
        sq_list.append(s_q)
    return np.array(v0_list), np.array(s_list), np.array(sq_list), np.array(taps)


# ----------------------------------------------------------------------------
# Sensibilidade POR FASE (MARKET_FASE=1)
# ----------------------------------------------------------------------------
# A media das fases so representa a barra quando as fases estao proximas. Numa
# rede desequilibrada ela esconde violacao: na IEEE 13 a negociacao feita sobre a
# media zera as violacoes na media e deixa 152 pontos acima de 1,03 pu quando a
# tensao e lida fase a fase. Aqui cada fase de cada barra vira uma LINHA da
# matriz, e cada fase em que um dispositivo pode injetar vira uma COLUNA (uma
# "porta"). As portas sao as cargas monofasicas `Port_<no>_<fase>` que o gerador
# do caso escreve no Master.dss, com potencia zero.
#
# Duas diferencas de metodo em relacao a `compute_sensitivity`:
#   - as perturbacoes sao feitas com as derivacoes do regulador CONGELADAS
#     (ControlMode=OFF), depois de o ponto base ter sido resolvido com elas
#     livres. E a sensibilidade local que interessa: o regulador tem banda morta
#     e nao responde a 1 kW; congelar apenas impede que um ponto perto da borda
#     da banda contamine uma coluna com uma troca de derivacao;
#   - o reativo da carga base fica no ponto base, como no metodo por no.

def phase_rows(dss, nodes):
    """(no, fase) de cada fase existente das barras dadas, na ordem dos nos."""
    rows = []
    for node in nodes:
        dss.circuit.set_active_bus(bus_name(node))
        rows += [(node, k) for k in sorted(dss.bus.nodes) if k in (1, 2, 3)]
    return rows


def phase_ports(dss):
    """(no, fase) de cada carga `Port_<no>_<fase>` do circuito."""
    ports = []
    for name in dss.loads.names:
        parts = name.lower().split("_")
        if len(parts) == 3 and parts[0] == "port":
            ports.append((int(parts[1]), int(parts[2])))
    return sorted(ports)


def read_voltages_phase(dss, rows):
    """Tensao em pu de cada (no, fase), pelo NUMERO do no da barra e nao pela
    posicao: numa barra 645, que so tem as fases B e C, a primeira leitura e B."""
    cache, v = {}, np.zeros(len(rows))
    for i, (node, k) in enumerate(rows):
        if node not in cache:
            dss.circuit.set_active_bus(bus_name(node))
            cache[node] = dict(zip(dss.bus.nodes, dss.bus.vmag_angle_pu[0::2]))
        v[i] = cache[node][k]
    return v


def compute_sensitivity_phase(dss, rows, ports, loads_kw, delta_kw=DEFAULT_DELTA_KW,
                              pf=DEFAULT_PF, reactive=True, taps_out=None):
    """V0 por fase e dV/dP, dV/dQ por porta, com diferenca central.

    Returns:
        (V0, S, SQ): V0 com len(rows) posicoes; S e SQ (len(rows), len(ports)),
        em pu/kW e pu/kvar, com P e Q em INJECAO, como em `compute_sensitivity`.
    """
    apply_loads(dss, loads_kw, pf=pf)
    for n, k in ports:
        dss.text(f"Edit Load.Port_{n}_{k} kW=0 kvar=0")
    dss.text("Set ControlMode=static")
    solve(dss)
    v0 = read_voltages_phase(dss, rows)
    if taps_out is not None:
        taps_out.append(read_taps(dss))
    dss.text("Set ControlMode=OFF")
    s = np.zeros((len(rows), len(ports)))
    s_q = np.zeros((len(rows), len(ports)))
    try:
        for j, (n, k) in enumerate(ports):
            for col, campo in ((s, "kW"), (s_q, "kvar") if reactive else (None, None)):
                if col is None:
                    continue
                dss.text(f"Edit Load.Port_{n}_{k} {campo}={-delta_kw}")
                solve(dss)
                vp = read_voltages_phase(dss, rows)
                dss.text(f"Edit Load.Port_{n}_{k} {campo}={delta_kw}")
                solve(dss)
                vm = read_voltages_phase(dss, rows)
                dss.text(f"Edit Load.Port_{n}_{k} {campo}=0")
                col[:, j] = (vp - vm) / (2.0 * delta_kw)
    finally:
        dss.text("Set ControlMode=static")
    return v0, s, s_q


def _run_day(args):
    """Gera V0(t) e S(t) para o dia, a partir dos perfis de carga e PV."""
    import csv

    import py_dss_interface

    def read_csv_cols(path):
        with open(path) as f:
            rows = list(csv.DictReader(f))
        return {int(k): np.array([float(r[k]) for r in rows]) for k in rows[0]}

    load = read_csv_cols(args.load_csv)
    pv = read_csv_cols(args.pv_csv)
    nodes = _all_nodes_except_slack()
    n_periods = len(next(iter(load.values())))

    # Ponto de operacao base: carga liquida (consumo menos geracao), sem
    # armazenamento. E sobre ele que a linearizacao e feita.
    periods = []
    for t in range(n_periods):
        periods.append({node: float(load.get(node, np.zeros(n_periods))[t]
                                   - pv.get(node, np.zeros(n_periods))[t])
                        for node in nodes if node in load})

    dss = py_dss_interface.DSS()
    dss.text(f'Compile "{MASTER}"')

    if args.por_fase:
        rows, ports = phase_rows(dss, nodes), phase_ports(dss)
        if not ports:
            raise SystemExit(f"{MASTER} nao tem cargas Port_<no>_<fase>: o modo por fase "
                             "precisa delas (ver gen_ieee13_market.py)")
        taps = []
        res = [compute_sensitivity_phase(dss, rows, ports, loads, taps_out=taps)
               for loads in periods]
        v0, s, s_q = (np.array([r[i] for r in res]) for i in range(3))
        np.savez(args.out, nodes=np.array(nodes), rows=np.array(rows),
                 ports=np.array(ports), v0=v0, s=s, s_q=s_q, taps=np.array(taps),
                 reguladores=np.array([n for n in dss.regcontrols.names if n]))
        print(f"{n_periods} periodos, {len(rows)} linhas por fase, {len(ports)} portas -> {args.out}")
        print(f"  V0 por fase: min={v0.min():.5f} max={v0.max():.5f}; violacoes no caso "
              f"base: {(v0 < 0.97).sum()} abaixo de 0,97 e {(v0 > 1.03).sum()} acima de 1,03 "
              f"(de {v0.size})")
        return

    v0, s, s_q, taps = compute_day(dss, nodes, periods)

    np.savez(args.out, nodes=np.array(nodes), v0=v0, s=s, s_q=s_q, taps=taps,
             reguladores=np.array([n for n in dss.regcontrols.names if n]))
    below = (v0 < 0.97).sum()
    above = (v0 > 1.03).sum()
    print(f"{n_periods} periodos, {len(nodes)} nos -> {args.out}")
    print(f"  V0: min={v0.min():.5f} (t={v0.min(axis=1).argmin()}) "
          f"max={v0.max():.5f} (t={v0.max(axis=1).argmax()})")
    print(f"  violacoes no caso base: {below} pontos abaixo de 0,97 pu e "
          f"{above} acima de 1,03 pu (de {v0.size})")


def _main():
    import time

    import py_dss_interface

    nodes = _all_nodes_except_slack()
    lv_nodes = _lv_nodes()
    base = _base_case_loads()

    dss = py_dss_interface.DSS()
    dss.text(f'Compile "{MASTER}"')

    t0 = time.time()
    v0, s, s_q = compute_sensitivity(dss, nodes, base, delta_kw=DEFAULT_DELTA_KW,
                                     central=True)
    dt = time.time() - t0
    print(f"S: {s.shape[0]}x{s.shape[1]} em {dt:.1f} s "
          f"({2 * len(nodes) + 1} fluxos de potencia)")
    print(f"V0: min={v0.min():.5f} max={v0.max():.5f} pu")
    print(f"|S| maximo = {np.abs(s).max():.3e} pu/kW  "
          f"(sensibilidade propria media = {np.abs(np.diag(s)).mean():.3e} pu/kW)")
    print(f"|SQ| maximo = {np.abs(s_q).max():.3e} pu/kvar  "
          f"(razao SQ/S na diagonal = {np.abs(np.diag(s_q)).mean() / np.abs(np.diag(s)).mean():.3f})")

    idx = {node: i for i, node in enumerate(nodes)}
    rng = np.random.default_rng(0)

    # Uma unica direcao aleatoria, escalada: assim o erro do modelo linear pode
    # ser lido como termo de segunda ordem (deve crescer com o quadrado da
    # amplitude). Sortear uma direcao nova por amplitude misturaria as duas
    # coisas e nao diria nada.
    direction = np.zeros(len(nodes))
    for node in lv_nodes:
        direction[idx[node]] = rng.uniform(-1.0, 1.0)

    # Q do ponto de operacao, mantido fixo: e a hipotese dQ = 0 de (6.16), e e
    # o que um armazenamento sem controle de reativo faz de fato.
    tan_phi = math.tan(math.acos(DEFAULT_PF))
    base_kvar = {node: base.get(node, 0.0) * tan_phi for node in nodes}

    print("\nprevisao linear x fluxo completo (perturbacao so nos nos BT,")
    print("direcao fixa escalada por |dP|, Q mantido no valor do ponto base):")
    print(f"{'|dP| por no':>14} {'|dV| real max':>15} {'erro max':>12} {'erro rms':>12}"
          f" {'erro/|dP|^2':>13}")
    for amp in (1.0, 2.0, 5.0, 10.0):
        dp = amp * direction

        v_lin = predict(v0, s, dp)

        loads = dict(base)
        for node in lv_nodes:
            loads[node] = base.get(node, 0.0) - dp[idx[node]]
        apply_loads(dss, loads, base_kvar)
        solve(dss)
        v_real = read_voltages(dss, nodes)

        err = v_lin - v_real
        print(f"{amp:>13.1f}  {np.abs(v_real - v0).max():>15.5f} "
              f"{np.abs(err).max():>12.2e} {np.sqrt((err ** 2).mean()):>12.2e}"
              f" {np.abs(err).max() / amp ** 2:>13.2e}")

    # Quanto custa a hipotese dQ = 0 se o dispositivo variar Q junto com P
    # (fator de potencia constante), que e como as cargas do circuito estao
    # parametrizadas por padrao, e quanto disso o termo dV/dQ recupera.
    print("\ncusto da hipotese dQ=0 se o dispositivo mantiver fator de potencia,")
    print("e o que sobra ao incluir o termo dV/dQ na previsao:")
    print(f"{'|dP| por no':>14} {'erro sem dQ':>13} {'erro com dQ':>13} {'razao':>8}")
    for amp in (1.0, 2.0, 5.0, 10.0):
        dp = amp * direction
        dq = tan_phi * dp                      # fator de potencia constante
        v_sem = predict(v0, s, dp)
        v_com = predict(v0, s, dp, s_q, dq)
        loads = dict(base)
        for node in lv_nodes:
            loads[node] = base.get(node, 0.0) - dp[idx[node]]
        apply_loads(dss, loads)                # Q acompanha P pelo fator de potencia
        solve(dss)
        v_real = read_voltages(dss, nodes)
        e_sem = np.abs(v_sem - v_real).max()
        e_com = np.abs(v_com - v_real).max()
        print(f"{amp:>13.1f} {e_sem:>13.2e} {e_com:>13.2e} {e_sem / e_com:>8.1f}x")

    apply_loads(dss, base)
    solve(dss)

    print("\nefeito do tamanho da perturbacao em S (delta em kW):")
    ref = s
    for delta in (0.1, 0.5, 2.0, 5.0):
        _, s_d, _ = compute_sensitivity(dss, nodes, base, delta_kw=delta, central=True,
                                        reactive=False)
        print(f"  delta={delta:>4} kW: |S - S(1 kW)| max = {np.abs(s_d - ref).max():.2e} pu/kW")

    _, s_fwd, _ = compute_sensitivity(dss, nodes, base, delta_kw=DEFAULT_DELTA_KW,
                                      central=False, reactive=False)
    print(f"\ndiferenca adiantada x central (delta=1 kW): "
          f"|dS| max = {np.abs(s_fwd - ref).max():.2e} pu/kW")

    # Gravar S e um produto de simulacao, nao dado de entrada: so acontece se o
    # caminho for pedido explicitamente, para comparar com outra ferramenta.
    out = os.environ.get("SENSITIVITY_OUT")
    if out:
        np.savez(out, nodes=np.array(nodes), v0=v0, s=s)
        print(f"\ngravado {out}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd")
    d = sub.add_parser("day", help="gera V0(t) e S(t) para o dia inteiro")
    d.add_argument("--load-csv", required=True, dest="load_csv")
    d.add_argument("--pv-csv", required=True, dest="pv_csv")
    d.add_argument("--out", required=True)
    d.add_argument("--por-fase", action="store_true", dest="por_fase",
                   help="linhas por (no, fase) e colunas pelas portas Port_<no>_<fase>")
    parsed = ap.parse_args()

    if parsed.cmd == "day":
        _run_day(parsed)
    else:
        _main()
