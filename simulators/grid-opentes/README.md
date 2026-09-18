# grid-opentes

Simulação da rede elétrica (OpenDSS via `py-dss-interface`): **IEEE 13 Barras**
com 5 sistemas fotovoltaicos e inversores. É o container de domínio **elétrico**
da co-simulação OpenTES.

> **Histórico:** esta pasta se chamava `tsre-der-opentes` (nome do repositório
> original do time TSRE), depois `tsre-opentes`, e enfim `grid-opentes` na
> refatoração de 4 containers — o nome reflete a **função** (simulação de rede),
> não o time. O collector elétrico, antes em `src/simulators/collector.py`, foi
> movido para `simulators/mosaik-opentes/collectors/elec_collector.py`.

## Como rodar

Este projeto **não roda sozinho**: ele sobe como container e o Mosaik se conecta
a ele. Use o script na **raiz do repositório**:

```bash
./run.sh integrated     # co-simulação completa (PADE + OMNeT++ + OpenDSS)
./run.sh ieee13         # só o bloco elétrico (validação isolada)
./run.sh --help         # todos os cenários e experimentos
```

Ver o [README da raiz](../../README.md) e [`docs/INTEGRACAO.md`](../../docs/INTEGRACAO.md).

> **Atenção:** os simuladores deste container rodam com `--remote` e aceitam
> **uma única** conexão Mosaik, encerrando em seguida. Não sonde suas portas com
> TCP de readiness — o probe consome a conexão e mata o simulador.

## Estrutura

```
src/
├── simulators/
│   ├── opendss_simulator.py      # entrypoint do container (--remote :5671)
│   ├── api_opendss.py            # simulador Mosaik do OpenDSS (step/get_data)
│   ├── opendss_wrapper.py        # wrapper do OpenDSS (py-dss-interface)
│   ├── smart_inverter_simulator.py  # inversor inteligente IEEE 1547 (OpenDER)
│   ├── pv_panel_simulator.py     # painel PV (irradiância/temperatura -> P_dc)
│   ├── csv_sim_pandas.py         # séries climáticas (CSV -> Mosaik)
│   └── gen_pv_loadshapes.py      # utilitário: gera as curvas do PV a partir dos CSVs
└── data/13Bus/                   # o modelo IEEE 13 (ver abaixo)
```

### Portas dos simuladores (`--remote`)

| Serviço | Porta | Módulo |
|---|---|---|
| `opendss` | 5671 | `simulators.opendss_simulator` |
| `csv-data-1` / `csv-data-2` | 5675 / 5676 | `csv_sim_pandas.py` |
| `pv-panel` | 5678 | `pv_panel_simulator.py` |
| `smart-inverter` | 5680 | `smart_inverter_simulator.py` |

### Dados (`src/data/13Bus/`)

O topofile carregado pela co-simulação é **`run_ieee13_cosim_pv_5min.dss`**, que:

1. compila `IEEE13Nodeckt_w_loadcurve.dss` (o modelo IEEE 13 **com** as curvas
   diárias das cargas), que por sua vez faz `redirect` de `IEEELineCodes.dss`
   (impedâncias) e `LoadShape.dss` (as curvas), e carrega `IEEE13Node_BusXY.csv`
   (coordenadas);
2. faz `redirect` de `ieee13_shape_pv_5min.dss` (curvas do PV) e `ieee13_pv.dss`
   (os 5 PVSystems);
3. configura o modo diário (288 passos de 5 min) e trava os reguladores
   (`maxtapchange=0`), para isolar o efeito do controle Volt/Var dos agentes.

Os CSVs `ieee13_shape_pv_5min.csv` e `ieee13_temperature_5min.csv` trazem as
séries climáticas; as versões `*_48h.csv` alimentam o experimento `./run.sh 48h`.
O `IEEE13Nodeckt.dss` é o modelo IEEE 13 "puro" (sem as curvas), mantido apenas
como referência — a co-simulação usa a variante `_w_loadcurve`.

## Documentação

- [Cenário smart inverter](docs/how-to-guides/cenario_smart_pv.md) — o modelo do
  inversor (IEEE 1547: Volt/Var, Volt/Watt) e os modos de fase.

## Desenvolvedores

Para adicionar uma biblioteca Python, use `uv add <lib>` (as dependências vivem
em `pyproject.toml`; o `requirements.txt` é o que o Dockerfile instala).
