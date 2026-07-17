import numpy as np
from scipy.integrate import solve_ivp, cumulative_trapezoid
from dataclasses import dataclass, field
from typing import Tuple, Dict
import warnings
warnings.filterwarnings('ignore')

# =====================================================================
# PROPRIEDADES DO FLUIDO
# =====================================================================
@dataclass
class HTPProperties:
    R_mix: float = 376.2
    gamma: float = 1.30
    cp: float = 1630.0
    cv: float = 1253.8
    T0: float = 1020.0
    delta_h_solucao: float = 2.59e6
    p_crit_ratio: float = 0.5457

# =====================================================================
# PARÂMETROS
# =====================================================================
@dataclass
class MHCParameters:
    L_plenum: float = 8.0
    R1: float = 5.5
    R2: float = 7.0
    h_plenum: float = 1.5
    n_setores: int = 12
    
    A_t: float = 5.95e-4
    A_e: float = 8.93e-3
    Cd: float = 0.95
    
    J1: float = 8.5e5
    J2: float = 1.1e6
    
    b1: float = 120.0
    b2: float = 150.0
    c1: float = 2500.0
    c2: float = 2800.0
    k_tanh: float = 0.1
    
    w_passagem: float = 0.3
    f_D: float = 0.02
    K_local: float = 1.5
    
    K_tau1: float = 15000.0
    K_tau2: float = 18000.0
    
    eta_rec: float = 0.75
    eta_motor: float = 0.92
    eta_cat: float = 0.90
    
    p_amb: float = 0.0
    
    def __post_init__(self):
        self.V_total_plenum = np.pi * (self.R2**2 - self.R1**2) * self.L_plenum
        self.V_setor = self.V_total_plenum / self.n_setores
        self.R_med = (self.R1 + self.R2) / 2.0
        self.A_pass = self.h_plenum * self.w_passagem
        self.L_conex = 2 * np.pi * self.R_med / self.n_setores
        self.L_f = self.L_conex / self.A_pass
        D_h = 2 * self.h_plenum * self.w_passagem / (self.h_plenum + self.w_passagem)
        self.R_f_base = (self.f_D * self.L_conex / (D_h * self.A_pass**2) + 
                         self.K_local / self.A_pass**2) / 2

# =====================================================================
# VETOR DE ESTADOS CORRIGIDO – FILTRO DERIVATIVO COMO ESTADO
# =====================================================================
@dataclass
class MHCState:
    Omega_1: float = 0.0
    Omega_2: float = 0.0
    phi_1: float = 0.0
    phi_2: float = np.pi/3
    
    rho_g: np.ndarray = field(default_factory=lambda: np.zeros(12))
    T_g: np.ndarray = field(default_factory=lambda: np.ones(12)*300.0)
    m_dot_ij: np.ndarray = field(default_factory=lambda: np.zeros(12))
    
    # PID: integrais e erros filtrados (estados)
    I_yaw: float = 0.0
    I_pitch: float = 0.0
    I_roll: float = 0.0
    e_f_yaw: float = 0.0
    e_f_pitch: float = 0.0
    e_f_roll: float = 0.0
    
    # Atuadores
    theta_yaw: float = 0.0
    theta_pitch: float = 0.0
    theta_roll: float = 0.0
    theta_dot_yaw: float = 0.0
    theta_dot_pitch: float = 0.0
    theta_dot_roll: float = 0.0
    
    # Armazenamento
    m_HTP: float = 5000.0
    E_bat: float = 2.0e9
    E_term_struct: float = 5.0e8
    
    # Acumuladores
    total_mass_in: float = 0.0
    total_mass_out: float = 0.0
    total_energy_quim: float = 0.0
    total_energy_jato: float = 0.0
    total_energy_friction: float = 0.0
    
    def to_array(self) -> np.ndarray:
        return np.concatenate([
            [self.Omega_1, self.Omega_2, self.phi_1, self.phi_2],
            self.rho_g, self.T_g, self.m_dot_ij,
            [self.I_yaw, self.I_pitch, self.I_roll,
             self.e_f_yaw, self.e_f_pitch, self.e_f_roll],
            [self.theta_yaw, self.theta_pitch, self.theta_roll,
             self.theta_dot_yaw, self.theta_dot_pitch, self.theta_dot_roll],
            [self.m_HTP, self.E_bat, self.E_term_struct,
             self.total_mass_in, self.total_mass_out,
             self.total_energy_quim, self.total_energy_jato,
             self.total_energy_friction]
        ])
    
    @classmethod
    def from_array(cls, arr: np.ndarray, n: int = 12) -> 'MHCState':
        idx = 0
        Omega_1, Omega_2, phi_1, phi_2 = arr[idx:idx+4]; idx += 4
        rho_g = arr[idx:idx+n]; idx += n
        T_g = arr[idx:idx+n]; idx += n
        m_dot_ij = arr[idx:idx+n]; idx += n
        I_yaw, I_pitch, I_roll = arr[idx:idx+3]; idx += 3
        e_f_yaw, e_f_pitch, e_f_roll = arr[idx:idx+3]; idx += 3
        theta_yaw, theta_pitch, theta_roll = arr[idx:idx+3]; idx += 3
        theta_dot_yaw, theta_dot_pitch, theta_dot_roll = arr[idx:idx+3]; idx += 3
        m_HTP, E_bat, E_term = arr[idx:idx+3]; idx += 3
        mass_in, mass_out = arr[idx:idx+2]; idx += 2
        energy_quim, energy_jato, energy_fric = arr[idx:idx+3]
        return cls(Omega_1, Omega_2, phi_1, phi_2, rho_g, T_g, m_dot_ij,
                   I_yaw, I_pitch, I_roll, e_f_yaw, e_f_pitch, e_f_roll,
                   theta_yaw, theta_pitch, theta_roll,
                   theta_dot_yaw, theta_dot_pitch, theta_dot_roll,
                   m_HTP, E_bat, E_term, mass_in, mass_out,
                   energy_quim, energy_jato, energy_fric)

# =====================================================================
# MODELO CORRIGIDO – TODAS AS EMENDAS APLICADAS
# =====================================================================
class MHC10:
    """MHC-1.0 – Consistência física completa (núcleo 0D)"""
    
    def __init__(self, params: MHCParameters = None):
        self.p = params or MHCParameters()
        self.htp = HTPProperties()
        self.n = self.p.n_setores
        self.theta_setores = np.linspace(0, 2*np.pi, self.n, endpoint=False)
        
        # Constante do bocal (vácuo)
        self.K_nozzle = (self.p.Cd * self.p.A_t / np.sqrt(self.htp.R_mix) * 
                         np.sqrt(self.htp.gamma) * 
                         (2/(self.htp.gamma+1))**((self.htp.gamma+1)/(2*(self.htp.gamma-1))))
        
        # Solução do Mach
        self.M_e = self._solve_mach_exit()
        self.T_ratio = 1 / (1 + (self.htp.gamma-1)/2 * self.M_e**2)
        self.p_ratio = self.T_ratio**(self.htp.gamma/(self.htp.gamma-1))
        self.v_e_coeff = self.M_e * np.sqrt(self.htp.gamma * self.htp.R_mix * self.T_ratio)
        
        # Ganhos PID
        self.Kp_yaw, self.Ki_yaw, self.Kd_yaw = 2.0, 0.3, 0.1
        self.Kp_pitch, self.Ki_pitch, self.Kd_pitch = 2.0, 0.3, 0.1
        self.Kp_roll, self.Ki_roll, self.Kd_roll = 1.5, 0.2, 0.05
        self.tau_d = 0.05  # Filtro derivativo
        
        # Atuador
        self.K_a = 50000.0
        self.B_a = 200.0
        self.Ja = 50.0
        self.theta_max = 0.20
    
    def _area_func(self, M: float) -> float:
        gamma = self.htp.gamma
        term = (2/(gamma+1)) * (1 + (gamma-1)/2 * M**2)
        exp = (gamma+1)/(2*(gamma-1))
        return (1/M) * term**exp
    
    def _solve_mach_exit(self) -> float:
        area_ratio = self.p.A_e / self.p.A_t
        M_low, M_high = 1.0, 50.0
        for _ in range(200):
            M_mid = (M_low + M_high) / 2
            if self._area_func(M_mid) < area_ratio:
                M_low = M_mid
            else:
                M_high = M_mid
            if M_high - M_low < 1e-12:
                break
        return (M_low + M_high) / 2
    
    def nozzle_mass_flow(self, p0: float, T0: float) -> float:
        """Vazão mássica – sempre ≥ 0 (estrangulado no vácuo)."""
        if p0 < 100.0 or T0 <= 0:
            return 0.0
        return self.K_nozzle * p0 / np.sqrt(T0)
    
    def nozzle_thrust_params(self, p0: float, T0: float) -> Dict:
        m_dot = self.nozzle_mass_flow(p0, T0)
        if m_dot <= 0:
            return {'m_dot': 0.0, 'v_e': 0.0, 'p_e': 0.0, 'T_mag': 0.0}
        v_e = self.v_e_coeff * np.sqrt(T0)
        p_e = p0 * self.p_ratio
        T_mag = m_dot * v_e + p_e * self.p.A_e
        return {'m_dot': m_dot, 'v_e': v_e, 'p_e': p_e, 'T_mag': T_mag}
    
    def _limit_actuator_rate(self, theta: float, theta_dot: float) -> float:
        """Limita velocidade próximo ao batente – retorna a velocidade efetiva."""
        if abs(theta) >= self.theta_max and theta * theta_dot > 0:
            return 0.0
        return theta_dot
    
    def dynamics(self, t: float, y: np.ndarray,
                 tau_m1: float, tau_m2: float,
                 m_dot_HTP: float) -> np.ndarray:
        
        state = MHCState.from_array(y, self.n)
        
        # Pressão
        p_g = state.rho_g * self.htp.R_mix * state.T_g
        p_g = np.maximum(p_g, 1.0)
        
        # ===== ROTORES =====
        v_theta = np.zeros(self.n)
        for k in range(self.n):
            if state.rho_g[k] > 1e-6:
                v_theta[k] = state.m_dot_ij[k] / (state.rho_g[k] * self.p.A_pass + 1e-10)
        Omega_f = np.mean(v_theta) / self.p.R_med
        
        delta_Omega_1 = state.Omega_1 - Omega_f
        delta_Omega_2 = state.Omega_2 + Omega_f
        
        tau_fluido1 = self.p.K_tau1 * delta_Omega_1 * abs(delta_Omega_1)
        tau_fluido2 = self.p.K_tau2 * delta_Omega_2 * abs(delta_Omega_2)
        
        tau_f1 = (self.p.b1 * state.Omega_1 + 
                  self.p.c1 * np.tanh(self.p.k_tanh * state.Omega_1))
        tau_f2 = (self.p.b2 * state.Omega_2 + 
                  self.p.c2 * np.tanh(self.p.k_tanh * state.Omega_2))
        
        dOmega_1 = (tau_m1 - tau_fluido1 - tau_f1) / self.p.J1
        dOmega_2 = (tau_m2 - tau_fluido2 - tau_f2) / self.p.J2
        dphi_1 = state.Omega_1
        dphi_2 = state.Omega_2
        
        # Potência rotor→gás (com sinal)
        W_rotor_to_gas = tau_fluido1 * state.Omega_1 + tau_fluido2 * state.Omega_2
        
        # Potência de atrito mecânico (sempre dissipativa)
        P_friction = (self.p.b1 * state.Omega_1**2 + 
                     self.p.b2 * state.Omega_2**2 +
                     self.p.c1 * abs(state.Omega_1) + 
                     self.p.c2 * abs(state.Omega_2))
        
        # ===== MASSA =====
        m_dot_in = m_dot_HTP * np.ones(self.n) / self.n
        m_dot_out = np.zeros(self.n)
        for k in range(self.n):
            m_dot_out[k] = self.nozzle_mass_flow(p_g[k], state.T_g[k])
        
        # Fluxos laterais
        m_dot_lateral = np.zeros(self.n)
        for k in range(self.n):
            k_next = (k + 1) % self.n
            m_dot_lateral[k] -= state.m_dot_ij[k]
            k_prev = (k - 1) % self.n
            m_dot_lateral[k] += state.m_dot_ij[k_prev]
        
        dm_dt = m_dot_in - m_dot_out + m_dot_lateral
        drho_g = dm_dt / self.p.V_setor
        
        # ===== ENERGIA =====
        dT_g = np.zeros(self.n)
        # 100% da potência rotor→gás é entregue ao gás (simplificação)
        W_por_setor = np.ones(self.n) / self.n * W_rotor_to_gas
        
        for k in range(self.n):
            m_k = state.rho_g[k] * self.p.V_setor
            if m_k < 1e-6:
                dT_g[k] = (self.htp.T0 - state.T_g[k]) * 0.1
                continue
            
            H_in = m_dot_in[k] * self.htp.cp * self.htp.T0
            H_out = m_dot_out[k] * self.htp.cp * state.T_g[k]
            dU_dt = H_in - H_out + W_por_setor[k]
            
            dT_g[k] = (dU_dt - self.htp.cv * state.T_g[k] * dm_dt[k]) / (m_k * self.htp.cv)
        
        # ===== FLUXOS LATERAIS =====
        dm_dot_ij = np.zeros(self.n)
        for k in range(self.n):
            k_next = (k + 1) % self.n
            delta_p = p_g[k] - p_g[k_next]
            rho_med = max((state.rho_g[k] + state.rho_g[k_next]) / 2, 1e-6)
            R_f = self.p.R_f_base / rho_med
            dm_dot_ij[k] = (delta_p - R_f * state.m_dot_ij[k] * abs(state.m_dot_ij[k])) / self.p.L_f
        
        # ===== PID COM FILTRO DERIVATIVO (ESTADOS) =====
        p_target = 2.0e6
        
        e_yaw = np.sum((p_target - p_g) * np.sin(self.theta_setores)) / (self.n * p_target)
        e_pitch = np.sum((p_target - p_g) * np.cos(self.theta_setores)) / (self.n * p_target)
        e_roll = (state.Omega_1 + state.Omega_2) / 30.0
        
        dI_yaw = e_yaw
        dI_pitch = e_pitch
        dI_roll = e_roll
        
        # Filtro derivativo (estado)
        de_f_yaw = (e_yaw - state.e_f_yaw) / self.tau_d
        de_f_pitch = (e_pitch - state.e_f_pitch) / self.tau_d
        de_f_roll = (e_roll - state.e_f_roll) / self.tau_d
        
        # Sinal de controle
        u_yaw = (self.Kp_yaw * e_yaw + self.Ki_yaw * state.I_yaw + 
                self.Kd_yaw * de_f_yaw)
        u_pitch = (self.Kp_pitch * e_pitch + self.Ki_pitch * state.I_pitch + 
                  self.Kd_pitch * de_f_pitch)
        u_roll = (self.Kp_roll * e_roll + self.Ki_roll * state.I_roll + 
                 self.Kd_roll * de_f_roll)
        
        u_yaw = np.clip(u_yaw, -5000, 5000)
        u_pitch = np.clip(u_pitch, -5000, 5000)
        u_roll = np.clip(u_roll, -3000, 3000)
        
        # Dinâmica dos atuadores
        dtheta_dot_yaw = (u_yaw - self.K_a * state.theta_yaw - self.B_a * state.theta_dot_yaw) / self.Ja
        dtheta_dot_pitch = (u_pitch - self.K_a * state.theta_pitch - self.B_a * state.theta_dot_pitch) / self.Ja
        dtheta_dot_roll = (u_roll - self.K_a * state.theta_roll - self.B_a * state.theta_dot_roll) / self.Ja
        
        # Velocidade angular limitada (limite de curso)
        dtheta_yaw = self._limit_actuator_rate(state.theta_yaw, state.theta_dot_yaw)
        dtheta_pitch = self._limit_actuator_rate(state.theta_pitch, state.theta_dot_pitch)
        dtheta_roll = self._limit_actuator_rate(state.theta_roll, state.theta_dot_roll)
        
        # ===== ARMAZENAMENTO =====
        P_quim = self.p.eta_cat * m_dot_HTP * self.htp.delta_h_solucao
        
        P_mot = 0.0
        if tau_m1 * state.Omega_1 > 0:
            P_mot += tau_m1 * state.Omega_1 / self.p.eta_motor
        if tau_m2 * state.Omega_2 > 0:
            P_mot += tau_m2 * state.Omega_2 / self.p.eta_motor
        
        P_rec = 0.0
        if tau_m1 * state.Omega_1 < 0:
            P_rec += self.p.eta_rec * abs(tau_m1 * state.Omega_1)
        if tau_m2 * state.Omega_2 < 0:
            P_rec += self.p.eta_rec * abs(tau_m2 * state.Omega_2)
        
        P_jato_total = 0.0
        for k in range(self.n):
            nozzle = self.nozzle_thrust_params(p_g[k], state.T_g[k])
            P_jato_total += 0.5 * nozzle['m_dot'] * nozzle['v_e']**2
        
        dm_HTP = -m_dot_HTP
        dE_bat = -P_mot - 5000.0 + P_rec
        dE_term = 0.3 * P_friction  # Apenas atrito mecânico aquece a estrutura
        
        # Acumuladores
        d_mass_in = m_dot_HTP
        d_mass_out = np.sum(m_dot_out)   # sempre ≥ 0
        d_energy_quim = P_quim
        d_energy_jato = P_jato_total
        d_energy_fric = P_friction
        
        dy = np.concatenate([
            [dOmega_1, dOmega_2, dphi_1, dphi_2],
            drho_g, dT_g, dm_dot_ij,
            [dI_yaw, dI_pitch, dI_roll, de_f_yaw, de_f_pitch, de_f_roll],
            [dtheta_yaw, dtheta_pitch, dtheta_roll,
             dtheta_dot_yaw, dtheta_dot_pitch, dtheta_dot_roll],
            [dm_HTP, dE_bat, dE_term,
             d_mass_in, d_mass_out, d_energy_quim, d_energy_jato, d_energy_fric]
        ])
        
        return dy

# =====================================================================
# CONTROLADOR DE MODO
# =====================================================================
def get_mode_torques(mode: str, Omega_1: float, Omega_2: float) -> Tuple[float, float]:
    if mode == "EQUILIBRADO":
        Kp = 8000.0
        return Kp*(15.0 - Omega_1), Kp*(-15.0 - Omega_2)
    elif mode == "PROPULSIVO":
        Kp = 10000.0
        return Kp*(25.0 - Omega_1), Kp*(-8.0 - Omega_2)
    elif mode == "VETORIAL_YAW+":
        Kp = 8000.0
        return Kp*(18.0 - Omega_1), Kp*(-12.0 - Omega_2)
    elif mode == "RECUPERACAO":
        return -15000.0, -12000.0
    return 0.0, 0.0

# =====================================================================
# SIMULAÇÃO SEGMENTADA E AUDITORIA
# =====================================================================

# =====================================================================
# SIMULAÇÃO SEGMENTADA E AUDITORIA DE REPRODUTIBILIDADE
# =====================================================================
if __name__ == "__main__":
    import csv
    from pathlib import Path
    from scipy.integrate import solve_ivp, cumulative_trapezoid

    print("="*76)
    print("MHC-1.0.1 - EXECUÇÃO SEGMENTADA E AUDITORIA DE CONSERVAÇÃO")
    print("="*76)

    params = MHCParameters()
    model = MHC10(params)

    state0 = MHCState(
        rho_g=np.ones(params.n_setores) * 0.001,
        T_g=np.ones(params.n_setores) * 300.0,
        m_HTP=5000.0,
        E_bat=2.0e9,
        E_term_struct=5.0e8
    )
    initial_gas_mass = np.sum(state0.rho_g) * params.V_setor

    mode_sequence = [
        (0.0, 10.0, "EQUILIBRADO", 8.0),
        (10.0, 25.0, "PROPULSIVO", 15.0),
        (25.0, 35.0, "VETORIAL_YAW+", 12.0),
        (35.0, 50.0, "PROPULSIVO", 15.0),
        (50.0, 60.0, "RECUPERACAO", 2.0),
    ]

    print(f"Bocal: M_e={model.M_e:.6f}, A_e/A_t={params.A_e/params.A_t:.6f}")
    print(f"K_nozzle={model.K_nozzle:.12e} kg*sqrt(K)/(s*Pa)")
    print(f"Massa inicial de gás={initial_gas_mass:.9f} kg")

    all_t=[]; all_y=[]; all_seg=[]; all_mode=[]; all_mdot=[]
    all_mout_quad=[]; all_min_exact=[]
    y0=state0.to_array(); out_offset=0.0; in_offset=0.0

    for seg_id,(t0,t1,mode,mdot) in enumerate(mode_sequence):
        npts=int(round((t1-t0)/0.01))+1
        t_eval=np.linspace(t0,t1,npts)

        def rhs_segment(t,y,mode=mode,mdot=mdot):
            st=MHCState.from_array(y,params.n_setores)
            tau1,tau2=get_mode_torques(mode,st.Omega_1,st.Omega_2)
            return model.dynamics(t,y,tau1,tau2,mdot)

        sol=solve_ivp(rhs_segment,(t0,t1),y0,method='RK45',t_eval=t_eval,
                      rtol=1e-9,atol=1e-11,max_step=0.01)
        if not sol.success:
            raise RuntimeError(f"Falha no segmento {seg_id}: {sol.message}")

        # Taxa de saída em todos os pontos do segmento, incluindo o ponto inicial.
        seg_mout_rate=np.zeros(len(sol.t))
        for j in range(len(sol.t)):
            st=MHCState.from_array(sol.y[:,j],params.n_setores)
            p=st.rho_g*model.htp.R_mix*st.T_g
            p=np.maximum(p,1.0)
            seg_mout_rate[j]=sum(model.nozzle_mass_flow(p[k],st.T_g[k]) for k in range(params.n_setores))
        seg_mout_quad=out_offset+cumulative_trapezoid(seg_mout_rate,sol.t,initial=0.0)
        seg_min_exact=in_offset+mdot*(sol.t-t0)

        # Concatena sem duplicar o ponto de fronteira, mas mantém a integral do primeiro intervalo.
        sl=slice(None) if seg_id==0 else slice(1,None)
        all_t.append(sol.t[sl]); all_y.append(sol.y[:,sl])
        all_seg.extend([seg_id]*len(sol.t[sl]))
        all_mode.extend([mode]*len(sol.t[sl]))
        all_mdot.extend([mdot]*len(sol.t[sl]))
        all_mout_quad.append(seg_mout_quad[sl]); all_min_exact.append(seg_min_exact[sl])

        out_offset=seg_mout_quad[-1]
        in_offset=seg_min_exact[-1]
        y0=sol.y[:,-1]

    t=np.concatenate(all_t)
    y=np.concatenate(all_y,axis=1)
    segment_ids=np.asarray(all_seg,dtype=int)
    mode_name=np.asarray(all_mode,dtype=object)
    mdot_command=np.asarray(all_mdot,dtype=float)
    M_out_quad=np.concatenate(all_mout_quad)
    M_in_exact=np.concatenate(all_min_exact)

    gas_mass=np.zeros_like(t); m_out_rate=np.zeros_like(t); thrust=np.zeros_like(t)
    p_mean=np.zeros_like(t); T_mean=np.zeros_like(t); omega1=np.zeros_like(t); omega2=np.zeros_like(t)

    for i in range(len(t)):
        st=MHCState.from_array(y[:,i],params.n_setores)
        p=st.rho_g*model.htp.R_mix*st.T_g
        p=np.maximum(p,1.0)
        gas_mass[i]=np.sum(st.rho_g)*params.V_setor
        p_mean[i]=np.mean(p); T_mean[i]=np.mean(st.T_g)
        omega1[i]=st.Omega_1; omega2[i]=st.Omega_2
        for k in range(params.n_setores):
            noz=model.nozzle_thrust_params(p[k],st.T_g[k])
            m_out_rate[i]+=noz['m_dot']; thrust[i]+=noz['T_mag']

    residual=gas_mass-initial_gas_mass-M_in_exact+M_out_quad

    stf=MHCState.from_array(y[:,-1],params.n_setores)
    final_m_in=M_in_exact[-1]; final_m_out=M_out_quad[-1]; final_gas=gas_mass[-1]
    final_res=residual[-1]; max_res=np.max(np.abs(residual))
    mass_scale=max(initial_gas_mass+final_m_in,1.0); rel_res=max_res/mass_scale
    final_mdot=m_out_rate[-1]; final_thrust=thrust[-1]
    final_isp=final_thrust/(final_mdot*9.80665) if final_mdot>0 else 0.0

    print("\nRESULTADOS FINAIS")
    print(f"HTP consumido: {5000.0-stf.m_HTP:.9f} kg")
    print(f"Entrada exata: {final_m_in:.9f} kg")
    print(f"Saída por quadratura segmentada: {final_m_out:.9f} kg")
    print(f"Saída pelo estado acumulador: {stf.total_mass_out:.9f} kg")
    print(f"Gás final no plenum: {final_gas:.9f} kg")
    print(f"Residual final: {final_res:.12e} kg")
    print(f"Residual máximo: {max_res:.12e} kg")
    print(f"Residual relativo: {rel_res:.12e}")
    print(f"Pressão média final: {p_mean[-1]/1e6:.6f} MPa")
    print(f"Temperatura média final: {T_mean[-1]:.6f} K")
    print(f"Vazão final: {final_mdot:.6f} kg/s")
    print(f"Empuxo final: {final_thrust/1000:.6f} kN")
    print(f"Isp final: {final_isp:.6f} s")

    checks={
        'solver_completed': True,
        'mass_out_nonnegative': bool(np.min(m_out_rate)>=-1e-12),
        'htp_consumed_670kg': bool(abs((5000.0-stf.m_HTP)-670.0)<1e-5),
        'mass_residual_abs_lt_1e-3kg': bool(max_res<1e-3),
        'mass_residual_rel_lt_1e-6': bool(rel_res<1e-6),
        'gas_mass_physical_bound': bool(final_gas<=initial_gas_mass+final_m_in+1e-9),
        'quadrature_matches_state_accumulator': bool(abs(final_m_out-stf.total_mass_out)<1e-3),
    }
    print("\nTESTES")
    for name,ok in checks.items():
        print(f"{name}: {'PASS' if ok else 'FAIL'}")

    out_dir=Path('/mnt/data/MHC_1_0_1_resultados')
    out_dir.mkdir(parents=True,exist_ok=True)

    with (out_dir/'MHC_1_0_1_serie_temporal.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f)
        w.writerow(['time_s','segment','mode','mdot_in_kg_s','omega1_rad_s','omega2_rad_s',
                    'pressure_mean_Pa','temperature_mean_K','gas_mass_kg','mdot_out_kg_s',
                    'thrust_N','M_in_exact_kg','M_out_quad_kg','mass_residual_kg'])
        for i in range(len(t)):
            w.writerow([t[i],int(segment_ids[i]),mode_name[i],mdot_command[i],omega1[i],omega2[i],
                        p_mean[i],T_mean[i],gas_mass[i],m_out_rate[i],thrust[i],
                        M_in_exact[i],M_out_quad[i],residual[i]])

    with (out_dir/'MHC_1_0_1_metricas.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f); w.writerow(['metric','value','unit'])
        rows=[('M_e',model.M_e,'-'),('K_nozzle',model.K_nozzle,'kg*sqrt(K)/(s*Pa)'),
              ('HTP_consumed',5000.0-stf.m_HTP,'kg'),('M_in_exact',final_m_in,'kg'),
              ('M_out_segmented',final_m_out,'kg'),('M_out_state',stf.total_mass_out,'kg'),
              ('gas_mass_final',final_gas,'kg'),('mass_residual_final',final_res,'kg'),
              ('mass_residual_max',max_res,'kg'),('mass_residual_relative',rel_res,'-'),
              ('pressure_mean_final',p_mean[-1],'Pa'),('temperature_mean_final',T_mean[-1],'K'),
              ('mdot_out_final',final_mdot,'kg/s'),('thrust_final',final_thrust,'N'),('Isp_final',final_isp,'s')]
        w.writerows(rows)

    import matplotlib.pyplot as plt
    fig=plt.figure(figsize=(10,5.5)); plt.plot(t,residual); plt.axhline(0,linewidth=0.8)
    plt.xlabel('Tempo (s)'); plt.ylabel('Residual de massa (kg)')
    plt.title('MHC-1.0.1 - Residual de massa com quadratura segmentada'); plt.tight_layout()
    fig.savefig(out_dir/'fig_residual_massa.png',dpi=180); plt.close(fig)

    fig=plt.figure(figsize=(10,5.5)); plt.plot(t,initial_gas_mass+M_in_exact,label='Massa disponível')
    plt.plot(t,gas_mass+M_out_quad,label='Gás + massa expelida')
    plt.xlabel('Tempo (s)'); plt.ylabel('Massa acumulada (kg)'); plt.title('Fechamento global de massa')
    plt.legend(); plt.tight_layout(); fig.savefig(out_dir/'fig_fechamento_massa.png',dpi=180); plt.close(fig)

    fig=plt.figure(figsize=(10,5.5)); plt.plot(t,p_mean/1e6,label='Pressão média (MPa)')
    plt.plot(t,T_mean/1000,label='Temperatura média (10³ K)')
    plt.xlabel('Tempo (s)'); plt.ylabel('Grandeza'); plt.title('Evolução termodinâmica média do plenum')
    plt.legend(); plt.tight_layout(); fig.savefig(out_dir/'fig_pressao_temperatura.png',dpi=180); plt.close(fig)

    fig=plt.figure(figsize=(10,5.5)); plt.plot(t,omega1,label='Omega 1'); plt.plot(t,omega2,label='Omega 2')
    plt.xlabel('Tempo (s)'); plt.ylabel('Velocidade angular (rad/s)'); plt.title('Resposta rotacional por modo operacional')
    plt.legend(); plt.tight_layout(); fig.savefig(out_dir/'fig_rotacao.png',dpi=180); plt.close(fig)

    fig=plt.figure(figsize=(10,5.5)); plt.plot(t,thrust/1000,label='Empuxo (kN)'); plt.plot(t,m_out_rate,label='Vazão (kg/s)')
    plt.xlabel('Tempo (s)'); plt.ylabel('Empuxo / vazão'); plt.title('Saída propulsiva do modelo 0D')
    plt.legend(); plt.tight_layout(); fig.savefig(out_dir/'fig_empuxo_vazao.png',dpi=180); plt.close(fig)

    print(f"\nArquivos gerados em: {out_dir}")
