# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import datetime
import folium
from streamlit_folium import st_folium
import openmeteo_requests
import requests_cache
from retry_requests import retry

# 1. SETUP DA PÁGINA E API
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
        # Lista de estilos (um para cada coluna)
        styles = [''] * len(row)
        
        # Índices das colunas
        cols = list(row.index)
        idx_ar = cols.index("Ar (°C)")
        idx_orvalho = cols.index("Orvalho (°C)")
        idx_sst = cols.index("SST (°C)")
        
        # 1. Lógica de Nevoeiro (Diferença Ar/Orvalho)
        diff = abs(row["Ar (°C)"] - row["Orvalho (°C)"])
        if diff < 0.5:
            color = 'background-color: #ff4b4b; color: white' # Vermelho
            styles[idx_ar] = color
            styles[idx_orvalho] = color
        elif 0.5 <= diff <= 2.0:
            color = 'background-color: #f1c40f; color: black' # Amarelo
            styles[idx_ar] = color
            styles[idx_orvalho] = color
            
        # 2. Lógica SST < Orvalho (Muro de Nevoeiro Marítimo)
        if row["SST (°C)"] < row["Orvalho (°C)"]:
            color_sst = 'background-color: #e67e22; color: white; font-weight: bold' # Laranja
            styles[idx_sst] = color_sst
            styles[idx_orvalho] = color_sst
            
        return styles

    return df.style.apply(apply_styles, axis=1).format(precision=1)

@st.cache_data(show_spinner=False)
def fetch_data(lat, lon, date_obj):
    date_str = date_obj.strftime('%Y-%m-%d')
    try:
        w_url = "https://api.open-meteo.com/v1/forecast"
        w_params = {
            "latitude": lat, "longitude": lon,
            "hourly": ["temperature_2m", "dew_point_2m", "wind_speed_10m", "wind_direction_10m", "wet_bulb_temperature_2m"],
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

        df_res = pd.DataFrame({
            "Hora": pd.date_range(
                start=pd.to_datetime(wh.Time() + w_resp.UtcOffsetSeconds(), unit="s"),
                periods=wh.Variables(0).ValuesAsNumpy().shape[0],
                freq=pd.Timedelta(seconds=wh.Interval())
            ).strftime('%H:%M'),
            "Ar (°C)": wh.Variables(0).ValuesAsNumpy(),
            "Orvalho (°C)": wh.Variables(1).ValuesAsNumpy(),
            "Vento_Vel": wh.Variables(2).ValuesAsNumpy(),
            "Vento_Dir": wh.Variables(3).ValuesAsNumpy(),
            "Wet Bulb (°C)": wh.Variables(4).ValuesAsNumpy(),
            "Swell_H": mh.Variables(0).ValuesAsNumpy(),
            "Swell_Dir": mh.Variables(1).ValuesAsNumpy(),
            "Período (s)": mh.Variables(2).ValuesAsNumpy(),
            "SST (°C)": mh.Variables(3).ValuesAsNumpy(),
            "Maré (m)": mh.Variables(4).ValuesAsNumpy()
        })
        
        # CÁLCULO DA ENERGIA (H^2 * T)
        df_res['Energia (kJ)'] = (df_res['Swell_H']**2) * df_res['Período (s)']
        return df_res
        
    except Exception as e:
        st.error(f"Erro na API: {e}")
        return None

# 3. ESTADO DA SESSÃO
if 'lat' not in st.session_state: st.session_state.lat = 41.1894
if 'lon' not in st.session_state: st.session_state.lon = -8.7171
if 'map_center' not in st.session_state: st.session_state.map_center = [41.1894, -8.7171]
if 'map_zoom' not in st.session_state: st.session_state.map_zoom = 12
if 'df' not in st.session_state: st.session_state.df = None

# 4. INTERFACE
st.title("🌊 Surf & Fog Forecast")

col1, col2 = st.columns([1, 2.5])

with col1:
    st.subheader("Mapa")
    data_sel = st.date_input("Data", datetime.date.today())
    
    m = folium.Map(location=st.session_state.map_center, zoom_start=st.session_state.map_zoom, tiles=None)
    folium.TileLayer(tiles='https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', attr='Googlehttp://googleusercontent.com/image_generation_content/0
