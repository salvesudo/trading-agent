import os

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/test")

from app.core.config import settings
from app.security.compliance import (
    check_algo_permissions_acknowledged,
    check_session_valid,
    check_static_ip,
    run_compliance_check,
)


def _with_setting(name, value):
    """Context-manager-free helper matching this repo's existing test
    style of mutating `settings` directly and restoring it afterwards."""

    class _Ctx:
        def __enter__(self_inner):
            self_inner.original = getattr(settings, name)
            setattr(settings, name, value)
            return self_inner

        def __exit__(self_inner, *exc):
            setattr(settings, name, self_inner.original)

    return _Ctx()


def test_static_ip_missing_configuration_fails():
    with _with_setting("fyers_static_ip", ""):
        result = check_static_ip(ip_fetcher=lambda: "1.2.3.4")
    assert not result.ok
    assert "not set" in result.detail


def test_static_ip_match_passes():
    with _with_setting("fyers_static_ip", "1.2.3.4"):
        result = check_static_ip(ip_fetcher=lambda: "1.2.3.4")
    assert result.ok


def test_static_ip_mismatch_fails():
    with _with_setting("fyers_static_ip", "1.2.3.4"):
        result = check_static_ip(ip_fetcher=lambda: "5.6.7.8")
    assert not result.ok
    assert "5.6.7.8" in result.detail
    assert "1.2.3.4" in result.detail


def test_static_ip_lookup_failure_reported_not_raised():
    def failing_fetcher():
        raise RuntimeError("network unreachable")

    with _with_setting("fyers_static_ip", "1.2.3.4"):
        result = check_static_ip(ip_fetcher=failing_fetcher)
    assert not result.ok
    assert "network unreachable" in result.detail


def test_session_valid_missing_credentials_fails():
    with _with_setting("fyers_app_id", ""), _with_setting("fyers_access_token", ""):
        result = check_session_valid()
    assert not result.ok


def test_session_valid_success():
    with _with_setting("fyers_app_id", "APPID-100"), _with_setting("fyers_access_token", "tok"):
        result = check_session_valid(profile_fetcher=lambda: {"data": {"name": "Test User"}})
    assert result.ok
    assert "Test User" in result.detail


def test_session_valid_profile_call_failure_reported_not_raised():
    def failing_profile():
        raise RuntimeError("invalid token")

    with _with_setting("fyers_app_id", "APPID-100"), _with_setting("fyers_access_token", "tok"):
        result = check_session_valid(profile_fetcher=failing_profile)
    assert not result.ok
    assert "invalid token" in result.detail


def test_algo_permissions_not_acknowledged_by_default():
    with _with_setting("owner_confirmed_algo_permissions", False):
        result = check_algo_permissions_acknowledged()
    assert not result.ok


def test_algo_permissions_acknowledged_when_set():
    with _with_setting("owner_confirmed_algo_permissions", True):
        result = check_algo_permissions_acknowledged()
    assert result.ok


def test_run_compliance_check_aggregates_all_three():
    with (
        _with_setting("fyers_static_ip", "1.2.3.4"),
        _with_setting("fyers_app_id", "APPID-100"),
        _with_setting("fyers_access_token", "tok"),
        _with_setting("owner_confirmed_algo_permissions", True),
    ):
        report = run_compliance_check(
            ip_fetcher=lambda: "1.2.3.4",
            profile_fetcher=lambda: {"data": {"name": "Test User"}},
        )
    assert len(report.checks) == 3
    assert report.all_passed


def test_run_compliance_check_all_passed_false_if_any_check_fails():
    with (
        _with_setting("fyers_static_ip", "1.2.3.4"),
        _with_setting("fyers_app_id", "APPID-100"),
        _with_setting("fyers_access_token", "tok"),
        _with_setting("owner_confirmed_algo_permissions", False),
    ):
        report = run_compliance_check(
            ip_fetcher=lambda: "1.2.3.4",
            profile_fetcher=lambda: {"data": {"name": "Test User"}},
        )
    assert not report.all_passed
