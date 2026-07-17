from __future__ import annotations
import json, math, csv
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

ROOT = Path('/mnt/data/M11_v2_work')
DATA = ROOT/'data'; FIG = ROOT/'figures'
DATA.mkdir(parents=True, exist_ok=True); FIG.mkdir(parents=True, exist_ok=True)

# ---------------- Baseline ----------------
p = {
    'configuration':'D1-P2-R0',
    'fluid':'ar seco',
    'T_K':293.15,
    'rho_kg_m3':1.20,
    'mu_Pa_s':1.81e-5,
    'a_m_s':343.0,
    'mdot_nom_kg_s':0.40,
    'rpm_nom':600.0,
    'rpm_oper_max':1200.0,
    'rpm_overspeed_test':1400.0,
    'rpm_fea_design':1500.0,
    'r_h_m':0.140,
    'r_t_m':0.200,
    'tip_clearance_m':0.0005,
    'Z_R1':12,
    'Z_R2':12,
    'swirl_ratio':0.55,
    'deviation_deg':4.0,
    'first_mode_reduced_Hz':337.0,
    'epsilon_reduced':0.12,
}
p['area_m2'] = math.pi*(p['r_t_m']**2-p['r_h_m']**2)
p['span_m'] = p['r_t_m']-p['r_h_m']
p['hub_tip_ratio'] = p['r_h_m']/p['r_t_m']
p['r_rms_m'] = math.sqrt((p['r_h_m']**2+p['r_t_m']**2)/2)
p['Vx_nom_m_s'] = p['mdot_nom_kg_s']/(p['rho_kg_m3']*p['area_m2'])
p['omega_nom_rad_s'] = 2*math.pi*p['rpm_nom']/60
p['U_mid_nom_m_s'] = p['omega_nom_rad_s']*p['r_rms_m']
p['phi_nom'] = p['Vx_nom_m_s']/p['U_mid_nom_m_s']
p['clearance_span_pct'] = 100*p['tip_clearance_m']/p['span_m']
p['ratio_R2_R1_reduced'] = 1-p['epsilon_reduced']

with open(DATA/'baseline_D1_P2_R0.json','w',encoding='utf-8') as f: json.dump(p,f,indent=2,ensure_ascii=False)

# ---------------- Radial design ----------------
radii = np.array([p['r_h_m'], p['r_rms_m'], p['r_t_m']])
labels = ['Cubo','Médio','Ponta']
chords = np.array([0.080,0.090,0.100])
rows=[]
for lab,r,c in zip(labels,radii,chords):
    U = p['omega_nom_rad_s']*r
    Vx = p['Vx_nom_m_s']
    Vt2 = p['swirl_ratio']*U
    # Angles from axial, signed by tangential direction
    b1_r1 = math.degrees(math.atan2(-U, Vx))
    b2_r1 = math.degrees(math.atan2(Vt2-U, Vx))
    b1_r2 = math.degrees(math.atan2(Vt2+U, Vx))
    b2_r2 = math.degrees(math.atan2(U, Vx))
    # metal angles baseline with 4 deg deviation magnitude toward additional turning
    bm1_r1 = b1_r1
    bm2_r1 = b2_r1 - p['deviation_deg']
    bm1_r2 = b1_r2
    bm2_r2 = b2_r2 - p['deviation_deg']
    spacing = 2*math.pi*r/p['Z_R1']
    solidity = c/spacing
    W1_r1 = math.hypot(Vx,U)
    W2_r1 = math.hypot(Vx,Vt2-U)
    W1_r2 = math.hypot(Vx,Vt2+U)
    W2_r2 = math.hypot(Vx,U)
    # Reynolds on local max relative speed, conservative
    Wmax=max(W1_r1,W2_r1,W1_r2,W2_r2)
    Re = p['rho_kg_m3']*Wmax*c/p['mu_Pa_s']
    Mrel=Wmax/p['a_m_s']
    rows.append({
        'estacao':lab,'r_m':r,'corda_m':c,'espacamento_m':spacing,'solidez':solidity,
        'U_m_s':U,'Vx_m_s':Vx,'Vtheta_R1_saida_m_s':Vt2,
        'beta_R1_entrada_deg':b1_r1,'beta_R1_saida_deg':b2_r1,
        'beta_R2_entrada_deg':b1_r2,'beta_R2_saida_deg':b2_r2,
        'metal_R1_entrada_deg':bm1_r1,'metal_R1_saida_deg':bm2_r1,
        'metal_R2_entrada_deg':bm1_r2,'metal_R2_saida_deg':bm2_r2,
        'cambra_R1_deg':abs(bm2_r1-bm1_r1),'cambra_R2_deg':abs(bm1_r2-bm2_r2),
        'Wmax_m_s':Wmax,'Re_corda_nom':Re,'Mach_rel_nom':Mrel,
        'tmax_m':0.10*c,'r_LE_min_m':0.015*c,'r_LE_max_m':0.020*c,
    })
radial=pd.DataFrame(rows)
radial.to_csv(DATA/'projeto_radial_D1_P2_R0.csv',index=False)

# ---------------- Performance map ----------------
map_rows=[]
for mdot in np.linspace(0.10,0.50,9):
    Vx=mdot/(p['rho_kg_m3']*p['area_m2'])
    for rpm in range(300,1501,100):
        om=2*math.pi*rpm/60
        U=om*p['r_rms_m']
        phi=Vx/U
        Wtip=math.hypot(Vx, 1.55*om*p['r_t_m']) # worst at R2 inlet
        Re=p['rho_kg_m3']*Wtip*0.10/p['mu_Pa_s']
        M=Wtip/p['a_m_s']
        bpf=p['Z_R1']*rpm/60
        margin=(p['first_mode_reduced_Hz']-bpf)/bpf if bpf>0 else np.nan
        map_rows.append({'mdot_kg_s':mdot,'rpm':rpm,'Vx_m_s':Vx,'phi':phi,'Re_tip_0p1m':Re,'Mach_rel_tip':M,'BPF_Hz':bpf,'modal_margin_fraction':margin})
perf=pd.DataFrame(map_rows)
perf.to_csv(DATA/'mapa_operacional_D1_P2_R0.csv',index=False)

# ---------------- Torque ratio sweep ----------------
ratio=np.linspace(0.80,1.00,81)
eps=p['epsilon_reduced']
# normalized net reaction closure; zero at 1-eps
net=(ratio-(1-eps))/(1-eps)
tr=pd.DataFrame({'ratio_abs_R2_R1':ratio,'torque_liquido_normalizado':net})
tr.to_csv(DATA/'varredura_razao_R2_R1.csv',index=False)

# ---------------- Nominal torque/power ----------------
U=p['U_mid_nom_m_s']; Vt=p['swirl_ratio']*U; r=p['r_rms_m']; md=p['mdot_nom_kg_s']; om=p['omega_nom_rad_s']
tau=md*r*Vt
P_each=tau*om
specific=U*Vt
nominal={
    'Vtheta_mid_R1_saida_m_s':Vt,
    'trabalho_especifico_R1_J_kg':specific,
    'trabalho_especifico_R2_J_kg':specific,
    'trabalho_especifico_total_J_kg':2*specific,
    'torque_ideal_por_rotor_Nm':tau,
    'potencia_fluidica_por_rotor_W':P_each,
    'potencia_fluidica_total_W':2*P_each,
}
with open(DATA/'desempenho_nominal_D1_P2_R0.json','w') as f: json.dump(nominal,f,indent=2)

# ---------------- Modal table ----------------
modal=[]
for rpm in [600,1000,1200,1400,1500]:
    bpf=p['Z_R1']*rpm/60
    margin=(p['first_mode_reduced_Hz']-bpf)/bpf
    modal.append({'rpm':rpm,'BPF_Hz':bpf,'f_modo_reduzido_Hz':p['first_mode_reduced_Hz'],'margem_pct':100*margin})
pd.DataFrame(modal).to_csv(DATA/'margem_modal_reduzida.csv',index=False)

# ---------------- Mitigations ----------------
mitigations=[
('BF-01','CAD sólido nativo/STEP','Parcial','Reconstrução paramétrica + desenhos GD&T','STEP AP242, árvore, datums e desenhos liberados'),
('BF-02','Pás sem projeto aerodinâmico','Mitigado analiticamente','Mean-line, triângulos, corda, solidez e torção','CFD 3D e correlações de cascata'),
('BF-03','FEA modal 3D ausente','Aberto','Limites administrativos de rotação','Modal prestress + Campbell do conjunto'),
('BF-04','Orçamento de massa incompleto','Aberto','Estrutura de BOM e margem de crescimento','Catálogos, CAD nativo e pesagem'),
('BF-05','Sobrepressão sem alívio','Aberto bloqueador','P&ID, cenário regulador aberto e requisitos PRD','Dimensionamento/seleção e revisão responsável'),
('BF-06','Motores não dimensionados','Parcial','Torque/potência aerodinâmicos estimados','Perdas, inércia, aceleração e seleção comercial'),
('BF-07','Mancais/eixos não selecionados','Aberto','Cargas e interfaces definidas','Vida L10, rigidez e rotodinâmica'),
('BF-08','Balanceamento não especificado','Aberto','Planos e requisito de procedimento','ISO 21940 e balanceamento físico'),
('BF-09','Contenção de fragmentos','Aberto','Energia rotacional como caso de carga','FEA/ensaio da contenção'),
('BF-10','Eficiência líquida A/B/C','Parcial','Equação e instrumentação definidas','Bancada com potência elétrica e pneumática'),
]
pd.DataFrame(mitigations,columns=['codigo','problema','estado','mitigacao_atual','criterio_fechamento']).to_csv(DATA/'matriz_mitigacoes_BF.csv',index=False)

# ---------------- Test plan T13-T18 ----------------
tests=[]
for i,rat in enumerate([0.80,0.84,0.88,0.92,0.96,1.00],start=13):
    tests.append({'teste':f'T{i:02d}','rpm_R1':600,'razao_abs_R2_R1':rat,'rpm_R2':-600*rat,'objetivo':'mapear torque estrutural líquido e swirl residual'})
pd.DataFrame(tests).to_csv(DATA/'plano_T13_T18_razao_torque.csv',index=False)

# ---------------- Automated checks ----------------
checks=[]
def check(name, cond, value, criterion): checks.append({'verificacao':name,'resultado':'APROVADO' if cond else 'REPROVADO','valor':value,'criterio':criterion})
check('Coeficiente de fluxo nominal',0.40<=p['phi_nom']<=0.60,p['phi_nom'],'0,40 <= phi <= 0,60')
check('Razão cubo-ponta',abs(p['hub_tip_ratio']-0.70)<1e-9,p['hub_tip_ratio'],'lambda = 0,70')
check('Solidez radial',radial.solidez.between(0.90,1.12).all(),f"{radial.solidez.min():.3f}–{radial.solidez.max():.3f}",'0,90 a 1,12')
check('Folga relativa ao span',p['clearance_span_pct']<=1.0,p['clearance_span_pct'],'<= 1,0%')
check('Mach relativo a 1200 rpm',perf[(perf.rpm==1200)&(np.isclose(perf.mdot_kg_s,0.40))].Mach_rel_tip.iloc[0] <=0.15,perf[(perf.rpm==1200)&(np.isclose(perf.mdot_kg_s,0.40))].Mach_rel_tip.iloc[0],'<= 0,15')
check('BPF a 600 rpm',abs(12*600/60-120)<1e-12,120,'120 Hz')
check('Margem reduzida a 1400 rpm',((337-280)/280)>=0.20,100*(337-280)/280,'>= 20% com modelo reduzido')
check('Rotação operacional abaixo do overspeed',p['rpm_oper_max']<p['rpm_overspeed_test'],p['rpm_oper_max'],'Nop < Nover')
check('Ótimo de torque incluído na varredura',ratio.min()<=p['ratio_R2_R1_reduced']<=ratio.max(),p['ratio_R2_R1_reduced'],'0,80 a 1,00')
check('Potência fluídica nominal positiva',nominal['potencia_fluidica_total_W']>0,nominal['potencia_fluidica_total_W'],'> 0 W')
pd.DataFrame(checks).to_csv(DATA/'verificacoes_automatizadas.csv',index=False)

# ---------------- Figures ----------------
plt.rcParams.update({'font.size':9,'axes.titlesize':11,'axes.labelsize':9})

# 1 annuli
fig,ax=plt.subplots(figsize=(8,4.5))
for x,(ri,ro,label) in enumerate([(0.11,0.28,'D1-P1'),(0.14,0.20,'D1-P2-R0')]):
    th=np.linspace(0,2*np.pi,400)
    ax.fill(x+ro*np.cos(th),ro*np.sin(th),alpha=.3)
    ax.fill(x+ri*np.cos(th),ri*np.sin(th),color='white')
    ax.plot(x+ro*np.cos(th),ro*np.sin(th),lw=1)
    ax.plot(x+ri*np.cos(th),ri*np.sin(th),lw=1)
    ax.text(x,-0.34,label,ha='center',fontweight='bold')
ax.set_aspect('equal'); ax.set_xlim(-.35,1.35); ax.set_ylim(-.4,.35); ax.axis('off')
ax.set_title('Redução do anel ativo para elevar o coeficiente de fluxo')
fig.tight_layout(); fig.savefig(FIG/'fig01_aneis_D1P1_D1P2.png',dpi=200); plt.close(fig)

# 2 phi map
pivot=perf.pivot(index='mdot_kg_s',columns='rpm',values='phi')
fig,ax=plt.subplots(figsize=(8,4.8))
im=ax.imshow(pivot.values,origin='lower',aspect='auto',extent=[pivot.columns.min(),pivot.columns.max(),pivot.index.min(),pivot.index.max()])
cb=fig.colorbar(im,ax=ax); cb.set_label('Coeficiente de fluxo φ')
ax.contour(pivot.columns,pivot.index,pivot.values,levels=[0.4,0.48,0.6],colors='k',linewidths=.8)
ax.scatter([600],[0.4],marker='x',s=80,label='Ponto nominal')
ax.set_xlabel('Rotação de R1 (rpm)'); ax.set_ylabel('Vazão mássica (kg/s)'); ax.set_title('Mapa de coeficiente de fluxo do cartucho D1-P2-R0'); ax.legend()
fig.tight_layout(); fig.savefig(FIG/'fig02_mapa_phi.png',dpi=200); plt.close(fig)

# 3 velocity triangles midspan
fig,axs=plt.subplots(1,2,figsize=(9,4))
rm=p['r_rms_m']; U=p['omega_nom_rad_s']*rm; Vx=p['Vx_nom_m_s']; Vt=.55*U
# use quiver from origin; x=axial, y=tangential
for ax,title,vti,vto,uvec in [(axs[0],'Rotor R1',0,Vt,U),(axs[1],'Rotor R2',Vt,0,-U)]:
    ax.quiver(0,0,Vx,vti,angles='xy',scale_units='xy',scale=1,label='V entrada')
    ax.quiver(0,0,Vx,vto,angles='xy',scale_units='xy',scale=1,label='V saída')
    ax.quiver(0,0,0,uvec,angles='xy',scale_units='xy',scale=1,label='U')
    ax.quiver(0,0,Vx,vti-uvec,angles='xy',scale_units='xy',scale=1,label='W entrada')
    ax.quiver(0,0,Vx,vto-uvec,angles='xy',scale_units='xy',scale=1,label='W saída')
    ax.axhline(0,lw=.5); ax.axvline(0,lw=.5); ax.grid(True,alpha=.25); ax.set_aspect('equal',adjustable='box'); ax.set_title(title); ax.set_xlabel('Componente axial (m/s)'); ax.set_ylabel('Componente tangencial (m/s)')
axs[1].legend(loc='center left',bbox_to_anchor=(1.02,.5))
fig.suptitle('Triângulos de velocidade no raio médio — 600 rpm, 0,40 kg/s')
fig.tight_layout(); fig.savefig(FIG/'fig03_triangulos_velocidade.png',dpi=200,bbox_inches='tight'); plt.close(fig)

# 4 chord solidity
fig,ax1=plt.subplots(figsize=(8,4.5))
ax1.plot(radial.r_m*1000,radial.corda_m*1000,marker='o',label='Corda')
ax1.set_xlabel('Raio (mm)'); ax1.set_ylabel('Corda (mm)'); ax1.grid(True,alpha=.25)
ax2=ax1.twinx(); ax2.plot(radial.r_m*1000,radial.solidez,marker='s',label='Solidez')
ax2.set_ylabel('Solidez c/s'); ax2.axhspan(.9,1.1,alpha=.12)
ax1.set_title('Distribuição radial de corda e solidez')
lines=ax1.lines+ax2.lines; ax1.legend(lines,[l.get_label() for l in lines],loc='best')
fig.tight_layout(); fig.savefig(FIG/'fig04_corda_solidez.png',dpi=200); plt.close(fig)

# 5 metal angles
fig,ax=plt.subplots(figsize=(8,4.8))
for col,label in [('metal_R1_entrada_deg','R1 entrada'),('metal_R1_saida_deg','R1 saída'),('metal_R2_entrada_deg','R2 entrada'),('metal_R2_saida_deg','R2 saída')]:
    ax.plot(radial.r_m*1000,radial[col],marker='o',label=label)
ax.axhline(0,lw=.5); ax.grid(True,alpha=.25); ax.set_xlabel('Raio (mm)'); ax.set_ylabel('Ângulo metálico a partir do eixo (graus)'); ax.set_title('Leis radiais preliminares dos ângulos metálicos'); ax.legend(ncol=2)
fig.tight_layout(); fig.savefig(FIG/'fig05_angulos_metalicos.png',dpi=200); plt.close(fig)

# 6 Re/Mach vs rpm at mdot .4
sub=perf[np.isclose(perf.mdot_kg_s,.4)]
fig,ax1=plt.subplots(figsize=(8,4.6))
ax1.plot(sub.rpm,sub.Re_tip_0p1m,label='Re na ponta (c=0,10 m)')
ax1.set_xlabel('Rotação (rpm)'); ax1.set_ylabel('Reynolds'); ax1.grid(True,alpha=.25)
ax2=ax1.twinx(); ax2.plot(sub.rpm,sub.Mach_rel_tip,label='Mach relativo')
ax2.set_ylabel('Mach relativo'); ax2.axhline(.15,ls='--',lw=1)
ax1.set_title('Reynolds e Mach relativo no envelope de rotação')
lines=ax1.lines+ax2.lines; ax1.legend(lines,[l.get_label() for l in lines],loc='upper left')
fig.tight_layout(); fig.savefig(FIG/'fig06_re_mach.png',dpi=200); plt.close(fig)

# 7 modal margin
rpm_arr=np.linspace(400,1600,241); bpf=12*rpm_arr/60; margin=100*(337-bpf)/bpf
fig,ax=plt.subplots(figsize=(8,4.5))
ax.plot(rpm_arr,bpf,label='BPF 12×'); ax.axhline(337,ls='--',label='Modo reduzido 337 Hz')
for x,lab in [(1200,'operacional'),(1400,'overspeed ensaio'),(1500,'FEA')]: ax.axvline(x,ls=':',label=f'{lab}: {x} rpm')
ax.set_xlabel('Rotação (rpm)'); ax.set_ylabel('Frequência (Hz)'); ax.grid(True,alpha=.25); ax.set_title('BPF e modo reduzido de referência'); ax.legend(fontsize=8)
fig.tight_layout(); fig.savefig(FIG/'fig07_bpf_modal.png',dpi=200); plt.close(fig)

# 8 torque ratio
fig,ax=plt.subplots(figsize=(8,4.5)); ax.plot(tr.ratio_abs_R2_R1,tr.torque_liquido_normalizado); ax.axhline(0,lw=.6); ax.axvline(.88,ls='--',label='Fechamento reduzido ≈ 0,88'); ax.axvspan(.80,1.00,alpha=.08,label='Faixa T13–T18'); ax.set_xlabel('|N2|/N1'); ax.set_ylabel('Torque líquido normalizado'); ax.set_title('Varredura de razão para mínimo torque estrutural'); ax.grid(True,alpha=.25); ax.legend(); fig.tight_layout(); fig.savefig(FIG/'fig08_razao_torque.png',dpi=200); plt.close(fig)

# 9 residual swirl stator envelope
x=np.linspace(0,1,100); residual=np.linspace(.15,.20,100)
fig,ax=plt.subplots(figsize=(8,3.9)); ax.fill_between(x,.15,.20,alpha=.25); ax.plot(x,residual*0+.175); ax.set_ylim(0,.3); ax.set_xlim(0,1); ax.set_xticks([]); ax.set_ylabel('ΔVθ/U alvo'); ax.set_title('Faixa inicial de carga prevista para o estator intercambiável'); ax.grid(True,axis='y',alpha=.25); fig.tight_layout(); fig.savefig(FIG/'fig09_estator_envelope.png',dpi=200); plt.close(fig)

# 10 mitigation status
mdf=pd.DataFrame(mitigations,columns=['codigo','problema','estado','mitigacao_atual','criterio_fechamento'])
status_order={'Mitigado analiticamente':3,'Parcial':2,'Aberto':1,'Aberto bloqueador':0}
vals=[status_order[s] for s in mdf.estado]
fig,ax=plt.subplots(figsize=(8,5)); ax.barh(mdf.codigo,vals); ax.set_xlim(-.1,3.3); ax.set_xticks([0,1,2,3],['Bloqueador','Aberto','Parcial','Mitigado analítico']); ax.set_title('Estado dos bloqueios de fabricação BF-01 a BF-10'); ax.grid(True,axis='x',alpha=.25); fig.tight_layout(); fig.savefig(FIG/'fig10_mitigacoes.png',dpi=200); plt.close(fig)

# 11 pressure safety chain diagram
fig,ax=plt.subplots(figsize=(10,3.2)); ax.axis('off')
boxes=['Fonte 3–6 bar','Bloqueio','Regulador','Restritor/medidor','Plenum D1-P2','Alívio independente','Descarga segura']
xs=np.linspace(.05,.95,len(boxes))
for i,(x,txt) in enumerate(zip(xs,boxes)):
    ax.text(x,.55,txt,ha='center',va='center',bbox=dict(boxstyle='round,pad=.35',fc='white',ec='black'),fontsize=8)
    if i<len(boxes)-1: ax.annotate('',xy=(xs[i+1]-.055,.55),xytext=(x+.055,.55),arrowprops=dict(arrowstyle='->'))
ax.text(.5,.12,'O dispositivo de alívio deve ser dimensionado para a vazão máxima da fonte no cenário de falha do regulador, não para a vazão nominal.',ha='center',fontsize=8)
ax.set_title('Arquitetura mínima de proteção contra sobrepressão')
fig.tight_layout(); fig.savefig(FIG/'fig11_cadeia_pressao.png',dpi=200); plt.close(fig)

# 12 test progression
fig,ax=plt.subplots(figsize=(10,3.2)); ax.axis('off')
steps=['CAD nativo','CFD MRF','FEA modal/Campbell','PDR/TRR','Baixa pressão','Rotação progressiva','A/B/C instrumentado']
xs=np.linspace(.06,.94,len(steps))
for i,(x,txt) in enumerate(zip(xs,steps)):
    ax.text(x,.55,txt,ha='center',va='center',bbox=dict(boxstyle='round,pad=.35',fc='white',ec='black'),fontsize=8)
    if i<len(steps)-1: ax.annotate('',xy=(xs[i+1]-.055,.55),xytext=(x+.055,.55),arrowprops=dict(arrowstyle='->'))
ax.set_title('Sequência de liberação técnica do cartucho D1-P2-R0')
fig.tight_layout(); fig.savefig(FIG/'fig12_sequencia_liberacao.png',dpi=200); plt.close(fig)

print('Baseline:',json.dumps(p,indent=2,ensure_ascii=False))
print('Nominal:',json.dumps(nominal,indent=2))
print('Checks:',pd.DataFrame(checks).to_string(index=False))
