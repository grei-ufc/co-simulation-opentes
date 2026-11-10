# Arquivos de dados

O caso fica em `simulators/grid-opentes/src/data/13Bus/`. Uma parte é entrada
(o circuito oficial, as curvas de PV e o preço), e o resto é gerado pelo
`gen_ieee13_market.py` e pelo `sensitivity.py`
([Regenerar o caso](../how-to-guides/regenerate-case.md)).

## Entradas

| Arquivo | Conteúdo | Origem |
|---|---|---|
| `IEEE13Nodeckt.dss`, `IEEE13Nodeckt_w_loadcurve.dss` | o circuito oficial do IEEE 13 Node Test Feeder | circuito publicado |
| `IEEELineCodes.dss` | os códigos de linha do circuito | circuito publicado |
| `LoadShape.dss` | as curvas diárias de carga | circuito publicado |
| `IEEE13Node_BusXY.csv` | coordenadas de desenho das barras | circuito publicado |
| `ieee13_pv.dss`, `ieee13_shape_pv_5min.dss` | os cinco sistemas fotovoltaicos e suas curvas, em OpenDSS | `pv_creator.py` |
| `ieee13_shape_pv_5min.csv`, `ieee13_temperature_5min.csv` | irradiância e temperatura do módulo a cada 5 min | `pv_creator.py` |
| `spot_price.csv` | um dia de preço do mercado spot | dado de entrada |
| `diagrama.png` | o diagrama unifilar do caso | figura |

As curvas de PV saem das estações solares em `src/data/InfoPV/` (BR-PVGen):
`power_station_metadata.csv` e `solar_station/PS_00N.csv`.

## Gerados pelo `gen_ieee13_market.py`

| Arquivo | Conteúdo |
|---|---|
| `Master.dss` | o circuito de mercado: uma carga por barra, os PV e as portas de armazenamento por fase |
| `force.json` | a topologia: barras, fases, linhas e o nome de cada barra no OpenDSS |
| `config.json` | a alocação do armazenamento: de rede e de prosumidor, potência e capacidade |
| `load_kw.csv`, `pv_kw.csv` | carga e geração de cada barra nos 96 intervalos de 15 min |
| `scenario_pool.npz` | nove dias sintéticos de carga, geração e preço, para os cenários do prosumidor e a demanda realizada |
| `nodes_xy.csv` | a posição de cada agente, com o comprimento real de cada linha, para a rede de rádio |

## Gerados pelo `sensitivity.py` (fora do git)

| Arquivo | Conteúdo |
|---|---|
| `sensitivity_day.npz` | dV/dP (`s`) e dV/dQ (`s_q`) por barra, a tensão de partida (`v0`) e as derivações do regulador (`taps`) em cada intervalo |
| `sensitivity_fase.npz` | o mesmo por fase: linhas por (barra, fase), colunas pelas portas |

## Gravados pelo servidor de rede

| Arquivo | Conteúdo |
|---|---|
| `tisch_links.csv` | cada par de agentes na rede 6TiSCH que o servidor simulou: distância, RSSI, erro de pacote (PER) e se o par virou enlace (`adjacent`) |
| `tisch_links_wisun_<taxa>k.csv` | o mesmo para cada taxa do Wi-SUN FAN (fora do git) |

## Formato dos perfis

`load_kw.csv` e `pv_kw.csv` têm uma coluna por barra (o número da barra no
cabeçalho) e uma linha por intervalo. `spot_price.csv` tem a coluna `price`,
em EUR/MWh.
