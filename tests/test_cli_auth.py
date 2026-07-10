import json
import urllib.error

import pytest

from dida_v2_client import cli
from dida_v2_client.transport import DidaV2Error, DidaV2HTTPError


class FakeStore:
    def __init__(self, values=None, events=None):
        self.values = dict(values or {})
        self.events = events if events is not None else []

    def get(self, profile):
        self.events.append(("get", profile))
        return self.values.get(profile)

    def set(self, profile, token):
        self.events.append(("set", profile, token))
        self.values[profile] = token

    def delete(self, profile):
        self.events.append(("delete", profile))
        self.values.pop(profile, None)


def install_auth_fakes(monkeypatch, store, *, status_error=None, events=None):
    events = events if events is not None else store.events
    monkeypatch.setattr(cli, "session_store_from_args", lambda args, required=False: store)

    class FakeClient:
        def __init__(self, config, session_token=None):
            self.config = config
            self.session_token = session_token

        def user_status(self):
            events.append(("verify", self.config.profile, self.session_token))
            if status_error is not None:
                raise status_error
            return {"account": "must-not-be-printed"}

    monkeypatch.setattr(cli, "DidaV2Client", FakeClient)


@pytest.mark.parametrize(
    "profile",
    ("dida", "dida365", "cn", "china", "ticktick", "global", "intl", "international"),
)
def test_cli_accepts_every_public_profile_alias(profile):
    args = cli.build_parser().parse_args(["--profile", profile, "auth", "status"])
    assert args.profile == profile


def test_auth_login_validates_before_saving_and_never_prints_token(monkeypatch, capsys):
    events = []
    store = FakeStore(events=events)
    install_auth_fakes(monkeypatch, store, events=events)

    def login(**kwargs):
        events.append(("login", kwargs["profile"]))
        return "NEW_SECRET_TOKEN"

    monkeypatch.setattr(cli, "direct_signon_login", login)
    assert cli.main(["--profile", "dida", "auth", "login"]) == 0
    assert events == [("login", "dida"), ("verify", "dida", "NEW_SECRET_TOKEN"), ("set", "dida", "NEW_SECRET_TOKEN")]
    output = capsys.readouterr().out
    assert "NEW_SECRET_TOKEN" not in output
    assert json.loads(output) == {"profile": "dida", "stored": True, "valid": True}


def test_auth_refresh_failure_preserves_old_token(monkeypatch, capsys):
    store = FakeStore({"dida": "OLD_TOKEN"})
    install_auth_fakes(
        monkeypatch,
        store,
        status_error=DidaV2HTTPError(503, "GET", "/user/status", error_code="user_not_sign_on"),
    )
    monkeypatch.setattr(cli, "direct_signon_login", lambda **_: "NEW_TOKEN")
    assert cli.main(["auth", "refresh"]) == 2
    assert store.values == {"dida": "OLD_TOKEN"}
    error = capsys.readouterr().err
    assert "OLD_TOKEN" not in error
    assert "NEW_TOKEN" not in error
    assert error.strip() == "ERROR: Authentication operation failed."


def test_auth_status_deletes_definitively_invalid_session(monkeypatch, capsys):
    store = FakeStore({"dida": "EXPIRED_TOKEN"})
    install_auth_fakes(
        monkeypatch,
        store,
        status_error=DidaV2HTTPError(401, "GET", "/user/status", error_code="user_not_sign_on"),
    )
    assert cli.main(["auth", "status"]) == 1
    assert store.values == {}
    assert json.loads(capsys.readouterr().out) == {"profile": "dida", "stored": False, "valid": False}


def test_auth_status_deletes_bare_structured_user_not_sign_on(monkeypatch, capsys):
    store = FakeStore({"dida": "EXPIRED_TOKEN"})
    install_auth_fakes(
        monkeypatch,
        store,
        status_error=DidaV2HTTPError(None, "GET", "/user/status", error_code="user_not_sign_on"),
    )

    assert cli.main(["auth", "status"]) == 1
    assert store.values == {}
    assert json.loads(capsys.readouterr().out) == {"profile": "dida", "stored": False, "valid": False}


@pytest.mark.parametrize(
    "status_error",
    [
        DidaV2HTTPError(403, "GET", "/user/status", error_code="user_not_sign_on"),
        DidaV2HTTPError(429, "GET", "/user/status", error_code="user_not_sign_on"),
        DidaV2HTTPError(503, "GET", "/user/status", error_code="user_not_sign_on"),
        DidaV2Error("server echoed STORED_TOKEN"),
        urllib.error.URLError("network echoed STORED_TOKEN"),
        OSError("socket echoed STORED_TOKEN"),
    ],
)
def test_auth_status_keeps_session_on_transient_or_unstructured_failure(monkeypatch, capsys, status_error):
    store = FakeStore({"dida": "STORED_TOKEN"})
    install_auth_fakes(monkeypatch, store, status_error=status_error)
    assert cli.main(["auth", "status"]) == 2
    assert store.values == {"dida": "STORED_TOKEN"}
    error = capsys.readouterr().err
    assert "STORED_TOKEN" not in error
    assert error.strip() == "ERROR: Authentication operation failed."


def test_auth_login_failure_redacts_exception_text(monkeypatch, capsys):
    store = FakeStore()
    install_auth_fakes(monkeypatch, store)
    monkeypatch.setattr(
        cli,
        "direct_signon_login",
        lambda **_: (_ for _ in ()).throw(urllib.error.URLError("PASSWORD_SENTINEL")),
    )

    assert cli.main(["auth", "login"]) == 2
    assert store.values == {}
    error = capsys.readouterr().err
    assert "PASSWORD_SENTINEL" not in error
    assert error.strip() == "ERROR: Authentication operation failed."


def test_auth_logout_only_deletes_selected_profile(monkeypatch, capsys):
    store = FakeStore({"dida": "DIDA_TOKEN", "ticktick": "TICK_TOKEN"})
    install_auth_fakes(monkeypatch, store)
    assert cli.main(["--profile", "ticktick", "auth", "logout"]) == 0
    assert store.values == {"dida": "DIDA_TOKEN"}
    assert json.loads(capsys.readouterr().out) == {"profile": "ticktick", "stored": False, "valid": False}
