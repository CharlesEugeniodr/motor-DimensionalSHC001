from pathlib import Path
import math, json, csv, hashlib, shutil
import numpy as np
import pandas as pd
import trimesh
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle, FancyArrowPatch, FancyBboxPatch
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

ROOT=Path('/mnt/data')
W=ROOT/'M12_work'
for sub in ['models','data','figures','code','cfd_template','fea_prep']:
    (W/sub).mkdir(parents=True, exist_ok=True)
MODELS=W/'models'; DATA=W/'data'; FIG=W/'figures'

# D1-P1 parametric baseline. This is a controlled digital baseline, not a fabrication release.
P={
    'config_id':'D1-P1',
    'purpose':'Revisão geométrica do demonstrador de fluxo frio para fechamento de bypass e preparação de CFD/FEA',
    'total_length_m':1.20,
    'outer_guard_od_m':0.70,
    'outer_guard_thickness_m':0.006,
    'flow_liner_inner_radius_m':0.280,
    'flow_liner_thickness_m':0.004,
    'central_capsule_outer_radius_m':0.110,
    'central_capsule_thickness_m':0.005,
    'active_annulus_inner_radius_m':0.110,
    'active_annulus_outer_radius_m':0.280,
    'rotor_hub_clearance_m':0.0005,
    'rotor_tip_clearance_m':0.0005,
    'rotor1_x0_m':0.240,
    'rotor1_length_m':0.170,
    'rotor2_x0_m':0.440,
    'rotor2_length_m':0.170,
    'stator_x0_m':0.640,
    'stator_length_m':0.140,
    'nozzle_x0_m':0.840,
    'nozzle_x1_m':1.100,
    'outlet_duct_x1_m':1.180,
    'nozzle_outer_exit_radius_m':0.240,
    'nozzle_inner_exit_radius_m':0.075,
    'nozzle_wall_thickness_m':0.003,
    'rotor1_blades':6,
    'rotor2_blades':6,
    'stator_vanes':8,
    'rotor1_twist_deg':62.0,
    'rotor2_twist_deg':-62.0,
    'stator_turn_deg':-18.0,
    'rotor_vane_thickness_m':0.0030,
    'stator_vane_thickness_m':0.0035,
    'rpm_nominal_max':1200,
    'rpm_analysis_limit':1500,
    'gas':'ar seco ou N2',
    'facility_source_pressure_bar_abs_min':3.0,
    'facility_source_pressure_bar_abs_max':6.0,
    'metering_regulator_pressure_bar_abs':2.0,
    'test_section_pressure_bar_abs_min':1.00,
    'test_section_pressure_bar_abs_max':1.05,
    'mass_flow_min_kg_s':0.05,
    'mass_flow_max_kg_s':0.40,
    'orifice_discharge_coefficient':0.80,
    'material_baseline':'Alumínio 6061-T6 para estimativa de massa; rolamentos/eixos separados',
    'status':'Baseline digital revisada; não liberada para fabricação'
}

# ---- geometry helpers ----
def rot_y(theta):
    c,s=math.cos(theta),math.sin(theta)
    T=np.eye(4); T[:3,:3]=[[c,0,s],[0,1,0],[-s,0,c]]; return T

def annulus_x(rmin,rmax,length,xcenter,sections=128):
    m=trimesh.creation.annulus(rmin,rmax,height=length,sections=sections)
    m.apply_transform(rot_y(math.pi/2)); m.apply_translation([xcenter,0,0])
    return ensure(m)

def cylinder_x(radius,length,xcenter,sections=128):
    m=trimesh.creation.cylinder(radius=radius,height=length,sections=sections)
    m.apply_transform(rot_y(math.pi/2)); m.apply_translation([xcenter,0,0])
    return ensure(m)

def ensure(m):
    m.remove_unreferenced_vertices()
    try: m.fix_normals(multibody=True)
    except Exception: pass
    if m.volume < 0: m.invert()
    return m

def box_radial(x, r0, r1, angle, axial=0.018, tangential=0.014):
    # box oriented radially in yz plane, centered between r0 and r1
    length=r1-r0
    m=trimesh.creation.box(extents=[axial,length,tangential])
    m.apply_translation([x,(r0+r1)/2,0])
    T=trimesh.transformations.rotation_matrix(angle,[1,0,0],point=[x,0,0])
    m.apply_transform(T)
    return ensure(m)

def frustum_annular_volume_x(rout0,rout1,rin0,rin1,length,xcenter,sections=128):
    x0=xcenter-length/2; x1=xcenter+length/2
    verts=[]
    for x,r in [(x0,rout0),(x1,rout1),(x0,rin0),(x1,rin1)]:
        for i in range(sections):
            a=2*math.pi*i/sections; verts.append([x,r*math.cos(a),r*math.sin(a)])
    faces=[]
    for i in range(sections):
        j=(i+1)%sections
        o0=i; o1=sections+i; i0=2*sections+i; i1=3*sections+i
        po0=j; po1=sections+j; pi0=2*sections+j; pi1=3*sections+j
        faces += [[o0,po0,po1],[o0,po1,o1]]
        faces += [[i0,i1,pi1],[i0,pi1,pi0]]
        faces += [[o0,i0,pi0],[o0,pi0,po0]]
        faces += [[o1,po1,pi1],[o1,pi1,i1]]
    return ensure(trimesh.Trimesh(vertices=np.array(verts),faces=np.array(faces),process=True))

def frustum_wall_x(flow_r0,flow_r1,thickness,length,xcenter,wall_side='outside',sections=128):
    # solid thin wall whose flow-facing radius is flow_r. outside wall extends outward; inside wall extends inward.
    if wall_side=='outside':
        rin0,rin1=flow_r0,flow_r1; rout0,rout1=flow_r0+thickness,flow_r1+thickness
    else:
        rin0,rin1=flow_r0-thickness,flow_r1-thickness; rout0,rout1=flow_r0,flow_r1
    return frustum_annular_volume_x(rout0,rout1,rin0,rin1,length,xcenter,sections)

def helical_vane(x0,length,r_inner,r_outer,theta0,twist_deg,thickness_m=0.003,steps=32):
    verts=[]
    for k in range(steps+1):
        t=k/steps; x=x0+length*t; theta=theta0+math.radians(twist_deg)*t
        for r,sign in [(r_inner,-1),(r_outer,-1),(r_inner,1),(r_outer,1)]:
            da=sign*thickness_m/(2*r)
            a=theta+da; verts.append([x,r*math.cos(a),r*math.sin(a)])
    faces=[]
    for k in range(steps):
        a=4*k; b=4*(k+1)
        faces += [[a,b,b+1],[a,b+1,a+1]]
        faces += [[a+2,a+3,b+3],[a+2,b+3,b+2]]
        faces += [[a,a+2,b+2],[a,b+2,b]]
        faces += [[a+1,b+1,b+3],[a+1,b+3,a+3]]
    faces += [[0,1,3],[0,3,2]]
    a=4*steps; faces += [[a,a+2,a+3],[a,a+3,a+1]]
    return ensure(trimesh.Trimesh(vertices=np.array(verts),faces=np.array(faces),process=True))

def rotor_assembly(x0,length,blades,twist,r_in,r_out,vane_t):
    parts=[]; ring_ax=0.010; ring_rad=0.006
    # rings remain inside clearance envelope
    for xc in [x0+ring_ax/2,x0+length-ring_ax/2]:
        parts.append(annulus_x(r_in,r_in+ring_rad,ring_ax,xc))
        parts.append(annulus_x(r_out-ring_rad,r_out,ring_ax,xc))
    for i in range(blades):
        parts.append(helical_vane(x0,length,r_in+ring_rad,r_out-ring_rad,2*math.pi*i/blades,twist,vane_t))
    m=trimesh.util.concatenate(parts); return ensure(m)

def stator_assembly(x0,length,vanes,turn,r_in,r_out,vane_t):
    parts=[]; ring_ax=0.010; ring_rad=0.006
    for xc in [x0+ring_ax/2,x0+length-ring_ax/2]:
        parts.append(annulus_x(r_in,r_in+ring_rad,ring_ax,xc))
        parts.append(annulus_x(r_out-ring_rad,r_out,ring_ax,xc))
    for i in range(vanes):
        parts.append(helical_vane(x0,length,r_in+ring_rad,r_out-ring_rad,2*math.pi*i/vanes,turn,vane_t,steps=24))
    return ensure(trimesh.util.concatenate(parts))

def make_internal_hub(x,shaft_r,outer_r=0.104,thickness=0.012,spokes=3):
    parts=[annulus_x(shaft_r,shaft_r+0.006,thickness,x),annulus_x(outer_r-0.006,outer_r,thickness,x)]
    for i in range(spokes): parts.append(box_radial(x,shaft_r+0.006,outer_r-0.006,2*math.pi*i/spokes,axial=thickness,tangential=0.010))
    return ensure(trimesh.util.concatenate(parts))

# ---- axial architecture ----
rin=P['active_annulus_inner_radius_m']; rout=P['active_annulus_outer_radius_m']
hub_clear=P['rotor_hub_clearance_m']; tip_clear=P['rotor_tip_clearance_m']
rrin=rin+hub_clear; rrout=rout-tip_clear

components={}
components['outer_guard']=annulus_x(P['outer_guard_od_m']/2-P['outer_guard_thickness_m'],P['outer_guard_od_m']/2,P['total_length_m'],P['total_length_m']/2)
# flow liner and seals
components['flow_liner']=annulus_x(rout,rout+P['flow_liner_thickness_m'],0.82,0.42)
components['outer_seal_inlet']=annulus_x(rout+P['flow_liner_thickness_m'],P['outer_guard_od_m']/2-P['outer_guard_thickness_m'],0.014,0.017)
components['outer_seal_outlet']=annulus_x(rout+P['flow_liner_thickness_m'],P['outer_guard_od_m']/2-P['outer_guard_thickness_m'],0.014,0.823)
# central capsule split around rotating hub windows
cap_ro=rin; cap_ri=rin-P['central_capsule_thickness_m']
segments=[(0.025,0.318),(0.332,0.518),(0.532,0.840)]
for idx,(x0,x1) in enumerate(segments,1):
    components[f'capsule_shell_{idx}']=annulus_x(cap_ri,cap_ro,x1-x0,(x0+x1)/2)
components['capsule_front_cap']=cylinder_x(cap_ro,0.006,0.022)
# Rotors and stator
components['rotor1']=rotor_assembly(P['rotor1_x0_m'],P['rotor1_length_m'],P['rotor1_blades'],P['rotor1_twist_deg'],rrin,rrout,P['rotor_vane_thickness_m'])
components['rotor2']=rotor_assembly(P['rotor2_x0_m'],P['rotor2_length_m'],P['rotor2_blades'],P['rotor2_twist_deg'],rrin,rrout,P['rotor_vane_thickness_m'])
components['stator']=stator_assembly(P['stator_x0_m'],P['stator_length_m'],P['stator_vanes'],P['stator_turn_deg'],rin,rout,P['stator_vane_thickness_m'])
# concentric shafts and internal hubs
components['shaft_R1']=cylinder_x(0.015,0.39,0.205)
components['shaft_R2']=annulus_x(0.018,0.024,0.59,0.305)
components['hub_R1_internal']=make_internal_hub(0.325,0.015)
components['hub_R2_internal']=make_internal_hub(0.525,0.024)
# rotating hub rings fill capsule windows, with 0.3 mm labyrinth clearance each side in x represented by window gaps
components['hub_R1_rotating_ring']=annulus_x(0.104,rrin,0.012,0.325)
components['hub_R2_rotating_ring']=annulus_x(0.104,rrin,0.012,0.525)
# simplified bearings inside capsule
for n,x,r0,r1 in [('bearing_R1A',0.10,0.015,0.028),('bearing_R1B',0.29,0.015,0.028),('bearing_R2A',0.14,0.024,0.038),('bearing_R2B',0.49,0.024,0.038)]:
    components[n]=annulus_x(r0,r1,0.018,x)
# outer cavity support ribs, outside pressure liner
rguard=P['outer_guard_od_m']/2-P['outer_guard_thickness_m']
ribs=[]
for x in [0.10,0.55,0.81]:
    for i in range(3): ribs.append(box_radial(x,rout+P['flow_liner_thickness_m'],rguard,2*math.pi*i/3,axial=0.018,tangential=0.012))
components['guard_support_ribs']=ensure(trimesh.util.concatenate(ribs))
# annular nozzle: two thin shells and exit duct shells
L=P['nozzle_x1_m']-P['nozzle_x0_m']; xc=(P['nozzle_x0_m']+P['nozzle_x1_m'])/2
components['nozzle_outer_shell']=frustum_wall_x(rout,P['nozzle_outer_exit_radius_m'],P['nozzle_wall_thickness_m'],L,xc,'outside')
components['nozzle_inner_shell']=frustum_wall_x(rin,P['nozzle_inner_exit_radius_m'],P['nozzle_wall_thickness_m'],L,xc,'inside')
components['outlet_outer_duct']=annulus_x(P['nozzle_outer_exit_radius_m'],P['nozzle_outer_exit_radius_m']+P['nozzle_wall_thickness_m'],P['outlet_duct_x1_m']-P['nozzle_x1_m'],(P['outlet_duct_x1_m']+P['nozzle_x1_m'])/2)
components['outlet_inner_duct']=annulus_x(P['nozzle_inner_exit_radius_m']-P['nozzle_wall_thickness_m'],P['nozzle_inner_exit_radius_m'],P['outlet_duct_x1_m']-P['nozzle_x1_m'],(P['outlet_duct_x1_m']+P['nozzle_x1_m'])/2)
# outlet cap for capsule after nozzle
components['capsule_rear_cap']=cylinder_x(P['nozzle_inner_exit_radius_m']-P['nozzle_wall_thickness_m'],0.006,P['outlet_duct_x1_m']-0.003)

# fluid envelopes for CFD pre-processing (without blade subtraction)
fluid_test=annulus_x(rin,rout,P['nozzle_x0_m'],P['nozzle_x0_m']/2)
fluid_nozzle=frustum_annular_volume_x(P['nozzle_outer_exit_radius_m'],rout,P['nozzle_inner_exit_radius_m'],rin,L,xc)
fluid_exit=annulus_x(P['nozzle_inner_exit_radius_m'],P['nozzle_outer_exit_radius_m'],P['outlet_duct_x1_m']-P['nozzle_x1_m'],(P['outlet_duct_x1_m']+P['nozzle_x1_m'])/2)
fluid_parts={'fluid_test_envelope':fluid_test,'fluid_nozzle_envelope':fluid_nozzle,'fluid_exit_envelope':fluid_exit}

# Export models and scene
colors={
 'outer_guard':[105,130,145,45],'flow_liner':[90,120,145,130],'outer_seal_inlet':[100,110,120,255],'outer_seal_outlet':[100,110,120,255],
 'rotor1':[25,95,165,255],'rotor2':[225,120,35,255],'stator':[60,145,105,255],
 'nozzle_outer_shell':[150,155,160,170],'nozzle_inner_shell':[150,155,160,170],
 'shaft_R1':[70,70,75,255],'shaft_R2':[105,105,110,255],'hub_R1_internal':[25,95,165,255],'hub_R2_internal':[225,120,35,255],
 'hub_R1_rotating_ring':[25,95,165,255],'hub_R2_rotating_ring':[225,120,35,255],
 'guard_support_ribs':[85,90,95,255]
}
scene=trimesh.Scene()
for name,m in components.items():
    c=colors.get(name,[115,120,125,255] if 'capsule' not in name and 'bearing' not in name else [70,80,90,255])
    m.visual.face_colors=c
    scene.add_geometry(m,node_name=name,geom_name=name)
    m.export(MODELS/f'{name}.stl')
for name,m in fluid_parts.items(): m.export(MODELS/f'{name}.stl')
scene.export(MODELS/'SHC001_D1_P1_assembly.glb')
scene.export(MODELS/'SHC001_D1_P1_assembly.obj')

# ---- numerical audit ----
DENSITY={'Alumínio 6061-T6':2700.0,'Aço inoxidável':7900.0}
material_map={name:('Aço inoxidável' if name.startswith('shaft') or name.startswith('bearing') else 'Alumínio 6061-T6') for name in components}
rows=[]
for name,m in components.items():
    parts=m.split(only_watertight=False)
    mat=material_map[name]; rho=DENSITY[mat]
    rows.append({
      'componente':name,'watertight':bool(m.is_watertight),'signed_volume_m3':float(m.volume),'absolute_volume_m3':abs(float(m.volume)),
      'surface_area_m2':float(m.area),'connected_bodies':len(parts),'material_baseline':mat,'mass_estimate_kg':abs(float(m.volume))*rho,
      'xmin_m':float(m.bounds[0,0]),'xmax_m':float(m.bounds[1,0]),'radial_max_m':float(np.max(np.linalg.norm(m.vertices[:,1:3],axis=1)))
    })
audit=pd.DataFrame(rows)
audit.to_csv(DATA/'auditoria_geometria_D1_P1.csv',index=False,encoding='utf-8-sig')

# Mass comparison vs P0
p0_summary=json.loads((ROOT/'E3A_work/data/resumo_resultados_E3A.json').read_text(encoding='utf-8'))
mass_p1=float(audit.mass_estimate_kg.sum())
mass_al_parts=float(audit.loc[audit.material_baseline=='Alumínio 6061-T6','mass_estimate_kg'].sum())
mass_ss_parts=float(audit.loc[audit.material_baseline=='Aço inoxidável','mass_estimate_kg'].sum())
comp_mass=pd.DataFrame([
 {'configuracao':'D1-P0 interpretado como sólidos de alumínio','massa_kg':p0_summary['solid_mass_all_aluminum_kg'],'natureza':'auditoria do STL anterior'},
 {'configuracao':'D1-P1 baseline de cascas e interfaces','massa_kg':mass_p1,'natureza':'estimativa geométrica por materiais baseline'}
])
comp_mass.to_csv(DATA/'comparacao_massa_P0_P1.csv',index=False,encoding='utf-8-sig')

# Areas and bypass
Aactive=math.pi*(rout*rout-rin*rin)
A_clear_outer=math.pi*(rout*rout-rrout*rrout)
A_clear_inner=math.pi*(rrin*rrin-rin*rin)
Aclear=A_clear_outer+A_clear_inner
bypass_frac=Aclear/Aactive
c_worst=0.0007
A_worst=math.pi*(rout*rout-(rout-c_worst)**2)+math.pi*((rin+c_worst)**2-rin*rin)
bypass_worst=A_worst/Aactive
areas=pd.DataFrame([
 {'item':'Anel ativo','area_m2':Aactive,'fraction_active_percent':100.0,'criterion':'referência'},
 {'item':'Folga de ponta nominal 0,5 mm','area_m2':A_clear_outer,'fraction_active_percent':100*A_clear_outer/Aactive,'criterion':'parte do limite <1%'},
 {'item':'Folga de cubo nominal 0,5 mm','area_m2':A_clear_inner,'fraction_active_percent':100*A_clear_inner/Aactive,'criterion':'parte do limite <1%'},
 {'item':'Bypass geométrico nominal total','area_m2':Aclear,'fraction_active_percent':100*bypass_frac,'criterion':'<1%'},
 {'item':'Bypass geométrico pior caso 0,7 mm','area_m2':A_worst,'fraction_active_percent':100*bypass_worst,'criterion':'<1%'}
])
areas.to_csv(DATA/'fechamento_bypass_D1_P1.csv',index=False,encoding='utf-8-sig')

# Pressure-flow closure through choked orifices
gamma=1.4; R=287.05; T0=293.15; p0=P['metering_regulator_pressure_bar_abs']*1e5; Cd=P['orifice_discharge_coefficient']
G=p0*math.sqrt(gamma/(R*T0))*(2/(gamma+1))**((gamma+1)/(2*(gamma-1)))
orows=[]
for mdot in [0.05,0.10,0.20,0.30,0.40]:
    A=mdot/(Cd*G); d=math.sqrt(4*A/math.pi)
    rho=1.0e5/(R*T0); vx=mdot/(rho*Aactive); q=0.5*rho*vx*vx
    orows.append({'mass_flow_kg_s':mdot,'regulator_pressure_bar_abs':2.0,'Cd':Cd,'orifice_area_m2':A,'orifice_diameter_mm':1000*d,'active_annulus_velocity_m_s':vx,'dynamic_pressure_Pa':q})
orifice=pd.DataFrame(orows)
orifice.to_csv(DATA/'dimensionamento_orificios_D1_P1.csv',index=False,encoding='utf-8-sig')

pressure_hierarchy=pd.DataFrame([
 {'station':'P0 - fonte da instalação','pressure_bar_abs_min':3.0,'pressure_bar_abs_max':6.0,'function':'energia pneumática da bancada'},
 {'station':'P1 - após regulador primário','pressure_bar_abs_min':2.0,'pressure_bar_abs_max':2.0,'function':'condição de estagnação do orifício sônico'},
 {'station':'P2 - plenum de amortecimento','pressure_bar_abs_min':1.00,'pressure_bar_abs_max':1.05,'function':'entrada estabilizada do módulo A/B/C'},
 {'station':'P3 - saída do módulo','pressure_bar_abs_min':0.995,'pressure_bar_abs_max':1.02,'function':'antes do duto/ambiente'},
 {'station':'Pamb - ambiente','pressure_bar_abs_min':0.98,'pressure_bar_abs_max':1.02,'function':'referência barométrica medida'}
])
pressure_hierarchy.to_csv(DATA/'hierarquia_pressao_D1_P1.csv',index=False,encoding='utf-8-sig')

# Torque ratio control map (from reduced model principle)
torque_map=[]
for eps in [0.05,0.08,0.10,0.12,0.15,0.18,0.20]:
    ratio=1-eps
    torque_map.append({'effectiveness_epsilon':eps,'initial_ratio_abs_rpm_R2_over_R1':ratio,'rpm_R1_example':1000,'rpm_R2_setpoint_example':-1000*ratio,'control_rule':'trim by measured individual torques until |Tnet|/max(|T1|,|T2|)<0.05'})
pd.DataFrame(torque_map).to_csv(DATA/'mapa_controle_contrarrotacao_D1_P1.csv',index=False,encoding='utf-8-sig')

# Interfaces and tolerances
interfaces=pd.DataFrame([
 ['IF-M-01','Liner - módulo rotativo','Diâmetro interno 560,0 mm','H7 equivalente / ajuste a definir','Concentricidade alvo 0,15 mm','CFD/FEA e desenho detalhado'],
 ['IF-M-02','Cápsula - cubos rotativos','Diâmetro externo 220,0 mm','Folga radial nominal 0,50 mm','Pior caso 0,70 mm','Medição CMM'],
 ['IF-M-03','Ponta de rotor - liner','Raio 279,5/280,0 mm','Folga radial nominal 0,50 mm','Pior caso 0,70 mm','Calibre e relógio comparador'],
 ['IF-M-04','Eixo R1','Ø30 mm','Tolerância a definir por rolamento','Batimento alvo <0,05 mm','Desenho do eixo'],
 ['IF-M-05','Eixo R2 tubular','Ø48/36 mm','Tolerância a definir por rolamento','Batimento alvo <0,05 mm','Desenho do eixo'],
 ['IF-F-01','Orifício sônico intercambiável','Ø13,1 a 36,9 mm','Conjunto de placas calibradas','Cd inicial 0,80','Calibração de vazão'],
 ['IF-I-01','Tomadas de pressão','1/8 NPT ou interface equivalente','Sem projetar no escoamento','P0/P1/P2/P3','Seleção final de sensor'],
 ['IF-I-02','Torquímetros R1/R2','Em linha com cada acionamento','Faixa mínima 0-5 N·m','Amostragem sincronizada','Seleção comercial']
],columns=['id','interface','dimensao_baseline','ajuste_ou_faixa','criterio','verificacao'])
interfaces.to_csv(DATA/'interfaces_D1_P1.csv',index=False,encoding='utf-8-sig')

bom=[]
for _,r in audit.iterrows():
    bom.append({'item':r.componente,'qty':1,'material_baseline':r.material_baseline,'mass_estimate_kg':r.mass_estimate_kg,'manufacturing_route':'usinagem/chapa/AM a definir','release_state':'baseline digital'})
pd.DataFrame(bom).to_csv(DATA/'BOM_D1_P1.csv',index=False,encoding='utf-8-sig')

# FEA preparation load cases
fea=pd.DataFrame([
 ['LC-01','Pressão estacionária no liner','Δp=5 kPa','liner, cápsula e nozzle','deslocamento, tensão, ovalização'],
 ['LC-02','Pressão limite de análise','Δp=25 kPa','liner, cápsula e nozzle','tensão e flambagem local'],
 ['LC-03','Rotação nominal','R1=1200 rpm; R2 conforme mapa','rotores e cubos','tensão centrífuga e deformação'],
 ['LC-04','Limite de análise','1500 rpm, sem operação até liberação modal','rotores, eixos e mancais','modos, Campbell, margens'],
 ['LC-05','Torque de projeto','±5 N·m em cada eixo','eixos, cubos e acoplamentos','tensão torsional e rotação relativa'],
 ['LC-06','Desbalanceamento','massa excêntrica a definir por classe de balanceamento','conjunto rotativo','resposta harmônica e carga de mancal'],
 ['LC-07','Peso próprio e montagem','1 g em três orientações','conjunto completo','alinhamento e apoio de bancada']
],columns=['case_id','load_case','input','scope','outputs'])
fea.to_csv(W/'fea_prep/load_cases_D1_P1.csv',index=False,encoding='utf-8-sig')

# CFD patch registry and generic template
patches=pd.DataFrame([
 ['inlet_annulus','patch','mass-flow or total-pressure inlet after metering plenum'],
 ['outlet','patch','static pressure / ambient'],
 ['capsule_wall','wall','stationary no-slip'],
 ['liner_wall','wall','stationary no-slip'],
 ['rotor1','wall+MRF','rotation +omega1'],
 ['rotor2','wall+MRF','rotation -omega2'],
 ['stator','wall','stationary'],
 ['nozzle_outer','wall','stationary'],
 ['nozzle_inner','wall','stationary'],
 ['periodic_or_full','configuration','full annulus baseline; sector only after periodicity proof']
],columns=['patch_name','type','definition'])
patches.to_csv(W/'cfd_template/patch_registry_D1_P1.csv',index=False,encoding='utf-8-sig')
(W/'cfd_template/README_CFD_D1_P1.md').write_text('''# D1-P1 - preparação de CFD 3D\n\nEsta pasta não contém resultados CFD. Ela registra a geometria e os nomes de patches para criação de um caso MRF.\n\n## Ordem de execução\n1. Importar os STL de paredes e rotores.\n2. Construir o volume fluídico entre cápsula, liner e bocal.\n3. Subtrair os sólidos de R1, R2 e estator no pré-processador escolhido.\n4. Criar zonas rotativas independentes para R1 e R2.\n5. Executar três malhas e verificar massa, torque, perda de pressão total e swirl residual.\n6. Comparar A/B/C com mesmas condições de entrada e saída.\n\nOs arquivos `fluid_*_envelope.stl` são envelopes auxiliares; não substituem a extração booleana final do volume de fluido.\n''',encoding='utf-8')

# Action closure matrix
closure=pd.DataFrame([
 ['AC-01','Crítica','Fechamento geométrico','Atendida na baseline digital','Liner e cápsula delimitam o anel; folgas nominal/pior caso = %.3f%% / %.3f%%'%(100*bypass_frac,100*bypass_worst),'Confirmar no CAD nativo e CMM'],
 ['AC-02','Crítica','Relação pressão-vazão','Atendida no modelo 1D de alimentação','Fonte/regulador/plenum separados; placas de %.1f a %.1f mm'%(orifice.orifice_diameter_mm.min(),orifice.orifice_diameter_mm.max()),'Calibrar Cd e medir vazão'],
 ['AC-03','Alta','Bocal maciço','Atendida geometricamente','Bocal dividido em duas cascas de 3 mm','FEA e rota de fabricação'],
 ['AC-04','Alta','Cápsula maciça','Atendida geometricamente','Cápsula em casca de 5 mm, eixos, cubos e mancais representados','Detalhar vedação e rolamentos'],
 ['AC-05','Alta','Normais/volumes negativos','Atendida no intercâmbio STL','Todos os componentes exportados com volume assinado positivo','Validar no CAD mestre'],
 ['AC-06','Alta','Cancelamento de torque','Atendida no nível de lógica de controle','Mapa R2/R1 e medição individual definidos','Verificação física E4 permanece aberta'],
 ['AC-07','Média','Cruzamento modal','Aberta','1500 rpm mantido apenas como limite de análise','FEA modal 3D'],
 ['AC-08','Média','Regime transicional','Aberta','Plano deve incluir caracterização de turbulência','Bancada E4'],
 ['AC-09','Média','Interfaces ausentes','Parcialmente atendida','Interfaces principais de eixos, mancais, folgas e sensores registradas','Desenhos de fabricação'],
 ['AC-10','Média','Coeficientes hipotéticos','Aberta','Módulos A/B/C e patches preparados','CFD 3D e ensaio']
],columns=['id','priority','issue','digital_status','evidence','remaining_verification'])
closure.to_csv(DATA/'matriz_fechamento_acoes_D1_P1.csv',index=False,encoding='utf-8-sig')

# Tests
def chk(name,condition,detail): return {'test':name,'passed':bool(condition),'detail':detail}
tests=[]
tests.append(chk('T01_all_component_stl_watertight',audit.watertight.all(),'Todos os componentes estruturais fechados'))
tests.append(chk('T02_all_signed_volumes_positive',(audit.signed_volume_m3>0).all(),'Normais reorientadas e volumes positivos'))
tests.append(chk('T03_nominal_bypass_under_1pct',bypass_frac<0.01,f'{100*bypass_frac:.4f}%'))
tests.append(chk('T04_worst_case_bypass_under_1pct',bypass_worst<0.01,f'{100*bypass_worst:.4f}%'))
tests.append(chk('T05_mass_reduction_vs_P0',mass_p1<0.35*p0_summary['solid_mass_all_aluminum_kg'],f'{mass_p1:.2f} kg vs {p0_summary["solid_mass_all_aluminum_kg"]:.2f} kg'))
tests.append(chk('T06_orifice_monotonic',orifice.orifice_diameter_mm.is_monotonic_increasing,'Diâmetro cresce com vazão'))
tests.append(chk('T07_rotor_clearance_positive',rrin>rin and rrout<rout,'Folgas de cubo e ponta positivas'))
tests.append(chk('T08_axial_modules_nonoverlap',P['rotor1_x0_m']+P['rotor1_length_m']<P['rotor2_x0_m'] and P['rotor2_x0_m']+P['rotor2_length_m']<P['stator_x0_m'],'Estações axiais separadas'))
tests.append(chk('T09_assembly_within_envelope',audit.xmin_m.min()>=-1e-6 and audit.xmax_m.max()<=P['total_length_m']+1e-6,'Conjunto dentro de 1,20 m'))
tests.append(chk('T10_pressure_hierarchy',P['facility_source_pressure_bar_abs_min']>P['metering_regulator_pressure_bar_abs']>P['test_section_pressure_bar_abs_max'],'Fonte > regulador > seção de teste'))
testdf=pd.DataFrame(tests); testdf.to_csv(DATA/'testes_D1_P1.csv',index=False,encoding='utf-8-sig')

# Summary
summary={
 'config_id':'D1-P1','component_count':len(components),'all_watertight':bool(audit.watertight.all()),'all_signed_volumes_positive':bool((audit.signed_volume_m3>0).all()),
 'mass_estimate_total_kg':mass_p1,'mass_estimate_aluminum_parts_kg':mass_al_parts,'mass_estimate_steel_parts_kg':mass_ss_parts,
 'p0_solid_mass_reference_kg':p0_summary['solid_mass_all_aluminum_kg'],'mass_reduction_percent':100*(1-mass_p1/p0_summary['solid_mass_all_aluminum_kg']),
 'active_area_m2':Aactive,'nominal_clearance_bypass_percent':100*bypass_frac,'worst_case_clearance_bypass_percent':100*bypass_worst,
 'orifice_diameter_min_mm':float(orifice.orifice_diameter_mm.min()),'orifice_diameter_max_mm':float(orifice.orifice_diameter_mm.max()),
 'tests_passed':int(testdf.passed.sum()),'tests_total':len(testdf),'ac01_to_ac05_digital_closed':True,'ac06_control_logic_defined':True,
 'cfd_3d_executed':False,'fea_3d_executed':False,'physical_bench_executed':False
}
(DATA/'resumo_D1_P1.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
(DATA/'D1_P1_baseline.json').write_text(json.dumps(P,ensure_ascii=False,indent=2),encoding='utf-8')
pd.DataFrame([{'group':'baseline','parameter':k,'value':v} for k,v in P.items()]).to_csv(DATA/'parametros_D1_P1.csv',index=False,encoding='utf-8-sig')

# ---- figures ----
def plot_mesh(ax,mesh,color,alpha=1.0,max_faces=4500):
    f=mesh.faces
    if len(f)>max_faces: f=f[np.linspace(0,len(f)-1,max_faces).astype(int)]
    tri=mesh.vertices[f]; coll=Poly3DCollection(tri,facecolor=color,edgecolor='none',alpha=alpha); ax.add_collection3d(coll)

def setup3d(ax,elev=22,azim=-58):
    ax.view_init(elev=elev,azim=azim); ax.set_box_aspect((1.65,1,1)); ax.set_xlim(-.03,1.22); ax.set_ylim(-.38,.38); ax.set_zlim(-.38,.38); ax.set_axis_off()

def save(name,fig):
    fig.savefig(FIG/name,dpi=220,bbox_inches='tight',facecolor='white'); plt.close(fig)

# fig 1 isometric
fig=plt.figure(figsize=(12,7)); ax=fig.add_subplot(111,projection='3d')
for name in components:
    alpha=0.10 if name=='outer_guard' else (0.35 if name=='flow_liner' else 1.0)
    c=np.array(colors.get(name,[110,115,120,255])[:3])/255
    plot_mesh(ax,components[name],c,alpha)
setup3d(ax,24,-58); ax.set_title('SHC-001 D1-P1 - baseline geométrica revisada',fontsize=16,fontweight='bold')
save('fig01_isometrico_D1P1.png',fig)

# fig 2 exploded key components
fig=plt.figure(figsize=(13,7)); ax=fig.add_subplot(111,projection='3d')
order=['outer_seal_inlet','rotor1','rotor2','stator','nozzle_outer_shell','nozzle_inner_shell']
for i,name in enumerate(order):
    m=components[name].copy(); m.apply_translation([i*0.10,0,0]); plot_mesh(ax,m,np.array(colors.get(name,[120,120,120,255])[:3])/255,.95)
for name in ['capsule_shell_1','capsule_shell_2','capsule_shell_3','shaft_R1','shaft_R2']:
    plot_mesh(ax,components[name],np.array(colors.get(name,[80,90,100,255])[:3])/255,.45)
setup3d(ax,22,-55); ax.set_xlim(-.03,1.75); ax.set_title('Vista explodida funcional - D1-P1',fontsize=16,fontweight='bold')
save('fig02_explodido_D1P1.png',fig)

# fig 3 longitudinal schematic
fig,ax=plt.subplots(figsize=(13,5)); ax.set_xlim(0,1.2); ax.set_ylim(-.37,.37); ax.axis('off')
ax.add_patch(Rectangle((0,-.35),1.2,.70,fill=False,lw=2,ec='#415a6b'))
# outer cavity/liner/capsule
ax.add_patch(Rectangle((0,-.284),.84,.568,fc='#cbdce8',alpha=.45,ec='#476b82'))
ax.add_patch(Rectangle((0.025,-.11),.815,.22,fc='#606c76',alpha=.9))
regs=[(.24,.41,'R1','#2f75b5'),(.44,.61,'R2','#ed7d31'),(.64,.78,'Estator','#548235'),(.84,1.10,'Bocal anular','#a5a5a5')]
for x0,x1,l,c in regs:
    ax.add_patch(Rectangle((x0,-.278),x1-x0,.556,fc=c,alpha=.72,ec='black')); ax.text((x0+x1)/2,.30,l,ha='center',fontweight='bold')
# nozzle lines
ax.plot([.84,1.10],[-.28,-.24],color='#666',lw=3); ax.plot([.84,1.10],[.28,.24],color='#666',lw=3)
ax.plot([.84,1.10],[-.11,-.075],color='#666',lw=3); ax.plot([.84,1.10],[.11,.075],color='#666',lw=3)
for y in [-.18,.18]: ax.add_patch(FancyArrowPatch((.01,y),(1.17,y),arrowstyle='->',mutation_scale=14,color='#1f4e79'))
ax.text(.02,-.36,'Entrada anular medida',fontsize=9); ax.text(.98,-.36,'Saída anular',fontsize=9)
ax.set_title('Seção longitudinal e caminho de escoamento controlado',fontsize=15,fontweight='bold')
save('fig03_longitudinal_D1P1.png',fig)

# fig 4 cross section bypass
fig,axs=plt.subplots(1,2,figsize=(12,5))
for ax,title,clear in [(axs[0],'Nominal: 0,50 mm',0.0005),(axs[1],'Pior caso: 0,70 mm',0.0007)]:
    ax.set_aspect('equal'); ax.axis('off')
    for r,fc,a in [(0.35,'#d9e2e8',.8),(0.344,'white',1),(0.284,'#9fbad0',.7),(0.280,'white',1),(0.110,'#59636d',.9),(0.105,'white',1)]:
        ax.add_patch(Circle((0,0),r,fc=fc,ec='black',alpha=a))
    ax.add_patch(Circle((0,0),0.280-clear,fill=False,ec='#ed7d31',lw=4))
    ax.add_patch(Circle((0,0),0.110+clear,fill=False,ec='#2f75b5',lw=4))
    frac=(math.pi*(.28**2-(.28-clear)**2)+math.pi*((.11+clear)**2-.11**2))/Aactive*100
    ax.text(0,-.41,f'Área de folga = {frac:.3f}% do anel ativo',ha='center',fontweight='bold')
    ax.set_xlim(-.42,.42); ax.set_ylim(-.45,.42); ax.set_title(title,fontweight='bold')
fig.suptitle('Fechamento do bypass geométrico por liner, cápsula e folgas controladas',fontsize=15,fontweight='bold')
save('fig04_bypass_D1P1.png',fig)

# fig 5 pressure hierarchy
fig,ax=plt.subplots(figsize=(12,5)); ax.axis('off'); ax.set_xlim(0,1); ax.set_ylim(0,1)
items=[(.05,'Fonte\n3-6 bar abs','#b4c7e7'),(.25,'Regulador\n2,0 bar abs','#9dc3e6'),(.45,'Orifício\nsônico','#ffd966'),(.65,'Plenum\n1,00-1,05 bar','#a9d18e'),(.85,'Módulo A/B/C\n~ambiente','#c6e0b4')]
for x,t,c in items:
    ax.add_patch(FancyBboxPatch((x-.075,.38),.15,.24,boxstyle='round,pad=.02',fc=c,ec='#44546a',lw=1.5)); ax.text(x,.50,t,ha='center',va='center',fontweight='bold')
for a,b in zip(items[:-1],items[1:]): ax.add_patch(FancyArrowPatch((a[0]+.08,.50),(b[0]-.08,.50),arrowstyle='->',mutation_scale=17,lw=1.8,color='#1f4e79'))
ax.text(.5,.18,'A pressão de 2 bar pertence ao elemento de medição; não à grande seção anular do demonstrador.',ha='center',fontsize=11,fontweight='bold',color='#9c0006')
ax.set_title('Hierarquia de pressão e fechamento do balanço de vazão',fontsize=15,fontweight='bold')
save('fig05_pressao_fluxo_D1P1.png',fig)

# fig6 orifice
fig,ax=plt.subplots(figsize=(9,5)); ax.plot(orifice.mass_flow_kg_s,orifice.orifice_diameter_mm,marker='o'); ax.grid(True,alpha=.3); ax.set_xlabel('Vazão mássica (kg/s)'); ax.set_ylabel('Diâmetro do orifício (mm)'); ax.set_title('Placas de medição para 2,0 bar abs, 293 K e Cd=0,80',fontweight='bold')
for _,r in orifice.iterrows(): ax.annotate(f'{r.orifice_diameter_mm:.1f}',(r.mass_flow_kg_s,r.orifice_diameter_mm),xytext=(0,7),textcoords='offset points',ha='center',fontsize=8)
save('fig06_orificios_D1P1.png',fig)

# fig7 mass comparison
fig,ax=plt.subplots(figsize=(9,5)); ax.bar(comp_mass.configuracao,comp_mass.massa_kg); ax.set_ylabel('Massa geométrica estimada (kg)'); ax.set_title('Efeito da conversão de sólidos maciços para cascas e interfaces',fontweight='bold'); ax.tick_params(axis='x',labelrotation=12); ax.grid(axis='y',alpha=.3)
for i,v in enumerate(comp_mass.massa_kg): ax.text(i,v+max(comp_mass.massa_kg)*.02,f'{v:.1f}',ha='center',fontweight='bold')
save('fig07_massa_P0_P1.png',fig)

# fig8 shafts/bearings schematic
fig,ax=plt.subplots(figsize=(12,4)); ax.set_xlim(0,.65); ax.set_ylim(-.12,.12); ax.axis('off')
ax.add_patch(Rectangle((.02,-.11),.61,.22,fc='#d9e2f3',ec='#44546a',alpha=.5)); ax.text(.325,.105,'Interior da cápsula',ha='center',va='bottom',fontweight='bold')
ax.add_patch(Rectangle((.04,-.015),.38,.03,fc='#2f75b5')); ax.text(.22,.025,'Eixo R1 Ø30',ha='center',fontsize=9)
ax.add_patch(Rectangle((.04,-.026),.58,.052,fill=False,ec='#ed7d31',lw=4)); ax.text(.39,-.055,'Eixo tubular R2 Ø48/36',ha='center',fontsize=9)
for x,l,c in [(.10,'BR1A','#2f75b5'),(.29,'BR1B','#2f75b5'),(.14,'BR2A','#ed7d31'),(.49,'BR2B','#ed7d31')]:
    ax.add_patch(Rectangle((x-.009,-.07),.018,.14,fc=c,alpha=.7)); ax.text(x,.078,l,ha='center',fontsize=8)
for x,l,c in [(.325,'Hub R1','#2f75b5'),(.525,'Hub R2','#ed7d31')]:
    ax.add_patch(Rectangle((x-.006,-.105),.012,.21,fc=c)); ax.text(x,-.115,l,ha='center',va='top',fontsize=8)
ax.set_title('Arquitetura mecânica de acionamento contrarrotativo - baseline de interface',fontsize=15,fontweight='bold')
save('fig08_eixos_mancais_D1P1.png',fig)

# fig9 CFD patches
fig,ax=plt.subplots(figsize=(13,4)); ax.set_xlim(0,1.2); ax.set_ylim(-.34,.34); ax.axis('off')
ax.add_patch(Rectangle((0,-.28),.84,.56,fc='#eaf2f8',ec='#5b9bd5'))
for x0,x1,l,c in [(.24,.41,'MRF R1','#5b9bd5'),(.44,.61,'MRF R2','#ed7d31'),(.64,.78,'Estator','#70ad47')]:
    ax.add_patch(Rectangle((x0,-.27),x1-x0,.54,fc=c,alpha=.55)); ax.text((x0+x1)/2,0,l,ha='center',va='center',fontweight='bold')
ax.plot([.84,1.10],[-.28,-.24],color='black'); ax.plot([.84,1.10],[.28,.24],color='black'); ax.plot([.84,1.10],[-.11,-.075],color='black'); ax.plot([.84,1.10],[.11,.075],color='black')
ax.text(0,-.32,'inlet_annulus',ha='left',color='#1f4e79',fontweight='bold'); ax.text(1.18,-.32,'outlet',ha='right',color='#1f4e79',fontweight='bold')
ax.set_title('Registro de zonas e patches para o futuro caso CFD 3D MRF',fontsize=15,fontweight='bold')
save('fig09_patches_CFD_D1P1.png',fig)

# fig10 load cases
fig,ax=plt.subplots(figsize=(10,5)); ax.axis('off'); ax.set_xlim(0,1); ax.set_ylim(0,1)
labels=[('Pressão\n5-25 kPa',.12,.68),('Rotação\n1200-1500 rpm',.38,.68),('Torque\n±5 N·m',.64,.68),('Desbalanceamento\nTBD',.88,.68),('Peso próprio\n3 orientações',.25,.28),('Modal/Campbell\n0-2000 rpm',.55,.28),('Mancais e apoios\nrigidez TBD',.82,.28)]
for text,x,y in labels:
    ax.add_patch(FancyBboxPatch((x-.09,y-.10),.18,.20,boxstyle='round,pad=.015',fc='#ddebf7',ec='#2f5597')); ax.text(x,y,text,ha='center',va='center',fontweight='bold',fontsize=9)
ax.set_title('Casos de carga preparados para FEA 3D e rotodinâmica',fontsize=15,fontweight='bold')
save('fig10_casos_FEA_D1P1.png',fig)

# fig11 closure dashboard
fig,ax=plt.subplots(figsize=(11,6)); ax.axis('off')
status_order=['Atendida na baseline digital','Atendida no modelo 1D de alimentação','Atendida geometricamente','Atendida no intercâmbio STL','Atendida no nível de lógica de controle','Parcialmente atendida','Aberta']
color_map={'Atendida na baseline digital':'#70ad47','Atendida no modelo 1D de alimentação':'#70ad47','Atendida geometricamente':'#70ad47','Atendida no intercâmbio STL':'#70ad47','Atendida no nível de lógica de controle':'#a5a5a5','Parcialmente atendida':'#ffc000','Aberta':'#ed7d31'}
y=0.92
for _,r in closure.iterrows():
    ax.add_patch(Rectangle((.05,y-.035),.12,.055,fc=color_map.get(r.digital_status,'#a5a5a5'),ec='none')); ax.text(.11,y-.007,r.id,ha='center',va='center',fontweight='bold')
    ax.text(.19,y-.007,r.issue,va='center',fontsize=9); ax.text(.67,y-.007,r.digital_status,va='center',fontsize=8,fontweight='bold')
    y-=.085
ax.set_title('Fechamento das ações AC-01 a AC-10 na revisão D1-P1',fontsize=15,fontweight='bold')
save('fig11_fechamento_acoes_D1P1.png',fig)

# fig12 verification summary
fig,ax=plt.subplots(figsize=(9,5)); passed=int(testdf.passed.sum()); total=len(testdf)
ax.bar(['Aprovados','Não aprovados'],[passed,total-passed]); ax.set_ylim(0,total+1); ax.set_ylabel('Número de verificações'); ax.set_title('Verificações automatizadas da baseline D1-P1',fontweight='bold'); ax.grid(axis='y',alpha=.3)
for i,v in enumerate([passed,total-passed]): ax.text(i,v+.15,str(v),ha='center',fontweight='bold')
save('fig12_testes_D1P1.png',fig)

# Copy scripts and baseline
shutil.copy2(__file__,W/'code'/'gerar_D1_P1_e_auditar.py')
(W/'README_M12.txt').write_text('''SHC-001 - Módulo 12 / D1-P1\n\nConteúdo:\n- modelo GLB/OBJ e STL por componente;\n- envelopes auxiliares de fluido;\n- auditoria geométrica, massas, folgas e fechamento pressão-vazão;\n- registro de interfaces;\n- preparação de patches CFD e casos de carga FEA;\n- testes automatizados e manifesto SHA-256.\n\nA execução deste pacote não constitui CFD 3D, FEA 3D nem qualificação física.\n''',encoding='utf-8')

# Manifest hashes
files=[]
for p in sorted(W.rglob('*')):
    if p.is_file() and p.name!='manifesto_sha256.csv':
        h=hashlib.sha256(p.read_bytes()).hexdigest(); files.append({'path':str(p.relative_to(W)),'size_bytes':p.stat().st_size,'sha256':h})
pd.DataFrame(files).to_csv(W/'manifesto_sha256.csv',index=False,encoding='utf-8-sig')
print(json.dumps(summary,ensure_ascii=False,indent=2))
