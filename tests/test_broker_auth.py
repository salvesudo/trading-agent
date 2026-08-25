import os

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/test")

import pytest

from app.broker.auth import FyersAuthManager, TokenResult, extract_auth_code, update_env_file
from app.broker.models import BrokerError


def test_extract_auth_code_from_bare_code():
    assert extract_auth_code("abc123") == "abc123"


def test_extract_auth_code_from_full_redirect_url():
    url = "https://example.com/callback?s=ok&code=200&auth_code=abc.def-123&state=fyers_agent"
    assert extract_auth_code(url) == "abc.def-123"


def test_manager_requires_all_credentials():
    with pytest.raises(BrokerError):
        FyersAuthManager(app_id="", secret_id="secret", redirect_uri="https://x/cb")
    with pytest.raises(BrokerError):
        FyersAuthManager(app_id="APPID-100", secret_id="", redirect_uri="https://x/cb")
    with pytest.raises(BrokerError):
        FyersAuthManager(app_id="APPID-100", secret_id="secret", redirect_uri="")


def test_login_url_is_built_locally_without_network(monkeypatch):
    manager = FyersAuthManager(app_id="APPID-100", secret_id="secret", redirect_uri="https://x/cb")
    url = manager.login_url()
    assert url.startswith("https://api-t1.fyers.in/api/v3/generate-authcode?")
    assert "client_id=APPID-100" in url
    assert "response_type=code" in url


def test_exchange_auth_code_rejects_empty_code():
    manager = FyersAuthManager(app_id="APPID-100", secret_id="secret", redirect_uri="https://x/cb")
    with pytest.raises(BrokerError):
        manager.exchange_auth_code("")


def test_exchange_auth_code_success(monkeypatch):
    import fyers_apiv3.fyersModel as fyers_model_module

    class FakeResponse:
        def json(self):
            return {"s": "ok", "access_token": "tok_abc123"}

    monkeypatch.setattr(fyers_model_module.requests, "post", lambda *a, **k: FakeResponse())

    manager = FyersAuthManager(app_id="APPID-100", secret_id="secret", redirect_uri="https://x/cb")
    result = manager.exchange_auth_code("some-auth-code")
    assert isinstance(result, TokenResult)
    assert result.access_token == "tok_abc123"


def test_exchange_auth_code_failure_raises_broker_error(monkeypatch):
    import fyers_apiv3.fyersModel as fyers_model_module

    class FakeResponse:
        def json(self):
            return {"s": "error", "message": "invalid appIdHash"}

    monkeypatch.setattr(fyers_model_module.requests, "post", lambda *a, **k: FakeResponse())

    manager = FyersAuthManager(app_id="APPID-100", secret_id="secret", redirect_uri="https://x/cb")
    with pytest.raises(BrokerError, match="invalid appIdHash"):
        manager.exchange_auth_code("some-auth-code")


def test_update_env_file_appends_missing_key(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("TRADING_MODE=PAPER\nSTOP_TRADING=false\n", encoding="utf-8")

    update_env_file(env_path, "FYERS_ACCESS_TOKEN", "tok_new")

    content = env_path.read_text(encoding="utf-8")
    assert "FYERS_ACCESS_TOKEN=tok_new" in content
    assert "TRADING_MODE=PAPER" in content


def test_update_env_file_replaces_existing_key(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("TRADING_MODE=PAPER\nFYERS_ACCESS_TOKEN=old_token\n", encoding="utf-8")

    update_env_file(env_path, "FYERS_ACCESS_TOKEN", "tok_new")

    lines = env_path.read_text(encoding="utf-8").splitlines()
    assert lines.count("FYERS_ACCESS_TOKEN=tok_new") == 1
    assert "FYERS_ACCESS_TOKEN=old_token" not in lines


def test_update_env_file_creates_file_if_missing(tmp_path):
    env_path = tmp_path / ".env"
    update_env_file(env_path, "FYERS_ACCESS_TOKEN", "tok_first")
    assert env_path.read_text(encoding="utf-8").strip() == "FYERS_ACCESS_TOKEN=tok_first"
