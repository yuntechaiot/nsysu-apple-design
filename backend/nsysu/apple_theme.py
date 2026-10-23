"""Presentation for the research workspace; no queries or data changes."""
from pathlib import Path


def apply():
    import streamlit as st
    web = Path(__file__).resolve().parents[2] / 'frontend/web'
    css = '\n'.join((web / name).read_text(encoding='utf-8')
                    for name in ['apple-dashboard.css', 'responsive-dashboard.css'])
    st.markdown('<style>' + css + '</style>', unsafe_allow_html=True)
