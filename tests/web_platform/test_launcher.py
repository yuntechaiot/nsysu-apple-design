"""Exercise real local processes without changing production data or live ports."""
import socket
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen

import pytest

import run_nsysu as launcher


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def configure(monkeypatch):
    diary, dashboard = free_port(), free_port()
    while dashboard == diary:
        dashboard = free_port()
    monkeypatch.setenv("VTCA_HOST", "127.0.0.1")
    monkeypatch.setenv("VTCA_PORT", str(diary))
    monkeypatch.setenv("VTCA_DASHBOARD_HOST", "127.0.0.1")
    monkeypatch.setenv("VTCA_DASHBOARD_PORT", str(dashboard))
    monkeypatch.setenv("VTCA_DASHBOARD_URL", "http://127.0.0.1:8501/")
    return diary, dashboard


def wait_for_page(url, worker, errors):
    deadline = time.monotonic() + 50
    while time.monotonic() < deadline:
        if errors:
            raise errors[0]
        try:
            with urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return response.read()
        except (OSError, URLError):
            pass
        if not worker.is_alive():
            raise AssertionError("Launcher stopped before its HTTP services became ready")
        time.sleep(0.2)
    raise AssertionError("Timed out waiting for the unified launcher")


def test_one_command_starts_both_services_and_stops_child(monkeypatch):
    diary, dashboard = configure(monkeypatch)
    stop = threading.Event()
    errors = []

    def run():
        try:
            launcher.main(stop)
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        homepage = wait_for_page(f"http://127.0.0.1:{diary}/", worker, errors)
        assert "填寫睡眠日誌".encode() in homepage
        import json
        config = json.loads(wait_for_page(f"http://127.0.0.1:{diary}/api/config", worker, errors))
        assert config['dashboard_url'] == f"http://127.0.0.1:{dashboard}/"
        assert wait_for_page(f"http://127.0.0.1:{dashboard}/_stcore/health", worker, errors) == b'ok'
        assert b'Streamlit' in wait_for_page(config['dashboard_url'], worker, errors)
    finally:
        stop.set()
        worker.join(timeout=15)
    assert not worker.is_alive()
    assert not errors
    for port in (diary, dashboard):
        with pytest.raises(OSError):
            socket.create_connection(('127.0.0.1', port), timeout=0.5)
        launcher.check_port('127.0.0.1', port, '已停止的服務')


def test_occupied_port_is_not_reused_or_stopped(monkeypatch):
    configure(monkeypatch)
    with socket.socket() as existing:
        existing.bind(('127.0.0.1', 0))
        existing.listen()
        port = existing.getsockname()[1]
        monkeypatch.setenv('VTCA_DASHBOARD_PORT', str(port))
        with pytest.raises(RuntimeError, match=str(port)):
            launcher.main()
        with socket.create_connection(('127.0.0.1', port), timeout=0.5):
            pass


def test_dashboard_startup_failure_cleans_up_launched_process(monkeypatch):
    diary, dashboard = configure(monkeypatch)
    processes = []
    popen = launcher.subprocess.Popen

    def spawn(*args, **kwargs):
        child = popen(*args, **kwargs)
        processes.append(child)
        return child

    def fail(*args, **kwargs):
        raise RuntimeError('SYNTHETIC startup failure')

    monkeypatch.setattr(launcher.subprocess, 'Popen', spawn)
    monkeypatch.setattr(launcher, 'wait_for_dashboard', fail)
    with pytest.raises(RuntimeError, match='startup failure'):
        launcher.main()
    assert len(processes) == 1 and processes[0].poll() is not None
    for port in (diary, dashboard):
        with pytest.raises(OSError):
            socket.create_connection(('127.0.0.1', port), timeout=0.5)
