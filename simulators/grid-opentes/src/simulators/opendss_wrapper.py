import py_dss_interface
import datetime as dt
import numpy as np
import pandas as pd
from typing import List, Union, Tuple, Dict, Any, Optional

LINE_CLASSES = ['Line', 'Xfmr', 'Capacitor']

class OpenDSSException(Exception):
    """Custom exception for OpenDSS interface related errors."""
    pass

class OpenDSS:
    """
    Wrapper class to manage the interface with OpenDSS (via py_dss_interface).

    It handles circuit compilation, time flow management, data extraction, 
    and element control (Loads, PVs, Storage, etc.).
    """ 
    name = 'DSS'

    def __init__(self, 
                 redirects: Union[str, List[str]], 
                 time_step: dt.timedelta, 
                 start_time: dt.datetime, 
                 fail_on_error: bool = True, 
                 **kwargs):
        """
        Initializes the OpenDSS instance.

        Args:
            redirects (Union[str, List[str]]): Path(s) to the master .dss file(s).
            time_step (dt.timedelta): The simulation time step.
            start_time (dt.datetime): The simulation start time (sets hour and angle).
            fail_on_error (bool, optional): If True, raises an exception on DSS errors. Defaults to True.
            **kwargs: Additional arguments (currently unused).
        """
        self.dss = py_dss_interface.DSS()
        self.fail_on_error = fail_on_error

        self.print('Compiling...')
        if not isinstance(redirects, list):
            redirects = [redirects]
        for redirect in redirects:
            self.dss.text(f'Redirect "{redirect}"')

        # Checks for the existence of specific elements to optimize data retrieval
        self.includes_elements = {
            'Load': len(self.dss.loads.names) > 0,
            'PVSystem': len(self.dss.pvsystems.names) > 0,
            'Generator': len(self.dss.generators.names) > 0,
        }
        
        # Specific logic to handle Storage elements
        self.dss.circuit.set_active_class("Storage")
        storages_names = self.dss.active_class.names
        
        if storages_names and storages_names[0] is not None:
            self.includes_elements['Storage'] = True
            self.storage_names = storages_names
        else:
            self.includes_elements['Storage'] = False
            self.storage_names = []

        self.dss.solution.mode = 0  # Snapshot mode (initialization)
        self.dss.solution.number = 1
        
        day_of_year = start_time.timetuple().tm_yday - 1
        self.dss.solution.hour = day_of_year * 24 + start_time.hour

        self.dss.solution.step_size = 0
        self.run_dss()
        self.dss.solution.step_size = time_step.total_seconds()

        self.print(f'Compiled Circuit: {self.dss.circuit.name}')

    def run_command(self, cmd: str) -> None:
        """
        Executes a direct text command in the OpenDSS engine.

        Args:
            cmd (str): The DSS command to execute.

        Raises:
            OpenDSSException: If the command returns an error and fail_on_error is True.
        """
        status = self.dss.text(cmd)
        if status and "error" in status.lower() and self.fail_on_error:
            self.fail(f'Status ({cmd}): {status}')
        if status:
             self.print(f'Status ({cmd}): {status}')

    def redirect(self, filename: str) -> None:
        """
        Compiles a specific .dss file.

        Args:
            filename (str): Path to the file.
        """
        self.print(f'Running file: {filename}')
        self.dss.text(f'compile "{filename}"')

    def run_dss(self, no_controls: bool = False) -> None:
        """
        Executes the OpenDSS solution command (Solve).

        Args:
            no_controls (bool, optional): If True, uses solve_no_control(). Defaults to False.
        """
        try:
            if no_controls:
                self.dss.solution.solve_no_control()
            else:
                self.dss.solution.solve()

            # Manually update storage state after solution
            if self.includes_elements.get('Storage', False):
                self.dss.text('UpdateStorage')

        except Exception as e:
            self.dss.text('export Eventlog')
            self.fail(f"An error occurred during DSS solution: {e}")

    def get_circuit_power(self) -> Tuple[float, float]:
        """
        Gets the total active and reactive power of the circuit.
        
        Note: This inverts the standard OpenDSS sign convention (where generation is positive)
        so that grid consumption is positive and injection into the grid is negative 
        (or vice versa, depending on reference, but signs are flipped from native output).

        Returns:
            Tuple[float, float]: (P_kW, Q_kvar).
        """
        p_kw, q_kvar = self.dss.circuit.total_power
        p_kw, q_kvar = -p_kw, -q_kvar
        
        if np.isnan(p_kw) or np.isnan(q_kvar):
            self.fail(f'NaN output for circuit power: ({p_kw}, {q_kvar})')
        return p_kw, q_kvar

    def get_losses(self) -> Tuple[float, float]:
        """
        Gets the total circuit losses.

        Returns:
            Tuple[float, float]: (P_kW, Q_kvar).
        """
        p_w, q_var = self.dss.circuit.losses
        return p_w / 1000.0, q_var / 1000.0

    def get_total_power(self, element: str = 'Load') -> Tuple[float, float]:
        """
        Calculates the aggregated power for a specific class of elements.

        Args:
            element (str): The class name (e.g., 'Load', 'PVSystem', 'Storage').

        Returns:
            Tuple[float, float]: Total (P_kW, Q_kvar).
        """
        p_total, q_total = 0.0, 0.0
        
        try:
            self.dss.circuit.set_active_class(element)
        except py_dss_interface.errors.DSSException:
             return 0.0, 0.0

        if self.dss.active_class.count == 0:
            return 0.0, 0.0
            
        idx = self.dss.active_class.first()
        while idx > 0:
            powers = self.dss.cktelement.powers
            p_total += sum(powers[0::2])
            q_total += sum(powers[1::2])
            idx = self.dss.active_class.next()
            
        # For Storage, we invert the sign to match injection/consumption conventions
        if element == 'Storage':
            return -p_total, -q_total
        
        return p_total, q_total

    def get_circuit_info(self) -> Dict[str, float]:
        """
        Runs a power flow and returns a summary dictionary of the system status.

        Returns:
            Dict[str, float]: Dictionary containing Total P/Q (MW/MVAR) and Losses.
        """
        self.run_dss()
        
        p_total_kw, q_total_kvar = self.get_circuit_power()
        p_loss_kw, q_loss_kvar = self.get_losses()
        total_by_class = {class_name: self.get_total_power(class_name) for class_name, included in
                          self.includes_elements.items() if included}

        out = {
            'Total P (MW)': p_total_kw / 1000,
            'Total Loss P (MW)': p_loss_kw / 1000,
        }
        for class_name, (p, q) in total_by_class.items():
            display_name = 'PV' if class_name == 'PVSystem' else class_name
            out[f'Total {display_name} P (MW)'] = p / 1000

        out.update({
            'Total Q (MVAR)': q_total_kvar / 1000,
            'Total Loss Q (MVAR)': q_loss_kvar / 1000,
        })
        for class_name, (p, q) in total_by_class.items():
            display_name = 'PV' if class_name == 'PVSystem' else class_name
            out[f'Total {display_name} Q (MVAR)'] = q / 1000
        return out

    def get_all_buses(self) -> List[str]:
        """Returns a list of all bus names in the circuit."""
        return self.dss.circuit.buses_names

    def get_all_elements(self, element: str = 'Load') -> pd.DataFrame:
        """
        Returns a DataFrame containing all properties for all elements of a specific class.

        Args:
            element (str): The element class (e.g., 'Load', 'Line').

        Returns:
            pd.DataFrame: DataFrame indexed by the full element name.
        """
        try:
            self.dss.circuit.set_active_class(element)
        except Exception:
            # Se a própria classe for inválida
            return pd.DataFrame()
        
        # CORREÇÃO DEFINITIVA: Checa se existem elementos antes de acessar os nomes
        if self.dss.active_class.count == 0:
            return pd.DataFrame()

        # Agora é seguro pedir os nomes
        names = self.dss.active_class.names

        # Dupla checagem de segurança
        if not names or names[0] is None or names[0].lower() == 'none':
            return pd.DataFrame()
        
        all_data = {}
        for name in names:
            full_name = f"{element}.{name}"
            self.dss.circuit.set_active_element(full_name)
            
            element_data = {}
            prop_names = self.dss.dsselement.property_names
            for i, prop_name in enumerate(prop_names, 1):
                element_data[prop_name] = self.dss.dssproperties.value_read(str(i))
            
            all_data[full_name] = element_data
            
        df = pd.DataFrame.from_dict(all_data, orient='index')
        return df
        
    def get_bus_voltage(self, bus: str, phase: Optional[int] = None, 
                        pu: bool = True, polar: bool = True, 
                        mag_only: bool = True, average: bool = False,
                        zero_voltage_error: bool = False) -> Union[float, Tuple, List[float]]:
        """
        Gets the voltage of a specific bus with flexible formatting options.

        Args:
            bus (str): The bus name.
            phase (int, optional): Specific phase (1, 2, 3). If None, returns all phases.
            pu (bool): If True, returns in per unit. Else, in real Volts/kV.
            polar (bool): If True, returns (Mag, Ang). Else, returns (Real, Imag).
            mag_only (bool): If True (and polar=True), returns only Magnitude.
            average (bool): If True, returns the average of phases (only if mag_only=True).
            zero_voltage_error (bool): If True, raises error if magnitude is ~0.

        Returns:
            Union[float, Tuple, List]: Voltage value(s) in the requested format.
        """
        self.dss.circuit.set_active_bus(bus)
        
        if polar:
            v = self.dss.bus.vmag_angle_pu if pu else self.dss.bus.vmag_angle
        else:
            v = self.dss.bus.pu_voltages if pu else self.dss.bus.voltages

        if not v or any(np.isnan(x) for x in v):
            self.fail(f'NaN or empty output for bus voltage: {bus}')
        
        n_phases = self.dss.bus.num_nodes
        nodes = self.dss.bus.nodes
        real_or_mag = tuple(v[0::2])
        imag_or_ang = tuple(v[1::2])

        real_or_mag = tuple(
            [real_or_mag[nodes.index(i+1)] if (i+1) in nodes else 0.0 for i in range(3)]
        )

        imag_or_ang = tuple(
            [imag_or_ang[nodes.index(i+1)] if (i+1) in nodes else 0.0 for i in range(3)]
        )

        if polar and zero_voltage_error and any([mag <= 1e-10 for mag in real_or_mag]):
            self.fail(f'Bus "{bus}" voltage is out of bounds: {real_or_mag}')

        # if n_phases == 1:
        #     return real_or_mag[0] if (polar and mag_only) else (real_or_mag[0], imag_or_ang[0])
        elif phase is None:
            if polar and mag_only and average:
                return sum(real_or_mag) / len(real_or_mag)
            elif polar and mag_only:
                return real_or_mag
            else:
                return real_or_mag, imag_or_ang
        elif phase - 1 in range(n_phases):
             if polar and mag_only:
                return real_or_mag[phase - 1]
             else:
                return real_or_mag[phase - 1], imag_or_ang[phase - 1]
        else:
            raise OpenDSSException(f'Bad phase for {n_phases}-phase Bus {bus}: {phase}')

    def set_element(self, name: str, element: str) -> None:
        """
        Sets the active element in the DSS circuit.

        Args:
            name (str): Element name (e.g., 'load1').
            element (str): Element class (e.g., 'Load').
        """
        full_name = f"{element}.{name}"
        self.dss.circuit.set_active_element(full_name)
        if self.dss.cktelement.name.lower() != full_name.lower():
             raise OpenDSSException(f'{element} "{name}" does not exist')
    
    def get_voltage(self, name: str, element: str = 'Load', line_bus: int = 1, **kwargs) -> Union[float, Tuple, Any]:
        """
        Gets the voltage at the terminals of a specific element.
        
        Args:
            name (str): Element name.
            element (str): Element class.
            line_bus (int): For lines/transformers, which bus to monitor (1 or 2).
            **kwargs: Passed to get_bus_voltage.
        """
        self.set_element(name, element)
        buses = self.dss.cktelement.bus_names
        # Selects the correct bus if it's a line element, otherwise picks the first one
        bus = buses[line_bus - 1 if element in LINE_CLASSES else 0]
        if self.dss.cktelement.num_phases == 1:
            kwargs['phase'] = 1
        return self.get_bus_voltage(bus, **kwargs)

    def get_all_bus_voltages(self, **kwargs) -> Dict[str, Union[float, Tuple]]:
        """
        Gets voltages for all buses in the system.

        Args:
            **kwargs: Passed to get_bus_voltage.

        Returns:
            Dict: Keys are bus names (or bus.phase), values are voltages.
        """
        buses = self.get_all_buses()
        data = {}
        for bus in buses:
            v = self.get_bus_voltage(bus, **kwargs)
            if isinstance(v, tuple) and v and not isinstance(v[0], tuple):
                # If tuple of phases is returned, expand to individual keys
                data.update({bus + '.' + str(i + 1): v_ph for i, v_ph in enumerate(v)})
            else:
                data[bus] = v
        return data

    def get_power(self, name: str, element: str = 'Load', 
                  phase: Optional[int] = None, total: bool = False, 
                  line_bus: int = 1, raw: bool = False) -> Tuple:
        """
        Gets the power (P, Q) of a specific element.

        Args:
            name (str): Element name.
            element (str): Element class.
            phase (int, optional): Specific phase.
            total (bool): If True, sums all phases.
            line_bus (int): Terminal for line elements (1 or 2).
            raw (bool): If True, returns raw DSS output tuple.

        Returns:
            Tuple: (P, Q) or tuple of tuples depending on arguments.
        """
        self.set_element(name, element)
        powers = self.dss.cktelement.powers 
        
        if raw:
            return tuple(powers)

        n_phases = self.dss.cktelement.num_phases
        if element in LINE_CLASSES:
            start_idx = (line_bus - 1) * 2 * n_phases
            end_idx = start_idx + 2 * n_phases
            powers = powers[start_idx:end_idx]
        else:
            powers = powers[:2 * n_phases]

        p_vals = powers[0::2]
        q_vals = powers[1::2]

        if n_phases == 1:
            return (p_vals[0], q_vals[0]) if p_vals else (0,0)
        elif n_phases in [2, 3]:
            if phase is None:
                if total:
                    return sum(p_vals), sum(q_vals)
                else:
                    return tuple(p_vals), tuple(q_vals)
            if phase - 1 in range(n_phases):
                return p_vals[phase-1], q_vals[phase-1]
            else:
                raise OpenDSSException(f'Unknown phase for {element} {name}: {phase}')
        else:
            raise OpenDSSException(f'Cannot parse powers for {element} {name}, num phases={n_phases}')
            
    def set_power(self, name: str, p: float = None, q: float = None, 
                  element: str = 'Load', size: float = None) -> None:
        """
        Sets the active and reactive power of an element.

        For 'Storage': Automatically calculates state (Charging/Discharging) and 
        Power Factor based on the sign of 'p'.

        Args:
            name (str): Element name.
            p (float): Active Power (kW).
            q (float): Reactive Power (kvar).
            element (str): Class ('Load', 'PV', 'Storage').
            size (float): Rated power (only for Storage).
        """
        element_class = 'PVSystem' if element == 'PV' else element
        if element_class != 'Storage':
            cmd = f"edit {element_class}.{name}"
            if p is not None:
                cmd += f" kW={p}"
            if q is not None:
                cmd += f" kvar={q}"
            self.run_command(cmd)
        else:
            # Specific logic for Storage
            if p is None: return
            if q is None: q = 0.0

            if p > 0:
                state_str = "Discharging"
            elif p < 0:
                state_str = "Charging"
            else:
                state_str = "Idling"

            if state_str == "Idling":
                cmd = f"Edit Storage.{name} State={state_str}"
            else:
                cmd = f"Edit Storage.{name} State={state_str} kW={p} kvar={q}"

            self.run_command(cmd)

    def get_current(self, name: str, element: str = 'Load', 
                    polar: bool = True, mag_only: bool = True, 
                    line_bus: int = 1, phase: Optional[int] = None, 
                    total: bool = False, raw: bool = False,
                    winding: int = 1) -> Union[float, Tuple]:
        """
        Gets the current of an element.

        Args:
            name (str): Element name.
            element (str): Class.
            polar (bool): Return in polar format (Mag, Ang).
            mag_only (bool): Return only magnitude (if polar=True).
            line_bus (int): Terminal (1 or 2 for lines).
            phase (int): Specific phase.
            total (bool): Sum magnitudes (if polar=True and mag_only=True).
            raw (bool): Return raw DSS tuple.

        Returns:
            Union[float, Tuple]: Current value or tuple of values.
        """
        self.set_element(name, element)
        if polar:
            currents = self.dss.cktelement.currents_mag_ang
        else:
            currents = self.dss.cktelement.currents
        if raw:
            return tuple(currents)

        n_phases = self.dss.cktelement.num_phases

        if element in LINE_CLASSES:
            start_idx = (line_bus - 1) * 2 * n_phases
            end_idx = start_idx + 2 * n_phases
            currents = currents[start_idx:end_idx]

        elif element.lower() == "transformer":
            start_idx = (winding - 1) * (2 * n_phases + 2)
            end_idx = start_idx + 2 * n_phases
            currents = currents[start_idx:end_idx]
        elif element.lower() == "storage":
            currents = currents[:-2]
        elif element.lower() == "pvsystem":
            currents = currents[:-2]
        else:
            currents = currents[:2 * n_phases]
            
        real_or_mag = tuple(currents[0::2])
        imag_or_ang = tuple(currents[1::2])

        if n_phases == 1:
            if not real_or_mag: return 0 if mag_only else (0,0)
            return real_or_mag[0] if mag_only and polar else (real_or_mag[0], imag_or_ang[0])
        elif n_phases in [2, 3]:
            if phase is None:
                if polar and mag_only:
                    return sum(real_or_mag) if total else real_or_mag
                else:
                    return real_or_mag, imag_or_ang
            if phase - 1 in range(n_phases):
                return real_or_mag[phase - 1], imag_or_ang[phase - 1]
            else:
                raise OpenDSSException(f'Unknown phase for {element} {name}: {phase}')
        else:
            raise OpenDSSException(f'Cannot parse currents for {element} {name}, num phases={n_phases}')

    def get_all_complex(self, name: str, element: str = 'Load') -> Dict[str, Tuple]:
        """Returns a dictionary with all complex quantities (V, I, S) for the element."""
        self.set_element(name, element)
        return {
            'Voltages': self.dss.cktelement.voltages,
            'VoltagesMagAng': self.dss.cktelement.voltages_mag_ang,
            'Currents': self.dss.cktelement.currents,
            'CurrentsMagAng': self.dss.cktelement.currents_mag_ang,
            'Powers': self.dss.cktelement.powers,
        }

    def get_all_properties(self, name: str, element: str = 'Load') -> List[str]:
        """Returns a list of property names available for the element."""
        self.set_element(name, element)
        return self.dss.dsselement.property_names

    def get_property(self, name: str, property_name: str, element: str = 'Load') -> Union[float, str]:
        """Reads the value of a specific property of an element."""
        all_properties = self.get_all_properties(name, element)
        if property_name.lower() not in [p.lower() for p in all_properties]:
            raise OpenDSSException(f'Could not find {property_name} property for {element} "{name}"')

        idx = [p.lower() for p in all_properties].index(property_name.lower()) + 1
        value = self.dss.dssproperties.value_read(str(idx))

        try:
            return float(value)
        except (ValueError, TypeError):
            return value

    def set_property(self, name: str, property_name: str, value: Any, element: str = 'Load') -> None:
        """Sets the value of an element's property and verifies if it was applied."""
        full_element_name = f"{element}.{name}"
        cmd = f"edit {full_element_name} {property_name}={value}"
        self.run_command(cmd)

        new_value = self.get_property(name, property_name, element)
        assert str(new_value) == str(value)

    def remove_loadshape(self, name: str, element: str = 'Load') -> None:
        """Removes the associated loadshape, setting the mode to constant."""
        self.set_property(name, 'yearly', 'constant', element)

    def set_is_open(self, name: str, open: bool = True, element: str = 'Load', term: int = 1) -> None:
        """Opens or closes the terminal of an element."""
        action = "Open" if open else "Close"
        full_name = f"{element}.{name}"
        self.run_command(f"{action} {full_name} term={term}")

    def get_is_open(self, name: str, element: str = 'Load', term: int = 1) -> bool:
        """Checks if the element terminal is open."""
        self.set_element(name, element)
        return bool(self.dss.cktelement.is_terminal_open(term))

    def set_tap(self, name: str, tap: int, max_tap: int = 16) -> None:
        """Sets the tap of a RegControl, clamping it to the max value."""
        # self.set_element(name, 'RegControl')
        self.dss.regcontrols.name = name
        tap = int(min(max(tap, -max_tap), max_tap))
        self.dss.regcontrols.tap_number = tap

    def get_tap(self, name: str) -> int:
        """Gets the current tap of a RegControl."""
        # self.set_element(name, 'RegControl')
        self.dss.regcontrols.name = name
        return self.dss.regcontrols.tap_number

    def set_pt_ratio(self, name: str, pt_ratio: float) -> None:
        """Sets the Potential Transformer (PT) Ratio of a CapControl."""
        self.set_element(name, 'CapControl')
        self.dss.capcontrols.pt_ratio = pt_ratio

    def get_pt_ratio(self, name: str) -> float:
        """Gets the PT Ratio of a CapControl."""
        self.set_element(name, 'CapControl')
        return self.dss.capcontrols.pt_ratio

    def print(self, *msg: Any) -> None:
        """Prints a message with timestamp and class name."""
        print(f'{dt.datetime.now()} - {self.name}:', *msg)

    def fail(self, *msg: Any) -> None:
        """Raises an exception or prints an error depending on fail_on_error configuration."""
        if self.fail_on_error:
            raise OpenDSSException(*msg)
        else:
            self.print(*msg)

    def get_all_regulators_info(self):
        """
        Return a list of dicts with all static data about the regulators.
        Detects the topology (Transformer, Winding, Bus, Phase)
        
        :param self: Description
        """
        reg_list = []
        try:
            names = self.dss.regcontrols.names
            for name in names:
                self.dss.regcontrols.name = name

                self.dss.regcontrols.max_tap_change = 0
                self.dss.regcontrols.tap_number = 0

                info = {
                    'name': name,
                    'vreg': self.dss.regcontrols.forward_vreg,
                    'band': self.dss.regcontrols.forward_band,
                    'pt_ratio': self.dss.regcontrols.pt_ratio,
                    'ct_primary': self.dss.regcontrols.ct_primary,
                    'R': self.dss.regcontrols.forward_r,
                    'X': self.dss.regcontrols.forward_x,
                    'delay': self.dss.regcontrols.delay,
                    'tap_delay': self.dss.regcontrols.tap_delay, # ou tap_delay se existir na versão
                    'trafo': self.dss.regcontrols.transformer,
                    'winding': self.dss.regcontrols.winding,
                    'tap_ini': 0
                }

                self.set_element(name=info['trafo'], element='Transformer')

                full_bus_name = self.dss.cktelement.bus_names[info['winding'] - 1]

                if '.' in full_bus_name:
                    parts = full_bus_name.split('.')
                    info['target_bus'] = parts[0]
                    try: info['target_phase'] = int(parts[1])
                    except: info['target_phase'] = 1

                else:
                    info['target_bus'] = full_bus_name
                    info['target_phase'] = 1

                reg_list.append(info)

        except Exception as e:
            print(f"[WRAPPER] Erro ao ler reguladores: {e}")

        return reg_list

    def get_regulator_measurements(self, reg_info):
        res = {'v': 0j, 'i': 0j, 'tap': 0}

        try:
            self.dss.regcontrols.name = reg_info['name']
            res['tap'] = self.dss.regcontrols.tap_number

            v_r, v_i = self.get_bus_voltage(
                bus=reg_info['target_bus'],
                phase=reg_info['target_phase'],
                pu=False, mag_only=False, polar=False 
            )

            res['v'] = complex(v_r, v_i)

            i_r, i_i = self.get_current(
                name=reg_info['trafo'],
                element='Transformer',
                winding=1,
                phase=reg_info['target_phase'],
                mag_only=False,
                polar=False)

            res['i'] = complex(i_r, i_i)

        except Exception as e:
            pass

        return res

    # def set_pvsystem_pq(self, name: str, p_des: float, q_des: float):
    #     """
    #     Força valores de potência ativa e reativa em um PVSystem no OpenDSS.
    #     Desacopla o elemento das curvas de temperatura e irradiância para controle via co-simulação.
    #     """
    #     self.dss.circuit.set_active_element(f"PVSystem.{name}")
    #     p_abs = abs(p_des)
        
    #     if p_abs > 0.001:
    #         pmpp_req = p_abs
            
    #         # Cálculo do Fator de Potência Base
    #         s_apparent = np.sqrt(p_des**2 + q_des**2)
    #         pf_calc = p_des / s_apparent if s_apparent > 0 else 1.0
            
    #         # Correção do Sinal do PF (Convenção Real do OpenDSS)
    #         if q_des > 0:
    #             pf_calc = abs(pf_calc)   # Injeção de Q = PF Positivo
    #         else:
    #             pf_calc = -abs(pf_calc)  # Absorção de Q = PF Negativo
                
    #         cmd = f"Edit PVSystem.{name} pmpp={pmpp_req} irradiance=1.0 pf={pf_calc}"
    #         self.dss.text(cmd)
            
    #     elif abs(q_des) > 0.001:
    #         # STATCOM puro (Noite / Sem Ativa)
    #         cmd = f"Edit PVSystem.{name} irradiance=0.0 kvar={q_des}"
    #         self.dss.text(cmd)
            
    #     else:
    #         # Desligado ou Ocioso
    #         cmd = f"Edit PVSystem.{name} irradiance=0.0 pf=1.0"
    #         self.dss.text(cmd)

    def set_pvsystem_pq(self, name: str, p_des: float, q_des: float):
        """
        Força valores de potência ativa e reativa em um PVSystem no OpenDSS.
        Desacopla o elemento das curvas de temperatura e irradiância para controle via co-simulação.

        IMPORTANTE — correção do congelamento do solve:
        Em modo snapshot, o OpenDSS REAPROVEITA a tensão do passo anterior quando o
        `Edit PVSystem` repete EXATAMENTE os mesmos valores (um "no-op"): a rede
        deixa de responder à variação de carga e "congela". Isso acontecia
        principalmente na madrugada (P=0 e Q estável → comando constante todo
        passo), e mascarava o efeito do controle. Tentativas de forçar o re-solve
        (rebuild Y, mode=snap, solve_direct, solve duplo) NÃO resolvem.
        Solução: aplicar um DITHER desprezível no reativo (±0,001 kvar = ±1 var),
        alternando a cada passo, de modo que o `Edit` nunca seja idêntico ao
        anterior e o solve sempre re-resolva. O efeito físico é nulo (1 var vs.
        dezenas/centenas de kvar de controle).
        """
        if not hasattr(self, "_pv_dither"):
            self._pv_dither = {}
        self._pv_dither[name] = -self._pv_dither.get(name, 0.001)   # alterna ±0,001
        q_eff = q_des + self._pv_dither[name]

        self.dss.circuit.set_active_element(f"PVSystem.{name}")
        p_abs = abs(p_des)

        if p_abs > 0.001:
            self.dss.text(f"Edit PVSystem.{name} pmpp={p_abs} irradiance=1.0 kvar={q_eff}")
        else:
            # Desligado ou ocioso (noite): P≈0, controla só o reativo (STATCOM)
            self.dss.text(f"Edit PVSystem.{name} irradiance=0.0 kvar={q_eff}")

    def get_pvsystem_power(self, name: str):
        """
        Coleta a potência ativa e reativa medida nos terminais do PVSystem.
        Retorna: (P_kW, Q_kvar)
        """
        self.dss.circuit.set_active_element(f"PVSystem.{name}")
        powers = self.dss.cktelement.powers
        # OpenDSS retorna powers no formato [P1, Q1, P2, Q2, P3, Q3...]
        # Multiplicamos por -1 pois a convenção de injeção de geração no OpenDSS é negativa
        p_meas = -sum(powers[0:6:2])
        q_meas = -sum(powers[1:6:2])
        return p_meas, q_meas
    
    def get_all_pvsystems_info(self):
        """
        Retorna um dicionário com todos os dados estáticos e curvas dos PVSystems.
        Lê automaticamente as XYCurves atreladas a cada inversor.
        """
        pv_infos = {}
        names = self.dss.pvsystems.names
        
        if not names or names[0].upper() == 'NONE':
            return pv_infos

        for name in names:
            self.dss.pvsystems.name = name
            
            # 1. Parâmetros Básicos
            pmpp = self.dss.pvsystems.pmpp
            kva = self.dss.pvsystems.kva
            irradiance = self.dss.pvsystems.irradiance
            daily = self.dss.text(f"? PVSystem.{name}.daily")
            
            # Lendo propriedades via texto (pois nem todas têm interface nativa direta no py_dss_interface)
            cutin = float(self.dss.text(f"? PVSystem.{name}.%cutin"))
            cutout = float(self.dss.text(f"? PVSystem.{name}.%cutout"))

            bus_name = self.dss.cktelement.bus_names[0]
            
            # 2. Descobrir os Nomes das Curvas
            pt_curve_name = self.dss.text(f"? PVSystem.{name}.P-TCurve")
            eff_curve_name = self.dss.text(f"? PVSystem.{name}.EffCurve")
            
            # 3. Função Auxiliar para buscar os arrays X e Y de uma XYCurve
            def get_xy_curve(curve_name):
                if not curve_name: return [], []
                self.dss.xycurves.name = curve_name
                x = list(self.dss.xycurves.x_array)
                y = list(self.dss.xycurves.y_array)
                return x, y

            pt_x, pt_y = get_xy_curve(pt_curve_name)
            eff_x, eff_y = get_xy_curve(eff_curve_name)
            
            pv_infos[name] = {
                'pmpp': pmpp,
                'kva': kva,
                'irradiance': irradiance,
                'daily': daily,
                'pct_cutin': cutin,
                'pct_cutout': cutout,
                'pt_curve_x': pt_x,
                'pt_curve_y': pt_y,
                'eff_curve_x': eff_x,
                'eff_curve_y': eff_y,
                'bus': bus_name
            }
            
        return pv_infos
    
    def get_all_storages_info(self):
        """
        Retorna um dicionário com todos os dados estáticos dos elementos Storage.
        """
        storage_infos = {}
        
        # Aproveitamos o método que já lista todos os elementos de uma classe
        storages_df = self.get_all_elements('Storage')
        if storages_df.empty:
            return storage_infos

        for full_name in storages_df.index:
            name = full_name.split('.')[1] if '.' in full_name else full_name
            
            # Lendo propriedades via texto para garantir consistência
            kw_rated = float(self.dss.text(f"? Storage.{name}.kWrated"))
            kwh_rated = float(self.dss.text(f"? Storage.{name}.kWhrated"))
            kwh_stored = float(self.dss.text(f"? Storage.{name}.kWhstored"))
            pct_reserve = float(self.dss.text(f"? Storage.{name}.%reserve"))
            eff_charge = float(self.dss.text(f"? Storage.{name}.%EffCharge"))
            eff_discharge = float(self.dss.text(f"? Storage.{name}.%EffDischarge"))
            pct_idling = float(self.dss.text(f"? Storage.{name}.%IdlingkW"))
            daily = self.dss.text(f"? Storage.{name}.daily")
            charge_trigger = float(self.dss.text(f"? Storage.{name}.chargeTrigger"))

            discharge_trigger = float(self.dss.text(f"? Storage.{name}.dischargeTrigger"))

            
            storage_infos[name] = {
                'name': name,
                'kw_rated': kw_rated,
                'kwh_rated': kwh_rated,
                'kwh_stored': kwh_stored,
                'pct_reserve': pct_reserve,
                'eff_charge': eff_charge,
                'eff_discharge': eff_discharge,
                'pct_idling': pct_idling,
                'daily': daily,
                'charge_trigger': charge_trigger,
                'discharge_trigger': discharge_trigger
            }
            
        return storage_infos