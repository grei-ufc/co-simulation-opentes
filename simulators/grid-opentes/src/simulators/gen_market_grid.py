"""Gera o circuito OpenDSS MVLV75 a partir do force.json (rede do estudo de caso
do SiMTES, tese de Lucas S. Melo, 2022).

A rede tem 75 nos: 7 em media tensao (13,8 kV) e 68 em baixa tensao (0,38 kV),
distribuidos em 5 subsistemas, cada um alimentado por um transformador de
distribuicao. Cada no de baixa tensao hospeda um prosumidor.

REFERENCIA REPRODUZIDA
----------------------
O trabalho original descreve a mesma rede em DOIS modelos diferentes:

  - pandapower (`create_grid_in_pandapower`, grid_optimization.py): usado pelo
    agente DSO para o fluxo de carga e para extrair o Jacobiano que alimenta a
    restricao de tensao do modelo de otimizacao. Trafos de 250 kVA (vk=4%,
    vkr=1,2%), cargas trifasicas equilibradas, linhas com os std_types
    '34-AL1/6-ST1A 10.0' (MT) e '15-AL1/3-ST1A 0.4' (BT).

  - MyGrid (`create_mygrid_model`, mosaik_mygrid/mygrid_tools.py): usado pela
    co-simulacao para registrar as tensoes vistas pelos agentes. Trafos de
    225 kVA com impedancia 0,01+0,2j, cargas MONOFASICAS na fase indicada pelo
    campo `phase` de cada no, linhas com modelo de condutor (Carson).

Os dois nao sao a mesma rede. Este gerador reproduz a ELETRICA do modelo do
pandapower (impedancias de linha, modelo de carga, percentuais do trafo), porque
e ele que carrega as restricoes operacionais e a matriz de sensibilidade que este
projeto substitui. A divergencia entre os dois modelos originais esta documentada
em docs/MERCADO.md.

DECISOES DE CONVERSAO
---------------------
- Trafos: a potencia vem do force.json (45/75/112,5 kVA, serie NBR 5440), e nao
  os 250 kVA uniformes do pandapower, que sao residuo do std type
  '0.25 MVA 10/0.4 kV' e nao dimensionamento. Ver TRAFO_PROFILE: o perfil 'ref'
  reproduz os 250 kVA para a regressao contra o modelo original.
- Comprimentos: o force.json guarda `length` em milhas; a referencia converte
  para km multiplicando por 1,60934. Fazemos o mesmo e emitimos `units=km`.
- Cargas: trifasicas equilibradas (o equivalente de sequencia positiva do
  pandapower). O campo `phase` de cada no fica preservado no force.json para uma
  eventual variante desbalanceada, que e o que o OpenDSS permite e o pandapower
  do trabalho original nao fazia.
- Fonte: `MVAsc3`/`MVAsc1` altos para aproximar a barra slack ideal do
  `create_ext_grid` do pandapower.
- Vminpu/Vmaxpu das cargas alargados: com os limites padrao (0,95/1,05) o
  OpenDSS troca o modelo de carga para impedancia constante fora da faixa, o que
  quebraria a comparacao com o pandapower (sempre potencia constante).

Uso (dentro do container grid, com o volume src montado):

    python src/simulators/gen_market_grid.py
"""

import json
import math
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "MVLV75"
FORCE_JSON = DATA_DIR / "force.json"

MILES_TO_KM = 1.60934

# Std types do pandapower usados pela referencia (pandapower 3.5.4).
LINECODES = {
    "MT_34AL1_6ST1A": {
        "std_type": "34-AL1/6-ST1A 10.0",
        "r_ohm_per_km": 0.8342,
        "x_ohm_per_km": 0.36,
        "c_nf_per_km": 9.7,
        "max_i_ka": 0.17,
    },
    "BT_15AL1_3ST1A": {
        "std_type": "15-AL1/3-ST1A 0.4",
        "r_ohm_per_km": 1.8769,
        "x_ohm_per_km": 0.35,
        "c_nf_per_km": 11.0,
        "max_i_ka": 0.105,
    },
}

# O pandapower so tem sequencia positiva (std_type nao traz R0/X0/C0). O OpenDSS
# exige os dois e NAO aceita Z0 == Z1: a construcao do Yprim a partir das
# componentes simetricas divide pela diferenca entre elas e falha com
# "Matrix Inversion Error". Usamos as relacoes tipicas de linha aerea. Como as
# cargas aqui sao equilibradas, nao circula corrente de sequencia zero e esses
# valores nao afetam o resultado (conferido na validacao contra o pandapower).
ZERO_SEQ_R_FACTOR = 3.0
ZERO_SEQ_X_FACTOR = 3.0
ZERO_SEQ_C_FACTOR = 0.5

# Transformadores.
#
# `force`: usa a potencia declarada por transformador no force.json (45, 75 e
#   112,5 kVA, potencias padronizadas de transformador de distribuicao no Brasil,
#   serie da NBR 5440). E o caso de pesquisa.
# `ref`: 250 kVA em todos, como no modelo pandapower do trabalho original. Serve
#   so para a regressao contra aquele modelo. Os 250 kVA de la nao sao
#   dimensionamento: sao os parametros do std type '0.25 MVA 10/0.4 kV' do
#   pandapower, que aparece na linha comentada logo acima do
#   create_transformer_from_parameters em grid_optimization.py. Com 250 kVA
#   alimentando de 8 a 20 prosumidores de ~1 kW, a restricao de carregamento de
#   transformador do modelo do DSO (Eq. 6.13 da tese) nunca atua.
#
# Os percentuais sao os mesmos nos dois perfis; muda so a potencia de base, de
# modo que a impedancia ohmica escala com 1/S (transformador menor, mais
# impedante), que e o comportamento fisico correto.
TRAFO_PROFILE = "force"
TRAFO_KVA_REF = 250.0
TRAFO_VK_PCT = 4.0       # tensao de curto-circuito
TRAFO_VKR_PCT = 1.2      # parte real da tensao de curto-circuito
TRAFO_PFE_PCT = 0.24     # perdas no ferro, em % da potencia nominal (0,6 kW / 250 kVA)
TRAFO_I0_PCT = 0.24      # corrente a vazio

KV_MV = 13.8
KV_LV = 0.38
BASE_FREQ = 60           # rede brasileira; ver nota de validacao em docs/

LOAD_PF = 0.9            # fator de potencia usado em run_powerflow_in_pandapower
LOAD_VMINPU = 0.7
LOAD_VMAXPU = 1.4


def _bus(name):
    return f"n{name}"


def _load_force(path):
    with open(path, "r") as f:
        return json.load(f)


def _trafo_params():
    """Converte os parametros do pandapower para os do OpenDSS."""
    xhl = math.sqrt(TRAFO_VK_PCT ** 2 - TRAFO_VKR_PCT ** 2)
    # %R por enrolamento: o %loadloss total do OpenDSS e a soma dos dois.
    pct_r_wdg = TRAFO_VKR_PCT / 2.0
    # A corrente a vazio tem componente ativa (perdas no ferro) e magnetizante.
    imag_sq = TRAFO_I0_PCT ** 2 - TRAFO_PFE_PCT ** 2
    pct_imag = math.sqrt(imag_sq) if imag_sq > 0 else 0.0
    return xhl, pct_r_wdg, TRAFO_PFE_PCT, pct_imag


def _trafo_kva(t):
    return float(t["power"]) if TRAFO_PROFILE == "force" else TRAFO_KVA_REF


def gen_linecodes():
    lines = [
        "! LineCodes equivalentes aos std_types do pandapower usados na referencia.",
        "! Sequencia positiva identica a do pandapower; sequencia zero em relacao",
        f"! tipica de linha aerea (R0={ZERO_SEQ_R_FACTOR}xR1, X0={ZERO_SEQ_X_FACTOR}xX1,"
        f" C0={ZERO_SEQ_C_FACTOR}xC1), que nao influi",
        "! com cargas equilibradas e e exigida pelo OpenDSS (Z0 != Z1).",
        "",
    ]
    for name, p in LINECODES.items():
        lines.append(
            f"New LineCode.{name} nphases=3 units=km"
            f" R1={p['r_ohm_per_km']} X1={p['x_ohm_per_km']} C1={p['c_nf_per_km']}"
            f" R0={p['r_ohm_per_km'] * ZERO_SEQ_R_FACTOR:.6g}"
            f" X0={p['x_ohm_per_km'] * ZERO_SEQ_X_FACTOR:.6g}"
            f" C0={p['c_nf_per_km'] * ZERO_SEQ_C_FACTOR:.6g}"
            f" normamps={p['max_i_ka'] * 1e3} emergamps={p['max_i_ka'] * 1e3}"
            f"   ! pandapower: {p['std_type']}"
        )
    return lines


def gen_lines(data, level_by_name):
    out = [
        "! Linhas. O tipo de condutor segue o nivel de tensao do no de destino,",
        "! como em create_grid_in_pandapower. Comprimento: milhas -> km.",
        "",
    ]
    n = 0
    for link in data["links"]:
        if link["type"] != "line":
            continue
        target_level = level_by_name[link["target"]]
        code = "MT_34AL1_6ST1A" if target_level == "medium voltage" else "BT_15AL1_3ST1A"
        length_km = link["length"] * MILES_TO_KM
        out.append(
            f"New Line.{link['name']} phases=3"
            f" bus1={_bus(link['source'])} bus2={_bus(link['target'])}"
            f" linecode={code} length={length_km:.6f} units=km"
        )
        n += 1
    return out, n


def gen_transformers(data):
    xhl, pct_r_wdg, pct_noloadloss, pct_imag = _trafo_params()
    out = [
        f"! Transformadores de distribuicao {KV_MV}/{KV_LV} kV, delta-estrela.",
        f"! Perfil de potencia: '{TRAFO_PROFILE}'"
        + (" (potencia declarada no force.json, serie NBR 5440)"
           if TRAFO_PROFILE == "force" else " (250 kVA, modelo pandapower original)"),
        f"! Percentuais do pandapower: vk={TRAFO_VK_PCT}%, vkr={TRAFO_VKR_PCT}%,"
        f" pfe={TRAFO_PFE_PCT}%, i0={TRAFO_I0_PCT}%",
        f"! -> XHL={xhl:.5f}%, %r por enrolamento={pct_r_wdg}%,"
        f" %noloadloss={pct_noloadloss}%, %imag={pct_imag}",
        "",
    ]
    for t in data["transformers"]:
        kva = _trafo_kva(t)
        out.append(f"New Transformer.{t['name']} phases=3 windings=2")
        out.append(
            f"~ wdg=1 bus={_bus(t['source'])} conn=delta kV={KV_MV}"
            f" kVA={kva} %r={pct_r_wdg}"
        )
        out.append(
            f"~ wdg=2 bus={_bus(t['target'])} conn=wye kV={KV_LV}"
            f" kVA={kva} %r={pct_r_wdg}"
        )
        out.append(
            f"~ XHL={xhl:.5f} %noloadloss={pct_noloadloss} %imag={pct_imag}"
        )
    return out, len(data["transformers"])


def gen_loads(data):
    """Uma carga por no (exceto o no 0, que e a subestacao).

    Potencia inicial zero: quem define P/Q a cada passo e o agente prosumidor,
    via mosaik. As cargas existem no .dss para que o simulador tenha o ponto de
    injecao ja mapeado.
    """
    out = [
        "! Uma carga por no (o no 0 e a subestacao e nao tem carga), com potencia",
        "! inicial zero: os valores vem dos agentes prosumidores a cada passo.",
        "! Vminpu/Vmaxpu alargados para manter potencia constante em toda a faixa",
        "! de tensao analisada (o padrao 0,95/1,05 trocaria para impedancia const.).",
        "",
    ]
    n = 0
    for node in data["nodes"]:
        if node["name"] == 0:
            continue
        kv = KV_MV if node["voltage_level"] == "medium voltage" else KV_LV
        out.append(
            f"New Load.Load_{node['name']} phases=3 bus1={_bus(node['name'])}"
            f" conn=wye kV={kv} kW=0.0 pf={LOAD_PF} model=1"
            f" Vminpu={LOAD_VMINPU} Vmaxpu={LOAD_VMAXPU}"
        )
        n += 1
    return out, n


def gen_master():
    return [
        "! Rede MVLV75: estudo de caso do SiMTES (tese de Lucas S. Melo, 2022),",
        "! convertida do force.json. Gerado por src/simulators/gen_market_grid.py.",
        "! NAO EDITAR A MAO: rode o gerador.",
        "",
        "Clear",
        f"Set DefaultBaseFrequency={BASE_FREQ}",
        "",
        f"New Circuit.MVLV75 bus1={_bus(0)} basekV={KV_MV} pu=1.0 phases=3",
        "! Fonte rigida, para aproximar a barra slack ideal do pandapower.",
        "! MVAsc1 != MVAsc3 pelo mesmo motivo do Z0 != Z1 das linhas.",
        "~ MVAsc3=100000 MVAsc1=105000",
        "",
        "Redirect MVLV75_LineCodes.dss",
        "Redirect MVLV75_Lines.dss",
        "Redirect MVLV75_Transformers.dss",
        "Redirect MVLV75_Loads.dss",
        "",
        f"Set VoltageBases=[{KV_MV}, {KV_LV}]",
        "CalcVoltageBases",
        "",
        "Set Mode=snap",
        "Solve",
    ]


def main():
    data = _load_force(FORCE_JSON)
    level_by_name = {n["name"]: n["voltage_level"] for n in data["nodes"]}

    linecodes = gen_linecodes()
    lines, n_lines = gen_lines(data, level_by_name)
    trafos, n_trafos = gen_transformers(data)
    loads, n_loads = gen_loads(data)
    master = gen_master()

    for filename, content in [
        ("MVLV75_LineCodes.dss", linecodes),
        ("MVLV75_Lines.dss", lines),
        ("MVLV75_Transformers.dss", trafos),
        ("MVLV75_Loads.dss", loads),
        ("Master.dss", master),
    ]:
        (DATA_DIR / filename).write_text("\n".join(content) + "\n")

    n_mv = sum(1 for v in level_by_name.values() if v == "medium voltage")
    n_lv = sum(1 for v in level_by_name.values() if v == "low voltage")
    print(f"Gerado em {DATA_DIR}:")
    print(f"  {len(level_by_name)} barras ({n_mv} MT + {n_lv} BT)")
    print(f"  {n_lines} linhas, {n_trafos} transformadores, {n_loads} cargas")


if __name__ == "__main__":
    main()
