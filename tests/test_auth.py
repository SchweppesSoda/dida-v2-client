from dida_v2_client.auth import resolve_session_token


def test_env_session_token_is_fallback(monkeypatch):
    monkeypatch.setenv("DIDA_SESSION_TOKEN", "TOKEN")
    assert resolve_session_token(headless=False) == "TOKEN"


def test_headless_is_default_strategy_without_cookie(monkeypatch):
    monkeypatch.delenv("DIDA_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("TICKTICK_SESSION_TOKEN", raising=False)
    calls = []

    def fake_headless(**kwargs):
        calls.append(kwargs)
        return "HEADLESS_TOKEN"

    assert resolve_session_token(headless_login=fake_headless) == "HEADLESS_TOKEN"
    assert calls and calls[0]["profile"] == "cn"
