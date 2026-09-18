# OpenTES — Co-simulação multidomínio (PADE + OMNeT++ + Mosaik + OpenDSS)

Repositório agregador da integração dos times **TSCC** (comunicação/co-simulação),
**TTESO** (agentes PADE) e **TSRE** (rede elétrica), tendo o **IEEE 13 Barras**
como benchmark. O Mosaik é o orquestrador temporal ("maestro"); toda a informação
elétrica trafega pela rede de comunicação simulada no OMNeT++, de modo que
latência, jitter e perda de pacotes sejam contabilizados.

## Estrutura — 4 containers funcionais

| Container | Pasta | Papel |
|-----------|-------|-------|
| `comm`   | `simulators/comm-opentes`   | Rede de comunicação (OMNeT++ + bridge ZMQ) |
| `pade`   | `simulators/pade-opentes`   | Agentes PADE (Python 3.12) |
| `mosaik` | `simulators/mosaik-opentes` | Orquestrador Mosaik + cenários + collectors |
| `grid`   | `simulators/grid-opentes`   | Rede elétrica IEEE 13 (OpenDSS via `py-dss-interface`) |

## Instalação

Há dois caminhos, com propósitos diferentes:

### 1. Docker Compose — para **rodar** a co-simulação (recomendado)

É o caminho oficial: cada simulador roda no seu container, nada é instalado no
host. Requisitos: Docker + Docker Compose.

```bash
docker compose build     # uma vez (ou após mudar Dockerfile/dependências)
./run.sh integrated      # pronto
```

### 2. `uv` — para **desenvolver** localmente, sem Docker

Instala o **conjunto** num ambiente Python local (não é preciso instalar
simulador por simulador). Requisito: [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync     # cria .venv com tudo (leva ~1s)
```

Isso traz `mosaik`, `opender`, `py-dss-interface`, `pandas`, `matplotlib`,
`pyzmq` e — como **dependências editáveis** apontando para o código deste repo —
o `pade-agents` (`simulators/pade-opentes`) e o `grid-opentes`
(`simulators/grid-opentes`). Editar o código dos simuladores reflete
direto no ambiente. Útil para IDE/autocomplete, mexer no PADE ou no grid e rodar
os scripts de figura:

```bash
MOSAIK_OUTPUT_DIR=output/integrated \
  uv run python simulators/mosaik-opentes/plot_integrated.py
```

> **Alcance de cada caminho:** o `uv` cobre todo o lado **Python**. A rede de
> comunicação (`comm`) é o **OMNeT++, em C++**, e existe apenas como container —
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
| `star`            | Comunicação pura: PADE ↔ OMNeT++ (50 agentes em estrela) — teste isolado | `output/star/` |
| `ieee13`          | Rede elétrica IEEE 13 + 5 PVs + inversores (só elétrico) — teste isolado | `output/ieee13/` |
| `market`          | **Mercado transativo** na rede MVLV75: negociação multiagente (PADE) + OpenDSS | `output/market/` |

> O cenário `market` **exige um solver de otimização** (IBM CPLEX por padrão), que
> não está no repositório nem nas imagens, por licença. Os demais cenários não
> dependem disso. Instalação, limitações e alternativas em
> [`simulators/market-opentes/README.md`](simulators/market-opentes/README.md#dependencias-e-o-solver).

O `integrated` é **a** simulação (a aplicação); `star` e `ieee13` são bancadas
de teste isoladas de cada bloco.

**Experimentos** (variam parâmetros do cenário integrado):

| Comando | O que faz | Resultado em |
|---------|-----------|--------------|
| `48h`             | Horizonte de 48 h (2 dias com a mesma irradiância) — verifica se o ciclo diário se repete. Perda 0% | `output/sensibilidade_48h/` |
| `loss-sweep`      | Sensibilidade do Volt/Var à perda de pacotes: baseline + 0/25/30/35/40/45/50/75/100%, 1 semente | `output/sensibilidade_perda/` |
| `loss-multiseed`  | Idem, varredura 0–100% (passo 5%) × 20 sementes, para média/desvio. **Resumível** | `output/sensibilidade_perda_multiseed/` |

```bash
./run.sh loss-sweep loss030 loss035   # roda só as passadas indicadas
```

Os experimentos editam o `omnetpp.ini` (perda/semente) e **o restauram ao final**,
mesmo se interrompidos. A leitura detalhada dos resultados é mantida fora do
repositório, em `Docs_Externo/EXPERIMENTO_PERDA.md`.

### O cenário integrado (`integrated`) — acoplamento causal Volt/Var

Evolução do `mosaik-opentes/scenarios/first.py` (que já unia PADE+OMNeT+++Mosaik),
agora fechando o laço com o OpenDSS. **PV System**: reproduz o estado do TSRE
(5 PVs injetando), mas **co-simulado e controlado** — cada um dos **5 inversores**
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
                              └────► (próximo passo: nova V) — laço fecha   (i = 1..5)
```

O cenário roda **duas vezes** e compara — **sem** controle (baseline) e **com**
controle (Volt/Var). A perda de pacotes é **parâmetro de modelo da rede**
(`drop_probability` no `omnetpp.ini`, herdado do TSCC = 15%) com **semente fixa**.
Registros em `output/integrated/`:

- `result_baseline.csv` / `result_volt_var.csv` — trajetórias elétricas (tensão
  de todas as barras, P_ref/Q_ref dos 5 controladores, P_meas/Q_meas dos 5 PVs).
- `comm_trace_baseline.csv` / `comm_trace_volt_var.csv` — rastro das mensagens
  pela rede OMNeT++ (FIPA com a tensão + telemetria: pacotes, latência, jitter).
- `dashboard_integrated.png` — painel de 8 quadros unindo os dois domínios:
  irradiância (5 PVs), temperatura, geração FV agregada, tensões das 13 barras,
  integridade de pacotes (pizza entregues×dropados), latência exata, jitter
  distribuído e o efeito do Volt/Var nas 5 barras PV.
- `comparacao_volt_var.png` — figura dedicada do controle atuando × não atuando
  (tensão por barra, σ e mínima por barra, resumo do ganho em p.u.).
- `analise_comunicacao.png` — caracterização da rede: histogramas de latência e
  jitter, integridade dos pacotes e pacotes acumulados.

A tabela completa do que cada arquivo apresenta está em
[`docs/INTEGRACAO.md`](docs/INTEGRACAO.md#resultados); o guia didático de cada
figura está em [`docs/RESULTADOS.md`](docs/RESULTADOS.md).

Resultado: o Volt/Var dá **suporte de tensão** — eleva as barras subtensionadas
(Bus 652: mínima 0,920 → 0,938 pu) e reduz o desvio em até 19% (média −10%), de
forma estável, com perda realista de **18,6%**. Achado importante: ganho
agressivo + atraso/perda da rede **desestabiliza** o controle distribuído (motiva
estudar o impacto da comunicação). Comparativo e
observações em [`docs/INTEGRACAO.md`](docs/INTEGRACAO.md#resultados).

## Figuras

O `run.sh` já gera a dashboard dos cenários `integrated` e `ieee13` ao final da
execução. As figuras adicionais são geradas sob demanda — via Docker:

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
> (verificado — o container sai logo após o connect). Sondar por TCP apenas o
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
├── sensibilidade_48h/            result_{baseline,volt_var}.csv  +  ciclo_48h.png
├── sensibilidade_perda/          result_<tag>.csv | comm_trace_<tag>.csv
│                                 sensibilidade_perda.png
└── sensibilidade_perda_multiseed/  result_lossNNN_sS.csv  +  figura multi-semente
```

O **guia didático** de cada arquivo (coluna a coluna, linha a linha) e de cada
gráfico está em [`docs/RESULTADOS.md`](docs/RESULTADOS.md).

## Coerência dos resultados

O IEEE 13 reproduz **exatamente** os valores do cenário de referência do TSRE
(Paulo Victor, branch `paulo-victor`): geração `P_dc` ≈ 3024,6 kW, `P_ac` ≈
2854,2 kW e `P_meas` ≈ 1902,7 kW de pico. As tensões ficam na faixa esperada do
IEEE 13 desbalanceado (barra 650/fonte em 1,0 pu; barras trifásicas 0,91–1,05 pu;
fases inexistentes de trechos monofásicos em 0,0).

Documentação: [`docs/GUIA.md`](docs/GUIA.md) (o mapa do repositório, para quem
chega agora), [`docs/INTEGRACAO.md`](docs/INTEGRACAO.md) (o que foi alterado em
cada componente para integrá-los, e por quê) e
[`docs/RESULTADOS.md`](docs/RESULTADOS.md) (guia da pasta `output/`).
