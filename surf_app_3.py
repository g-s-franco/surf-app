# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import datetime
import folium
from streamlit_folium import st_folium
import openmeteo_requests
import requests_cache
from retry_requests import retry

# 1. SETUP DA PÁGINA
st.set_page_config(page_title="Surf forecast", layout="wide")

cache_session = requests_cache.CachedSession('.cache', expire_after=3600)
retry_session = retry(cache_session, retries=5)
openmeteo = openmeteo_requests.Client(session=retry_session)

# 2. FUNÇÕES AUXILIARES E ESTILO
def get_arrow(deg):
    if pd.isna(deg): return "-"
    arrows = ['↓', '↙', '←', '↖', '↑', '↗', '→', '↘']
    idx = int((deg + 22.5) % 360 // 45)
    return arrows[idx]

def style_forecast(df):
    def apply_styles(row):
        styles = [''] * len(row)
        c = row.index
        
        # Lógica Ar vs Orvalho (Nevoeiro por Humidade)
        diff = abs(row["Ar (°C)"] - row["Orvalho (°C)"])
        if diff < 0.5:
            styles[c.get_loc("Ar (°C)")] = styles[c.get_loc("Orvalho (°C)")] = 'background-color: #ff4b4b; color: white'
        elif diff <= 2.0:
            styles[c.get_loc("Ar (°C)")] = styles[c.get_loc("Orvalho (°C)")] = 'background-color: #f1c40f; color: black'
            
        # Lógica SST vs Orvalho (Muro de Nevoeiro no Mar)
        if row["SST (°C)"] < row["Orvalho (°C)"]:
            orange = 'background-color: #e67e22; color: white; font-weight: bold'
            styles[c.get_loc("SST (°C)")] = orange
            styles[c.get_loc("Orvalho (°C)")] = orange

        # Lógica Visibilidade vinda da API
        v = row["Visibilidade (km)"]
        if v < 1.0:
            styles[c.get_loc("Visibilidade (km)")] = 'background-color: #ff4b4b; color: white'
        elif v < 5.0:
            styles[c.get_loc("Visibilidade (km)")] = 'background-color: #f1c40f; color: black'
            
        return styles

    return df.style.apply(apply_styles, axis=1).format(precision=1)

@st.cache_data(show_spinner=False)
def fetch_data(lat, lon, date_obj):
    date_str = date_obj.strftime('%Y-%m-%d')
    try:
        w_url = "https://api.open-meteo.com/v1/forecast"
        w_params = {
            "latitude": lat, "longitude": lon,
            "hourly": ["temperature_2m", "dew_point_2m", "wind_speed_10m", "wind_direction_10m", "wet_bulb_temperature_2m", "visibility"],
            "timezone": "auto", "start_date": date_str, "end_date": date_str
        }
        m_url = "https://marine-api.open-meteo.com/v1/marine"
        m_params = {
            "latitude": lat, "longitude": lon,
            "hourly": ["swell_wave_height", "swell_wave_direction", "swell_wave_period", "sea_surface_temperature", "sea_level_height_msl"],
            "timezone": "auto", "start_date": date_str, "end_date": date_str
        }
        w_resp = openmeteo.weather_api(w_url, params=w_params)[0]
        m_resp = openmeteo.weather_api(m_url, params=m_params)[0]
        wh, mh = w_resp.Hourly(), m_resp.Hourly()

        df = pd.DataFrame({
            "Hora": pd.date_range(
                start=pd.to_datetime(wh.Time() + w_resp.UtcOffsetSeconds(), unit="s"),
                periods=wh.Variables(0).ValuesAsNumpy().shape[0],
                freq=pd.Timedelta(seconds=wh.Interval())
            ).strftime('%H:%M'),
            "Ar (°C)": wh.Variables(0).ValuesAsNumpy(),
            "Orvalho (°C)": wh.Variables(1).ValuesAsNumpy(),
            "Visibilidade (km)": wh.Variables(5).ValuesAsNumpy() / 1000.0,
            "Vento_Vel": wh.Variables(2).ValuesAsNumpy(),
            "Vento_Dir": wh.Variables(3).ValuesAsNumpy(),
            "Swell_H": mh.Variables(0).ValuesAsNumpy(),
            "Swell_Dir": mh.Variables(1).ValuesAsNumpy(),
            "Período (s)": mh.Variables(2).ValuesAsNumpy(),
            "SST (°C)": mh.Variables(3).ValuesAsNumpy(),
            "Maré (m)": mh.Variables(4).ValuesAsNumpy()
        })
        
        # Cálculo da Potência (kW/m) - P ≈ 0.5 * H^2 * T
        df['Energia (kJ)'] = 0.5 * (df['Swell_H']**2) * df['Período (s)']
        return df
        
    except Exception as e:
        st.error(f"Erro na API: {e}")
        return None

# 3. ESTADO DA SESSÃO
if 'lat' not in st.session_state: st.session_state.lat = 41.1894
if 'lon' not in st.session_state: st.session_state.lon = -8.7171
if 'df' not in st.session_state: st.session_state.df = None

# 4. INTERFACE
st.title("🌊 Surf Forecast Inteligente")
col1, col2 = st.columns([1, 2.2])

with col1:
    data_sel = st.date_input("Data", datetime.date.today())
    m = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=12)
    folium.TileLayer('https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', attr='Google', name='Satélite', show=True).add_to(m)
    
    map_output = st_folium(m, height=500, width=450, key="mapa")
    if map_output and map_output.get('last_clicked'):
        lc = map_output['last_clicked']
        st.session_state.lat, st.session_state.lon = lc['lat'], lc['lng']
        st.session_state.df = fetch_data(st.session_state.lat, st.session_state.lon, data_sel)
        st.rerun()

with col2:
    if st.session_state.df is None:
        st.session_state.df = fetch_data(st.session_state.lat, st.session_state.lon, data_sel)
    
    if st.session_state.df is not None:
        # Preparar colunas de visualização
        disp = st.session_state.df.copy()
        disp['Vento'] = disp.apply(lambda x: f"{x['Vento_Vel']:.1f} {get_arrow(x['Vento_Dir'])}", axis=1)
        disp['Swell'] = disp.apply(lambda x: f"{x['Swell_H']:.2f} {get_arrow(x['Swell_Dir'])}", axis=1)
        
        colunas_finais = ["Hora", "Visibilidade (km)", "Ar (°C)", "Orvalho (°C)", "SST (°C)", "Vento", "Swell", "Período (s)", "Energia (kJ)"]
        
        # Criar a tabela estilizada
        styled_df = style_forecast(disp[colunas_finais])
        
        st.dataframe(
            styled_df, # IMPORTANTE: Usar o styled_df e não o disp
            on_select="rerun",
            selection_mode="single-row",
            key="data_table",
            use_container_width=True,
            height=600
        )
