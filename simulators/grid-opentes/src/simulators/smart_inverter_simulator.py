import mosaik_api_v3
import numpy as np
from opender import DER, DER_PV

META = {
    'api_version': '3.0',
    'type': 'time-based',
    'models': {
        'Inverter': {
            'public': True,
            'params': [
                'kVA', 'eff_curve_x', 'eff_curve_y', 
                'ctrl_config', 'phase_mode'
            ],
            'attrs': [
                'P_dc',       
                'V_meas_1', 'V_meas_2', 'V_meas_3',  
                
                'P_ac', 'Q_ac', 
                'P_ac_1', 'Q_ac_1',
                'P_ac_2', 'Q_ac_2',
                'P_ac_3', 'Q_ac_3',
            ],
        },
    },
}

class InverterModel:
    def __init__(self, kVA, eff_curve_x, eff_curve_y, ctrl_config=None, phase_mode='AVG',
                 np_phase='THREE', np_v_meas_unbalance='AVG'):
        self.kVA = kVA
        self.eff_curve_x = eff_curve_x
        self.eff_curve_y = eff_curve_y
        self.phase_mode = phase_mode.upper()
        
        ctrl_config = ctrl_config or {}
        
        if self.phase_mode == 'INDEP':
            self.ders = [self._create_der(kVA / 3.0, ctrl_config) for _ in range(3)]
        else:
            self.ders = [self._create_der(kVA, ctrl_config)]

        self.P_dc = 0.0
        self.V_meas = [1.0, 1.0, 1.0] 
        
        self.P_ac_out = [0.0, 0.0, 0.0]
        self.Q_ac_out = [0.0, 0.0, 0.0]

    def _create_der(self, kva_rating, config, np_phase='THREE'):
        # Utilizando DER_PV conforme o snippet oficial
        der = DER_PV()
        
        # Definie se o modelo DER é monofásico ou trifásico
        der.der_file.NP_PHASE = np_phase

        # Nameplate Settings (Ajustados para a API correta)
        der.der_file.NP_VA_MAX = kva_rating * 1000 
        der.der_file.NP_P_MAX = kva_rating * 1000 
        
        # Ativação das funções da IEEE 1547 (Mapeadas da documentação)
        der.der_file.CONST_PF_MODE_ENABLE = config.get('Const_PF', False)
        if 'PF' in config: 
            der.der_file.CONST_PF_MODE_ENABLE = config['PF']
            
        der.der_file.QV_MODE_ENABLE = config.get('Volt_Var', False)     # Q(V)
        der.der_file.PV_MODE_ENABLE = config.get('Volt_Watt', False)    # P(V)
        
        return der

    def calculate_step(self, current_time, eid):
        # 1. Filtro da Eficiência do Inversor (Física)
        if self.kVA > 0 and self.P_dc > 0:
            loading_pu = self.P_dc / self.kVA
            efficiency = np.interp(loading_pu, self.eff_curve_x, self.eff_curve_y)
            p_avail_total = self.P_dc * efficiency
        else:
            p_avail_total = 0.0

        # === INÍCIO DOS LOGS ===
        # print(f"\n[OpenDER LOG] {eid} | Tempo: {current_time}s")
        # print(f" -> P_dc (Placas): {self.P_dc:.2f} kW | P_avail (Pós-Eficiência): {p_avail_total:.2f} kW")

        # 2. Execução das Malhas de Controle do OpenDER
        if self.phase_mode == 'INDEP':
            p_avail_per_phase = p_avail_total / 3.0
            
            for i in range(3):
                der = self.ders[i]
                v_pu = self.V_meas[i] if self.V_meas[i] > 0.1 else 1.0
                p_pu = (p_avail_per_phase * 1000) / der.der_file.NP_P_MAX if der.der_file.NP_P_MAX > 0 else 0
                
                der.update_der_input(v_pu=v_pu, f=60.0, p_dc_pu=p_pu)

                P_w, Q_var = der.run()

                p_out_kw = P_w / 1000.0
                q_out_kvar = Q_var / 1000.0
                
                self.P_ac_out[i] = p_out_kw
                self.Q_ac_out[i] = q_out_kvar
                
        else: 
            v_validas = [v for v in self.V_meas if v > 0.1]
            v_avg = sum(v_validas) / len(v_validas) if v_validas else 1.0
            
            der = self.ders[0]
            p_pu = (p_avail_total * 1000) / der.der_file.NP_P_MAX if der.der_file.NP_P_MAX > 0 else 0
            
            der.update_der_input(v_pu=v_avg, f=60.0, p_dc_pu=p_pu)

            P_w, Q_var = der.run()

            # Converte para as bases do OpenDSS (kW e kVAr)
            p_out_kw = P_w / 1000.0
            q_out_kvar = Q_var / 1000.0
            
            p_total_kw = p_out_kw
            q_total_kvar = q_out_kvar
            
            self.P_ac_out = [p_total_kw / 3.0] * 3
            self.Q_ac_out = [q_total_kvar / 3.0] * 3

            # LOG Global (Modo AVG)
            # print(f"    [Global] INPUTS  -> V_avg_meas: {v_avg:.4f} pu | P_avl_pu: {p_pu:.4f} pu")
            # print(f"    [Global] OUTPUTS -> P_out: {p_total_kw:.2f} kW | Q_out: {q_total_kvar:.2f} kvar")

class InverterSim(mosaik_api_v3.Simulator):
    def __init__(self):
        super().__init__(META)
        self.sid = None
        self.entities = {}
        self.step_size = None

    def init(self, sid, time_resolution=1., step_size=900):
        self.sid = sid
        self.step_size = step_size
        
        # ---> ESSENCIAL: Configura o timestep global da simulação dinâmica da IEEE 1547
        # DER.t_s = self.step_size 
        
        return self.meta

    def create(self, num, model, **model_params):
        entities = []
        for i in range(num):
            eid = f'{model}_{len(self.entities) + i}'
            inv_model = InverterModel(
                kVA=model_params.get('kVA', 1000.0),
                eff_curve_x=model_params.get('eff_curve_x', [0.0, 1.0]),
                eff_curve_y=model_params.get('eff_curve_y', [1.0, 1.0]),
                ctrl_config=model_params.get('ctrl_config', {'Const_PF': True, 'PF': 1.0}),
                phase_mode=model_params.get('phase_mode', 'AVG')
            )
            self.entities[eid] = inv_model
            entities.append({'eid': eid, 'type': model})
        return entities

    def step(self, time, inputs, max_advance):
        for eid, attrs in inputs.items():
            inv = self.entities[eid]
            if 'P_dc' in attrs: inv.P_dc = float(list(attrs['P_dc'].values())[0])
            
            if 'V_meas_1' in attrs: inv.V_meas[0] = float(list(attrs['V_meas_1'].values())[0])
            if 'V_meas_2' in attrs: inv.V_meas[1] = float(list(attrs['V_meas_2'].values())[0])
            if 'V_meas_3' in attrs: inv.V_meas[2] = float(list(attrs['V_meas_3'].values())[0])

        for eid, inv in self.entities.items():
            inv.calculate_step(current_time=time, eid=eid)

        return time + self.step_size

    def get_data(self, outputs):
        data = {}
        for eid, attrs in outputs.items():
            inv = self.entities[eid]
            data[eid] = {}
            for attr in attrs:
                if attr == 'P_ac': data[eid][attr] = sum(inv.P_ac_out)
                elif attr == 'Q_ac': data[eid][attr] = sum(inv.Q_ac_out)
                elif attr == 'P_ac_1': data[eid][attr] = inv.P_ac_out[0]
                elif attr == 'Q_ac_1': data[eid][attr] = inv.Q_ac_out[0]
                elif attr == 'P_ac_2': data[eid][attr] = inv.P_ac_out[1]
                elif attr == 'Q_ac_2': data[eid][attr] = inv.Q_ac_out[1]
                elif attr == 'P_ac_3': data[eid][attr] = inv.P_ac_out[2]
                elif attr == 'Q_ac_3': data[eid][attr] = inv.Q_ac_out[2]
        return data

def main():
    return mosaik_api_v3.start_simulation(InverterSim())

if __name__ == '__main__':
    main()