# co-simulation-opentes

**Plataforma de co-simulação multidomínio do OpenTES, aplicada a um mercado transativo por fase sobre a IEEE 13 barras**

co-simulation-opentes reúne num só ambiente os simuladores das equipes do
projeto [OpenTES](https://github.com/grei-ufc/general-opentes): os agentes do
[PADE](https://github.com/grei-ufc/pade), a rede de comunicação no
[OMNeT++](https://omnetpp.org/), a rede elétrica no
[OpenDSS](https://www.epri.com/pages/sa/opendss) (via
[py-dss-interface](https://github.com/PauloRadatz/py_dss_interface)) e o
orquestrador [mosaik](https://mosaik.readthedocs.io/), cada um no seu contêiner.

O caso de aplicação é um mercado transativo. Prosumidores com baterias negociam
a programação do dia seguinte com o operador da rede, e um **preço sombra por
fase** coordena os dois lados para que a tensão de cada fase fique entre 0,97 e
1,03 pu. O mecanismo vem da tese de Lucas S. Melo (UFC, 2022), formulada para uma
rede equilibrada; aqui ele é levado à IEEE 13, que é desequilibrada, e a análise
passa a ser por fase.

## O que o projeto permite

- Rodar a negociação do mercado entre agentes PADE que trocam mensagens FIPA-ACL
- Passar cada mensagem por um modelo de rede: entrega ideal, perda sorteada,
  6TiSCH ou Wi-SUN FAN no OMNeT++
- Conferir a programação negociada no fluxo de potência completo do OpenDSS, a
  cada 15 minutos, com a demanda realizada
- Comparar a análise por barra (a da tese) com a análise por fase, e o inversor
  de quatro fios com o de três
- Rodar a mesma negociação sem agentes nem mosaik, para separar o risco numérico
  do risco de comunicação
- Gerar as figuras de tensão, preço sombra, negociação, mercados e comunicação
- Operar tudo por um console interativo ou por comandos (`opentes market`)

## Números do caso

| Medida | Por barra | Por fase |
|---|---:|---:|
| Leituras de fase acima de 1,03 pu na co-simulação | 134 | 9 |
| Leituras fora da ANSI C84.1 faixa A | 3 | 0 |
| Rodadas até o acordo | 48 | 42 |

O circuito IEEE 13 do repositório reproduz o perfil de tensão publicado com erro
médio de 0,00044 pu. Os detalhes estão em [Resultados](results.md).

## Início rápido

```bash
git clone https://github.com/grei-ufc/co-simulation-opentes
cd co-simulation-opentes
docker compose build
export CPLEX_HOME=$HOME/IBM/CPLEX_Studio2211/cplex
./run.sh                  # console interativo
```

Consulte [Instalação](getting-started/installation.md) para os requisitos e
[Primeira Simulação](getting-started/first-simulation.md) para o fluxo completo.
O console está em [Usando o console](tutorials/console.md).

## Quem fez

Trabalho do time **TTESO** do OpenTES, no
[GREI](https://github.com/grei-ufc) (Grupo de Redes Elétricas Inteligentes da
Universidade Federal do Ceará), sobre componentes das equipes do projeto:

| Equipe | Contribuição | Onde está |
|---|---|---|
| TSCC | rede de comunicação e a ponte com o mosaik | `simulators/comm-opentes`, `simulators/mosaik-opentes` |
| TSRE | rede elétrica, sistemas fotovoltaicos e o simulador OpenDSS | `simulators/grid-opentes` |
| TTESO | agentes, otimização, mercado transativo e a integração | `simulators/pade-opentes`, `simulators/market-opentes` |

O mercado e os agentes também têm repositórios próprios, que rodam sem os outros
simuladores: [tteso-market-opentes](https://grei-ufc.github.io/tteso-market-opentes/)
e [tteso-agents-opentes](https://grei-ufc.github.io/tteso-agents-opentes/).

## Licença

MIT License, Smart Grids Research Group - UFC (Universidade Federal do Ceará), 2025
