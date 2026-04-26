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



# Cache configuration for performance

cache_session = requests_cache.CachedSession('.cache', expire_after=3600)

retry_session = retry(cache_session, retries=5)

openmeteo = openmeteo_requests.Client(session=retry_session)



# 2. FUNÇÕES AUXILIARES

def get_arrow(deg):

    if pd.isna(deg): return "-"

    arrows = ['↓', '↙', '←', '↖', '↑', '↗', '→', '↘']

    idx = int((deg + 22.5) % 360 // 45)

    return arrows[idx]

def style_forecast(df):
    def apply_styles(row):
        styles = [''] * len(row)
        cols = list(row.index)
        
        idx_ar = cols.index("Ar (°C)")
        idx_orvalho = cols.index("Orvalho (°C)")
        idx_sst = cols.index("SST (°C)")
        idx_vis = cols.index("Visibilidade (km)")
        
        diff = abs(row["Ar (°C)"] - row["Orvalho (°C)"])
        vis = row["Visibilidade (km)"]
        
        # 1. Alerta por proximidade (Física do Ar)
        if diff < 0.5:
            styles[idx_ar] = styles[idx_orvalho] = 'background-color: #ff4b4b; color: white'
        elif 0.5 <= diff <= 2.0:
            styles[idx_ar] = styles[idx_orvalho] = 'background-color: #f1c40f; color: black'
            
        # 2. Alerta pelo dado da API (Distância de Visão)
        if vis < 1.0: # Menos de 1km
            styles[idx_vis] = 'background-color: #ff4b4b; color: white; font-weight: bold'
        elif 1.0 <= vis <= 5.0: # Entre 1km e 5km
            styles[idx_vis] = 'background-color: #f1c40f; color: black'
            
        # 3. Lógica SST < Orvalho (O teu alerta de "Muro")
        if row["SST (°C)"] < row["Orvalho (°C)"]:
            styles[idx_sst] = styles[idx_orvalho] = 'background-color: #e67e22; color: white'
            
        return styles

    return df.style.apply(apply_styles, axis=1).format(precision=1)



@st.cache_data(show_spinner=False) # Optimized for Cloud: Caches results to save API calls

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



        return pd.DataFrame({

            "Hora": pd.date_range(

                start=pd.to_datetime(wh.Time() + w_resp.UtcOffsetSeconds(), unit="s"),

                periods=wh.Variables(0).ValuesAsNumpy().shape[0],

                freq=pd.Timedelta(seconds=wh.Interval())

            ).strftime('%H:%M'),

            "Ar (°C)": wh.Variables(0).ValuesAsNumpy(),

            "Orvalho (°C)": wh.Variables(1).ValuesAsNumpy(),
            
            "Visibilidade (km)": wh.Variables(5).ValuesAsNumpy() / 1000.0, # Converte metros para km

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

st.title("🌊 Surf forecast")



col1, col2 = st.columns([1, 2])



with col1:

    st.subheader("Mapa")

    data_sel = st.date_input("Data", datetime.date.today())

    

    if 'selected_row_idx' not in st.session_state:

        st.session_state.selected_row_idx = [0] 



    # MAP CONFIGURATION

    # We set tiles=None so we can manually define the order and names of layers

    m = folium.Map(

        location=st.session_state.map_center, 

        zoom_start=st.session_state.map_zoom,

        control_scale=True,

        tiles=None 

    )



    # 1. Google Hybrid (Satellite + Place Names) - Set as DEFAULT

    google_hybrid = 'https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}'

    folium.TileLayer(

        tiles=google_hybrid,

        attr='Google',

        name='Satélite (Híbrido)',

        overlay=False,

        control=True,

        show=True  # This makes it the default visible layer

    ).add_to(m)

    

    # 2. Standard Streets (Optional backup)

    folium.TileLayer(

        'openstreetmap', 

        name='Mapa de Ruas',

        overlay=False,

        control=True,

        show=False

    ).add_to(m)



    folium.LayerControl().add_to(m)



    # ARROW LOGIC

    row_to_show = None

    if 'data_table' in st.session_state and st.session_state.data_table.get("selection", {}).get("rows"):

        st.session_state.selected_row_idx = st.session_state.data_table["selection"]["rows"]

    

    if st.session_state.df is not None and st.session_state.selected_row_idx:

        idx = st.session_state.selected_row_idx[0]

        row_to_show = st.session_state.df.iloc[idx]



    if row_to_show is not None:

        swell_to = (row_to_show['Swell_Dir'] + 180) % 360

        wind_to = (row_to_show['Vento_Dir'] + 180) % 360

        

        swell_label = f"{row_to_show['Swell_H']:.1f}m {int(row_to_show['Período (s)'])}s"

        swell_html = f"""

            <svg width="100" height="100" viewBox="0 0 100 100" style="overflow: visible;">

                <g transform="rotate({swell_to}, 50, 0)">

                    <path d="M 50,0 L 70,25 L 60,25 L 60,90 L 40,90 L 40,25 L 30,25 Z" 

                          fill="blue" stroke="white" stroke-width="1.5"/>

                    <text x="50" y="58" font-family="Arial" font-size="12" fill="white" font-weight="bold" 

                          text-anchor="middle" transform="rotate(-90, 50, 58)">{swell_label}</text>

                </g>

            </svg>

        """

        

        wind_label = f"{row_to_show['Vento_Vel']:.0f}km/h"

        wind_html = f"""

            <svg width="100" height="100" viewBox="0 0 100 100" style="overflow: visible;">

                <g transform="rotate({wind_to}, 50, 0)">

                    <path d="M 50,0 L 62,20 L 55,20 L 55,75 L 45,75 L 45,20 L 38,20 Z" 

                          fill="#2ecc71" stroke="white" stroke-width="1"/>

                    <text x="50" y="48" font-family="Arial" font-size="10" fill="white" font-weight="bold" 

                          text-anchor="middle" transform="rotate(-90, 50, 48)">{wind_label}</text>

                </g>

            </svg>

        """



        folium.Marker([st.session_state.lat, st.session_state.lon],

                      icon=folium.DivIcon(html=swell_html, icon_anchor=(50, 0))).add_to(m)

        folium.Marker([st.session_state.lat, st.session_state.lon],

                      icon=folium.DivIcon(html=wind_html, icon_anchor=(50, 0))).add_to(m)

    else:

        folium.CircleMarker([st.session_state.lat, st.session_state.lon], radius=6, color="red", fill=True).add_to(m)



    m.add_child(folium.LatLngPopup())



    map_output = st_folium(

        m, 

        key="mapa_surf_v6",

        height=500, width=700,

        returned_objects=["last_clicked", "zoom"] 

    )

    

    if map_output and map_output.get('last_clicked'):

        lc = map_output['last_clicked']

        if (abs(lc['lat'] - st.session_state.lat) > 0.0001):

            st.session_state.lat = lc['lat']

            st.session_state.lon = lc['lng']

            st.session_state.map_center = [lc['lat'], lc['lng']]

            if map_output.get('zoom') is not None:

                st.session_state.map_zoom = map_output['zoom']

            st.session_state.df = fetch_data(st.session_state.lat, st.session_state.lon, data_sel)

            st.rerun()



with col2:

    st.subheader("Dados")

    current_loc_key = f"{st.session_state.lat}_{st.session_state.lon}_{data_sel}"

    

    if 'last_loc_key' not in st.session_state or st.session_state.last_loc_key != current_loc_key:

        with st.spinner("A carregar forecast..."):

            st.session_state.df = fetch_data(st.session_state.lat, st.session_state.lon, data_sel)

            st.session_state.last_loc_key = current_loc_key



    if st.session_state.df is not None:

        disp_df = st.session_state.df.copy()

        

        # MODIFIED: Includes degrees in the text labels

        disp_df['Vento'] = disp_df.apply(lambda x: f"{x['Vento_Vel']:.1f} {get_arrow(x['Vento_Dir'])} ({int(x['Vento_Dir'])}°)", axis=1)

        disp_df['Swell'] = disp_df.apply(lambda x: f"{x['Swell_H']:.2f} {get_arrow(x['Swell_Dir'])} ({int(x['Swell_Dir'])}°)", axis=1)

        

        colunas_exibir = [

            "Hora", "Ar (°C)", "Orvalho (°C)", "Wet Bulb (°C)", "Visibilidade (km)",

            "SST (°C)", "Vento", "Swell", "Período (s)", "Maré (m)", "Energia (kJ)"

        ]

        styled_df = style_forecast(disp[colunas_exibir])

        

        st.dataframe(

            disp_df[colunas_exibir],

            on_select="rerun",

            selection_mode="single-row",

            key="data_table",

            use_container_width=True,

            height=550

        )

    else:

        st.info("Clica no mapa para carregar os dados de previsão.")
