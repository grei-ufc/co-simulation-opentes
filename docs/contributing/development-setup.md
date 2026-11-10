# Ambiente de desenvolvimento

## Fork e branches

As mudanças entram no repositório do grupo por pull request, a partir de um
fork:

```bash
git clone https://github.com/<seu-usuario>/co-simulation-opentes
cd co-simulation-opentes
git remote add upstream https://github.com/grei-ufc/co-simulation-opentes
git fetch upstream
git switch -c minha-mudanca upstream/main
```

Ao terminar, envie a branch para o fork e abra o pull request para o `main` de
`grei-ufc/co-simulation-opentes`.

## Ambiente

```bash
docker compose build          # as imagens dos simuladores
uv sync                       # .venv local, para a IDE e scripts fora dos contêineres
uv sync --group docs          # acrescenta as ferramentas da documentação
```

O código de `agents/`, `market-opentes/`, `mosaik-opentes/` e `grid-opentes/src/`
é montado por volume nos contêineres: uma mudança vale na próxima execução, sem
reconstruir a imagem ([Serviços Docker](../reference/docker-services.md#volumes)).

## Conferir uma mudança

O repositório não tem suíte de testes automatizados. A conferência é rodar o
cenário e comparar com os números de referência:

| Mudança em | Rode | Confira |
|---|---|---|
| mercado ou otimização | `./run.sh centralizado` | 42 rodadas; `dlmp.csv`, `transactions.csv`, `market_series.csv` e `flexibility.csv` iguais aos de antes, se a mudança não devia alterar o resultado |
| agentes ou camada de rede | `./run.sh market` | 42 rodadas no `run.json`; 9 leituras acima de 1,03 pu no `result_negociado.csv` |
| caso ou circuito | `./run.sh caso`, depois os dois acima | os números de [Resultados](../results.md) |
| `run.sh` ou console | `bash -n run.sh && bash -n cli/console.sh` e uma execução pelo console | sintaxe e fluxo |

Não edite o `run.sh` ou o `docker-compose.yaml` enquanto uma execução estiver
rodando: o bash lê o script aos poucos, e a execução em curso pode quebrar.

## Comentários e textos

O código, os comentários e esta documentação estão em português. Os
comentários explicam o porquê de cada escolha, e os modelos citam as equações da
tese pelo número, como (6.25). As docstrings alimentam a
[API gerada](../reference/api/index.md).
