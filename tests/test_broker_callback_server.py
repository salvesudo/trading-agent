import os

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/test")

import threading
import time
import urllib.error
import urllib.request

import pytest

from app.broker.callback_server import CallbackServer
from app.broker.models import BrokerError


def test_callback_server_captures_auth_code():
    server = CallbackServer("127.0.0.1", 0, "/fyers/callback")
    result_holder = {}

    def waiter():
        result_holder["code"] = server.wait(timeout_seconds=5)

    thread = threading.Thread(target=waiter)
    thread.start()
    time.sleep(0.1)  # let serve_forever start accepting

    url = f"http://127.0.0.1:{server.port}/fyers/callback?auth_code=abc123&state=fyers_agent"
    with urllib.request.urlopen(url, timeout=5) as response:
        assert response.status == 200

    thread.join(timeout=5)
    assert result_holder["code"] == "abc123"


def test_callback_server_reports_missing_auth_code():
    server = CallbackServer("127.0.0.1", 0, "/fyers/callback")
    result_holder = {}

    def waiter():
        try:
            server.wait(timeout_seconds=5)
        except BrokerError as exc:
            result_holder["error"] = str(exc)

    thread = threading.Thread(target=waiter)
    thread.start()
    time.sleep(0.1)

    url = f"http://127.0.0.1:{server.port}/fyers/callback?error=access_denied"
    try:
        urllib.request.urlopen(url, timeout=5)
    except urllib.error.HTTPError as exc:
        assert exc.code == 400

    thread.join(timeout=5)
    assert "No auth_code" in result_holder["error"]


def test_callback_server_times_out_when_nothing_arrives():
    server = CallbackServer("127.0.0.1", 0, "/fyers/callback")
    with pytest.raises(BrokerError, match="Timed out"):
        server.wait(timeout_seconds=0.3)


def test_callback_server_ignores_requests_to_other_paths():
    server = CallbackServer("127.0.0.1", 0, "/fyers/callback")
    result_holder = {}

    def waiter():
        result_holder["code"] = server.wait(timeout_seconds=5)

    thread = threading.Thread(target=waiter)
    thread.start()
    time.sleep(0.1)

    other_url = f"http://127.0.0.1:{server.port}/unrelated"
    try:
        urllib.request.urlopen(other_url, timeout=5)
    except urllib.error.HTTPError as exc:
        assert exc.code == 404

    correct_url = f"http://127.0.0.1:{server.port}/fyers/callback?auth_code=xyz789"
    with urllib.request.urlopen(correct_url, timeout=5) as response:
        assert response.status == 200

    thread.join(timeout=5)
    assert result_holder["code"] == "xyz789"
