# market-opentes: o modelo de mercado

Biblioteca Python com a formulação do mercado transativo: os modelos de
otimização de cada agente, a decomposição dual que coordena os três, a fase de
operação, a liquidação e as figuras. A formulação vem de Melo (2022, cap. 6), e
os comentários do código citam as equações de lá pelo número, como (6.25).

## O papel no projeto

Esta pasta não tem contêiner nem processo próprio. Ela é usada de dois jeitos:

- **pelos agentes** (`simulators/pade-opentes`), que a importam e chamam um
  modelo por vez, cada um no seu papel. É o caminho da co-simulação
  (`./run.sh market`);
- **sozinha**, no `./run.sh centralizado`: a mesma negociação num laço único,
  sem agentes nem Mosaik, que mostra se a decomposição converge e gera a
  liquidação e os dados das figuras.

Nos dois casos ela roda dentro da imagem `opentes/pade`, que tem o Pyomo, montada
em `/market`, com o CPLEX montado do host. As figuras rodam na imagem
`opentes/mosaik`, que tem o matplotlib.

## O que há aqui

```
market_opentes/
  config.py              o caso, a faixa de tensão e as chaves do armazenamento (por barra ou por porta)
  optimization.py        os modelos: prosumidor (6.1)-(6.9), concentrador (6.25)-(6.26), DSO (6.27)-(6.29)
  dual.py                a decomposição dual centralizada, com o subgradiente (6.30)
  operation.py           a fase de operação, intervalo a intervalo, e a demanda realizada
  scenarios.py           geração e redução de cenários do prosumidor (Kantorovich)
  settlement.py          transações, preço locacional (DLMP) e flexibilidade
  figuras.py             as figuras de uma execução (./run.sh figuras)
  figuras_mensagens.py   as figuras do traço de mensagens, chamadas pelo figuras.py
```

As entradas (`config.json`, perfis, preço, matrizes de sensibilidade) vêm de
`grid-opentes/src/data/13Bus/`; os caminhos são lidos de `MARKET_DATA_DIR` e
`MARKET_GRID_DIR`.

## Rodar

```bash
export CPLEX_HOME=$HOME/IBM/CPLEX_Studio2211/cplex
./run.sh centralizado        # na raiz: output/market/
./run.sh figuras             # output/market/figuras/
```

O solver é o IBM CPLEX: o modelo do prosumidor é inteiro-misto, e os do
concentrador e do DSO são quadráticos. A licença acadêmica é pessoal, então ele
não entra em imagem nem no repositório. Outro solver pode ser apontado com
`MARKET_SOLVER` e `MARKET_SOLVER_PATH`, desde que resolva MIQP.

A formulação completa, a análise por fase e os desvios em relação à referência
estão em [docs/explanation/market-model.md](../../docs/explanation/market-model.md).
