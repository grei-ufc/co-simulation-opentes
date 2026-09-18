import mosaik_api_v3
import numpy as np

from typing import List

# PV Panel Model

class PVPanelModel:
    """
    Emulates the physical and electrical behavior of a photovoltaic panel.

    The model is independent from simulation frameworks and computes the
    available DC power from irradiance and module temperature.

    Parameters
    ----------
    p_mpp : float
        Maximum power point power in kilowatts.
    irradiance_base : float
        Reference irradiance used for normalization in kW/m².
    pt_curve_x : list of float
        Temperatures in degrees Celsius that define the power-temperature curve.
    pt_curve_y : list of float
        Dimensionless power factors corresponding to pt_curve_x.

    Attributes
    ----------
    irradiance : float
        Current irradiance applied to the panel (0..1).
    temperature : float
        Current module temperature in degrees Celsius.
    P_dc : float
        Calculated DC power in kilowatts (non-negative).

    Notes
    -----
    The calculation uses the relation:
    P_dc = p_mpp * irradiance_base * irradiance * pt_factor
    where pt_factor is interpolated from pt_curve_x and pt_curve_y.
    See repository documentation for modeling details and validation.
    """
    def __init__(self,
                 p_mpp: float,
                 irradiance_base: float,
                 pt_curve_x: List[float],
                 pt_curve_y: List[float]
                 ) -> None:

        # Parâmetros construtivos
        self.p_mpp = p_mpp
        self.irradiance_base = irradiance_base
        self.pt_curve_x = pt_curve_x
        self.pt_curve_y = pt_curve_y
        
        # Variáveis de Estado (Inputs e Outputs)
        self.irradiance = 0.0
        self.temperature = 25.0
        self.P_dc = 0.0 

    def calculate_step(self) -> None:
        """
        Update P_dc based on the current irradiance and temperature.
        """
        # Apply P-TCurve
        pt_factor = np.interp(self.temperature, self.pt_curve_x, self.pt_curve_y)
        
        p_dc_calc = self.p_mpp * self.irradiance_base * self.irradiance * pt_factor
        self.P_dc = max(0.0, p_dc_calc)

# Simulator API

META = {
    'api_version': '3.0',
    'type': 'time-based',
    'models': {
        'PVPanel': {
            'public': True,
            'params': [
                'P_mpp',           
                'irradiance_base', 
                'pt_curve_x',     
                'pt_curve_y'
            ],
            # CORREÇÃO: I_dc removido da lista de atributos
            'attrs': ['irradiance', 'temperature', 'P_dc'],
        },
    },
}

class PVPanelSim(mosaik_api_v3.Simulator):
    """
    Mosaik simulator wrapper for PVPanelModel instances.

    This class manages multiple `PVPanelModel` objects and exposes them to a
    Mosaik co-simulation. It translates Mosaik inputs into model state,
    triggers the physical calculation, and returns model attributes as outputs.

    Parameters
    ----------
    None

    Attributes
    ----------
    entities : dict
        Mapping from entity id (str) to `PVPanelModel` instance.
    step_size : int
        Simulation step size in seconds used by the `step` method.

    Notes
    -----
    - The simulator expects a `META` dictionary to be available in the module.
    - `PVPanelModel` must be importable and follow the documented API:
      it should expose `irradiance`, `temperature`, `P_dc`, and a `calculate_step()` method.
    """
    def __init__(self) -> None:
        super().__init__(META)
        self.entities = {} # Aqui guardaremos instâncias de PVPanelModel
        self.step_size = 1

    def init(self, sid, time_resolution=1.0, step_size=1.0):
        """
        Initialize the simulator instance called by Mosaik.

        Parameters
        ----------
        sid : str
            Simulator id assigned by Mosaik.
        time_resolution : float, optional
            Time resolution requested by the orchestrator (unused here).
        step_size : float, optional
            Default step size in seconds for the simulation.

        Returns
        -------
        dict
            The simulator META information returned to Mosaik.
        """
        self.step_size = int(step_size)
        return self.meta

    def create(self, num, model, **model_params):
        entities = []
        for i in range(num):
            eid = f'{model}_{len(self.entities) + i}'
            
            panel_model = PVPanelModel(
                p_mpp=model_params.get('P_mpp', 1000.0),
                irradiance_base=model_params.get('irradiance_base', 1.0),
                pt_curve_x=model_params.get('pt_curve_x', [0, 25, 75, 100]),
                pt_curve_y=model_params.get('pt_curve_y', [1.15, 1.0, 0.8, 0.6]),
            )
            
            self.entities[eid] = panel_model
            entities.append({'eid': eid, 'type': model})
            
        return entities

    def step(self, time, inputs, max_advance):
        # 1. Update Inputs
        for eid, attrs in inputs.items():
            panel = self.entities[eid]
            
            if 'irradiance' in attrs:
                panel.irradiance = float(list(attrs['irradiance'].values())[0])
            if 'temperature' in attrs:
                panel.temperature = float(list(attrs['temperature'].values())[0])

        # 2. Run physics for all panels
        for eid, panel in self.entities.items():
            panel.calculate_step()
        
        return time + self.step_size

    def get_data(self, outputs):
        data = {}
        for eid, attrs in outputs.items():
            panel = self.entities[eid]
            data[eid] = {}
            for attr in attrs:
                if hasattr(panel, attr):
                    data[eid][attr] = getattr(panel, attr)
        return data

if __name__ == '__main__':
    mosaik_api_v3.start_simulation(PVPanelSim())