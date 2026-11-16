"""Ponto de entrada do simulador OpenDSS para o Mosaik (o CMD do contêiner `grid`).

A implementação está no pacote `opendss/`, cópia sem alteração do adaptador da
equipe TSRE (`tsre-der-opentes`, `src/simulators/opendss/`); este módulo só a
expõe e inicia o servidor:
`python -m simulators.opendss_simulator --remote 0.0.0.0:5671`.
"""

from importlib import import_module

import mosaik_api_v3


_module = import_module("simulators.opendss.api_opendss")

OpenDSSSimulator = _module.OpenDSSSimulator
OpenDSS = getattr(_module, "OpenDSS", None)
OpenDSSException = getattr(_module, "OpenDSSException", None)


if __name__ == "__main__":
	mosaik_api_v3.start_simulation(OpenDSSSimulator())
