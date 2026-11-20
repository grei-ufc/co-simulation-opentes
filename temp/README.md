# temp/: o que ainda não tem time dono

Esta pasta é provisória. Ela guarda o que a co-simulação precisa hoje e que
ainda não está no repositório de nenhum time. O código dos times entra por
submódulo em `teams/`, que faz o papel da antiga `simulators/`. A meta é que
`temp/` fique vazia até o fim do projeto (dezembro de 2026) e seja apagada.

Cada item sai daqui quando o time que deve absorvê-lo publicar o equivalente na
branch `integration-<time>`. O destino abaixo é uma proposta, a confirmar com
cada time.

| Pasta | O que tem | Destino proposto | Por quê |
|---|---|---|---|
| `grid-opentes/Dockerfile` | imagem do OpenDSS | TSRE (`tsre-der-opentes`) | o adaptador que ela roda já é do TSRE |
| `grid-opentes/src/data/13Bus/` | o caso IEEE 13 de mercado: circuito, perfis, armazenamento, preço, cenários, posições dos agentes | TTESO (`tteso-market-opentes`) | são entradas do mercado; o circuito oficial já existe em `tsre-der-opentes/data/13Bus/` |
| `grid-opentes/src/simulators/gen_ieee13_market.py` | gerador do caso a partir do circuito oficial | TTESO (`tteso-market-opentes`) | decide alocação de armazenamento, portas e perfis do mercado |
| `grid-opentes/src/simulators/sensitivity.py` | matrizes dV/dP e dV/dQ | TTESO, ou TSRE se ele quiser o utilitário (item T10 da análise do adaptador) | quem consome é o DSO do mercado |
| `grid-opentes/src/simulators/pv_creator.py`, `pv_validator.py` | gerador dos cinco PV fixos | TSRE | reescrita do `util/pv_creator.py` do TSRE, que hoje não importa (item T5) |
| `pade-opentes/Dockerfile` | imagem dos agentes (PADE 3.0, Pyomo, OpenDSS) | TTESO (`tteso-agents-opentes`) | instala o que os agentes do TTESO declaram |
| `mosaik-opentes/scenarios/market.py` | o cenário do mercado no Mosaik | TTESO (`tteso-agents-opentes`), ou TSCC se o time assumir a orquestração | liga os agentes do mercado ao circuito |
| `mosaik-opentes/collectors/elec_collector.py` | coletor das tensões e potências | TSRE (coletor próprio, que mantém `NaN` na fase ausente) | a convenção de saída é do adaptador do TSRE |
| `mosaik-opentes/Dockerfile` | imagem do Mosaik | quem ficar com o cenário | |
| `comm-opentes/` | rede 6TiSCH e Wi-SUN FAN no OMNeT++ (`Tisch.cc`) | TSCC (`tscc-com-opentes`) | é a rede LPWA de Melo (2022); a proposta de integração está na análise do TSCC |

O que fica permanentemente na raiz do repositório é só a integração: `run.sh`,
`cli/`, `docker-compose.yaml`, `.gitmodules`, `pyproject.toml`, `docs/` e
`mkdocs.yml`.
