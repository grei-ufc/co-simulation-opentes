# grid-opentes: a rede elétrica

O OpenDSS, chamado pelo `py-dss-interface`, com o caso IEEE 13 barras do
mercado. Resolve o fluxo de potência de cada passo da co-simulação e mede as
matrizes de sensibilidade que o operador da rede usa na negociação.

## O papel no projeto

```mermaid
flowchart LR
    G[gen_ieee13_market.py] -- caso --> D[(src/data/13Bus)]
    D --> S[sensitivity.py] -- matrizes dV/dP --> M[tteso-market-opentes]
    D --> O[api_opendss do TSRE<br/>contêiner grid] <-- potência por porta,<br/>derivações / tensões --> K[Mosaik]
```

- **Antes da co-simulação:** `gen_ieee13_market.py` monta o caso a partir do
  circuito oficial, e `sensitivity.py` mede, por perturbação no próprio OpenDSS,
  quanto a tensão de cada barra (ou fase) muda com 1 kW injetado em cada ponto.
  O mercado (`teams/tteso-market-opentes`) usa essas matrizes na restrição de
  tensão do DSO.
- **Durante a co-simulação:** o contêiner `grid` expõe o circuito ao Mosaik
  com o adaptador do TSRE, lido do submódulo `teams/tsre-der-opentes`.
  A cada 15 minutos recebe a potência de cada carga e porta de armazenamento e
  as derivações do regulador, resolve o fluxo e devolve as tensões.

## O que há aqui

```
src/simulators/
  gen_ieee13_market.py   monta o caso de mercado (./run.sh caso)
  sensitivity.py         matrizes de sensibilidade de tensão, por barra e por fase
  pv_creator.py          curvas de irradiância e temperatura dos cinco PV
  pv_validator.py        conferências das curvas e da ligação dos PV
src/data/
  13Bus/                 o caso: circuito, perfis, alocação, posições de rádio, matrizes
  InfoPV/                estações solares (BR-PVGen) que alimentam o pv_creator
Dockerfile, requirements.txt   a imagem opentes/grid
pyproject.toml                 o mesmo pacote, para uso local com `uv`
```

O simulador do circuito não está aqui: é o adaptador do TSRE
(`src/simulators/opendss/` do `tsre-der-opentes`), que o `docker-compose.yaml`
monta do submódulo `teams/tsre-der-opentes` em `/tsre/src` e o contêiner roda com
`python -m simulators.opendss.api_opendss --remote 0.0.0.0:5671`.

Os arquivos de `13Bus/` que **não** são gerados: o circuito oficial
(`IEEE13Nodeckt*.dss`, `IEEELineCodes.dss`, `LoadShape.dss`), as curvas de PV
(`ieee13_*_5min.*`, saídas do `pv_creator`) e o preço spot (`spot_price.csv`).
O resto sai do `gen_ieee13_market.py` e do `sensitivity.py`.

## Rodar

Dentro do projeto, pelo `run.sh` da raiz: `./run.sh market` sobe este contêiner,
e `./run.sh caso` regenera o caso e as matrizes. Isolado, pela imagem:

```bash
docker compose build grid
# o caso, a partir do circuito oficial e das curvas de PV
docker compose run --rm --no-deps grid python src/simulators/gen_ieee13_market.py
# a matriz por fase (sem --por-fase, a por barra)
docker compose run --rm --no-deps -e GRID_DIR=/app/src/data/13Bus grid \
  python src/simulators/sensitivity.py day --por-fase \
  --load-csv /app/src/data/13Bus/load_kw.csv --pv-csv /app/src/data/13Bus/pv_kw.csv \
  --out /app/src/data/13Bus/sensitivity_fase.npz
# as curvas de PV, se as estações mudarem
docker compose run --rm --no-deps grid python src/simulators/pv_creator.py
```

O simulador `--remote` aceita **uma única** conexão Mosaik e encerra depois
dela: não sonde a porta com TCP. O OpenDSS da imagem só carrega rodando como
root no contêiner.

## Autoria

O simulador Mosaik do OpenDSS e o gerador de curvas de PV são da equipe TSRE do
OpenTES. O simulador vem do
[tsre-der-opentes](https://github.com/grei-ufc/tsre-der-opentes) pelo submódulo
`teams/tsre-der-opentes`, que segue a branch `integration-tsre`: para atualizar,
`./run.sh submodulos atualizar` e `./run.sh market` para conferir o resultado. O
`pv_creator.py` foi adaptado do mesmo repositório (versão 1.1.1). O que este repositório muda em relação ao
adaptador fica fora da pasta: o coletor grava `0.0` na fase que a barra não tem
(o adaptador devolve `NaN`), e o cenário envia a derivação do regulador a cada
passo, porque sem comando o adaptador a deixa onde o circuito a resolveu ao
compilar. O caso de mercado e as matrizes de
sensibilidade são do time TTESO. Mais sobre o caso em
[docs/explanation/ieee13-case.md](../docs/explanation/ieee13-case.md).
