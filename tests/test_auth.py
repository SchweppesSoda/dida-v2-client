import io
import json
import re
import traceback
import urllib.error
from email.message import Message

import pytest

from dida_v2_client import KeyringSessionStore as ExportedKeyringSessionStore
from dida_v2_client import SessionStore as ExportedSessionStore
from dida_v2_client.auth import (
    DidaAuthError,
    KeyringSessionStore,
    SessionStore,
    direct_signon_login,
    resolve_session_token,
)
from dida_v2_client.version import USER_AGENT

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


def test_session_store_types_are_exported():
    assert ExportedSessionStore is SessionStore
    assert ExportedKeyringSessionStore is KeyringSessionStore


class FakeKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, service, username):
        return self.values.get((service, username))

    def set_password(self, service, username, password):
        self.values[(service, username)] = password

    def delete_password(self, service, username):
        self.values.pop((service, username), None)


def test_keyring_session_store_normalizes_profiles_and_supports_crud():
    backend = FakeKeyring()
    store: SessionStore = KeyringSessionStore(backend=backend)

    store.set("cn", "DIDA_TOKEN")
    store.set("global", "TICKTICK_TOKEN")

    assert store.get("dida") == "DIDA_TOKEN"
    assert store.get("ticktick") == "TICKTICK_TOKEN"
    store.delete("dida")
    assert store.get("cn") is None
    assert store.get("ticktick") == "TICKTICK_TOKEN"


def test_keyring_session_store_normalizes_all_public_profile_aliases():
    backend = FakeKeyring()
    store = KeyringSessionStore(backend=backend)

    store.set("china", "DIDA_TOKEN")
    store.set("international", "TICKTICK_TOKEN")

    for alias in ("dida", "dida365", "cn", "china"):
        assert store.get(alias) == "DIDA_TOKEN"
    for alias in ("ticktick", "global", "intl", "international"):
        assert store.get(alias) == "TICKTICK_TOKEN"


def test_keyring_session_store_errors_do_not_echo_tokens():
    class BrokenKeyring(FakeKeyring):
        def set_password(self, service, username, password):
            raise RuntimeError(f"failed for {password}")

    store = KeyringSessionStore(backend=BrokenKeyring())
    secret = "TOP_SECRET_" + "SESSION"

    with pytest.raises(DidaAuthError) as excinfo:
        store.set("dida", secret)
    assert secret not in str(excinfo.value)
    formatted = "".join(traceback.format_exception(excinfo.type, excinfo.value, excinfo.tb))
    assert secret not in formatted


def test_resolve_session_prefers_explicit_token_over_store_env_and_login(monkeypatch):
    monkeypatch.setenv("DIDA_SESSION_TOKEN", "ENV_TOKEN")

    class FailingStore:
        def get(self, profile):
            raise AssertionError("store must not run after explicit token")

    assert (
        resolve_session_token(
            profile="dida",
            session_token="EXPLICIT_TOKEN",
            session_store=FailingStore(),
            headless_login=lambda **_: (_ for _ in ()).throw(AssertionError("login must not run")),
        )
        == "EXPLICIT_TOKEN"
    )


def test_resolve_session_uses_secure_store_before_env_and_login(monkeypatch):
    monkeypatch.setenv("DIDA_SESSION_TOKEN", "ENV_TOKEN")

    class FakeStore:
        def get(self, profile):
            assert profile == "dida"
            return "STORED_TOKEN"

    assert (
        resolve_session_token(
            profile="dida",
            session_store=FakeStore(),
            headless_login=lambda **_: (_ for _ in ()).throw(AssertionError("login must not run")),
        )
        == "STORED_TOKEN"
    )


def test_resolve_session_canonicalizes_profile_before_secure_store(monkeypatch):
    monkeypatch.delenv("DIDA_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("TICKTICK_SESSION_TOKEN", raising=False)
    seen = []

    class FakeStore:
        def get(self, profile):
            seen.append(profile)
            return "STORED_TOKEN"

        def set(self, profile, token):
            raise AssertionError("not used")

        def delete(self, profile):
            raise AssertionError("not used")

    assert resolve_session_token(profile="international", session_store=FakeStore()) == "STORED_TOKEN"
    assert seen == ["ticktick"]


@pytest.mark.parametrize(
    ("profile", "expected_token"),
    [
        ("dida", "DIDA_TOKEN"),
        ("dida365", "DIDA_TOKEN"),
        ("cn", "DIDA_TOKEN"),
        ("china", "DIDA_TOKEN"),
        ("ticktick", "TICKTICK_TOKEN"),
        ("global", "TICKTICK_TOKEN"),
        ("intl", "TICKTICK_TOKEN"),
        ("international", "TICKTICK_TOKEN"),
    ],
)
def test_resolve_session_uses_profile_specific_env_token(monkeypatch, profile, expected_token):
    monkeypatch.setenv("DIDA_SESSION_TOKEN", "DIDA_TOKEN")
    monkeypatch.setenv("TICKTICK_SESSION_TOKEN", "TICKTICK_TOKEN")

    assert resolve_session_token(profile=profile, headless=False) == expected_token


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
    assert calls and calls[0]["profile"] == "dida"


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
    assert seen["headers"]["User-agent"] == USER_AGENT
    x_device = json.loads(seen["headers"]["X-device"])
    assert x_device["id"] == "6790a0b0c1d2e3f4a5b6c7d8"
    assert re.fullmatch(r"[0-9a-f]{24}", x_device["id"])


def test_direct_signon_uses_only_canonical_profile_credentials(monkeypatch):
    monkeypatch.setenv("DIDA_EMAIL", "dida@example.com")
    monkeypatch.setenv("DIDA_PASSWORD", "DIDA_PASSWORD_SENTINEL")
    monkeypatch.setenv("TICKTICK_EMAIL", "ticktick@example.com")
    monkeypatch.setenv("TICKTICK_PASSWORD", "TICKTICK_PASSWORD_SENTINEL")
    seen = []

    def fake_urlopen(request, timeout):
        seen.append((request.full_url, json.loads(request.data.decode())))
        return FakeResponse({"token": "SESSION_TOKEN"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    direct_signon_login(profile="dida")
    direct_signon_login(profile="international")

    assert seen == [
        (
            "https://api.dida365.com/api/v2/user/signon?wc=true&remember=true",
            {"username": "dida@example.com", "password": "DIDA_PASSWORD_SENTINEL"},
        ),
        (
            "https://api.ticktick.com/api/v2/user/signon?wc=true&remember=true",
            {"username": "ticktick@example.com", "password": "TICKTICK_PASSWORD_SENTINEL"},
        ),
    ]


def test_direct_signon_url_error_does_not_echo_credentials(monkeypatch):
    monkeypatch.setenv("DIDA_EMAIL", "user@example.com")
    monkeypatch.setenv("DIDA_PASSWORD", "PASSWORD_SENTINEL")

    def fail_urlopen(request, timeout):
        raise urllib.error.URLError("network failed for PASSWORD_SENTINEL")

    monkeypatch.setattr("urllib.request.urlopen", fail_urlopen)

    with pytest.raises(DidaAuthError) as excinfo:
        direct_signon_login(profile="dida")
    assert "PASSWORD_SENTINEL" not in str(excinfo.value)
    formatted = "".join(traceback.format_exception(excinfo.type, excinfo.value, excinfo.tb))
    assert "PASSWORD_SENTINEL" not in formatted


def test_direct_signon_http_error_is_closed_and_does_not_echo_response(monkeypatch):
    monkeypatch.setenv("DIDA_EMAIL", "user@example.com")
    monkeypatch.setenv("DIDA_PASSWORD", "PASSWORD_SENTINEL")
    body = io.BytesIO(b'{"error":"SERVER_SECRET_SENTINEL"}')

    def fail_urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, "SERVER_SECRET_SENTINEL", Message(), body)

    monkeypatch.setattr("urllib.request.urlopen", fail_urlopen)

    with pytest.raises(DidaAuthError) as excinfo:
        direct_signon_login(profile="dida")
    formatted = "".join(traceback.format_exception(excinfo.type, excinfo.value, excinfo.tb))
    assert "PASSWORD_SENTINEL" not in formatted
    assert "SERVER_SECRET_SENTINEL" not in formatted
    assert body.closed


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


def test_resolve_session_uses_env_session_before_direct_signon(monkeypatch):
    monkeypatch.setenv("DIDA_SESSION_TOKEN", "CACHED_TOKEN")

    def fail_direct(**kwargs):
        raise AssertionError("direct sign-on must not run while an env session exists")

    monkeypatch.setattr("dida_v2_client.auth.direct_signon_login", fail_direct)

    assert resolve_session_token() == "CACHED_TOKEN"


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
    assert "direct boom" not in message
    assert "selenium boom" not in message
    assert "direct sign-on: DidaAuthError" in message
    assert "selenium fallback: DidaAuthError" in message
