"""Compatibility wrapper for the OpenDSS simulator module.

This keeps older scenario files working even though the implementation lives
in `1_api_opendss.py`.
"""

from importlib import import_module

import mosaik_api_v3


_module = import_module("simulators.api_opendss")

OpenDSSSimulator = _module.OpenDSSSimulator
OpenDSS = getattr(_module, "OpenDSS", None)
OpenDSSException = getattr(_module, "OpenDSSException", None)


if __name__ == "__main__":
	mosaik_api_v3.start_simulation(OpenDSSSimulator())
