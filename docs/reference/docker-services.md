# Serviços Docker

O `docker-compose.yaml` define cinco serviços na rede `opentes-net`. Não os suba
à mão: o `run.sh` sobe na ordem certa e espera cada um ficar pronto.

| Serviço | Imagem | Porta | Comando | Papel |
|---|---|---|---|---|
| `comm` | `opentes/comm` | 5556 | compila o modelo e roda `sim_exec` (Cmdenv) | servidor de rede 6TiSCH e Wi-SUN no OMNeT++, consultado por ZMQ; só com `NET_BACKEND=omnet` |
| `comm-tscc` | `opentes/comm-tscc` | 5556 | gera a rede (`python -m cosim.ieee13`), compila e roda `sim_exec -f consulta.ini` | a rede do TSCC no lugar do `comm`, com o alias `comm`; só com `NET_BACKEND=omnet COMM=tscc` |
| `grid` | `opentes/grid` | 5671 | `python -m simulators.opendss.api_opendss --remote 0.0.0.0:5671` (o adaptador do TSRE) | o circuito no OpenDSS, resolvido a cada passo de 15 min |
| `collector` | `opentes/grid` | 5673 | `python -m simulators.collector.collector --remote 0.0.0.0:5673` (o coletor do TSRE) | grava tensões e potências de cada passo em `result_<tag>.csv` |
| `pade` | `opentes/pade` | 5678 | `python3 agents/market_agents.py` | os agentes do mercado (prosumidores, concentrador, DSO, mercado) e o simulador mosaik deles |
| `mosaik` | `opentes/mosaik` | nenhuma | `python scenarios/market.py` | o orquestrador: liga os agentes ao circuito no mesmo relógio |

O `mosaik` depende de `pade`, `grid` e `collector`. Os dois `--remote` aceitam
uma única conexão e encerram, por isso o `run.sh` sobe contêineres novos a cada
passada.

## Volumes

| Serviço | Pasta do host | No contêiner |
|---|---|---|
| `comm` | `temp/comm-opentes` | `/root/models` |
| `comm` | `teams/tsre-der-opentes/data` | `/grid-data` (posições dos agentes e topologia de rádio gravada) |
| `comm-tscc` | `teams/tscc-com-opentes` | `/root/models` |
| `comm-tscc` | `teams/tsre-der-opentes/data` | `/grid-data` (posições dos agentes, somente leitura) |
| `comm-tscc` | `output` | `/output` (levantamento dos enlaces simulados, `tscc_links.csv`) |
| `grid`, `collector` | `teams/tsre-der-opentes/src` | `/app/src` (adaptador, coletor e ferramentas do caso, somente leitura) |
| `grid` | `teams/tsre-der-opentes/data` | `/app/data` (o caso IEEE 13) |
| `mosaik` | `temp/mosaik-opentes` | `/app` |
| `collector`, `mosaik`, `pade` | `output` | `/app/output` |
| `pade` | `teams/tteso-agents-opentes/agentes` | `/app/agents` (somente leitura) |
| `pade` | `teams/tteso-market-opentes` | `/market` (somente leitura) |
| `pade` | `teams/tsre-der-opentes/data` | `/grid-data` (somente leitura) |
| `pade` | `$CPLEX_HOME` | `/opt/cplex` (somente leitura) |

Como o código é montado por volume, mudanças em `teams/` (um submódulo
atualizado) e `temp/mosaik-opentes/` valem na próxima execução,
sem reconstruir a imagem. Mudanças em Dockerfile ou dependências pedem
`docker compose build`.

## Imagens

| Imagem | Base | O que tem |
|---|---|---|
| `opentes/comm` | `omnetpp/omnetpp:u22.04-6.0` | ZMQ e JSON para o servidor de rede |
| `opentes/grid` | `python:3.12.11-slim` | OpenDSS via `py-dss-interface`, o adaptador mosaik do circuito e o coletor |
| `opentes/pade` | `python:3.12.11-slim` | PADE 3.0, Pyomo, `mosaik-api-v3`, pyzmq e `py-dss-interface`; o CPLEX vem do host |
| `opentes/mosaik` | `python:3.12.11-slim` | mosaik, pandas e matplotlib; serve ao orquestrador e às figuras |
