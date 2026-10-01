# OpenTES: co-simulação multidomínio (PADE + OMNeT++ + Mosaik + OpenDSS)

Repositório agregador da integração dos times **TSCC** (comunicação/co-simulação),
**TTESO** (agentes PADE) e **TSRE** (rede elétrica), tendo o **IEEE 13 Barras**
como benchmark. O Mosaik é o orquestrador temporal ("maestro"); toda a informação
elétrica trafega pela rede de comunicação simulada no OMNeT++, de modo que
latência, jitter e perda de pacotes sejam contabilizados.

Sobre a mesma plataforma roda a camada de **mercado transativo**, portada da tese
de referência do grupo.

## Estrutura: 4 containers funcionais

| Container | Pasta | Papel |
|-----------|-------|-------|
| `comm`   | `simulators/comm-opentes`   | Rede de comunicação (OMNeT++ + bridge ZMQ) |
| `pade`   | `simulators/pade-opentes`   | Agentes PADE (Python 3.12) |
| `mosaik` | `simulators/mosaik-opentes` | Orquestrador Mosaik + cenários + collectors |
| `grid`   | `simulators/grid-opentes`   | Rede elétrica (OpenDSS via `py-dss-interface`) |

Fora dos quatro, `simulators/market-opentes` guarda os modelos de otimização do
mercado em Pyomo, e `estudos/` os scripts curtos que sustentam decisões de
projeto. Nenhum dos dois é um container: rodam sobre a imagem do `mosaik`, sem
subir a co-simulação inteira.

## Instalação

Há dois caminhos, com propósitos diferentes:

### 1. Docker Compose, para **rodar** a co-simulação (recomendado)

É o caminho oficial: cada simulador roda no seu container, nada é instalado no
host. Requisitos: Docker + Docker Compose.

```bash
docker compose build     # uma vez (ou após mudar Dockerfile/dependências)
./run.sh integrated      # pronto
```

### 2. `uv`, para **desenvolver** localmente, sem Docker

Instala o **conjunto** num ambiente Python local (não é preciso instalar
simulador por simulador). Requisito: [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync     # cria .venv com tudo (leva ~1s)
```

Isso traz `mosaik`, `opender`, `py-dss-interface`, `pandas`, `matplotlib`,
`pyzmq` e, como **dependências editáveis** apontando para o código deste repo,
o `pade-agents` (`simulators/pade-opentes`) e o `grid-opentes`
(`simulators/grid-opentes`). Editar o código dos simuladores reflete
direto no ambiente. Útil para IDE/autocomplete, mexer no PADE ou no grid e rodar
os scripts de figura:

```bash
MOSAIK_OUTPUT_DIR=output/integrated \
  uv run python simulators/mosaik-opentes/plot_integrated.py
```

> **Alcance de cada caminho:** o `uv` cobre todo o lado **Python**. A rede de
> comunicação (`comm`) é o **OMNeT++, em C++**, e existe apenas como container,
> por isso os cenários que usam comunicação (`integrated`, `star`) e todos os
> experimentos precisam do **Docker**. O `uv` sozinho serve para desenvolvimento,
> inspeção e geração de figuras.

## Cenários e experimentos

Tudo se executa pelo script único `run.sh`, que faz a limpeza completa do Docker
antes/depois (evita o erro `network ... not found` causado por containers de
profile que o `down` simples não remove) e espera os simuladores ficarem prontos:

```bash
./run.sh integrated     # co-simulação completa (o comando do dia a dia)
./run.sh market         # mercado transativo (exige CPLEX; ver abaixo)
./run.sh --help         # lista todos os cenários e experimentos
```

**Cenários:**

| Cenário | O que faz | Resultado em |
|---------|-----------|--------------|
| `integrated`      | **Co-simulação completa** dos 4 containers (Volt/Var causal) | `output/integrated/` |
| `star`            | Comunicação pura, PADE ↔ OMNeT++ com 50 agentes em estrela. Bancada isolada | `output/star/` |
| `ieee13`          | Rede elétrica IEEE 13 + 5 PVs + inversores, sem comunicação. Bancada isolada | `output/ieee13/` |
| `market`          | **Mercado transativo**: negociação multiagente (PADE) + OpenDSS. A rede vem de `MARKET_NETWORK` | `output/market*/` |

O `market` aceita quatro redes: `MVLV75` (padrão, a da tese), `BT16` e `BT38` (as
duas projetadas neste trabalho) e `13Bus` (o mesmo benchmark da plataforma, agora
como caso de mercado). Cada uma grava no seu diretório:

```bash
MARKET_NETWORK=13Bus ./run.sh market    # -> output/market_13Bus/
```

> O cenário `market` **exige um solver de otimização** (IBM CPLEX por padrão), que
> não está no repositório nem nas imagens, por licença. Os demais cenários não
> dependem disso. Instalação, limitações e alternativas em
> [`simulators/market-opentes/README.md`](simulators/market-opentes/README.md#dependencias-e-o-solver).

O `integrated` é **a** simulação (a aplicação); `star` e `ieee13` são bancadas
de teste isoladas de cada bloco.

**Experimentos** (variam parâmetros do cenário integrado):

| Comando | O que faz | Resultado em |
|---------|-----------|--------------|
| `48h`             | Horizonte de 48 h (2 dias com a mesma irradiância): verifica se o ciclo diário se repete. Perda 0% | `output/sensibilidade_48h/` |
| `loss-sweep`      | Sensibilidade do Volt/Var à perda de pacotes: baseline + 0/25/30/35/40/45/50/75/100%, 1 semente | `output/sensibilidade_perda/` |
| `loss-multiseed`  | Idem, varredura 0–100% (passo 5%) × 20 sementes, para média/desvio. **Resumível** | `output/sensibilidade_perda_multiseed/` |

```bash
./run.sh loss-sweep loss030 loss035   # roda só as passadas indicadas
```

Os experimentos editam o `omnetpp.ini` (perda/semente) e **o restauram ao final**,
mesmo se interrompidos. A leitura detalhada dos resultados é mantida fora do
repositório, em `Docs_Externo/EXPERIMENTO_PERDA.md`.

### O cenário integrado (`integrated`): acoplamento causal Volt/Var

Evolução do `mosaik-opentes/scenarios/first.py` (que já unia PADE+OMNeT+++Mosaik),
agora fechando o laço com o OpenDSS. **PV System**: reproduz o estado do TSRE
(5 PVs injetando), mas **co-simulado e controlado**: cada um dos **5 inversores**
tem um par de agentes (medidor + controlador Volt/Var) e a tensão da sua barra
trafega pela rede OMNeT++:

```
OpenDSS resolve V  ──►  AgenteA_i (medidor) lê a tensão da barra do PV_i
                              │  publica mensagem FIPA-ACL (marcada com a barra)
                              ▼
                        OMNeT++  (latência / jitter / perda de pacotes)
                              │  tensão chega ATRASADA
                              ▼
                        AgenteB_i (controlador Volt/Var):
                          P (ativa)   = solar disponível
                          Q (reativa) = f(tensão),  S = √(P²+Q²) ≤ kVA
                              │
                              ▼
                        PVSystem.PV_i (P_des, Q_des) ──► OpenDSS muda a injeção
                              │
                              └────► (próximo passo: nova V), laço fecha   (i = 1..5)
```

O cenário roda **duas vezes** e compara **sem** controle (baseline) contra
**com** controle (Volt/Var). A perda de pacotes é **parâmetro de modelo da rede**
(`drop_probability` no `omnetpp.ini`, herdado do TSCC = 15%) com **semente fixa**.
Registros em `output/integrated/`:

- `result_baseline.csv` e `result_volt_var.csv`: trajetórias elétricas (tensão
  de todas as barras, P_ref/Q_ref dos 5 controladores, P_meas/Q_meas dos 5 PVs).
- `comm_trace_baseline.csv` e `comm_trace_volt_var.csv`: rastro das mensagens
  pela rede OMNeT++ (FIPA com a tensão + telemetria: pacotes, latência, jitter).
- `dashboard_integrated.png`: painel de 8 quadros unindo os dois domínios:
  irradiância (5 PVs), temperatura, geração FV agregada, tensões das 13 barras,
  integridade de pacotes (pizza entregues×dropados), latência exata, jitter
  distribuído e o efeito do Volt/Var nas 5 barras PV.
- `comparacao_volt_var.png`: figura dedicada do controle atuando × não atuando
  (tensão por barra, σ e mínima por barra, resumo do ganho em p.u.).
- `analise_comunicacao.png`: caracterização da rede, com histogramas de latência e
  jitter, integridade dos pacotes e pacotes acumulados.

A tabela completa do que cada arquivo apresenta está em
[`docs/INTEGRACAO.md`](docs/INTEGRACAO.md#resultados); o guia didático de cada
figura está em [`docs/RESULTADOS.md`](docs/RESULTADOS.md).

Resultado, com perda medida de **17,4%** sobre o parâmetro de 15%: o Volt/Var
atua nas duas pontas da faixa. Eleva as barras subtensionadas (Bus 652: mínima
0,9203 → 0,9366 pu) e corta a sobretensão onde ela existe (Bus 646: máxima
1,0517 → 1,0437 pu), com o desvio-padrão da tensão caindo 15% em média e 20% na
barra 652. Achado importante: ganho agressivo somado ao atraso e à perda da rede
**desestabiliza** o controle distribuído, o que motiva estudar o impacto da
comunicação. Comparativo e observações em
[`docs/INTEGRACAO.md`](docs/INTEGRACAO.md#resultados).

## Figuras

O `run.sh` já gera a dashboard dos cenários `integrated` e `ieee13` ao final da
execução. As figuras adicionais são geradas sob demanda, via Docker:

```bash
# comparação do Volt/Var + caracterização da rede (após ./run.sh integrated)
docker compose run --rm --no-deps -e MOSAIK_OUTPUT_DIR=/app/output/integrated \
  mosaik python plot_comparacao.py     # comparacao_volt_var.png + analise_comunicacao.png

# figuras dos experimentos
docker compose run --rm --no-deps -e MOSAIK_OUTPUT_DIR=/app/output/sensibilidade_perda \
  mosaik python plot_loss_sweep.py
docker compose run --rm --no-deps -e MOSAIK_OUTPUT_DIR=/app/output/sensibilidade_48h \
  mosaik python plot_48h.py
```

…ou localmente, com o ambiente do `uv` (apontando `MOSAIK_OUTPUT_DIR` para o
caminho no host):

```bash
MOSAIK_OUTPUT_DIR=output/sensibilidade_perda \
  uv run python simulators/mosaik-opentes/plot_loss_sweep.py
```

> **Atenção operacional**: os simuladores `--remote` do grid (portas 5671, 5673,
> 5675, 5676, 5678, 5680) aceitam uma **única** conexão Mosaik e encerram após.
> Por isso o `run.sh` sempre sobe containers frescos. **Não sondar essas portas
> com TCP de readiness**: o probe consome a conexão e mata o simulador
> (verificado: o container sai logo após o connect). Sondar por TCP apenas o
> `comm` (5555, ZMQ). Para os `--remote`, a prontidão é detectada pelo **log**
> (ver `_wait_remote_sims` no `run.sh`).

## Onde observar os resultados

Tudo é gravado em `output/`, separado por cenário:

```
output/
├── star/             results.csv  +  grafico_trafego.png
├── ieee13/           result_run_ieee13_cosim_pv_5min.csv  +  ieee13_dashboard.png
├── integrated/       result_baseline.csv | result_volt_var.csv
│                     comm_trace_baseline.csv | comm_trace_volt_var.csv
│                     dashboard_integrated.png
│                     comparacao_volt_var.png | analise_comunicacao.png
├── market/           result_baseline.csv | result_negociado.csv  (rede MVLV75)
├── market_13Bus/     idem, sobre o IEEE 13, + dlmp.csv, transactions.csv
├── market_BT16/, market_BT38/     idem, nas redes projetadas
│                     (o registro da negociacao, run.json, fica em
│                      simulators/market-opentes/data/run_<REDE>/)
├── sensibilidade_48h/            result_{baseline,volt_var}.csv  +  ciclo_48h.png
├── sensibilidade_perda/          result_<tag>.csv | comm_trace_<tag>.csv
│                                 sensibilidade_perda.png
└── sensibilidade_perda_multiseed/  result_lossNNN_sS.csv  +  figura multi-semente
```

O **guia didático** de cada arquivo (coluna a coluna, linha a linha) e de cada
gráfico está em [`docs/RESULTADOS.md`](docs/RESULTADOS.md).

## Coerência dos resultados

A referência de validação do bloco elétrico é o **perfil de tensão publicado do
IEEE 13 Node Test Feeder**: com as derivações do regulador nos valores oficiais, o
circuito o reproduz com erro médio de **0,00044 pu** e máximo de 0,00134 pu nas 33
medidas de fase da tabela. As tensões ficam na faixa esperada do alimentador
desbalanceado (barra 650/fonte em 1,0 pu; demais barras entre 0,909 e 1,059 pu;
fases inexistentes de trechos monofásicos em 0,0), e a geração fotovoltaica
agregada tem pico de 4.030 kW no cenário isolado.

Os números publicados pelo TSRE (`P_dc` 3.024,6 / `P_ac` 2.854,2 / `P_meas`
1.902,7 kW no PV1) não são reproduzidos, e isso é intencional: dois defeitos
herdados foram corrigidos no caminho, a temperatura do módulo que vinha dividida
por 25 e o PV1 declarado em três fases numa barra que só tem duas. O registro está
em [`docs/INTEGRACAO.md`](docs/INTEGRACAO.md#validação-do-bloco-elétrico-cenário-ieee13-isolado).

## Documentação

O site completo, com tudo isto navegável, sai de `mkdocs.yml`:

```bash
uvx --with mkdocs-material mkdocs serve     # http://127.0.0.1:8000
```

| Documento | Para quê |
|---|---|
| [`docs/GUIA.md`](docs/GUIA.md) | o mapa do repositório, para quem chega agora |
| [`docs/INTEGRACAO.md`](docs/INTEGRACAO.md) | o que foi alterado em cada componente para integrá-los, e por quê |
| [`docs/RESULTADOS.md`](docs/RESULTADOS.md) | guia da pasta `output/`, arquivo por arquivo |
| [`docs/MERCADO.md`](docs/MERCADO.md) | a formulação do mercado transativo, equação por equação |
| [`estudos/ieee13/README.md`](estudos/ieee13/README.md) | os scripts que refazem as decisões de projeto do caso IEEE 13 |
