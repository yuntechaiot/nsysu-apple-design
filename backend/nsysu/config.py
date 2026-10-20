"""本機環境與 Streamlit Secrets；只由明確白名單提供瀏覽器設定。"""
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


def setting(name, default=''):
    load_dotenv(ROOT / '.env')
    try:
        import streamlit as st
        value = st.secrets.get(name)
    except (FileNotFoundError, KeyError):
        value = None
    return str(value if value is not None else os.getenv(name, default)).strip()


def public_url(current_url=None):
    configured = setting('PUBLIC_APP_URL')
    candidate = configured or current_url or 'http://localhost:8501/'
    url = urlsplit(candidate)
    if url.scheme not in ('http', 'https') or not url.netloc or url.username or url.password:
        raise ValueError('PUBLIC_APP_URL 必須為有效 HTTP／HTTPS 網址，且不能含帳密')
    # 查詢參數在各次導覽才加入，避免 QR Code 帶入研究者或歷史頁狀態。
    return urlunsplit((url.scheme, url.netloc, url.path or '/', '', ''))
