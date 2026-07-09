import json
import re

import pytest

from dida_v2_client.auth import DidaAuthError, direct_signon_login, resolve_session_token


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_env_session_token_is_fallback(monkeypatch):
    monkeypatch.setenv("DIDA_SESSION_TOKEN", "TOKEN")
    assert resolve_session_token(headless=False) == "TOKEN"


def test_headless_callback_can_be_injected(monkeypatch):
    monkeypatch.delenv("DIDA_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("TICKTICK_SESSION_TOKEN", raising=False)
    calls = []

    def fake_headless(**kwargs):
        calls.append(kwargs)
        return "HEADLESS_TOKEN"

    assert resolve_session_token(headless_login=fake_headless) == "HEADLESS_TOKEN"
    assert calls and calls[0]["profile"] == "cn"


def test_direct_signon_login_posts_to_dida_v2(monkeypatch):
    monkeypatch.setenv("DIDA_EMAIL", "user@example.com")
    monkeypatch.setenv("DIDA_PASSWORD", "local-password")
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        seen["body"] = json.loads(request.data.decode())
        seen["headers"] = dict(request.header_items())
        return FakeResponse({"token": "SESSION_TOKEN"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert direct_signon_login(profile="dida", timeout=7) == "SESSION_TOKEN"
    assert seen["url"] == "https://api.dida365.com/api/v2/user/signon?wc=true&remember=true"
    assert seen["timeout"] == 7
    assert seen["body"] == {"username": "user@example.com", "password": "local-password"}
    assert seen["headers"]["Origin"] == "https://dida365.com"
    x_device = json.loads(seen["headers"]["X-device"])
    assert x_device["id"] == "6790a0b0c1d2e3f4a5b6c7d8"
    assert re.fullmatch(r"[0-9a-f]{24}", x_device["id"])


def test_direct_signon_rejects_invalid_device_id(monkeypatch):
    monkeypatch.setenv("DIDA_EMAIL", "user@example.com")
    monkeypatch.setenv("DIDA_PASSWORD", "local-password")
    monkeypatch.setenv("DIDA_DEVICE_ID", "not-a-hex-device-id")

    with pytest.raises(DidaAuthError, match="24-character hex"):
        direct_signon_login()


def test_direct_signon_requires_local_credentials(monkeypatch):
    monkeypatch.delenv("DIDA_EMAIL", raising=False)
    monkeypatch.delenv("DIDA_PASSWORD", raising=False)
    monkeypatch.delenv("TICKTICK_EMAIL", raising=False)
    monkeypatch.delenv("TICKTICK_PASSWORD", raising=False)

    with pytest.raises(DidaAuthError, match="local env credentials"):
        direct_signon_login()


def test_resolve_session_uses_direct_signon_before_env_fallback(monkeypatch):
    monkeypatch.setenv("DIDA_SESSION_TOKEN", "FALLBACK")

    def fake_direct(**kwargs):
        return "DIRECT_TOKEN"

    def fail_selenium(**kwargs):  # pragma: no cover - should not be called
        raise AssertionError("selenium should not run after direct sign-on succeeds")

    monkeypatch.setattr("dida_v2_client.auth.direct_signon_login", fake_direct)
    monkeypatch.setattr("dida_v2_client.auth.selenium_headless_login", fail_selenium)

    assert resolve_session_token() == "DIRECT_TOKEN"


def test_resolve_session_reports_login_failures_when_no_token_fallback(monkeypatch):
    monkeypatch.delenv("DIDA_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("TICKTICK_SESSION_TOKEN", raising=False)

    def fail_direct(**kwargs):
        raise DidaAuthError("direct boom")

    def fail_selenium(**kwargs):
        raise DidaAuthError("selenium boom")

    monkeypatch.setattr("dida_v2_client.auth.direct_signon_login", fail_direct)
    monkeypatch.setattr("dida_v2_client.auth.selenium_headless_login", fail_selenium)

    with pytest.raises(DidaAuthError) as excinfo:
        resolve_session_token()
    message = str(excinfo.value)
    assert "Could not resolve v2 session token" in message
    assert "direct sign-on: direct boom" in message
    assert "selenium fallback: selenium boom" in message
