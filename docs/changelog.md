# Changelog

As mudanças entram no `main` por pull request. A lista abaixo resume cada um,
do mais recente ao mais antigo.

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
