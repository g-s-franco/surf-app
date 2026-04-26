# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import datetime
import folium
from streamlit_folium import st_folium
import openmeteo_requests
import requests_cache
from retry_requests import retry

# 1. SETUP
st.set_page_config(page_title="Surf Forecast Pro", layout="wide")

cache_session = requests_cache.CachedSession('.cache', expire_after=3600)
retry_session = retry(cache_session, retries=5)
openmeteo = openmeteo_requests.Client(session=retry_session)

# 2. FUNÇÕES
def get_arrow(deg):
    if pd.isna(deg): return "-"
    arrows = ['↓', '↙', '←', '↖', '↑', '↗', '→', '↘']
    idx = int((deg + 22.5) % 360 // 45)
    return arrows[idx]

def style_forecast(df):
    def apply_styles(row):
        styles = [''] * len(row)
        c = row.index
        # Nevoeiro Ar/Orvalho
        diff = abs(row["Ar (°C)"] - row["Orvalho (°C)"])
        if diff < 0.5:
            styles[c.get_loc("Ar (°C)")] = styles[c.get_loc("Orvalho (°C)")] = 'background-color: #ff4b4b; color: white'
        elif diff <= 2.0:
            styles[c.get_loc("Ar (°C)")] = styles[c.get_loc("Orvalho (°C)")] = 'background-color: #f1c40f; color: black'
        # Muro de Mar (SST)
        if row["SST (°C)"] < row["Orvalho (°C)"]:
            orange = 'background-color: #e67e22; color: white; font-weight: bold'
            styles[c.get_loc("SST (°C)")] = orange
            styles[c.get_loc("Orvalho (°C)")] = orange
        # Visibilidade
        if row["Visibilidade (km)"] < 1.0:
            styles[c.get_loc("Visibilidade (km)")] = 'background-color: #ff4b4b; color: white'
        elif row["Visibilidade (km)"] < 5.0:
            styles[c.get_loc("Visibilidade (km)")] = 'background-color: #f1c40f; color: black'
        return styles
    return df.style.apply(apply_styles, axis=1).format(precision=1)

@st.cache_data(show_spinner=False)
def fetch_data(lat, lon, date_obj):
    date_str = date_obj.strftime('%Y-%m-%d')
    try:
        w_url = "https://api.open-meteo.com/v1/forecast"
        m_url = "https://marine-api.open-meteo.com/v1/marine"
        w_params = {"latitude": lat, "longitude": lon, "hourly": ["temperature_2m", "dew_point_2m", "wind_speed_10m", "wind_direction_10m", "visibility"], "timezone": "auto", "start_date": date_str, "end_date": date_str}
        m_params = {"latitude": lat, "longitude": lon, "hourly": ["swell_wave_height", "swell_wave_direction", "swell_wave_period", "sea_surface_temperature", "sea_level_height_msl"], "timezone": "auto", "start_date": date_str, "end_date": date_str}
        
        w_resp = openmeteo.weather_api(w_url, params=w_params)[0]
        m_resp = openmeteo.weather_api(m_url, params=m_params)[0]
        wh, mh = w_resp.Hourly(), m_resp.Hourly()

        df = pd.DataFrame({
            "Hora": pd.date_range(start=pd.to_datetime(wh.Time() + w_resp.UtcOffsetSeconds(), unit="s"), periods=wh.Variables(0).ValuesAsNumpy().shape[0], freq="H").strftime('%H:%M'),
            "Ar (°C)": wh.Variables(0).ValuesAsNumpy(),
            "Orvalho (°C)": wh.Variables(1).ValuesAsNumpy(),
            "Visibilidade (km)": wh.Variables(4).ValuesAsNumpy() / 1000.0,
            "Vento_Vel": wh.Variables(2).ValuesAsNumpy(),
            "Vento_Dir": wh.Variables(3).ValuesAsNumpy(),
            "Swell_H": mh.Variables(0).ValuesAsNumpy(),
            "Swell_Dir": mh.Variables(1).ValuesAsNumpy(),
            "Período (s)": mh.Variables(2).ValuesAsNumpy(),
            "SST (°C)": mh.Variables(3).ValuesAsNumpy(),
            "Maré (m)": mh.Variables(4).ValuesAsNumpy()
        })
        # Fórmula da Potência: P = 0.5 * H^2 * T
        df['Potência (kW/m)'] = 0.5 * (df['Swell_H']**2) * df['Período (s)']
        return df
    except Exception as e:
        st.error(f"Erro: {e}")
        return None

# 3. INTERFACE
if 'lat' not in st.session_state: st.session_state.lat = 41.1894
if 'lon' not in st.session_state: st.session_state.lon = -8.7171

st.title("🌊 Surf Forecast Inteligente")
col1, col2 = st.columns([1, 2.2])

with col1:
    data_sel = st.date_input("Data", datetime.date.today())
    m = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=13)
    folium.TileLayer('https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', attr='Google', name='Satélite').add_to(m)
    
    # Lógica das Setinhas
    if st.session_state.get('df') is not None:
        sel = st.session_state.get('data_table', {}).get("selection", {}).get("rows", [0])
        row = st.session_state.df.iloc[sel[0] if sel else 0]
        s_to = (row['Swell_Dir'] + 180) % 360
        icon_html = f'''<div style="transform: rotate({s_to}deg); width: 50px; height: 50px;">
                        <svg viewBox="0 0 100 100"><path d="M50 5 L80 40 L60 40 L60 95 L40 95 L40 40 L20 40 Z" fill="blue" stroke="white" stroke-width="2"/></svg>
                        </div>'''
        folium.Marker([st.session_state.lat, st.session_state.lon], icon=folium.DivIcon(html=icon_html)).add_to(m)

    map_out = st_folium(m, height=450, width=400, key="mapa")
    if map_out and map_out.get('last_clicked'):
        st.session_state.lat, st.session_state.lon = map_out['last_clicked']['lat'], map_out['last_clicked']['lng']
        st.session_state.df = fetch_data(st.session_state.lat, st.session_state.lon, data_sel)
        st.rerun()

with col2:
    if st.session_state.get('df') is None:
        st.session_state.df = fetch_data(st.session_state.lat, st.session_state.lon, data_sel)
    
    if st.session_state.df is not None:
        disp = st.session_state.df.copy()
        disp['Vento'] = disp.apply(lambda x: f"{x['Vento_Vel']:.0f} {get_arrow(x['Vento_Dir'])}", axis=1)
        disp['Swell'] = disp.apply(lambda x: f"{x['Swell_H']:.1f}m {get_arrow(x['Swell_Dir'])}", axis=1)
        
        # COLUNAS REATIVADAS: Adicionei "Maré (m)" e corrigi o nome da Energia
        cols = ["Hora", "Visibilidade (km)", "Ar (°C)", "Orvalho (°C)", "SST (°C)", "Vento", "Swell", "Período (s)", "Maré (m)", "Potência (kW/m)"]
        st.dataframe(style_forecast(disp[cols]), on_select="rerun", selection_mode="single-row", key="data_table", use_container_width=True)
