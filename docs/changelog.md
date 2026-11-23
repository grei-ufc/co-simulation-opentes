# Changelog

As mudanças entram no `main` por pull request. A lista abaixo resume cada um,
do mais recente ao mais antigo.

## Código dos times por submódulo git

- O código de cada time entra por submódulo em `teams/`, que segue a branch
  `integration-<time>` do repositório do time (`.gitmodules`): `tsre-der-opentes`,
  `tteso-market-opentes`, `tteso-agents-opentes` e `tscc-com-opentes`. Enquanto
  a branch não existe, o submódulo fica no commit do `main` do time.
- Saem as cópias: `simulators/market-opentes/`, `simulators/pade-opentes/pade/`
  e `agents/`, e `simulators/grid-opentes/src/simulators/opendss/` com o
  `opendss_simulator.py`. A pasta `simulators/` deixa de existir: `teams/` faz o
  papel dela, e `grid-opentes/`, `pade-opentes/`, `mosaik-opentes/` e
  `comm-opentes/` (as imagens e a cola da integração) vão para `temp/`, pasta
  provisória que se esvazia à medida que cada time absorve a sua parte
  (`temp/README.md`). O contêiner `grid` roda o adaptador do TSRE direto
  (`python -m simulators.opendss.api_opendss`), e a imagem `pade` instala o
  `pade-agents==3.0` do PyPI.
- A rede elétrica passa para `teams/tsre-der-opentes`, na branch
  `integration-tsre`, reduzida ao que o caso usa: o adaptador do OpenDSS, o
  coletor do TSRE, o caso IEEE 13 e as ferramentas que o geram. Os contêineres
  `grid` e `collector` deixam de usar `temp/grid-opentes` e o coletor antigo.
- O coletor do TSRE grava `NaN` na fase que a barra não tem, no lugar de `0.0`:
  a ARGOS do TSDQ lê `0.0` como tensão crítica.
- Novo comando `opentes submodulos [atualizar]`, e o `run.sh` passa a esperar o
  `grid` ficar pronto, pelo log, antes de subir o Mosaik.
- Página nova: [Organização dos repositórios](explanation/repositories.md).
- Resultados conferidos contra o `main` e contra a referência de 21/10/2026:
  por fase e por barra, mesmas rodadas (42 e 48) e potências, tensões com
  diferença máxima de 2e-9 pu; `neutro` idêntico; saídas do `centralizado`
  idênticas.

## Adaptador do OpenDSS atualizado para o do TSRE

- O adaptador do OpenDSS (`simulators/grid-opentes/src/simulators/opendss/`)
  passa a ser a cópia sem alteração do `tsre-der-opentes` no commit `b086ea8`
  (10/11/2026), no lugar da cópia de maio de 2026 (`api_opendss.py` e
  `opendss_wrapper.py`).
- Resultados conferidos contra a versão anterior nos modos por fase, por barra
  e `MARKET_REGULADOR=neutro`: mesmas rodadas e potências, e tensões com
  diferença máxima de 8e-9 pu.
- O coletor mantém `0.0` na fase que a barra não tem, e o modo `neutro` passa a
  enviar a derivação 0 de forma explícita.

## Documentação no padrão do OpenTES

- Site reorganizado no modelo do `tsre-der-opentes`: `mkdocs.yml` na raiz,
  seções de primeiros passos, tutoriais, guias, referência, conceitos e
  contribuição, e API gerada das docstrings.
- Publicação automática no GitHub Pages pelo workflow de CI.

## #10, 04/11/2026: mercado por fase

- Análise por fase no mercado da IEEE 13 (`MARKET_FASE=1`, o novo padrão), com
  inversor de quatro ou de três fios (`MARKET_DISPOSITIVO`).
- O regulador segue as derivações da previsão no cenário de mercado.
- Critério de parada relativo à potência de cada dispositivo, e partida dos
  agentes sem corrida.
- Console interativo no `./run.sh` e o comando `opentes`.
- Diagnóstico da 6TiSCH e retransmissão na verificação de operação.
- Wi-SUN FAN como alternativa à 6TiSCH (`TISCH_MAC=wisun`) e fatias por enlace
  configuráveis (`TISCH_CELLS`).
- Limpeza do repositório: só o mercado sobre a IEEE 13.

## #9, 01/10/2026: site de documentação

- A documentação reunida num site MkDocs, com os números desatualizados
  corrigidos.

## #8, 21/09/2026: IEEE 13 corrigida

- Temperatura dos PV, medidor do Volt/Var e redimensionamento do armazenamento.

## #7, 17/09/2026: mercado transativo

- O mercado transativo da tese de referência levado à plataforma: modelos de
  otimização, decomposição dual, agentes, liquidação e figuras no formato da
  tese.

## #5, 06/08/2026: execução unificada

- Execução unificada no `run.sh`, com o que não é da IEEE 13 removido.
- Os dois caminhos de instalação documentados: Docker e uv.

## #4, 26/06/2026: experimento de perda

- Varredura de perda de pacotes de 0 a 100% no controle Volt/Var, com várias
  sementes por nível.
- Correções no simulador da rede: congelamento do fluxo no controle dos PV e
  deslocamento das curvas de carga.

## #2 e #3, 12/06/2026: quatro contêineres

- A arquitetura dividida em contêineres por domínio, com o acoplamento causal
  OpenDSS, OMNeT++ e PADE fechado e o controle Volt/Var nos inversores PV.

## #1, 21/05/2026: integração inicial

- Primeira organização dos simuladores das equipes do OpenTES num repositório.
