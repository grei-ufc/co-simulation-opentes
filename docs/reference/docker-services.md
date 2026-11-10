# Serviços Docker

O `docker-compose.yaml` define cinco serviços na rede `opentes-net`. Não os suba
à mão: o `run.sh` sobe na ordem certa e espera cada um ficar pronto.

| Serviço | Imagem | Porta | Comando | Papel |
|---|---|---|---|---|
| `comm` | `opentes/comm` | 5556 | compila o modelo e roda `sim_exec` (Cmdenv) | servidor de rede 6TiSCH e Wi-SUN no OMNeT++, consultado por ZMQ; só com `NET_BACKEND=omnet` |
| `grid` | `opentes/grid` | 5671 | `python -m simulators.opendss_simulator --remote 0.0.0.0:5671` | o circuito no OpenDSS, resolvido a cada passo de 15 min |
| `collector` | `opentes/mosaik` | 5673 | `python collectors/elec_collector.py --remote 0.0.0.0:5673` | grava tensões e potências de cada passo em `result_<tag>.csv` |
| `pade` | `opentes/pade` | 5678 | `python3 agents/market_agents.py` | os agentes do mercado (prosumidores, concentrador, DSO, mercado) e o simulador mosaik deles |
| `mosaik` | `opentes/mosaik` | nenhuma | `python scenarios/market.py` | o orquestrador: liga os agentes ao circuito no mesmo relógio |

O `mosaik` depende de `pade`, `grid` e `collector`. Os dois `--remote` aceitam
uma única conexão e encerram, por isso o `run.sh` sobe contêineres novos a cada
passada.

## Volumes

| Serviço | Pasta do host | No contêiner |
|---|---|---|
| `comm` | `simulators/comm-opentes` | `/root/models` |
| `comm` | `simulators/grid-opentes/src/data` | `/grid-data` (posições dos agentes e topologia de rádio gravada) |
| `grid` | `simulators/grid-opentes/src` | `/app/src` |
| `collector`, `mosaik` | `simulators/mosaik-opentes` | `/app` |
| `collector`, `mosaik`, `pade` | `output` | `/app/output` |
| `pade` | `simulators/pade-opentes/agents` | `/app/agents` |
| `pade` | `simulators/market-opentes` | `/market` |
| `pade` | `simulators/grid-opentes/src/data` | `/grid-data` (somente leitura) |
| `pade` | `$CPLEX_HOME` | `/opt/cplex` (somente leitura) |

Como o código é montado por volume, mudanças em `agents/`, `market-opentes/`,
`mosaik-opentes/` e `grid-opentes/src/` valem na próxima execução, sem
reconstruir a imagem. Mudanças em Dockerfile ou dependências pedem
`docker compose build`.

## Imagens

| Imagem | Base | O que tem |
|---|---|---|
| `opentes/comm` | `omnetpp/omnetpp:u22.04-6.0` | ZMQ e JSON para o servidor de rede |
| `opentes/grid` | `python:3.12.11-slim` | OpenDSS via `py-dss-interface` e o simulador mosaik do circuito |
| `opentes/pade` | `python:3.12.11-slim` | PADE 3.0, Pyomo, `mosaik-api-v3`, pyzmq e `py-dss-interface`; o CPLEX vem do host |
| `opentes/mosaik` | `python:3.12.11-slim` | mosaik, pandas e matplotlib; serve ao orquestrador, ao coletor e às figuras |
