# API (gerada)

Estas páginas são geradas a partir das docstrings do código pelo
[mkdocstrings](https://mkdocstrings.github.io/), a cada build da documentação.
Elas cobrem os módulos Python que definem o comportamento da plataforma:

| Página | Pasta | Módulos |
|---|---|---|
| [Mercado](market.md) | `teams/tteso-market-opentes/` (submódulo) | `config`, `optimization`, `dual`, `operation`, `scenarios`, `settlement` |
| [Rede elétrica](grid.md) | `teams/tsre-der-opentes/src/` | `gen_ieee13_market`, `sensitivity` |
| [Agentes](agents.md) | `teams/tteso-agents-opentes/agentes/` (submódulo) | `market_agents`, `network_link` |

O servidor de rede (`Tisch.cc`) é C++ e fica fora desta referência; os
parâmetros dele estão documentados no `Tisch.ned`. O adaptador OpenDSS é do TSRE
e tem a referência publicada pelo próprio time (ver [Rede elétrica](grid.md)). O PADE tem documentação
própria em [grei-ufc/pade](https://github.com/grei-ufc/pade).

Os comentários do código citam as equações da tese de referência pelo número,
como (6.25), e a formulação completa está em
[O modelo de mercado](../../explanation/market-model.md).
