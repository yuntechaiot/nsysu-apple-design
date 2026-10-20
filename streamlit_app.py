"""GitHub／Streamlit Community Cloud 共用入口。"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'backend'))
from nsysu.cloud import main

if __name__ == '__main__':
    main()
