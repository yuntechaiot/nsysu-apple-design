"""使用本次專用本機伺服器做瀏覽器測試，不接管既有連接埠。"""
from pathlib import Path
import os
import runpy
import socket
import sys
import threading
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
NS = ROOT
sys.path.insert(0, str(NS / 'backend'))
sys.path.insert(0, str(NS))
from run_nsysu import main


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


os.chdir(NS)
diary, dashboard = port(), port()
while dashboard == diary:
    dashboard = port()
os.environ.update(VTCA_HOST='127.0.0.1', VTCA_PORT=str(diary), VTCA_DASHBOARD_HOST='127.0.0.1',
                  VTCA_DASHBOARD_PORT=str(dashboard), VTCA_DASHBOARD_URL=f'http://127.0.0.1:{dashboard}/',
                  VTCA_DIARY_URL=f'http://127.0.0.1:{diary}/',
                  NSYSU_TEST_BASE_URL=f'http://127.0.0.1:{diary}',
                  NSYSU_TEST_DASHBOARD_URL=f'http://127.0.0.1:{dashboard}')
stop = threading.Event()
errors = []


def serve():
    try:
        main(stop)
    except BaseException as error:
        errors.append(error)


worker = threading.Thread(target=serve, daemon=True)
worker.start()
try:
    deadline = time.monotonic() + 50
    while True:
        if errors:
            raise errors[0]
        try:
            with urlopen(f'http://127.0.0.1:{diary}/health', timeout=.5) as response:
                if response.status == 200:
                    break
        except OSError:
            pass
        if time.monotonic() > deadline:
            raise RuntimeError('測試服務啟動逾時')
        time.sleep(.2)
    runpy.run_path(str(NS / 'tools/browser_check.py'), run_name='__main__')
finally:
    stop.set()
    worker.join(timeout=15)
if errors:
    raise errors[0]
