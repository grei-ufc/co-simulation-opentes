# Variáveis de ambiente

Todas têm valor padrão no `docker-compose.yaml`, com um comentário sobre cada
uma. Valem na frente de qualquer comando (`MARKET_FASE=0 ./run.sh market`), e o
console grava as que configura em `.opentes.env`.

## Execução

| Variável | Padrão | O que muda |
|---|---|---|
| `CPLEX_HOME` | nenhum (obrigatória) | pasta `cplex` da instalação do CPLEX no host, montada nos contêineres |
| `OPENTES_SAIDA` | `market` ou `market_por_no` | pasta de resultados dentro de `output/` |
| `MOSAIK_N_PASSOS` | `96` | passos de 15 min da co-simulação |

## Formulação do mercado

| Variável | Padrão | O que muda |
|---|---|---|
| `MARKET_FASE` | `1` | `1`: tensão e preço sombra por fase. `0`: por barra, com a média das fases (a formulação da tese), para comparação |
| `MARKET_DISPOSITIVO` | `independente` | inversor de quatro fios, com cada fase despachada separadamente; `equilibrado`: três fios, potência igual nas fases |
| `MARKET_REGULADOR` | `previsao` | derivações do regulador fixadas pelo ponto da previsão; `neutro` as deixa em 0 |
| `MARKET_CRITERIO` | `relativo` | critério de parada: `relativo` à potência de cada dispositivo, ou `absoluto` (variação de λ até `MARKET_EPS`, o da tese) |
| `MARKET_EPS_REL` | `1e-3` | desacordo máximo entre concentrador e DSO, em fração da potência do dispositivo |
| `MARKET_EPS` | `1e-3` | tolerância do critério absoluto |
| `MARKET_ALPHA` | `0.6` | passo do subgradiente |
| `MARKET_MAX_ROUNDS` | `150` | teto de rodadas da negociação |
| `MARKET_SCENARIOS` | `1` | cenários por prosumidor; `1` é determinístico, `3` gera nove cenários de preço e potência |
| `MARKET_V_BACKOFF` | `1e-3` | margem nos limites de tensão dentro do modelo do DSO, contra o erro da linearização |
| `MARKET_STORAGE_PF` | `none` | fator de potência do armazenamento; `none` é a hipótese ΔQ = 0 |
| `MARKET_SOLVER` | `cplex` | solver do Pyomo |
| `MARKET_CK_EUR` | vazio | calibração do peso `Ck` em EUR/(kW²·h); sem ela, o preço sombra e o DLMP saem como sinal |

## Fase de operação

| Variável | Padrão | O que muda |
|---|---|---|
| `MARKET_NEGOTIATE` | `1` | `0` publica a programação proposta pelos prosumidores, sem negociação (a passada `baseline`; o `run.sh` define sozinho) |
| `MARKET_OPERATION` | `1` | liga a fase de operação a cada 15 min |
| `MARKET_REALIZED` | `1` | a rede vê a demanda realizada, e não a prevista |
| `MARKET_REALIZED_MODE` | `perturb` | como a demanda realizada difere da programada: `perturb` perturba a programação de cada prosumidor; `day` usa um dia do reservatório de cenários |
| `MARKET_REALIZED_SPREAD` | `0.10` | no modo `perturb`, a perturbação máxima da programação de cada prosumidor (±10%) |
| `MARKET_REALIZED_DAY` | `9` | no modo `day`, o dia do reservatório usado como realização |
| `MARKET_V_ACAO_MIN`, `MARKET_V_ACAO_MAX` | `0.971`, `1.03` | limiar de ação da operação; o limite contado continua 0,97 e 1,03 pu |
| `MARKET_ROUND_TIMEOUT` | vazio | tempo limite de cada ciclo antes de retransmitir; vazio é 120 s com entrega ideal e três janelas de tempo de rede nos outros backends |

## Rede entre os agentes

| Variável | Padrão | O que muda |
|---|---|---|
| `NET_BACKEND` | `ideal` | `ideal` (entrega imediata), `lossy` (perda e atraso sorteados) ou `omnet` (servidor de rede do OMNeT++) |
| `NET_TIME_SCALE` | `1.0` | fração do atraso nominal esperada em relógio real; com `omnet`, use `0.02` |
| `NET_DROP_PROBABILITY` | `0.0` | com `lossy`, a probabilidade de cada mensagem se perder |
| `NET_MESSAGE_SIZE` | `real` | tamanho informado à rede: `real` (conteúdo serializado) ou `declarado` (classes fixas da implementação de referência) |
| `NET_TRACE` | vazio | arquivo do traço de mensagens; o `run.sh` o define com `omnet` |

## OMNeT++

Só com `NET_BACKEND=omnet`.

| Variável | Padrão | O que muda |
|---|---|---|
| `TISCH_MAC` | `tsch` | acesso ao meio: `tsch` (6TiSCH, a rede da tese) ou `wisun` (Wi-SUN FAN) |
| `TISCH_CELLS` | `2` | na 6TiSCH, fatias por enlace a cada *slotframe* de 4,04 s |
| `TISCH_RATE_BPS` | `50000` | no Wi-SUN, a taxa do rádio: `50000`, `150000` ou `300000` |
| `TISCH_ARGS` | vazio | parâmetros extras do `Tisch.ned` na linha de comando do OMNeT++, como `--**.tisch.colocated_wired=true` |
