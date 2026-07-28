import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import pydeck as pdk
from pymongo import MongoClient
import urllib.parse
from datetime import datetime, time, timedelta

# ==============================================================================
# 1. CONFIGURAÇÕES INICIAIS
# ==============================================================================
st.set_page_config(
    page_title="Monitoramento Ambiental IoT",
    page_icon="🏭",
    layout="wide"
)

TEMPLATE_GRAFICO = "plotly_dark" 

# --- CONFIGURAÇÃO GEOGRÁFICA (Fixa) ---
COORDENADAS_FIXAS = {
    "Setor Central":           {"lat": -16.6805, "lon": -49.2563},
    "Setor Bueno":             {"lat": -16.6972, "lon": -49.2770},
    "Setor Jaó":               {"lat": -16.6502, "lon": -49.2285},
    "Jardim Goiás":            {"lat": -16.7041, "lon": -49.2386},
    "Setor Norte Ferroviário": {"lat": -16.6595, "lon": -49.2597} 
}

RAIOS_SETORES = {
    "Setor Central": 900, "Setor Bueno": 1300, "Setor Jaó": 1600,     
    "Jardim Goiás": 1100, "Setor Norte Ferroviário": 1000 
}

# ==============================================================================
# 2. CONEXÃO (OTIMIZADA)
# ==============================================================================
@st.cache_resource
def init_connection():
    MONGO_USER = "davi"
    MONGO_PASS = "337766@Go"
    MONGO_CLUSTER = "quality-of-air.0liyr8g.mongodb.net"
    
    username = urllib.parse.quote_plus(MONGO_USER)
    password = urllib.parse.quote_plus(MONGO_PASS)
    uri = f"mongodb+srv://{username}:{password}@{MONGO_CLUSTER}/?retryWrites=true&w=majority"
    return MongoClient(uri)

client = init_connection()

def get_data():
    """
    Busca dados do MongoDB com limite de performance.
    Traz apenas os últimos 15.000 registros para evitar travamento de memória.
    """
    db = client["Monitoramento_do_Ar"]
    coll = db["Leituras_Analiticas"]
    
    # OTIMIZAÇÃO: .sort().limit() é feito no banco, economizando banda e RAM
    cursor = coll.find({}, {'_id': 0}).sort("timestamp", -1).limit(15000)
    data = list(cursor)
    
    df = pd.DataFrame(data)
    
    if not df.empty:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp') # Reordena para cronológico (Plotly gosta assim)
        
        # Garante numérico mas NÃO filtra por lat/lon aqui, pois vamos forçar no mapa
        df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
        df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
        
    return df

# ==============================================================================
# 3. LÓGICA DE CORES E TEXTO
# ==============================================================================
def definir_cor_indicador(valor):
    if valor < 50: return [0, 100, 0, 180]       # Verde Escuro
    elif valor < 75: return [50, 205, 50, 180]   # Verde Claro
    elif valor < 100: return [255, 215, 0, 180]  # Amarelo
    else: return [220, 20, 60, 180]              # Vermelho

def definir_status_texto(valor):
    if valor < 50: return "Excelente"
    elif valor < 75: return "Boa"
    elif valor < 100: return "Moderada"
    else: return "Ruim"

# ==============================================================================
# 4. DASHBOARD
# ==============================================================================

# Botão de refresh manual na sidebar
if st.sidebar.button("🔄 Atualizar Dados"):
    st.cache_data.clear() # Opcional: limpa caches de dados se houver
    st.rerun()

df_raw = get_data()

if df_raw.empty:
    st.error("⚠️ Nenhum dado encontrado. Verifique se o Pipeline (Script 2) está rodando e salvando no Mongo.")
    st.stop()

# --- SIDEBAR: TIMELINE DE DISPONIBILIDADE ---
st.sidebar.markdown("### 📅 Disponibilidade")
st.sidebar.caption("Barras = Dados coletados.")

# Histograma leve para sidebar
df_hist = df_raw.set_index('timestamp').resample('H').size().reset_index(name='count')
df_hist = df_hist[df_hist['count'] > 0]

fig_timeline = px.bar(df_hist, x='timestamp', y='count', color_discrete_sequence=['#00CC96'])

fig_timeline.update_layout(
    plot_bgcolor='rgba(0,0,0,0)', 
    paper_bgcolor='rgba(0,0,0,0)',
    xaxis=dict(showgrid=False, title=None, tickformat="%d/%m", nticks=4, tickfont=dict(size=10, color='gray')),
    yaxis=dict(showgrid=False, showticklabels=False, title=None),
    margin=dict(l=0, r=0, t=0, b=20), 
    height=80, 
    showlegend=False,
    dragmode='select', 
    selectdirection='h'
)
fig_timeline.update_traces(hovertemplate='<b>%{x|%d/%m %H:%M}</b><br>Leituras: %{y}<extra></extra>')

selection = st.sidebar.plotly_chart(fig_timeline, use_container_width=True, config={'displayModeBar': False}, on_select="rerun")

# --- FILTROS DE TEMPO ---
st.sidebar.markdown("### 🕒 Intervalo")

# Pega data do último dado disponível
data_max_db = df_raw['timestamp'].max().date()
data_min_db = df_raw['timestamp'].min().date()

# Seletor de data
data_selecionada = st.sidebar.date_input("Data:", value=data_max_db, min_value=data_min_db, max_value=data_max_db)

# Slider de hora
hora_inicio, hora_fim = st.sidebar.slider(
    "Horário:",
    value=(time(0, 0), time(23, 59)),
    format="HH:mm",
    step=timedelta(minutes=30) 
)

# Lógica de Filtro (Prioridade: Seleção Gráfica > Slider)
hora_inicio_filtro = datetime.combine(data_selecionada, hora_inicio)
hora_fim_filtro = datetime.combine(data_selecionada, hora_fim)

if (selection and "selection" in selection and "xrange" in selection["selection"] and selection["selection"]["xrange"]):
    x_range = selection["selection"]["xrange"]
    hora_inicio_filtro = pd.to_datetime(x_range[0]).to_pydatetime()
    hora_fim_filtro = pd.to_datetime(x_range[1]).to_pydatetime()
    st.sidebar.success(f"🔎 Zoom: {hora_inicio_filtro.strftime('%H:%M')} - {hora_fim_filtro.strftime('%H:%M')}")

# Aplica filtro
df_time = df_raw[
    (df_raw['timestamp'] >= hora_inicio_filtro) & 
    (df_raw['timestamp'] <= hora_fim_filtro)
]

if df_time.empty:
    st.warning(f"❌ Sem dados para este período ({data_selecionada.strftime('%d/%m')}). Tente expandir o horário.")
    st.stop() 

# Filtro de Local
st.sidebar.markdown("### 📍 Local")
setores = ["Todos"] + list(df_raw['localizacao'].unique())
filtro_local = st.sidebar.selectbox("Bairro:", setores)

if filtro_local != "Todos":
    df_view = df_time[df_time['localizacao'] == filtro_local]
else:
    df_view = df_time

# Legenda Visual (HTML)
st.sidebar.markdown("---")
st.sidebar.caption("Legenda de Qualidade:")
st.sidebar.markdown(
    """
    <div style="background-color: #262730; padding: 10px; border-radius: 5px; font-size: 12px;">
        <div style="margin-bottom: 5px;">🟢 <b>0-50:</b> Excelente</div>
        <div style="margin-bottom: 5px;">🍃 <b>50-75:</b> Boa</div>
        <div style="margin-bottom: 5px;">🟡 <b>75-100:</b> Moderada</div>
        <div>🔴 <b>>100:</b> Ruim/Crítica</div>
    </div>
    """, unsafe_allow_html=True
)

# --- MAPA PREP ---
df_view = df_view.copy()
# Recalcula cores e status baseado no dado filtrado
df_view['color_rgb'] = df_view['carga_poluente'].apply(definir_cor_indicador)
df_view['classificacao_ar'] = df_view['carga_poluente'].apply(definir_status_texto)

# Agrupa pelo último status de cada sensor para mostrar no mapa
df_mapa = df_view.groupby('localizacao').last().reset_index()

# --- AQUI ESTÁ A MUDANÇA ---
# Força o uso das coordenadas FIXAS para visualização, como pedido
df_mapa['latitude'] = df_mapa['localizacao'].map(lambda x: COORDENADAS_FIXAS.get(x, {}).get("lat", -16.68))
df_mapa['longitude'] = df_mapa['localizacao'].map(lambda x: COORDENADAS_FIXAS.get(x, {}).get("lon", -49.26))
# -----------------------------

# Define raio visual (usa dicionário ou default)
df_mapa['raio_visual'] = df_mapa['localizacao'].map(RAIOS_SETORES).fillna(1000)

# --- KPIs ---
st.title("🏭 Qualidade do Ar: Goiânia")
st.caption(f"Visualizando dados de: **{hora_inicio_filtro.strftime('%d/%m %H:%M')}** até **{hora_fim_filtro.strftime('%H:%M')}**")

c1, c2, c3, c4 = st.columns(4)

poluicao_media = df_mapa['carga_poluente'].mean()
c1.metric("Índice Geral (Médio)", f"{poluicao_media:.0f}", delta=f"{100-poluicao_media:.0f} margem", delta_color="normal")

temp_media = df_mapa['temperatura'].mean()
c2.metric("Temperatura", f"{temp_media:.1f}°C")

pm25_medio = df_mapa['pm25'].mean()
c3.metric("PM2.5", f"{pm25_medio:.1f} µg/m³")

# Conta anomalias "Reais" (Ignora desvio estatístico simples, foca em perigo)
anomalias_reais = len(df_view[(df_view['anomalia_detectada'] == True) & (df_view['tipo_anomalia'] != 'Desvio Estatístico')])
c4.metric("Anomalias/Alertas", anomalias_reais, delta_color="inverse")

st.divider()

# --- MAPA 3D (PyDeck) ---
st.subheader("🗺️ Mapa em Tempo Real")
layer_setores = pdk.Layer(
    "ScatterplotLayer",
    data=df_mapa,
    get_position='[longitude, latitude]',
    get_fill_color='color_rgb',
    get_line_color=[255, 255, 255],
    get_line_width=20,              
    get_radius='raio_visual',       
    pickable=True,                  
    opacity=0.8,
    stroked=True,
    filled=True
)

# Centraliza mapa na média dos pontos exibidos
lat_centro = df_mapa['latitude'].mean()
lon_centro = df_mapa['longitude'].mean()

view_state = pdk.ViewState(latitude=lat_centro, longitude=lon_centro, zoom=11.5, pitch=30)

st.pydeck_chart(pdk.Deck(
    map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
    initial_view_state=view_state,
    layers=[layer_setores],
    tooltip={"html": "<b>{localizacao}</b><br/>Índice: {carga_poluente}<br/>Status: {classificacao_ar}<br/>Temp: {temperatura}°C", "style": {"backgroundColor": "#111", "color": "white"}}
))

st.divider()

# --- GRÁFICOS ---
st.subheader("📈 Evolução Temporal e Previsão IA")

fig_line = go.Figure()
# Linha Real
fig_line.add_trace(go.Scatter(
    x=df_view['timestamp'], y=df_view['carga_poluente'], 
    name='Poluição Medida', line=dict(color='#ff4b4b', width=3), mode='lines'
))
# Linha IA (Previsão)
fig_line.add_trace(go.Scatter(
    x=df_view['timestamp'], y=df_view['carga_estimada'], 
    name='IA Esperada (Baseline)', line=dict(color='#00cc96', dash='dot', width=2)
))

fig_line.update_layout(
    template=TEMPLATE_GRAFICO, height=350, hovermode="x unified",
    xaxis_title="Horário", yaxis_title="Índice Unificado",
    legend=dict(orientation="h", y=1.1)
)
st.plotly_chart(fig_line, use_container_width=True)

# --- DETALHAMENTO ---
col_pm, col_gas = st.columns(2)

with col_pm:
    # Agrupa média por local para gráfico de barras limpo
    df_pm = df_view.groupby('localizacao')['pm25'].mean().sort_values().reset_index()
    fig_pm = px.bar(df_pm, x='pm25', y='localizacao', orientation='h',
                    title="Poeira Fina (PM2.5)", labels={'pm25': 'µg/m³', 'localizacao': ''},
                    color='pm25', color_continuous_scale='Blues', template=TEMPLATE_GRAFICO)
    fig_pm.update_layout(coloraxis_showscale=False)
    st.plotly_chart(fig_pm, use_container_width=True)

with col_gas:
    df_gas = df_view.groupby('localizacao')['gases_ppm'].mean().sort_values().reset_index()
    fig_gas = px.bar(df_gas, x='gases_ppm', y='localizacao', orientation='h',
                     title="Gases Tóxicos (MQ-135)", labels={'gases_ppm': 'PPM', 'localizacao': ''},
                     color='gases_ppm', color_continuous_scale='Oranges', template=TEMPLATE_GRAFICO)
    fig_gas.update_layout(coloraxis_showscale=False)
    st.plotly_chart(fig_gas, use_container_width=True)

# --- TABELA DE ANOMALIAS ---
st.subheader("🚨 Histórico de Alertas")
df_anomalias = df_view[
    (df_view['anomalia_detectada'] == True) & 
    (df_view['tipo_anomalia'] != 'Desvio Estatístico')
].sort_values('timestamp', ascending=False)

if not df_anomalias.empty:
    st.dataframe(
        df_anomalias[['timestamp', 'localizacao', 'tipo_anomalia', 'carga_poluente', 'pm25', 'gases_ppm']], 
        use_container_width=True, 
        hide_index=True,
        column_config={
            "timestamp": st.column_config.DatetimeColumn("Horário", format="DD/MM HH:mm"),
            "carga_poluente": st.column_config.NumberColumn("Índice", format="%.0f"),
            "pm25": st.column_config.NumberColumn("PM2.5", format="%.1f"),
            "gases_ppm": st.column_config.NumberColumn("Gases", format="%.0f")
        }
    )
else:
    st.success("✅ Nenhuma anomalia crítica detectada no período selecionado.")