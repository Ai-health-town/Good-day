import streamlit as st
import streamlit.components.v1 as components
from pathlib import Path

st.set_page_config(page_title="G'day — RCM Workspace", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
    <style>
        #MainMenu, header, footer {visibility: hidden;}
        .block-container {padding: 0 !important; max-width: 100% !important;}
        iframe {height: 100vh !important;}
    </style>
""", unsafe_allow_html=True)

html_code = Path("index.html").read_text(encoding="utf-8")
components.html(html_code, height=950, scrolling=True)
