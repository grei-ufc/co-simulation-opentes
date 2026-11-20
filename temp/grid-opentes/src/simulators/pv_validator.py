"""Validacoes do gerador de curvas fotovoltaicas (`pv_creator.py`).

Portado do `pv_validator.py` do tsre-der-opentes, que reuniu num modulo so as
verificacoes antes espalhadas pelo `pv_creator`. Ficaram as que o caso do IEEE 13
usa: caminhos de entrada, metadados das estacoes, integridade das curvas
interpoladas e conferencia de cada PV contra o circuito compilado. A conversao
automatica de PV bifasico em monofasico, com sorteio da fase, NAO veio: o PV1 da
barra 646 e bifasico de proposito (ver `ieee13_pv.dss`).
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)

# Faixa de temperatura de operacao de modulo fotovoltaico da IEC 61215. Leitura
# fora dela e defeito do sensor ou do registro, nao clima.
TEMP_MIN_C, TEMP_MAX_C = -40.0, 85.0
# Teto de irradiancia normalizada por 1000 W/m2. Irradiancia no plano do modulo
# passa de 1 pu em dia claro com reflexao de nuvem, mas nao de 1,5.
IRRAD_MAX_PU = 1.5


def validar_caminhos(*caminhos):
    """Falha cedo se algum arquivo ou pasta de entrada nao existe."""
    for c in caminhos:
        if not c.exists():
            raise FileNotFoundError(f"entrada ausente: '{c}'")


def carregar_metadados(arquivo):
    """Le o CSV de metadados das estacoes e confere que ele tem linhas."""
    try:
        meta = pd.read_csv(arquivo)
    except pd.errors.EmptyDataError as err:
        raise EOFError(f"'{arquivo}' esta vazio ou sem cabecalho") from err
    except pd.errors.ParserError as err:
        raise TypeError(f"'{arquivo}' esta corrompido ou mal formatado") from err
    if meta.empty:
        raise ValueError(f"'{arquivo.name}' nao tem linhas de dados")
    return meta


def validar_irradiancia(curva, origem):
    """A curva ja recortada em zero e normalizada; aqui so o teto."""
    if (curva > IRRAD_MAX_PU).any():
        raise ValueError(f"irradiancia extrema ({curva.max():.2f} pu) em {origem}")


def validar_temperatura(curva, origem):
    """Temperatura do modulo em graus Celsius, dentro da faixa IEC."""
    if (curva < TEMP_MIN_C).any() or (curva > TEMP_MAX_C).any():
        raise ValueError(
            f"anomalia termica em {origem}: {curva.min():.1f} a {curva.max():.1f} C, "
            f"fora da faixa IEC [{TEMP_MIN_C:.0f}, {TEMP_MAX_C:.0f}]")


def validar_curvas_interpoladas(nome, irrad, temp, pontos, origem):
    """Tamanho esperado e nenhum NaN depois da interpolacao."""
    if len(irrad) != pontos or len(temp) != pontos:
        raise ValueError(
            f"{nome}: esperados {pontos} pontos, vieram {len(irrad)} (irradiancia) "
            f"e {len(temp)} (temperatura)")
    if irrad.isna().any() or temp.isna().any():
        raise ValueError(f"{nome}: NaN restante apos a interpolacao de '{origem}'")


def validar_no_circuito(pvs, dss):
    """Cada PV precisa cair em nos que existem na barra do circuito compilado.

    E a verificacao que teria pego o PV1 declarado em `646.1.2.3`: a barra 646
    so tem as fases 2 e 3, e o OpenDSS nao avisa quando um terminal fica ligado
    a um no inexistente; ele injeta a potencia la e segue.
    """
    for pv in pvs:
        base, *nos = pv["bus"].split(".")
        nos = nos or ["1", "2", "3"]
        if len(nos) != pv["phases"]:
            raise ValueError(f"{pv['name']}: phases={pv['phases']} mas a barra "
                             f"'{pv['bus']}' declara {len(nos)} no(s)")
        if len(set(nos)) != len(nos):
            raise ValueError(f"{pv['name']}: no repetido em '{pv['bus']}'")
        if base.lower() not in [b.lower() for b in dss.circuit.buses_names]:
            raise ValueError(f"{pv['name']}: a barra '{base}' nao existe no circuito")
        dss.circuit.set_active_bus(base)
        existentes = {str(n) for n in dss.bus.nodes}
        faltando = [n for n in nos if n not in existentes]
        if faltando:
            raise ValueError(f"{pv['name']}: no(s) {faltando} nao existem na barra "
                             f"{base}, que tem {sorted(existentes)}")
