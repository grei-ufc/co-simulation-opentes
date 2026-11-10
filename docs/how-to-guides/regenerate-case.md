# Regenerar o caso IEEE 13

O caso de mercado em `simulators/grid-opentes/src/data/13Bus/` é gerado a partir
do circuito oficial. Regenere depois de mudar o circuito, as curvas de PV ou a
alocação de armazenamento; fora isso, não é preciso.

## Tudo de uma vez

```bash
./run.sh caso
```

Roda o `gen_ieee13_market.py` e gera as duas matrizes de sensibilidade
(`sensitivity_day.npz`, por barra, e `sensitivity_fase.npz`, por fase). Leva
cerca de um minuto.

As matrizes também são geradas sozinhas pelo `centralizado` e pelo `market`
quando faltam, ou quando foram geradas por uma versão anterior, sem as
derivações do regulador.

## Passo a passo, pela imagem do grid

```bash
docker compose build grid

# o caso, a partir do circuito oficial e das curvas de PV
docker compose run --rm --no-deps grid python src/simulators/gen_ieee13_market.py

# a matriz por fase (sem --por-fase, a por barra)
docker compose run --rm --no-deps -e GRID_DIR=/app/src/data/13Bus grid \
  python src/simulators/sensitivity.py day --por-fase \
  --load-csv /app/src/data/13Bus/load_kw.csv --pv-csv /app/src/data/13Bus/pv_kw.csv \
  --out /app/src/data/13Bus/sensitivity_fase.npz
```

## As curvas de PV

Se as estações solares de `src/data/InfoPV/` mudarem, refaça as curvas antes do
caso:

```bash
docker compose run --rm --no-deps grid python src/simulators/pv_creator.py
```

## O que muda e o que não

Os arquivos de `13Bus/` que **não** são gerados ficam como estão: o circuito
oficial (`IEEE13Nodeckt*.dss`, `IEEELineCodes.dss`, `LoadShape.dss`), as curvas
de PV (`ieee13_*_5min.*`, saídas do `pv_creator`) e o preço spot
(`spot_price.csv`). A lista completa está em
[Arquivos de dados](../reference/data-files.md).

!!! warning "Os repositórios do TTESO carregam uma cópia do caso"

    O [tteso-market-opentes](https://github.com/grei-ufc/tteso-market-opentes)
    traz os arquivos do caso e as matrizes em `market_opentes/dados/ieee13/`.
    Depois de regenerar aqui, copie-os para lá, ou os dois repositórios passam a
    negociar sobre casos diferentes.
