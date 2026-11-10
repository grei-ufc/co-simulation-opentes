# Rodar um simulador sozinho

O `run.sh` sobe os contêineres juntos e na ordem certa. Para testar ou estudar
uma parte, cada uma também roda isolada.

## O mercado, sem agentes nem mosaik

```bash
./run.sh centralizado
```

A decomposição dual num laço único, na imagem `opentes/pade`. Fora do Docker, o
mesmo pacote está no
[tteso-market-opentes](https://grei-ufc.github.io/tteso-market-opentes/), com o
caso embutido.

## Os agentes, sem mosaik

A negociação entre os agentes PADE, sem OpenDSS nem OMNeT++, está no
[tteso-agents-opentes](https://grei-ufc.github.io/tteso-agents-opentes/)
(`agentes/negociacao_isolada.py`).

## Um exemplo do PADE

A imagem `opentes/pade` traz o PADE 3.0 com os exemplos:

```bash
docker compose build pade
docker run --rm -w /opt/pade/pade/tests/agent_example_4 opentes/pade:local \
  pade start-runtime --username pade_user --password 12345 --port 24000 agent_example_4_updated.py
```

O `start-runtime` sobe o AMS, o Sniffer e o script dos agentes, e grava a sessão
em `logs/`. A lista dos exemplos está no README de `simulators/pade-opentes/`.

## O servidor de rede

```bash
docker compose up comm      # a primeira vez compila e leva alguns minutos
```

O servidor anuncia `[6TiSCH] pronto` no log quando aceita consultas, na porta
5556, e fica esperando.

## O grid

O caso e as matrizes rodam pela imagem do grid, como em
[Regenerar o caso](regenerate-case.md#passo-a-passo-pela-imagem-do-grid). O
simulador em si (`opendss_simulator.py --remote`) só faz sentido com o mosaik do
outro lado, e aceita uma única conexão.
