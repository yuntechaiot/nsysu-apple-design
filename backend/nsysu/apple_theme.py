"""Presentation for the research workspace; no queries or data changes."""
from pathlib import Path


def apply():
    import streamlit as st
    css = (Path(__file__).resolve().parents[2] / 'frontend/web/apple-dashboard.css').read_text(encoding='utf-8')
    st.markdown('<style>' + css + '</style>', unsafe_allow_html=True)
