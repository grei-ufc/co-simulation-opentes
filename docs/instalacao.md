# Instalação e execução

Há dois caminhos, com propósitos diferentes. O Docker é o caminho oficial de
**execução**; o `uv` é o caminho de **desenvolvimento**.

=== "Docker (recomendado)"

    Cada simulador roda no seu contêiner e nada é instalado no host. Requisitos:
    Docker e Docker Compose.

    ```bash
    git clone https://github.com/grei-ufc/co-simulation-opentes
    cd co-simulation-opentes
    docker compose build      # uma vez, ou após mudar Dockerfile/dependências
    ./run.sh integrated       # a co-simulação completa
    ```

    O primeiro `build` compila o OMNeT++ e leva alguns minutos. Os seguintes
    aproveitam o cache.

=== "uv (desenvolvimento)"

    Instala o **conjunto** num ambiente Python local, sem instalar simulador por
    simulador. Requisito: [`uv`](https://docs.astral.sh/uv/).

    ```bash
    uv sync     # cria .venv com tudo
    ```

    Isso traz `mosaik`, `opender`, `py-dss-interface`, `pandas`, `matplotlib` e
    `pyzmq`, mais o `pade-agents` e o `grid-opentes` como **dependências
    editáveis** apontando para o código deste repositório. Editar o código dos
    simuladores reflete direto no ambiente, o que serve para o autocomplete da
    IDE, para mexer no PADE ou no grid e para rodar os scripts de figura:

    ```bash
    MOSAIK_OUTPUT_DIR=output/integrated \
      uv run python simulators/mosaik-opentes/plot_integrated.py
    ```

!!! info "O alcance de cada caminho"

    O `uv` cobre todo o lado **Python**. A rede de comunicação é o **OMNeT++, em
    C++**, e existe apenas como contêiner, então os cenários que usam comunicação
    (`integrated`, `star`, `market` com `NET_BACKEND=omnet`) e todos os
    experimentos precisam do Docker. O `uv` sozinho serve para desenvolvimento,
    inspeção e geração de figuras.

## Os quatro contêineres funcionais

Os nomes refletem a função, e não a equipe de origem.

| Contêiner | Pasta | Papel |
|---|---|---|
| `comm` | `simulators/comm-opentes` | rede de comunicação (OMNeT++ e ponte ZMQ) |
| `pade` | `simulators/pade-opentes` | agentes PADE, em Python 3.12 |
| `mosaik` | `simulators/mosaik-opentes` | orquestrador, cenários e coletores |
| `grid` | `simulators/grid-opentes` | rede elétrica, OpenDSS via `py-dss-interface` |

Fora dos quatro, `simulators/market-opentes` guarda os modelos de otimização do
mercado em Pyomo, e `estudos/` os scripts curtos que sustentam decisões de
projeto. Nenhum dos dois é um contêiner: rodam sobre a imagem do `mosaik`, sem
subir a co-simulação inteira.

## O solver do mercado

O cenário `market` **exige um solver de otimização**. O padrão é o IBM CPLEX,
que tem licença acadêmica pessoal e por isso não está no repositório nem nas
imagens: ele é montado do host em tempo de execução.

```bash
export CPLEX_HOME=/caminho/para/cplex
./run.sh market
```

Sem CPLEX dá para usar um solver livre, `MARKET_SOLVER=ipopt`, ao custo de perder
a parte inteira do modelo do prosumidor. Os detalhes estão no
`simulators/market-opentes/README.md`. Os demais cenários não dependem de solver.

## Gerar as figuras

O `run.sh` já gera a dashboard dos cenários `integrated` e `ieee13` ao final da
execução. As demais saem sob demanda:

=== "Docker"

    ```bash
    # comparação do Volt/Var e caracterização da rede
    docker compose run --rm --no-deps -e MOSAIK_OUTPUT_DIR=/app/output/integrated \
      mosaik python plot_comparacao.py

    # figuras dos experimentos
    docker compose run --rm --no-deps -e MOSAIK_OUTPUT_DIR=/app/output/sensibilidade_perda \
      mosaik python plot_loss_sweep.py
    docker compose run --rm --no-deps -e MOSAIK_OUTPUT_DIR=/app/output/sensibilidade_48h \
      mosaik python plot_48h.py
    ```

=== "uv"

    ```bash
    MOSAIK_OUTPUT_DIR=output/sensibilidade_perda \
      uv run python simulators/mosaik-opentes/plot_loss_sweep.py
    ```

!!! danger "Não sondar as portas dos simuladores `--remote`"

    Os simuladores `--remote` do grid (portas 5671, 5673, 5675, 5676, 5678 e
    5680) aceitam uma **única** conexão Mosaik e encerram depois dela. Um probe
    TCP de prontidão consome essa conexão e mata o simulador, o que já foi
    verificado: o contêiner sai logo após o `connect`. Sonde por TCP apenas o
    `comm` (porta 5555, ZMQ); para os `--remote`, a prontidão é detectada pelo
    **log**, como faz o `_wait_remote_sims` do `run.sh`. É por isso que o
    `run.sh` sobe contêineres frescos a cada passada.

!!! bug "O contêiner do OpenDSS não roda com `--user`"

    Chamar o `grid` com `--user` derruba a engine com segfault. Rode como root e
    ajuste o dono das saídas depois:

    ```bash
    docker run --rm -v "$PWD/output:/out" alpine chown -R $(id -u):$(id -g) /out
    ```

## Este site

A documentação é construída com [MkDocs](https://www.mkdocs.org/) e o tema
[Material](https://squidfunk.github.io/mkdocs-material/), a partir do
`mkdocs.yml` na raiz:

```bash
uvx --with mkdocs-material mkdocs serve   # http://127.0.0.1:8000
uvx --with mkdocs-material mkdocs build   # site estático em site/
```

O `site/` é produto de compilação e está no `.gitignore`.
