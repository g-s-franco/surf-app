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

# 2. FUNÇÕES AUXILIARES
def get_arrow(deg):
    if pd.isna(deg): return "-"
    arrows = ['↓', '↙', '←', '↖', '↑', '↗', '→', '↘']
    idx = int((deg + 22.5) % 360 // 45)
    return arrows[idx]

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

        return pd.DataFrame({
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
    except Exception as e:
        st.error(f"Erro na API: {e}")
        return None

# 3. ESTADO DA SESSÃO (PERSISTÊNCIA)
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
    
    # 1. INICIALIZAÇÃO DE ESTADO
    if 'map_center' not in st.session_state:
        st.session_state.map_center = [41.1894, -8.7171]
        st.session_state.map_zoom = 12
    # Garantimos que existe sempre uma seleção inicial para evitar o pin vermelho
    if 'selected_row_idx' not in st.session_state:
        st.session_state.selected_row_idx = [0] 

    # 2. CONFIGURAÇÃO DO MAPA
    # O segredo: location e zoom_start só são usados na PRIMEIRA vez que o objeto 'm' é criado
    m = folium.Map(
        location=st.session_state.map_center, 
        zoom_start=st.session_state.map_zoom,
        control_scale=True
    )

    # Camadas de visualização (Satélite e Ruas)
    folium.TileLayer('openstreetmap', name='Ruas').add_to(m)
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri', name='Satélite'
    ).add_to(m)
    folium.LayerControl().add_to(m)

    # 3. LÓGICA DE EXIBIÇÃO (SETAS SEMPRE QUE POSSÍVEL)
    # Verificamos se há uma linha selecionada na sessão ou na interface
    row_to_show = None
    
    # Prioridade 1: Seleção manual na tabela
    if 'data_table' in st.session_state and st.session_state.data_table.get("selection", {}).get("rows"):
        st.session_state.selected_row_idx = st.session_state.data_table["selection"]["rows"]
    
    # Se temos um DataFrame e um índice, mostramos as setas
    if st.session_state.df is not None and st.session_state.selected_row_idx:
        idx = st.session_state.selected_row_idx[0]
        row_to_show = st.session_state.df.iloc[idx]

    if row_to_show is not None:
        swell_to = (row_to_show['Swell_Dir'] + 180) % 360
        wind_to = (row_to_show['Vento_Dir'] + 180) % 360
        
        # --- SETA SWELL (AZUL) ---
        swell_label = f"{row_to_show['Swell_H']:.1f}m {int(row_to_show['Período (s)'])}s"
        # O segredo: A rotação é feita no atributo 'transform' do SVG, não na div.
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
        
        # --- SETA VENTO (VERDE) ---
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

        # O ponto (50, 0) do SVG é a ponta da seta. 
        # Ao definir icon_anchor=(50, 0), esse ponto fica colado na latitude/longitude.
        folium.Marker([st.session_state.lat, st.session_state.lon],
                      icon=folium.DivIcon(html=swell_html, icon_anchor=(50, 0))).add_to(m)
        folium.Marker([st.session_state.lat, st.session_state.lon],
                      icon=folium.DivIcon(html=wind_html, icon_anchor=(50, 0))).add_to(m)
    else:
        folium.CircleMarker([st.session_state.lat, st.session_state.lon], radius=6, color="red", fill=True).add_to(m)

    m.add_child(folium.LatLngPopup())

    # 3. RENDERIZAÇÃO COM 'key' ESTÁTICA
    # O key é o que diz ao Streamlit: "Não destruas este mapa, apenas atualiza-o"
    map_output = st_folium(
        m, 
        key="mapa_surf_v6",
        height=500, width=700,
        # Importante: não devolvemos center/zoom se não formos usá-los para "forçar" o mapa
        returned_objects=["last_clicked", "zoom"] 
    )
    
# 4. ATUALIZAÇÃO APENAS NO CLIQUE
    if map_output and map_output.get('last_clicked'):
        lc = map_output['last_clicked']
        # Só atualizamos a coordenada do ponto. O zoom e o centro do mapa 
        # ficam guardados na memória do navegador (client-side) pelo 'key'
        if (abs(lc['lat'] - st.session_state.lat) > 0.0001):
            st.session_state.lat = lc['lat']
            st.session_state.lon = lc['lng']
            # ATUALIZA O CENTRO DO MAPA (Para ele centrar no novo ponto)
            st.session_state.map_center = [lc['lat'], lc['lng']]
            
            # 2. O SEGREDO: Captura o zoom atual do mapa antes de reiniciar
            # Se o utilizador fez zoom-in, map_output['zoom'] terá o valor novo
            if map_output.get('zoom') is not None:
                st.session_state.map_zoom = map_output['zoom']
            # Se já tínhamos dados, fazemos o fetch novo ANTES do rerun 
            # para que as setas apareçam logo no ponto novo se houver uma linha selecionada
            st.session_state.df = fetch_data(st.session_state.lat, st.session_state.lon, data_sel)
            st.rerun()

with col2:
    st.subheader("Dados")
    
    # --- ATUALIZAÇÃO AUTOMÁTICA ---
    # Criamos uma chave baseada na localização e data para saber se precisamos de novos dados
    current_loc_key = f"{st.session_state.lat}_{st.session_state.lon}_{data_sel}"
    
    if 'last_loc_key' not in st.session_state or st.session_state.last_loc_key != current_loc_key:
        with st.spinner("A carregar forecast..."):
            # Chama a função que já configuraste com Dew Point (índice 1)
            st.session_state.df = fetch_data(st.session_state.lat, st.session_state.lon, data_sel)
            st.session_state.last_loc_key = current_loc_key

    # --- EXIBIÇÃO DOS DADOS ---
    if st.session_state.df is not None:
        # Criamos uma cópia para formatar as strings de Vento e Swell (com as setas de texto)
        disp_df = st.session_state.df.copy()
        
        # Formatação das colunas combinadas (Velocidade + Seta)
        disp_df['Vento'] = disp_df.apply(lambda x: f"{x['Vento_Vel']:.1f} {get_arrow(x['Vento_Dir'])}", axis=1)
        disp_df['Swell'] = disp_df.apply(lambda x: f"{x['Swell_H']:.2f} {get_arrow(x['Swell_Dir'])}", axis=1)
        
        # Seleção e ordem das colunas para a tabela final
        # NOTA: O nome "Orvalho (°C)" deve ser IGUAL ao que está no teu pd.DataFrame
        colunas_exibir = [
            "Hora", 
            "Ar (°C)", 
            "Orvalho (°C)", 
            "Wet Bulb (°C)",
            "SST (°C)",
            "Vento", 
            "Swell", 
            "Período (s)", 
            "Maré (m)"
        ]
        
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